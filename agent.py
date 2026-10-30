"""invoice_audit agent: Gmail -> find receipts -> match card statement -> Google Drive + Sheet.

Pure Python, no Streamlit dependency, so the same code runs from the UI button
or from a nightly scheduler (`python agent.py statement.csv`).
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import os
import re
from difflib import SequenceMatcher

import pandas as pd
from fpdf import FPDF
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from groq import Groq
from pypdf import PdfReader

# Least privilege: read-only mail, and Drive access only to files this app creates.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
ROOT_FOLDER = "Kvitton - invoice_audit"
SHEET_TITLE = "invoice_audit - Receipt log"
MAX_EMAILS = 150

# Swedish + English words that show up in receipts, bookings and order confirmations.
RECEIPT_WORDS = [
    "kvitto", "receipt", "faktura", "invoice", "orderbekräftelse", "order", "bokning",
    "booking", "bokningsbekräftelse", "biljett", "ticket", "betalning", "payment",
    "betalningsbekräftelse", "confirmation", "prenumeration", "subscription", "moms", "vat",
    '"your trip"', '"din resa"', "tankning",
]


# ---------------------------------------------------------------- card statement

STATEMENT_COLUMNS = {
    # Checked in this order so "original amount" is claimed before plain "amount".
    "orig_amount": ["originalbelopp", "original amount", "belopp i valuta", "foreign amount", "local amount"],
    "orig_currency": ["originalvaluta", "original currency", "local currency"],
    "date": ["transaktionsdatum", "köpdatum", "transaction date", "purchase date", "datum", "date", "bokföringsdatum"],
    "amount": ["belopp (sek)", "amount (sek)", "belopp", "amount", "summa", "total", "sek"],
    "currency": ["valuta", "currency"],
    "merchant": ["handlare", "merchant", "butik", "beskrivning", "description", "text", "mottagare", "namn", "name"],
}


def _to_number(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("\xa0", "").replace(" ", "").replace("kr", "").replace("SEK", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    s = re.sub(r"[^0-9.\-−]", "", s).replace("−", "-")
    try:
        return float(s)
    except ValueError:
        return None


def _map_columns(columns: list[str], groq_key: str | None) -> dict[str, str]:
    lower = {c: str(c).strip().lower() for c in columns}
    mapping: dict[str, str] = {}
    for key, candidates in STATEMENT_COLUMNS.items():
        for exact in (True, False):
            for cand in candidates:
                hit = next((c for c, l in lower.items() if c not in mapping.values()
                            and (l == cand if exact else cand in l)), None)
                if hit:
                    mapping[key] = hit
                    break
            if key in mapping:
                break
    if {"date", "amount", "merchant"} <= mapping.keys() or not groq_key:
        return mapping
    # Unknown export format: let the LLM map the header instead of failing.
    prompt = (f"Card statement columns: {list(columns)}. Return JSON mapping keys "
              f"date, amount, merchant, currency (optional) to exact column names.")
    ai = _llm_json(groq_key, "You map spreadsheet columns. Answer with JSON only.", prompt)
    return {k: v for k, v in ai.items() if v in columns} or mapping


def load_statement(file, filename: str, groq_key: str | None = None) -> pd.DataFrame:
    """Read a Mynt/Pleo/bank export (CSV or Excel) into date, merchant, amount, currency."""
    if filename.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(file, header=None)
        header_row = next((i for i, row in raw.head(20).iterrows()
                           if any(str(v).strip().lower() in ("datum", "date", "transaktionsdatum",
                                                             "transaction date", "köpdatum")
                                  for v in row.values)), 0)
        df = raw.iloc[header_row + 1:].reset_index(drop=True)
        df.columns = [str(c).strip() for c in raw.iloc[header_row]]
    else:
        data = file.read() if hasattr(file, "read") else open(file, "rb").read()
        text = data.decode("utf-8-sig", errors="replace")
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python")

    m = _map_columns(list(df.columns), groq_key)
    missing = {"date", "amount", "merchant"} - m.keys()
    if missing:
        raise ValueError(f"Could not find columns for {sorted(missing)} in {list(df.columns)}")

    out = pd.DataFrame({
        "date": pd.to_datetime(df[m["date"]], errors="coerce", dayfirst=False).dt.date,
        "merchant": df[m["merchant"]].astype(str).str.strip(),
        "amount": df[m["amount"]].map(_to_number),
        "currency": df[m["currency"]].astype(str).str.upper() if "currency" in m else "SEK",
        "orig_amount": df[m["orig_amount"]].map(_to_number) if "orig_amount" in m else None,
        "orig_currency": df[m["orig_currency"]].astype(str).str.upper() if "orig_currency" in m else None,
    }).dropna(subset=["date", "amount"])

    # Keep purchases only (drop card top-ups / refunds), whichever sign the export uses.
    purchases_negative = (out["amount"] < 0).sum() > (out["amount"] > 0).sum()
    out = out[out["amount"] < 0] if purchases_negative else out[out["amount"] > 0]
    out["amount"] = out["amount"].abs().round(2)
    out = out.sort_values("date").reset_index(drop=True)
    out.insert(0, "tx_id", [f"tx{i}" for i in range(len(out))])
    return out


# ---------------------------------------------------------------- LLM

def _llm_json(groq_key: str, system: str, user: str) -> dict:
    client = Groq(api_key=groq_key, max_retries=6)  # free tier rate limits -> back off and retry
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        return {}


EXTRACT_PROMPT = """You read emails for a Swedish small-business owner's bookkeeping.
Decide if the email (plus any PDF text) is a RECEIPT: proof of a completed purchase with a price
(kvitto, paid order confirmation, paid invoice, ticket/booking with price, subscription charge).
NOT receipts: newsletters, offers, shipping updates without a price, password resets, unpaid quotes.
Return JSON only:
{"is_receipt": bool, "merchant": "short brand name, e.g. SJ, Circle K, Uber, Slack",
 "date": "YYYY-MM-DD purchase date", "amount": number total incl. VAT, "currency": "SEK",
 "vat": number or null, "category": "travel|fuel|hotel|flight|taxi|software|food|office|other",
 "description": "max 8 words"}"""


def extract_receipt(groq_key: str, sender: str, subject: str, date: str, text: str) -> dict:
    user = f"From: {sender}\nSubject: {subject}\nEmail date: {date}\n\n{text[:4000]}"
    data = _llm_json(groq_key, EXTRACT_PROMPT, user)
    if not data.get("is_receipt") or _to_number(data.get("amount")) is None:
        return {}
    data["amount"] = abs(_to_number(data["amount"]))
    try:
        data["date"] = dt.date.fromisoformat(str(data.get("date"))[:10])
    except ValueError:
        data["date"] = dt.datetime.strptime(date[:10], "%Y-%m-%d").date()
    data["currency"] = (data.get("currency") or "SEK").upper()
    return data


# ---------------------------------------------------------------- Gmail (read-only)

PRICE = re.compile(r"\d[\d\s.,]*\s?(kr|sek|eur|usd|nok|dkk|gbp|€|\$|£)|(€|\$|£|sek|usd|eur)\s?\d", re.I)


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _walk_parts(part: dict, out: dict) -> None:
    mime, body = part.get("mimeType", ""), part.get("body", {})
    if part.get("filename") and body.get("attachmentId"):
        out["attachments"].append((part["filename"], mime, body["attachmentId"]))
    elif mime == "text/plain" and body.get("data"):
        out["plain"].append(_b64(body["data"]).decode("utf-8", errors="replace"))
    elif mime == "text/html" and body.get("data"):
        out["html"].append(_b64(body["data"]).decode("utf-8", errors="replace"))
    for p in part.get("parts", []) or []:
        _walk_parts(p, out)


def scan_gmail(creds: Credentials, groq_key: str, since: dt.date, until: dt.date, log=print) -> list[dict]:
    """Find receipts in Gmail between two dates. Only extracted fields are kept, never the mail body."""
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    words = " OR ".join(RECEIPT_WORDS)
    query = (f"after:{since:%Y/%m/%d} before:{until + dt.timedelta(days=1):%Y/%m/%d} "
             f"({words} OR filename:pdf) -in:chats")
    ids, page = [], None
    while len(ids) < MAX_EMAILS:
        res = gmail.users().messages().list(userId="me", q=query, pageToken=page, maxResults=100).execute()
        ids += [m["id"] for m in res.get("messages", [])]
        page = res.get("nextPageToken")
        if not page:
            break
    log(f"📬 {len(ids[:MAX_EMAILS])} candidate emails between {since} and {until}")

    receipts = []
    for msg_id in ids[:MAX_EMAILS]:
        msg = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        sent = dt.datetime.fromtimestamp(int(msg["internalDate"]) / 1000).strftime("%Y-%m-%d")
        parts = {"plain": [], "html": [], "attachments": []}
        _walk_parts(msg["payload"], parts)
        body_text = "\n".join(parts["plain"]) or _html_to_text("\n".join(parts["html"]))

        pdf_name, pdf_bytes, pdf_text = None, None, ""
        for fname, mime, att_id in parts["attachments"]:
            if fname.lower().endswith(".pdf") or mime == "application/pdf":
                att = gmail.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=att_id).execute()
                pdf_name, pdf_bytes = fname, _b64(att["data"])
                try:
                    pdf_text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages[:3])
                except Exception:
                    pdf_text = ""
                break

        combined = f"{body_text}\n\n--- PDF {pdf_name or ''} ---\n{pdf_text}"
        if not PRICE.search(combined):  # no price anywhere -> not a receipt, skip the LLM call
            continue
        data = extract_receipt(groq_key, headers.get("from", ""), headers.get("subject", ""), sent,
                               combined)
        if not data:
            continue
        data.update({
            "rc_id": msg_id,
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "gmail_link": f"https://mail.google.com/mail/u/0/#all/{msg_id}",
            # File content kept only in memory until it is filed in Drive.
            "_pdf": pdf_bytes,
            "_text": None if pdf_bytes else body_text,
        })
        receipts.append(data)
        log(f"🧾 {data['merchant']} · {data['date']} · {data['amount']:.2f} {data['currency']}")
    log(f"✅ {len(receipts)} receipts found")
    return receipts


# ---------------------------------------------------------------- matching

_NOISE = re.compile(r"\b(ab|inc|ltd|llc|gmbh|as|oy|se|com|www|sverige|sweden|nordic|ref|kortköp)\b")


def _norm(name: str) -> str:
    name = _NOISE.sub(" ", str(name).lower())
    return re.sub(r"[^a-z0-9åäö]", "", name)


def name_similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def score(tx: dict, rc: dict) -> float:
    """0..1 confidence that a receipt belongs to a card transaction (amount > date > name)."""
    amounts = [tx["amount"]]
    if tx.get("orig_amount") and str(tx.get("orig_currency")) == rc["currency"]:
        amounts.append(abs(tx["orig_amount"]))
    diff = min(abs(a - rc["amount"]) for a in amounts)
    amount_s = 1.0 if diff <= 0.5 else 0.6 if diff <= 0.03 * rc["amount"] else 0.0
    days = abs((tx["date"] - rc["date"]).days)
    date_s = 1.0 if days <= 1 else 0.7 if days <= 3 else 0.4 if days <= 7 else 0.0
    return round(0.5 * amount_s + 0.25 * date_s + 0.25 * name_similarity(tx["merchant"], rc["merchant"]), 2)


def match(transactions: pd.DataFrame, receipts: list[dict]) -> list[dict]:
    """Greedy one-to-one matching. Honest statuses: matched / check (suggestion) / missing."""
    txs = transactions.to_dict("records")
    pairs = sorted(((score(t, r), t["tx_id"], r["rc_id"]) for t in txs for r in receipts), reverse=True)
    by_rc = {r["rc_id"]: r for r in receipts}
    used_tx, used_rc, best = set(), set(), {}
    for s, tx_id, rc_id in pairs:
        if s < 0.5 or tx_id in used_tx or rc_id in used_rc:
            continue
        used_tx.add(tx_id)
        used_rc.add(rc_id)
        best[tx_id] = (s, by_rc[rc_id])

    rows = []
    for t in txs:
        s, rc = best.get(t["tx_id"], (0.0, None))
        status = "missing" if rc is None else "matched" if s >= 0.75 else "check"
        rows.append({**t, "status": status, "confidence": s, "receipt": rc})
    return rows


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


def _text_pdf(rc: dict) -> bytes:
    """Email receipts without a PDF attachment are archived as a PDF of the email text."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    safe = lambda s: str(s).encode("latin-1", "replace").decode("latin-1")
    header = (f"Receipt: {rc['merchant']}\nDate: {rc['date']}\nAmount: {rc['amount']:.2f} {rc['currency']}\n"
              f"From: {rc.get('sender', '')}\nSubject: {rc.get('subject', '')}\n\n")
    pdf.multi_cell(0, 5, safe(header + (rc.get("_text") or "")[:15000]))
    return bytes(pdf.output())


def receipt_filename(rc: dict, ext: str = "pdf") -> str:
    merchant = re.sub(r"\s+", " ", re.sub(r"[^\w\- åäöÅÄÖ]", "", str(rc["merchant"]))).strip()[:40] or "receipt"
    return f"{rc['date']} {merchant} {rc['amount']:.2f} {rc['currency']}.{ext}"


def file_receipt(drive, rc: dict, content: bytes | None = None, mime: str = "application/pdf", ext: str = "pdf") -> str:
    """Upload to Kvitton/<year>/<year-month>/<date merchant amount>.pdf. Idempotent by file name."""
    root = _folder(drive, ROOT_FOLDER)
    month = _folder(drive, f"{rc['date']:%Y-%m}", _folder(drive, f"{rc['date']:%Y}", root))
    name = receipt_filename(rc, ext)
    found = drive.files().list(q=f"name='{_q(name)}' and '{month}' in parents and trashed=false",
                               fields="files(id,webViewLink)").execute().get("files", [])
    if found:
        return found[0]["webViewLink"]
    content = content or rc.get("_pdf") or _text_pdf(rc)
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime)
    return drive.files().create(body={"name": name, "parents": [month]}, media_body=media,
                                fields="webViewLink").execute()["webViewLink"]


def _sheet_id(drive, sheets) -> str:
    q = f"name='{_q(SHEET_TITLE)}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    found = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if found:
        return found[0]["id"]
    sid = sheets.spreadsheets().create(body={
        "properties": {"title": SHEET_TITLE, "locale": "en_US"},
        "sheets": [{"properties": {"title": "Transactions"}}, {"properties": {"title": "Receipts"}}],
    }, fields="spreadsheetId").execute()["spreadsheetId"]
    drive.files().update(fileId=sid, addParents=_folder(drive, ROOT_FOLDER), removeParents="root").execute()
    return sid


STATUS_LABEL = {"matched": "✅ Matched", "check": "🟡 Check suggestion", "missing": "❌ Missing",
                "no_receipt": "➖ No receipt needed"}


def write_sheet(drive, sheets, rows: list[dict], receipts: list[dict]) -> str:
    sid = _sheet_id(drive, sheets)
    link = lambda url: f'=HYPERLINK("{url}","Open")' if url else ""
    tx_values = [["Date", "Merchant (card)", "Amount SEK", "Status", "Confidence",
                  "Receipt merchant", "Receipt date", "Receipt amount", "Receipt file"]]
    for r in rows:
        rc = r.get("receipt") or {}
        tx_values.append([str(r["date"]), r["merchant"], r["amount"], STATUS_LABEL[r["status"]], r["confidence"],
                          rc.get("merchant", ""), str(rc.get("date", "")),
                          f"{rc['amount']:.2f} {rc['currency']}" if rc else "", link(rc.get("drive_link"))])
    rc_values = [["Date", "Merchant", "Amount", "Currency", "VAT", "Category", "Description", "File", "Email"]]
    for rc in receipts:
        rc_values.append([str(rc["date"]), rc["merchant"], rc["amount"], rc["currency"], rc.get("vat") or "",
                          rc.get("category", ""), rc.get("description", ""),
                          link(rc.get("drive_link")), link(rc.get("gmail_link"))])
    for tab, values in (("Transactions", tx_values), ("Receipts", rc_values)):
        sheets.spreadsheets().values().clear(spreadsheetId=sid, range=tab).execute()
        sheets.spreadsheets().values().update(spreadsheetId=sid, range=f"{tab}!A1",
                                              valueInputOption="USER_ENTERED", body={"values": values}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def google_services(creds: Credentials):
    return (build("drive", "v3", credentials=creds, cache_discovery=False),
            build("sheets", "v4", credentials=creds, cache_discovery=False))


def sync(creds: Credentials, rows: list[dict], receipts: list[dict], log=print) -> dict:
    """File every receipt in Drive and rewrite the log sheet. Safe to call repeatedly."""
    drive, sheets = google_services(creds)
    for rc in receipts:
        if not rc.get("drive_link"):
            rc["drive_link"] = file_receipt(drive, rc)
            log(f"📁 Filed {receipt_filename(rc)}")
        rc.pop("_pdf", None), rc.pop("_text", None)  # filed -> drop email content from memory
    sheet = write_sheet(drive, sheets, rows, receipts)
    log("📊 Sheet updated")
    return {"sheet": sheet, "folder": f"https://drive.google.com/drive/folders/{_folder(drive, ROOT_FOLDER)}"}


def run(creds: Credentials, groq_key: str, transactions: pd.DataFrame, since: dt.date, until: dt.date,
        log=print) -> dict:
    """The nightly job: scan -> match -> file -> log."""
    receipts = scan_gmail(creds, groq_key, since, until, log)
    rows = match(transactions, receipts)
    links = sync(creds, rows, receipts, log)
    return {"rows": rows, "receipts": receipts, **links}


# ---------------------------------------------------------------- nightly CLI

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 2:
        sys.exit("usage: python agent.py <card-statement.csv|xlsx> [days_back]")
    creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["GOOGLE_CLIENT_ID"],
                        client_secret=os.environ["GOOGLE_CLIENT_SECRET"], scopes=SCOPES)
    creds.refresh(Request())
    tx = load_statement(sys.argv[1], sys.argv[1], os.environ["GROQ_API_KEY"])
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    result = run(creds, os.environ["GROQ_API_KEY"], tx, dt.date.today() - dt.timedelta(days=days), dt.date.today())
    done = sum(r["status"] == "matched" for r in result["rows"])
    print(f"\n{done} of {len(result['rows'])} transactions have a receipt. Sheet: {result['sheet']}")
