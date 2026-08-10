from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"app/main.py").read_text(encoding="utf-8")
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")
HTML=(ROOT/"app/templates/index.html").read_text(encoding="utf-8")
def test_permissions():
    for x in ["documents_card","returns_card","reports","reports_view","reports_pdf","warehouse_delay_alerts"]: assert x in MAIN
def test_reports_routes():
    for x in ["/api/reports/summary","/api/reports/returns","/api/reports/drivers","/api/alerts/warehouse-delay"]: assert x in MAIN
def test_five_day_alert():
    assert "timedelta(days=5)" in MAIN and 'Invoice.status == "WAREHOUSE_PENDING"' in MAIN
def test_mobile_report_ui():
    assert 'id="reportsTab"' in HTML and 'id="reportsSection"' in HTML
    assert "function runReport()" in JS and "function printCurrentReport()" in JS
def test_dashboard_card_permissions():
    assert "can('returns_card')" in JS and "can('documents_card')" in JS
