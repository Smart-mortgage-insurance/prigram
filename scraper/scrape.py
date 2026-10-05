# -*- coding: utf-8 -*-
"""
נטגרם – mirrors public Telegram channels into a NetFree-reachable feed.

Transparent aggregator: every post is shown AS-IS, attributed to its source
channel, with a link to the original. We do not edit, rewrite or re-word posts
(that is what keeps the site a quoting platform rather than a publisher).

Runs on GitHub Actions (unfiltered egress) because NetFree blocks t.me and the
Telegram CDN. Media is downloaded into the repo (data/media/) so it loads for
NetFree users; every image passes a Gemini modesty filter first.
"""

import os
import re
import io
import json
import time
import base64
import hashlib
import mimetypes
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
NEWS_PATH = os.path.join(DATA_DIR, "news.json")
REMOVED_PATH = os.path.join(DATA_DIR, "removed.json")
CONFIG_PATH = os.path.join(HERE, "config.json")

os.makedirs(MEDIA_DIR, exist_ok=True)

with open(CONFIG_PATH, encoding="utf-8") as fh:
    CFG = json.load(fh)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# without a Gemini key, keep images anyway (NetFree filters images on the user's side)
UNFILTERED_OK = CFG["media_filter"].get("allow_without_gemini", False)
# Photos/videos in the channels mostly belong to press photographers and agencies.
# Re-hosting them needs a licence, so post media is off unless explicitly enabled.
MEDIA_ON = CFG["media_filter"].get("enabled", True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
})


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- #
# Telegram parsing
# --------------------------------------------------------------------------- #
BG_URL_RE = re.compile(r"background-image\s*:\s*url\(['\"]?(.*?)['\"]?\)", re.I)


def parse_views(s):
    s = (s or "").strip().upper().replace(",", "")
    try:
        if s.endswith("K"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1000000)
        return int(s)
    except ValueError:
        return None


def fetch_channel(username):
    """Return (channel_info, messages) for one public channel."""
    try:
        resp = SESSION.get("https://t.me/s/{}".format(username), timeout=30)
    except Exception as exc:
        log("  ! network error for @{}: {}".format(username, exc))
        return None, []
    if resp.status_code != 200:
        log("  ! @{} HTTP {}".format(username, resp.status_code))
        return None, []
    soup = BeautifulSoup(resp.text, "html.parser")

    info = {"username": username, "title": username, "avatar_src": None}
    t = soup.select_one(".tgme_channel_info_header_title")
    if t:
        info["title"] = t.get_text(" ", strip=True)
    av = soup.select_one(".tgme_page_photo_image img, .tgme_channel_info_header img")
    if av and av.get("src"):
        info["avatar_src"] = av["src"]
    return info, parse_messages(soup)


def parse_messages(soup):
    out = []
    for msg in soup.select("div.tgme_widget_message"):
        post_id = msg.get("data-post")  # "channel/1234"
        if not post_id:
            continue

        text = ""
        tnode = msg.select_one("div.tgme_widget_message_text")
        if tnode:
            for br in tnode.find_all("br"):
                br.replace_with("\n")
            text = tnode.get_text().strip()

        ts = None
        tm = msg.select_one("a.tgme_widget_message_date time")
        if tm and tm.get("datetime"):
            ts = tm["datetime"]

        views = None
        vn = msg.select_one(".tgme_widget_message_views")
        if vn:
            views = parse_views(vn.get_text())

        fwd = None
        fn = msg.select_one(".tgme_widget_message_forwarded_from_name")
        if fn:
            fwd = fn.get_text(" ", strip=True)

        media = []
        for ph in msg.select("a.tgme_widget_message_photo_wrap, "
                             "a.tgme_widget_message_link_preview_image, "
                             "i.link_preview_image"):
            m = BG_URL_RE.search(ph.get("style", ""))
            if m:
                media.append({"type": "image", "src": m.group(1)})
        for vid in msg.select("video.tgme_widget_message_video"):
            if vid.get("src"):
                media.append({"type": "video", "src": vid["src"], "poster": vid.get("poster")})
            elif vid.get("poster"):
                media.append({"type": "image", "src": vid["poster"]})
        for vthumb in msg.select("i.tgme_widget_message_video_thumb"):
            m = BG_URL_RE.search(vthumb.get("style", ""))
            if m and not any(x["type"] == "video" for x in media):
                media.append({"type": "image", "src": m.group(1)})

        if not text and not media:
            continue
        out.append({"post": post_id, "text": text, "ts": ts, "views": views,
                    "forwarded_from": fwd, "media": media})
    return out


# --------------------------------------------------------------------------- #
# Filtering (spam/ads only — the post itself is never rewritten)
# --------------------------------------------------------------------------- #
URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.I)
DROP_REGEX = [re.compile(p) for p in CFG["text_filter"].get("drop_regex", [])]


HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}")
FOOTER_RE = [re.compile(p) for p in CFG["text_filter"].get("strip_line_regex", [])]
# per-line leftovers: "| source >>", arrows pointing at a removed link, bare domains
TRAIL_RE = [re.compile(p) for p in CFG["text_filter"].get("strip_regex", [])]


def clean_text(text):
    # removed: raw links (Telegram is blocked in NetFree) and each channel's own
    # "join us / follow us" footer. The news text itself is never changed.
    for marker in CFG["text_filter"].get("cut_from", []):
        pos = text.find(marker)
        if pos != -1:
            text = text[:pos]
    text = URL_RE.sub("", text)
    text = HANDLE_RE.sub("", text)
    lines = []
    for ln in text.split("\n"):
        ln = ln.strip()
        for _ in range(3):  # repeat: stripping one tail can expose another
            for rx in TRAIL_RE:
                ln = rx.sub("", ln).strip()
        if not any(rx.search(ln) for rx in FOOTER_RE):
            lines.append(ln)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text_allowed(text):
    if len(re.sub(r"\W", "", text)) < CFG["text_filter"].get("min_letters", 12):
        return False  # "#", "שר החוץ" and similar fragments
    low = text.lower()
    if any(b.lower() in low for b in CFG["text_filter"].get("drop_if_contains", [])):
        return False
    return not any(rx.search(text) for rx in DROP_REGEX)


# --------------------------------------------------------------------------- #
# Media download + Gemini modesty filter
# --------------------------------------------------------------------------- #
EXT_BY_MIME = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
               "image/webp": ".webp", "image/gif": ".gif",
               "video/mp4": ".mp4", "video/webm": ".webm"}


def download(url, max_bytes):
    try:
        r = SESSION.get(url, timeout=45, stream=True)
        if r.status_code != 200:
            return None, None
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        buf = io.BytesIO()
        for chunk in r.iter_content(65536):
            buf.write(chunk)
            if buf.tell() > max_bytes:
                return None, None
        return buf.getvalue(), ctype
    except Exception as exc:
        log("    ! download failed: {}".format(exc))
        return None, None


def gemini_image_ok(img_bytes, mime):
    model = CFG["media_filter"].get("gemini_model", "gemini-2.5-flash")
    endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                "{}:generateContent?key={}".format(model, GEMINI_KEY))
    prompt = (
        "אתה מסנן תמונות לאתר המיועד לציבור חרדי עם אינטרנט מסונן (נטפרי). "
        "החזר JSON בלבד: {\"ok\": true/false}. "
        "ok=false אם מופיעות נשים או נערות, לבוש לא צנוע, תוכן אלים/מזעזע/דוחה, "
        "או כל דבר לא ראוי לציבור חרדי. ok=true לגברים, רבנים, נופים, מבנים, מסמכים, "
        "מפות, גרפיקת טקסט, חפצים ורכבים. בספק – false."
    )
    body = {"contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime or "image/jpeg",
                                 "data": base64.b64encode(img_bytes).decode()}}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 40,
                                 "responseMimeType": "application/json"}}
    try:
        r = requests.post(endpoint, json=body, timeout=45)
        if r.status_code != 200:
            log("    ! gemini HTTP {}: {}".format(r.status_code, r.text[:160]))
            return False
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r'"ok"\s*:\s*(true|false)', txt, re.I)
        return bool(m) and m.group(1).lower() == "true"
    except Exception as exc:
        log("    ! gemini error: {}".format(exc))
        return False  # fail safe


def save_media(key, data, ctype, default_ext):
    ext = EXT_BY_MIME.get(ctype) or mimetypes.guess_extension(ctype or "") or default_ext
    fname = hashlib.sha1(key.encode()).hexdigest()[:16] + ext
    fpath = os.path.join(MEDIA_DIR, fname)
    if not os.path.exists(fpath):
        with open(fpath, "wb") as out:
            out.write(data)
    return "data/media/" + fname


def process_media(post, media):
    """Download + filter; returns local media entries (images/videos that passed)."""
    if not MEDIA_ON or (not GEMINI_KEY and not UNFILTERED_OK):
        return []  # media switched off, or no filter available -> text only
    max_bytes = CFG["limits"]["max_media_bytes"]
    kept = []
    for m in media:
        if m["type"] == "video" and not CFG["media_filter"].get("allow_videos", True):
            continue
        data, ctype = download(m["src"], max_bytes)
        if not data:
            continue
        judge, jmime, pdata, pctype = data, ctype, None, None
        if m["type"] == "video":
            if not m.get("poster"):
                continue  # can't judge a video with no frame
            pdata, pctype = download(m["poster"], max_bytes)
            if not pdata:
                continue
            judge, jmime = pdata, pctype
        if GEMINI_KEY and not gemini_image_ok(judge, jmime):
            log("    - media rejected by filter")
            continue
        entry = {"type": m["type"],
                 "file": save_media(post + m["src"], data, ctype,
                                    ".mp4" if m["type"] == "video" else ".jpg")}
        if pdata:
            entry["poster"] = save_media(post + m["poster"], pdata, pctype, ".jpg")
        kept.append(entry)
    return kept


def process_avatar(info):
    """Channel logos are shown for attribution; still pass the modesty filter."""
    src = info.pop("avatar_src", None)
    if not src or not (GEMINI_KEY or UNFILTERED_OK):
        return None
    data, ctype = download(src, 2000000)
    if not data or (GEMINI_KEY and not gemini_image_ok(data, ctype)):
        return None
    return save_media("avatar:" + info["username"], data, ctype, ".jpg")


# --------------------------------------------------------------------------- #
# Merge + persist
# --------------------------------------------------------------------------- #
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def prune_media(items, channels):
    referenced = {os.path.basename(c["avatar"]) for c in channels.values() if c.get("avatar")}
    for it in items:
        for m in it.get("media", []):
            for key in ("file", "poster"):
                if m.get(key):
                    referenced.add(os.path.basename(m[key]))
    for fn in os.listdir(MEDIA_DIR):
        if fn != ".gitkeep" and fn not in referenced:
            try:
                os.remove(os.path.join(MEDIA_DIR, fn))
            except OSError:
                pass


def main():
    log("== נטגרם scraper ==  image filter:", "ON" if GEMINI_KEY else ("OFF (images kept, NetFree filters)" if UNFILTERED_OK else "OFF (text-only)"))
    news = load_json(NEWS_PATH, {"items": [], "channels": {}})
    removed = set(load_json(REMOVED_PATH, {"posts": []}).get("posts", []))
    enabled = [c for c in CFG["channels"] if c.get("enabled", True)]
    enabled_names = {c["username"] for c in enabled}
    # some channels mark every real news item with a fixed prefix ("הפרגוד:");
    # their sponsored posts come without it, so anything unprefixed is dropped
    prefixes = {c["username"]: c["require_prefix"] for c in enabled if c.get("require_prefix")}

    def channel_ok(post, raw):
        pre = prefixes.get(post.split("/")[0])
        return not pre or re.sub(r"^[\s‎‏*]+", "", raw or "").startswith(pre)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=CFG["limits"].get("max_age_days", 5))).isoformat()
    existing = {}
    for it in news.get("items", []):
        if (it.get("post") in removed or it.get("post", "").split("/")[0] not in enabled_names
                or (it.get("ts") or "") < cutoff):
            continue
        # re-apply the current filters, so filter changes also clean older posts
        it["text"] = clean_text(it.get("text", ""))
        if not MEDIA_ON:
            it["media"] = []  # also strips photos/videos already published
        if not channel_ok(it["post"], it["text"]):
            continue
        if it["text"] and not text_allowed(it["text"]):
            continue
        if not it["text"] and not it.get("media"):
            continue
        existing[it["post"]] = it
    channels = {k: v for k, v in news.get("channels", {}).items() if k in enabled_names}
    new_count = 0

    for ch in enabled:
        uname = ch["username"]
        log("-> @" + uname)
        info, msgs = fetch_channel(uname)
        if not msgs:
            log("   ! no public posts (wrong username / private / empty) - skipped")
            channels.pop(uname, None)
            continue
        if info:
            prev = channels.get(uname, {})
            avatar = prev.get("avatar") or process_avatar(info)
            info.pop("avatar_src", None)
            channels[uname] = {"title": ch.get("title") or info["title"],
                               "avatar": avatar}
        log("   {} messages".format(len(msgs)))

        for msg in msgs[-CFG["limits"]["max_messages_per_channel"]:]:
            post = msg["post"]
            if post in existing:
                if msg["views"] is not None:
                    existing[post]["views"] = msg["views"]  # keep view counts fresh
                continue
            if post in removed or (msg["ts"] or "") < cutoff:
                continue  # removed on request, or an old post (dead/moved channel)
            if not channel_ok(post, msg["text"]):
                log("   - dropped (sponsored: no channel prefix)")
                continue
            if msg["text"] and not text_allowed(msg["text"]):
                log("   - dropped (ad/spam)")
                continue
            text = clean_text(msg["text"])
            if not text and not msg["media"]:
                continue
            if text and not text_allowed(text):
                log("   - dropped (ad/spam)")
                continue
            media = process_media(post, msg["media"])
            if not text and not media:
                continue
            existing[post] = {
                "id": "p" + hashlib.sha1(post.encode()).hexdigest()[:12],
                "post": post,
                "ts": msg["ts"],
                "text": text,
                "views": msg["views"],
                "forwarded_from": msg["forwarded_from"],
                "media": media,
            }
            new_count += 1
        time.sleep(1)

    items = sorted(existing.values(), key=lambda x: x.get("ts") or "", reverse=True)
    # per-channel cap, so busy channels never push the quieter ones off the site
    per_ch, kept = CFG["limits"].get("max_items_per_channel", 20), {}
    capped = []
    for it in items:
        ch = it["post"].split("/")[0]
        if kept.get(ch, 0) < per_ch:
            kept[ch] = kept.get(ch, 0) + 1
            capped.append(it)
    items = capped[: CFG["limits"]["max_items"]]
    prune_media(items, channels)

    out = {"updated": datetime.now(timezone.utc).isoformat(),
           "channels": channels, "count": len(items), "items": items}
    with open(NEWS_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log("== done: {} new, {} total ==".format(new_count, len(items)))


if __name__ == "__main__":
    main()
