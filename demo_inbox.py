"""Demo inboxes: receipt emails (body or PDF attachment) for card statements, with deliberate gaps.

  python demo_inbox.py [--set sample|lahdo]            # write demo_inbox/<set>/ (PDFs + SEND_ME.md)
  python demo_inbox.py --set lahdo --check             # run every email through the real extraction prompt
  python demo_inbox.py --set lahdo --send              # send via Gmail SMTP

Sending needs SMTP_USER + SMTP_PASSWORD (a Gmail app password) and DEMO_TO in .env. Send from a different
account than the inbox you test: mail you send to yourself is labelled "Sent", and the agent skips sent mail.

sample: sample_mynt_export.csv -> 8 matched, Bolt "check" (129 vs 132), Circle K + parking missing.
lahdo:  a Mynt PDF statement (Oct 2026, 25 card lines) -> 6 receipts: 5 in SEK, Anthropic in USD (FX, LLM judges).
"""
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv

import tools

load_dotenv(".env")
TO = os.getenv("DEMO_TO", "crazycoder110@gmail.com")
NOTE = "\n\n-- invoice_audit demo receipt --"

# (sender name, subject, body, pdf_name, pdf_text)
SETS = {
    "sample": [
        ("SJ", "Kvitto för din resa med SJ",
         "Hej!\nTack för att du reser med SJ.\n\nKvitto\nOrdernummer: SJ-7Q4K2M\nDatum: 2026-10-02\n"
         "Stockholm C - Uppsala C, 2026-10-02 08:12\n1 vuxen, 2 klass\n\nTotalt: 349,00 kr\nVarav moms 6 %: 19,75 kr\n"
         "Betalt med kort **** 4417", None, None),
        ("Slack", "Your Slack invoice", "Hi, your invoice for Slack Pro is attached. Thanks for using Slack.",
         "Slack_invoice_SL-88412.pdf",
         "INVOICE SL-88412\nSlack Technologies\nInvoice date: Oct 6, 2026\nBill to: Demo AB\n\n"
         "Slack Pro - 1 user - Oct 6 to Nov 5, 2026      USD 8.75\nTax                                              USD 0.00\n"
         "Total paid                                       USD 8.75\nPaid with Visa ending 4417"),
        ("Uber Receipts", "Your Wednesday evening trip with Uber",
         "Thanks for riding, Demo\n\nTotal SEK 186.00\nOct 8, 2026\n\nTrip fare 159.20\nBooking fee 12.00\nTip 14.80\n"
         "VAT (6%) included 10.53\n\nPickup 18:42 Kungsgatan 12, Stockholm\nDropoff 19:01 Hornsgatan 80, Stockholm\n"
         "Payment: Visa ••••4417", None, None),
        ("Scandic", "Scandic - kvitto för din vistelse", "Hej Demo,\nTack för din vistelse. Kvittot finns bifogat.\nVälkommen åter!",
         "Scandic_kvitto_88213.pdf",
         "KVITTO / RECEIPT\nScandic Continental, Stockholm\nKvittonr: 88213\nIncheckning: 2026-10-11  Utcheckning: 2026-10-12\n\n"
         "Logi 1 natt, standardrum        1 280,00\nFrukost                            170,00\n\nSumma SEK                        1 450,00\n"
         "Varav moms 12 %                  155,36\nBetalning: Visa **** 4417  2026-10-12"),
        ("SAS", "Booking confirmation - SK1417 Stockholm-Copenhagen",
         "Thank you for flying SAS.\n\nBooking reference: K8L2PQ\nIssued: 2026-10-14\nPassenger: DEMO PERSON\n"
         "SK1417 ARN-CPH 2026-10-21 07:05\nSK1426 CPH-ARN 2026-10-23 18:30\n\nFare 1 840.00\nTaxes and fees 475.00\n"
         "Total paid SEK 2 315.00\nCard Visa xxxx4417", None, None),
        ("Bolt", "Din resa med Bolt", "Tack för att du åkte med Bolt!\n\n15 okt 2026, 22:14\nFrån: Stureplan\nTill: Södermalm\n\n"
         "Pris 129,00 kr\nVarav moms 6 %: 7,30 kr\nBetalt: Visa •••• 4417", None, None),
        ("Clas Ohlson", "Tack för ditt köp hos Clas Ohlson",
         "Tack för ditt köp!\nOrder 4471-2290\n2026-10-20\n\nForlängningskabel 5 m      199,00\nLED-lampa E27 3-pack      260,00\n\n"
         "Totalt 459,00 kr\nVarav moms 25 % 91,80 kr\nBetalsätt: Kort", None, None),
        ("Google Workspace", "Google Workspace: Your invoice is available",
         "Your Google Workspace invoice for October is attached.",
         "Google_Workspace_invoice_5122334.pdf",
         "Invoice number: 5122334\nGoogle Cloud EMEA Limited\nInvoice date: Oct 24, 2026\nBilling period: Sep 24 - Oct 23, 2026\n\n"
         "Google Workspace Business Standard  4 users     1 104.00 SEK\nVAT (25%)                                          276.00 SEK\n"
         "Total in SEK                                      1 380.00 SEK\nPaid by Visa ****4417"),
        ("OpenAI", "Your ChatGPT Plus receipt", "OpenAI\nReceipt #2741-5560\nDate paid: October 27, 2026\n\nChatGPT Plus Subscription\n"
         "Oct 27 - Nov 27, 2026          $20.00\nTax                              $0.00\nAmount paid      $20.00 USD\n"
         "Payment method: Visa - 4417", None, None),
        # noise: triage should skip these
        ("Webbutiken", "Höstrea! Upp till 50 % på allt",
         "Missa inte vår höstrea. Handla nu på webben. Erbjudandet gäller till 31/10.", None, None),
        ("Security", "Your verification code", "Your verification code is 482913. It expires in 10 minutes.", None, None),
    ],
    "lahdo": [
        ("Radisson Blu Arlandia", "Kvitto - Radisson Blu Arlandia Hotel",
         "Hej,\nTack för ditt besök i vår restaurang. Kvittot finns bifogat.\n\nVänliga hälsningar\nRadisson Blu Arlandia Hotel",
         "Radisson_Arlandia_kvitto_40917.pdf",
         "KVITTO\nRadisson Blu Arlandia Hotel - Restaurang & Bar\nArlanda Stad\nKvittonr: 40917   Bord 12\n"
         "Datum: 2026-10-05  20:41\n\n2 x Dagens fisk                  2 x 295,00      590,00\n2 x Entrecôte                   2 x 225,00      450,00\n"
         "2 x Glas vin (rött)             2 x 134,90      269,80\n\nTotalt SEK                                     1 309,80\n"
         "Moms 12 %   underlag 928,57          111,43\nMoms 25 %   underlag 215,84           53,96\n"
         "Kort: Mastercard **** 1622"),
        ("Anthropic", "Your receipt from Anthropic #2481-7734",
         "Anthropic, PBC\nReceipt #2481-7734\nDate paid: October 10, 2026\n\nClaude Pro - monthly\nOct 10 - Nov 10, 2026"
         "          $20.00\n\nSubtotal                         $20.00\nVAT - Sweden (25%)                $5.00\n"
         "Total                            $25.00\nAmount paid                      $25.00 USD\n\n"
         "Payment method: Mastercard - 1622", None, None),
        ("Vy", "Kvitto på din resa med Vy",
         "Hej!\nHär är kvittot för din resa.\n\nBokningsnummer: VY-K44RT8\nKöpdatum: 2026-10-14\n"
         "Norrköping C - Stockholm C, 2026-10-14 07:32\n1 vuxen, 2 klass, flexbiljett\n\nPris: 420,00 kr\n"
         "Varav moms 6 %: 23,77 kr\nBetalsätt: Mastercard **** 1622\n\nTrevlig resa!\nVy", None, None),
        ("Dropbox", "Your Dropbox receipt", "Hi Lahdo & Partners,\nThanks for your payment. Your receipt is attached.\n\n"
         "- The Dropbox team", "Dropbox_receipt_GZ8R4K.pdf",
         "RECEIPT\nDropbox International Unlimited Company\nReceipt number: GZ8R4K-0023\nDate paid: Oct 23, 2026\n"
         "Billed to: Lahdo & Partners\n\nDropbox Business Standard - 3 licenses, monthly     SEK 1 090.62\n"
         "VAT 25%                                             SEK   272.66\n"
         "Total paid                                          SEK 1 363.28\nPayment method: Mastercard ending in 1622"),
        ("Bergs Gård Trosa", "Ditt kvitto från Bergs Gård",
         "Tack för besöket på Bergs Gård!\n\nKvitto nr 2026-1187\nDatum: 2026-10-24  13:05\n\n"
         "Lunch, dagens rätt     5 st x 245,00     1 225,00\nKaffe och kaka         5 st x 30,00        150,00\n\n"
         "Summa: 1 375,00 kr\nVarav moms 12 %: 147,32 kr\nBetalt med kort ****1622\n\nVälkommen åter!\nBergs Gård, Trosa",
         None, None),
        ("Volvo Cars", "Volvo Cars - receipt for your service plan",
         "Hello,\nThank you for your purchase. Your receipt is attached.\n\nVolvo Cars Customer Service",
         "Volvo_Cars_receipt_SE-77120.pdf",
         "RECEIPT\nVolvo Car Corporation\nReceipt no: SE-77120\nDate: 2026-10-19\n\n"
         "Volvo Cars app - Connected services, 12 months          344,00\nMoms 25 %                                                 86,00\n"
         "Total SEK                                               430,00\nPaid with card **** 1622"),
    ],
}


def emails(name: str) -> list:
    return SETS[name]


def build(name: str) -> Path:
    out = Path("demo_inbox") / name
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Demo emails ({name}) - send each to {TO}\n"]
    for i, (sender, subject, body, pdf_name, pdf_text) in enumerate(emails(name), 1):
        if pdf_name:
            (out / pdf_name).write_bytes(tools.text_pdf("", pdf_text + NOTE))
        lines += [f"## {i}. {subject}  (from: {sender})", f"Attach: {out}/{pdf_name}" if pdf_name else "",
                  "```", body, "```", ""]
    (out / "SEND_ME.md").write_text("\n".join(lines))
    print(f"wrote {out}/ ({sum(1 for e in emails(name) if e[3])} PDFs + SEND_ME.md)")
    return out


def check(name: str) -> None:
    llm = __import__("agent").make_context(None, os.environ["GROQ_API_KEY"], "SEK").fast
    for sender, subject, body, pdf_name, pdf_text in emails(name):
        text = tools.compact(body + ("\n" + pdf_text + NOTE if pdf_text else ""))
        doc = tools.structured(llm, tools.ExtractedDocument, tools.prompts.EXTRACT,
                               f"From: {sender}\nSubject: {subject}\n{text}")
        print(f"{'RECEIPT' if doc.is_financial_document else 'skip   '} {doc.date} {doc.merchant} "
              f"{doc.total_amount} {doc.currency} vat={doc.tax_amount}  <- {subject}")
    print(f"≈{tools.tokens_used()} tokens")


def send(name: str, out: Path) -> None:
    user, password = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"].replace(" ", "")
    if user.lower() == TO.lower():
        sys.exit("SMTP_USER and DEMO_TO are the same account: the agent skips mail you sent yourself.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        for sender, subject, body, pdf_name, _ in emails(name):
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = formataddr((sender, user)), TO, subject
            msg.set_content(body + NOTE)
            if pdf_name:
                msg.add_attachment((out / pdf_name).read_bytes(), maintype="application", subtype="pdf",
                                   filename=pdf_name)
            smtp.send_message(msg)
            print("sent:", subject)


if __name__ == "__main__":
    name = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else "sample"
    folder = build(name)
    if "--check" in sys.argv:
        check(name)
    if "--send" in sys.argv:
        send(name, folder)
