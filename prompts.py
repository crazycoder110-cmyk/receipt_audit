"""LLM instructions. Short on purpose (Groq free tier: 8K tokens/min per model) and language/country agnostic:
no keyword lists, no column names, no assumed currency or tax system."""

RULES = ("Bookkeeping agent. Documents can be in any language, country, currency or tax system "
         "(VAT, moms, GST, MwSt...). Never invent values: unknown -> null. Dates YYYY-MM-DD. "
         "Amounts as numbers with '.' decimal. Currency as ISO 4217.")

PLAN_QUERIES = RULES + (" Write up to 5 Gmail queries to find receipts for these card descriptors. One brand per "
                        "query, like: from:(uber.com) OR \"Uber\". Infer the real brand and sender domain. No dates.")

TRIAGE = RULES + (" Email lines are 'n|sender|subject'. Return the n of every email that may be a receipt, invoice, "
                  "paid order, priced booking or payment confirmation. Order and booking confirmations count. "
                  "Emails from the card payments' merchants (brand names can differ from card text) almost always "
                  "count. When unsure, include it (the next step checks). Skip marketing, shipping updates, OTP, personal.")

EXTRACT = RULES + (" Extract the purchase this email documents. is_financial_document=true only for proof of a "
                   "purchase or charge (not ads, not refunds, not unpaid quotes). total_amount = final amount paid "
                   "incl. tax. tax_amount = total VAT/GST/sales tax. date = purchase date.")

RECONCILE = RULES + (" For each card transaction pick the receipt_id from its candidates, or null. Amount is the "
                     "strongest signal; tips, FX and fees explain small gaps; a receipt in another currency fits if "
                     "the implied exchange rate is realistic (card FX fee up to ~3%); bookings can be paid days earlier; "
                     "card descriptors abbreviate brands. One receipt per transaction. confidence>=0.8 only when "
                     "certain; plausible but unsure -> still return it with 0.5-0.79 so the owner confirms. "
                     "reason max 12 words.")

HUNTER = RULES + (" Find receipts for the missing card transactions in Gmail (read-only). Search by brand or "
                  "sender domain within the date window, open promising emails, extract_receipt, then submit_match. "
                  "Max 2 searches per transaction. Never force a match. End with a one-line summary.")

STATEMENT = RULES + " Map the columns of this card statement export from its first rows (row numbers are 0-based)."

STATEMENT_PDF = RULES + (" List every money row in this statement (not balances or totals) and set its kind. "
                         "The text keeps the page layout: a value belongs to the column header above it. "
                         "amount = the money of that row (never a card number, balance or reference). A row's "
                         "description can continue on the next lines without amounts: join them; the merchant is "
                         "often there (e.g. UPI/ref/ then SHOP/...). "
                         "Merchant = the shop or service name from the description. Amounts positive.")

STATEMENT_KINDS = RULES + (" Rows are outgoing money from a bank or card statement: 'n|date|description|amount'. Give "
                           "every n a kind: purchase = paid to a shop, company or service (card, online, UPI, wallet "
                           "or bill payment, subscription, direct debit); cash = cash withdrawal; fee = bank fee, "
                           "interest or tax on a fee; transfer = to a private person or own account; top_up = money "
                           "added to a wallet; other = not a transaction (total, balance). Also a short name per "
                           "row (merchant or payee as people know it, e.g. Amazon Pay, Airtel), the statement "
                           "currency and whether dates are written day first.")
