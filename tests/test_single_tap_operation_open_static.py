from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'app/main.py').read_text(encoding='utf-8')
JS=(ROOT/'app/static/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'app/static/app.css').read_text(encoding='utf-8')


def test_dynamic_open_buttons_use_one_delegated_click_handler():
    assert "document.addEventListener('click', handleInvoiceOpenClick, true)" in JS
    assert "INVOICE_OPEN_SELECTOR" in JS
    assert "invoiceOpenButtonFromEvent(event)" in JS
    assert "body.querySelectorAll('.open').forEach" not in JS
    assert "document.querySelectorAll('.popup-open').forEach" not in JS


def test_repeated_tap_does_not_create_duplicate_open_request():
    b=re.search(r'async function openInvoice\(invoiceNo, sourceButton=null\).*?(?=\n\nfunction showInvoice)',JS,re.S).group(0)
    assert "invoiceOpeningPromise && invoiceOpeningNo === invoiceNo" in b
    assert "return invoiceOpeningPromise" in b
    assert "setInvoiceOpenButtonBusy(sourceButton, true)" in b


def test_operation_modal_backend_uses_single_endpoint():
    b=re.search(r'@app\.get\("/api/invoices/\{invoice_no\}/operations"\).*?(?=\n\n@app\.get\("/api/invoices/\{invoice_no\}"\))',MAIN,re.S).group(0)
    assert 'goods_movement_timeline(db, invoice)' in b
    assert 'InvoiceIssueItem.invoice_no == invoice_no' in b
    assert '"invoice": invoice_dict(invoice)' in b
    assert '"movement": movement' in b
    assert '"issues": [' in b


def test_open_buttons_are_touch_optimized_on_mobile_and_desktop():
    assert '.retry-open-invoice' in CSS
    assert 'touch-action:manipulation' in CSS
    assert '.operation-open-error' in CSS
