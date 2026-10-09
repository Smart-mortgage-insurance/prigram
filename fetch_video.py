"""Finds short live-action breastfeeding instruction videos (latch / positioning) from open sources and converts the best ones to MP4.
Sources: Wikimedia Commons, Global Health Media Project. Prints only titles, durations and URLs."""
import re, subprocess, sys, time, requests
UA = {"User-Agent": "NetgramVideoFetch/1.0 (https://github.com/Smart-mortgage-insurance/prigram; one-off download) python-requests"}
GOOD = re.compile(r"latch|attach|position|how to breastfeed|breastfeeding (technique|basics|tips)|hold", re.I)
BAD = re.compile(r"animat|cartoon|drawing|illustrat", re.I)
cands = []
for q in ["breastfeeding latch filetype:video", "breastfeeding attach baby filetype:video", "breastfeeding position filetype:video",
          "how to breastfeed filetype:video", "breastfeeding filetype:video", "lactation latch filetype:video"]:
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={"action": "query", "format": "json", "generator": "search", "gsrsearch": q,
                         "gsrnamespace": 6, "gsrlimit": 50, "prop": "videoinfo", "viprop": "url|metadata"}, headers=UA, timeout=30).json()
    except Exception as e:
        print("commons failed", type(e).__name__); continue
    for p in (r.get("query") or {}).get("pages", {}).values():
        vi = (p.get("videoinfo") or [{}])[0]
        meta = {m.get("name"): m.get("value") for m in (vi.get("metadata") or []) if isinstance(m, dict)}
        dur = float(meta.get("playtime_seconds") or meta.get("length") or 0)
        if vi.get("url") and 30 <= dur <= 900 and not BAD.search(p["title"]):
            cands.append(("commons", p["title"], dur, vi["url"]))
    time.sleep(1)
# Global Health Media Project: public download links on their breastfeeding pages
for page in ["https://globalhealthmedia.org/topic/breastfeeding/", "https://globalhealthmedia.org/videos/"]:
    try:
        html = requests.get(page, headers=UA, timeout=30).text
        print("ghmp page", page, len(html))
        for u in sorted(set(re.findall(r'https?://[^"\'\s]+\.mp4', html))):
            cands.append(("ghmp", u.rsplit("/", 1)[-1], 0, u))
        for u in sorted(set(re.findall(r'https?://globalhealthmedia\.org/videos/[^"\'\s#?]+', html)))[:40]:
            if re.search(r"breast|latch|attach|position|milk", u, re.I):
                h2 = requests.get(u, headers=UA, timeout=30).text
                for m in sorted(set(re.findall(r'https?://[^"\'\s]+\.mp4', h2))):
                    cands.append(("ghmp", u.rstrip("/").rsplit("/", 1)[-1] + " :: " + m.rsplit("/", 1)[-1], 0, m))
                vim = re.findall(r'player\.vimeo\.com/video/(\d+)', h2)
                if vim: cands.append(("ghmp-vimeo", u.rstrip("/").rsplit("/", 1)[-1], 0, "https://vimeo.com/" + vim[0]))
    except Exception as e:
        print("ghmp failed", type(e).__name__)
seen, uniq = set(), []
for c in cands:
    if c[3] not in seen: seen.add(c[3]); uniq.append(c)
uniq.sort(key=lambda c: (not GOOD.search(c[1]), c[0] != "ghmp", c[0] != "ghmp-vimeo", c[2] or 999))
print("candidates:", len(uniq))
for c in uniq[:40]: print("  %-10s | %4.0f s | %s | %s" % (c[0], c[2], c[1][:90], c[3][:120]))
saved = 0
for c in uniq:
    if saved >= 3: break
    if not GOOD.search(c[1]): continue
    out = "video%d.mp4" % (saved + 1)
    if c[0] == "ghmp-vimeo":
        rc = subprocess.run(["yt-dlp", "-f", "b[height<=720]/b", "--merge-output-format", "mp4", "-o", "raw.%(ext)s", c[3]]).returncode
        raw = next((f for f in __import__("os").listdir(".") if f.startswith("raw.")), None)
        if rc or not raw: print("vimeo failed", c[1]); continue
    else:
        raw = "raw"
        for attempt in range(4):
            with requests.get(c[3], headers=UA, timeout=300, stream=True) as d:
                if d.status_code == 200 and "video" in (d.headers.get("content-type") or ""):
                    with open(raw, "wb") as fh:
                        for chunk in d.iter_content(1 << 20): fh.write(chunk)
                    break
            time.sleep(15 * (attempt + 1))
        else:
            print("download failed", c[1]); continue
    rc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]).returncode
    for f in __import__("os").listdir("."):
        if f.startswith("raw"): __import__("os").remove(f)
    if rc: print("convert failed", c[1]); continue
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    saved += 1
    print("SAVED", out, dur, "|", c[0], "|", c[1][:100])
    open("sources.txt", "a", encoding="utf-8").write("%s\t%s\t%s\n" % (out, c[1], c[3]))
sys.exit(0 if saved else 1)
