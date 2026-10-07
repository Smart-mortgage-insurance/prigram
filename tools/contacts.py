"""Finds how to reach the owner of each enabled channel: the channel description plus
contact details that recur in the post footers. Prints one JSON line per channel."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CFG = json.loads((Path(__file__).resolve().parent.parent / "scraper" / "config.json").read_text(encoding="utf-8"))
CHANNELS = sys.argv[1:] or [c["username"] for c in CFG["channels"] if c.get("enabled", True) and c.get("kind")]

PHONE = re.compile(r"(?<!\d)(?:\+?972[-\s]?|0)(?:5\d|[2-4]|7\d|[89])[-\s]?\d{3}[-\s]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
MENTION = re.compile(r"(?<![\w@.])@([A-Za-z]\w{4,31})")
TME = re.compile(r"(?:t\.me|telegram\.me)/(\+?[\w-]+)(?:/\d+)?", re.I)
WA = re.compile(r"wa\.me/\+?(\d{9,15})|whatsapp\.com/send/?\?[^\s\"]*?phone=\+?(\d{9,15})", re.I)


def tokens(node, own):
    """Contact tokens in one HTML node (visible text + link targets)."""
    text = node.get_text(" ")
    blob = text + " " + " ".join(a.get("href", "") for a in node.select("a[href]"))
    out = set()
    out.update("mail:" + m.lower() for m in EMAIL.findall(blob))
    out.update("tel:" + re.sub(r"\D", "", m) for m in PHONE.findall(text))
    out.update("tg:@" + m for m in MENTION.findall(text) if m.lower() != own)
    out.update("tg:" + m for m in TME.findall(blob) if m.lower() not in (own, "s", "share", "joinchat"))
    out.update("wa:" + (a or b) for a, b in WA.findall(blob))
    return out


def info(u):
    r = requests.get("https://t.me/s/" + u, headers=UA, timeout=25)
    soup = BeautifulSoup(r.text, "html.parser")
    msgs = soup.select(".tgme_widget_message_text")
    title = soup.select_one(".tgme_channel_info_header_title")
    subs = soup.select_one(".tgme_channel_info_counter .counter_value")
    desc = soup.select_one(".tgme_channel_info_description")
    own = u.lower()
    seen = Counter()
    for m in msgs:
        seen.update(tokens(m, own))
    need = max(3, len(msgs) // 4)
    return {
        "u": u,
        "title": title.get_text(strip=True) if title else "",
        "subs": subs.get_text() if subs else "",
        "posts": len(msgs),
        "desc": desc.get_text(" ", strip=True)[:400] if desc else "",
        "desc_contacts": sorted(tokens(desc, own)) if desc else [],
        "footer_contacts": {k: v for k, v in seen.most_common(12) if v >= need},
    }


for u in CHANNELS:
    try:
        print("CONTACT " + json.dumps(info(u), ensure_ascii=True))
    except Exception as exc:
        print("CONTACT " + json.dumps({"u": u, "error": type(exc).__name__}))
