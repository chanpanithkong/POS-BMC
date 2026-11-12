"""Import every model so Alembic and the metadata see all tables."""

from app.models.audit_log import AuditLog
from app.models.branch import Branch, PosTerminal, TerminalCashier
from app.models.catalog import (
    Brand,
    Category,
    PriceChange,
    PriceList,
    Product,
    ProductBarcode,
    ProductBranchSetting,
    ProductPrice,
    ProductWarehouseSetting,
    Unit,
    UnitConversion,
)
from app.models.company import Company, Currency, DocumentSequence, ExchangeRate, TaxCode
from app.models.customers import Customer, CustomerGroup, StoreCreditEntry
from app.models.extras import (
    Coupon,
    Expense,
    ExpenseCategory,
    ImportBatch,
    ImportPreview,
    Notification,
    NotificationRead,
    Promotion,
)
from app.models.inventory import (
    InventoryAlert,
    InventoryBalance,
    InventoryBatch,
    InventoryMovement,
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
)
from app.models.platform import IdempotencyKey, OutboxEvent
from app.models.purchasing import (
    GoodsReceipt,
    GoodsReceiptLine,
    ProductSupplier,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)
from app.models.role import Permission, Role, RolePermission
from app.models.sales import (
    CashierSession,
    CashMovement,
    Refund,
    Sale,
    SaleLine,
    SalePayment,
    SalesReturn,
    SalesReturnLine,
    StockReservation,
)
from app.models.settings import PaymentMethod, ReceiptTemplate
from app.models.user import (
    Approval,
    Employee,
    LoginAttempt,
    PasswordResetToken,
    User,
    UserBranchAccess,
    UserRole,
    UserSession,
    UserWarehouseAccess,
)
from app.models.warehouse import LocationType, Warehouse, WarehouseLocation

__all__ = [
    "Coupon", "Expense", "ExpenseCategory", "ImportBatch", "ImportPreview", "Notification", "NotificationRead", "Promotion",
    "Customer", "CustomerGroup", "GoodsReceipt", "GoodsReceiptLine", "ProductSupplier", "PurchaseOrder", "PurchaseOrderLine", "PurchaseReturn", "PurchaseReturnLine",
    "StoreCreditEntry", "Supplier", "SupplierInvoice", "SupplierPayment",
    "CashMovement", "CashierSession", "Refund", "Sale", "SaleLine", "SalePayment", "SalesReturn", "SalesReturnLine", "StockReservation",
    "InventoryAlert", "InventoryBalance", "InventoryBatch", "InventoryMovement", "StockAdjustment", "StockAdjustmentLine", "StockCount", "StockCountLine",
    "StockTransfer", "StockTransferLine",
    "Brand", "Category", "PaymentMethod", "PriceChange", "PriceList", "Product", "ProductBarcode", "ProductBranchSetting", "ProductPrice",
    "ProductWarehouseSetting", "ReceiptTemplate", "Unit", "UnitConversion",
    "Approval", "AuditLog", "Branch", "Company", "Currency", "DocumentSequence", "Employee", "ExchangeRate", "IdempotencyKey",
    "LocationType", "LoginAttempt", "OutboxEvent", "PasswordResetToken", "Permission", "PosTerminal", "Role", "RolePermission",
    "TaxCode", "TerminalCashier", "User", "UserBranchAccess", "UserRole", "UserSession", "UserWarehouseAccess", "Warehouse",
    "WarehouseLocation",
]
