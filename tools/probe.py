# One-off helper: find current Telegram usernames of news outlets (runs on Actions).
import re, requests
from bs4 import BeautifulSoup
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"
LINK = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_+]{4,40})", re.I)

def links(url):
    try:
        return sorted(set(LINK.findall(S.get(url, timeout=25).text)))
    except Exception as e:
        return ["ERR " + str(e)[:60]]

print("### links inside old channels (moved notices)")
for ch in ["channelkikar", "kikar_hashabbat", "jdn_news", "behadrei_harebim_bhol", "kikarm_musik"]:
    print(ch, "->", links("https://t.me/s/" + ch))

print("### links on outlet websites")
for site in ["https://www.kikar.co.il/", "https://www.jdn.co.il/", "https://ch10.co.il/", "https://www.kore.co.il/",
             "https://www.emess.co.il/", "https://www.bhol.co.il/", "https://www.hm-news.co.il/", "https://www.actualic.co.il/",
             "https://www.hamechadesh.co.il/", "https://www.kolhai.co.il/", "https://www.kikar.co.il/newsflash"]:
    print(site, "->", links(site))

def info(u):
    try:
        r = S.get("https://t.me/s/" + u, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        t = soup.select_one(".tgme_channel_info_header_title")
        times = [x["datetime"] for x in soup.select("a.tgme_widget_message_date time") if x.get("datetime")]
        subs = soup.select_one(".tgme_channel_info_counter .counter_value")
        return "{} | last={} | subs={}".format(t.get_text(strip=True) if t else None,
                                               max(times)[:16] if times else None, subs.get_text() if subs else None)
    except Exception as e:
        return "ERR " + str(e)[:60]

print("### candidate usernames")
for u in ["kikar", "kikarnews", "kikar_news", "kikarhashabat", "kikar_co_il", "kikarhashabbat", "kikarofficial", "kikar_official",
          "kikar1", "kikar_il", "KikarHashabbatNews", "kikar_hashabbat_news", "jdn", "jdnnews", "jdn_il", "JDN_News_il", "jdnisrael",
          "jdn_hadashot", "ch10news", "charedim_10", "haredim10news", "ch10_news", "kore_co_il", "korenews", "kolhai", "kolhai93",
          "emess", "emessnews", "hm_news", "hmnews", "actualic", "hamodia", "hamodia_news", "yated", "hamevaser",
          "kolbarama", "kol_barama", "bhol", "bholnews", "behadrei", "haredi_news", "charedi_news", "chadashot_charedi"]:
    print(u, "->", info(u))
