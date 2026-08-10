from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import shutil
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .drive_service import SupabaseStorage
from .models import AuditLog, Invoice, User, Vehicle, Product, InvoiceIssueItem, AppSetting, SalesRep
from .security import clear_session, hash_password, require_role, require_user, set_session, verify_password

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ROLES = {"ADMIN", "HR", "WAREHOUSE", "DRIVER", "SALES_ACCOUNTANT", "SALES_REP"}

PERMISSION_CATALOG = {
    "screens": {
        "queue": "المعلقة عندي", "search": "البحث والأرشيف", "users": "المستخدمون",
        "vehicles": "السيارات", "products": "الأصناف", "logs": "الحركات",
        "documents": "المستندات", "warehouse_card": "مربع المخزن",
        "drivers_card": "مربع السائقين", "returns_card": "مربع المرتجعات",
        "documents_card": "مربع المستندات", "closed_card": "مربع المكتملة",
        "reports": "التقارير والتنبيهات"
    },
    "actions": {
        "invoice_create": "إضافة فاتورة", "invoice_edit": "تعديل فاتورة",
        "invoice_delete": "حذف فاتورة", "warehouse_approve": "اعتماد المخزن",
        "driver_approve": "اعتماد السائق", "return_approve": "استلام المرتجع",
        "close_invoice": "استلام أصل الفاتورة", "sales_return_review": "اعتماد مردود المبيعات", "customer_receipt_upload": "رفع استلام العميل", "delivery_discrepancy_review": "مراجعة فرق التسليم", "manage_users": "إدارة المستخدمين والصلاحيات",
        "manage_vehicles": "إدارة السيارات", "manage_products": "إدارة الأصناف",
        "reports_view": "عرض التقارير", "reports_pdf": "طباعة التقارير PDF",
        "warehouse_delay_alerts": "عرض تنبيهات تأخر المخزن"
    }
}

ROLE_DEFAULTS = {
    "ADMIN": {"screens": list(PERMISSION_CATALOG["screens"]), "actions": list(PERMISSION_CATALOG["actions"])},
    "HR": {"screens": ["queue","search","documents","documents_card"], "actions": ["invoice_create","invoice_edit","close_invoice","delivery_discrepancy_review"]},
    "WAREHOUSE": {"screens": ["queue","search","warehouse_card","returns_card"], "actions": ["warehouse_approve","return_approve","warehouse_delay_alerts"]},
    "DRIVER": {"screens": ["queue","search","drivers_card"], "actions": ["driver_approve"]},
    "SALES_ACCOUNTANT": {"screens": ["queue","search","returns_card","reports"], "actions": ["sales_return_review","reports_view","reports_pdf","warehouse_delay_alerts"]},
    "SALES_REP": {"screens": ["queue","search"], "actions": ["customer_receipt_upload"]},
}

def effective_permissions(user_row: User | None, session_user: dict) -> dict:
    if session_user.get("username") == "admin":
        return ROLE_DEFAULTS["ADMIN"]
    defaults = ROLE_DEFAULTS.get(session_user.get("role"), {"screens": [], "actions": []})
    if not user_row or not user_row.permissions_json:
        return defaults
    try:
        custom = json.loads(user_row.permissions_json)
        return {"screens": custom.get("screens", []), "actions": custom.get("actions", [])}
    except Exception:
        return defaults

def require_permission(request: Request, db: Session, permission: str):
    session_user = require_user(request)
    row = db.scalar(select(User).where(User.username == session_user["username"]))
    perms = effective_permissions(row, session_user)
    if session_user.get("username") != "admin" and permission not in perms["actions"]:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية تنفيذ هذه العملية.")
    return session_user

def ensure_columns():
    """Lightweight migration for existing Supabase/Postgres and local SQLite databases."""
    with engine.begin() as conn:
        dialect = engine.dialect.name
        stmts = []
        if dialect == "postgresql":
            stmts = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions_json TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_rep_id INTEGER",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS return_qty_text VARCHAR(180)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(30)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_return_required BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_return_reviewed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_return_reviewed_by VARCHAR(80)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_return_reviewed_at TIMESTAMP",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_return_notes TEXT",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_rep_id INTEGER",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_rep_name VARCHAR(150)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_document_received_at TIMESTAMP",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_document_received_by VARCHAR(80)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_document_photo VARCHAR(255)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_discrepancy_notes TEXT",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_discrepancy_reviewed_by VARCHAR(80)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_discrepancy_reviewed_at TIMESTAMP",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_discrepancy_reviewed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_discrepancy_required BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_notes TEXT",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_match VARCHAR(30)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_received_by VARCHAR(80)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_received_at TIMESTAMP",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_photo VARCHAR(255)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_received BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_receipt_required BOOLEAN DEFAULT FALSE",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS carrier_receipt_photo VARCHAR(255)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_target VARCHAR(30)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS transport_office_name VARCHAR(180)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS external_driver_phone VARCHAR(40)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS goods_source VARCHAR(30)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source_customer VARCHAR(180)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source_return_photo VARCHAR(255)",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source_return_received_at TIMESTAMP",
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source_return_received_by VARCHAR(80)",
                "ALTER TABLE invoice_issue_items ADD COLUMN IF NOT EXISTS warehouse_match BOOLEAN",
                "ALTER TABLE invoice_issue_items ADD COLUMN IF NOT EXISTS actual_quantity VARCHAR(80)",
                "ALTER TABLE invoice_issue_items ADD COLUMN IF NOT EXISTS warehouse_note TEXT",
            ]
        elif dialect == "sqlite":
            cols_u = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
            cols_i = {r[1] for r in conn.execute(text("PRAGMA table_info(invoices)"))}
            cols_ii = {r[1] for r in conn.execute(text("PRAGMA table_info(invoice_issue_items)"))}
            if "permissions_json" not in cols_u: stmts.append("ALTER TABLE users ADD COLUMN permissions_json TEXT")
            if "sales_rep_id" not in cols_u: stmts.append("ALTER TABLE users ADD COLUMN sales_rep_id INTEGER")
            if "return_qty_text" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN return_qty_text VARCHAR(180)")
            if "delivery_mode" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_mode VARCHAR(30)")
            if "sales_return_required" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_return_required BOOLEAN DEFAULT 0")
            if "sales_return_reviewed" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_return_reviewed BOOLEAN DEFAULT 0")
            if "sales_return_reviewed_by" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_return_reviewed_by VARCHAR(80)")
            if "sales_return_reviewed_at" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_return_reviewed_at DATETIME")
            if "sales_return_notes" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_return_notes TEXT")
            if "sales_rep_id" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_rep_id INTEGER")
            if "sales_rep_name" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN sales_rep_name VARCHAR(150)")
            if "original_document_received_at" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN original_document_received_at DATETIME")
            if "original_document_received_by" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN original_document_received_by VARCHAR(80)")
            if "original_document_photo" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN original_document_photo VARCHAR(255)")
            if "delivery_discrepancy_notes" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_discrepancy_notes TEXT")
            if "delivery_discrepancy_reviewed_by" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_discrepancy_reviewed_by VARCHAR(80)")
            if "delivery_discrepancy_reviewed_at" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_discrepancy_reviewed_at DATETIME")
            if "delivery_discrepancy_reviewed" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_discrepancy_reviewed BOOLEAN DEFAULT 0")
            if "delivery_discrepancy_required" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_discrepancy_required BOOLEAN DEFAULT 0")
            if "customer_receipt_notes" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_notes TEXT")
            if "customer_receipt_match" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_match VARCHAR(30)")
            if "customer_receipt_received_by" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_received_by VARCHAR(80)")
            if "customer_receipt_received_at" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_received_at DATETIME")
            if "customer_receipt_photo" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_photo VARCHAR(255)")
            if "customer_receipt_received" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_received BOOLEAN DEFAULT 0")
            if "customer_receipt_required" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN customer_receipt_required BOOLEAN DEFAULT 0")
            if "carrier_receipt_photo" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN carrier_receipt_photo VARCHAR(255)")
            if "delivery_target" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN delivery_target VARCHAR(30)")
            if "transport_office_name" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN transport_office_name VARCHAR(180)")
            if "external_driver_phone" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN external_driver_phone VARCHAR(40)")
            if "goods_source" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN goods_source VARCHAR(30)")
            if "source_customer" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN source_customer VARCHAR(180)")
            if "source_return_photo" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN source_return_photo VARCHAR(255)")
            if "source_return_received_at" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN source_return_received_at DATETIME")
            if "source_return_received_by" not in cols_i: stmts.append("ALTER TABLE invoices ADD COLUMN source_return_received_by VARCHAR(80)")
            if "warehouse_match" not in cols_ii: stmts.append("ALTER TABLE invoice_issue_items ADD COLUMN warehouse_match BOOLEAN")
            if "actual_quantity" not in cols_ii: stmts.append("ALTER TABLE invoice_issue_items ADD COLUMN actual_quantity VARCHAR(80)")
            if "warehouse_note" not in cols_ii: stmts.append("ALTER TABLE invoice_issue_items ADD COLUMN warehouse_note TEXT")
        for stmt in stmts:
            conn.execute(text(stmt))


def app_version() -> str:
    return (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("APP_VERSION")
        or "dev"
    )[:12]


app = FastAPI(title="منصة جولدن كوست لإدارة العمليات")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def audit(db: Session, action: str, username: str, invoice_no: str | None = None, details: dict | None = None):
    db.add(AuditLog(
        action=action,
        username=username,
        invoice_no=invoice_no,
        details=json.dumps(details or {}, ensure_ascii=False),
    ))
    db.commit()


def save_upload(file: UploadFile | None, invoice_no: str, kind: str) -> str | None:
    if not file or not file.filename:
        return None
    content_type = (file.content_type or "").lower()
    suffix = Path(file.filename or "").suffix.lower()
    allowed_image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif"}
    if not content_type.startswith("image/") and suffix not in allowed_image_suffixes:
        raise HTTPException(status_code=400, detail="المسموح صور فقط.")
    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="الصورة المرفوعة فارغة.")
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        try:
            return SupabaseStorage().upload_image(invoice_no, kind, raw)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"فشل رفع الصورة إلى Supabase Storage: {exc}")

    # Local fallback for development only. Render must use Supabase Storage.
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    folder = UPLOAD_DIR / str(datetime.now().year) / f"{datetime.now().month:02d}" / invoice_no
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{kind}_{uuid.uuid4().hex[:10]}{suffix}"
    target.write_bytes(raw)
    return "/" + str(target.relative_to(ROOT_DIR)).replace("\\", "/")


def recover_existing_photo_links(invoice: Invoice) -> bool:
    """Repair missing DB links from existing Supabase objects; never uploads a new file."""
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")):
        return False
    changed = False
    storage = SupabaseStorage()

    lookups = [
        ("original_document_photo", ["original_document"], invoice.original_document_received_at),
        ("customer_receipt_photo", ["customer_final_receipt"], invoice.customer_receipt_received_at),
        ("source_return_photo", ["source_customer_return"], invoice.source_return_received_at),
        ("return_photo", ["return_warehouse", "warehouse"], invoice.return_received_at),
        ("driver_return_photo", ["return_driver", "return_driver_edit"], invoice.delivered_at),
        ("receipt_photo", ["delivery_receipt", "receipt_edit"], invoice.delivered_at),
        ("warehouse_photo", ["warehouse"], invoice.loaded_at),
    ]
    for field, kinds, at in lookups:
        if getattr(invoice, field, None) or not at:
            continue
        found = storage.find_existing_image(invoice.invoice_no, kinds, at)
        if found:
            setattr(invoice, field, found)
            changed = True

    # Carrier receipt may originate at warehouse handoff (external driver) or driver delivery to office.
    if not invoice.carrier_receipt_photo:
        at = invoice.loaded_at if invoice.delivery_mode == "EXTERNAL_DRIVER" else invoice.delivered_at
        kinds = ["warehouse_handoff"] if invoice.delivery_mode == "EXTERNAL_DRIVER" else ["delivery_receipt", "receipt_edit"]
        if at:
            found = storage.find_existing_image(invoice.invoice_no, kinds, at)
            if found:
                invoice.carrier_receipt_photo = found
                changed = True
    return changed


def upsert_user(db: Session, username: str, password: str, name: str, role: str,
                driver_code: str | None = None, external: bool = False):
    """Create seed users only when missing; never reset passwords/status on deploy."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            name=name,
            role=role,
            driver_code=driver_code,
            active=True,
            is_external_driver=external,
        )
        db.add(user)

@app.middleware("http")
async def deployment_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path == "/manifest.webmanifest" or path == "/api/version":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/api/version")
def current_app_version():
    return {"version": app_version()}


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    ensure_columns()
    with Session(engine) as db:
        upsert_user(db, "admin", "62420071", "المدير", "ADMIN")
        upsert_user(db, "hr1", "123321", "فؤاد حاجب", "HR")
        upsert_user(db, "inv1", "321", "معين", "WAREHOUSE")
        upsert_user(db, "dr1", "852", "خالد قنبع", "DRIVER", "dr1")
        upsert_user(db, "dr2", "321", "جميل", "DRIVER", "dr2")
        upsert_user(db, "external", "000", "سائق خارجي", "DRIVER", "external", True)
        db.commit()


@app.get("/health")
def health():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "app_version": app_version()})

@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({
        "name": "شركة جولدن كوست التجارية",
        "short_name": "جولدن كوست",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#17365d",
        "dir": "rtl",
        "lang": "ar",
    })


@app.post("/api/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.lower().strip()))
    if not user or not user.active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة.")
    if user.is_external_driver:
        raise HTTPException(status_code=403, detail="السائق الخارجي لا يملك حساب دخول.")
    response = JSONResponse({"ok": True})
    set_session(response, user)
    audit(db, "LOGIN", user.username)
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    clear_session(response)
    return response




def numeric_invoice_no(value: str | None) -> int | None:
    if value is None:
        return None
    text_value = str(value).strip()
    # التسلسل يعمل على أرقام الفواتير الرقمية. الأرقام العربية يتم تحويلها كذلك.
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    text_value = text_value.translate(trans)
    if not text_value.isdigit():
        return None
    try:
        return int(text_value)
    except ValueError:
        return None


def get_invoice_sequence_start(db: Session) -> int | None:
    row = db.get(AppSetting, "invoice_sequence_start")
    if not row or not (row.value or "").strip():
        return None
    try:
        return int(row.value)
    except ValueError:
        return None


def invoice_sequence_status(db: Session) -> dict:
    start = get_invoice_sequence_start(db)
    numbers = []
    for invoice_no in db.scalars(select(Invoice.invoice_no)).all():
        value = numeric_invoice_no(invoice_no)
        if value is not None:
            numbers.append(value)
    numbers = sorted(set(numbers))
    week_key = datetime.utcnow().strftime("%G-W%V")
    ack = db.get(AppSetting, "invoice_sequence_ack_week")
    acknowledged = bool(ack and ack.value == week_key)

    if start is None:
        return {
            "start": None, "max": max(numbers) if numbers else None, "missing": [],
            "configured": False, "week": week_key, "acknowledged": acknowledged,
        }

    eligible = [n for n in numbers if n >= start]
    if not eligible:
        return {
            "start": start, "max": None, "missing": [], "configured": True,
            "week": week_key, "acknowledged": acknowledged,
        }

    maximum = max(eligible)
    present = set(eligible)
    missing = [n for n in range(start, maximum + 1) if n not in present]
    return {
        "start": start, "max": maximum, "missing": missing, "configured": True,
        "week": week_key, "acknowledged": acknowledged,
    }


def maybe_close_invoice(invoice: Invoice):
    """Close only when every independent required track is complete."""
    ready_document = invoice.goods_source == "CUSTOMER_TRANSFER" or bool(invoice.original_document_received)

    # Never close while a physical return is still waiting for warehouse confirmation.
    ready_physical_return = not (
        invoice.status == "RETURN_PENDING" and not bool(invoice.return_received)
    )

    ready_return = (not invoice.sales_return_required) or bool(invoice.sales_return_reviewed)
    ready_customer = (not invoice.customer_receipt_required) or bool(invoice.customer_receipt_received)
    ready_discrepancy = (not invoice.delivery_discrepancy_required) or bool(invoice.delivery_discrepancy_reviewed)

    if ready_document and ready_physical_return and ready_return and ready_customer and ready_discrepancy:
        invoice.status = "CLOSED"
        invoice.current_owner = "ARCHIVE"
        invoice.closed_at = datetime.utcnow()
        return True

    # Keep the invoice with the real pending owner instead of marking it complete.
    if not ready_physical_return:
        invoice.status = "RETURN_PENDING"
        invoice.current_owner = "WAREHOUSE"
    elif not ready_customer:
        invoice.status = "CUSTOMER_RECEIPT_PENDING"
        invoice.current_owner = "SALES_REP"
    elif not ready_discrepancy:
        invoice.status = "DELIVERY_DISCREPANCY_PENDING"
        invoice.current_owner = "HR"
    else:
        invoice.status = "FINAL_REVIEW_PENDING"
        invoice.current_owner = "MULTI"
    return False


def user_dict(user: User):
    return {
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "driver_code": user.driver_code,
        "sales_rep_id": user.sales_rep_id,
        "phone": user.phone,
        "active": user.active,
        "is_external_driver": user.is_external_driver,
        "permissions": effective_permissions(user, {"username": user.username, "role": user.role}),
    }


def vehicle_dict(vehicle: Vehicle):
    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "plate_no": vehicle.plate_no,
        "vehicle_type": vehicle.vehicle_type,
        "status": vehicle.status,
        "active": vehicle.active,
        "notes": vehicle.notes,
    }


def goods_movement_timeline(db: Session, invoice: Invoice) -> list[dict]:
    events = []
    def add(kind, title, when, user="", detail="", photo=None):
        if when:
            events.append({
                "kind": kind,
                "title": title,
                "at": when.isoformat() if hasattr(when, "isoformat") else str(when),
                "user": user or "",
                "detail": detail or "",
                "photo": photo,
            })

    add("CREATE", "إدخال الفاتورة", invoice.created_at, invoice.created_by,
        f"العميل: {invoice.customer or '-'}" + (f" — المندوب: {invoice.sales_rep_name}" if invoice.sales_rep_name else ""))

    if invoice.goods_source == "CUSTOMER_TRANSFER":
        add("CUSTOMER_TRANSFER_SOURCE", "سحب البضاعة من العميل الأول",
            invoice.source_return_received_at, invoice.source_return_received_by,
            f"العميل الأول: {invoice.source_customer or '-'}", invoice.source_return_photo)

    warehouse_title = "مرتجع كامل من المخزن" if invoice.load_status == "مرتجع كامل من المخزن" else "تحميل المخزن"
    add("WAREHOUSE", warehouse_title, invoice.loaded_at, invoice.warehouse_user or invoice.updated_by,
        (invoice.warehouse_shortage_reason or invoice.load_status or "") if invoice.load_status == "مرتجع كامل من المخزن" else (invoice.load_status or ""), invoice.warehouse_photo)

    warehouse_items = db.scalars(select(InvoiceIssueItem).where(
        InvoiceIssueItem.invoice_no == invoice.invoice_no,
        InvoiceIssueItem.stage == "WAREHOUSE",
    ).order_by(InvoiceIssueItem.id)).all()
    if warehouse_items:
        detail = "، ".join(f"{x.product_name}: {x.quantity} {x.unit}" for x in warehouse_items)
        add("LOAD_SHORTAGE", "نقص/مرتجع التحميل", invoice.loaded_at, invoice.warehouse_user or invoice.updated_by, detail)

    if invoice.delivery_mode == "EXTERNAL_DRIVER":
        add("CARRIER_HANDOFF", "تسليم لسائق خارجي", invoice.loaded_at, invoice.warehouse_user or invoice.updated_by,
            invoice.driver_name or "", invoice.carrier_receipt_photo)
    elif invoice.delivery_mode == "SALES_REP_SELF":
        add("REP_HANDOFF", "المندوب استلم البضاعة للتوصيل", invoice.loaded_at, invoice.warehouse_user or invoice.updated_by,
            invoice.sales_rep_name or "")
    elif invoice.delivery_mode == "CUSTOMER_SELF":
        add("CUSTOMER_PICKUP", "العميل استلم من المخزن", invoice.delivered_at or invoice.loaded_at,
            invoice.warehouse_user or invoice.updated_by, "", invoice.customer_receipt_photo)

    if invoice.delivery_mode == "COMPANY_DRIVER" and invoice.delivered_at:
        target = "العميل" if invoice.delivery_target == "CUSTOMER" else f"مكتب النقل: {invoice.transport_office_name or '-'}"
        add("DELIVERY", f"سائق الشركة سلّم إلى {target}", invoice.delivered_at, invoice.driver_name,
            invoice.delivery_result or "", invoice.receipt_photo if invoice.delivery_target == "CUSTOMER" else invoice.carrier_receipt_photo)

    driver_items = db.scalars(select(InvoiceIssueItem).where(
        InvoiceIssueItem.invoice_no == invoice.invoice_no,
        InvoiceIssueItem.stage == "DRIVER",
    ).order_by(InvoiceIssueItem.id)).all()
    if driver_items:
        detail = "، ".join(f"{x.product_name}: {x.quantity} {x.unit}" for x in driver_items)
        add("CUSTOMER_RETURN", "مرتجع العميل المسجل بواسطة السائق", invoice.delivered_at, invoice.driver_name, detail, invoice.driver_return_photo)

    confirmed_items = [x for x in (warehouse_items + driver_items) if x.warehouse_match is not None]
    confirmed_detail = "، ".join(
        f"{'نقص تحميل' if x.stage == 'WAREHOUSE' else 'مرتجع عميل'} — {x.product_name}: "
        f"المسجل {x.quantity} {x.unit} / المستلم {x.actual_quantity or x.quantity} {x.unit}"
        + (" (مطابق)" if x.warehouse_match else " (غير مطابق)")
        for x in confirmed_items
    )
    add("RETURN_RECEIVED", "المخزن أكد المرتجعات", invoice.return_received_at, invoice.updated_by,
        confirmed_detail or invoice.return_notes or "", invoice.return_photo)

    add("CUSTOMER_FINAL", "استلام العميل النهائي", invoice.customer_receipt_received_at,
        invoice.customer_receipt_received_by, {
            "MATCH": "مطابق", "SHORT": "نقص عند التسليم", "OVER": "زيادة عند التسليم"
        }.get(invoice.customer_receipt_match, invoice.customer_receipt_notes or ""),
        invoice.customer_receipt_photo)

    rep_items = db.scalars(select(InvoiceIssueItem).where(
        InvoiceIssueItem.invoice_no == invoice.invoice_no,
        InvoiceIssueItem.stage == "SALES_REP",
    ).order_by(InvoiceIssueItem.id)).all()
    if rep_items:
        detail = "، ".join(f"{x.issue_type} — {x.product_name}: {x.quantity} {x.unit}" for x in rep_items)
        add("DELIVERY_DIFF", "فرق في استلام العميل", invoice.customer_receipt_received_at,
            invoice.customer_receipt_received_by, detail)

    add("DELIVERY_DIFF_REVIEW", "الموارد راجعت فرق التسليم", invoice.delivery_discrepancy_reviewed_at,
        invoice.delivery_discrepancy_reviewed_by, invoice.delivery_discrepancy_notes or "")

    add("SALES_RETURN", "اعتماد مردود المبيعات", invoice.sales_return_reviewed_at,
        invoice.sales_return_reviewed_by, invoice.sales_return_notes or "")

    add("DOCUMENT", "استلام أصل الفاتورة", invoice.original_document_received_at,
        invoice.original_document_received_by or invoice.updated_by, invoice.closure_notes or "",
        invoice.original_document_photo)

    add("CLOSED", "إغلاق الفاتورة", invoice.closed_at, invoice.updated_by, "مكتملة")
    return sorted(events, key=lambda x: x["at"] or "")


def invoice_dict(invoice: Invoice):
    return {
        "invoice_no": invoice.invoice_no,
        "customer": invoice.customer,
        "sales_rep_id": invoice.sales_rep_id,
        "sales_rep_name": invoice.sales_rep_name,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "driver_code": invoice.driver_code,
        "delivery_mode": invoice.delivery_mode,
        "driver_name": invoice.driver_name,
        "is_external_driver": invoice.is_external_driver,
        "vehicle_no": invoice.vehicle_no,
        "original_document_photo": invoice.original_document_photo,
        "delivery_discrepancy_notes": invoice.delivery_discrepancy_notes,
        "delivery_discrepancy_reviewed_by": invoice.delivery_discrepancy_reviewed_by,
        "delivery_discrepancy_reviewed_at": invoice.delivery_discrepancy_reviewed_at.isoformat() if invoice.delivery_discrepancy_reviewed_at else None,
        "delivery_discrepancy_reviewed": invoice.delivery_discrepancy_reviewed,
        "delivery_discrepancy_required": invoice.delivery_discrepancy_required,
        "customer_receipt_notes": invoice.customer_receipt_notes,
        "customer_receipt_match": invoice.customer_receipt_match,
        "customer_receipt_received_by": invoice.customer_receipt_received_by,
        "customer_receipt_received_at": invoice.customer_receipt_received_at.isoformat() if invoice.customer_receipt_received_at else None,
        "customer_receipt_photo": invoice.customer_receipt_photo,
        "customer_receipt_received": invoice.customer_receipt_received,
        "customer_receipt_required": invoice.customer_receipt_required,
        "carrier_receipt_photo": invoice.carrier_receipt_photo,
        "delivery_target": invoice.delivery_target,
        "transport_office_name": invoice.transport_office_name,
        "external_driver_phone": invoice.external_driver_phone,
        "goods_source": invoice.goods_source,
        "source_customer": invoice.source_customer,
        "source_return_photo": invoice.source_return_photo,
        "source_return_received_at": invoice.source_return_received_at.isoformat() if invoice.source_return_received_at else None,
        "source_return_received_by": invoice.source_return_received_by,
        "status": invoice.status,
        "load_status": invoice.load_status,
        "warehouse_shortage_reason": invoice.warehouse_shortage_reason,
        "warehouse_photo": invoice.warehouse_photo,
        "delivery_result": invoice.delivery_result,
        "delivery_reason": invoice.delivery_reason,
        "receipt_photo": invoice.receipt_photo,
        "driver_return_photo": invoice.driver_return_photo,
        "return_qty_declared": invoice.return_qty_declared,
        "return_qty_text": invoice.return_qty_text,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "loaded_at": invoice.loaded_at.isoformat() if invoice.loaded_at else None,
        "delivered_at": invoice.delivered_at.isoformat() if invoice.delivered_at else None,
        "return_received": invoice.return_received,
        "return_qty_actual": invoice.return_qty_actual,
        "return_difference": invoice.return_difference,
        "return_condition": invoice.return_condition,
        "return_photo": invoice.return_photo,
        "sales_return_required": invoice.sales_return_required,
        "sales_return_reviewed": invoice.sales_return_reviewed,
        "sales_return_reviewed_by": invoice.sales_return_reviewed_by,
        "sales_return_reviewed_at": invoice.sales_return_reviewed_at.isoformat() if invoice.sales_return_reviewed_at else None,
        "sales_return_notes": invoice.sales_return_notes,
        "original_document_received": invoice.original_document_received,
        "original_document_received_by": invoice.original_document_received_by,
        "original_document_received_at": invoice.original_document_received_at.isoformat() if invoice.original_document_received_at else None,
        "closure_notes": invoice.closure_notes,
        "hr_notes": invoice.hr_notes,
        "warehouse_notes": invoice.warehouse_notes,
        "driver_notes": invoice.driver_notes,
        "created_by": invoice.created_by,
        "updated_by": invoice.updated_by,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
    }


def list_drivers(db: Session):
    rows = db.scalars(
        select(User).where(User.role == "DRIVER", User.active == True).order_by(User.name)
    ).all()
    return [user_dict(x) for x in rows]


def list_vehicles(db: Session):
    rows = db.scalars(
        select(Vehicle).where(Vehicle.active == True).order_by(Vehicle.name)
    ).all()
    return [vehicle_dict(x) for x in rows]


def list_users(db: Session):
    rows = db.scalars(select(User).order_by(User.name)).all()
    return [user_dict(x) for x in rows]


def list_logs(db: Session):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)).all()
    return [{
        "id": x.id,
        "action": x.action,
        "username": x.username,
        "invoice_no": x.invoice_no,
        "details": x.details,
        "created_at": x.created_at.isoformat() if x.created_at else None,
    } for x in rows]


def get_queue(db: Session, user: dict):
    stmt = select(Invoice)
    if user["role"] == "ADMIN":
        stmt = stmt.where(Invoice.status != "CLOSED")
    elif user["role"] == "HR":
        stmt = stmt.where(
            Invoice.status != "CLOSED",
            or_(
                and_(Invoice.goods_source != "CUSTOMER_TRANSFER", Invoice.loaded_at.is_not(None), Invoice.original_document_received == False),
                (Invoice.delivery_discrepancy_required == True) & (Invoice.delivery_discrepancy_reviewed == False),
            ),
        )
    elif user["role"] == "SALES_ACCOUNTANT":
        stmt = stmt.where(
            Invoice.status != "CLOSED",
            Invoice.sales_return_required == True,
            Invoice.sales_return_reviewed == False,
        )
    elif user["role"] == "SALES_REP":
        rep_id = user.get("sales_rep_id")
        if not rep_id:
            return []
        stmt = stmt.where(
            Invoice.status != "CLOSED",
            Invoice.sales_rep_id == rep_id,
            Invoice.customer_receipt_required == True,
            Invoice.customer_receipt_received == False,
        )
    elif user["role"] == "WAREHOUSE":
        stmt = stmt.where(Invoice.status.in_(["WAREHOUSE_PENDING", "RETURN_PENDING"]))
    elif user["role"] == "DRIVER":
        stmt = stmt.where(
            Invoice.status.in_(["DRIVER_PENDING", "POSTPONED"]),
            Invoice.driver_code == user.get("driver_code", ""),
        )
    else:
        return []
    return [invoice_dict(x) for x in db.scalars(stmt.order_by(Invoice.created_at.asc())).all()]


def get_stats(db: Session, user: dict):
    stmt = select(Invoice)
    if user["role"] == "DRIVER":
        stmt = stmt.where(Invoice.driver_code == user.get("driver_code", ""))
    elif user["role"] == "SALES_REP":
        stmt = stmt.where(Invoice.sales_rep_id == user.get("sales_rep_id"))
    rows = db.scalars(stmt).all()
    count = lambda status: sum(1 for x in rows if x.status == status)
    return {
        "my_pending": len(get_queue(db, user)),
        "warehouse_pending": count("WAREHOUSE_PENDING"),
        "driver_pending": count("DRIVER_PENDING") + count("POSTPONED"),
        "returns_pending": count("RETURN_PENDING"),
        "documents_pending": count("DOCUMENT_PENDING") + count("FINAL_REVIEW_PENDING") + count("CUSTOMER_RECEIPT_PENDING") + count("DELIVERY_DISCREPANCY_PENDING"),
        "closed": count("CLOSED"),
    }


def _report_date(value: str, end=False):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if end and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt

def warehouse_delay_alerts(db: Session):
    cutoff = datetime.utcnow() - timedelta(days=5)
    rows = db.scalars(
        select(Invoice).where(
            Invoice.status == "WAREHOUSE_PENDING",
            Invoice.loaded_at.is_(None),
            Invoice.invoice_date <= cutoff,
        ).order_by(Invoice.invoice_date.asc())
    ).all()
    now = datetime.utcnow()
    return [{
        "invoice_no": x.invoice_no, "customer": x.customer, "sales_rep_name": x.sales_rep_name,
        "invoice_date": x.invoice_date.isoformat() if x.invoice_date else None,
        "days": max(0, (now.date() - x.invoice_date.date()).days) if x.invoice_date else 0,
    } for x in rows]

@app.get("/api/alerts/warehouse-delay")
def get_warehouse_delay_alerts(request: Request, db: Session = Depends(get_db)):
    user = require_permission(request, db, "warehouse_delay_alerts")
    return warehouse_delay_alerts(db)

@app.get("/api/reports/summary")
def report_summary(request: Request, date_from: str = "", date_to: str = "", driver: str = "", sales_rep: str = "", db: Session = Depends(get_db)):
    require_permission(request, db, "reports_view")
    stmt = select(Invoice)
    start, end = _report_date(date_from), _report_date(date_to, True)
    if start: stmt = stmt.where(Invoice.invoice_date >= start)
    if end: stmt = stmt.where(Invoice.invoice_date <= end)
    if driver: stmt = stmt.where(Invoice.driver_name.ilike(f"%{driver.strip()}%"))
    if sales_rep: stmt = stmt.where(Invoice.sales_rep_name.ilike(f"%{sales_rep.strip()}%"))
    rows = db.scalars(stmt.order_by(Invoice.invoice_date.desc())).all()
    status_counts = {}
    for x in rows: status_counts[x.status] = status_counts.get(x.status, 0) + 1
    return {
        "total": len(rows), "status_counts": status_counts,
        "closed": sum(x.status == "CLOSED" for x in rows),
        "pending": sum(x.status != "CLOSED" for x in rows),
        "returns": sum(bool(x.return_received or x.sales_return_required or x.driver_return_photo) for x in rows),
        "rows": [invoice_dict(x) for x in rows],
    }

@app.get("/api/reports/returns")
def report_returns(request: Request, date_from: str = "", date_to: str = "", driver: str = "", sales_rep: str = "", db: Session = Depends(get_db)):
    require_permission(request, db, "reports_view")
    stmt = select(Invoice).where(or_(Invoice.return_received == True, Invoice.sales_return_required == True, Invoice.driver_return_photo.is_not(None)))
    start, end = _report_date(date_from), _report_date(date_to, True)
    if start: stmt = stmt.where(Invoice.invoice_date >= start)
    if end: stmt = stmt.where(Invoice.invoice_date <= end)
    if driver: stmt = stmt.where(Invoice.driver_name.ilike(f"%{driver.strip()}%"))
    if sales_rep: stmt = stmt.where(Invoice.sales_rep_name.ilike(f"%{sales_rep.strip()}%"))
    rows = db.scalars(stmt.order_by(Invoice.invoice_date.desc())).all()

    invoice_nos = [x.invoice_no for x in rows]
    by_invoice = {}
    if invoice_nos:
        all_items = db.scalars(
            select(InvoiceIssueItem).where(
                InvoiceIssueItem.invoice_no.in_(invoice_nos),
                InvoiceIssueItem.issue_type.in_(["مرتجع","مرتجع عميل","ناقص","نقص تحميل"]),
            )
        ).all()
        for item in all_items:
            by_invoice.setdefault(item.invoice_no, []).append(item)

    out = []
    for x in rows:
        items = by_invoice.get(x.invoice_no, [])
        out.append({**invoice_dict(x), "return_items":[{
            "product_name": i.product_name, "unit": i.unit, "quantity": i.quantity,
            "warehouse_match": i.warehouse_match, "actual_quantity": i.actual_quantity,
            "note": i.warehouse_note, "issue_type": i.issue_type
        } for i in items]})
    return out

@app.get("/api/reports/drivers")
def report_drivers(request: Request, date_from: str = "", date_to: str = "", driver: str = "", sales_rep: str = "", db: Session = Depends(get_db)):
    require_permission(request, db, "reports_view")
    stmt = select(Invoice).where(
        Invoice.loaded_at.is_not(None),
        Invoice.delivery_mode.in_(["COMPANY_DRIVER", "EXTERNAL_DRIVER"]),
    )
    start, end = _report_date(date_from), _report_date(date_to, True)
    if start: stmt = stmt.where(Invoice.invoice_date >= start)
    if end: stmt = stmt.where(Invoice.invoice_date <= end)
    if driver: stmt = stmt.where(Invoice.driver_name.ilike(f"%{driver.strip()}%"))
    if sales_rep: stmt = stmt.where(Invoice.sales_rep_name.ilike(f"%{sales_rep.strip()}%"))
    rows = db.scalars(stmt).all()

    invoice_nos = [x.invoice_no for x in rows]
    customer_return_invoices = set()
    if invoice_nos:
        customer_return_invoices = set(db.scalars(
            select(InvoiceIssueItem.invoice_no).where(
                InvoiceIssueItem.invoice_no.in_(invoice_nos),
                InvoiceIssueItem.stage == "DRIVER",
                InvoiceIssueItem.issue_type.in_(["مرتجع عميل", "مرتجع"]),
            ).distinct()
        ).all())

    agg = {}
    for x in rows:
        name = x.driver_name or "غير محدد"
        a = agg.setdefault(name, {"driver":name,"loaded":0,"delivered":0,"office":0,"postponed":0,"returns":0})
        a["loaded"] += 1
        if x.delivered_at: a["delivered"] += 1
        if x.delivery_target == "TRANSPORT_OFFICE": a["office"] += 1
        if x.status == "POSTPONED" or x.delivery_result in ["مؤجل","العميل مغلق"]: a["postponed"] += 1
        if x.invoice_no in customer_return_invoices: a["returns"] += 1
    return sorted(agg.values(), key=lambda x:(-x["loaded"],x["driver"]))

@app.get("/api/bootstrap")
def bootstrap(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    row = db.scalar(select(User).where(User.username == user["username"]))
    perms = effective_permissions(row, user)
    return {
        "user": user,
        "stats": get_stats(db, user),
        "warehouse_delay_alerts": warehouse_delay_alerts(db) if ("warehouse_delay_alerts" in perms["actions"] or user.get("username") == "admin") else [],
        "queue": get_queue(db, user),
        "drivers": list_drivers(db),
        "sales_reps": [{"id": r.id, "name": r.name, "phone": r.phone, "active": r.active} for r in db.scalars(select(SalesRep).order_by(SalesRep.name)).all()],
        "vehicles": list_vehicles(db),
        "users": list_users(db) if (user.get("username") == "admin" or "users" in perms["screens"]) else [],
        "logs": list_logs(db) if (user.get("username") == "admin" or "logs" in perms["screens"]) else [],
        "products": [{"id": p.id, "name": p.name, "units": json.loads(p.units_json or "[]"), "active": p.active}
                     for p in db.scalars(
                         (select(Product).order_by(Product.name)) if user["role"] == "ADMIN"
                         else (select(Product).where(Product.active == True).order_by(Product.name))
                     ).all()],
        "permission_catalog": PERMISSION_CATALOG,
        "permissions": effective_permissions(db.scalar(select(User).where(User.username == user["username"])), user),
        "invoice_sequence": invoice_sequence_status(db),
    }


@app.get("/api/sales-reps")
def get_sales_reps(request: Request, db: Session = Depends(get_db)):
    require_user(request)
    return [{"id": r.id, "name": r.name, "phone": r.phone, "active": r.active}
            for r in db.scalars(select(SalesRep).order_by(SalesRep.name)).all()]


@app.post("/api/sales-reps")
def create_sales_rep(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN"])
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="اكتب اسم المندوب.")
    if db.scalar(select(SalesRep).where(SalesRep.name == name)):
        raise HTTPException(status_code=400, detail="المندوب موجود مسبقًا.")
    db.add(SalesRep(name=name, phone=phone.strip() or None, active=True))
    db.commit()
    audit(db, "CREATE_SALES_REP", user["username"], details={"name": name})
    return {"ok": True}


@app.post("/api/sales-reps/{rep_id}/toggle")
def toggle_sales_rep(rep_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_role(request, ["ADMIN"])
    rep = db.get(SalesRep, rep_id)
    if not rep:
        raise HTTPException(status_code=404, detail="المندوب غير موجود.")
    rep.active = not rep.active
    db.commit()
    audit(db, "TOGGLE_SALES_REP", user["username"], details={"name": rep.name, "active": rep.active})
    return {"ok": True}


@app.post("/api/sales-reps/{rep_id}/update")
def update_sales_rep(
    rep_id: int,
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN"])
    rep = db.get(SalesRep, rep_id)
    if not rep:
        raise HTTPException(status_code=404, detail="المندوب غير موجود.")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="اسم المندوب مطلوب.")
    duplicate = db.scalar(select(SalesRep).where(SalesRep.name == name, SalesRep.id != rep.id))
    if duplicate:
        raise HTTPException(status_code=400, detail="اسم المندوب موجود مسبقًا.")
    rep.name = name
    rep.phone = phone.strip() or None
    db.query(Invoice).filter(Invoice.sales_rep_id == rep.id).update({"sales_rep_name": rep.name})
    db.commit()
    audit(db, "UPDATE_SALES_REP", user["username"], details={"rep_id": rep.id, "name": rep.name})
    return {"ok": True}


@app.post("/api/sales-reps/{rep_id}/delete")
def delete_sales_rep(rep_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_role(request, ["ADMIN"])
    rep = db.get(SalesRep, rep_id)
    if not rep:
        raise HTTPException(status_code=404, detail="المندوب غير موجود.")
    linked_invoice = db.scalar(select(Invoice.id).where(Invoice.sales_rep_id == rep.id).limit(1))
    linked_user = db.scalar(select(User.id).where(User.sales_rep_id == rep.id).limit(1))
    if linked_invoice or linked_user:
        raise HTTPException(status_code=400, detail="لا يمكن حذف المندوب لأنه مرتبط بفواتير أو مستخدم. يمكنك توقيفه.")
    name = rep.name
    db.delete(rep)
    db.commit()
    audit(db, "DELETE_SALES_REP", user["username"], details={"name": name})
    return {"ok": True}



@app.get("/api/invoices/{invoice_no}/movement")
def invoice_movement(invoice_no: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية لعرض حركة هذه الفاتورة.")
    if user["role"] == "SALES_REP" and invoice.sales_rep_id != user.get("sales_rep_id"):
        raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لمندوبك.")
    return goods_movement_timeline(db, invoice)


@app.post("/api/invoices")
def create_invoice(
    request: Request,
    invoice_no: str = Form(...),
    customer: str = Form(""),
    invoice_date: str = Form(""),
    notes: str = Form(""),
    sales_rep_id: str = Form(""),
    goods_source: str = Form("WAREHOUSE"),
    source_customer: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "invoice_create")
    invoice_no = invoice_no.strip()
    if db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no)):
        raise HTTPException(status_code=400, detail="رقم الفاتورة موجود مسبقًا.")
    if not customer.strip():
        raise HTTPException(status_code=400, detail="اسم العميل إجباري عند إدخال الفاتورة.")
    if not sales_rep_id.strip() or not sales_rep_id.strip().isdigit():
        raise HTTPException(status_code=400, detail="اختيار المندوب إجباري عند إدخال الفاتورة.")
    rep = None
    if sales_rep_id.strip():
        try:
            rep = db.get(SalesRep, int(sales_rep_id))
        except ValueError:
            rep = None
        if not rep or not rep.active:
            raise HTTPException(status_code=400, detail="المندوب المحدد غير صحيح أو موقوف.")
    if goods_source not in ["WAREHOUSE", "CUSTOMER_TRANSFER"]:
        raise HTTPException(status_code=400, detail="مصدر البضاعة غير صحيح.")
    if goods_source == "CUSTOMER_TRANSFER":
        if not rep:
            raise HTTPException(status_code=400, detail="حدد المندوب لأن تحويل عميل إلى عميل ينتقل مباشرة للمندوب.")
        if not source_customer.strip():
            raise HTTPException(status_code=400, detail="اكتب اسم العميل الأول الذي ستؤخذ منه البضاعة.")

    direct_transfer = goods_source == "CUSTOMER_TRANSFER"
    db.add(Invoice(
        invoice_no=invoice_no,
        customer=customer.strip() or None,
        sales_rep_id=rep.id if rep else None,
        sales_rep_name=rep.name if rep else None,
        invoice_date=datetime.fromisoformat(invoice_date) if invoice_date else datetime.utcnow(),
        hr_notes=notes.strip() or None,
        goods_source=goods_source,
        source_customer=source_customer.strip() or None,
        delivery_mode="CUSTOMER_TRANSFER" if direct_transfer else None,
        customer_receipt_required=direct_transfer,
        delivery_result="تحويل مباشر من عميل إلى عميل — بانتظار المندوب" if direct_transfer else None,
        created_by=user["username"],
        updated_by=user["username"],
        status="CUSTOMER_RECEIPT_PENDING" if direct_transfer else "WAREHOUSE_PENDING",
        current_owner="SALES_REP" if direct_transfer else "WAREHOUSE",
    ))
    db.commit()
    audit(db, "CREATE_INVOICE", user["username"], invoice_no)
    return {"ok": True}


@app.get("/api/invoices/search")
def search_invoices(
    request: Request,
    q: str = "",
    include_closed: bool = False,
    db: Session = Depends(get_db),
):
    user = require_user(request)
    stmt = select(Invoice)
    if not include_closed:
        stmt = stmt.where(Invoice.status != "CLOSED")
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Invoice.invoice_no.like(like), Invoice.customer.like(like)))
    if user["role"] == "DRIVER":
        stmt = stmt.where(Invoice.driver_code == user.get("driver_code", ""))
    elif user["role"] == "SALES_REP":
        stmt = stmt.where(Invoice.sales_rep_id == user.get("sales_rep_id"))
    return [invoice_dict(x) for x in db.scalars(stmt.order_by(Invoice.created_at.desc()).limit(200)).all()]


@app.get("/api/invoices/{invoice_no}")
def get_invoice(invoice_no: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية.")
    if user["role"] == "SALES_REP" and invoice.sales_rep_id != user.get("sales_rep_id"):
        raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لمندوبك.")
    if recover_existing_photo_links(invoice):
        db.commit()
    return invoice_dict(invoice)


@app.post("/api/invoices/{invoice_no}/warehouse")
def warehouse_update(
    invoice_no: str,
    request: Request,
    delivery_mode: str = Form("COMPANY_DRIVER"),
    driver_code: str = Form(""),
    external_driver_name: str = Form(""),
    external_driver_phone: str = Form(""),
    vehicle_id: str = Form(""),
    load_status: str = Form(...),
    shortage_reason: str = Form(""),
    notes: str = Form(""),
    loaded_at: str = Form(""),
    issues_json: str = Form("[]"),
    photo: UploadFile | None = File(None),
    receipt_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "warehouse_approve")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status != "WAREHOUSE_PENDING":
        raise HTTPException(status_code=400, detail="الفاتورة ليست معلقة في المخزن.")

    allowed_modes = ["COMPANY_DRIVER", "EXTERNAL_DRIVER", "CUSTOMER_SELF", "SALES_REP_SELF"]
    if delivery_mode not in allowed_modes:
        raise HTTPException(status_code=400, detail="طريقة التوصيل غير صحيحة.")

    full_warehouse_return = load_status == "مرتجع كامل من المخزن"

    if not full_warehouse_return and delivery_mode in ["EXTERNAL_DRIVER", "SALES_REP_SELF"] and not invoice.sales_rep_id:
        raise HTTPException(
            status_code=400,
            detail="حدد مندوب الفاتورة أولًا من تعديل بيانات الفاتورة قبل اعتماد هذا النوع من التوصيل.",
        )

    driver = None
    vehicle = None
    if not full_warehouse_return and delivery_mode == "EXTERNAL_DRIVER":
        if not external_driver_name.strip():
            raise HTTPException(status_code=400, detail="اسم السائق الخارجي إجباري.")
        if not external_driver_phone.strip():
            raise HTTPException(status_code=400, detail="رقم جوال السائق الخارجي إجباري.")

    if not full_warehouse_return and delivery_mode == "COMPANY_DRIVER":
        if not driver_code:
            raise HTTPException(status_code=400, detail="اختر السائق.")
        driver = db.scalar(select(User).where(
            User.driver_code == driver_code,
            User.role == "DRIVER",
            User.active == True,
        ))
        if not driver:
            raise HTTPException(status_code=400, detail="السائق غير موجود أو موقوف.")

    if not full_warehouse_return and delivery_mode == "COMPANY_DRIVER":
        if not vehicle_id:
            raise HTTPException(status_code=400, detail="اختيار الدينة إجباري لسائق الشركة.")
        try:
            vehicle_id_int = int(vehicle_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="اختيار الدينة إجباري لسائق الشركة.")
        vehicle = db.get(Vehicle, vehicle_id_int)
        if not vehicle or not vehicle.active:
            raise HTTPException(status_code=400, detail="السيارة غير موجودة أو موقوفة.")

    handoff_photo = None if full_warehouse_return else save_upload(receipt_photo, invoice_no, "warehouse_handoff")
    if not full_warehouse_return and delivery_mode == "CUSTOMER_SELF" and not handoff_photo:
        raise HTTPException(status_code=400, detail="صورة استلام العميل إجبارية عندما يستلم من المخزن.")
    if not full_warehouse_return and delivery_mode == "EXTERNAL_DRIVER" and not handoff_photo:
        raise HTTPException(status_code=400, detail="صورة استلام السائق الخارجي من المخزن إجبارية.")

    # Parse shortage rows before changing the invoice.
    try:
        issue_rows = json.loads(issues_json or "[]")
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات الأصناف غير صحيحة.")

    valid_issue_rows = []
    for row in issue_rows:
        try:
            product_id = int(row.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        product = db.get(Product, product_id)
        quantity = str(row.get("quantity") or "").strip()
        unit = str(row.get("unit") or "").strip()
        if product and quantity and unit:
            valid_issue_rows.append((product, quantity, unit))

    if full_warehouse_return:
        if not shortage_reason.strip():
            raise HTTPException(status_code=400, detail="سبب المرتجع الكامل من المخزن إجباري.")
        if photo is None or not getattr(photo, "filename", ""):
            raise HTTPException(status_code=400, detail="صورة مستند المرتجع الكامل من المخزن إجبارية.")

    if load_status == "تم التحميل ناقص" and not valid_issue_rows:
        raise HTTPException(
            status_code=400,
            detail="عند التحميل الناقص يجب تحديد الصنف والوحدة والكمية التي لم تُحمّل.",
        )

    invoice.delivery_mode = None if full_warehouse_return else delivery_mode
    invoice.delivery_target = None
    if full_warehouse_return:
        # driver_code and driver_name are NOT NULL in the existing database schema.
        invoice.driver_code = ""
        invoice.driver_name = ""
        invoice.external_driver_phone = None
        invoice.is_external_driver = False
        invoice.vehicle_no = None
    elif delivery_mode == "EXTERNAL_DRIVER":
        invoice.driver_code = "EXTERNAL_DRIVER"
        invoice.driver_name = external_driver_name.strip()
        invoice.external_driver_phone = external_driver_phone.strip()
        invoice.is_external_driver = True
        invoice.vehicle_no = None
    else:
        invoice.driver_code = driver.driver_code if driver else (
            "SALES_REP_SELF" if delivery_mode == "SALES_REP_SELF" else "CUSTOMER_SELF"
        )
        invoice.driver_name = driver.name if driver else (
            invoice.sales_rep_name if delivery_mode == "SALES_REP_SELF" else "العميل نفسه"
        )
        invoice.external_driver_phone = None
        invoice.is_external_driver = False
        invoice.vehicle_no = f"{vehicle.name} - {vehicle.plate_no}" if vehicle else None
    invoice.warehouse_user = user["username"]
    invoice.load_status = load_status
    invoice.warehouse_shortage_reason = shortage_reason.strip() or None
    invoice.warehouse_notes = notes.strip() or None
    invoice.warehouse_photo = save_upload(photo, invoice_no, "warehouse") or invoice.warehouse_photo
    invoice.loaded_at = datetime.fromisoformat(loaded_at) if loaded_at else datetime.utcnow()

    db.query(InvoiceIssueItem).filter(
        InvoiceIssueItem.invoice_no == invoice_no,
        InvoiceIssueItem.stage == "WAREHOUSE",
    ).delete()
    for product, quantity, unit in valid_issue_rows:
        db.add(InvoiceIssueItem(
            invoice_no=invoice_no,
            stage="WAREHOUSE",
            issue_type="نقص تحميل",
            product_id=product.id,
            product_name=product.name,
            unit=unit,
            quantity=quantity,
        ))

    invoice.customer_receipt_required = False
    invoice.customer_receipt_received = False
    invoice.delivery_discrepancy_required = False
    invoice.delivery_discrepancy_reviewed = False

    if full_warehouse_return:
        # No driver is involved. Warehouse attaches the return document and reason.
        invoice.return_received = True
        invoice.return_photo = invoice.warehouse_photo
        invoice.return_notes = shortage_reason.strip()
        invoice.return_received_at = invoice.loaded_at
        invoice.sales_return_required = True
        invoice.sales_return_reviewed = False
        invoice.delivery_result = "مرتجع كامل من المخزن — لم يتم تحميل البضاعة"
        invoice.status, invoice.current_owner = "FINAL_REVIEW_PENDING", "MULTI"
    elif delivery_mode == "COMPANY_DRIVER":
        invoice.status, invoice.current_owner = "DRIVER_PENDING", "DRIVER"
    elif delivery_mode == "EXTERNAL_DRIVER":
        invoice.carrier_receipt_photo = handoff_photo
        invoice.customer_receipt_required = True
        invoice.delivery_result = "سُلّمت لسائق خارجي — بانتظار استلام العميل"
        invoice.status, invoice.current_owner = "CUSTOMER_RECEIPT_PENDING", "SALES_REP"
    elif delivery_mode == "CUSTOMER_SELF":
        invoice.receipt_photo = handoff_photo
        invoice.customer_receipt_photo = handoff_photo
        invoice.customer_receipt_received = True
        invoice.customer_receipt_received_at = datetime.utcnow()
        invoice.customer_receipt_received_by = user["username"]
        invoice.customer_receipt_match = "MATCH"
        invoice.delivery_result = "استلم العميل بنفسه من المخزن"
        invoice.delivered_at = invoice.loaded_at
        if load_status == "تم التحميل ناقص":
            invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
        else:
            invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
    else:  # SALES_REP_SELF
        invoice.delivery_result = "المندوب نفسه استلم البضاعة للتوصيل"
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "WAREHOUSE_UPDATE", user["username"], invoice_no, {
        "delivery_mode": delivery_mode,
        "driver": driver.name if driver else invoice.driver_name,
        "full_warehouse_return": full_warehouse_return,
        "vehicle": invoice.vehicle_no,
        "load_status": load_status,
        "shortage_items": len(valid_issue_rows),
    })
    return {"ok": True}

@app.post("/api/invoices/{invoice_no}/driver")
def driver_update(
    invoice_no: str,
    request: Request,
    delivery_result: str = Form(...),
    delivery_target: str = Form("CUSTOMER"),
    transport_office_name: str = Form(""),
    return_qty_declared: str = Form(""),
    reason: str = Form(""),
    notes: str = Form(""),
    issues_json: str = Form("[]"),
    receipt_photo: UploadFile | None = File(None),
    return_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "driver_approve")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status not in ["DRIVER_PENDING", "POSTPONED"]:
        raise HTTPException(status_code=400, detail="الفاتورة ليست مع السائق.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لك.")

    if delivery_target not in ["CUSTOMER", "TRANSPORT_OFFICE"]:
        raise HTTPException(status_code=400, detail="حدد هل تم التسليم للعميل أو لمكتب النقل.")
    if delivery_target == "TRANSPORT_OFFICE" and not transport_office_name.strip():
        raise HTTPException(status_code=400, detail="اكتب اسم مكتب / شركة النقل.")
    if delivery_target == "TRANSPORT_OFFICE" and not invoice.sales_rep_id:
        raise HTTPException(
            status_code=400,
            detail="الفاتورة تحتاج مندوبًا لمتابعة استلام العميل من مكتب النقل. أضف المندوب أولًا.",
        )

    receipt = save_upload(receipt_photo, invoice_no, "delivery_receipt")
    returned = save_upload(return_photo, invoice_no, "return_driver")
    if delivery_result not in ["مؤجل", "العميل مغلق"] and not (receipt or invoice.receipt_photo):
        target_name = "مكتب النقل" if delivery_target == "TRANSPORT_OFFICE" else "العميل"
        raise HTTPException(status_code=400, detail=f"يجب رفع صورة استلام {target_name} قبل الاعتماد.")

    try:
        issue_rows = json.loads(issues_json or "[]")
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات أصناف المرتجع غير صحيحة.")

    valid_return_rows = []
    for row in issue_rows:
        try:
            product_id = int(row.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        product = db.get(Product, product_id)
        quantity = str(row.get("quantity") or "").strip()
        unit = str(row.get("unit") or "").strip()
        if product and quantity and unit:
            valid_return_rows.append((product, quantity, unit))

    if delivery_result in ["تم جزئي", "رفض كامل"] and not valid_return_rows:
        raise HTTPException(status_code=400, detail="عند وجود مرتجع من العميل يجب تحديد الصنف والوحدة والكمية.")

    db.query(InvoiceIssueItem).filter(
        InvoiceIssueItem.invoice_no == invoice_no,
        InvoiceIssueItem.stage == "DRIVER",
    ).delete()
    for product, quantity, unit in valid_return_rows:
        db.add(InvoiceIssueItem(
            invoice_no=invoice_no,
            stage="DRIVER",
            issue_type="مرتجع عميل",
            product_id=product.id,
            product_name=product.name,
            unit=unit,
            quantity=quantity,
        ))

    invoice.delivery_target = delivery_target
    invoice.transport_office_name = transport_office_name.strip() or None
    invoice.delivery_result = delivery_result
    invoice.delivery_reason = reason.strip() or None
    invoice.driver_notes = notes.strip() or None
    invoice.return_qty_text = return_qty_declared.strip() or None
    invoice.driver_return_photo = returned or invoice.driver_return_photo
    invoice.delivered_at = datetime.utcnow()

    if delivery_target == "CUSTOMER":
        invoice.receipt_photo = receipt or invoice.receipt_photo
        invoice.customer_receipt_photo = receipt or invoice.customer_receipt_photo
        if receipt:
            invoice.customer_receipt_received = True
            invoice.customer_receipt_received_at = datetime.utcnow()
            invoice.customer_receipt_received_by = user["username"]
            invoice.customer_receipt_match = "MATCH"
        invoice.customer_receipt_required = False
    else:
        invoice.carrier_receipt_photo = receipt or invoice.carrier_receipt_photo
        invoice.customer_receipt_required = True
        invoice.customer_receipt_received = False

    load_shortage_exists = db.scalar(select(InvoiceIssueItem.id).where(
        InvoiceIssueItem.invoice_no == invoice_no,
        InvoiceIssueItem.stage == "WAREHOUSE",
        InvoiceIssueItem.issue_type == "نقص تحميل",
    ).limit(1)) is not None

    if delivery_result in ["مؤجل", "العميل مغلق"]:
        invoice.status, invoice.current_owner = "POSTPONED", "DRIVER"
    elif valid_return_rows or load_shortage_exists:
        invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
    elif delivery_target == "TRANSPORT_OFFICE":
        invoice.status, invoice.current_owner = "CUSTOMER_RECEIPT_PENDING", "SALES_REP"
    else:
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "DRIVER_UPDATE", user["username"], invoice_no, {
        "delivery_target": delivery_target,
        "delivery_result": delivery_result,
        "return_items": len(valid_return_rows),
        "load_shortage_pending": load_shortage_exists,
    })
    return {"ok": True}

@app.post("/api/invoices/{invoice_no}/return")
def return_update(
    invoice_no: str,
    request: Request,
    issue_results_json: str = Form("[]"),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "return_approve")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status != "RETURN_PENDING":
        raise HTTPException(status_code=400, detail="لا يوجد مرتجع بانتظار المخزن.")

    return_items = db.scalars(
        select(InvoiceIssueItem).where(
            InvoiceIssueItem.invoice_no == invoice_no,
            or_(
                (InvoiceIssueItem.stage == "WAREHOUSE") & (InvoiceIssueItem.issue_type.in_(["نقص تحميل", "ناقص"])),
                (InvoiceIssueItem.stage == "DRIVER") & (InvoiceIssueItem.issue_type.in_(["مرتجع عميل", "مرتجع"])),
            ),
        ).order_by(InvoiceIssueItem.id)
    ).all()
    if not return_items:
        raise HTTPException(status_code=400, detail="لا توجد أصناف مرتجع مسجلة لهذه الفاتورة.")

    try:
        results = json.loads(issue_results_json or "[]")
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات مطابقة المرتجع غير صحيحة.")
    result_map = {int(x.get("id")): x for x in results if x.get("id")}

    for item in return_items:
        result = result_map.get(item.id)
        if not result or result.get("match") not in [True, False]:
            raise HTTPException(status_code=400, detail=f"حدد مطابقة الصنف «{item.product_name}».")
        item.warehouse_match = bool(result["match"])
        if item.warehouse_match:
            item.actual_quantity = item.quantity
            item.warehouse_note = None
        else:
            actual = str(result.get("actual_quantity") or "").strip()
            if not actual:
                raise HTTPException(status_code=400, detail=f"اكتب الكمية المستلمة فعليًا للصنف «{item.product_name}».")
            item.actual_quantity = actual
            item.warehouse_note = str(result.get("note") or "").strip() or None

    image = save_upload(photo, invoice_no, "return_warehouse")
    invoice.return_received = True
    invoice.return_photo = image or invoice.return_photo
    invoice.return_notes = notes.strip() or None
    invoice.return_received_at = datetime.utcnow()
    invoice.sales_return_required = True
    invoice.sales_return_reviewed = False

    # Customer-receipt follow-up and return accounting remain independent.
    if invoice.customer_receipt_required and not invoice.customer_receipt_received:
        invoice.status, invoice.current_owner = "CUSTOMER_RECEIPT_PENDING", "SALES_REP"
    else:
        invoice.status, invoice.current_owner = "FINAL_REVIEW_PENDING", "MULTI"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "RETURN_UPDATE", user["username"], invoice_no, {
        "items": [{
            "id": x.id,
            "source": "نقص تحميل" if x.stage == "WAREHOUSE" else "مرتجع عميل",
            "product": x.product_name,
            "declared": x.quantity,
            "matched": x.warehouse_match,
            "actual": x.actual_quantity,
        } for x in return_items]
    })
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/customer-receipt")
def customer_receipt_update(
    invoice_no: str,
    request: Request,
    match_status: str = Form("MATCH"),
    notes: str = Form(""),
    issues_json: str = Form("[]"),
    receipt_photo: UploadFile | None = File(None),
    source_return_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "customer_receipt_upload")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if not invoice.customer_receipt_required:
        raise HTTPException(status_code=400, detail="هذه الفاتورة لا تحتاج متابعة استلام عميل من المندوب.")
    if user["role"] == "SALES_REP":
        rep_id = user.get("sales_rep_id")
        if not rep_id or invoice.sales_rep_id != rep_id:
            raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لهذا المندوب.")

    if match_status not in ["MATCH", "SHORT", "OVER"]:
        raise HTTPException(status_code=400, detail="حالة المطابقة غير صحيحة.")

    receipt = save_upload(receipt_photo, invoice_no, "customer_final_receipt")
    if not receipt:
        raise HTTPException(status_code=400, detail="صورة استلام العميل النهائي إجبارية.")
    if invoice.goods_source == "CUSTOMER_TRANSFER":
        source_photo = save_upload(source_return_photo, invoice_no, "source_customer_return")
        if not source_photo:
            raise HTTPException(status_code=400, detail="صورة السحب من العميل الأول إجبارية.")
        invoice.source_return_photo = source_photo
        invoice.source_return_received_at = datetime.utcnow()
        invoice.source_return_received_by = user["username"]

    try:
        issue_rows = json.loads(issues_json or "[]")
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات فرق التسليم غير صحيحة.")

    valid_rows = []
    for row in issue_rows:
        try:
            product_id = int(row.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        product = db.get(Product, product_id)
        quantity = str(row.get("quantity") or "").strip()
        unit = str(row.get("unit") or "").strip()
        if product and quantity and unit:
            valid_rows.append((product, quantity, unit))

    if match_status in ["SHORT", "OVER"] and not valid_rows:
        raise HTTPException(
            status_code=400,
            detail="عند وجود فرق يجب تحديد الصنف والوحدة وكمية الفرق.",
        )

    db.query(InvoiceIssueItem).filter(
        InvoiceIssueItem.invoice_no == invoice_no,
        InvoiceIssueItem.stage == "SALES_REP",
    ).delete()

    issue_label = "نقص تسليم نهائي" if match_status == "SHORT" else "زيادة تسليم نهائي"
    for product, quantity, unit in valid_rows:
        db.add(InvoiceIssueItem(
            invoice_no=invoice_no,
            stage="SALES_REP",
            issue_type=issue_label,
            product_id=product.id,
            product_name=product.name,
            unit=unit,
            quantity=quantity,
        ))

    invoice.customer_receipt_received = True
    invoice.customer_receipt_photo = receipt
    invoice.customer_receipt_received_at = datetime.utcnow()
    invoice.customer_receipt_received_by = user["username"]
    invoice.customer_receipt_match = match_status
    invoice.customer_receipt_notes = notes.strip() or None

    # Any discrepancy discovered after external/office delivery is reviewed by HR,
    # not sent back to warehouse.
    invoice.delivery_discrepancy_required = match_status in ["SHORT", "OVER"]
    invoice.delivery_discrepancy_reviewed = False if invoice.delivery_discrepancy_required else True

    load_shortage_pending = db.scalar(select(InvoiceIssueItem.id).where(
        InvoiceIssueItem.invoice_no == invoice_no,
        InvoiceIssueItem.stage == "WAREHOUSE",
        InvoiceIssueItem.issue_type.in_(["نقص تحميل", "ناقص"]),
        InvoiceIssueItem.warehouse_match.is_(None),
    ).limit(1)) is not None

    if load_shortage_pending:
        invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
    elif invoice.delivery_discrepancy_required:
        invoice.status, invoice.current_owner = "DELIVERY_DISCREPANCY_PENDING", "HR"
    else:
        maybe_close_invoice(invoice)

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "CUSTOMER_RECEIPT_UPDATE", user["username"], invoice_no, {
        "match_status": match_status,
        "difference_items": len(valid_rows),
    })
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/delivery-discrepancy-review")
def delivery_discrepancy_review(
    invoice_no: str,
    request: Request,
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "delivery_discrepancy_review")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or not invoice.delivery_discrepancy_required:
        raise HTTPException(status_code=400, detail="لا يوجد فرق تسليم يحتاج مراجعة الموارد.")
    if invoice.delivery_discrepancy_reviewed:
        raise HTTPException(status_code=400, detail="تمت مراجعة فرق التسليم مسبقًا.")

    invoice.delivery_discrepancy_reviewed = True
    invoice.delivery_discrepancy_reviewed_at = datetime.utcnow()
    invoice.delivery_discrepancy_reviewed_by = user["username"]
    invoice.delivery_discrepancy_notes = notes.strip() or None
    invoice.updated_by = user["username"]
    closed = maybe_close_invoice(invoice)
    db.commit()
    audit(db, "DELIVERY_DISCREPANCY_REVIEW", user["username"], invoice_no, {"closed": closed})
    return {"ok": True, "closed": closed}


@app.post("/api/invoices/{invoice_no}/sales-return-review")
def sales_return_review(
    invoice_no: str,
    request: Request,
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "sales_return_review")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or not invoice.sales_return_required:
        raise HTTPException(status_code=400, detail="لا يوجد مردود يحتاج اعتماد محاسب المبيعات.")
    if not invoice.return_received:
        raise HTTPException(status_code=400, detail="لا يمكن اعتماد المردود قبل استلام ومطابقة المرتجع في المخزن.")
    if invoice.sales_return_reviewed:
        raise HTTPException(status_code=400, detail="تم اعتماد المردود مسبقًا.")

    invoice.sales_return_reviewed = True
    invoice.sales_return_reviewed_by = user["username"]
    invoice.sales_return_reviewed_at = datetime.utcnow()
    invoice.sales_return_notes = notes.strip() or None
    invoice.updated_by = user["username"]
    closed = maybe_close_invoice(invoice)
    db.commit()
    audit(db, "SALES_RETURN_REVIEW", user["username"], invoice_no, {"closed": closed})
    return {"ok": True, "closed": closed}

@app.post("/api/invoices/{invoice_no}/close")
def close_invoice(
    invoice_no: str,
    request: Request,
    original_received: str = Form(...),
    notes: str = Form(""),
    original_document_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "close_invoice")
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or not invoice.loaded_at or invoice.status == "CLOSED":
        raise HTTPException(status_code=400, detail="الفاتورة ليست جاهزة لمتابعة أصلها.")

    if original_received not in ["نعم", "لا"]:
        raise HTTPException(status_code=400, detail="حدد هل تم استلام أصل الفاتورة أم لا.")

    invoice.closure_notes = notes.strip() or None
    invoice.updated_by = user["username"]

    if original_received == "لا":
        # لا نطلب من الموارد إعادة رفع صورة استلام العميل ولا صورة أخرى.
        # تبقى الفاتورة معلقة حتى يصل أصلها الورقي.
        invoice.original_document_received = False
        db.commit()
        audit(db, "ORIGINAL_DOCUMENT_NOT_RECEIVED", user["username"], invoice_no)
        return {"ok": True, "closed": False, "original_received": False}

    # Restore the original-invoice photo workflow. Upload only when a new file was selected.
    # If an old image is already linked/recovered, do not create a duplicate Storage object.
    if not invoice.original_document_photo:
        recover_existing_photo_links(invoice)
    original_image = save_upload(original_document_photo, invoice_no, "original_document")
    if original_image:
        invoice.original_document_photo = original_image
    if not invoice.original_document_photo:
        raise HTTPException(status_code=400, detail="صورة أصل الفاتورة إجبارية عند تأكيد استلام الأصل.")

    invoice.original_document_received = True
    invoice.original_document_received_at = datetime.utcnow()
    invoice.original_document_received_by = user["username"]

    pending_rep_shortage = False
    if invoice.delivery_mode == "SALES_REP_SELF":
        pending_rep_shortage = db.scalar(select(InvoiceIssueItem.id).where(
            InvoiceIssueItem.invoice_no == invoice_no,
            InvoiceIssueItem.stage == "WAREHOUSE",
            InvoiceIssueItem.issue_type.in_(["نقص تحميل", "ناقص"]),
            InvoiceIssueItem.warehouse_match.is_(None),
        ).limit(1)) is not None

    if pending_rep_shortage:
        invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
        closed = False
    else:
        closed = maybe_close_invoice(invoice)

    db.commit()
    audit(db, "ORIGINAL_DOCUMENT_RECEIVED", user["username"], invoice_no, {"closed": closed})
    return {"ok": True, "closed": closed, "original_received": True}

@app.get("/api/settings/invoice-sequence")
def get_invoice_sequence(request: Request, db: Session = Depends(get_db)):
    require_user(request)
    return invoice_sequence_status(db)


@app.post("/api/settings/invoice-sequence")
def set_invoice_sequence(
    request: Request,
    start: int = Form(...),
    db: Session = Depends(get_db),
):
    user = require_user(request)
    if user["role"] not in ["ADMIN", "SALES_ACCOUNTANT"]:
        raise HTTPException(status_code=403, detail="تحديد بداية تسلسل الفواتير متاح للإدارة أو محاسب المبيعات.")
    if start < 1:
        raise HTTPException(status_code=400, detail="رقم بداية التسلسل يجب أن يكون أكبر من صفر.")
    row = db.get(AppSetting, "invoice_sequence_start")
    if row is None:
        row = AppSetting(key="invoice_sequence_start", value=str(start))
        db.add(row)
    else:
        row.value = str(start)
    ack = db.get(AppSetting, "invoice_sequence_ack_week")
    if ack:
        ack.value = ""
    db.commit()
    audit(db, "SET_INVOICE_SEQUENCE_START", user["username"], details={"start": start})
    return invoice_sequence_status(db)



@app.get("/api/documents")
def documents_archive(
    request: Request,
    category: str = "originals",
    q: str = "",
    db: Session = Depends(get_db),
):
    user = require_user(request)
    user_row = db.scalar(select(User).where(User.username == user["username"]))
    perms = effective_permissions(user_row, user)
    if user.get("username") != "admin" and "documents" not in perms["screens"]:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية لعرض المستندات.")

    stmt = select(Invoice)
    if user["role"] == "SALES_REP":
        stmt = stmt.where(Invoice.sales_rep_id == user.get("sales_rep_id"))
    elif user["role"] == "DRIVER":
        stmt = stmt.where(Invoice.driver_code == user.get("driver_code", ""))

    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Invoice.invoice_no.like(like), Invoice.customer.like(like), Invoice.sales_rep_name.like(like)))

    rows = db.scalars(stmt.order_by(Invoice.created_at.desc()).limit(500)).all()
    data = []
    recovered_any = False
    for inv in rows:
        needs_recovery = (
            (category == "originals" and inv.original_document_received and not inv.original_document_photo) or
            (category == "returns" and (inv.return_received or inv.sales_return_reviewed) and not (inv.return_photo or inv.driver_return_photo)) or
            (category == "customer_receipts" and inv.customer_receipt_received and not (inv.customer_receipt_photo or inv.receipt_photo)) or
            (category == "carrier_receipts" and not inv.carrier_receipt_photo)
        )
        if needs_recovery and recover_existing_photo_links(inv):
            recovered_any = True
        if category == "originals":
            if not inv.original_document_received:
                continue
            # Legacy compatibility: older versions sometimes stored the photographed
            # original invoice in receipt_photo. Display that existing object only;
            # never copy it or upload another file.
            original_photo = inv.original_document_photo or inv.receipt_photo
            data.append({
                "invoice_no": str(inv.invoice_no or ""), "customer": inv.customer, "sales_rep_name": inv.sales_rep_name,
                "date": inv.original_document_received_at.isoformat() if inv.original_document_received_at else None,
                "by": inv.original_document_received_by, "photo": original_photo,
                "label": "أصل الفاتورة",
                "legacy_photo": bool(not inv.original_document_photo and inv.receipt_photo),
            })
        elif category == "returns":
            if not (inv.return_received or inv.sales_return_reviewed):
                continue
            data.append({
                "invoice_no": str(inv.invoice_no or ""), "customer": inv.customer, "sales_rep_name": inv.sales_rep_name,
                "date": (inv.sales_return_reviewed_at or inv.return_received_at).isoformat() if (inv.sales_return_reviewed_at or inv.return_received_at) else None,
                "by": inv.sales_return_reviewed_by or inv.updated_by, "photo": inv.return_photo or inv.driver_return_photo,
                "label": "مستند المرتجع",
            })
        elif category == "customer_receipts":
            photo = inv.customer_receipt_photo or (inv.receipt_photo if inv.delivery_target == "CUSTOMER" or inv.delivery_mode == "CUSTOMER_SELF" else None)
            if not photo:
                continue
            data.append({
                "invoice_no": str(inv.invoice_no or ""), "customer": inv.customer, "sales_rep_name": inv.sales_rep_name,
                "date": (inv.customer_receipt_received_at or inv.delivered_at).isoformat() if (inv.customer_receipt_received_at or inv.delivered_at) else None,
                "by": inv.customer_receipt_received_by or inv.driver_name, "photo": photo,
                "label": "استلام العميل",
            })
        elif category == "carrier_receipts":
            if not inv.carrier_receipt_photo:
                continue
            data.append({
                "invoice_no": str(inv.invoice_no or ""), "customer": inv.customer, "sales_rep_name": inv.sales_rep_name,
                "date": (inv.delivered_at or inv.loaded_at).isoformat() if (inv.delivered_at or inv.loaded_at) else None,
                "by": inv.driver_name or inv.warehouse_user, "photo": inv.carrier_receipt_photo,
                "label": "استلام الناقل / مكتب النقل",
            })
    if recovered_any:
        db.commit()
    return data


@app.get("/api/dashboard/{bucket}")
def dashboard_bucket(bucket: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    user_row = db.scalar(select(User).where(User.username == user["username"]))
    perms = effective_permissions(user_row, user)
    required_screen = {
        "warehouse": "warehouse_card", "drivers": "drivers_card",
        "returns": "returns_card", "documents": "documents_card", "closed": "closed_card",
    }.get(bucket)
    if user.get("username") != "admin" and required_screen and required_screen not in perms["screens"]:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية عرض هذا المربع.")
    mapping = {
        "warehouse": ["WAREHOUSE_PENDING"], "drivers": ["DRIVER_PENDING","POSTPONED"],
        "returns": ["RETURN_PENDING"], "documents": ["DOCUMENT_PENDING","FINAL_REVIEW_PENDING","CUSTOMER_RECEIPT_PENDING","DELIVERY_DISCREPANCY_PENDING"], "closed": ["CLOSED"]
    }
    statuses = mapping.get(bucket)
    if not statuses:
        raise HTTPException(status_code=404, detail="القائمة غير موجودة.")
    stmt = select(Invoice).where(Invoice.status.in_(statuses))
    if user["role"] == "DRIVER":
        stmt = stmt.where(Invoice.driver_code == user.get("driver_code",""))
    elif user["role"] == "SALES_REP":
        stmt = stmt.where(Invoice.sales_rep_id == user.get("sales_rep_id"))
    return [invoice_dict(x) for x in db.scalars(stmt.order_by(Invoice.created_at.desc())).all()]


@app.get("/api/invoices/{invoice_no}/issues")
def invoice_issues(invoice_no: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية.")
    if user["role"] == "SALES_REP" and invoice.sales_rep_id != user.get("sales_rep_id"):
        raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لمندوبك.")
    rows = db.scalars(select(InvoiceIssueItem).where(InvoiceIssueItem.invoice_no == invoice_no).order_by(InvoiceIssueItem.id)).all()
    return [{"id":x.id,"stage":x.stage,"issue_type":x.issue_type,"product_id":x.product_id,
             "product_name":x.product_name,"unit":x.unit,"quantity":x.quantity,
             "warehouse_match":x.warehouse_match,"actual_quantity":x.actual_quantity,
             "warehouse_note":x.warehouse_note} for x in rows]


@app.post("/api/settings/invoice-sequence/ack")
def acknowledge_invoice_sequence(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    if user["role"] not in ["ADMIN", "SALES_ACCOUNTANT"]:
        raise HTTPException(status_code=403, detail="هذه العملية للإدارة أو محاسب المبيعات.")
    week_key = datetime.utcnow().strftime("%G-W%V")
    row = db.get(AppSetting, "invoice_sequence_ack_week")
    if row is None:
        row = AppSetting(key="invoice_sequence_ack_week", value=week_key)
        db.add(row)
    else:
        row.value = week_key
    db.commit()
    audit(db, "ACK_INVOICE_SEQUENCE", user["username"], details={"week": week_key})
    return invoice_sequence_status(db)


@app.post("/api/products")
def create_product(request: Request, name: str = Form(...), units: str = Form(...), db: Session = Depends(get_db)):
    user = require_permission(request, db, "manage_products")
    name = name.strip()
    if db.scalar(select(Product).where(Product.name == name)):
        raise HTTPException(status_code=400, detail="الصنف موجود مسبقًا.")
    unit_list = [x.strip() for x in units.replace("،", ",").split(",") if x.strip()]
    if not unit_list:
        raise HTTPException(status_code=400, detail="أضف وحدة واحدة على الأقل.")
    db.add(Product(name=name, units_json=json.dumps(unit_list, ensure_ascii=False), active=True))
    db.commit()
    audit(db, "CREATE_PRODUCT", user["username"], details={"product":name,"units":unit_list})
    return {"ok": True}


@app.post("/api/users/{username}/permissions")
def update_permissions(username: str, request: Request, permissions_json: str = Form(...), db: Session = Depends(get_db)):
    admin = require_permission(request, db, "manage_users")
    if username == "admin":
        raise HTTPException(status_code=400, detail="صلاحيات المدير الرئيسي ثابتة ولا يمكن تقييدها.")
    row = db.scalar(select(User).where(User.username == username))
    if not row:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
    try:
        data = json.loads(permissions_json)
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات الصلاحيات غير صحيحة.")
    allowed_s = set(PERMISSION_CATALOG["screens"])
    allowed_a = set(PERMISSION_CATALOG["actions"])
    data = {"screens":[x for x in data.get("screens",[]) if x in allowed_s],
            "actions":[x for x in data.get("actions",[]) if x in allowed_a]}
    row.permissions_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    audit(db, "UPDATE_PERMISSIONS", admin["username"], details={"user":username})
    return {"ok": True}


@app.post("/api/vehicles")
def create_vehicle(
    request: Request,
    name: str = Form(...),
    plate_no: str = Form(...),
    vehicle_type: str = Form(""),
    status: str = Form("AVAILABLE"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "manage_vehicles")
    if db.scalar(select(Vehicle).where(Vehicle.plate_no == plate_no.strip())):
        raise HTTPException(status_code=400, detail="رقم اللوحة موجود.")
    db.add(Vehicle(
        name=name.strip(),
        plate_no=plate_no.strip(),
        vehicle_type=vehicle_type.strip() or None,
        status=status,
        active=True,
        notes=notes.strip() or None,
    ))
    db.commit()
    audit(db, "CREATE_VEHICLE", user["username"])
    return {"ok": True}


@app.post("/api/users")
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    driver_code: str = Form(""),
    phone: str = Form(""),
    sales_rep_id: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_permission(request, db, "manage_users")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="الدور غير صحيح.")
    rep_id_value = int(sales_rep_id) if sales_rep_id.strip().isdigit() else None
    if role == "SALES_REP":
        if not rep_id_value or not db.get(SalesRep, rep_id_value):
            raise HTTPException(status_code=400, detail="حساب المندوب يجب ربطه بمندوب موجود.")
    if role == "DRIVER" and not driver_code.strip():
        raise HTTPException(status_code=400, detail="رمز السائق إجباري لحساب السائق.")
    username = username.lower().strip()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=400, detail="اسم المستخدم موجود.")
    db.add(User(
        username=username,
        password_hash=hash_password(password),
        name=name.strip(),
        role=role,
        driver_code=driver_code.strip() or None,
        phone=phone.strip() or None,
        sales_rep_id=rep_id_value,
        active=True,
    ))
    db.commit()
    audit(db, "CREATE_USER", admin["username"])
    return {"ok": True}


@app.post("/api/users/{username}")
def update_user(
    username: str,
    request: Request,
    new_username: str = Form(...),
    name: str = Form(...),
    role: str = Form(...),
    driver_code: str = Form(""),
    phone: str = Form(""),
    sales_rep_id: str = Form(""),
    active: str = Form("true"),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_permission(request, db, "manage_users")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="الدور غير صحيح.")
    rep_id_value = int(sales_rep_id) if sales_rep_id.strip().isdigit() else None
    if role == "SALES_REP":
        if not rep_id_value or not db.get(SalesRep, rep_id_value):
            raise HTTPException(status_code=400, detail="حساب المندوب يجب ربطه بمندوب موجود.")
    if role == "DRIVER" and not driver_code.strip():
        raise HTTPException(status_code=400, detail="رمز السائق إجباري لحساب السائق.")
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")

    new_username = new_username.lower().strip()
    duplicate = db.scalar(select(User).where(User.username == new_username, User.id != user.id))
    if duplicate:
        raise HTTPException(status_code=400, detail="اسم المستخدم مستخدم.")

    user.username = new_username
    user.name = name.strip()
    user.role = role
    user.driver_code = driver_code.strip() or None
    user.phone = phone.strip() or None
    user.sales_rep_id = rep_id_value
    user.active = active == "true"
    if password.strip():
        user.password_hash = hash_password(password.strip())

    db.commit()
    audit(db, "UPDATE_USER", admin["username"], details={"user": new_username})
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/edit-hr")
def edit_invoice_hr(
    invoice_no: str,
    request: Request,
    new_invoice_no: str = Form(...),
    customer: str = Form(""),
    notes: str = Form(""),
    sales_rep_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "HR"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "HR" and invoice.status != "WAREHOUSE_PENDING":
        raise HTTPException(status_code=403, detail="تم اعتماد الفاتورة من المخزن ولا يمكن للموارد تعديلها.")
    new_invoice_no = new_invoice_no.strip()
    duplicate = db.scalar(select(Invoice).where(Invoice.invoice_no == new_invoice_no, Invoice.id != invoice.id))
    if duplicate:
        raise HTTPException(status_code=400, detail="رقم الفاتورة موجود مسبقًا.")
    rep = None
    if sales_rep_id.strip():
        try: rep = db.get(SalesRep, int(sales_rep_id))
        except ValueError: rep = None
        if not rep:
            raise HTTPException(status_code=400, detail="المندوب غير موجود.")
    old_no = invoice.invoice_no
    invoice.invoice_no = new_invoice_no
    invoice.customer = customer.strip() or None
    invoice.sales_rep_id = rep.id if rep else None
    invoice.sales_rep_name = rep.name if rep else None
    invoice.hr_notes = notes.strip() or None
    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "EDIT_HR_DATA", user["username"], new_invoice_no, {"old_invoice_no": old_no})
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/edit-warehouse")
def edit_invoice_warehouse(
    invoice_no: str,
    request: Request,
    driver_code: str = Form(...),
    vehicle_id: str = Form(""),
    load_status: str = Form(...),
    shortage_reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "WAREHOUSE"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "WAREHOUSE" and invoice.status not in ["WAREHOUSE_PENDING", "DRIVER_PENDING"]:
        raise HTTPException(status_code=403, detail="اعتمد السائق المرحلة ولا يمكن للمخزن تعديلها.")

    driver = db.scalar(select(User).where(
        User.driver_code == driver_code,
        User.role == "DRIVER",
        User.active == True,
    ))
    try:
        vehicle_id_int = int(vehicle_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="اختر سيارة صحيحة.")
    vehicle = db.get(Vehicle, vehicle_id_int)
    if not driver:
        raise HTTPException(status_code=400, detail="اختر سائقًا صحيحًا.")
    if not vehicle or not vehicle.active:
        raise HTTPException(status_code=400, detail="اختر سيارة صحيحة.")

    invoice.driver_code = driver.driver_code or ""
    invoice.driver_name = driver.name
    invoice.is_external_driver = driver.is_external_driver
    invoice.vehicle_no = f"{vehicle.name} - {vehicle.plate_no}"
    invoice.load_status = load_status
    invoice.warehouse_shortage_reason = shortage_reason.strip() or None
    invoice.warehouse_notes = notes.strip() or None
    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "EDIT_WAREHOUSE_DATA", user["username"], invoice_no)
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/edit-driver")
def edit_invoice_driver(
    invoice_no: str,
    request: Request,
    delivery_result: str = Form(...),
    return_qty_declared: str = Form("0"),
    reason: str = Form(""),
    notes: str = Form(""),
    receipt_photo: UploadFile | None = File(None),
    return_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "DRIVER"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "DRIVER":
        if invoice.driver_code != user.get("driver_code", ""):
            raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لك.")
        if invoice.status not in ["DRIVER_PENDING", "POSTPONED", "RETURN_PENDING", "DOCUMENT_PENDING"]:
            raise HTTPException(status_code=403, detail="تم اعتماد المرحلة التالية ولا يمكن للسائق تعديلها.")
        if invoice.status == "RETURN_PENDING" and invoice.return_received:
            raise HTTPException(status_code=403, detail="استلم المخزن المرتجع ولا يمكن تعديل النتيجة.")
        if invoice.status == "DOCUMENT_PENDING" and invoice.original_document_received:
            raise HTTPException(status_code=403, detail="أغلقت الموارد الفاتورة ولا يمكن تعديلها.")

    receipt = save_upload(receipt_photo, invoice_no, "receipt_edit")
    returned = save_upload(return_photo, invoice_no, "return_driver_edit")
    if user["role"] == "DRIVER" and not (receipt or invoice.receipt_photo):
        raise HTTPException(status_code=400, detail="يجب رفع صورة الاستلام قبل اعتماد النتيجة.")
    try:
        return_qty_value = float(return_qty_declared or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="كمية المرتجع غير صحيحة.")
    invoice.delivery_result = delivery_result
    invoice.delivery_reason = reason.strip() or None
    invoice.driver_notes = notes.strip() or None
    invoice.return_qty_declared = return_qty_value
    invoice.receipt_photo = receipt or invoice.receipt_photo
    invoice.driver_return_photo = returned or invoice.driver_return_photo

    if delivery_result == "تم كامل":
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
    elif delivery_result in ["تم جزئي", "رفض كامل"]:
        invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
    else:
        invoice.status, invoice.current_owner = "POSTPONED", "DRIVER"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "EDIT_DRIVER_DATA", user["username"], invoice_no)
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/admin-edit")
def admin_edit_invoice(
    invoice_no: str,
    request: Request,
    new_invoice_no: str = Form(...),
    customer: str = Form(""),
    driver_code: str = Form(""),
    vehicle_no: str = Form(""),
    status: str = Form(...),
    hr_notes: str = Form(""),
    warehouse_notes: str = Form(""),
    driver_notes: str = Form(""),
    sales_rep_id: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_role(request, ["ADMIN"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")

    new_invoice_no = new_invoice_no.strip()
    duplicate = db.scalar(select(Invoice).where(Invoice.invoice_no == new_invoice_no, Invoice.id != invoice.id))
    if duplicate:
        raise HTTPException(status_code=400, detail="رقم الفاتورة موجود مسبقًا.")

    if driver_code.strip():
        driver = db.scalar(select(User).where(User.driver_code == driver_code.strip(), User.role == "DRIVER"))
        if not driver:
            raise HTTPException(status_code=400, detail="السائق غير موجود.")
        invoice.driver_code = driver.driver_code or ""
        invoice.driver_name = driver.name
        invoice.is_external_driver = driver.is_external_driver

    rep = None
    if sales_rep_id.strip():
        try: rep = db.get(SalesRep, int(sales_rep_id))
        except ValueError: rep = None
        if not rep:
            raise HTTPException(status_code=400, detail="المندوب غير موجود.")
    invoice.invoice_no = new_invoice_no
    invoice.customer = customer.strip() or None
    invoice.sales_rep_id = rep.id if rep else None
    invoice.sales_rep_name = rep.name if rep else None
    invoice.vehicle_no = vehicle_no.strip() or None
    invoice.status = status
    invoice.current_owner = {
        "WAREHOUSE_PENDING": "WAREHOUSE",
        "DRIVER_PENDING": "DRIVER",
        "POSTPONED": "DRIVER",
        "RETURN_PENDING": "WAREHOUSE",
        "DOCUMENT_PENDING": "HR",
        "CLOSED": "ARCHIVE",
    }.get(status, invoice.current_owner)
    invoice.hr_notes = hr_notes.strip() or None
    invoice.warehouse_notes = warehouse_notes.strip() or None
    invoice.driver_notes = driver_notes.strip() or None
    invoice.updated_by = admin["username"]
    db.commit()
    audit(db, "ADMIN_EDIT_INVOICE", admin["username"], new_invoice_no)
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/delete")
def delete_invoice(invoice_no: str, request: Request, db: Session = Depends(get_db)):
    admin = require_role(request, ["ADMIN"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    db.delete(invoice)
    db.commit()
    audit(db, "ADMIN_DELETE_INVOICE", admin["username"], invoice_no)
    return {"ok": True}


@app.get("/api/logs")
def get_logs(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    row = db.scalar(select(User).where(User.username == user["username"]))
    perms = effective_permissions(row, user)
    if user.get("username") != "admin" and "logs" not in perms["screens"]:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية عرض سجل الحركات.")
    return list_logs(db)


@app.post("/api/logs/{log_id}/delete")
def delete_log(log_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_role(request, ["ADMIN"])
    log = db.get(AuditLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="الحركة غير موجودة.")
    details = {"deleted_log_id": log.id, "action": log.action, "invoice_no": log.invoice_no}
    db.delete(log)
    db.commit()
    audit(db, "ADMIN_DELETE_LOG", admin["username"], details=details)
    return {"ok": True}


@app.post("/api/products/{product_id}/update")
def update_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    units: str = Form(...),
    active: str = Form("true"),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "manage_products")
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="الصنف غير موجود.")
    duplicate = db.scalar(select(Product).where(Product.name == name.strip(), Product.id != product_id))
    if duplicate:
        raise HTTPException(status_code=400, detail="يوجد صنف آخر بنفس الاسم.")
    unit_list = [x.strip() for x in units.replace("،", ",").split(",") if x.strip()]
    if not unit_list:
        raise HTTPException(status_code=400, detail="أضف وحدة واحدة على الأقل.")
    before = {"name": product.name, "units": product.units_json, "active": product.active}
    product.name = name.strip()
    product.units_json = json.dumps(unit_list, ensure_ascii=False)
    product.active = active == "true"
    db.commit()
    audit(db, "UPDATE_PRODUCT", user["username"], details={"before": before, "product_id": product_id})
    return {"ok": True}


@app.post("/api/products/{product_id}/toggle")
def toggle_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission(request, db, "manage_products")
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="الصنف غير موجود.")
    product.active = not product.active
    db.commit()
    audit(db, "TOGGLE_PRODUCT", user["username"], details={"product_id": product_id, "active": product.active})
    return {"ok": True, "active": product.active}


@app.post("/api/products/{product_id}/delete")
def delete_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission(request, db, "manage_products")
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="الصنف غير موجود.")
    used = db.scalar(select(InvoiceIssueItem.id).where(InvoiceIssueItem.product_id == product_id).limit(1))
    if used:
        product.active = False
        db.commit()
        audit(db, "DEACTIVATE_USED_PRODUCT", user["username"], details={"product_id": product_id})
        return {"ok": True, "deactivated": True, "message": "الصنف مستخدم سابقًا، لذلك تم تعطيله بدل حذفه."}
    db.delete(product)
    db.commit()
    audit(db, "DELETE_PRODUCT", user["username"], details={"product_id": product_id})
    return {"ok": True, "deleted": True}


@app.post("/api/vehicles/{vehicle_id}/update")
def update_vehicle(
    vehicle_id: int,
    request: Request,
    name: str = Form(...),
    plate_no: str = Form(...),
    vehicle_type: str = Form(""),
    status: str = Form("AVAILABLE"),
    notes: str = Form(""),
    active: str = Form("true"),
    db: Session = Depends(get_db),
):
    user = require_permission(request, db, "manage_vehicles")
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="السيارة غير موجودة.")
    duplicate = db.scalar(select(Vehicle).where(Vehicle.plate_no == plate_no.strip(), Vehicle.id != vehicle_id))
    if duplicate:
        raise HTTPException(status_code=400, detail="رقم اللوحة مستخدم في سيارة أخرى.")
    before = {"name": vehicle.name, "plate_no": vehicle.plate_no, "status": vehicle.status, "active": vehicle.active}
    vehicle.name = name.strip()
    vehicle.plate_no = plate_no.strip()
    vehicle.vehicle_type = vehicle_type.strip() or None
    vehicle.status = status
    vehicle.notes = notes.strip() or None
    vehicle.active = active == "true"
    db.commit()
    audit(db, "UPDATE_VEHICLE", user["username"], details={"before": before, "vehicle_id": vehicle_id})
    return {"ok": True}


@app.post("/api/vehicles/{vehicle_id}/toggle")
def toggle_vehicle(vehicle_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission(request, db, "manage_vehicles")
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="السيارة غير موجودة.")
    vehicle.active = not vehicle.active
    db.commit()
    audit(db, "TOGGLE_VEHICLE", user["username"], details={"vehicle_id": vehicle_id, "active": vehicle.active})
    return {"ok": True, "active": vehicle.active}


@app.post("/api/vehicles/{vehicle_id}/delete")
def delete_vehicle(vehicle_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission(request, db, "manage_vehicles")
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="السيارة غير موجودة.")
    used = db.scalar(select(Invoice.id).where(Invoice.vehicle_no.like(f"%{vehicle.plate_no}%")).limit(1))
    if used:
        vehicle.active = False
        db.commit()
        audit(db, "DEACTIVATE_USED_VEHICLE", user["username"], details={"vehicle_id": vehicle_id})
        return {"ok": True, "deactivated": True, "message": "السيارة مستخدمة في فواتير سابقة، لذلك تم تعطيلها بدل حذفها."}
    db.delete(vehicle)
    db.commit()
    audit(db, "DELETE_VEHICLE", user["username"], details={"vehicle_id": vehicle_id})
    return {"ok": True, "deleted": True}


@app.post("/api/users/{username}/toggle")
def toggle_user(username: str, request: Request, db: Session = Depends(get_db)):
    admin = require_permission(request, db, "manage_users")
    if username == "admin":
        raise HTTPException(status_code=400, detail="لا يمكن تعطيل المدير الرئيسي.")
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
    user.active = not user.active
    db.commit()
    audit(db, "TOGGLE_USER", admin["username"], details={"user": username, "active": user.active})
    return {"ok": True, "active": user.active}


@app.post("/api/users/{username}/delete")
def delete_user(username: str, request: Request, db: Session = Depends(get_db)):
    admin = require_permission(request, db, "manage_users")
    if username == "admin":
        raise HTTPException(status_code=400, detail="لا يمكن حذف المدير الرئيسي.")
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
    # Preserve historical audit/invoice references: deactivate instead of destructive deletion.
    user.active = False
    db.commit()
    audit(db, "DEACTIVATE_USER", admin["username"], details={"user": username})
    return {"ok": True, "deactivated": True}
