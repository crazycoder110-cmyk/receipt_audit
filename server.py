"""invoice_audit - web backend (FastAPI) for the HTML app in static/.

    uvicorn server:app --port 8501          # locally (8501 is the registered Google redirect URI)

The agent itself lives in agent.py / tools.py. This file only keeps per-browser sessions, runs the agent in a
background thread and exposes small JSON endpoints. Nothing is stored on disk: sessions live in memory.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google_auth_oauthlib.flow import Flow

load_dotenv(".env")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # Google adds openid/email aliases to granted scopes

import agent  # noqa: E402
import fortnox  # noqa: E402
import tools  # noqa: E402

ROOT = Path(__file__).parent
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
REDIRECT = os.getenv("REDIRECT_URI", "http://localhost:8501")
SECURE = REDIRECT.startswith("https://")
NEEDED_SCOPES = {"https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/drive.file"}
SAMPLE = ROOT / "sample_mynt_export.csv"
SESSION_HOURS = 6

app = FastAPI(title="invoice_audit", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


# ---------------------------------------------------------------- sessions (memory only)

@dataclass
class Session:
    creds: object = None
    email: str = ""
    demo: bool = False
    fortnox: dict | None = None
    statement: list | None = None
    statement_name: str = ""
    result: dict | None = None
    events: list = field(default_factory=list)
    running: bool = False
    error: str = ""
    oauth_state: str = ""
    flash: str = ""
    seen: float = field(default_factory=time.time)

    def live(self) -> bool:
        return bool(self.creds) and not self.demo

    def fx(self):
        if not (self.live() and self.fortnox):
            return None
        return fortnox.Fortnox(self.fortnox, on_refresh=lambda token: setattr(self, "fortnox", token))

    def log(self, stage: str, text: str, level: str = "info") -> None:
        self.events.append({"t": time.strftime("%H:%M:%S"), "stage": stage, "text": text, "level": level})


SESSIONS: dict[str, Session] = {}
LOCK = threading.Lock()


def session(request: Request) -> tuple[str, Session]:
    now = time.time()
    with LOCK:
        for sid in [k for k, v in SESSIONS.items() if now - v.seen > SESSION_HOURS * 3600 and not v.running]:
            SESSIONS.pop(sid)
        sid = request.cookies.get("ia_sid", "")
        if sid not in SESSIONS:
            sid = secrets.token_urlsafe(32)
            SESSIONS[sid] = Session()
        SESSIONS[sid].seen = now
        return sid, SESSIONS[sid]


def respond(sid: str, body, status: int = 200):
    res = body if not isinstance(body, (dict, list)) else JSONResponse(body, status_code=status)
    res.set_cookie("ia_sid", sid, max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax", secure=SECURE)
    return res


# ---------------------------------------------------------------- views of the session for the browser

def fmt_date(d: str) -> str:
    return dt.date.fromisoformat(str(d)[:10]).strftime("%d %b %Y")


def receipt_view(rc: dict | None) -> dict | None:
    if not rc:
        return None
    return {k: rc.get(k) for k in ("rc_id", "merchant", "date", "amount", "currency", "vat", "tax_label", "category",
                                   "drive_link", "gmail_link", "fortnox_id")}


def state_view(s: Session) -> dict:
    res = s.result
    rows = res["rows"] if res else []
    used = {r["receipt"]["rc_id"] for r in rows if r.get("receipt")}
    return {
        "google": {"configured": bool(os.getenv("GOOGLE_CLIENT_ID")), "connected": bool(s.creds), "email": s.email},
        "demo": s.demo,
        "fortnox": {"configured": fortnox.configured(), "connected": bool(s.fortnox)},
        "statement": {"name": s.statement_name, "count": len(s.statement), "first": fmt_date(s.statement[0]["date"]),
                      "last": fmt_date(s.statement[-1]["date"]),
                      "preview": [{k: t.get(k) for k in ("date", "merchant", "amount", "currency")}
                                  for t in s.statement[:5]]} if s.statement else None,
        "running": s.running, "error": s.error, "events": len(s.events),
        "result": {
            "rows": [{**{k: r.get(k) for k in ("tx_id", "date", "merchant", "amount", "currency", "status",
                                               "confidence", "reason", "by")},
                      "receipt": receipt_view(r.get("receipt"))} for r in rows],
            "orphans": [receipt_view(rc) for rc in res["receipts"] if rc["rc_id"] not in used],
            "sheet": res.get("sheet"), "folder": res.get("folder"),
            "sent_to_fortnox": sum(bool(rc.get("fortnox_id")) for rc in res["receipts"]),
        } if res else None,
        "flash": s.flash,
    }


# ---------------------------------------------------------------- OAuth (Google + Fortnox share the redirect URI)

def google_flow() -> Flow:
    return Flow.from_client_config(
        {"web": {"client_id": os.getenv("GOOGLE_CLIENT_ID"), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=tools.SCOPES, redirect_uri=REDIRECT, autogenerate_code_verifier=False)


def oauth_callback(s: Session, params) -> None:
    provider, _, state = params.get("state", "").partition(":")
    expected, s.oauth_state = s.oauth_state, ""
    if "error" in params:
        s.flash = "denied"
    elif not expected or params.get("state") != expected or "code" not in params:
        s.flash = "expired"
    elif provider == "google":
        flow = google_flow()
        flow.fetch_token(code=params["code"])
        granted = flow.oauth2session.token.get("scope") or []
        granted = set(granted.split() if isinstance(granted, str) else granted)
        if not NEEDED_SCOPES <= granted:  # Google lets people untick Gmail or Drive on the consent screen
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": flow.credentials.token}, timeout=10)
            s.flash = "scopes"
            return
        s.creds, s.demo, s.flash = flow.credentials, False, "google_ok"
        payload = s.creds.id_token.split(".")[1] if isinstance(s.creds.id_token, str) else ""
        s.email = json.loads(base64.urlsafe_b64decode(payload + "==")).get("email", "") if payload else ""
    elif provider == "fortnox":
        s.fortnox, s.flash = fortnox.exchange(params["code"]), "fortnox_ok"


@app.get("/")
def index(request: Request):
    sid, s = session(request)
    if "state" in request.query_params:
        try:
            oauth_callback(s, request.query_params)
        except Exception as e:
            s.flash = "failed:" + tools.friendly_error(e)
        return respond(sid, RedirectResponse("/", status_code=303))
    return respond(sid, FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"}))


@app.get("/auth/google")
def auth_google(request: Request):
    sid, s = session(request)
    s.oauth_state = f"google:{secrets.token_urlsafe(16)}"
    url, _ = google_flow().authorization_url(state=s.oauth_state, access_type="offline",
                                             prompt="consent select_account")
    return respond(sid, RedirectResponse(url, status_code=303))


@app.get("/auth/fortnox")
def auth_fortnox(request: Request):
    sid, s = session(request)
    if not fortnox.configured():
        return respond(sid, RedirectResponse("/", status_code=303))
    s.oauth_state = f"fortnox:{secrets.token_urlsafe(16)}"
    return respond(sid, RedirectResponse(fortnox.auth_url(s.oauth_state), status_code=303))


# ---------------------------------------------------------------- API

@app.get("/api/health")
def health():
    return JSONResponse({"ok": True}, headers={"Access-Control-Allow-Origin": "*"})


@app.get("/api/state")
def get_state(request: Request):
    sid, s = session(request)
    view = state_view(s)
    s.flash = ""
    return respond(sid, view)


@app.post("/api/demo")
def demo(request: Request):
    sid, s = session(request)
    s.demo = True
    return respond(sid, state_view(s))


@app.post("/api/statement")
def statement(request: Request, file: UploadFile | None = File(None), sample: str = Form("")):
    sid, s = session(request)
    if not (s.creds or s.demo):
        return respond(sid, {"error": "Connect Google or choose sample data first."}, 400)
    name, data = (SAMPLE.name, SAMPLE.read_bytes()) if sample else (file.filename, file.file.read()) if file else ("", b"")
    if not data:
        return respond(sid, {"error": "No file received."}, 400)
    try:
        ctx = agent.make_context(s.creds, GROQ_KEY)
        s.statement, s.statement_name = agent.load_statement(io.BytesIO(data), name, ctx), name
    except Exception as e:
        return respond(sid, {"error": f"Could not read this file. {tools.friendly_error(e)}"}, 400)
    if not s.statement:
        return respond(sid, {"error": "No card purchases found in this file."}, 400)
    s.result, s.events, s.error = None, [], ""
    return respond(sid, state_view(s))


def _run(s: Session, since: dt.date, until: dt.date) -> None:
    try:
        tx = s.statement
        if s.demo:  # inbox scan replaced by sample receipts; matching runs for real (rules + LLM)
            import demo_data
            s.log("search", "Sample mode: using built-in sample receipts instead of an inbox")
            receipts = [dict(r) for r in demo_data.RECEIPTS]
            for r in receipts:
                s.log("read", f"Read receipt: {r['merchant']}, {fmt_date(r['date'])[:6]}, "
                              f"{r['amount']:.2f} {r['currency']}", "ok")
            s.log("match", f"Matching {len(receipts)} receipts to {len(tx)} card transactions")
            token = tools.on_progress(s.log)
            try:
                matches, lines = agent.reconcile_receipts(tx, receipts, agent.make_context(None, GROQ_KEY).smart)
            except Exception as e:
                raise RuntimeError(tools.friendly_error(e)) from e
            finally:
                tools._progress.reset(token)
            for line in lines:
                s.log("match", line, "ok")
            s.result = {"rows": agent.build_rows(tx, {r["rc_id"]: r for r in receipts}, matches), "receipts": receipts}
            s.log("done", "Done", "ok")
        else:
            s.result = agent.run(s.creds, GROQ_KEY, tx, since, until, progress=s.log, fortnox=s.fx())
    except Exception as e:
        s.error = str(e)
        if not s.events or s.events[-1]["level"] != "error":
            s.log("error", s.error, "error")
    finally:
        s.running = False


@app.post("/api/run")
async def start_run(request: Request):
    sid, s = session(request)
    if s.running:
        return respond(sid, {"error": "The agent is already running."}, 409)
    if not s.statement:
        return respond(sid, {"error": "Add a card statement first."}, 400)
    period = int((await request.json()).get("period", 0))
    today = dt.date.today()
    first, last = dt.date.fromisoformat(s.statement[0]["date"]), dt.date.fromisoformat(s.statement[-1]["date"])
    since, until = {  # bookings are paid before the email; hotel folios and invoices often arrive later
        0: (first - dt.timedelta(days=7), min(last + dt.timedelta(days=14), today)),
        1: (today - dt.timedelta(days=1), today),
        2: (today - dt.timedelta(days=7), today),
    }.get(period, (first, last))
    s.running, s.error, s.events, s.result = True, "", [], None
    threading.Thread(target=_run, args=(s, since, until), daemon=True).start()
    return respond(sid, {"ok": True})


@app.get("/api/run")
def run_status(request: Request, since: int = 0):
    sid, s = session(request)
    return respond(sid, {"events": s.events[since:], "running": s.running, "error": s.error,
                         "state": None if s.running else state_view(s)})


@app.get("/api/log")
def full_log(request: Request):
    sid, s = session(request)
    return respond(sid, {"events": s.events})


def _row(s: Session, tx_id: str) -> dict | None:
    return next((r for r in (s.result or {}).get("rows", []) if r["tx_id"] == tx_id), None)


def _sync(s: Session) -> None:
    if s.live():
        s.result.update(agent.sync(s.creds, s.result["rows"], s.result["receipts"],
                                   log=lambda text: s.log("save", text, "ok"), fortnox=s.fx()))


def _fix(request: Request, tx_id: str, change) -> JSONResponse:
    sid, s = session(request)
    row = _row(s, tx_id)
    if not row:
        return respond(sid, {"error": "Unknown transaction."}, 404)
    try:
        change(s, row)
        _sync(s)
    except Exception as e:
        return respond(sid, {"error": tools.friendly_error(e)}, 500)
    return respond(sid, state_view(s))


@app.post("/api/tx/{tx_id}/confirm")
def confirm(request: Request, tx_id: str):
    def change(s, row):
        row.update(status="matched", reason="Confirmed by owner", by="owner")
    return _fix(request, tx_id, change)


@app.post("/api/tx/{tx_id}/no-receipt")
def no_receipt(request: Request, tx_id: str):
    return _fix(request, tx_id, lambda s, row: row.update(status="no_receipt", by="owner"))


@app.post("/api/tx/{tx_id}/upload")
def upload(request: Request, tx_id: str, file: UploadFile = File(...)):
    data, name = file.file.read(), file.filename or "receipt.jpg"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "jpg"
    mime = file.content_type or ("application/pdf" if ext == "pdf" else "image/jpeg")

    def change(s, row):
        rc = dict(rc_id=f"photo-{tx_id}", merchant=row["merchant"], date=row["date"], amount=row["amount"],
                  currency=row.get("currency") or "SEK", category="other", description="Added by owner",
                  vat=None, subject="Receipt added by owner", sender="owner")
        if s.live():
            rc["drive_link"] = tools.file_receipt(s.creds, rc, data, mime, ext)
            if s.fx() and ext in fortnox.ACCEPTED:
                rc["fortnox_id"] = s.fx().upload(tools.receipt_filename(rc, ext), data)
        s.result["receipts"].append(rc)
        row.update(status="matched", receipt=rc, confidence=1.0, reason="Added by owner", by="owner")
    return _fix(request, tx_id, change)


@app.post("/api/fortnox/send")
def fortnox_send(request: Request):
    sid, s = session(request)
    if not s.fx():
        return respond(sid, {"error": "not_connected"}, 400)
    sent = []
    agent.push_to_fortnox(s.fx(), s.creds, s.result["rows"], sent.append)
    _sync(s)
    return respond(sid, {**state_view(s), "messages": sent})


@app.post("/api/restart")
def restart(request: Request):
    sid, s = session(request)
    if not s.running:
        s.statement, s.statement_name, s.result, s.events, s.error = None, "", None, [], ""
    return respond(sid, state_view(s))


@app.post("/api/disconnect")
def disconnect(request: Request):
    sid, s = session(request)
    if s.creds:
        requests.post("https://oauth2.googleapis.com/revoke", params={"token": s.creds.token}, timeout=10)
    with LOCK:
        SESSIONS.pop(sid, None)
    res = JSONResponse({"ok": True})
    res.delete_cookie("ia_sid")
    return res
