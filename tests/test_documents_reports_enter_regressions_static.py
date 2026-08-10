from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"app/main.py").read_text(encoding="utf-8")
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")
CSS=(ROOT/"app/static/app.css").read_text(encoding="utf-8")

def test_documents_invoice_number_visible():
    assert "color:#0f4c81" in CSS
    assert 'data-no="${attr(x.invoice_no)}">${esc(x.invoice_no)}</button>' in JS

def test_legacy_original_photo_is_display_only():
    b=re.search(r'@app\.get\("/api/documents"\).*?(?=\n@app\.)',MAIN,re.S).group(0)
    assert "original_photo = inv.original_document_photo or inv.receipt_photo" in b
    assert '"legacy_photo": bool(' in b
    assert "save_upload(" not in b

def test_return_report_has_precise_states():
    assert "بانتظار محاسب المبيعات" in JS
    assert "لم يصل للمحاسب بعد" in JS
    assert "تم استلام المرتجع" in JS
    assert "حالة الفاتورة" in JS

def test_enter_search_is_global():
    for field in ["searchInput","queueFilter","usersFilter","vehiclesFilter","productsFilter","documentsFilter","salesRepsFilter","logsFilter","reportDriver","reportSalesRep","popupFilter"]:
        assert field in JS
    assert "document.addEventListener('keydown',handleSearchEnter)" in JS
