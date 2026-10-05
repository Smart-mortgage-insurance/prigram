const SITE = "https://smart-mortgage-insurance.github.io/prigram/";
const $ = (id) => document.getElementById(id);
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" }) : "");

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

async function draw() {
  const st = await chrome.storage.local.get({ enabled: true, muted: [], latest: [], channels: {} });
  const name = (u) => (st.channels[u] && st.channels[u].title) || u;
  $("enabled").checked = st.enabled;

  const list = $("list");
  list.textContent = "";
  if (!st.latest.length) list.append(el("div", "empty", "עדיין אין עדכונים להצגה."));
  st.latest.forEach((it) => {
    const u = it.post.split("/")[0];
    const box = el("div", "it");
    const head = el("div", "h");
    const mute = el("button", "m", st.muted.includes(u) ? "🔕" : "🔔");
    mute.title = st.muted.includes(u) ? "הערוץ מושתק – לחצו להחזרת ההתראות" : "השתקת התראות מהערוץ הזה";
    mute.addEventListener("click", async (e) => {
      e.stopPropagation();
      const muted = st.muted.includes(u) ? st.muted.filter((m) => m !== u) : st.muted.concat(u);
      await chrome.storage.local.set({ muted });
      draw();
    });
    head.append(el("span", "n", name(u)), el("span", "t", hhmm(it.ts)), mute);
    box.append(head, el("div", "x", it.text || "תמונה / סרטון"));
    box.addEventListener("click", () => chrome.runtime.sendMessage("open"));
    list.append(box);
  });

  const m = $("muted");
  m.textContent = "";
  if (st.muted.length) {
    m.append("ערוצים מושתקים: ");
    st.muted.forEach((u) => {
      const b = el("button", "", name(u) + " ✕");
      b.addEventListener("click", async () => {
        await chrome.storage.local.set({ muted: st.muted.filter((x) => x !== u) });
        draw();
      });
      m.append(b);
    });
  }
}

$("enabled").addEventListener("change", (e) => chrome.storage.local.set({ enabled: e.target.checked }));
$("open").addEventListener("click", () => chrome.runtime.sendMessage("open"));
$("msg").addEventListener("click", () => chrome.tabs.create({ url: SITE + "#msg" }));

chrome.runtime.sendMessage("read");
draw();
