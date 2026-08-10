from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"app/main.py").read_text(encoding="utf-8")
DRIVE=(ROOT/"app/drive_service.py").read_text(encoding="utf-8")
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")

def block(pattern, text):
    m=re.search(pattern,text,re.S)
    assert m, pattern
    return m.group(0)

def test_original_document_upload_restored():
    b=block(r'@app\.post\("/api/invoices/\{invoice_no\}/close"\).*?(?=\n@app\.)',MAIN)
    assert "original_document_photo: UploadFile | None = File(None)" in b
    assert 'save_upload(original_document_photo, invoice_no, "original_document")' in b
    assert "invoice.original_document_photo = original_image" in b

def test_old_storage_recovery_does_not_upload():
    b=block(r'def recover_existing_photo_links\(.*?(?=\n\ndef )',MAIN)
    assert "find_existing_image" in b
    assert "save_upload(" not in b
    assert "upload_image(" not in b

def test_storage_recovery_is_read_only_list():
    b=block(r'    def find_existing_image\(.*?(?=\n    def upload_image)',DRIVE)
    assert "/storage/v1/object/list/" in b
    assert "httpx.post" in b
    assert "/storage/v1/object/" not in b.replace("/storage/v1/object/list/","")

def test_close_form_photo_is_mobile_optimized():
    assert 'name="original_document_photo" type="file"' in JS
    assert "'closeForm'" in JS
    assert "optimizedFormData(form)" in JS

def test_invoice_detail_shows_all_operational_photos():
    for field in [
        "original_document_photo","customer_receipt_photo","receipt_photo",
        "carrier_receipt_photo","source_return_photo","return_photo",
        "driver_return_photo","warehouse_photo"
    ]:
        assert f"invoice.{field}" in JS

def test_generic_mobile_image_mime_supported():
    assert 'allowed_image_suffixes' in MAIN
    assert '".heic"' in MAIN and '".heif"' in MAIN and '".avif"' in MAIN
