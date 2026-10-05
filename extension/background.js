// נטגרם – בודק פעם בדקה אם עלו עדכונים חדשים ומקפיץ עליהם חלונית.
const SITE = "https://smart-mortgage-insurance.github.io/prigram/";
const ALARM = "prigram-poll";
const MAX_POPUPS = 3;      // מעבר לזה מוצגת חלונית אחת מסכמת
const KEEP_SEEN = 600;

async function jget(path) {
  const r = await fetch(SITE + path + "?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

const chName = (channels, u) => (channels[u] && channels[u].title) || u;
const snippet = (it) => (it.text || "").replace(/\s+/g, " ").trim().slice(0, 240) || "תמונה / סרטון חדש";

function notify(id, title, message) {
  chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/128.png",
    title,
    message,
    priority: 2,
  });
}

async function poll() {
  const st = await chrome.storage.local.get({ enabled: true, muted: [], seen: null, unread: 0 });
  let news, removed;
  try {
    [news, removed] = await Promise.all([jget("data/news.json"), jget("data/removed.json").catch(() => ({ posts: [] }))]);
  } catch (_) {
    return; // אין רשת כרגע – ננסה שוב בדקה הבאה
  }
  const gone = new Set(removed.posts || []);
  const items = (news.items || []).filter((i) => !gone.has(i.post));
  const channels = news.channels || {};
  await chrome.storage.local.set({ latest: items.slice(0, 20), channels });

  const ids = items.map((i) => i.post);
  if (!st.seen) {
    // הפעלה ראשונה: מסמנים את הקיים כנקרא, בלי להציף בחלוניות
    await chrome.storage.local.set({ seen: ids.slice(0, KEEP_SEEN) });
    return;
  }
  const seen = new Set(st.seen);
  const fresh = items.filter((i) => !seen.has(i.post));
  if (!fresh.length) return;
  await chrome.storage.local.set({ seen: ids.concat(st.seen.filter((p) => !ids.includes(p))).slice(0, KEEP_SEEN) });

  const muted = new Set(st.muted);
  const show = fresh.filter((i) => !muted.has(i.post.split("/")[0]));
  if (!st.enabled || !show.length) return;

  const unread = st.unread + show.length;
  await chrome.storage.local.set({ unread });
  chrome.action.setBadgeBackgroundColor({ color: "#4a726a" });
  chrome.action.setBadgeText({ text: unread > 99 ? "99+" : String(unread) });

  if (show.length <= MAX_POPUPS) {
    // מהישן לחדש, כדי שהחדש ביותר יהיה למעלה
    show.slice().reverse().forEach((it) => notify("post:" + it.post, chName(channels, it.post.split("/")[0]), snippet(it)));
  } else {
    const first = show[0];
    notify("many:" + Date.now(), show.length + " עדכונים חדשים בנטגרם",
      chName(channels, first.post.split("/")[0]) + ": " + snippet(first));
  }
}

async function openSite() {
  const tabs = await chrome.tabs.query({ url: SITE + "*" });
  if (tabs.length) {
    await chrome.tabs.update(tabs[0].id, { active: true });
    await chrome.windows.update(tabs[0].windowId, { focused: true });
    chrome.tabs.reload(tabs[0].id);
  } else {
    await chrome.tabs.create({ url: SITE });
  }
}

function schedule() {
  chrome.alarms.get(ALARM, (a) => { if (!a) chrome.alarms.create(ALARM, { periodInMinutes: 1 }); });
}

chrome.runtime.onInstalled.addListener(() => { schedule(); poll(); });
chrome.runtime.onStartup.addListener(() => { schedule(); poll(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === ALARM) poll(); });
chrome.notifications.onClicked.addListener((id) => { chrome.notifications.clear(id); openSite(); });
chrome.runtime.onMessage.addListener((m) => {
  if (m === "read") { chrome.storage.local.set({ unread: 0 }); chrome.action.setBadgeText({ text: "" }); }
  if (m === "open") openSite();
});
