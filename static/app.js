/* invoice_audit - browser app. Talks to server.py; no framework, so it loads fast and switches language instantly. */
const SITE = "https://receipt-audit-site.onrender.com";

const I18N = {
  en: {
    nav_sub: "Receipt matching agent", home: "Home", hero_eyebrow: "AI receipt assistant",
    hero_title: "Every card payment, <em>matched</em> to its receipt.",
    hero_text: "Connect your inbox, add your card statement and let the agent find, match and file every receipt. You only handle the few it cannot find.",
    chips: ["Gmail read-only", "Saved in your own Drive", "Log in Google Sheets", "Any language and currency", "Fortnox next"],
    step1: "Connect your inbox", google_hint: "Reads Gmail (read-only) and saves receipts in your own Google Drive.",
    signin: "Sign in with Google", switch: "Use another account", demo: "No account at hand? Try with sample data",
    demo_on: "Sample data mode", demo_sub: "Nothing is read or saved.", connected: "Connected", done: "Done",
    step2: "Add your card statement", upload_hint: "Any card or bank export: CSV, Excel or PDF. Mynt, Pleo, any bank.",
    drop_title: "Drop your statement here", drop_sub: "or click to choose a file", sample: "Use the sample Mynt export",
    reading: ["Reading your statement", "Finding the columns", "Collecting card purchases"],
    purchases: "{n} purchases", step3: "Run the agent", period: "Look for receipts from",
    periods: ["Statement period", "Last 24 hours", "Last 7 days"],
    nightly: "This is the job the agent runs every night. Run it now to see it work.", run: "Run agent now",
    how_eyebrow: "How it works", how_title: "What happens when you run it",
    flow: [["Fetch", "Fetches emails in the period, read-only."], ["Sort", "AI picks out receipts and invoices."],
           ["Read", "Reads email text, PDFs and scans."], ["Match", "Pairs each card payment with its receipt."],
           ["Search", "Looks again for anything missing."], ["Save", "Files in Drive and updates the log."]],
    privacy_1: "Email access is read-only.", privacy_2: "Receipts are stored in your own Google Drive.",
    privacy_3: "Disconnect at any time. Nothing stays on our side.", policy: "Privacy policy",
    run_eyebrow: "Agent at work", run_title: "Finding and matching your receipts", progress: "Progress",
    activity: "Activity", live: "Live",
    tips: ["Reading only. Nothing in your inbox is changed.", "Receipts in any language and currency are understood.",
           "Every match comes with a reason you can check.", "Missing receipts are searched for a second time.",
           "Receipts are saved in your own Google Drive."],
    stages: { search: ["Fetching emails", "Searching your inbox for the period"], triage: ["Identifying receipts", "Separating receipts from other email"],
              read: ["Reading receipts", "Merchant, date, amount and VAT"], match: ["Matching transactions", "Card payment to receipt"],
              hunt: ["Finding missing receipts", "A second, deeper search"], save: ["Saving", "Google Drive and receipt log"] },
    stage_short: { search: "Inbox", triage: "Sort", read: "Read", match: "Match", hunt: "Search", save: "Save", ai: "AI", done: "Done", error: "Error" },
    run_failed: "The run stopped", groq_title: "AI service (Groq) issue", try_again: "Try again", back: "Back",
    res_eyebrow: "Run complete", res_eyebrow_demo: "Sample run complete",
    headline: "{have} of {total} transactions have a receipt",
    res_todo: "{n} need your attention. Everything else is filed.", res_all: "Nothing to do. Every transaction has a receipt.",
    drive: "Open Drive folder", sheet: "Open receipt log", fortnox: "Send to Fortnox", next_phase: "Next phase",
    stats: { matched: "Matched", check: "To check", missing: "Missing", no_receipt: "No receipt" },
    todo: "Needs your attention", all_good: "All transactions have a receipt.",
    suggested: "Suggested receipt", confirm: "Yes, that's it", upload: "Upload receipt", upload_sub: "Image or PDF",
    no_receipt: "No receipt", saving: "Saving", status: { matched: "Matched", check: "Check", missing: "Missing", no_receipt: "No receipt" },
    connections: "Connections", google: "Google", sample_mode: "Sample data", not_connected: "Not connected",
    fortnox_sent: "{n} sent", show_all: "Show all", show_less: "Show less",
    tab_all: "All transactions", search: "Search", filter_all: "All",
    cols: ["Status", "Date", "Card text", "Amount", "Receipt", "Why", "By", "File"], open: "Open",
    orphans: "Receipts with no card transaction", orphans_hint: "Found in your inbox but not on this statement. Paid with another card?",
    restart: "New run", forget: "Disconnect and delete my data", forgotten: "Disconnected. Nothing is stored on our side.",
    fortnox_title: "Send to Fortnox", fortnox_text: "In the next phase, matched receipts go straight to your Fortnox inbox, ready for your accountant to book. Nothing to set up now.",
    fortnox_connect: "Connect Fortnox", close: "Close",
    flash: { google_ok: "Google connected.", fortnox_ok: "Fortnox connected.", denied: "Sign-in was cancelled.",
             expired: "The sign-in link expired. Please try again.", scopes: "Please allow both permissions (read Gmail, save files in Drive). Sign in again and tick both boxes." },
    boot: ["Starting the agent", "Connecting securely", "Waking up the server", "Almost there"],
    by: { rules: "Rules", LLM: "AI", "hunter agent": "AI search", owner: "You" },
  },
  sv: {
    nav_sub: "Agent för kvittomatchning", home: "Startsida", hero_eyebrow: "AI-kvittoassistent",
    hero_title: "Varje kortköp, <em>matchat</em> mot sitt kvitto.",
    hero_text: "Koppla din inkorg, lägg till kortutdraget och låt agenten hitta, matcha och arkivera varje kvitto. Du hanterar bara de få den inte hittar.",
    chips: ["Gmail endast läsning", "Sparas i din egen Drive", "Logg i Google Kalkylark", "Alla språk och valutor", "Fortnox nästa"],
    step1: "Koppla din inkorg", google_hint: "Läser Gmail (endast läsning) och sparar kvitton i din egen Google Drive.",
    signin: "Logga in med Google", switch: "Byt konto", demo: "Inget konto till hands? Testa med exempeldata",
    demo_on: "Exempeldata", demo_sub: "Inget läses eller sparas.", connected: "Kopplad", done: "Klart",
    step2: "Lägg till kortutdraget", upload_hint: "Valfri export från kort eller bank: CSV, Excel eller PDF.",
    drop_title: "Släpp utdraget här", drop_sub: "eller klicka för att välja fil", sample: "Använd exempel-export från Mynt",
    reading: ["Läser ditt utdrag", "Hittar kolumnerna", "Samlar kortköpen"],
    purchases: "{n} köp", step3: "Kör agenten", period: "Leta efter kvitton från",
    periods: ["Utdragets period", "Senaste dygnet", "Senaste 7 dagarna"],
    nightly: "Det här jobbet kör agenten varje natt. Kör nu för att se hur det fungerar.", run: "Kör agenten nu",
    how_eyebrow: "Så fungerar det", how_title: "Det här händer när du kör",
    flow: [["Hämta", "Hämtar mejl för perioden, endast läsning."], ["Sortera", "AI väljer ut kvitton och fakturor."],
           ["Läsa", "Läser mejltext, PDF:er och skannade kvitton."], ["Matcha", "Parar varje kortköp med sitt kvitto."],
           ["Söka", "Letar igen efter det som saknas."], ["Spara", "Arkiverar i Drive och uppdaterar loggen."]],
    privacy_1: "Mejlåtkomsten är endast läsning.", privacy_2: "Kvitton sparas i din egen Google Drive.",
    privacy_3: "Koppla från när du vill. Inget sparas hos oss.", policy: "Integritetspolicy",
    run_eyebrow: "Agenten arbetar", run_title: "Hittar och matchar dina kvitton", progress: "Förlopp",
    activity: "Aktivitet", live: "Live",
    tips: ["Endast läsning. Inget i din inkorg ändras.", "Kvitton på alla språk och valutor förstås.",
           "Varje matchning har en anledning du kan kontrollera.", "Saknade kvitton söks en andra gång.",
           "Kvitton sparas i din egen Google Drive."],
    stages: { search: ["Hämtar mejl", "Söker i inkorgen för perioden"], triage: ["Identifierar kvitton", "Skiljer kvitton från annan e-post"],
              read: ["Läser kvitton", "Butik, datum, belopp och moms"], match: ["Matchar transaktioner", "Kortköp mot kvitto"],
              hunt: ["Letar efter saknade kvitton", "En andra, djupare sökning"], save: ["Sparar", "Google Drive och kvittologg"] },
    stage_short: { search: "Inkorg", triage: "Sortera", read: "Läsa", match: "Matcha", hunt: "Söka", save: "Spara", ai: "AI", done: "Klart", error: "Fel" },
    run_failed: "Körningen stoppades", groq_title: "Problem hos AI-tjänsten (Groq)", try_again: "Försök igen", back: "Tillbaka",
    res_eyebrow: "Körning klar", res_eyebrow_demo: "Exempelkörning klar",
    headline: "{have} av {total} transaktioner har ett kvitto",
    res_todo: "{n} behöver din uppmärksamhet. Allt annat är arkiverat.", res_all: "Inget att göra. Alla transaktioner har kvitto.",
    drive: "Öppna Drive-mappen", sheet: "Öppna kvittologgen", fortnox: "Skicka till Fortnox", next_phase: "Nästa fas",
    stats: { matched: "Matchade", check: "Att kolla", missing: "Saknas", no_receipt: "Inget kvitto" },
    todo: "Behöver din uppmärksamhet", all_good: "Alla transaktioner har kvitto.",
    suggested: "Föreslaget kvitto", confirm: "Ja, stämmer", upload: "Ladda upp kvitto", upload_sub: "Bild eller PDF",
    no_receipt: "Inget kvitto", saving: "Sparar", status: { matched: "Matchad", check: "Kolla", missing: "Saknas", no_receipt: "Inget kvitto" },
    connections: "Kopplingar", google: "Google", sample_mode: "Exempeldata", not_connected: "Inte kopplad",
    fortnox_sent: "{n} skickade", show_all: "Visa alla", show_less: "Visa färre",
    tab_all: "Alla transaktioner", search: "Sök", filter_all: "Alla",
    cols: ["Status", "Datum", "Korttext", "Belopp", "Kvitto", "Varför", "Av", "Fil"], open: "Öppna",
    orphans: "Kvitton utan korttransaktion", orphans_hint: "Hittade i inkorgen men inte på utdraget. Betalt med ett annat kort?",
    restart: "Ny körning", forget: "Koppla från och radera min data", forgotten: "Frånkopplad. Inget sparas hos oss.",
    fortnox_title: "Skicka till Fortnox", fortnox_text: "I nästa fas skickas matchade kvitton direkt till din Fortnox-inkorg, redo för din redovisningskonsult. Inget att ställa in nu.",
    fortnox_connect: "Koppla Fortnox", close: "Stäng",
    flash: { google_ok: "Google kopplat.", fortnox_ok: "Fortnox kopplat.", denied: "Inloggningen avbröts.",
             expired: "Inloggningslänken har gått ut. Försök igen.", scopes: "Tillåt båda behörigheterna (läsa Gmail, spara filer i Drive). Logga in igen och kryssa i båda." },
    boot: ["Startar agenten", "Ansluter säkert", "Väcker servern", "Snart klart"],
    by: { rules: "Regler", LLM: "AI", "hunter agent": "AI-sökning", owner: "Du" },
  },
};
const STAGES = ["search", "triage", "read", "match", "hunt", "save"];

let lang = (() => { try { return localStorage.getItem("ia_lang") || "en"; } catch { return "en"; } })();
let T = I18N[lang];
let S = null;                  // last /api/state
let period = 0, filter = "all", query = "", logOpen = false;
let events = [], polling = null, runStart = 0, tipTimer = null;

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => o[k]);
const money = (a, c) => `${Number(a).toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${c || ""}`.trim();
const day = (d) => new Date(d + "T00:00:00").toLocaleDateString(lang === "sv" ? "sv-SE" : "en-GB", { day: "2-digit", month: "short", year: "numeric" });
const ICON = {
  drive: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>',
  sheet: '<svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 9h16M4 15h16M10 3v18" stroke="currentColor" stroke-width="1.8"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M4 12l16-8-6 16-2-7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  google: '<svg viewBox="0 0 24 24"><path fill="#EA4335" d="M12 10.2v3.9h5.4c-.2 1.3-1.6 3.8-5.4 3.8-3.2 0-5.9-2.7-5.9-6s2.7-6 5.9-6c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.7 3.3 14.6 2.4 12 2.4 6.8 2.4 2.6 6.6 2.6 11.9s4.2 9.5 9.4 9.5c5.4 0 9-3.8 9-9.2 0-.6-.1-1.1-.2-1.6H12z"/></svg>',
};

/* ---------------------------------------------------------------- api */
async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
const post = (path, body) => api(path, { method: "POST", ...(body instanceof FormData ? { body } :
  { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }) });

function toast(text, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = text;
  $("#toasts").append(el); setTimeout(() => el.remove(), 5000);
}

/* ---------------------------------------------------------------- language */
function setLang(l) {
  lang = l; T = I18N[l];
  try { localStorage.setItem("ia_lang", l); } catch {}
  document.documentElement.lang = l;
  document.querySelectorAll("#lang button").forEach((b) => b.classList.toggle("on", b.dataset.lang === l));
  document.querySelectorAll("[data-i18n]").forEach((el) => { const v = T[el.dataset.i18n]; if (typeof v === "string") el.textContent = v; });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = T[el.dataset.i18nHtml]; });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = T[el.dataset.i18nPh]; });
  $("#hero-chips").innerHTML = T.chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("");
  $("#flow").innerHTML = T.flow.map(([b, s], i) => `<li><div class="k">${i + 1}</div><b>${esc(b)}</b><span>${esc(s)}</span></li>`).join("");
  if (S) render();
  if (!$("#view-run").hidden) renderRun();
}

/* ---------------------------------------------------------------- rendering */
function show(view) {
  ["onboard", "run", "result"].forEach((v) => { $(`#view-${v}`).hidden = v !== view; });
  window.scrollTo({ top: 0 });
}

function render() {
  renderAccount();
  if (S.running) { show("run"); renderRun(); return; }
  if (S.result) { show("result"); renderResult(); return; }
  show("onboard"); renderOnboard();
}

function renderAccount() {
  const who = S.google.connected ? S.google.email : S.demo ? T.sample_mode : "";
  $("#account").innerHTML = who ? `<div class="account"><span class="avatar">${esc(who[0].toUpperCase())}</span><span>${esc(who)}</span></div>` : "";
}

function renderOnboard() {
  const ready = S.google.connected || S.demo;
  const b1 = $("#step1-body");
  if (S.google.connected) {
    b1.innerHTML = `<div class="connected"><span class="avatar">${esc(S.google.email[0].toUpperCase())}</span><div><b>${esc(S.google.email)}</b><small>${T.connected}</small></div></div>
      <a class="btn btn-ghost full" href="/auth/google">${T.switch}</a>`;
  } else if (S.demo) {
    b1.innerHTML = `<div class="connected"><div><b>${T.demo_on}</b><small>${T.demo_sub}</small></div></div>
      <a class="btn btn-dark full" href="/auth/google">${ICON.google}${T.signin}</a>`;
  } else {
    b1.innerHTML = `<a class="btn btn-dark btn-lg full" href="/auth/google">${ICON.google}${T.signin}</a>
      <button class="link" id="demo">${T.demo}</button>`;
    $("#demo").onclick = async () => { S = await post("/api/demo"); render(); };
  }
  $("#step1").classList.toggle("done", ready);
  $("#step1-tag").className = ready ? "tag ok" : "tag"; $("#step1-tag").textContent = ready ? T.done : "";
  $("#step2").classList.toggle("locked", !ready);
  $("#use-sample").disabled = !ready;
  const st = S.statement;
  $("#step2").classList.toggle("done", !!st);
  $("#step2-tag").className = st ? "tag ok" : "tag"; $("#step2-tag").textContent = st ? T.done : "";
  $("#statement-summary").innerHTML = st ? `<div class="summary"><div class="summary-head"><span>${esc(st.name)}</span><span>${fmt(T.purchases, { n: st.count })} · ${esc(st.first)} – ${esc(st.last)}</span></div>
    <table>${st.preview.map((t) => `<tr><td>${esc(t.date)}</td><td>${esc(t.merchant)}</td><td>${money(t.amount, t.currency)}</td></tr>`).join("")}</table></div>` : "";
  $("#step3").classList.toggle("locked", !st);
  $("#period").innerHTML = T.periods.map((p, i) => `<button data-p="${i}" class="${i === period ? "on" : ""}">${esc(p)}</button>`).join("");
  $("#period").querySelectorAll("button").forEach((b) => { b.disabled = !st; b.onclick = () => { period = +b.dataset.p; renderOnboard(); }; });
  $("#run").disabled = !st;
}

function renderRun() {
  const last = {};
  let reached = -1;
  events.forEach((e) => { const i = STAGES.indexOf(e.stage); if (i > reached) reached = i; last[e.stage] = true; });
  const finished = events.some((e) => e.stage === "done");
  $("#stepper").innerHTML = STAGES.map((s, i) => {
    const cls = finished || i < reached ? (last[s] ? "done" : "skipped") : i === reached ? "active" : "";
    const [title, sub] = T.stages[s];
    return `<li class="${cls}"><span class="dot"></span><div><b>${esc(title)}</b><small>${esc(sub)}</small></div></li>`;
  }).join("");
  const feed = $("#feed");
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
  feed.innerHTML = events.map(feedItem).join("");
  if (atBottom) feed.scrollTop = feed.scrollHeight;
  const err = S && S.error;
  $("#run-error").innerHTML = err ? `<div class="alert"><b>${esc(err.startsWith("Groq issue") ? T.groq_title : T.run_failed)}</b>${esc(err)}
    <div class="row"><button class="btn btn-primary" id="retry">${T.try_again}</button><button class="btn btn-ghost" id="back">${T.back}</button></div></div>` : "";
  if (err) {
    $("#retry").onclick = () => startRun();
    $("#back").onclick = async () => { S = await api("/api/state"); S.running = false; show("onboard"); renderOnboard(); };
  }
}

function feedItem(e) {
  return `<li class="${e.level}"><time>${esc(e.t)}</time><span class="st">${esc(T.stage_short[e.stage] || e.stage)}</span><span>${esc(e.text)}</span></li>`;
}

function renderResult() {
  const r = S.result, rows = r.rows;
  const counted = rows.filter((x) => x.status !== "no_receipt");
  const have = counted.filter((x) => x.status === "matched").length;
  const todo = rows.filter((x) => x.status === "missing" || x.status === "check");
  $("#res-eyebrow").textContent = `${S.demo ? T.res_eyebrow_demo : T.res_eyebrow} · ${S.statement ? `${S.statement.first} – ${S.statement.last}` : ""}`;
  $("#res-title").textContent = fmt(T.headline, { have, total: counted.length });
  $("#res-sub").textContent = todo.length ? fmt(T.res_todo, { n: todo.length }) : T.res_all;
  requestAnimationFrame(() => { $("#res-bar").style.width = `${(100 * have) / Math.max(counted.length, 1)}%`; });

  const links = r.folder ? `<a class="btn btn-light" href="${esc(r.folder)}" target="_blank" rel="noopener">${ICON.drive}${T.drive}</a>
     <a class="btn btn-light" href="${esc(r.sheet)}" target="_blank" rel="noopener">${ICON.sheet}${T.sheet}</a>` : "";
  $("#res-actions").innerHTML = `${links}<button class="btn btn-coral" id="fortnox-btn">${ICON.send}${T.fortnox}${S.fortnox.connected ? "" : ` <span class="badge">${T.next_phase}</span>`}</button>`;
  $("#fortnox-btn").onclick = sendFortnox;

  const colors = { matched: "var(--ok)", check: "var(--khaki-dark)", missing: "var(--bad)", no_receipt: "var(--muted)" };
  $("#stats").innerHTML = Object.keys(colors).map((k) => `<div class="stat" style="--c:${colors[k]}"><div class="n">${rows.filter((x) => x.status === k).length}</div><div class="l">${T.stats[k]}</div></div>`).join("");

  $("#todo-title").textContent = todo.length ? `${T.todo} (${todo.length})` : T.todo;
  $("#todo").innerHTML = todo.length ? todo.map(todoCard).join("") : `<div class="empty">${T.all_good}</div>`;
  todo.forEach(wireTodo);

  $("#connections").innerHTML = `<div class="conn"><div><b>${T.google}</b><small>${esc(S.google.email || "")}</small></div>${S.google.connected && !S.demo ? `<span class="pill matched">${T.connected}</span>` : `<span class="pill check">${T.sample_mode}</span>`}</div>
    <div class="conn"><div><b>Fortnox</b><small>${T.next_phase}</small></div>${S.fortnox.connected ? `<span class="pill matched">${fmt(T.fortnox_sent, { n: r.sent_to_fortnox })}</span>` : `<span class="pill no_receipt">${T.not_connected}</span>`}</div>`;
  renderResFeed();

  $("#filters").innerHTML = [["all", T.filter_all], ...Object.keys(T.status).map((k) => [k, T.status[k]])]
    .map(([k, l]) => `<button data-f="${k}" class="${filter === k ? "on" : ""}">${esc(l)} <span class="muted">${k === "all" ? rows.length : rows.filter((x) => x.status === k).length}</span></button>`).join("");
  $("#filters").querySelectorAll("button").forEach((b) => (b.onclick = () => { filter = b.dataset.f; renderResult(); }));
  renderTable();

  $("#orphans-card").hidden = !r.orphans.length;
  $("#orphans").innerHTML = r.orphans.map((o) => `<li><b>${esc(o.merchant)}</b>, ${day(o.date)}, ${money(o.amount, o.currency)}</li>`).join("");
  $("#forget").hidden = !S.google.connected;
}

function renderResFeed() {
  const list = (logOpen ? events : events.slice(-12)).slice().reverse();  // newest first
  $("#res-feed").innerHTML = list.map(feedItem).join("") || `<li class="muted">-</li>`;
  $("#log-toggle").textContent = logOpen ? T.show_less : T.show_all;
}

function renderTable() {
  const cols = T.cols, rows = S.result.rows.filter((x) => (filter === "all" || x.status === filter) &&
    (!query || `${x.merchant} ${x.receipt?.merchant || ""} ${x.amount}`.toLowerCase().includes(query)));
  $("#table").innerHTML = `<thead><tr>${cols.map((c, i) => `<th${i === 3 ? ' style="text-align:right"' : ""}>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((x) => {
    const rc = x.receipt;
    return `<tr><td><span class="pill ${x.status}">${T.status[x.status]}</span></td><td>${esc(x.date)}</td><td>${esc(x.merchant)}</td>
      <td class="num-col">${money(x.amount, x.currency)}</td><td>${rc ? `${esc(rc.merchant)}<div class="why">${money(rc.amount, rc.currency)}${rc.vat ? ` · ${esc(rc.tax_label || "VAT")} ${money(rc.vat, "")}` : ""}</div>` : ""}</td>
      <td class="why">${esc(x.reason || "")}</td><td>${esc(T.by[x.by] || x.by || "")}</td><td>${rc && rc.drive_link ? `<a href="${esc(rc.drive_link)}" target="_blank" rel="noopener">${T.open}</a>` : ""}</td></tr>`;
  }).join("")}</tbody>`;
}

function todoCard(x) {
  const rc = x.receipt;
  return `<div class="todo ${x.status}" id="todo-${x.tx_id}">
    <div class="todo-top"><div><b>${esc(x.merchant)}</b><small>${day(x.date)} · ${money(x.amount, x.currency)}</small></div><span class="pill ${x.status}">${T.status[x.status]}</span></div>
    ${x.status === "check" && rc ? `<div class="suggest">${T.suggested}: <b>${esc(rc.merchant)}</b>, ${day(rc.date)}, ${money(rc.amount, rc.currency)}${x.reason ? `<small>${esc(x.reason)}</small>` : ""}</div>` : ""}
    <div class="todo-actions">
      ${x.status === "check" ? `<button class="btn btn-ok" data-act="confirm">${T.confirm}</button>` : "<span></span>"}
      <label class="btn btn-ghost upload-btn"><input type="file" accept="image/*,.pdf,application/pdf">${T.upload}<small>${T.upload_sub}</small></label>
      <button class="btn btn-danger-ghost" data-act="no-receipt">${T.no_receipt}</button>
    </div>
    <div class="busy"><span class="spin"></span>${T.saving}</div>
  </div>`;
}

function wireTodo(x) {
  const card = $(`#todo-${x.tx_id}`);
  const act = async (path, body) => {
    card.classList.add("loading");
    try { S = await post(`/api/tx/${encodeURIComponent(x.tx_id)}/${path}`, body); renderResult(); }
    catch (e) { card.classList.remove("loading"); toast(e.message, "error"); }
  };
  card.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(b.dataset.act)));
  const upload = (file) => { if (!file) return; const fd = new FormData(); fd.append("file", file); act("upload", fd); };
  card.querySelector("input[type=file]").onchange = (e) => upload(e.target.files[0]);
  card.ondragover = (e) => { e.preventDefault(); card.classList.add("over"); };
  card.ondragleave = () => card.classList.remove("over");
  card.ondrop = (e) => { e.preventDefault(); card.classList.remove("over"); upload(e.dataTransfer.files[0]); };
}

/* ---------------------------------------------------------------- actions */
async function uploadStatement(file, sample) {
  const drop = $("#drop");
  drop.classList.add("busy");
  let i = 0; $("#drop-busy-msg").textContent = T.reading[0];
  const t = setInterval(() => { i = (i + 1) % T.reading.length; $("#drop-busy-msg").textContent = T.reading[i]; }, 1500);
  const fd = new FormData();
  if (sample) fd.append("sample", "1"); else fd.append("file", file);
  try { S = await post("/api/statement", fd); renderOnboard(); }
  catch (e) { toast(e.message, "error"); }
  finally { clearInterval(t); drop.classList.remove("busy"); $("#statement-file").value = ""; }
}

async function startRun() {
  try { await post("/api/run", { period }); }
  catch (e) { toast(e.message, "error"); return; }
  events = []; S.running = true; S.error = "";
  show("run"); renderRun(); pollRun();
}

function pollRun() {
  runStart = runStart || Date.now();
  clearInterval(tipTimer);
  let ticks = 0; $("#run-tip").textContent = T.tips[0];
  tipTimer = setInterval(() => {
    ticks++;
    if (ticks % 4 === 0) $("#run-tip").textContent = T.tips[(ticks / 4) % T.tips.length];
    const s = Math.floor((Date.now() - runStart) / 1000);
    $("#run-elapsed").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  clearTimeout(polling);
  const tick = async () => {
    try {
      const r = await api(`/api/run?since=${events.length}`);
      events.push(...r.events);
      if (r.running) { renderRun(); polling = setTimeout(tick, 900); return; }
      clearInterval(tipTimer); runStart = 0;
      S = r.state;
      if (S.error) { show("run"); renderRun(); return; }
      render();
    } catch { polling = setTimeout(tick, 2500); }
  };
  tick();
}

async function sendFortnox() {
  if (S.fortnox.connected) {
    try { S = await post("/api/fortnox/send"); renderResult(); toast(fmt(T.fortnox_sent, { n: S.result.sent_to_fortnox }), "ok"); }
    catch (e) { toast(e.message, "error"); }
    return;
  }
  const m = $("#modal");
  m.innerHTML = `<div class="modal-box"><h3>${T.fortnox_title} <span class="badge">${T.next_phase}</span></h3><p>${T.fortnox_text}</p>
    <div class="modal-actions">${S.fortnox.configured && S.google.connected && !S.demo ? `<a class="btn btn-coral" href="/auth/fortnox">${T.fortnox_connect}</a>` : ""}<button class="btn btn-ghost" id="modal-close">${T.close}</button></div></div>`;
  m.hidden = false;
  $("#modal-close").onclick = () => (m.hidden = true);
  m.onclick = (e) => { if (e.target === m) m.hidden = true; };
}

/* ---------------------------------------------------------------- boot */
function wire() {
  document.querySelectorAll("#lang button").forEach((b) => (b.onclick = () => setLang(b.dataset.lang)));
  $("#statement-file").onchange = (e) => e.target.files[0] && uploadStatement(e.target.files[0]);
  const drop = $("#drop");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) uploadStatement(e.dataTransfer.files[0]); };
  $("#use-sample").onclick = () => uploadStatement(null, true);
  $("#run").onclick = startRun;
  $("#search").oninput = (e) => { query = e.target.value.toLowerCase(); renderTable(); };
  $("#log-toggle").onclick = () => { logOpen = !logOpen; renderResFeed(); };
  $("#restart").onclick = async () => { S = await post("/api/restart"); events = []; render(); };
  $("#forget").onclick = async () => { await post("/api/disconnect"); toast(T.forgotten, "ok"); S = await api("/api/state"); events = []; render(); };
  $("#privacy-link").href = `${SITE}/privacy.html`;
  $("#home-link").href = SITE;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });
}

async function boot() {
  let i = 0;
  const msg = setInterval(() => { i = (i + 1) % T.boot.length; $("#boot-msg").textContent = T.boot[i]; }, 1400);
  $("#boot-msg").textContent = T.boot[0];
  setLang(lang); wire();
  for (let attempt = 0; ; attempt++) {
    try { S = await api("/api/state"); break; }
    catch { await new Promise((r) => setTimeout(r, Math.min(1000 + attempt * 500, 4000))); }
  }
  clearInterval(msg);
  if (S.flash) {
    const [key, detail] = S.flash.split(/:(.*)/s);
    toast(key === "failed" ? detail : T.flash[key] || key, key.endsWith("_ok") ? "ok" : key === "failed" ? "error" : "");
  }
  if (S.running || S.result) events = (await api("/api/log")).events;
  render();
  if (S.running) pollRun();
  $("#boot").classList.add("hide");
  setTimeout(() => $("#boot").remove(), 400);
}
boot();
