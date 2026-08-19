from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'app/main.py').read_text(encoding='utf-8')
JS=(ROOT/'app/static/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'app/static/app.css').read_text(encoding='utf-8')


def test_open_invoice_is_one_request_and_modal_opens_immediately():
    b=re.search(r'async function openInvoice\(invoiceNo, sourceButton=null\).*?(?=\n\nfunction showInvoice)',JS,re.S).group(0)
    assert 'openModal();' in b
    assert 'waitForModalPaint()' in b
    assert '/operations' in b
    assert 'Promise.all([' not in b
    assert 'جاري فتح العمليات' in b


def test_operational_refresh_is_lightweight():
    backend=re.search(r'@app\.get\("/api/bootstrap"\).*?(?=\n\n@app\.get\("/api/sales-reps"\))',MAIN,re.S).group(0)
    assert 'light: bool = False' in backend
    assert 'if light:' in backend
    assert "'/api/bootstrap?light=true'" in JS or '"/api/bootstrap?light=true"' in JS
    assert 'refreshOperationalState()' in JS


def test_image_preparation_reuses_inflight_work_and_uses_smaller_payload():
    assert 'optimizedImagePromiseCache' in JS
    assert 'optimizedImageForFile(file)' in JS
    assert '650 * 1024' in JS
    assert 'quality=0.68' in JS


def test_multiple_independent_images_upload_in_parallel_on_server():
    helper=re.search(r'def save_uploads_parallel\(.*?(?=\n\ndef recover_existing_photo_links)',MAIN,re.S).group(0)
    assert 'ThreadPoolExecutor' in helper
    assert 'max_workers=min(3' in helper
    assert 'save_uploads_parallel(invoice_no' in MAIN


def test_action_buttons_have_immediate_busy_feedback_and_recover_on_error():
    assert "setSubmitting(form, true" in JS
    setter=re.search(r'function setSubmitting\(.*?(?=\n\nfunction bindLiveFilterControls)',JS,re.S).group(0)
    assert 'btn.disabled = true' in setter
    assert 'btn.disabled = false' in setter
    assert '.operation-loading' in CSS and '.mini-spinner' in CSS
