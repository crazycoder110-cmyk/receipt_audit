"""Demo inbox for sample_mynt_export.csv: receipt emails (body or PDF) for most card lines, a few deliberate gaps.

  python demo_inbox.py            # write demo_inbox/ (PDFs + SEND_ME.md to send by hand)
  python demo_inbox.py --check    # run every email through the real extraction prompt (Groq)
  python demo_inbox.py --send     # send them via SMTP (SMTP_USER + SMTP_PASSWORD = Gmail app password)

Expected result: 8 matched, Bolt "check" (129 vs 132), Circle K + parking missing -> one-tap fixes."""
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

import tools

load_dotenv(".env")
OUT = Path("demo_inbox")
TO = os.getenv("DEMO_TO", "crazycoder110@gmail.com")
NOTE = "\n\n-- invoice_audit demo receipt --"

# (subject, body, pdf_name, pdf_text). Circle K and parking are left out on purpose.
EMAILS = [
    ("Kvitto för din resa med SJ",
     "Hej!\nTack för att du reser med SJ.\n\nKvitto\nOrdernummer: SJ-7Q4K2M\nDatum: 2026-10-02\n"
     "Stockholm C - Uppsala C, 2026-10-02 08:12\n1 vuxen, 2 klass\n\nTotalt: 349,00 kr\nVarav moms 6 %: 19,75 kr\n"
     "Betalt med kort **** 4417", None, None),
    ("Your Slack invoice", "Hi, your invoice for Slack Pro is attached. Thanks for using Slack.",
     "Slack_invoice_SL-88412.pdf",
     "INVOICE SL-88412\nSlack Technologies\nInvoice date: Oct 6, 2026\nBill to: Demo AB\n\n"
     "Slack Pro - 1 user - Oct 6 to Nov 5, 2026      USD 8.75\nTax                                              USD 0.00\n"
     "Total paid                                       USD 8.75\nPaid with Visa ending 4417"),
    ("Your Wednesday evening trip with Uber",
     "Thanks for riding, Demo\n\nTotal SEK 186.00\nOct 8, 2026\n\nTrip fare 159.20\nBooking fee 12.00\nTip 14.80\n"
     "VAT (6%) included 10.53\n\nPickup 18:42 Kungsgatan 12, Stockholm\nDropoff 19:01 Hornsgatan 80, Stockholm\n"
     "Payment: Visa ••••4417", None, None),
    ("Scandic - kvitto för din vistelse", "Hej Demo,\nTack för din vistelse. Kvittot finns bifogat.\nVälkommen åter!",
     "Scandic_kvitto_88213.pdf",
     "KVITTO / RECEIPT\nScandic Continental, Stockholm\nKvittonr: 88213\nIncheckning: 2026-10-11  Utcheckning: 2026-10-12\n\n"
     "Logi 1 natt, standardrum        1 280,00\nFrukost                            170,00\n\nSumma SEK                        1 450,00\n"
     "Varav moms 12 %                  155,36\nBetalning: Visa **** 4417  2026-10-12"),
    ("Booking confirmation - SK1417 Stockholm-Copenhagen",
     "Thank you for flying SAS.\n\nBooking reference: K8L2PQ\nIssued: 2026-10-14\nPassenger: DEMO PERSON\n"
     "SK1417 ARN-CPH 2026-10-21 07:05\nSK1426 CPH-ARN 2026-10-23 18:30\n\nFare 1 840.00\nTaxes and fees 475.00\n"
     "Total paid SEK 2 315.00\nCard Visa xxxx4417", None, None),
    ("Din resa med Bolt", "Tack för att du åkte med Bolt!\n\n15 okt 2026, 22:14\nFrån: Stureplan\nTill: Södermalm\n\n"
     "Pris 129,00 kr\nVarav moms 6 %: 7,30 kr\nBetalt: Visa •••• 4417", None, None),
    ("Tack för ditt köp hos Clas Ohlson",
     "Tack för ditt köp!\nOrder 4471-2290\n2026-10-20\n\nForlängningskabel 5 m      199,00\nLED-lampa E27 3-pack      260,00\n\n"
     "Totalt 459,00 kr\nVarav moms 25 % 91,80 kr\nBetalsätt: Kort", None, None),
    ("Google Workspace: Your invoice is available", "Your Google Workspace invoice for October is attached.",
     "Google_Workspace_invoice_5122334.pdf",
     "Invoice number: 5122334\nGoogle Cloud EMEA Limited\nInvoice date: Oct 24, 2026\nBilling period: Sep 24 - Oct 23, 2026\n\n"
     "Google Workspace Business Standard  4 users     1 104.00 SEK\nVAT (25%)                                          276.00 SEK\n"
     "Total in SEK                                      1 380.00 SEK\nPaid by Visa ****4417"),
    ("Your ChatGPT Plus receipt", "OpenAI\nReceipt #2741-5560\nDate paid: October 27, 2026\n\nChatGPT Plus Subscription\n"
     "Oct 27 - Nov 27, 2026          $20.00\nTax                              $0.00\nAmount paid      $20.00 USD\n"
     "Payment method: Visa - 4417", None, None),
    # noise: triage should skip these
    ("Höstrea! Upp till 50 % på allt", "Missa inte vår höstrea. Handla nu på webben. Erbjudandet gäller till 31/10.",
     None, None),
    ("Your verification code", "Your verification code is 482913. It expires in 10 minutes.", None, None),
]


def build() -> None:
    OUT.mkdir(exist_ok=True)
    lines = [f"# Demo emails - send each to {TO}\n"]
    for i, (subject, body, pdf_name, pdf_text) in enumerate(EMAILS, 1):
        if pdf_name:
            (OUT / pdf_name).write_bytes(tools.text_pdf("", pdf_text + NOTE))
        lines += [f"## {i}. {subject}", f"Attach: demo_inbox/{pdf_name}" if pdf_name else "", "```", body, "```", ""]
    (OUT / "SEND_ME.md").write_text("\n".join(lines))
    print(f"wrote {OUT}/ ({sum(1 for e in EMAILS if e[2])} PDFs + SEND_ME.md)")


def check() -> None:
    llm = __import__("agent").make_context(None, os.environ["GROQ_API_KEY"], "SEK").fast
    for subject, body, pdf_name, pdf_text in EMAILS:
        text = tools.compact(body + ("\n" + pdf_text + NOTE if pdf_text else ""))
        doc = tools.structured(llm, tools.ExtractedDocument, tools.prompts.EXTRACT, f"Subject: {subject}\n{text}")
        print(f"{'RECEIPT' if doc.is_financial_document else 'skip   '} {doc.date} {doc.merchant} "
              f"{doc.total_amount} {doc.currency} vat={doc.tax_amount}  <- {subject}")
    print(f"≈{tools.tokens_used()} tokens")


def send() -> None:
    user, password = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        for subject, body, pdf_name, _ in EMAILS:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = user, TO, subject
            msg.set_content(body)
            if pdf_name:
                msg.add_attachment((OUT / pdf_name).read_bytes(), maintype="application", subtype="pdf",
                                   filename=pdf_name)
            smtp.send_message(msg)
            print("sent:", subject)


if __name__ == "__main__":
    build()
    if "--check" in sys.argv:
        check()
    if "--send" in sys.argv:
        send()
