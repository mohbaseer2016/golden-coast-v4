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


def test_hr_original_receipt_does_not_reupload_same_invoice():
    b=block(r'@app\.post\("/api/invoices/\{invoice_no\}/close"\).*?(?=\n@app\.)',MAIN)
    assert "original_document_photo: UploadFile" not in b
    assert 'save_upload(original_document_photo' not in b
    assert "invoice.receipt_photo or invoice.customer_receipt_photo or invoice.carrier_receipt_photo" in b
    close_form=block(r'function closeForm\(invoice\).*?(?=\n\nfunction customerReceiptForm)',JS)
    assert 'type="file"' not in close_form
    assert 'لا حاجة لتصويره أو رفعه مرة ثانية' in close_form


def test_old_storage_recovery_does_not_upload_and_is_batched():
    b=block(r'def recover_existing_photo_links\(.*?(?=\n\ndef upsert_user)',MAIN)
    assert "list_existing_images" in b
    assert "grouped" in b
    assert "save_upload(" not in b
    assert "upload_image(" not in b


def test_storage_recovery_is_read_only_list():
    b=block(r'    def list_existing_images\(.*?(?=\n    def find_existing_image)',DRIVE)
    assert "/storage/v1/object/list/" in b
    assert "httpx.post" in b
    assert "/storage/v1/object/" not in b.replace("/storage/v1/object/list/","")


def test_invoice_detail_shows_all_operational_photos_lazily():
    for field in [
        "original_document_photo","customer_receipt_photo","receipt_photo",
        "carrier_receipt_photo","source_return_photo","return_photo",
        "driver_return_photo","warehouse_photo"
    ]:
        assert f"invoice.{field}" in JS
    assert 'loading="lazy"' in JS
    assert 'decoding="async"' in JS


def test_generic_mobile_image_mime_supported():
    assert 'allowed_image_suffixes' in MAIN
    assert '".heic"' in MAIN and '".heif"' in MAIN and '".avif"' in MAIN
