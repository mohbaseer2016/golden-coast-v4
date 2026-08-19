import io
import os
import uuid
from datetime import datetime
from urllib.parse import quote

import httpx
from PIL import Image, UnidentifiedImageError
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


class SupabaseStorage:
    """Uploads invoice images to a Supabase Storage public bucket."""

    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "invoice-attachments")

        if not self.supabase_url or not self.service_role_key:
            raise RuntimeError(
                "إعداد Supabase Storage غير مكتمل. أضف SUPABASE_URL وSUPABASE_SERVICE_ROLE_KEY."
            )

    @staticmethod
    def _compress_image(raw: bytes) -> bytes:
        try:
            source = Image.open(io.BytesIO(raw))
            source.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("الملف المرفوع ليس صورة صالحة أو صيغة الصورة غير مدعومة.") from exc

        # المتصفح يضغط الصور قبل الإرسال. لا نعيد ضغط JPEG صغير بلا داعٍ.
        if (source.format in ("JPEG", "JPG") and len(raw) <= 950 * 1024
                and max(source.size) <= 1280 and source.mode in ("RGB", "L")):
            return raw

        image = source.convert("RGB")
        image.thumbnail((1280, 1280))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=68, optimize=False)
        return output.getvalue()


    def _public_url(self, object_path: str) -> str:
        encoded_path = quote(object_path, safe="/")
        return f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{encoded_path}"

    def list_existing_images(self, invoice_no: str, at: datetime | None = None) -> list[dict[str, str]]:
        """List an invoice folder once so multiple missing photo links can be recovered cheaply."""
        if not at:
            return []
        safe_invoice = "".join(c for c in str(invoice_no) if c.isalnum() or c in ("-", "_")) or "invoice"
        prefix = f"{at.year}/{at.month:02d}/{safe_invoice}"
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.supabase_url}/storage/v1/object/list/{self.bucket}"
        body = {
            "prefix": prefix,
            "limit": 200,
            "offset": 0,
            "sortBy": {"column": "created_at", "order": "desc"},
        }
        try:
            response = httpx.post(url, json=body, headers=headers, timeout=6.0)
            if response.status_code != 200:
                return []
            rows = response.json()
        except (httpx.RequestError, ValueError):
            return []

        result = []
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get("name") or "")
            if name:
                result.append({"name": name, "url": self._public_url(f"{prefix}/{name}")})
        return result

    def find_existing_image(self, invoice_no: str, kinds: list[str], at: datetime | None = None) -> str | None:
        """Find an already-stored invoice image without creating/copying any object."""
        normalized = tuple(f"{kind}_" for kind in kinds)
        for row in self.list_existing_images(invoice_no, at):
            if row["name"].startswith(normalized):
                return row["url"]
        return None


    def upload_image(self, invoice_no: str, kind: str, raw: bytes) -> str:
        now = datetime.now()
        safe_invoice = "".join(c for c in invoice_no if c.isalnum() or c in ("-", "_")) or "invoice"
        filename = f"{kind}_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        object_path = f"{now.year}/{now.month:02d}/{safe_invoice}/{filename}"
        encoded_path = quote(object_path, safe="/")

        payload = self._compress_image(raw)
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "image/jpeg",
            "x-upsert": "false",
        }
        upload_url = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{encoded_path}"

        try:
            response = httpx.post(upload_url, content=payload, headers=headers, timeout=25.0)
        except httpx.RequestError as exc:
            raise RuntimeError(f"تعذر الاتصال بـ Supabase Storage: {exc}") from exc

        if response.status_code not in (200, 201):
            detail = response.text[:500]
            raise RuntimeError(f"فشل رفع الصورة ({response.status_code}): {detail}")

        return f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{encoded_path}"
