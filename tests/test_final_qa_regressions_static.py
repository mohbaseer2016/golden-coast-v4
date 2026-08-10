from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'app/main.py').read_text(encoding='utf-8')
JS=(ROOT/'app/static/app.js').read_text(encoding='utf-8')
HTML=(ROOT/'app/templates/index.html').read_text(encoding='utf-8')
CSS=(ROOT/'app/static/app.css').read_text(encoding='utf-8')

def test_reports_tab_is_switchable():
    block=re.search(r'function switchTab\(tab\).*?(?=\nfunction )',JS,re.S).group(0)
    assert "'reports'" in block
    assert 'id="reportsSection"' in HTML

def test_sqlalchemy_and_imported():
    assert 'from sqlalchemy import and_' in MAIN

def test_manifest_exists_for_mobile():
    assert '@app.get("/manifest.webmanifest")' in MAIN

def test_external_driver_identity_is_saved():
    b=re.search(r'@app\.post\("/api/invoices/\{invoice_no\}/warehouse"\).*?(?=\n@app\.)',MAIN,re.S).group(0)
    assert 'invoice.driver_code = "EXTERNAL_DRIVER"' in b
    assert 'invoice.driver_name = external_driver_name.strip()' in b
    assert 'invoice.external_driver_phone = external_driver_phone.strip()' in b

def test_dashboard_cards_have_permissions():
    for p in ['warehouse_card','drivers_card','returns_card','documents_card','closed_card']:
        assert p in MAIN
        assert p in JS

def test_global_five_day_alert_visible_outside_reports():
    assert 'id="globalWarehouseDelayAlertBox"' in HTML
    assert 'showWarehouseDelayAlertDetails' in JS
    assert 'timedelta(days=5)' in MAIN

def test_vehicle_delete_uses_stored_vehicle_no_not_missing_id():
    b=re.search(r'@app\.post\("/api/vehicles/\{vehicle_id\}/delete"\).*?(?=\n@app\.|\Z)',MAIN,re.S).group(0)
    assert 'Invoice.vehicle_id' not in b
    assert 'Invoice.vehicle_no.like' in b

def test_report_mobile_no_forced_page_overflow():
    assert '#reportsSection table{min-width:720px}' not in CSS
    assert '#reportsSection .table-wrap{overflow-x:auto!important' in CSS

def test_image_upload_optimized():
    for x in ['compressImageFileForUpload','optimizedFormData','Promise.all','createImageBitmap']:
        assert x in JS
