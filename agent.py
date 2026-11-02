"""invoice_audit - LangGraph receipt-matching agent.

    START → plan_queries → search_inbox → triage ─(Send × N)→ extract_one ─→ reconcile
                                                                              │
                                     ┌──── receipts still missing ────────────┤
                                     ▼                                        │ all found
                       hunter (ReAct) ⇄ tools                                 │
                                     │ done                                   ▼
                                     └────────────────────────────────► file_receipts (Drive)
                                                                              │ Fortnox connected?
                                                                     send_to_fortnox ─► write_log (Sheet) → END

Every decision that needs understanding (what to search for, which mails are receipts, what a document says,
which receipt belongs to which transaction, where else to look) is made by the LLM. Code only does I/O,
scoring and safety checks. Run from the UI (app.py) or nightly: `python agent.py statement.csv 1`.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Annotated, Literal, Optional

import warnings

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

import prompts
import tools
from tools import AgentContext, structured

# Groq rate limits are per model, so bulk work and reasoning run on different models (2x the free budget).
# ToolRuntime carries our (non-pydantic) context object; serialising it only produces a harmless warning.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)

GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
WINDOW_SCAN_LIMIT = 120    # emails in the date window looked at (metadata only, no LLM tokens)
QUERY_SCAN_LIMIT = 15      # per LLM-planned search
MAX_EXTRACT = 40           # emails read in full per run (~1K tokens each)
HUNTER_MAX_STEPS = 6
HUNTER_MAX_TX = 5


# ---------------------------------------------------------------- state

def merge(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class AuditState(TypedDict, total=False):
    transactions: list[dict]                      # card statement lines
    since: str
    until: str
    hunt: bool
    queries: list[str]
    candidates: Annotated[dict, merge]            # email id -> metadata (no bodies)
    shortlist: list[str]
    receipts: Annotated[dict, merge]              # email id -> extracted receipt
    matches: Annotated[dict, merge]               # tx_id -> {receipt_id, confidence, status, reason, by}
    messages: Annotated[list, add_messages]       # hunter agent conversation
    hunter_steps: int
    fortnox: bool                                 # Fortnox connected for this run
    links: dict


class ExtractTask(TypedDict):
    msg_id: str


# ---------------------------------------------------------------- LLM schemas

class SearchPlan(BaseModel):
    reasoning: str = Field(description="One or two sentences")
    queries: list[str]


class Triage(BaseModel):
    selected: list[int]


class Decision(BaseModel):
    tx_id: str
    receipt_id: Optional[str]
    confidence: float
    reason: str


class Decisions(BaseModel):
    decisions: list[Decision]


class StatementLayout(BaseModel):
    header_row: int = Field(description="0-based index of the header row in the preview")
    date_column: str
    description_column: str = Field(description="Merchant / description / text column")
    amount_column: str = Field(description="Amount charged in the statement currency")
    currency_column: Optional[str]
    original_amount_column: Optional[str] = Field(description="Amount in the purchase's own currency, if separate")
    original_currency_column: Optional[str]
    statement_currency: Optional[str] = Field(description="ISO 4217, when not given per row")
    decimal_separator: Literal[",", "."]
    day_first: bool = Field(description="True if dates like 03/10/2026 mean 3 October")
    purchases_are_negative: bool
    debit_credit_column: Optional[str] = Field(description="Separate column that marks debit vs credit, if any")
    purchase_marker: Optional[str] = Field(description="Value in that column that marks a purchase, e.g. 'Dr', 'D'")


class StatementLine(BaseModel):
    kind: Literal["purchase", "top_up", "cash", "transfer", "fee", "incoming"] = Field(
        description="purchase = paid to a shop, company or service: card, online, UPI, wallet or bill payment, "
                    "direct debit. transfer = to a private person or own account")
    date: str = Field(description="YYYY-MM-DD")
    description: str = Field(description="Short: the merchant or payee name, max 60 characters, no reference numbers")
    amount: float
    currency: Optional[str]
    original_amount: Optional[float]
    original_currency: Optional[str]
    balance_before: Optional[float] = Field(description="Running balance printed on the row above, else null")
    balance_after: Optional[float] = Field(description="Running balance printed on this row, else null")


class StatementLines(BaseModel):
    transactions: list[StatementLine]


# ---------------------------------------------------------------- models

def make_context(creds, groq_key: str, home_currency: str = "SEK", fortnox=None) -> AgentContext:
    def llm(model: str, max_tokens: int) -> ChatGroq:
        # low reasoning effort keeps hidden reasoning tokens (which count against TPM) small
        return ChatGroq(model=model, api_key=groq_key, temperature=0, reasoning_effort="low",
                        max_tokens=max_tokens, max_retries=4)
    fast, smart = llm(GROQ_FAST_MODEL, 1200), llm(GROQ_MODEL, 4000)
    tools.pair_models(fast, smart)
    return AgentContext(creds=creds, fast=fast, smart=smart,
                        vision=ChatGroq(model=GROQ_VISION_MODEL, api_key=groq_key, temperature=0, max_tokens=600,
                                        max_retries=3),
                        home_currency=home_currency, fortnox=fortnox)


# ---------------------------------------------------------------- card statement (any provider, any country)

def to_number(value, decimal: str = ".") -> float | None:
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    negative = bool(re.search(r"[-−]\s*\d", s)) or (s.startswith("(") and s.endswith(")"))
    s = re.sub(rf"[^\d{re.escape(decimal)}]", "", s).replace(decimal, ".")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def _parse_dates(series: pd.Series, day_first: bool) -> pd.Series:
    iso = pd.to_datetime(series, format="ISO8601", errors="coerce")
    if iso.notna().mean() > 0.8:
        return iso.dt.date
    return pd.to_datetime(series, dayfirst=day_first, errors="coerce", format="mixed").dt.date


def _read_table(data: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    # Bank exports often have title lines above the table -> read ragged rows and pad them.
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    width = max(map(len, rows), default=0)
    return pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=str)


def _balance_kinds(lines: list[StatementLine]) -> list[str]:
    """Arithmetic beats reading columns: where the running balance rose by exactly the row's amount the money came
    in, where it fell by that amount it went out (whatever the label said). Every money row is listed in order, so
    the balance before a row is the previous row's balance after."""
    kinds, previous = [], None
    for line in lines:
        kind, before = line.kind, line.balance_before if line.balance_before is not None else previous
        if line.balance_after is not None and before is not None:
            change = line.balance_after - before
            if abs(change - abs(line.amount)) < 0.02:
                kind = "incoming"
            elif abs(change + abs(line.amount)) < 0.02 and kind == "incoming":
                kind = "transfer"  # money went out: kept in the background, a receipt can prove it was a purchase
        if line.balance_after is not None:
            previous = line.balance_after
        kinds.append(kind)
    return kinds


# ---------------------------------------------------------------- statement PDFs: only the transaction table

OUTGOING = ("purchase", "transfer", "top_up")


def is_purchase(t: dict) -> bool:
    """Rows the owner needs a receipt for. Other outgoing rows (transfers, top-ups) are kept in the background and
    only show up when a receipt proves they were a purchase (reading a statement can mislabel a UPI payment)."""
    return t.get("kind", "purchase") == "purchase"


MAX_STATEMENT_PAGES = 5
# a transaction row has a date and an amount, in any language: 2026-10-04, 04/10/2026, 18 Jun 19, Oct 4, 2026
_DATE = re.compile(r"\b(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
                   r"|\d{1,2}\s?[^\W\d_]{3,9}\.?,?\s?\d{2,4}|[^\W\d_]{3,9}\.?\s\d{1,2},?\s\d{2,4})\b")
_AMOUNT = re.compile(r"\d[\d\s,.']*[.,]\d{2}(?!\d)")


class StatementTooLong(ValueError):
    def __init__(self, pages: int):
        super().__init__(f"This PDF has {pages} pages. For now statements can have at most {MAX_STATEMENT_PAGES} "
                         "pages: upload the pages with the transactions.")
        self.pages = pages


def _transaction_lines(lines: list[str]) -> list[int]:
    """Rows start with a date and end with an amount (maybe followed by Dr/Cr or a balance). Sentences in terms and
    notices also contain dates and amounts, but not in that shape."""
    return [i for i, line in enumerate(lines)
            if _DATE.match(line.strip()) and any(_AMOUNT.search(t) for t in line.split()[-3:])]


def statement_tables(pages: list[str]) -> list[str]:
    """Keep only the transaction table of each page: a few lines above the first row (column headers), up to a few
    lines after the last row (descriptions continue below). Pages of terms, rewards or notices are dropped.
    The short header lines of page 1 (period, currency, card) go in front of the first table."""
    tables = []
    for text in pages:
        lines = text.splitlines()
        rows = _transaction_lines(lines)
        if len(rows) >= 2:
            tables.append("\n".join(lines[max(0, rows[0] - 3):min(len(lines), rows[-1] + 5)]))
    if tables and pages:
        first = pages[0].splitlines()
        rows = _transaction_lines(first)
        head = [l for l in first[:rows[0] - 3 if rows else 40] if 0 < len(l.split()) <= 12][:15]
        tables[0] = "\n".join(head + [tables[0]])
    return tables


# money: 1,234.56 / 1 234,56 / -841.04 / (12.00); not percentages, times or long reference numbers
_MONEY = re.compile(r"(?<![\w.,/])\(?[-−]?(?:\d{1,3}(?:[ ,.'’]\d{3})+|\d+)[.,]\d{2}\)?(?![\d%])(?!\s?%)")
_MARKERS = {"dr": "out", "db": "out", "debit": "out", "d": "out", "cr": "in", "credit": "in", "c": "in"}


def _money(token: str) -> float:
    return to_number(token, token.rstrip(")")[-3])


def table_rows(pages: list[str]) -> list[dict]:
    """The transaction rows of statement tables, read by code (no LLM): a row starts where an amount appears, with
    the date at the start of the line or the previous row's date; lines without amounts continue the description
    (e.g. UPI/ref/ then the merchant). Direction comes from the running balance, a Dr/Cr marker or the sign."""
    rows, date = [], None
    for page in pages:
        current = None
        for line in page.splitlines():
            text, lead = line.strip(), []
            while (m := _DATE.match(text)):  # a row can start with two dates (purchase, settlement)
                lead.append(m.group(0))
                text = text[m.end():].strip()
            money = list(_MONEY.finditer(text))
            if money:
                date = lead[0] if lead else date
                if date is None:  # header lines above the first row
                    continue
                after = text[money[-1].end():].split()
                current = {"date": date, "lines": 1,
                           "description": re.sub(r"(\s+\d+)+$", "", text[:money[0].start()].strip()),
                           "values": [_money(x.group(0)) for x in money],
                           "marker": _MARKERS.get(after[0].lower().strip(".")) if after else None}
                rows.append(current)
            elif current is not None and text and current["lines"] < 4:
                current["description"] = f"{current['description']} {text}".strip()
                current["lines"] += 1
    # running balance: the last value of a row, if it moves by the row's amount on most rows
    pairs = [(a, b) for a, b in zip(rows, rows[1:]) if len(b["values"]) >= 2]
    chained = sum(abs(abs(b["values"][-1] - a["values"][-1]) - abs(b["values"][0])) < 0.01 for a, b in pairs)
    balance_mode = bool(pairs) and chained >= 0.6 * len(pairs)
    signs = [r["values"][0] < 0 for r in rows]
    negative_out = sum(signs) >= len(signs) / 2  # card exports: purchases are the usual (negative) rows
    out, previous = [], None
    for r in rows:
        values = r["values"]
        if balance_mode and len(values) == 1:  # balance brought forward
            previous = values[0]
            continue
        direction = r["marker"]
        if balance_mode and previous is not None:
            change = values[-1] - previous
            if abs(change) < 0.005:  # totals and summaries do not move the balance
                previous = values[-1]
                continue
            if abs(abs(change) - abs(values[0])) < 0.01:
                direction = "in" if change > 0 else "out"
        if balance_mode:
            previous = values[-1]
        if direction is None:
            direction = "out" if (values[0] < 0) == negative_out else "in"
        out.append({"date": r["date"], "description": r["description"][:160], "amount": abs(values[0]),
                    "direction": direction})
    return out


class RowKind(BaseModel):
    n: int
    name: str = Field(description="Short merchant or payee name, max 30 characters, no reference numbers")
    kind: Literal["purchase", "cash", "fee", "transfer", "top_up", "other"]


class StatementKinds(BaseModel):
    currency: Optional[str] = Field(description="ISO 4217 of the statement")
    day_first: bool = Field(description="True if dates like 03/10/2026 mean 3 October")
    rows: list[RowKind]


def _classify(ctx: AgentContext, header: str, rows: list[dict]) -> tuple[list[RowKind | None], str | None, bool]:
    """One small LLM call: the kind and a short name of each outgoing row, the statement currency, the date order."""
    lines = "\n".join(f"{n}|{r['date']}|{' '.join(r['description'].split())[:70]}|{r['amount']:.2f}"
                      for n, r in enumerate(rows))
    try:
        res = structured(ctx.smart, StatementKinds, prompts.STATEMENT_KINDS,
                         f"Statement header:\n{header}\n\nRows:\n{lines}", out=300 + 20 * len(rows))
    except Exception:
        return [None] * len(rows), None, True
    kinds = {k.n: k for k in res.rows}
    return [kinds.get(n) for n in range(len(rows))], res.currency, res.day_first


def _read_rows(ctx: AgentContext, pages: list[str]) -> list[StatementLine]:
    """One LLM call for a few pages; if the answer fails (too long, broken JSON), one call per page instead."""
    import groq
    try:
        return structured(ctx.smart, StatementLines, prompts.STATEMENT_PDF, "\n".join(pages), out=2500).transactions
    except (groq.RateLimitError, groq.AuthenticationError, groq.APIConnectionError):
        raise
    except Exception:
        if len(pages) == 1:
            raise
        return [l for page in pages for l in _read_rows(ctx, [page])]


def load_statement(file, filename: str, ctx: AgentContext, password: str | None = None,
                   info: dict | None = None) -> list[dict]:
    """Card statement (CSV / Excel / PDF) -> purchases. The LLM reads the layout, so any export format works.
    PDFs: raises tools.PdfLocked (needs a password) or StatementTooLong; `info` gets the pages used."""
    data = file.read() if hasattr(file, "read") else open(file, "rb").read()
    if filename.lower().endswith(".pdf"):
        pdf = tools.open_pdf(data, password)
        if len(pdf) > MAX_STATEMENT_PAGES:
            raise StatementTooLong(len(pdf))
        # page layout kept (a value stays under its column header) and whole lines, not compact():
        # descriptions often continue on lines without digits. Only transaction tables go to the LLM, in chunks
        # of pages so each answer stays short enough to be complete.
        text_pages = [tools._page_lines(pdf[i], layout=True) for i in range(len(pdf))]
        pages = statement_tables(text_pages)
        if info is not None:
            info.update(pages=len(pdf), used_pages=len(pages))
        if not pages and not any(p.strip() for p in text_pages):  # a scan without a text layer
            pages = [tools.vision_read(ctx.vision, tools.pdf_images(data, MAX_STATEMENT_PAGES))]
        if not pages:
            raise ValueError("No transactions found in this PDF.")
        table = [r for r in table_rows(pages) if r["direction"] == "out"]
        if len(table) >= 2:  # read by code; the LLM only labels short rows
            kinds, currency, day_first = _classify(ctx, "\n".join(pages[0].splitlines()[:20]), table)
            dates = _parse_dates(pd.Series([r["date"] for r in table]), day_first)
            rows = [{"date": d.isoformat(), "merchant": (k.name.strip() if k and k.name.strip() else
                                                         " ".join(r["description"].split())[:80]),
                     "amount": r["amount"], "currency": (currency or ctx.home_currency).upper(),
                     "orig_amount": None, "orig_currency": None, "kind": k.kind if k else "purchase"}
                    for r, k, d in zip(table, kinds, dates) if (k.kind if k else "purchase") in OUTGOING and pd.notna(d)]
            rows.sort(key=lambda r: r["date"])
            return [{"tx_id": f"tx{i}", **r} for i, r in enumerate(rows)]
        chunks, size = [[]], 0
        for page in pages:
            page_size = len(" ".join(page.split()))
            if chunks[-1] and size + page_size > 5000:
                chunks.append([])
                size = 0
            chunks[-1].append(page)
            size += page_size
        lines = [l for chunk in chunks for l in _read_rows(ctx, chunk)]
        kinds = _balance_kinds(lines)
        rows = [{"date": l.date, "merchant": l.description, "amount": abs(l.amount),
                 "currency": (l.currency or ctx.home_currency).upper(),
                 "orig_amount": abs(l.original_amount) if l.original_amount else None,
                 "orig_currency": l.original_currency or None, "kind": kind}
                for l, kind in zip(lines, kinds) if kind in OUTGOING]
    else:
        raw = _read_table(data, filename)
        preview = "\n".join(f"{i}: " + "|".join("" if pd.isna(v) else str(v)[:40] for v in row)
                            for i, row in raw.head(12).iterrows())
        lay = structured(ctx.smart, StatementLayout, prompts.STATEMENT, preview)
        header = [str(v).strip() if pd.notna(v) else f"col{i}" for i, v in enumerate(raw.iloc[lay.header_row])]
        df = raw.iloc[lay.header_row + 1:].copy()
        df.columns = header
        col = lambda name: df[name] if name and name in df.columns else None
        for need in (lay.date_column, lay.description_column, lay.amount_column):
            if need not in df.columns:
                raise ValueError(f"Could not understand the statement (column '{need}' not in {header}).")
        currency = col(lay.currency_column)
        orig_amount = col(lay.original_amount_column)
        orig_currency = col(lay.original_currency_column)
        frame = pd.DataFrame({
            "date": _parse_dates(col(lay.date_column), lay.day_first),
            "merchant": col(lay.description_column).astype(str).str.strip(),
            "amount": col(lay.amount_column).map(lambda v: to_number(v, lay.decimal_separator)),
            "currency": currency.str.upper() if currency is not None else (lay.statement_currency or ctx.home_currency),
            "orig_amount": orig_amount.map(lambda v: to_number(v, lay.decimal_separator))
            if orig_amount is not None else None,
            "orig_currency": orig_currency.str.strip().str.upper().replace({"": None}) if orig_currency is not None else None,
        })
        marker = col(lay.debit_credit_column)
        if marker is not None and lay.purchase_marker:
            frame = frame[marker.astype(str).str.strip().str.lower() == lay.purchase_marker.strip().lower()]
            frame = frame.assign(amount=frame["amount"].abs() * (-1 if lay.purchases_are_negative else 1))
        frame = frame.dropna(subset=["date", "amount"])
        frame = frame[frame["amount"] < 0] if lay.purchases_are_negative else frame[frame["amount"] > 0]
        frame = frame.astype(object).where(frame.notna(), None)
        rows = [{**r, "kind": "purchase", "date": r["date"].isoformat(), "amount": abs(r["amount"]),
                 "orig_amount": abs(r["orig_amount"]) if r["orig_amount"] else None} for r in frame.to_dict("records")]
    rows.sort(key=lambda r: r["date"])
    return [{"tx_id": f"tx{i}", **r} for i, r in enumerate(rows)]


# ---------------------------------------------------------------- scoring (cheap first pass, LLM decides the rest)

def _d(value) -> dt.date:
    return dt.date.fromisoformat(str(value)[:10])


def name_similarity(card: str, merchant: str) -> float:
    a, b = re.sub(r"[\W_]", "", str(card).lower()), re.sub(r"[\W_]", "", str(merchant).lower())
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    tokens = [t for t in re.split(r"[\W_]+", str(merchant).lower()) if len(t) >= 3]
    if any(t in a for t in tokens):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def score(tx: dict, rc: dict) -> tuple[float, str]:
    amounts = []
    if tx.get("currency") == rc["currency"]:
        amounts.append(tx["amount"])
    if tx.get("orig_amount") and tx.get("orig_currency") == rc["currency"]:
        amounts.append(tx["orig_amount"])
    if amounts:
        diff = min(abs(a - rc["amount"]) for a in amounts)
        rel = diff / max(rc["amount"], 1)
        amount_s = 1.0 if diff <= 0.5 else 0.6 if rel <= 0.05 else 0.3 if rel <= 0.15 else 0.0
        amount_txt = "same amount" if amount_s == 1 else f"amount differs by {diff:.2f}"
    name_s = name_similarity(tx["merchant"], rc["merchant"])
    if not amounts:  # amounts can't be compared across currencies, so the brand has to agree (LLM judges the rate)
        amount_s = 0.3 if name_s >= 0.6 else 0.0
        rate = f", implied rate {tx['amount'] / rc['amount']:.4g} {tx.get('currency')}/{rc['currency']}" if rc["amount"] else ""
        amount_txt = f"different currency ({rc['amount']} {rc['currency']}{rate})"
    days = abs((_d(tx["date"]) - _d(rc["date"])).days)
    date_s = 1.0 if days <= 1 else 0.8 if days <= 3 else 0.5 if days <= 7 else 0.2 if days <= 14 else 0.0
    total = round(0.5 * amount_s + 0.25 * date_s + 0.25 * name_s, 2)
    return total, f"{amount_txt}, {days} day(s) apart, name similarity {name_s:.0%}"


def reconcile_receipts(transactions: list[dict], receipts: list[dict], llm=None,
                       taken: dict | None = None) -> tuple[dict, list[str]]:
    """Clear cases are matched by score; everything ambiguous is decided by the LLM, reasoning like an accountant."""
    taken = taken or {}
    used = {m["receipt_id"] for m in taken.values() if m.get("receipt_id")}
    open_tx = [t for t in transactions if t["tx_id"] not in taken]
    pool = [r for r in receipts if r["rc_id"] not in used]
    cands = {}
    for t in open_tx:
        scored = sorted(((*score(t, r), r) for r in pool), key=lambda x: -x[0])
        cands[t["tx_id"]] = [c for c in scored if c[0] >= 0.35][:3]

    matches, log = {}, []
    for t in sorted(open_tx, key=lambda t: -(cands[t["tx_id"]][0][0] if cands[t["tx_id"]] else 0)):
        c = cands[t["tx_id"]]
        clear = c and c[0][0] >= 0.9 and (len(c) == 1 or c[0][0] - c[1][0] >= 0.15)
        if clear and c[0][2]["rc_id"] not in used:
            used.add(c[0][2]["rc_id"])
            matches[t["tx_id"]] = {"receipt_id": c[0][2]["rc_id"], "confidence": c[0][0], "status": "matched",
                                   "reason": c[0][1].capitalize() + ".", "by": "rules"}
    log.append(f"{len(matches)} matched automatically (same amount, date and merchant)")

    ambiguous = [t for t in open_tx if t["tx_id"] not in matches and is_purchase(t)
                 and any(r["rc_id"] not in used for _, _, r in cands[t["tx_id"]])]
    if ambiguous and llm is not None:
        payload = [{"tx_id": t["tx_id"], "date": t["date"], "card_description": t["merchant"], "amount": t["amount"],
                    "currency": t.get("currency"), "original_amount": t.get("orig_amount"),
                    "original_currency": t.get("orig_currency"),
                    "candidates": [{"receipt_id": r["rc_id"], "merchant": r["merchant"], "date": r["date"],
                                    "total": r["amount"], "currency": r["currency"], "pre_score": s, "signals": why}
                                   for s, why, r in cands[t["tx_id"]] if r["rc_id"] not in used]}
                   for t in ambiguous]
        decisions = structured(llm, Decisions, prompts.RECONCILE,
                               json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                               out=150 * len(payload) + 300).decisions
        allowed = {p["tx_id"]: {c["receipt_id"] for c in p["candidates"]} for p in payload}
        for d in sorted(decisions, key=lambda d: -d.confidence):
            if d.tx_id in allowed and d.receipt_id in allowed[d.tx_id] and d.receipt_id not in used \
                    and d.tx_id not in matches and d.confidence >= 0.4:
                used.add(d.receipt_id)
                matches[d.tx_id] = {"receipt_id": d.receipt_id, "confidence": round(d.confidence, 2),
                                    "status": "matched" if d.confidence >= 0.8 else "check",
                                    "reason": d.reason, "by": "LLM"}
        log.append(f"AI reviewed {len(ambiguous)} uncertain match(es)")
    elif ambiguous:  # no LLM available: conservative suggestions only
        for t in ambiguous:
            s, why, r = next((c for c in cands[t["tx_id"]] if c[2]["rc_id"] not in used), (0, "", None))
            if r and s >= 0.5:
                used.add(r["rc_id"])
                matches[t["tx_id"]] = {"receipt_id": r["rc_id"], "confidence": s, "status": "check",
                                       "reason": why.capitalize() + ".", "by": "rules"}
    # evidence: a receipt with exactly the amount of an outgoing row the statement reading did not call a purchase
    # (same currency, at most 3 days apart, only one such row) shows it was one
    found = 0
    for r in pool:
        if r["rc_id"] in used:
            continue
        rows = [t for t in open_tx if not is_purchase(t) and t["tx_id"] not in matches
                and t.get("currency") == r["currency"] and abs(t["amount"] - r["amount"]) <= 0.01
                and abs((_d(t["date"]) - _d(r["date"])).days) <= 3]
        if len(rows) == 1:
            used.add(r["rc_id"])
            matches[rows[0]["tx_id"]] = {"receipt_id": r["rc_id"], "confidence": 0.9, "status": "matched",
                                         "reason": "Exact amount and date; a payment the statement listed as "
                                                   f"{rows[0]['kind'].replace('_', '-')}.", "by": "rules"}
            found += 1
    if found:
        log.append(f"{found} more payment(s) matched by exact amount and date")
    return matches, log


# ---------------------------------------------------------------- graph nodes

def _window(state: AuditState) -> str:
    until = _d(state["until"]) + dt.timedelta(days=1)
    return f"after:{_d(state['since']):%Y/%m/%d} before:{until:%Y/%m/%d}"


def plan_queries(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    window = _window(state)
    merchants = [m for m, _ in Counter(t["merchant"] for t in state["transactions"]).most_common(40)]
    tools.emit("search", f"Preparing searches for {len(merchants)} card merchants")
    plan = structured(runtime.context.fast, SearchPlan, prompts.PLAN_QUERIES, "\n".join(merchants))
    queries = [f"({q}) {window} {tools.MAILBOX}" for q in plan.queries[:5]]
    return {"queries": queries}


def search_inbox(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    creds = runtime.context.creds
    tools.emit("search", f"Fetching emails from {_d(state['since']):%d %b} to {_d(state['until']):%d %b %Y}")
    # One structural scan of the whole window (operators only, no keywords) + the LLM's targeted searches.
    found = {m["id"]: m for m in tools.search_messages(
        creds, f"{_window(state)} {tools.MAILBOX}", WINDOW_SCAN_LIMIT)}
    for q in state["queries"]:
        try:
            found.update({m["id"]: m for m in tools.search_messages(creds, q, QUERY_SCAN_LIMIT)})
        except Exception as e:  # an invalid query from the planner must not stop the run
            tools.emit("search", f"One search was skipped: {tools.friendly_error(e)}", "warn")
    tools.emit("search", f"Found {len(found)} emails in the period", "ok")
    return {"candidates": found}


def triage(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    items = list(state.get("candidates", {}).values())
    tools.emit("triage", f"Identifying receipts and invoices among {len(items)} emails")
    # the card merchants tell the model what to look for (names only: words with digits are references)
    names = [" ".join(w for w in re.split(r"[\s/*@]+", t["merchant"]) if w and not any(c.isdigit() for c in w))
             for t in state["transactions"]]
    merchants = ", ".join(dict.fromkeys(" ".join(n.split()[:4]) for n in names if n))[:600]
    # safety net without the model: sender or subject shares a word with a card merchant (Airtel ~ AIRTEL.IN)
    words = {w for n in names for w in re.findall(r"[^\W\d_]{4,}", n.lower())}
    def known_merchant(m: dict) -> bool:
        return any(w[:5] == k[:5] for w in re.findall(r"[^\W\d_]{4,}", f"{m['from']} {m['subject']}".lower())
                   for k in words if len(w) >= 5 and len(k) >= 5)
    picked: list[str] = []
    for i in range(0, len(items), 60):  # compact 'n|sender|subject' lines, the model answers with numbers
        batch = items[i:i + 60]
        lines = "\n".join(f"{n}|{m['from']}|{m['subject']}" for n, m in enumerate(batch))
        res = structured(runtime.context.fast, Triage, prompts.TRIAGE,
                         f"Card payments: {merchants}\n\nEmails:\n{lines}", out=300)
        picked += [batch[n]["id"] for n in res.selected if 0 <= n < len(batch)]
    picked += [m["id"] for m in items if known_merchant(m)]
    picked = list(dict.fromkeys(picked))[:MAX_EXTRACT]
    tools.emit("triage", f"{len(picked)} emails look like receipts or invoices" if picked
               else "No receipts or invoices found in the inbox", "ok" if picked else "warn")
    return {"shortlist": picked}


def fan_out(state: AuditState):
    return [Send("extract_one", {"msg_id": i}) for i in state.get("shortlist", [])] or "reconcile"


def extract_one(task: ExtractTask, runtime: Runtime[AgentContext]) -> dict:
    try:
        rc = tools.extract_document(runtime.context, task["msg_id"])
    except Exception as e:
        tools.emit("read", f"Could not read one email: {tools.friendly_error(e)}", "warn")
        return {}
    if not rc:
        return {}
    tax = f", VAT {rc['vat']:.2f}" if rc.get("vat") else ""
    tools.emit("read", f"Read receipt: {rc['merchant']}, {_d(rc['date']):%d %b}, "
                       f"{rc['amount']:.2f} {rc['currency']}{tax}", "ok")
    return {"receipts": {rc["rc_id"]: rc}}


def _duplicates(receipts: dict) -> dict:
    """The same receipt found twice (forwarded, in two folders): later copies point to the first."""
    first, dupes = {}, {}
    for rc in sorted(receipts.values(), key=lambda r: r["rc_id"]):
        key = (re.sub(r"\W", "", str(rc["merchant"]).lower())[:10], rc["date"], round(rc["amount"], 2), rc["currency"])
        if key in first and not rc.get("duplicate_of"):
            dupes[rc["rc_id"]] = {**rc, "duplicate_of": first[key]}
        first.setdefault(key, rc["rc_id"])
    return dupes


def unique_receipts(receipts: dict) -> dict:
    return {k: v for k, v in receipts.items() if not v.get("duplicate_of")}


def reconcile(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    dupes = _duplicates(state.get("receipts", {}))
    receipts = [r for k, r in unique_receipts(state.get("receipts", {})).items() if k not in dupes]
    purchases = [t for t in state["transactions"] if is_purchase(t)]
    tools.emit("match", f"Matching {len(receipts)} receipts to {len(purchases)} card transactions"
                        + (f" ({len(dupes)} duplicate receipt(s) merged)" if dupes else ""))
    matches, log = reconcile_receipts(state["transactions"], receipts, runtime.context.smart, state.get("matches"))
    for line in log:
        tools.emit("match", line, "ok")
    done = {**state.get("matches", {}), **matches}
    missing = len([t for t in purchases if t["tx_id"] not in done])
    tools.emit("match", f"{missing} transaction(s) still without a receipt", "warn" if missing else "ok")
    return {"matches": matches, "receipts": dupes}


def route_after_reconcile(state: AuditState) -> str:
    missing = [t for t in state["transactions"] if is_purchase(t) and t["tx_id"] not in state.get("matches", {})]
    return "hunter" if missing and state.get("hunt", True) else "file_receipts"


def hunter(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    """ReAct agent: thinks about where a missing receipt could be and uses the Gmail tools to find it."""
    history = state.get("messages") or []
    new = []
    if not history:
        missing = [t for t in state["transactions"]
                   if is_purchase(t) and t["tx_id"] not in state.get("matches", {})][:HUNTER_MAX_TX]
        tools.emit("hunt", f"Searching deeper for {len(missing)} missing receipt(s)")
        new = [SystemMessage(prompts.HUNTER),
               HumanMessage(f"Window: {_window(state)}\nMissing (tx_id|date|card text|amount):\n" + "\n".join(
                   f"{t['tx_id']}|{t['date']}|{t['merchant']}|{t['amount']} {t.get('currency') or ''}"
                   + (f" ({t['orig_amount']} {t['orig_currency']})" if t.get("orig_amount") else "")
                   for t in missing))]
    ctx = runtime.context
    messages = history + new
    def think(model):
        tools.budget(model).acquire(tools._estimate(*(m.content for m in messages), out=700))
        return model.bind_tools(tools.HUNTER_TOOLS).invoke(messages)
    reply = tools.with_daily_fallback(ctx.smart, think)
    steps = state.get("hunter_steps", 0) + 1
    if not reply.tool_calls or steps >= HUNTER_MAX_STEPS:
        tools.emit("hunt", "Deeper search finished")
    return {"messages": new + [reply], "hunter_steps": steps}


def route_hunter(state: AuditState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state.get("hunter_steps", 0) < HUNTER_MAX_STEPS:
        return "tools"
    return "file_receipts"


def build_rows(transactions: list[dict], receipts: dict, matches: dict) -> list[dict]:
    rows = []
    for t in transactions:
        m = matches.get(t["tx_id"])
        rc = receipts.get(m["receipt_id"]) if m and m.get("receipt_id") else None
        if not is_purchase(t) and not rc:
            continue
        rows.append({**t, "status": m["status"] if rc else (m or {}).get("status", "missing"),
                     "confidence": m["confidence"] if m else 0.0, "reason": (m or {}).get("reason", ""),
                     "by": (m or {}).get("by", ""), "receipt": rc})
    return rows


def file_receipts(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    receipts = {k: dict(v) for k, v in unique_receipts(state.get("receipts", {})).items()}
    tools.emit("save", f"Saving {len(receipts)} receipt(s) to Google Drive")
    for rc in receipts.values():
        if not rc.get("drive_link"):
            try:
                rc["drive_link"] = tools.file_receipt(runtime.context.creds, rc)
                tools.emit("save", f"Saved to Drive: {tools.receipt_filename(rc)}", "ok")
            except Exception as e:
                tools.emit("save", f"Could not save {rc['merchant']}: {tools.friendly_error(e)}", "warn")
    return {"receipts": receipts}


def route_after_filing(state: AuditState) -> str:
    return "send_to_fortnox" if state.get("fortnox") else "write_log"


def push_to_fortnox(fx, creds, rows: list[dict], log) -> None:
    """Matched receipts go to the Fortnox voucher inbox once (fortnox_id marks them as sent).
    Suggestions wait until the owner confirms them; owner photos are sent by the UI at upload time."""
    for r in rows:
        rc = r.get("receipt")
        if r["status"] != "matched" or not rc or rc.get("fortnox_id") or rc["rc_id"].startswith("photo-"):
            continue
        try:
            rc["fortnox_id"] = fx.upload(tools.receipt_filename(rc), tools.receipt_content(creds, rc))
            log(f"Sent to Fortnox: {tools.receipt_filename(rc)}")
        except Exception as e:
            log(f"Could not send {rc['merchant']} to Fortnox: {tools.friendly_error(e)}")


def send_to_fortnox(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    receipts = {k: dict(v) for k, v in state.get("receipts", {}).items()}
    rows = build_rows(state["transactions"], receipts, state.get("matches", {}))
    push_to_fortnox(runtime.context.fortnox, runtime.context.creds, rows,
                    lambda text: tools.emit("save", text, "warn" if text.startswith("Could not") else "ok"))
    return {"receipts": receipts}


def write_log(state: AuditState, runtime: Runtime[AgentContext]) -> dict:
    creds = runtime.context.creds
    receipts = unique_receipts(state.get("receipts", {}))
    rows = build_rows(state["transactions"], receipts, state.get("matches", {}))
    tools.emit("save", "Updating the receipt log in Google Sheets")
    links = {"sheet": tools.write_sheet(creds, rows, list(receipts.values())),
             "folder": tools.root_folder_link(creds)}
    tools.emit("save", "Receipt log updated", "ok")
    return {"links": links}


def build_graph():
    g = StateGraph(AuditState, context_schema=AgentContext)
    g.add_node("plan_queries", plan_queries)
    g.add_node("search_inbox", search_inbox)
    g.add_node("triage", triage)
    g.add_node("extract_one", extract_one)
    g.add_node("reconcile", reconcile)
    g.add_node("hunter", hunter)
    g.add_node("tools", ToolNode(tools.HUNTER_TOOLS))
    g.add_node("file_receipts", file_receipts)
    g.add_node("send_to_fortnox", send_to_fortnox)
    g.add_node("write_log", write_log)

    g.add_edge(START, "plan_queries")
    g.add_edge("plan_queries", "search_inbox")
    g.add_edge("search_inbox", "triage")
    g.add_conditional_edges("triage", fan_out, ["extract_one", "reconcile"])
    g.add_edge("extract_one", "reconcile")
    g.add_conditional_edges("reconcile", route_after_reconcile, ["hunter", "file_receipts"])
    g.add_conditional_edges("hunter", route_hunter, ["tools", "file_receipts"])
    g.add_edge("tools", "hunter")
    g.add_conditional_edges("file_receipts", route_after_filing, ["send_to_fortnox", "write_log"])
    g.add_edge("send_to_fortnox", "write_log")
    g.add_edge("write_log", END)
    return g.compile()


GRAPH = build_graph()


# ---------------------------------------------------------------- entry points

def print_progress(stage: str, text: str, level: str = "info") -> None:
    print(f"[{stage}] {text}")


def run(creds, groq_key: str, transactions: list[dict], since: dt.date, until: dt.date,
        progress=print_progress, hunt: bool = True, fortnox=None) -> dict:
    """The nightly job. Reports progress(stage, text, level) and returns rows for the UI.
    Errors are raised as RuntimeError with a message for the owner (AI provider issues are named)."""
    home = Counter(t.get("currency") or "SEK" for t in transactions).most_common(1)[0][0] if transactions else "SEK"
    ctx = make_context(creds, groq_key, home, fortnox)
    state: dict = {"transactions": transactions, "since": since.isoformat(), "until": until.isoformat(),
                   "hunt": hunt, "fortnox": fortnox is not None}
    final, start = state, tools.tokens_used()
    token = tools.on_progress(progress)
    try:
        for final in GRAPH.stream(state, config={"max_concurrency": 2, "recursion_limit": 60},
                                  context=ctx, stream_mode="values"):
            pass
    except Exception as e:
        message = tools.friendly_error(e)
        progress("error", message, "error")
        raise RuntimeError(message) from e
    finally:
        tools._progress.reset(token)
    progress("done", f"Done. AI usage this run: about {tools.tokens_used() - start:,} tokens", "ok")
    receipts = unique_receipts(final.get("receipts", {}))
    return {"rows": build_rows(transactions, receipts, final.get("matches", {})),
            "receipts": list(receipts.values()), **final.get("links", {})}


def sync(creds, rows: list[dict], receipts: list[dict], log=print, fortnox=None) -> dict:
    """After the owner fixes misses in the UI: file anything new, send confirmed receipts, rewrite the sheet."""
    for rc in receipts:
        if not rc.get("drive_link"):
            rc["drive_link"] = tools.file_receipt(creds, rc)
            log(f"Filed in Drive: {tools.receipt_filename(rc)}")
    if fortnox:
        push_to_fortnox(fortnox, creds, rows, log)
    return {"sheet": tools.write_sheet(creds, rows, receipts), "folder": tools.root_folder_link(creds)}


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    import fortnox

    load_dotenv(".env")
    if len(sys.argv) < 2:
        sys.exit("usage: python agent.py <statement.csv|xlsx|pdf> [days_back]")
    creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token", client_id=os.environ["GOOGLE_CLIENT_ID"],
                        client_secret=os.environ["GOOGLE_CLIENT_SECRET"], scopes=tools.SCOPES)
    creds.refresh(Request())
    key = os.environ["GROQ_API_KEY"]
    tx = load_statement(sys.argv[1], sys.argv[1], make_context(creds, key))
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    result = run(creds, key, tx, dt.date.today() - dt.timedelta(days=days), dt.date.today(),
                 fortnox=fortnox.from_saved_token())
    done = sum(r["status"] == "matched" for r in result["rows"])
    print(f"\n{done} of {len(result['rows'])} transactions have a receipt. Sheet: {result.get('sheet')}")
