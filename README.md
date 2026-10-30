# 🧾 invoice_audit — AI receipt matching agent

An agent that reads a Gmail inbox, finds receipts, matches them against a card statement (Mynt export),
files them in Google Drive and keeps a Google Sheet log. The owner only handles the few misses.

```
Gmail (read-only) ─► pre-filter (price in mail?) ─► LLM extracts merchant/date/amount/VAT
                                                          │
Mynt / Pleo / bank export (CSV, Excel) ─────────────► match engine (amount › date › name)
                                                          │
                       ┌──────────── matched ────────────┼──────── check / missing ───────┐
                       ▼                                                                  ▼
     Drive: Kvitton - invoice_audit/2026/2026-10/               Home screen: one tap per miss
            2026-10-02 SJ 349.00 SEK.pdf                       (confirm · photo · no receipt)
     Sheet: invoice_audit - Receipt log
```

## Try it in 30 seconds

Open the app → **Try with sample data** → **Use sample Mynt export** → **Run agent now**.
You land on the home screen: *"8 of 11 transactions have a receipt"* plus the misses to fix.

With a real inbox: **Sign in with Google** → drop your Mynt export → **Run agent now**.

## Files

| File | What it does |
|---|---|
| `agent.py` | The agent: Gmail scan, LLM extraction (Groq), matching, Drive filing, Sheet log. Also a CLI for the nightly run. |
| `app.py` | Streamlit UI: 3-step onboarding, home screen, one-tap fixes, Swedish/English. |
| `sample_mynt_export.csv` | Sample statement in Mynt-style Swedish format (`;`, `1 450,00`, original currency). |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in the keys (see setup below)
streamlit run app.py
```

Nightly mode (same job, no UI) — e.g. cron `0 3 * * *`:

```bash
python agent.py path/to/mynt_export.csv 1     # 1 = look back one day
```

## Setup (one time)

1. **Groq** – create an API key at console.groq.com → `GROQ_API_KEY`.
2. **Google Cloud** (console.cloud.google.com), new project:
   - Enable **Gmail API**, **Google Drive API**, **Google Sheets API**.
   - *OAuth consent screen*: External, app name `invoice_audit`, add scopes `gmail.readonly` and `drive.file`,
     add every tester's Gmail under **Test users**.
   - *Credentials → OAuth client ID → Web application*. Authorised redirect URIs:
     `http://localhost:8501` and your deployed URL (e.g. `https://<app>.streamlit.app`).
   - Copy client ID/secret → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and set `REDIRECT_URI`.
3. **Deploy** on Streamlit Community Cloud (share.streamlit.io): point at this repo, `app.py`,
   paste the same keys into *Secrets* (TOML format). Streamlit apps need a long-running server,
   so Vercel (serverless) is not a fit for this UI.

## Design decisions

- **Onboarding in 3 taps**: Google sign-in (one consent screen covers Gmail + Drive) → drop the statement → run.
  No card-provider picker: the column detector reads Mynt, Pleo and bank exports, and falls back to the LLM to
  map unknown formats.
- **Least privilege**: `gmail.readonly` (cannot send/change/delete) and `drive.file` (only sees files the app
  created, not the user's whole Drive).
- **Store as little email as possible**: only extracted fields (merchant, date, amount, VAT, category) and the
  message id are kept. The email body/PDF lives in memory just long enough to be filed in the owner's own Drive.
- **Cheap and fast**: a regex pre-filter drops mails without any price before the LLM is called.
- **Honest matching**: score = 50% amount (also checks original currency, e.g. USD subscriptions) + 25% date
  (±7 days, bookings are often paid before travel) + 25% merchant-name similarity. ≥0.75 = matched,
  0.5–0.75 = *"Is this it?"* suggestion, otherwise missing. One receipt can only match one transaction.
- **Drive structure** an accountant understands: `Kvitton/<year>/<year-month>/<date> <merchant> <amount>.pdf`.
  Email receipts without a PDF attachment are archived as a PDF of the email text. Re-runs are idempotent.
- **Missing receipts**: one tap — confirm the suggestion, snap a photo (opens the camera on mobile, filed to the
  same Drive folder), or mark "no receipt". The Sheet is updated immediately.
- **GDPR**: "Disconnect & delete my data" revokes the Google token; nothing is stored server-side.

## Biggest risks

1. **Gmail access** – `gmail.readonly` is a *restricted* scope. Until the app passes Google verification plus an
   annual third-party security assessment (CASA), it is limited to 100 manually added test users and shows an
   "unverified app" warning. Start verification in week 1; it takes weeks. Microsoft (`Mail.Read`) needs publisher
   verification and, in many company tenants, admin consent.
2. **LLM data location** – Groq is fine for a demo, but GDPR requires EU processing in production
   (e.g. Claude on AWS Bedrock Frankfurt, Azure OpenAI EU, or Mistral).
3. **Fortnox** – each customer needs an integration licence and the app must be approved by Fortnox for
   multi-customer use. Mynt/Fortnox Företagskort already match receipts for their own card, so our edge must be
   *all cards + all inboxes + one simple screen*.
4. **Matching edge cases** – tips (Bolt/Uber), FX differences, split payments, one receipt covering several
   transactions. Handled today by the "check" state; to be measured on real Mynt exports.

## What I'd build next

1. Fortnox: upload receipts to the Fortnox Inbox (`/archive`) and attach them to vouchers (`/voucherfileconnections`).
2. Real nightly scheduler + database (Postgres in the EU) so decisions persist between runs, multi-tenant.
3. Microsoft 365 / Outlook and extra inboxes (one click each).
4. Pleo API + bank card feeds (open banking), so no statement upload is needed.
5. Learn from the owner's confirmations (merchant aliases like `BOLT.EU/O` → Bolt) to raise auto-match rate.

## Estimated running cost per user

~300 candidate emails/month × ~1.5k tokens ≈ 0.5M tokens → **≈ $0.3–0.5/user/month** for the LLM,
Google APIs are free at this volume, hosting a few cents per user at scale.
