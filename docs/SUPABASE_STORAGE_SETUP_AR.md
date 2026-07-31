# تحديث V5 — Supabase Storage

تم حذف الاعتماد على Google Drive. الصور تُرفع الآن إلى Bucket باسم:

`invoice-attachments`

## متغيرات Render المطلوبة

- `APP_SECRET`: اضغط Generate في Render.
- `DATABASE_URL`: رابط Session Pooler الحقيقي، ويبدأ بـ `postgresql+psycopg://`.
- `SUPABASE_URL`: من Supabase → Project Settings → API → Project URL.
- `SUPABASE_SERVICE_ROLE_KEY`: من Supabase → Project Settings → API Keys → مفتاح `service_role` أو Secret key الخاص بالخادم.
- `SUPABASE_STORAGE_BUCKET`: القيمة `invoice-attachments`.
- `PUBLIC_BASE_URL`: رابط Render، مثل `https://golden-coast-v4.onrender.com`.

## مهم أمنيًا

`SUPABASE_SERVICE_ROLE_KEY` مفتاح سري قوي يتجاوز سياسات RLS. لا تضعه في GitHub ولا ترسله في المحادثات، بل ضعه فقط في Environment Variables داخل Render.

يمكن حذف المتغيرات القديمة التالية من Render:

- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_DRIVE_ROOT_FOLDER_ID`

كما يمكن حذف Secret File الخاص بـ Google من Render؛ لم يعد مستخدمًا.

## مسار الصور

يُنشئ النظام المسارات تلقائيًا بهذا الشكل:

`السنة/الشهر/رقم-الفاتورة/نوع-الصورة_التاريخ_رقم-عشوائي.jpg`

مثال:

`2026/07/10525/customer_receipt_20260731_214500_a1b2c3d4.jpg`

## رفع التحديث إلى GitHub

بعد استبدال ملفات المشروع بهذه النسخة، افتح Git Bash داخل المجلد ونفذ:

```bash
git add .
git commit -m "Replace Google Drive with Supabase Storage"
git push origin master
```

Render سيعيد النشر تلقائيًا إذا كان Auto Deploy مفعّلًا.
