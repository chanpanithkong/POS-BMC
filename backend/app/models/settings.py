"""Payment method and receipt template configuration (ORG, Phase 3)."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, UUIDPk

PAYMENT_METHOD_CODES = ("CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT")


class PaymentMethod(UUIDPk, Authored, Base):
    __tablename__ = "payment_methods"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    # Card, QR and bank transfer are recorded by reference only (D-04).
    requires_reference: Mapped[bool] = mapped_column(default=False)
    provider: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint(f"code IN ({','.join(repr(c) for c in PAYMENT_METHOD_CODES)})", name="code"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class ReceiptTemplate(UUIDPk, Authored, Base):
    __tablename__ = "receipt_templates"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    name: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="BILINGUAL")
    paper_width: Mapped[str] = mapped_column(String(5), default="80mm")
    header: Mapped[str] = mapped_column(Text, default="")
    footer: Mapped[str] = mapped_column(Text, default="")
    show_logo: Mapped[bool] = mapped_column(default=True)
    show_tax_id: Mapped[bool] = mapped_column(default=True)
    show_qr: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        CheckConstraint("language IN ('EN','KM','BILINGUAL')", name="language"),
        CheckConstraint("paper_width IN ('58mm','80mm')", name="paper_width"),
    )
