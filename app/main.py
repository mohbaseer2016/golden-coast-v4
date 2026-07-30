from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .drive_service import DriveStorage
from .models import AuditLog, Invoice, User, Vehicle
from .security import clear_session, hash_password, require_role, require_user, set_session, verify_password

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ROLES = {"ADMIN", "HR", "WAREHOUSE", "DRIVER"}

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
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="المسموح صور فقط.")
    raw = file.file.read()
    if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID"):
        try:
            return DriveStorage().upload_image(invoice_no, kind, raw)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"فشل رفع الصورة إلى Google Drive: {exc}")
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    folder = UPLOAD_DIR / str(datetime.now().year) / f"{datetime.now().month:02d}" / invoice_no
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{kind}_{uuid.uuid4().hex[:10]}{suffix}"
    target.write_bytes(raw)
    return "/" + str(target.relative_to(ROOT_DIR)).replace("\\", "/")


def upsert_user(db: Session, username: str, password: str, name: str, role: str,
                driver_code: str | None = None, external: bool = False):
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
    else:
        user.password_hash = hash_password(password)
        user.name = name
        user.role = role
        user.driver_code = driver_code
        user.active = True
        user.is_external_driver = external


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
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
    return templates.TemplateResponse("index.html", {"request": request})


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


def user_dict(user: User):
    return {
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "driver_code": user.driver_code,
        "phone": user.phone,
        "active": user.active,
        "is_external_driver": user.is_external_driver,
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


def invoice_dict(invoice: Invoice):
    return {
        "invoice_no": invoice.invoice_no,
        "customer": invoice.customer,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "driver_code": invoice.driver_code,
        "driver_name": invoice.driver_name,
        "is_external_driver": invoice.is_external_driver,
        "vehicle_no": invoice.vehicle_no,
        "status": invoice.status,
        "load_status": invoice.load_status,
        "warehouse_shortage_reason": invoice.warehouse_shortage_reason,
        "delivery_result": invoice.delivery_result,
        "delivery_reason": invoice.delivery_reason,
        "receipt_photo": invoice.receipt_photo,
        "driver_return_photo": invoice.driver_return_photo,
        "return_qty_declared": invoice.return_qty_declared,
        "return_received": invoice.return_received,
        "return_qty_actual": invoice.return_qty_actual,
        "return_difference": invoice.return_difference,
        "return_condition": invoice.return_condition,
        "return_photo": invoice.return_photo,
        "original_document_received": invoice.original_document_received,
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
        stmt = stmt.where(Invoice.status == "DOCUMENT_PENDING")
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
    rows = db.scalars(select(Invoice)).all()
    count = lambda status: sum(1 for x in rows if x.status == status)
    return {
        "my_pending": len(get_queue(db, user)),
        "warehouse_pending": count("WAREHOUSE_PENDING"),
        "driver_pending": count("DRIVER_PENDING") + count("POSTPONED"),
        "returns_pending": count("RETURN_PENDING"),
        "documents_pending": count("DOCUMENT_PENDING"),
        "closed": count("CLOSED"),
    }


@app.get("/api/bootstrap")
def bootstrap(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    return {
        "user": user,
        "stats": get_stats(db, user),
        "queue": get_queue(db, user),
        "drivers": list_drivers(db),
        "vehicles": list_vehicles(db),
        "users": list_users(db) if user["role"] == "ADMIN" else [],
        "logs": list_logs(db) if user["role"] == "ADMIN" else [],
    }


@app.post("/api/invoices")
def create_invoice(
    request: Request,
    invoice_no: str = Form(...),
    customer: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "HR"])
    invoice_no = invoice_no.strip()
    if db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no)):
        raise HTTPException(status_code=400, detail="رقم الفاتورة موجود مسبقًا.")
    db.add(Invoice(
        invoice_no=invoice_no,
        customer=customer.strip() or None,
        hr_notes=notes.strip() or None,
        created_by=user["username"],
        updated_by=user["username"],
        status="WAREHOUSE_PENDING",
        current_owner="WAREHOUSE",
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
    return [invoice_dict(x) for x in db.scalars(stmt.order_by(Invoice.created_at.desc()).limit(200)).all()]


@app.get("/api/invoices/{invoice_no}")
def get_invoice(invoice_no: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية.")
    return invoice_dict(invoice)


@app.post("/api/invoices/{invoice_no}/warehouse")
def warehouse_update(
    invoice_no: str,
    request: Request,
    driver_code: str = Form(...),
    vehicle_id: int = Form(...),
    load_status: str = Form(...),
    shortage_reason: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "WAREHOUSE"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status != "WAREHOUSE_PENDING":
        raise HTTPException(status_code=400, detail="الفاتورة ليست معلقة في المخزن.")

    driver = db.scalar(select(User).where(
        User.driver_code == driver_code,
        User.role == "DRIVER",
        User.active == True,
    ))
    vehicle = db.get(Vehicle, vehicle_id)
    if not driver:
        raise HTTPException(status_code=400, detail="اختر سائقًا.")
    if not vehicle or not vehicle.active:
        raise HTTPException(status_code=400, detail="اختر سيارة.")

    invoice.driver_code = driver.driver_code or ""
    invoice.driver_name = driver.name
    invoice.is_external_driver = driver.is_external_driver
    invoice.vehicle_no = f"{vehicle.name} - {vehicle.plate_no}"
    invoice.load_status = load_status
    invoice.warehouse_shortage_reason = shortage_reason.strip() or None
    invoice.warehouse_notes = notes.strip() or None
    invoice.warehouse_photo = save_upload(photo, invoice_no, "warehouse") or invoice.warehouse_photo
    invoice.loaded_at = datetime.utcnow()

    if load_status == "مرفوض من المخزن":
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
    elif driver.is_external_driver:
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
        invoice.delivery_result = "سائق خارجي — بانتظار إرسال الاستلام للموارد"
    else:
        invoice.status, invoice.current_owner = "DRIVER_PENDING", "DRIVER"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "WAREHOUSE_UPDATE", user["username"], invoice_no, {
        "driver": driver.name,
        "vehicle": invoice.vehicle_no,
        "load_status": load_status,
    })
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/driver")
def driver_update(
    invoice_no: str,
    request: Request,
    delivery_result: str = Form(...),
    return_qty_declared: float = Form(0),
    reason: str = Form(""),
    notes: str = Form(""),
    receipt_photo: UploadFile | None = File(None),
    return_photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "DRIVER"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status not in ["DRIVER_PENDING", "POSTPONED"]:
        raise HTTPException(status_code=400, detail="الفاتورة ليست مع السائق.")
    if user["role"] == "DRIVER" and invoice.driver_code != user.get("driver_code", ""):
        raise HTTPException(status_code=403, detail="الفاتورة ليست مسندة لك.")

    receipt = save_upload(receipt_photo, invoice_no, "receipt")
    returned = save_upload(return_photo, invoice_no, "return_driver")
    if delivery_result == "تم كامل" and not (receipt or invoice.receipt_photo):
        raise HTTPException(status_code=400, detail="صورة الاستلام مطلوبة.")

    invoice.delivery_result = delivery_result
    invoice.delivery_reason = reason.strip() or None
    invoice.driver_notes = notes.strip() or None
    invoice.return_qty_declared = return_qty_declared
    invoice.receipt_photo = receipt or invoice.receipt_photo
    invoice.driver_return_photo = returned or invoice.driver_return_photo
    invoice.delivered_at = datetime.utcnow()

    if delivery_result == "تم كامل":
        invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
    elif delivery_result in ["تم جزئي", "رفض كامل"]:
        invoice.status, invoice.current_owner = "RETURN_PENDING", "WAREHOUSE"
    else:
        invoice.status, invoice.current_owner = "POSTPONED", "DRIVER"

    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "DRIVER_UPDATE", user["username"], invoice_no)
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/return")
def return_update(
    invoice_no: str,
    request: Request,
    return_qty_actual: float = Form(...),
    condition: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "WAREHOUSE"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status != "RETURN_PENDING":
        raise HTTPException(status_code=400, detail="لا يوجد مرتجع.")

    difference = float(invoice.return_qty_declared or 0) - return_qty_actual
    if abs(difference) > 1e-9:
        raise HTTPException(status_code=400, detail=f"فرق الكمية: {difference}")

    image = save_upload(photo, invoice_no, "return_warehouse")
    if not image:
        raise HTTPException(status_code=400, detail="صورة المرتجع مطلوبة.")

    invoice.return_received = True
    invoice.return_qty_actual = return_qty_actual
    invoice.return_difference = difference
    invoice.return_condition = condition.strip() or None
    invoice.return_notes = notes.strip() or None
    invoice.return_photo = image
    invoice.return_received_at = datetime.utcnow()
    invoice.status, invoice.current_owner = "DOCUMENT_PENDING", "HR"
    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "RETURN_UPDATE", user["username"], invoice_no)
    return {"ok": True}


@app.post("/api/invoices/{invoice_no}/close")
def close_invoice(
    invoice_no: str,
    request: Request,
    original_received: str = Form(...),
    notes: str = Form(""),
    external_receipt: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    user = require_role(request, ["ADMIN", "HR"])
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_no == invoice_no))
    if not invoice or invoice.status != "DOCUMENT_PENDING":
        raise HTTPException(status_code=400, detail="الفاتورة ليست عند الموارد.")
    if original_received != "نعم":
        raise HTTPException(status_code=400, detail="أصل الفاتورة لم يُستلم.")

    if invoice.is_external_driver:
        image = save_upload(external_receipt, invoice_no, "external_receipt")
        if not image:
            raise HTTPException(status_code=400, detail="صورة استلام السائق الخارجي مطلوبة.")
        invoice.receipt_photo = image

    invoice.original_document_received = True
    invoice.closure_notes = notes.strip() or None
    invoice.status, invoice.current_owner = "CLOSED", "ARCHIVE"
    invoice.closed_at = datetime.utcnow()
    invoice.updated_by = user["username"]
    db.commit()
    audit(db, "CLOSE_INVOICE", user["username"], invoice_no)
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
    user = require_role(request, ["ADMIN"])
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
    db: Session = Depends(get_db),
):
    admin = require_role(request, ["ADMIN"])
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
    active: str = Form("true"),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_role(request, ["ADMIN"])
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
    old_no = invoice.invoice_no
    invoice.invoice_no = new_invoice_no
    invoice.customer = customer.strip() or None
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
    vehicle_id: int = Form(...),
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
    vehicle = db.get(Vehicle, vehicle_id)
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
    return_qty_declared: float = Form(0),
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
    invoice.delivery_result = delivery_result
    invoice.delivery_reason = reason.strip() or None
    invoice.driver_notes = notes.strip() or None
    invoice.return_qty_declared = return_qty_declared
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

    invoice.invoice_no = new_invoice_no
    invoice.customer = customer.strip() or None
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
    require_role(request, ["ADMIN"])
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
