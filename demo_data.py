"""Sample receipts for "Try with sample data": what an inbox scan would return for sample_mynt_export.csv."""

RECEIPTS = [
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
for i, r in enumerate(RECEIPTS):
    r.update(rc_id=f"demo{i}", subject=f"Receipt from {r['merchant']}", sender=r["merchant"])
    r.setdefault("vat", None)
