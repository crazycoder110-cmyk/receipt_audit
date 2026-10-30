"""Tools and I/O for the agent.

Gmail access is read-only by construction: the OAuth scope is gmail.readonly and no function here can send,
modify or delete mail. Drive access is drive.file: the agent only sees files it created itself.
"""
from __future__ import annotations

import base64
import contextvars
import datetime as dt
import html
import io
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

import pypdfium2 as pdfium
from fpdf import FPDF
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, Field

import prompts

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
ROOT_FOLDER = "Receipts - invoice_audit"
SHEET_TITLE = "invoice_audit - Receipt log"
DOC_CHARS = 1800          # per email/attachment sent to the LLM (~500 tokens)


@dataclass
class AgentContext:
    """Runtime dependencies, passed to the graph as `context` (never stored in state)."""
    creds: Any
    fast: Any                # gpt-oss-20b: plan, triage, extraction (bulk work)
    smart: Any               # gpt-oss-120b: statement layout, reconcile, hunter (reasoning)
    vision: Any = None       # scanned PDFs / photos
    home_currency: str = "SEK"
    fortnox: Any = None      # fortnox.Fortnox when the owner connected Fortnox


# ---------------------------------------------------------------- progress for the UI

_progress: contextvars.ContextVar = contextvars.ContextVar("progress", default=None)


def on_progress(callback) -> contextvars.Token:
    """Route emit() calls of this run (and the graph's worker threads, which copy the context) to `callback`."""
    return _progress.set(callback)


def emit(stage: str, text: str, level: str = "info") -> None:
    """One line in the activity log. stage: search|triage|read|match|hunt|save|ai|done, level: info|ok|warn|error."""
    callback = _progress.get()
    if callback:
        callback(stage, text, level)


def friendly_error(e: Exception) -> str:
    """Errors in words the owner understands; AI provider problems are named as such."""
    import groq
    from googleapiclient.errors import HttpError

    text = str(e)
    if isinstance(e, groq.RateLimitError):
        if any(k in text.lower() for k in ("per day", "tpd", "rpd")):
            return "Groq issue: the daily AI limit of the free plan is used up. Try again tomorrow or use a paid key."
        return "Groq issue: the AI rate limit was reached. Wait a minute and run again."
    if isinstance(e, groq.AuthenticationError):
        return "Groq issue: the AI key was rejected. Check GROQ_API_KEY."
    if isinstance(e, groq.APIConnectionError):
        return "Groq issue: the AI service could not be reached. Try again in a moment."
    if isinstance(e, groq.APIStatusError):
        return f"Groq issue: the AI service returned an error ({e.status_code})."
    if isinstance(e, HttpError):
        return f"Google issue: {e.reason or text}"
    return text


# ---------------------------------------------------------------- Groq free-tier budget

class RateBudget:
    """Client-side RPM/TPM limiter per model, so a run waits instead of failing with 429s.
    Defaults are Groq's free tier (30 RPM, 8K TPM); raise GROQ_TPM / GROQ_RPM on a paid plan."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm, self.calls, self.used = rpm, tpm, deque(), 0
        self.lock = threading.Lock()

    def acquire(self, tokens: int) -> None:
        tokens = min(tokens, self.tpm)
        with self.lock:
            while True:
                now = time.time()
                while self.calls and now - self.calls[0][0] > 60:
                    self.calls.popleft()
                if len(self.calls) < self.rpm and sum(t for _, t in self.calls) + tokens <= self.tpm:
                    self.calls.append((now, tokens))
                    self.used += tokens
                    return
                wait = max(0.5, 60 - (now - self.calls[0][0]))
                if wait >= 3:
                    emit("ai", f"Waiting {wait:.0f}s for AI capacity (Groq free-tier limit)", "warn")
                time.sleep(wait)


_budgets: dict[str, RateBudget] = {}


def budget(llm) -> RateBudget:
    name = getattr(llm, "model_name", "default")
    if name not in _budgets:
        _budgets[name] = RateBudget(int(os.getenv("GROQ_RPM", 30)), int(os.getenv("GROQ_TPM", 8000)))
    return _budgets[name]


def tokens_used() -> int:
    return sum(b.used for b in _budgets.values())


def _estimate(*texts: Any, out: int = 400) -> int:
    return sum(len(str(t)) for t in texts) // 3 + out   # ~3 chars/token incl. non-latin scripts


def call(llm, messages: list, out: int = 400):
    budget(llm).acquire(_estimate(*(m.content for m in messages), out=out))
    return llm.invoke(messages)


def structured(llm, schema: type[BaseModel], system: str, user: str, out: int = 400) -> BaseModel:
    """Strict JSON-schema output (guaranteed shape); falls back to tool-calling mode if strict is rejected."""
    messages = [SystemMessage(system), HumanMessage(user)]
    budget(llm).acquire(_estimate(system, user, json.dumps(schema.model_json_schema()), out=out))
    try:
        return llm.with_structured_output(schema, method="json_schema", strict=True).invoke(messages)
    except Exception:
        return llm.with_structured_output(schema, method="function_calling").invoke(messages)


class ExtractedDocument(BaseModel):
    is_financial_document: bool
    merchant: Optional[str] = Field(description="short brand name, not the legal entity")
    date: Optional[str]
    total_amount: Optional[float]
    currency: Optional[str]
    tax_amount: Optional[float]
    tax_label: Optional[str] = Field(description="tax type and rate(s) only, e.g. moms 25%, moms 12% + 25%, CGST 9% + SGST 9%")
    seller_tax_id: Optional[str] = Field(description="VAT no / GSTIN / org no")
    document_number: Optional[str]
    category: Optional[str] = Field(description="travel|fuel|hotel|flight|taxi|software|food|office|telecom|other")
    summary: Optional[str] = Field(description="max 6 words, English")


# ---------------------------------------------------------------- Google clients

_local = threading.local()


def google(creds, api: str, version: str):
    """googleapiclient is not thread-safe and the graph extracts emails in parallel -> one client per thread."""
    cache = _local.__dict__.setdefault("svc", {})
    key = (id(creds), api)
    if key not in cache:
        cache[key] = build(api, version, credentials=creds, cache_discovery=False)
    return cache[key]


# ---------------------------------------------------------------- Gmail (read-only)

def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0\u200c\u200b]+", " ", text)).strip()


def compact(text: str, limit: int = DOC_CHARS) -> str:
    """Shrink a document for the LLM without keywords: drop URLs, keep the opening lines (who/what) and every
    line that contains a digit (amounts, dates, tax, ids) - that holds in every language."""
    lines = [l.strip() for l in re.sub(r"https?://\S+|\[image[^\]]*\]", "", text).splitlines()]
    lines = [l for l in lines if len(l) > 1]
    keep = lines[:8] + [l for l in lines[8:] if re.search(r"\d", l)]
    return "\n".join(dict.fromkeys(keep))[:limit]


def _walk(part: dict, out: dict) -> None:
    mime, body = part.get("mimeType", ""), part.get("body", {})
    if part.get("filename") and body.get("attachmentId"):
        out["attachments"].append({"filename": part["filename"], "mime": mime, "attachment_id": body["attachmentId"]})
    elif mime == "text/plain" and body.get("data"):
        out["plain"].append(_b64(body["data"]).decode("utf-8", errors="replace"))
    elif mime == "text/html" and body.get("data"):
        out["html"].append(_b64(body["data"]).decode("utf-8", errors="replace"))
    for p in part.get("parts", []) or []:
        _walk(p, out)


def _sender(value: str) -> str:
    name, _, addr = value.partition("<")
    return f"{name.strip().strip(chr(34))} {addr.rstrip('>')}".strip()[:60]


def search_messages(creds, query: str, limit: int = 50) -> list[dict]:
    """Gmail search returning light metadata (no bodies)."""
    gmail = google(creds, "gmail", "v1")
    ids, page = [], None
    while len(ids) < limit:
        res = gmail.users().messages().list(userId="me", q=query, pageToken=page,
                                            maxResults=min(100, limit)).execute()
        ids += [m["id"] for m in res.get("messages", [])]
        page = res.get("nextPageToken")
        if not page:
            break
    out = []
    for msg_id in ids[:limit]:
        m = gmail.users().messages().get(userId="me", id=msg_id, format="metadata",
                                         metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
        out.append({"id": msg_id, "from": _sender(h.get("from", "")), "subject": h.get("subject", "")[:90],
                    "date": dt.datetime.fromtimestamp(int(m["internalDate"]) / 1000).strftime("%Y-%m-%d")})
    return out


def fetch_email(creds, msg_id: str) -> dict:
    m = google(creds, "gmail", "v1").users().messages().get(userId="me", id=msg_id, format="full").execute()
    h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
    parts = {"plain": [], "html": [], "attachments": []}
    _walk(m["payload"], parts)
    body = "\n".join(parts["plain"]) or html_to_text("\n".join(parts["html"]))
    return {"id": msg_id, "from": h.get("from", ""), "subject": h.get("subject", ""),
            "date": dt.datetime.fromtimestamp(int(m["internalDate"]) / 1000).strftime("%Y-%m-%d"),
            "body": body, "attachments": parts["attachments"]}


def fetch_attachment(creds, msg_id: str, attachment_id: str) -> bytes:
    att = google(creds, "gmail", "v1").users().messages().attachments().get(
        userId="me", messageId=msg_id, id=attachment_id).execute()
    return _b64(att["data"])


# ---------------------------------------------------------------- PDF + vision

def _page_lines(page) -> str:
    """Text in visual rows. PDF text order can be column by column (e.g. card statements), which would
    separate each date from its description and amount."""
    tp = page.get_textpage()
    segments = []
    for i in range(tp.count_rects()):
        left, bottom, right, top = tp.get_rect(i)
        text = tp.get_text_bounded(left, bottom, right, top).strip()
        if text:
            segments.append((left, bottom, right, top, text))
    rows: list[dict] = []  # a piece joins a row when they overlap vertically (letters like g, j, p hang lower)
    for left, bottom, right, top, text in sorted(segments, key=lambda s: -s[3]):
        for row in rows:
            overlap = min(top, row["top"]) - max(bottom, row["bottom"])
            if overlap > 0.5 * min(top - bottom, row["top"] - row["bottom"]):
                row["parts"].append((left, right, top - bottom, text))
                row["top"], row["bottom"] = max(top, row["top"]), min(bottom, row["bottom"])
                break
        else:
            rows.append({"top": top, "bottom": bottom, "parts": [(left, right, top - bottom, text)]})
    lines = []
    for row in sorted(rows, key=lambda r: -r["top"]):
        line, prev_right, height = "", None, row["top"] - row["bottom"]
        for left, right, _, text in sorted(row["parts"]):
            gap = left - prev_right if prev_right is not None else 0
            line += ("" if gap < 0.15 * height else " " if gap < 1.2 * height else "  ") + text
            prev_right = max(right, prev_right or right)
        lines.append(line.strip())
    return "\n".join(lines)


def pdf_text(data: bytes, max_pages: int = 3) -> str:
    try:
        pdf = pdfium.PdfDocument(data)
        return "\n".join(_page_lines(pdf[i]) for i in range(min(len(pdf), max_pages)))
    except Exception:
        return ""


def pdf_images(data: bytes, max_pages: int = 1) -> list[bytes]:
    pdf = pdfium.PdfDocument(data)
    images = []
    for i in range(min(len(pdf), max_pages)):
        buf = io.BytesIO()
        pdf[i].render(scale=1.5).to_pil().convert("RGB").save(buf, format="JPEG", quality=75)
        images.append(buf.getvalue())
    return images


def vision_read(vision, images: list[bytes], mime: str = "image/jpeg") -> str:
    """Transcribe receipt images (scans, photos) in any language. Each image costs ~2K tokens, so only on demand."""
    if vision is None or not images:
        return ""
    content: list = [{"type": "text", "text": "Transcribe this receipt: seller, date, total, currency, tax lines, "
                                              "document number. Original language, plain text, concise."}]
    content += [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(b).decode()}"}}
                for b in images[:2]]
    try:
        budget(vision).acquire(2100 * len(images[:2]) + 500)
        return str(vision.invoke([HumanMessage(content=content)]).content)
    except Exception as e:
        return f"[vision unavailable: {e}]"


def attachment_text(ctx: AgentContext, msg_id: str, att: dict) -> str:
    name, mime = att["filename"].lower(), att["mime"]
    if not (name.endswith(".pdf") or mime == "application/pdf" or mime.startswith("image/")):
        return ""
    data = fetch_attachment(ctx.creds, msg_id, att["attachment_id"])
    if mime.startswith("image/"):
        return vision_read(ctx.vision, [data], mime)
    text = pdf_text(data)
    if len(text.strip()) < 40:  # scanned PDF without a text layer
        text = vision_read(ctx.vision, pdf_images(data))
    return text


def read_document(ctx: AgentContext, msg_id: str) -> tuple[dict, str]:
    email = fetch_email(ctx.creds, msg_id)
    chunks = [compact(email["body"])]
    for att in email["attachments"][:2]:
        text = attachment_text(ctx, msg_id, att)
        if text:
            chunks.append(f"[{att['filename']}]\n{compact(text)}")
    return email, "\n".join(chunks)


def extract_document(ctx: AgentContext, msg_id: str) -> dict | None:
    """Email -> structured receipt (any language, any country), or None if it is not a purchase document."""
    email, text = read_document(ctx, msg_id)
    doc = structured(ctx.fast, ExtractedDocument, prompts.EXTRACT,
                     f"From: {_sender(email['from'])}\nSubject: {email['subject']}\nSent: {email['date']}\n{text}")
    if not doc.is_financial_document or not doc.total_amount:
        return None
    try:
        date = dt.date.fromisoformat((doc.date or "")[:10]).isoformat()
    except ValueError:
        date = email["date"]
    pdf = next((a for a in email["attachments"]
                if a["filename"].lower().endswith(".pdf") or a["mime"] == "application/pdf"), None)
    return {
        "rc_id": msg_id, "merchant": doc.merchant or _sender(email["from"]) or "Unknown",
        "date": date, "amount": abs(float(doc.total_amount)),
        "currency": (doc.currency or ctx.home_currency).upper(), "vat": doc.tax_amount,
        "tax_label": doc.tax_label, "seller_tax_id": doc.seller_tax_id, "document_number": doc.document_number,
        "category": doc.category, "description": doc.summary,
        "subject": email["subject"], "sender": email["from"],
        "gmail_link": f"https://mail.google.com/mail/u/0/#all/{msg_id}",
        "pdf_attachment_id": pdf["attachment_id"] if pdf else None,
    }


# ---------------------------------------------------------------- tools for the hunter agent (compact outputs)

@tool
def gmail_search(query: str, runtime: ToolRuntime) -> str:
    """Search Gmail (read-only) with Gmail syntax, e.g. 'from:uber.com after:2026/10/01 before:2026/10/20'.
    Returns up to 6 lines: id|date|sender|subject."""
    emit("hunt", f"Searching the inbox: {query}")
    try:
        found = search_messages(runtime.context.creds, query, limit=6)
    except Exception as e:
        return f"Search failed: {e}"
    return "\n".join(f"{m['id']}|{m['date']}|{m['from']}|{m['subject']}" for m in found) or "No results."


@tool
def read_email(message_id: str, runtime: ToolRuntime) -> str:
    """Open one email: sender, subject, date, the key lines of the body and attachment names."""
    e = fetch_email(runtime.context.creds, message_id)
    emit("hunt", f"Opening email: {e['subject'][:80]}")
    files = ", ".join(a["filename"] for a in e["attachments"]) or "none"
    return f"From: {_sender(e['from'])}\nSubject: {e['subject']}\nDate: {e['date']}\nAttachments: {files}\n" \
           f"{compact(e['body'], 1000)}"


@tool
def read_attachment(message_id: str, filename: str, runtime: ToolRuntime) -> str:
    """Read the key lines of a PDF or image attachment (scans are OCR'd)."""
    email = fetch_email(runtime.context.creds, message_id)
    att = next((a for a in email["attachments"] if a["filename"] == filename), None)
    if not att:
        return f"No attachment {filename}. Available: {[a['filename'] for a in email['attachments']]}"
    emit("hunt", f"Reading attachment: {filename}")
    return compact(attachment_text(runtime.context, message_id, att), 1200) or "No readable text."


def _brief(rc: dict) -> str:
    return f"{rc['rc_id']}: {rc['merchant']} {rc['date']} {rc['amount']:.2f} {rc['currency']}"


@tool
def extract_receipt(message_id: str, runtime: ToolRuntime) -> Command:
    """Extract merchant, date, total and currency from an email and remember it for submit_match."""
    rc = extract_document(runtime.context, message_id)
    return Command(update={"receipts": {rc["rc_id"]: rc} if rc else {},
                           "messages": [ToolMessage(_brief(rc) if rc else "Not a purchase document.",
                                                    tool_call_id=runtime.tool_call_id)]})


@tool
def submit_match(tx_id: str, receipt_id: str, confidence: float, reason: str, runtime: ToolRuntime) -> Command:
    """Link a receipt (email id) to a card transaction. confidence 0..1, reason max 12 words."""
    state = runtime.state
    receipts = dict(state.get("receipts") or {})
    used = {m["receipt_id"] for m in (state.get("matches") or {}).values() if m.get("receipt_id")}
    reply = lambda text, **upd: Command(update={**upd, "messages": [
        ToolMessage(text, tool_call_id=runtime.tool_call_id)]})
    if tx_id not in {t["tx_id"] for t in state["transactions"]}:
        return reply(f"Unknown tx_id {tx_id}.")
    if receipt_id in used:
        return reply("That receipt is already matched to another transaction.")
    if receipt_id not in receipts:
        rc = extract_document(runtime.context, receipt_id)
        if not rc:
            return reply("That email is not a receipt.")
        receipts[receipt_id] = rc
    match = {"receipt_id": receipt_id, "confidence": round(float(confidence), 2), "reason": reason,
             "status": "matched" if confidence >= 0.8 else "check", "by": "hunter agent"}
    card = next(t["merchant"] for t in state["transactions"] if t["tx_id"] == tx_id)
    emit("hunt", f"Found missing receipt: {receipts[receipt_id]['merchant']} for {card}", "ok")
    return reply("Saved.", receipts={receipt_id: receipts[receipt_id]}, matches={tx_id: match})


HUNTER_TOOLS = [gmail_search, read_email, read_attachment, extract_receipt, submit_match]


# ---------------------------------------------------------------- Drive + Sheet

def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _folder(drive, name: str, parent: str | None = None) -> str:
    q = f"name='{_q(name)}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    found = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if found:
        return found[0]["id"]
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent] if parent else []}
    return drive.files().create(body=body, fields="id").execute()["id"]


_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
          "/Library/Fonts/Arial Unicode.ttf", "C:/Windows/Fonts/arial.ttf"]


def text_pdf(title: str, text: str) -> bytes:
    """Email receipts without a PDF attachment are archived as a PDF of the email text."""
    pdf = FPDF()
    pdf.add_page()
    font = next((f for f in _FONTS if os.path.exists(f)), None)
    if font:
        pdf.add_font("doc", fname=font)
        pdf.set_font("doc", size=9)
        safe = str
    else:
        pdf.set_font("Helvetica", size=9)
        safe = lambda s: str(s).encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 4.5, safe(f"{title}\n\n{text}"[:20000]), wrapmode="CHAR")
    return bytes(pdf.output())


def receipt_filename(rc: dict, ext: str = "pdf") -> str:
    merchant = re.sub(r"\s+", " ", re.sub(r"[^\w\- ]", "", str(rc["merchant"]))).strip()[:40] or "receipt"
    return f"{rc['date']} {merchant} {rc['amount']:.2f} {rc['currency']}.{ext}"


def receipt_content(creds, rc: dict) -> bytes:
    """Re-fetch the original document from Gmail at filing time, so email content is never stored by us."""
    if rc.get("pdf_attachment_id"):
        return fetch_attachment(creds, rc["rc_id"], rc["pdf_attachment_id"])
    email = fetch_email(creds, rc["rc_id"])
    title = (f"{rc['merchant']} | {rc['date']} | {rc['amount']:.2f} {rc['currency']}\n"
             f"From: {email['from']}\nSubject: {email['subject']}\nEmail date: {email['date']}")
    return text_pdf(title, email["body"])


def file_receipt(creds, rc: dict, content: bytes | None = None, mime: str = "application/pdf",
                 ext: str = "pdf") -> str:
    """Upload to <root>/<year>/<year-month>/<date merchant amount>.pdf. Idempotent by file name."""
    drive = google(creds, "drive", "v3")
    d = dt.date.fromisoformat(str(rc["date"])[:10])
    month = _folder(drive, f"{d:%Y-%m}", _folder(drive, f"{d:%Y}", _folder(drive, ROOT_FOLDER)))
    name = receipt_filename(rc, ext)
    found = drive.files().list(q=f"name='{_q(name)}' and '{month}' in parents and trashed=false",
                               fields="files(id,webViewLink)").execute().get("files", [])
    if found:
        return found[0]["webViewLink"]
    media = MediaIoBaseUpload(io.BytesIO(content or receipt_content(creds, rc)), mimetype=mime)
    return drive.files().create(body={"name": name, "parents": [month]}, media_body=media,
                                fields="webViewLink").execute()["webViewLink"]


STATUS_LABEL = {"matched": "Matched", "check": "Check suggestion", "missing": "Missing",
                "no_receipt": "No receipt needed"}


def write_sheet(creds, rows: list[dict], receipts: list[dict]) -> str:
    drive, sheets = google(creds, "drive", "v3"), google(creds, "sheets", "v4")
    q = f"name='{_q(SHEET_TITLE)}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    found = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if found:
        sid = found[0]["id"]
    else:
        sid = sheets.spreadsheets().create(body={
            "properties": {"title": SHEET_TITLE, "locale": "en_US"},
            "sheets": [{"properties": {"title": "Transactions"}}, {"properties": {"title": "Receipts"}}],
        }, fields="spreadsheetId").execute()["spreadsheetId"]
        drive.files().update(fileId=sid, addParents=_folder(drive, ROOT_FOLDER), removeParents="root").execute()

    link = lambda url: f'=HYPERLINK("{url}","Open")' if url else ""
    tx_values = [["Date", "Card description", "Amount", "Currency", "Status", "Confidence", "Why", "Matched by",
                  "Receipt merchant", "Receipt date", "Receipt total", "Tax", "Receipt file", "Fortnox"]]
    for r in rows:
        rc = r.get("receipt") or {}
        tx_values.append([r["date"], r["merchant"], r["amount"], r.get("currency", ""), STATUS_LABEL[r["status"]],
                          r["confidence"], r.get("reason", ""), r.get("by", ""), rc.get("merchant", ""),
                          rc.get("date", ""), f"{rc['amount']:.2f} {rc['currency']}" if rc else "",
                          f"{rc['vat']} ({rc.get('tax_label') or ''})" if rc.get("vat") else "",
                          link(rc.get("drive_link")), "Sent" if rc.get("fortnox_id") else ""])
    rc_values = [["Date", "Merchant", "Total", "Currency", "Tax", "Tax label", "Seller tax id", "Doc no",
                  "Category", "Description", "File", "Email"]]
    for rc in receipts:
        rc_values.append([rc["date"], rc["merchant"], rc["amount"], rc["currency"], rc.get("vat") or "",
                          rc.get("tax_label") or "", rc.get("seller_tax_id") or "", rc.get("document_number") or "",
                          rc.get("category") or "", rc.get("description") or "",
                          link(rc.get("drive_link")), link(rc.get("gmail_link"))])
    for tab, values in (("Transactions", tx_values), ("Receipts", rc_values)):
        sheets.spreadsheets().values().clear(spreadsheetId=sid, range=tab).execute()
        sheets.spreadsheets().values().update(spreadsheetId=sid, range=f"{tab}!A1", valueInputOption="USER_ENTERED",
                                              body={"values": values}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def root_folder_link(creds) -> str:
    return f"https://drive.google.com/drive/folders/{_folder(google(creds, 'drive', 'v3'), ROOT_FOLDER)}"
