from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(40), index=True)
    driver_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sales_rep_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_external_driver: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    units_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvoiceIssueItem(Base):
    __tablename__ = "invoice_issue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(100), index=True)
    stage: Mapped[str] = mapped_column(String(40), index=True)  # WAREHOUSE / DRIVER
    issue_type: Mapped[str] = mapped_column(String(40), index=True)  # ناقص / مرتجع
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    product_name: Mapped[str] = mapped_column(String(180))
    unit: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[str] = mapped_column(String(80))
    warehouse_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    actual_quantity: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warehouse_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class SalesRep(Base):
    __tablename__ = "sales_reps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    plate_no: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    customer: Mapped[str | None] = mapped_column(String(180), nullable=True)
    sales_rep_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sales_rep_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    invoice_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    driver_code: Mapped[str] = mapped_column(String(80), default="", index=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    driver_name: Mapped[str] = mapped_column(String(150), default="")
    is_external_driver: Mapped[bool] = mapped_column(Boolean, default=False)
    vehicle_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivery_target: Mapped[str | None] = mapped_column(String(30), nullable=True)
    transport_office_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    carrier_receipt_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_receipt_required: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_receipt_received: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_receipt_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_receipt_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer_receipt_received_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_receipt_match: Mapped[str | None] = mapped_column(String(30), nullable=True)
    customer_receipt_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_discrepancy_required: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_discrepancy_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_discrepancy_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_discrepancy_reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivery_discrepancy_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(60), index=True, default="WAREHOUSE_PENDING")
    current_owner: Mapped[str] = mapped_column(String(60), index=True, default="WAREHOUSE")
    hr_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    warehouse_user: Mapped[str | None] = mapped_column(String(80), nullable=True)
    load_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warehouse_shortage_reason: Mapped[str | None] = mapped_column(String(180), nullable=True)
    warehouse_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warehouse_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    delivery_result: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_reason: Mapped[str | None] = mapped_column(String(180), nullable=True)
    receipt_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    driver_return_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    driver_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_qty_declared: Mapped[float] = mapped_column(Float, default=0)
    return_qty_text: Mapped[str | None] = mapped_column(String(180), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    return_received: Mapped[bool] = mapped_column(Boolean, default=False)
    return_qty_actual: Mapped[float] = mapped_column(Float, default=0)
    return_difference: Mapped[float] = mapped_column(Float, default=0)
    return_condition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    return_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sales_return_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_return_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_return_reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sales_return_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sales_return_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_document_received: Mapped[bool] = mapped_column(Boolean, default=False)
    original_document_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_document_received_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_document_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closure_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    invoice_no: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
