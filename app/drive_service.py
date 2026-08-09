import io
import os
import uuid
from datetime import datetime
from urllib.parse import quote

import httpx
from PIL import Image, UnidentifiedImageError


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
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("الملف المرفوع ليس صورة صالحة.") from exc

        image.thumbnail((1280, 1280))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=68, optimize=False)
        return output.getvalue()

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
