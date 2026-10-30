"""invoice_audit - Streamlit UI. Run: streamlit run app.py"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os

import requests
import streamlit as st
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow

import agent
import tools

load_dotenv(".env")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # Google adds openid/email aliases to granted scopes
st.set_page_config(page_title="invoice_audit", page_icon="🧾", layout="centered")


def cfg(key: str, default: str | None = None) -> str | None:
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


for key in ("GROQ_MODEL", "GROQ_FAST_MODEL", "GROQ_VISION_MODEL", "GROQ_TPM", "GROQ_RPM"):
    if cfg(key):
        os.environ[key] = str(cfg(key))

TEXT = {
    "English": {
        "tagline": "Your receipts find themselves.",
        "step1": "Connect Gmail & Drive", "signin": "Sign in with Google", "demo": "Try with sample data",
        "connected": "Connected", "readonly": "Read-only. We never send, change or delete email.",
        "step2": "Add your card statement", "upload": "Drop any card or bank export (CSV, Excel or PDF)",
        "sample": "Use sample Mynt export", "loaded": "purchases found",
        "step3": "Run the agent", "period": "Look for receipts from",
        "periods": ["The statement period", "Last 24 hours", "Last 7 days"],
        "run": "Run agent now", "nightly": "This is the job the agent runs every night. Tap to run it now.",
        "running": "Agent is working…", "done": "Done",
        "headline": "<b>{have} of {total}</b> transactions have a receipt",
        "allgood": "Nothing to do. Every transaction has a receipt. 🎉",
        "todo": "Needs you", "suggest": "Is this it? **{m}** · {d} · {a}",
        "confirm": "✅ Yes, that's it", "photo": "📷 Add photo", "photo_hint": "Snap or upload the receipt",
        "noreceipt": "🚫 No receipt", "missing": "Missing", "check": "Check",
        "drive": "📁 Receipts in Drive", "sheet": "📊 Receipt log (Sheet)",
        "all": "All transactions", "orphans": "Receipts with no card transaction (paid privately?)",
        "log": "What the agent did", "how": "How the agent works", "restart": "Start over",
        "forget": "Disconnect & delete my data", "forgotten": "Disconnected. Nothing is stored on our side.",
        "no_google": "Google sign-in is not configured (GOOGLE_CLIENT_ID / SECRET).",
        "no_key": "GROQ_API_KEY is missing.",
    },
    "Svenska": {
        "tagline": "Kvittona hittar sig själva.",
        "step1": "Koppla Gmail & Drive", "signin": "Logga in med Google", "demo": "Testa med exempeldata",
        "connected": "Kopplad", "readonly": "Endast läsning. Vi skickar, ändrar eller raderar aldrig mejl.",
        "step2": "Lägg till kortutdraget", "upload": "Släpp en export från valfritt kort eller bank (CSV, Excel eller PDF)",
        "sample": "Använd exempel-export från Mynt", "loaded": "köp hittade",
        "step3": "Kör agenten", "period": "Leta efter kvitton från",
        "periods": ["Utdragets period", "Senaste dygnet", "Senaste 7 dagarna"],
        "run": "Kör agenten nu", "nightly": "Det här jobbet kör agenten varje natt. Tryck för att köra nu.",
        "running": "Agenten arbetar…", "done": "Klart",
        "headline": "<b>{have} av {total}</b> transaktioner har ett kvitto",
        "allgood": "Inget att göra. Alla transaktioner har kvitto. 🎉",
        "todo": "Behöver dig", "suggest": "Är det här rätt? **{m}** · {d} · {a}",
        "confirm": "✅ Ja, stämmer", "photo": "📷 Lägg till foto", "photo_hint": "Fota eller ladda upp kvittot",
        "noreceipt": "🚫 Inget kvitto", "missing": "Saknas", "check": "Kolla",
        "drive": "📁 Kvitton i Drive", "sheet": "📊 Kvittologg (Kalkylark)",
        "all": "Alla transaktioner", "orphans": "Kvitton utan korttransaktion (betalt privat?)",
        "log": "Vad agenten gjorde", "how": "Så fungerar agenten", "restart": "Börja om",
        "forget": "Koppla från & radera min data", "forgotten": "Frånkopplad. Inget sparas hos oss.",
        "no_google": "Google-inloggning är inte konfigurerad (GOOGLE_CLIENT_ID / SECRET).",
        "no_key": "GROQ_API_KEY saknas.",
    },
}

st.markdown("""<style>
.block-container {max-width: 720px; padding-top: 2rem;}
.big {font-size: 1.6rem; line-height: 1.3; margin: .2rem 0 .6rem;}
.step {font-weight: 600; font-size: 1.05rem;}
div[data-testid="stPopover"] button, div.stButton button {width: 100%;}
</style>""", unsafe_allow_html=True)

ss = st.session_state
GROQ_KEY = cfg("GROQ_API_KEY")

# ---------------------------------------------------------------- Google OAuth


def oauth_flow() -> Flow:
    return Flow.from_client_config(
        {"web": {"client_id": cfg("GOOGLE_CLIENT_ID"), "client_secret": cfg("GOOGLE_CLIENT_SECRET"),
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=tools.SCOPES, redirect_uri=cfg("REDIRECT_URI", "http://localhost:8501"),
        autogenerate_code_verifier=False,  # the redirect lands in a new Streamlit session
    )


if "code" in st.query_params and "creds" not in ss:
    try:
        flow = oauth_flow()
        flow.fetch_token(code=st.query_params["code"])
        ss.creds = flow.credentials
        payload = ss.creds.id_token.split(".")[1] if isinstance(ss.creds.id_token, str) else ""
        ss.email = json.loads(base64.urlsafe_b64decode(payload + "==")).get("email", "") if payload else ""
    except Exception as e:
        st.error(f"Google sign-in failed: {e}")
    st.query_params.clear()
    st.rerun()

# ---------------------------------------------------------------- demo data (what the inbox scan would return)

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
    return agent.make_context(ss.get("creds"), GROQ_KEY)


def live() -> bool:
    return bool(ss.get("creds")) and not ss.get("demo")


def fmt_date(d) -> str:
    return dt.date.fromisoformat(str(d)[:10]).strftime("%d %b")


def money(amount: float, currency: str | None) -> str:
    return f"{amount:,.2f} {currency or ''}".replace(",", " ").strip()


def sync_google() -> None:
    if live():
        with st.spinner("Saving to Drive…"):
            ss.result.update(agent.sync(ss.creds, ss.result["rows"], ss.result["receipts"], log=ss.logs.append))


def set_status(row: dict, status: str, receipt: dict | None = None) -> None:
    row["status"] = status
    if receipt:
        row["receipt"], row["confidence"], row["reason"], row["by"] = receipt, 1.0, "Added by owner", "owner"
        ss.result["receipts"].append(receipt)
    elif status == "matched":
        row["reason"], row["by"] = "Confirmed by owner", "owner"
    sync_google()
    st.rerun()


def graph_dot() -> str:
    g = agent.GRAPH.get_graph()
    lines = ['digraph { rankdir=TB; node [shape=box style="rounded,filled" fillcolor="#eef2ff" fontname=Helvetica '
             'fontsize=11]; edge [fontname=Helvetica fontsize=9];']
    for e in g.edges:
        style = ' [style=dashed]' if e.conditional else ''
        lines.append(f'"{e.source}" -> "{e.target}"{style};')
    return "\n".join(lines) + "}"


# ---------------------------------------------------------------- header

top = st.columns([3, 1.4])
lang = top[1].segmented_control("lang", list(TEXT), default="English", label_visibility="collapsed") or "English"
T = TEXT[lang]
top[0].markdown(f"## 🧾 invoice_audit\n{T['tagline']}")
if not GROQ_KEY:
    st.error(T["no_key"])
    st.stop()

# ---------------------------------------------------------------- home screen (after a run)

if ss.get("result"):
    res, rows = ss.result, ss.result["rows"]
    counted = [r for r in rows if r["status"] != "no_receipt"]
    have = sum(r["status"] == "matched" for r in counted)
    st.markdown(f"<div class='big'>{T['headline'].format(have=have, total=len(counted))}</div>",
                unsafe_allow_html=True)
    st.progress(have / max(len(counted), 1))
    if res.get("folder"):
        c = st.columns(2)
        c[0].link_button(T["drive"], res["folder"], width="stretch")
        c[1].link_button(T["sheet"], res["sheet"], width="stretch")

    todo = [r for r in rows if r["status"] in ("missing", "check")]
    if not todo:
        st.success(T["allgood"])
    else:
        st.markdown(f"#### {T['todo']} ({len(todo)})")
    for r in todo:
        with st.container(border=True):
            head = st.columns([3, 1])
            head[0].markdown(f"**{r['merchant']}**  \n{fmt_date(r['date'])} · {money(r['amount'], r.get('currency'))}")
            head[1].markdown(f":orange-badge[{T['check']}]" if r["status"] == "check" else f":red-badge[{T['missing']}]")
            if r["status"] == "check":
                rc = r["receipt"]
                st.caption(T["suggest"].format(m=rc["merchant"], d=fmt_date(rc["date"]),
                                               a=money(rc["amount"], rc["currency"])) + f"  \n🧠 {r.get('reason', '')}")
            b = st.columns(3)
            if r["status"] == "check" and b[0].button(T["confirm"], key=f"ok{r['tx_id']}"):
                set_status(r, "matched")
            with b[1].popover(T["photo"], width="stretch"):
                up = st.file_uploader(T["photo_hint"], type=["jpg", "jpeg", "png", "heic", "pdf"], key=f"up{r['tx_id']}")
                if up:
                    rc = dict(rc_id=f"photo-{r['tx_id']}", merchant=r["merchant"], date=r["date"], amount=r["amount"],
                              currency=r.get("currency") or "SEK", category="other", description="Photo added by owner",
                              vat=None, subject="Photo receipt", sender="owner")
                    if live():
                        ext = up.name.rsplit(".", 1)[-1].lower()
                        rc["drive_link"] = tools.file_receipt(ss.creds, rc, up.getvalue(), up.type or "image/jpeg", ext)
                    set_status(r, "matched", rc)
            if b[2].button(T["noreceipt"], key=f"no{r['tx_id']}"):
                set_status(r, "no_receipt")

    label = {"matched": "✅", "check": "🟡", "missing": "❌", "no_receipt": "➖"}
    with st.expander(T["all"]):
        st.dataframe([{"": label[r["status"]], "Date": r["date"], "Card text": r["merchant"],
                       "Amount": money(r["amount"], r.get("currency")),
                       "Receipt": (r["receipt"] or {}).get("merchant", ""), "Why": r.get("reason", ""),
                       "By": r.get("by", ""), "File": (r["receipt"] or {}).get("drive_link")} for r in rows],
                     column_config={"File": st.column_config.LinkColumn(display_text="Open")},
                     hide_index=True, width="stretch")
    used = {r["receipt"]["rc_id"] for r in rows if r["receipt"]}
    orphans = [rc for rc in res["receipts"] if rc["rc_id"] not in used]
    if orphans:
        with st.expander(f"{T['orphans']} ({len(orphans)})"):
            for rc in orphans:
                st.markdown(f"- **{rc['merchant']}** · {rc['date']} · {money(rc['amount'], rc['currency'])}")
    with st.expander(T["log"]):
        st.code("\n".join(ss.logs) or "-", language=None)

    c = st.columns(2)
    if c[0].button(T["restart"]):
        for k in ("result", "logs", "statement", "statement_key"):
            ss.pop(k, None)
        st.rerun()
    if ss.get("creds") and c[1].button(T["forget"]):
        requests.post("https://oauth2.googleapis.com/revoke", params={"token": ss.creds.token}, timeout=10)
        ss.clear()
        st.toast(T["forgotten"])
        st.rerun()
    st.stop()

# ---------------------------------------------------------------- onboarding: 3 steps

# Step 1 - Google
with st.container(border=True):
    st.markdown(f"<div class='step'>1 · {T['step1']}</div>", unsafe_allow_html=True)
    if ss.get("creds"):
        st.success(f"{T['connected']}: {ss.get('email') or 'Google'}")
    elif ss.get("demo"):
        st.info("Demo mode")
    else:
        c = st.columns(2)
        if cfg("GOOGLE_CLIENT_ID"):
            url, _ = oauth_flow().authorization_url(access_type="offline", prompt="consent")
            c[0].link_button(T["signin"], url, type="primary", width="stretch")
        else:
            c[0].caption(T["no_google"])
        if c[1].button(T["demo"]):
            ss.demo = True
            st.rerun()
    st.caption(T["readonly"])

ready = bool(ss.get("creds") or ss.get("demo"))

# Step 2 - card statement: any provider, any country (the LLM reads the layout). Parsed once per file.
with st.container(border=True):
    st.markdown(f"<div class='step'>2 · {T['step2']}</div>", unsafe_allow_html=True)
    up = st.file_uploader(T["upload"], type=["csv", "xlsx", "xls", "pdf"], disabled=not ready)
    sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_mynt_export.csv")
    use_sample = st.button(T["sample"], disabled=not ready)
    source = (up.name, up.getvalue()) if up else (os.path.basename(sample), open(sample, "rb").read()) if use_sample else None
    if source and ss.get("statement_key") != (source[0], len(source[1])):
        try:
            with st.spinner("Reading statement…"):
                ss.statement = agent.load_statement(io.BytesIO(source[1]), source[0], ctx())
            ss.statement_key = (source[0], len(source[1]))
        except Exception as e:
            st.error(f"Could not read this file: {e}")
    if ss.get("statement"):
        tx = ss.statement
        st.success(f"{len(tx)} {T['loaded']} · {tx[0]['date']} → {tx[-1]['date']}")

# Step 3 - run
with st.container(border=True):
    st.markdown(f"<div class='step'>3 · {T['step3']}</div>", unsafe_allow_html=True)
    has_tx = bool(ss.get("statement"))
    period = st.radio(T["period"], T["periods"], horizontal=True, disabled=not has_tx)
    st.caption(f"🌙 {T['nightly']}")
    if st.button(T["run"], type="primary", disabled=not has_tx):
        tx = ss.statement
        today = dt.date.today()
        first, last = dt.date.fromisoformat(tx[0]["date"]), dt.date.fromisoformat(tx[-1]["date"])
        since, until = {
            0: (first - dt.timedelta(days=7), min(last + dt.timedelta(days=3), today)),
            1: (today - dt.timedelta(days=1), today),
            2: (today - dt.timedelta(days=7), today),
        }[T["periods"].index(period)]
        ss.logs = []
        with st.status(T["running"], expanded=True) as status:
            def log(msg: str) -> None:
                ss.logs.append(msg)
                status.write(msg)
            try:
                if ss.get("demo"):  # inbox scan replaced by sample receipts; matching runs for real (rules + LLM)
                    receipts = [dict(r) for r in DEMO_RECEIPTS]
                    for r in receipts:
                        log(f"🧾 {r['merchant']} · {r['date']} · {money(r['amount'], r['currency'])}")
                    matches, lines = agent.reconcile_receipts(tx, receipts, ctx().smart)
                    for line in lines:
                        log(line)
                    ss.result = {"rows": agent.build_rows(tx, {r["rc_id"]: r for r in receipts}, matches),
                                 "receipts": receipts}
                else:
                    ss.result = agent.run(ss.creds, GROQ_KEY, tx, since, until, log)
                status.update(label=T["done"], state="complete")
            except Exception as e:
                status.update(label=str(e), state="error")
                st.stop()
        st.rerun()

with st.expander(T["how"]):
    st.graphviz_chart(graph_dot())
    st.caption("LangGraph StateGraph · Groq gpt-oss-20b (read & triage) + gpt-oss-120b (reasoning & tools) · "
               "dashed = the agent decides the next step")
