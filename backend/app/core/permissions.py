"""Permission catalogue and default roles.

Permission codes follow SRS 4.2: `<module>.<resource>.<action>`. The default
role matrix is the SRS 4.3 and 14.2 proposal, pending approval (D-12). Limits
are proposed values the business can change per role.
"""

from dataclasses import dataclass, field

PERMISSIONS: dict[str, str] = {
    "dashboard.dashboard.view": "View dashboards",
    "reports.consolidated.view": "View consolidated data across permitted branches",
    "pos.sale.create": "Sell on the POS and take payment",
    "pos.sale.hold": "Build and hold sales",
    "pos.discount.apply": "Apply discounts within limit",
    "pos.price.override": "Override prices within limit",
    "pos.sale.cancel": "Cancel sales with items",
    "sales.sale.view": "View sales (own terminal unless view_all)",
    "sales.sale.view_all": "View all sales in scope",
    "sales.sale.void": "Void finalized sales in the same session",
    "sales.return.create": "Initiate returns and exchanges",
    "sales.return.approve": "Approve refunds within limit",
    "sales.refund.process": "Process and confirm refunds",
    "payments.payment.view": "View payments",
    "payments.payment.reconcile": "Reconcile payments",
    "products.product.view": "View products",
    "products.product.create": "Create products",
    "products.product.edit": "Edit products",
    "products.product.delete": "Delete draft products",
    "products.category.manage": "Manage categories, brands and units",
    "pricing.price.view": "View prices",
    "pricing.price.edit": "Change prices",
    "inventory.cost.view": "View costs, margins and stock value",
    "inventory.stock.view": "View stock",
    "inventory.adjustment.create": "Request adjustments",
    "inventory.adjustment.approve": "Approve and post adjustments",
    "inventory.transfer.create": "Request, dispatch and receive transfers",
    "inventory.transfer.approve": "Approve and close transfers",
    "inventory.count.create": "Run stock counts",
    "inventory.count.approve": "Approve and post stock counts",
    "inventory.movement.reverse": "Reverse posted movements",
    "inventory.alert.view": "View inventory alerts",
    "inventory.alert.manage": "Acknowledge and resolve alerts",
    "purchasing.order.view": "View purchase orders",
    "purchasing.order.create": "Create purchase orders",
    "purchasing.order.approve": "Approve purchase orders",
    "purchasing.receipt.create": "Create goods receipts",
    "purchasing.receipt.post": "Post goods receipts",
    "purchasing.receipt.exception": "Receive without a purchase order",
    "purchasing.supplier.view": "View suppliers",
    "purchasing.supplier.manage": "Manage suppliers",
    "purchasing.invoice.manage": "Record supplier invoices and payments",
    "purchasing.return.manage": "Manage purchase returns",
    "customers.customer.view": "View customers",
    "customers.customer.manage": "Manage customers",
    "customers.personal_data.view": "See unmasked personal data and anonymise",
    "promotions.promotion.view": "View promotions",
    "promotions.promotion.manage": "Manage promotions",
    "cash.session.open": "Open own cashier session",
    "cash.session.close": "Close own cashier session",
    "cash.session.approve": "Approve variances and force close sessions",
    "cash.session.view": "View own sessions",
    "cash.session.view_all": "View all sessions in scope",
    "reports.sales.view": "Sales reports",
    "reports.tax.view": "Tax reports",
    "reports.profit.view": "Profit reports",
    "reports.inventory.view": "Inventory reports",
    "reports.purchasing.view": "Purchasing reports",
    "reports.cash.view": "Cash and payment reports",
    "reports.business.view": "Business performance reports",
    "reports.exceptions.view": "Control exception report",
    "reports.data.export": "Export reports",
    "expenses.expense.view": "View expenses",
    "expenses.expense.create": "Record expenses",
    "expenses.expense.approve": "Approve expenses",
    "users.user.view": "View users",
    "users.user.manage": "Manage users",
    "users.role.view": "View roles",
    "users.role.manage": "Manage roles and permissions",
    "audit.log.view": "View audit logs",
    "settings.settings.view": "View settings",
    "settings.settings.manage": "Change settings",
    "imports.import.manage": "Import data",
}

# Short keys used by the current Next.js frontend, mapped to SRS codes.
FRONTEND_KEY_MAP: dict[str, str] = {
    "dashboard.view": "dashboard.dashboard.view", "reports.consolidated": "reports.consolidated.view",
    "pos.sell": "pos.sale.create", "pos.hold": "pos.sale.hold", "pos.discount": "pos.discount.apply", "pos.override": "pos.price.override", "pos.cancel": "pos.sale.cancel",
    "sales.view": "sales.sale.view", "sales.view_all": "sales.sale.view_all", "sales.void": "sales.sale.void",
    "returns.create": "sales.return.create", "returns.approve": "sales.return.approve",
    "products.view": "products.product.view", "products.create": "products.product.create", "products.edit": "products.product.edit", "products.delete": "products.product.delete",
    "pricing.view": "pricing.price.view", "pricing.edit": "pricing.price.edit", "costs.view": "inventory.cost.view",
    "inventory.view": "inventory.stock.view", "inventory.adjust": "inventory.adjustment.create", "inventory.adjust.approve": "inventory.adjustment.approve",
    "inventory.transfer": "inventory.transfer.create", "inventory.transfer.approve": "inventory.transfer.approve",
    "inventory.count": "inventory.count.create", "inventory.count.approve": "inventory.count.approve", "inventory.reverse": "inventory.movement.reverse",
    "purchasing.view": "purchasing.order.view", "purchasing.create": "purchasing.order.create", "purchasing.approve": "purchasing.order.approve",
    "receiving.create": "purchasing.receipt.create", "receiving.post": "purchasing.receipt.post", "receiving.exception": "purchasing.receipt.exception",
    "suppliers.view": "purchasing.supplier.view", "suppliers.manage": "purchasing.supplier.manage",
    "customers.view": "customers.customer.view", "customers.manage": "customers.customer.manage", "customers.personal_data": "customers.personal_data.view",
    "promotions.view": "promotions.promotion.view", "promotions.manage": "promotions.promotion.manage",
    "cash.session.open": "cash.session.open", "cash.session.close": "cash.session.close", "cash.session.approve": "cash.session.approve",
    "cash.session.view": "cash.session.view", "cash.session.view_all": "cash.session.view_all",
    "reports.sales": "reports.sales.view", "reports.tax": "reports.tax.view", "reports.profit": "reports.profit.view", "reports.inventory": "reports.inventory.view",
    "reports.purchasing": "reports.purchasing.view", "reports.cash": "reports.cash.view", "reports.business": "reports.business.view",
    "reports.exceptions": "reports.exceptions.view", "reports.export": "reports.data.export",
    "expenses.view": "expenses.expense.view", "expenses.create": "expenses.expense.create", "expenses.approve": "expenses.expense.approve",
    "users.view": "users.user.view", "users.manage": "users.user.manage", "roles.manage": "users.role.manage", "audit.view": "audit.log.view",
    "settings.view": "settings.settings.view", "settings.manage": "settings.settings.manage", "imports.manage": "imports.import.manage",
    "alerts.view": "inventory.alert.view", "alerts.manage": "inventory.alert.manage",
}


@dataclass(frozen=True)
class RoleLimits:
    discount_pct: str = "0"
    override_amount: str = "0"
    refund_amount: str = "0"
    adjustment_value: str = "0"
    po_approval_limit: str = "0"


@dataclass(frozen=True)
class RoleDefinition:
    name: str
    description: str
    permissions: frozenset[str]
    limits: RoleLimits = field(default_factory=RoleLimits)


def _p(*codes: str) -> frozenset[str]:
    unknown = [c for c in codes if c not in PERMISSIONS]
    if unknown:
        raise ValueError(f"Unknown permissions: {unknown}")
    return frozenset(codes)


_ALL_REPORTS = ("reports.sales.view", "reports.tax.view", "reports.profit.view", "reports.inventory.view", "reports.purchasing.view", "reports.cash.view", "reports.business.view", "reports.data.export")
_CATALOG_VIEW = ("products.product.view", "pricing.price.view")
_UNLIMITED = RoleLimits("100", "1000000", "1000000", "1000000", "1000000")

DEFAULT_ROLES: dict[str, RoleDefinition] = {
    "SYSADMIN": RoleDefinition(
        "System Administrator", "Users, roles, terminals, devices and settings. No sales, approvals or inventory posting.",
        _p("dashboard.dashboard.view", "products.product.view", "users.user.view", "users.user.manage", "users.role.view", "users.role.manage",
           "audit.log.view", "settings.settings.view", "settings.settings.manage", "imports.import.manage", "inventory.alert.view", "reports.data.export"),
    ),
    "OWNER": RoleDefinition(
        "Business Owner", "All branches, approvals above managers' limits, costs and profits.",
        frozenset(code for code in PERMISSIONS if code != "users.role.manage"), _UNLIMITED,
    ),
    "STOREMGR": RoleDefinition(
        "Store Manager", "Operations of assigned stores; pricing; approvals within limit.",
        _p("dashboard.dashboard.view", "pos.sale.create", "pos.sale.hold", "pos.discount.apply", "pos.price.override", "pos.sale.cancel",
           "sales.sale.view", "sales.sale.view_all", "sales.sale.void", "sales.return.create", "sales.return.approve", "sales.refund.process",
           "payments.payment.view", "payments.payment.reconcile",
           "products.product.view", "products.product.create", "products.product.edit", "products.product.delete", "products.category.manage",
           "pricing.price.view", "pricing.price.edit", "inventory.cost.view", "inventory.stock.view",
           "inventory.adjustment.create", "inventory.adjustment.approve", "inventory.transfer.create", "inventory.transfer.approve",
           "inventory.count.create", "inventory.count.approve", "inventory.movement.reverse",
           "purchasing.order.view", "purchasing.order.create", "purchasing.order.approve", "purchasing.receipt.create", "purchasing.receipt.post",
           "purchasing.receipt.exception", "purchasing.supplier.view", "purchasing.supplier.manage", "purchasing.invoice.manage", "purchasing.return.manage",
           "customers.customer.view", "customers.customer.manage", "customers.personal_data.view", "promotions.promotion.view", "promotions.promotion.manage",
           "cash.session.open", "cash.session.close", "cash.session.approve", "cash.session.view", "cash.session.view_all",
           *_ALL_REPORTS, "reports.exceptions.view", "reports.consolidated.view", "expenses.expense.view", "expenses.expense.create",
           "settings.settings.view", "imports.import.manage", "inventory.alert.view", "inventory.alert.manage"),
        RoleLimits("30", "100", "500", "500", "5000"),
    ),
    "BRMGR": RoleDefinition(
        "Branch Manager", "Branch operations, session reviews, refunds and adjustments within limit.",
        _p("dashboard.dashboard.view", "pos.sale.create", "pos.sale.hold", "pos.discount.apply", "pos.price.override", "pos.sale.cancel",
           "sales.sale.view", "sales.sale.view_all", "sales.sale.void", "sales.return.create", "sales.return.approve", "sales.refund.process",
           "payments.payment.view", *_CATALOG_VIEW, "products.product.edit", "inventory.cost.view", "inventory.stock.view",
           "inventory.adjustment.create", "inventory.transfer.create", "inventory.count.create",
           "purchasing.order.view", "purchasing.receipt.create", "purchasing.receipt.post", "purchasing.supplier.view",
           "customers.customer.view", "customers.customer.manage", "customers.personal_data.view", "promotions.promotion.view",
           "cash.session.open", "cash.session.close", "cash.session.approve", "cash.session.view", "cash.session.view_all",
           "reports.sales.view", "reports.inventory.view", "reports.cash.view", "reports.data.export",
           "expenses.expense.view", "expenses.expense.create", "inventory.alert.view", "inventory.alert.manage"),
        RoleLimits("20", "50", "200", "100", "0"),
    ),
    "INVMGR": RoleDefinition(
        "Inventory Manager", "Stock, adjustments, transfers, stocktakes and alerts. No sales.",
        _p("dashboard.dashboard.view", *_CATALOG_VIEW, "products.product.create", "products.product.edit", "products.category.manage",
           "inventory.cost.view", "inventory.stock.view", "inventory.adjustment.create", "inventory.adjustment.approve",
           "inventory.transfer.create", "inventory.transfer.approve", "inventory.count.create", "inventory.count.approve", "inventory.movement.reverse",
           "purchasing.order.view", "purchasing.receipt.create", "purchasing.receipt.post", "purchasing.receipt.exception", "purchasing.supplier.view",
           "reports.inventory.view", "reports.data.export", "settings.settings.view", "imports.import.manage", "inventory.alert.view", "inventory.alert.manage"),
        RoleLimits(adjustment_value="300"),
    ),
    "PUROFF": RoleDefinition(
        "Purchasing Officer", "Suppliers, purchase orders, supplier invoices and purchase returns.",
        _p("dashboard.dashboard.view", *_CATALOG_VIEW, "products.product.create", "products.product.edit", "inventory.cost.view", "inventory.stock.view",
           "purchasing.order.view", "purchasing.order.create", "purchasing.supplier.view", "purchasing.supplier.manage",
           "purchasing.invoice.manage", "purchasing.return.manage", "reports.purchasing.view", "reports.data.export", "imports.import.manage", "inventory.alert.view"),
    ),
    "CASHIER": RoleDefinition(
        "Cashier", "Sales, payments, receipts, own session and initiating returns.",
        _p("dashboard.dashboard.view", "pos.sale.create", "pos.sale.hold", "pos.discount.apply", "sales.sale.view", "sales.return.create",
           *_CATALOG_VIEW, "inventory.stock.view", "customers.customer.view", "customers.customer.manage",
           "cash.session.open", "cash.session.close", "cash.session.view", "reports.cash.view"),
        RoleLimits(discount_pct="5", refund_amount="20"),
    ),
    "SALES": RoleDefinition(
        "Salesperson", "Create and hold sales, look up stock and prices, customers.",
        _p("dashboard.dashboard.view", "pos.sale.hold", "sales.sale.view", *_CATALOG_VIEW, "inventory.stock.view", "customers.customer.view", "customers.customer.manage"),
    ),
    "WHSTAFF": RoleDefinition(
        "Warehouse Staff", "Receive goods, dispatch and receive transfers, count stock.",
        _p("dashboard.dashboard.view", *_CATALOG_VIEW, "inventory.stock.view", "inventory.adjustment.create", "inventory.transfer.create", "inventory.count.create",
           "purchasing.order.view", "purchasing.receipt.create", "purchasing.receipt.post", "inventory.alert.view"),
    ),
    "ACCT": RoleDefinition(
        "Accountant", "Costs, valuation, payment reconciliation, expenses and exports.",
        _p("dashboard.dashboard.view", "sales.sale.view", "sales.sale.view_all", "sales.refund.process", "payments.payment.view", "payments.payment.reconcile",
           *_CATALOG_VIEW, "inventory.cost.view", "inventory.stock.view", "purchasing.order.view", "purchasing.supplier.view", "purchasing.invoice.manage",
           "customers.customer.view", "promotions.promotion.view", "cash.session.view", "cash.session.view_all", "cash.session.approve",
           *_ALL_REPORTS, "reports.consolidated.view", "expenses.expense.view", "expenses.expense.create", "expenses.expense.approve", "settings.settings.view"),
    ),
    "AUDITOR": RoleDefinition(
        "Auditor", "Read-only access including audit logs.",
        _p("dashboard.dashboard.view", "reports.consolidated.view", "sales.sale.view", "sales.sale.view_all", "payments.payment.view", *_CATALOG_VIEW,
           "inventory.cost.view", "inventory.stock.view", "purchasing.order.view", "purchasing.supplier.view", "customers.customer.view",
           "customers.personal_data.view", "promotions.promotion.view", "cash.session.view", "cash.session.view_all", *_ALL_REPORTS, "reports.exceptions.view",
           "expenses.expense.view", "users.user.view", "users.role.view", "audit.log.view", "settings.settings.view", "inventory.alert.view"),
    ),
    "READONLY": RoleDefinition(
        "Read-only User", "View permitted data. No changes and no costs.",
        _p("dashboard.dashboard.view", "sales.sale.view", *_CATALOG_VIEW, "inventory.stock.view", "reports.sales.view", "reports.inventory.view", "reports.data.export"),
    ),
}

# Separation-of-duties pairs flagged on role and user forms (SRS 4.4).
SOD_CONFLICTS: list[tuple[str, str, str]] = [
    ("purchasing.order.create", "purchasing.order.approve", "create PO and approve PO"),
    ("expenses.expense.create", "expenses.expense.approve", "record expense and approve expense"),
    ("inventory.adjustment.create", "inventory.adjustment.approve", "request adjustment and approve adjustment"),
]
