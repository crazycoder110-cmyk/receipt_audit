"""invoice_audit - Streamlit UI. Run: streamlit run app.py"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import secrets
import time
from html import escape as esc

import requests
import streamlit as st
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow

load_dotenv(".env")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # Google adds openid/email aliases to granted scopes


def cfg(key: str, default: str | None = None) -> str | None:
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


# Streamlit Cloud keeps keys in st.secrets; the agent modules read os.environ (at import time).
for key in ("GROQ_MODEL", "GROQ_FAST_MODEL", "GROQ_VISION_MODEL", "GROQ_TPM", "GROQ_RPM", "REDIRECT_URI",
            "FORTNOX_CLIENT_ID", "FORTNOX_CLIENT_SECRET", "FORTNOX_REDIRECT_URI"):
    if cfg(key):
        os.environ[key] = str(cfg(key))

import agent  # noqa: E402
import fortnox  # noqa: E402
import tools  # noqa: E402

st.set_page_config(page_title="invoice_audit", layout="wide")

TEXT = {
    "English": {
        "nav": "Receipt matching agent",
        "hero_eyebrow": "AI receipt assistant",
        "hero_title": "Every card payment, matched to its receipt.",
        "hero_text": "Connect your inbox, add your card statement and let the agent find, match and file every "
                     "receipt. You only handle the few it cannot find.",
        "chips": ["Gmail read-only", "Saved in your own Drive", "Log in Google Sheets", "Fortnox ready",
                  "Any language and currency"],
        "step": "Step", "optional": "optional", "done_tag": "Done",
        "step1": "Connect your accounts",
        "google": "Google", "google_hint": "Reads Gmail (read-only) and saves receipts in your own Drive.",
        "signin": "Sign in with Google", "switch": "Use another account", "connected": "Connected",
        "demo": "No account at hand? Try with sample data", "demo_on": "Sample data mode. Nothing is read or saved.",
        "fortnox": "Fortnox", "fortnox_hint": "Matched receipts go to your Fortnox inbox, ready to book.",
        "fortnox_connect": "Connect Fortnox", "fortnox_on": "Connected", "fortnox_off": "Not set up on this server",
        "fortnox_demo": "Needs a Google account", "not_connected": "Not connected",
        "step2": "Add your card statement", "upload": "Any card or bank export: CSV, Excel or PDF",
        "sample": "Use the sample Mynt export", "loaded": "{n} purchases, {a} to {b}", "reading": "Reading statement...",
        "step3": "Run the agent", "period": "Look for receipts from",
        "periods": ["The statement period", "Last 24 hours", "Last 7 days"],
        "run": "Run agent now", "nightly": "This is the job the agent runs every night.",
        "running": "Agent is working...", "done": "Done",
        "how_title": "What happens when you run it",
        "flow": [("Search", "Looks through your inbox for the period, read-only."),
                 ("Sort", "AI picks out receipts and invoices in any language."),
                 ("Read", "Reads email text, PDF invoices and scanned receipts."),
                 ("Match", "Pairs each card payment with its receipt and says why."),
                 ("Hunt", "Searches again for anything still missing."),
                 ("File", "Saves to Drive, logs to Sheets, sends to Fortnox.")],
        "graph": "Show the agent graph",
        "privacy_title": "Your data", "policy": "Privacy policy", "terms": "Terms of service",
        "privacy": ["Email access is read-only. Nothing is sent, changed or deleted.",
                    "Receipts are stored in your own Google Drive.",
                    "Disconnect at any time. Nothing stays on our side."],
        "result_eyebrow": "Run complete",
        "headline": "{have} of {total} transactions have a receipt",
        "result_todo": "{n} need your attention. Everything else is filed.",
        "allgood": "Nothing to do. Every transaction has a receipt.",
        "m_matched": "Matched", "m_check": "To check", "m_missing": "Missing", "m_none": "No receipt",
        "drive": "Open Drive folder", "sheet": "Open receipt log",
        "fortnox_sent": "{n} receipts sent to Fortnox",
        "todo": "Needs your attention", "connections": "Connections", "sample_mode": "Sample data",
        "suggest": "Suggested receipt: **{m}**, {d}, {a}", "why": "Reason: {r}",
        "confirm": "Yes, that's it", "photo": "Add photo", "photo_hint": "Take or upload a photo of the receipt",
        "noreceipt": "No receipt", "missing": "Missing", "check": "Check",
        "tab_all": "All transactions", "tab_orphans": "Unmatched receipts", "tab_log": "Agent log",
        "tab_how": "How it works", "orphans_hint": "Receipts with no card transaction. Paid with another card?",
        "none": "None.", "restart": "Start over", "forget": "Disconnect and delete my data",
        "forgotten": "Disconnected. Nothing is stored on our side.", "saving": "Saving...",
        "no_google": "Google sign-in is not configured (GOOGLE_CLIENT_ID / SECRET).",
        "no_key": "GROQ_API_KEY is missing.", "bad_file": "Could not read this file: {e}",
        "denied": "Sign-in was cancelled.", "expired": "The sign-in link expired. Please try again.",
        "scopes": "Please allow both permissions (read Gmail, save files in Drive). Sign in again and tick both boxes.",
        "failed": "Sign-in failed: {e}", "fortnox_ok": "Fortnox connected.",
        "status": {"matched": "Matched", "check": "Check", "missing": "Missing", "no_receipt": "No receipt"},
        "cols": ["Status", "Date", "Card text", "Amount", "Receipt", "Why", "By", "File"],
    },
    "Svenska": {
        "nav": "Agent för kvittomatchning",
        "hero_eyebrow": "AI-kvittoassistent",
        "hero_title": "Varje kortköp, matchat mot sitt kvitto.",
        "hero_text": "Koppla din inkorg, lägg till kortutdraget och låt agenten hitta, matcha och arkivera varje "
                     "kvitto. Du hanterar bara de få den inte hittar.",
        "chips": ["Gmail endast läsning", "Sparas i din egen Drive", "Logg i Google Kalkylark", "Redo för Fortnox",
                  "Alla språk och valutor"],
        "step": "Steg", "optional": "valfritt", "done_tag": "Klart",
        "step1": "Koppla dina konton",
        "google": "Google", "google_hint": "Läser Gmail (endast läsning) och sparar kvitton i din egen Drive.",
        "signin": "Logga in med Google", "switch": "Byt konto", "connected": "Kopplad",
        "demo": "Inget konto till hands? Testa med exempeldata",
        "demo_on": "Exempeldata. Inget läses eller sparas.",
        "fortnox": "Fortnox", "fortnox_hint": "Matchade kvitton hamnar i din Fortnox-inkorg, redo att bokföras.",
        "fortnox_connect": "Koppla Fortnox", "fortnox_on": "Kopplad", "fortnox_off": "Inte konfigurerat på servern",
        "fortnox_demo": "Kräver ett Google-konto", "not_connected": "Inte kopplad",
        "step2": "Lägg till kortutdraget", "upload": "Valfri export från kort eller bank: CSV, Excel eller PDF",
        "sample": "Använd exempel-export från Mynt", "loaded": "{n} köp, {a} till {b}", "reading": "Läser utdraget...",
        "step3": "Kör agenten", "period": "Leta efter kvitton från",
        "periods": ["Utdragets period", "Senaste dygnet", "Senaste 7 dagarna"],
        "run": "Kör agenten nu", "nightly": "Det här jobbet kör agenten varje natt.",
        "running": "Agenten arbetar...", "done": "Klart",
        "how_title": "Det här händer när du kör",
        "flow": [("Söka", "Går igenom inkorgen för perioden, endast läsning."),
                 ("Sortera", "AI väljer ut kvitton och fakturor på alla språk."),
                 ("Läsa", "Läser mejltext, PDF-fakturor och skannade kvitton."),
                 ("Matcha", "Parar varje kortköp med sitt kvitto och förklarar varför."),
                 ("Leta", "Söker igen efter det som fortfarande saknas."),
                 ("Arkivera", "Sparar i Drive, loggar i Kalkylark, skickar till Fortnox.")],
        "graph": "Visa agentens graf",
        "privacy_title": "Din data", "policy": "Integritetspolicy", "terms": "Användarvillkor",
        "privacy": ["Mejlåtkomsten är endast läsning. Inget skickas, ändras eller raderas.",
                    "Kvitton sparas i din egen Google Drive.",
                    "Koppla från när du vill. Inget sparas hos oss."],
        "result_eyebrow": "Körning klar",
        "headline": "{have} av {total} transaktioner har ett kvitto",
        "result_todo": "{n} behöver din uppmärksamhet. Allt annat är arkiverat.",
        "allgood": "Inget att göra. Alla transaktioner har kvitto.",
        "m_matched": "Matchade", "m_check": "Att kolla", "m_missing": "Saknas", "m_none": "Inget kvitto",
        "drive": "Öppna Drive-mappen", "sheet": "Öppna kvittologgen",
        "fortnox_sent": "{n} kvitton skickade till Fortnox",
        "todo": "Behöver din uppmärksamhet", "connections": "Kopplingar", "sample_mode": "Exempeldata",
        "suggest": "Föreslaget kvitto: **{m}**, {d}, {a}", "why": "Anledning: {r}",
        "confirm": "Ja, stämmer", "photo": "Lägg till foto", "photo_hint": "Fota eller ladda upp kvittot",
        "noreceipt": "Inget kvitto", "missing": "Saknas", "check": "Kolla",
        "tab_all": "Alla transaktioner", "tab_orphans": "Omatchade kvitton", "tab_log": "Agentlogg",
        "tab_how": "Så fungerar det", "orphans_hint": "Kvitton utan korttransaktion. Betalt med ett annat kort?",
        "none": "Inga.", "restart": "Börja om", "forget": "Koppla från och radera min data",
        "forgotten": "Frånkopplad. Inget sparas hos oss.", "saving": "Sparar...",
        "no_google": "Google-inloggning är inte konfigurerad (GOOGLE_CLIENT_ID / SECRET).",
        "no_key": "GROQ_API_KEY saknas.", "bad_file": "Kunde inte läsa filen: {e}",
        "denied": "Inloggningen avbröts.", "expired": "Inloggningslänken har gått ut. Försök igen.",
        "scopes": "Tillåt båda behörigheterna (läsa Gmail, spara filer i Drive). Logga in igen och kryssa i båda.",
        "failed": "Inloggningen misslyckades: {e}", "fortnox_ok": "Fortnox kopplat.",
        "status": {"matched": "Matchad", "check": "Kolla", "missing": "Saknas", "no_receipt": "Inget kvitto"},
        "cols": ["Status", "Datum", "Korttext", "Belopp", "Kvitto", "Varför", "Av", "Fil"],
    },
}

st.markdown("""<style>
:root {--ink:#0F172A; --muted:#64748B; --line:#E3E6EF; --brand:#4F46E5; --brand2:#7C3AED;
       --ok:#16A34A; --warn:#D97706; --bad:#DC2626; --card:#FFFFFF;}
.block-container {max-width: 1240px; padding: 1.2rem 2rem 4rem;}
header[data-testid="stHeader"] {background: transparent;}
.nav {display:flex; align-items:center; gap:.75rem;}
.logo {width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center;
       background:linear-gradient(135deg,var(--brand),var(--brand2)); color:#fff; font-weight:800; font-size:.9rem;
       box-shadow:0 8px 18px -6px rgba(79,70,229,.6);}
.nav-name {font-weight:800; font-size:1.15rem; letter-spacing:-.02em; color:var(--ink); line-height:1.1;}
.nav-sub {color:var(--muted); font-size:.8rem;}
.hero {position:relative; overflow:hidden; border-radius:22px; padding:2.4rem 2.6rem; margin:.9rem 0 1.6rem;
       color:#fff; background:linear-gradient(120deg,#312E81 0%,#4F46E5 48%,#7C3AED 100%);
       box-shadow:0 24px 48px -24px rgba(79,70,229,.7);}
.hero:before {content:""; position:absolute; right:-90px; top:-110px; width:360px; height:360px; border-radius:50%;
       background:radial-gradient(circle,rgba(255,255,255,.22),transparent 70%);}
.hero:after {content:""; position:absolute; right:140px; bottom:-140px; width:260px; height:260px; border-radius:50%;
       background:radial-gradient(circle,rgba(167,139,250,.45),transparent 70%);}
.hero .eyebrow {color:#C7D2FE;}
.hero h1 {color:#fff; font-size:2.35rem; font-weight:800; letter-spacing:-.03em; line-height:1.15;
          margin:.35rem 0 .7rem; padding:0;}
.hero p {color:#E0E7FF; font-size:1.02rem; max-width:660px; margin:0;}
.chips {display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1.3rem; position:relative; z-index:1;}
.chip {background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.28); color:#fff; border-radius:999px;
       padding:.32rem .85rem; font-size:.8rem; font-weight:500;}
.hero-actions {display:flex; gap:.6rem; margin-top:1.5rem; flex-wrap:wrap; position:relative; z-index:1;}
.hbtn {display:inline-block; padding:.65rem 1.2rem; border-radius:10px; font-weight:600; font-size:.9rem;
       text-decoration:none !important;}
.hbtn.light {background:#fff; color:#4338CA !important;}
.hbtn.ghost {background:rgba(255,255,255,.12); color:#fff !important; border:1px solid rgba(255,255,255,.4);}
.bar {height:10px; background:rgba(255,255,255,.22); border-radius:999px; margin-top:1.2rem; max-width:580px;
      overflow:hidden;}
.bar > div {height:100%; background:linear-gradient(90deg,#34D399,#A7F3D0); border-radius:999px;}
.stats {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1rem; margin:0 0 1.6rem;}
.stat {background:var(--card); border:1px solid var(--line); border-top:4px solid var(--c); border-radius:16px;
       padding:1.05rem 1.25rem; box-shadow:0 1px 3px rgba(15,23,42,.05);}
.stat .n {font-size:2.1rem; font-weight:800; color:var(--c); line-height:1.1;}
.stat .l {color:var(--muted); font-size:.85rem; font-weight:600; margin-top:.25rem;}
[class*="st-key-card"] {background:var(--card); border:1px solid var(--line); border-radius:18px;
       padding:1.35rem 1.45rem 1.25rem; box-shadow:0 1px 3px rgba(15,23,42,.05), 0 10px 30px -22px rgba(15,23,42,.25);}
[class*="st-key-card_check"] {border-left:5px solid var(--warn);}
[class*="st-key-card_missing"] {border-left:5px solid var(--bad);}
.eyebrow {font-size:.72rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase; color:var(--brand);}
.title {font-size:1.12rem; font-weight:700; color:var(--ink); margin:.1rem 0 .1rem;}
.section {font-size:1.2rem; font-weight:800; color:var(--ink); letter-spacing:-.01em; margin:.2rem 0 .8rem;}
.muted {color:var(--muted); font-size:.9rem;}
.label {font-weight:700; color:var(--ink);}
.step-head {display:flex; align-items:center; gap:.7rem; margin-bottom:.3rem;}
.num {width:32px; height:32px; flex:none; border-radius:50%; display:inline-flex; align-items:center;
      justify-content:center; font-weight:700; font-size:.85rem; color:#fff;
      background:linear-gradient(135deg,var(--brand),var(--brand2));}
.num.done {background:var(--ok);}
.pill {display:inline-block; padding:.22rem .7rem; border-radius:999px; font-size:.76rem; font-weight:700;}
.pill.ok {background:#DCFCE7; color:#15803D;} .pill.warn {background:#FEF3C7; color:#B45309;}
.pill.bad {background:#FEE2E2; color:#B91C1C;} .pill.info {background:#EEF2FF; color:#4338CA;}
.pill.gray {background:#F1F5F9; color:#475569;}
.flow {list-style:none; padding:0; margin:.6rem 0 0;}
.flow li {display:flex; gap:.85rem; align-items:flex-start; padding:.5rem 0; border-bottom:1px dashed var(--line);}
.flow li:last-child {border-bottom:0;}
.flow .k {width:26px; height:26px; flex:none; border-radius:8px; background:#EEF2FF; color:var(--brand);
          font-weight:700; font-size:.8rem; display:flex; align-items:center; justify-content:center;}
.flow b {display:block; color:var(--ink); font-size:.93rem;}
.flow span {display:block; color:var(--muted); font-size:.86rem; line-height:1.45;}
.sep {height:1px; background:var(--line); margin:.1rem 0 .3rem;}
.plist {margin:.5rem 0 0; padding-left:1.1rem; color:var(--muted); font-size:.88rem;}
.plist li {margin:.3rem 0;}
.conn {display:flex; justify-content:space-between; align-items:center; padding:.55rem 0;
       border-bottom:1px solid var(--line);}
.conn:last-child {border-bottom:0;}
button[data-testid="stBaseButton-primary"], a[data-testid="stBaseLinkButton-primary"] {
       background:linear-gradient(135deg,#4F46E5,#7C3AED) !important; border:0 !important; color:#fff !important;
       font-weight:600 !important; box-shadow:0 8px 16px -8px rgba(79,70,229,.7);
       transition:transform .08s ease, box-shadow .15s ease;}
button[data-testid="stBaseButton-primary"]:hover, a[data-testid="stBaseLinkButton-primary"]:hover {
       transform:translateY(-1px); box-shadow:0 12px 22px -10px rgba(79,70,229,.8);}
button[data-testid="stBaseButton-primary"]:disabled {opacity:.45; box-shadow:none;}
button[data-testid="stBaseButton-secondary"], a[data-testid="stBaseLinkButton-secondary"],
div[data-testid="stPopover"] button {background:#fff !important; border:1px solid #C7D2FE !important;
       color:#4338CA !important; font-weight:600 !important;}
button[data-testid="stBaseButton-secondary"]:hover, a[data-testid="stBaseLinkButton-secondary"]:hover,
div[data-testid="stPopover"] button:hover {background:#EEF2FF !important; border-color:#818CF8 !important;}
button[data-testid="stBaseButton-tertiary"] {color:#4F46E5 !important; font-weight:600 !important;}
[class*="st-key-ok_"] button {background:linear-gradient(135deg,#16A34A,#22C55E) !important;
       box-shadow:0 8px 16px -8px rgba(22,163,74,.7);}
[class*="st-key-no_"] button, [class*="st-key-forget"] button {border-color:#FECACA !important;
       color:#B91C1C !important;}
[class*="st-key-no_"] button:hover, [class*="st-key-forget"] button:hover {background:#FEF2F2 !important;}
div.stButton button, div[data-testid="stPopover"] button, a[data-testid^="stBaseLinkButton"] {width:100%;
       min-height:2.6rem;}
button[data-baseweb="tab"] p {font-weight:600;}
[data-testid="stFileUploaderDropzone"] {background:#F8F9FF; border:1.5px dashed #C7D2FE;}
@media (max-width: 760px) {
  .block-container {padding:1rem 1rem 3rem;}
  .hero {padding:1.7rem 1.4rem;} .hero h1 {font-size:1.7rem;}
  .stats {grid-template-columns:repeat(2,minmax(0,1fr));}
}
</style>""", unsafe_allow_html=True)

ss = st.session_state
GROQ_KEY = cfg("GROQ_API_KEY")
REDIRECT = cfg("REDIRECT_URI", "http://localhost:8501")
SITE = cfg("SITE_URL", "https://receipt-audit.vercel.app")  # home page, privacy policy and terms (site/)
NEEDED_SCOPES = {"https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/drive.file"}


# ---------------------------------------------------------------- app state that survives OAuth redirects
# Google and Fortnox send the browser back to a fresh Streamlit session. The OAuth `state` carries a random key
# to this server-side dict, so the new session picks up where the old one was (and forged callbacks are ignored).

@st.cache_resource
def _sessions() -> dict:
    return {}


def app_state() -> dict:
    store, now = _sessions(), time.time()
    for key in [k for k, v in store.items() if now - v["_seen"] > 6 * 3600]:
        store.pop(key)
    if ss.get("nonce") not in store:
        ss.nonce = secrets.token_urlsafe(24)
        store[ss.nonce] = {}
    store[ss.nonce]["_seen"] = now
    return store[ss.nonce]


def google_flow() -> Flow:
    return Flow.from_client_config(
        {"web": {"client_id": cfg("GOOGLE_CLIENT_ID"), "client_secret": cfg("GOOGLE_CLIENT_SECRET"),
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=tools.SCOPES, redirect_uri=REDIRECT,
        autogenerate_code_verifier=False,  # the redirect lands in a new Streamlit session
    )


def google_sign_in_url() -> str:
    url, _ = google_flow().authorization_url(state=f"google:{ss.nonce}", access_type="offline",
                                             prompt="consent select_account")
    return url


def google_callback(S: dict, code: str) -> None:
    flow = google_flow()
    flow.fetch_token(code=code)
    granted = flow.oauth2session.token.get("scope") or []
    granted = set(granted.split() if isinstance(granted, str) else granted)
    if not NEEDED_SCOPES <= granted:  # Google lets people untick Gmail or Drive on the consent screen
        requests.post("https://oauth2.googleapis.com/revoke", params={"token": flow.credentials.token}, timeout=10)
        S["flash"] = ("error", "scopes", "")
        return
    S["creds"], S["demo"] = flow.credentials, False
    payload = S["creds"].id_token.split(".")[1] if isinstance(S["creds"].id_token, str) else ""
    S["email"] = json.loads(base64.urlsafe_b64decode(payload + "==")).get("email", "") if payload else ""


if "state" in st.query_params:
    provider, _, nonce = st.query_params.get("state", "").partition(":")
    known = nonce in _sessions()
    if known:
        ss.nonce = nonce
    S = app_state()
    try:
        if "error" in st.query_params:
            S["flash"] = ("warning", "denied", "")
        elif not known or "code" not in st.query_params:
            S["flash"] = ("warning", "expired", "")
        elif provider == "google":
            google_callback(S, st.query_params["code"])
        elif provider == "fortnox":
            S["fortnox"] = fortnox.exchange(st.query_params["code"])
            S["flash"] = ("success", "fortnox_ok", "")
    except Exception as e:
        S["flash"] = ("error", "failed", str(e))
    st.query_params.clear()
    st.rerun()

S = app_state()

# ---------------------------------------------------------------- sample data (what the inbox scan would return)

DEMO_RECEIPTS = [
    dict(merchant="SJ", date="2026-10-01", amount=349.0, currency="SEK", category="travel", description="Train Stockholm - Uppsala", vat=19.75, tax_label="moms 6%"),
    dict(merchant="Circle K", date="2026-10-03", amount=812.4, currency="SEK", category="fuel", description="Diesel 41 l", vat=162.48, tax_label="moms 25%"),
    dict(merchant="Slack", date="2026-10-06", amount=8.75, currency="USD", category="software", description="Slack Pro monthly"),
    dict(merchant="Uber", date="2026-10-08", amount=186.0, currency="SEK", category="taxi", description="Trip to Arlanda"),
    dict(merchant="Scandic Hotels", date="2026-10-12", amount=1450.0, currency="SEK", category="hotel", description="1 night Scandic Malmö"),
    dict(merchant="SAS Scandinavian Airlines", date="2026-10-10", amount=2315.0, currency="SEK", category="flight", description="ARN-CPH return"),
    dict(merchant="Bolt", date="2026-10-15", amount=129.0, currency="SEK", category="taxi", description="Ride, before tip"),
    dict(merchant="Google Workspace", date="2026-10-24", amount=1380.0, currency="SEK", category="software", description="Workspace Business"),
    dict(merchant="OpenAI", date="2026-10-27", amount=20.0, currency="USD", category="software", description="ChatGPT Plus"),
    dict(merchant="Apple", date="2026-10-19", amount=129.0, currency="SEK", category="software", description="iCloud+"),
]
for i, r in enumerate(DEMO_RECEIPTS):
    r.update(rc_id=f"demo{i}", subject=f"Receipt from {r['merchant']}", sender=r["merchant"])
    r.setdefault("vat", None)

# ---------------------------------------------------------------- helpers


def ctx():
    return agent.make_context(S.get("creds"), GROQ_KEY)


def live() -> bool:
    return bool(S.get("creds")) and not S.get("demo")


def fx() -> fortnox.Fortnox | None:
    if not (live() and S.get("fortnox")):
        return None
    return fortnox.Fortnox(S["fortnox"], on_refresh=lambda token: S.update(fortnox=token))


def fmt_date(d) -> str:
    return dt.date.fromisoformat(str(d)[:10]).strftime("%d %b %Y")


def money(amount: float, currency: str | None) -> str:
    return f"{amount:,.2f} {currency or ''}".replace(",", " ").strip()


def sync_google() -> None:
    if live():
        with st.spinner(T["saving"]):
            S["result"].update(agent.sync(S["creds"], S["result"]["rows"], S["result"]["receipts"],
                                          log=S["logs"].append, fortnox=fx()))


def set_status(row: dict, status: str, receipt: dict | None = None) -> None:
    row["status"] = status
    if receipt:
        row["receipt"], row["confidence"], row["reason"], row["by"] = receipt, 1.0, "Added by owner", "owner"
        S["result"]["receipts"].append(receipt)
    elif status == "matched":
        row["reason"], row["by"] = "Confirmed by owner", "owner"
    sync_google()
    st.rerun()


def graph_dot() -> str:
    g = agent.GRAPH.get_graph()
    lines = ['digraph { rankdir=TB; bgcolor="transparent"; node [shape=box style="rounded,filled" fillcolor="#eef2ff" '
             'color="#c7d2fe" fontname=Helvetica fontsize=11]; edge [color="#9ca3af"];']
    for e in g.edges:
        lines.append(f'"{e.source}" -> "{e.target}"{" [style=dashed]" if e.conditional else ""};')
    return "\n".join(lines) + "}"


def h(target, markup: str) -> None:
    target.markdown(markup, unsafe_allow_html=True)


def step_header(box, n: int, title: str, done: bool = False, optional: bool = False) -> None:
    tag = f"<span class='pill ok'>{T['done_tag']}</span>" if done else \
        f"<span class='pill gray'>{T['optional']}</span>" if optional else ""
    h(box, f"<div class='step-head'><span class='num{' done' if done else ''}'>{n}</span>"
           f"<div class='title'>{title}</div>{tag}</div>")


def account_row(box, name: str, hint: str):
    left, right = box.columns([3, 2], vertical_alignment="center")
    h(left, f"<div class='label'>{name}</div><div class='muted'>{hint}</div>")
    return right


def pill(kind: str, text: str) -> str:
    return f"<span class='pill {kind}'>{esc(text)}</span>"


# ---------------------------------------------------------------- header

nav = st.columns([5, 1.4], vertical_alignment="center")
h(nav[0], f"<div class='nav'><div class='logo'>IA</div><div><div class='nav-name'>invoice_audit</div>"
          f"<div class='nav-sub'>{TEXT[S.get('lang', 'English')]['nav']}</div></div></div>")
lang = nav[1].segmented_control("lang", list(TEXT), default=S.get("lang", "English"),
                                label_visibility="collapsed") or "English"
S["lang"] = lang
T = TEXT[lang]
if not GROQ_KEY:
    st.error(T["no_key"])
    st.stop()
if S.get("flash"):
    kind, key, detail = S.pop("flash")
    getattr(st, kind)(T[key].format(e=detail))

# ---------------------------------------------------------------- home screen (after a run)

if S.get("result"):
    res, rows = S["result"], S["result"]["rows"]
    counted = [r for r in rows if r["status"] != "no_receipt"]
    have = sum(r["status"] == "matched" for r in counted)
    todo = [r for r in rows if r["status"] in ("missing", "check")]
    actions = ""
    if res.get("folder"):
        actions = (f"<div class='hero-actions'><a class='hbtn light' href='{res['folder']}' target='_blank'>"
                   f"{T['drive']}</a><a class='hbtn ghost' href='{res['sheet']}' target='_blank'>{T['sheet']}</a></div>")
    h(st, f"<div class='hero'><div class='eyebrow'>{T['result_eyebrow']} &middot; {fmt_date(rows[0]['date'])} – "
          f"{fmt_date(rows[-1]['date'])}</div><h1>{T['headline'].format(have=have, total=len(counted))}</h1>"
          f"<p>{T['result_todo'].format(n=len(todo)) if todo else T['allgood']}</p>"
          f"<div class='bar'><div style='width:{100 * have / max(len(counted), 1):.0f}%'></div></div>{actions}</div>")
    count = lambda s: sum(r["status"] == s for r in rows)
    h(st, "<div class='stats'>" + "".join(
        f"<div class='stat' style='--c:{color}'><div class='n'>{count(status)}</div><div class='l'>{T[label]}</div></div>"
        for label, status, color in (("m_matched", "matched", "#16A34A"), ("m_check", "check", "#D97706"),
                                     ("m_missing", "missing", "#DC2626"), ("m_none", "no_receipt", "#64748B")))
      + "</div>")

    main, side = st.columns([1.65, 1], gap="large")
    with main:
        if todo:
            h(st, f"<div class='section'>{T['todo']} ({len(todo)})</div>")
        else:
            st.success(T["allgood"])
        for r in todo:
            with st.container(key=f"card_{r['status']}_{r['tx_id']}"):
                head = st.columns([4, 1.2], vertical_alignment="center")
                h(head[0], f"<div class='label'>{esc(r['merchant'])}</div><div class='muted'>{fmt_date(r['date'])} "
                           f"&middot; {money(r['amount'], r.get('currency'))}</div>")
                h(head[1], "<div style='text-align:right'>" + (pill("warn", T["check"]) if r["status"] == "check"
                                                                else pill("bad", T["missing"])) + "</div>")
                if r["status"] == "check":
                    rc = r["receipt"]
                    st.markdown(T["suggest"].format(m=rc["merchant"], d=fmt_date(rc["date"]),
                                                    a=money(rc["amount"], rc["currency"])))
                    if r.get("reason"):
                        st.caption(T["why"].format(r=r["reason"]))
                b = st.columns(3)
                if r["status"] == "check" and b[0].button(T["confirm"], key=f"ok_{r['tx_id']}", type="primary", width="stretch"):
                    set_status(r, "matched")
                with b[1].popover(T["photo"], width="stretch"):
                    up = st.file_uploader(T["photo_hint"], type=["jpg", "jpeg", "png", "heic", "pdf"],
                                          key=f"up{r['tx_id']}")
                    if up:
                        rc = dict(rc_id=f"photo-{r['tx_id']}", merchant=r["merchant"], date=r["date"],
                                  amount=r["amount"], currency=r.get("currency") or "SEK", category="other",
                                  description="Photo added by owner", vat=None, subject="Photo receipt", sender="owner")
                        if live():
                            ext = up.name.rsplit(".", 1)[-1].lower()
                            rc["drive_link"] = tools.file_receipt(S["creds"], rc, up.getvalue(),
                                                                  up.type or "image/jpeg", ext)
                            if fx() and ext in fortnox.ACCEPTED:
                                rc["fortnox_id"] = fx().upload(tools.receipt_filename(rc, ext), up.getvalue())
                        set_status(r, "matched", rc)
                if b[2].button(T["noreceipt"], key=f"no_{r['tx_id']}", width="stretch"):
                    set_status(r, "no_receipt")

    with side:
        with st.container(key="card_connections"):
            sent = sum(bool(rc.get("fortnox_id")) for rc in res["receipts"])
            google_state = pill("ok", T["connected"]) if live() else pill("info", T["sample_mode"])
            fortnox_state = (pill("ok", T["fortnox_sent"].format(n=sent)) if fx() else pill("gray", T["not_connected"]))
            h(st, f"<div class='eyebrow'>{T['connections']}</div>"
                  f"<div class='conn'><span class='label'>Google</span>{google_state}</div>"
                  f"<div class='conn'><span class='label'>Fortnox</span>{fortnox_state}</div>")
        with st.container(key="card_log"):
            h(st, f"<div class='eyebrow'>{T['tab_log']}</div>")
            with st.container(height=300, border=False):
                st.code("\n".join(S.get("logs", [])) or "-", language=None, wrap_lines=True)

    st.write("")
    tabs = st.tabs([T["tab_all"], T["tab_orphans"], T["tab_how"]])
    cols = T["cols"]
    tabs[0].dataframe([dict(zip(cols, [T["status"][r["status"]], r["date"], r["merchant"],
                                       money(r["amount"], r.get("currency")),
                                       (r["receipt"] or {}).get("merchant", ""), r.get("reason", ""),
                                       r.get("by", ""), (r["receipt"] or {}).get("drive_link")])) for r in rows],
                      column_config={cols[-1]: st.column_config.LinkColumn(display_text="Open")},
                      hide_index=True, width="stretch")
    used = {r["receipt"]["rc_id"] for r in rows if r["receipt"]}
    orphans = [rc for rc in res["receipts"] if rc["rc_id"] not in used]
    tabs[1].caption(T["orphans_hint"])
    tabs[1].markdown("\n".join(f"- **{rc['merchant']}**, {fmt_date(rc['date'])}, {money(rc['amount'], rc['currency'])}"
                               for rc in orphans) or T["none"])
    tabs[2].graphviz_chart(graph_dot())

    st.write("")
    c = st.columns([1, 1.4, 2.6])
    if c[0].button(T["restart"], key="restart", width="stretch"):
        for k in ("result", "logs", "statement", "statement_key"):
            S.pop(k, None)
        st.rerun()
    if S.get("creds") and c[1].button(T["forget"], key="forget", width="stretch"):
        requests.post("https://oauth2.googleapis.com/revoke", params={"token": S["creds"].token}, timeout=10)
        _sessions().pop(ss.nonce, None)
        ss.clear()
        st.toast(T["forgotten"])
        st.rerun()
    st.stop()

# ---------------------------------------------------------------- onboarding: 3 steps

h(st, f"<div class='hero'><div class='eyebrow'>{T['hero_eyebrow']}</div><h1>{T['hero_title']}</h1>"
      f"<p>{T['hero_text']}</p><div class='chips'>" + "".join(f"<span class='chip'>{c}</span>" for c in T["chips"])
      + "</div></div>")

main, side = st.columns([1.65, 1], gap="large")
ready = bool(S.get("creds") or S.get("demo"))

with main:
    # Step 1 - accounts
    with st.container(key="card_step1"):
        step_header(st, 1, T["step1"], done=ready)
        right = account_row(st, T["google"], esc(S.get("email") or "Google") if S.get("creds")
                            else T["demo_on"] if S.get("demo") else T["google_hint"])
        if not cfg("GOOGLE_CLIENT_ID"):
            right.caption(T["no_google"])
        elif S.get("creds"):
            right.link_button(T["switch"], google_sign_in_url(), width="stretch")
        else:
            right.link_button(T["signin"], google_sign_in_url(), type="primary", width="stretch")
        if not S.get("creds") and not S.get("demo") and st.button(T["demo"], type="tertiary"):
            S["demo"] = True
            st.rerun()
        h(st, "<div class='sep'></div>")
        right = account_row(st, f"{T['fortnox']} &nbsp;{pill('gray', T['optional'])}", T["fortnox_hint"])
        if not fortnox.configured():
            right.caption(T["fortnox_off"])
        elif not live():
            right.caption(T["fortnox_demo"])
        elif S.get("fortnox"):
            h(right, f"<div style='text-align:right'>{pill('ok', T['fortnox_on'])}</div>")
        else:
            right.link_button(T["fortnox_connect"], fortnox.auth_url(f"fortnox:{ss.nonce}"), width="stretch")

    # Step 2 - card statement: any provider, any country (the LLM reads the layout). Parsed once per file.
    with st.container(key="card_step2"):
        step_header(st, 2, T["step2"], done=bool(S.get("statement")))
        up = st.file_uploader(T["upload"], type=["csv", "xlsx", "xls", "pdf"], disabled=not ready)
        sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_mynt_export.csv")
        use_sample = st.button(T["sample"], disabled=not ready, width="stretch")
        source = (up.name, up.getvalue()) if up else \
            (os.path.basename(sample), open(sample, "rb").read()) if use_sample else None
        if source and S.get("statement_key") != (source[0], len(source[1])):
            try:
                with st.spinner(T["reading"]):
                    S["statement"] = agent.load_statement(io.BytesIO(source[1]), source[0], ctx())
                S["statement_key"] = (source[0], len(source[1]))
            except Exception as e:
                st.error(T["bad_file"].format(e=e))
        if S.get("statement"):
            tx = S["statement"]
            st.success(T["loaded"].format(n=len(tx), a=fmt_date(tx[0]["date"]), b=fmt_date(tx[-1]["date"])))

    # Step 3 - run
    with st.container(key="card_step3"):
        step_header(st, 3, T["step3"])
        has_tx = bool(S.get("statement"))
        period = st.radio(T["period"], T["periods"], horizontal=True, disabled=not has_tx)
        st.caption(T["nightly"])
        if st.button(T["run"], type="primary", disabled=not has_tx, width="stretch"):
            tx = S["statement"]
            today = dt.date.today()
            first, last = dt.date.fromisoformat(tx[0]["date"]), dt.date.fromisoformat(tx[-1]["date"])
            since, until = {
                0: (first - dt.timedelta(days=7), min(last + dt.timedelta(days=3), today)),
                1: (today - dt.timedelta(days=1), today),
                2: (today - dt.timedelta(days=7), today),
            }[T["periods"].index(period)]
            S["logs"] = []
            with st.status(T["running"], expanded=True) as status:
                def log(msg: str) -> None:
                    S["logs"].append(msg)
                    status.write(msg)
                try:
                    if S.get("demo"):  # inbox scan replaced by sample receipts; matching runs for real (rules + LLM)
                        receipts = [dict(r) for r in DEMO_RECEIPTS]
                        for r in receipts:
                            log(f"Receipt: {r['merchant']} · {r['date']} · {money(r['amount'], r['currency'])}")
                        matches, lines = agent.reconcile_receipts(tx, receipts, ctx().smart)
                        for line in lines:
                            log(line)
                        S["result"] = {"rows": agent.build_rows(tx, {r["rc_id"]: r for r in receipts}, matches),
                                       "receipts": receipts}
                    else:
                        S["result"] = agent.run(S["creds"], GROQ_KEY, tx, since, until, log, fortnox=fx())
                    status.update(label=T["done"], state="complete")
                except Exception as e:
                    status.update(label=str(e), state="error")
                    st.stop()
            st.rerun()

with side:
    with st.container(key="card_how"):
        h(st, f"<div class='eyebrow'>{T['tab_how']}</div><div class='title'>{T['how_title']}</div><ul class='flow'>"
              + "".join(f"<li><div class='k'>{i}</div><div><b>{name}</b><span>{text}</span></div></li>"
                        for i, (name, text) in enumerate(T["flow"], 1)) + "</ul>")
        with st.expander(T["graph"]):
            st.graphviz_chart(graph_dot())
    with st.container(key="card_privacy"):
        h(st, f"<div class='eyebrow'>{T['privacy_title']}</div><ul class='plist'>"
              + "".join(f"<li>{line}</li>" for line in T["privacy"]) + "</ul>"
              f"<div class='muted'><a href='{SITE}/privacy' target='_blank'>{T['policy']}</a> &middot; "
              f"<a href='{SITE}/terms' target='_blank'>{T['terms']}</a></div>")
