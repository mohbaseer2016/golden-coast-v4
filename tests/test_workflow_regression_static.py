from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")

def block(pattern, text=MAIN):
    m = re.search(pattern, text, re.S)
    assert m, pattern
    return m.group(0)

def test_invoice_dict_exposes_parallel_closure_flags():
    b = block(r"def invoice_dict\(invoice: Invoice\):.*?(?=\n\ndef )")
    for field in [
        "sales_return_required", "sales_return_reviewed",
        "sales_return_reviewed_by", "sales_return_reviewed_at",
        "original_document_received", "original_document_received_by",
        "original_document_received_at", "customer_receipt_required",
        "customer_receipt_received", "delivery_discrepancy_required",
        "delivery_discrepancy_reviewed",
    ]:
        assert f'"{field}"' in b

def test_final_close_requires_all_independent_tracks():
    b = block(r"def maybe_close_invoice\(invoice: Invoice\):.*?(?=\n\ndef |\n@app\.)")
    assert "ready_physical_return" in b
    assert "ready_return" in b
    assert "ready_customer" in b
    assert "ready_discrepancy" in b
    assert "ready_document" in b

def test_warehouse_return_activates_sales_accountant_track():
    b = block(r'@app\.post\("/api/invoices/\{invoice_no\}/return"\).*?(?=\n@app\.)')
    assert "invoice.return_received = True" in b
    assert "invoice.sales_return_required = True" in b
    assert "invoice.sales_return_reviewed = False" in b

def test_sales_accountant_cannot_precede_warehouse():
    b = block(r'@app\.post\("/api/invoices/\{invoice_no\}/sales-return-review"\).*?(?=\n@app\.)')
    assert "if not invoice.return_received:" in b
    assert "invoice.sales_return_reviewed = True" in b
    assert "maybe_close_invoice(invoice)" in b

def test_transport_office_waits_for_rep_customer_receipt():
    b = block(r'@app\.post\("/api/invoices/\{invoice_no\}/driver"\).*?(?=\n@app\.)')
    assert 'delivery_target == "TRANSPORT_OFFICE"' in b
    assert "invoice.customer_receipt_required = True" in b
    assert '"CUSTOMER_RECEIPT_PENDING", "SALES_REP"' in b

def test_customer_transfer_requires_two_photos():
    b = block(r'@app\.post\("/api/invoices/\{invoice_no\}/customer-receipt"\).*?(?=\n@app\.)')
    assert "source_return_photo" in b
    assert "receipt_photo" in b

def test_frontend_sales_accountant_action_uses_exposed_flags():
    assert "invoice.sales_return_required && !invoice.sales_return_reviewed" in JS
    assert "تم عمل المردود — اعتماد محاسبي" in JS
