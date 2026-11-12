"""Role dashboard (DSH; Phase 7).

The variant follows the user's roles (owner, manager, inventory, purchasing, cashier).
Every KPI states its definition and links to the report that explains it. Cost-based
KPIs are dropped for users without cost visibility. Figures use the same sales facts
as the reports, so a dashboard number always matches its report.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CashierSession,
    Category,
    Company,
    GoodsReceipt,
    InventoryAlert,
    InventoryBalance,
    PosTerminal,
    Product,
    PurchaseOrder,
    Sale,
    SalePayment,
    StockAdjustment,
    StockTransfer,
    Warehouse,
    WarehouseLocation,
)
from app.services import cash_sessions, reports, stock
from app.services.principal import Principal
from app.services.reports import Ctx, aggregate, payments_received, r2, sales_facts


def variant_for(codes: list[str]) -> str:
    if set(codes) & {"OWNER", "ACCT", "AUDITOR"}:
        return "OWNER"
    if set(codes) & {"STOREMGR", "BRMGR"}:
        return "MANAGER"
    if set(codes) & {"INVMGR", "WHSTAFF"}:
        return "INVENTORY"
    if "PUROFF" in codes:
        return "PURCHASING"
    if set(codes) & {"CASHIER", "SALES"}:
        return "CASHIER"
    return "BASIC"


async def _period(ctx: Ctx, frm: date, to: date) -> dict:
    facts, sales, returns = await sales_facts(ctx, date_from=frm, date_to=to, override_range=True)
    gross = sum((f.gross for f in facts), Decimal(0))
    discounts = sum((f.discount for f in facts), Decimal(0))
    ret = sum((f.returns for f in facts), Decimal(0))
    net = gross - discounts - ret
    cogs = sum((f.cogs for f in facts), Decimal(0))
    return {"facts": facts, "sales": sales, "returns": returns, "gross": gross, "discounts": discounts, "returns_value": ret, "net": net, "cogs": cogs, "gp": net - cogs,
            "margin": (net - cogs) / net * 100 if net else Decimal(0), "transactions": len(sales)}


def _kpi(key: str, label: str, value: Any, fmt: str, definition: str, href: str, previous: Any = None, needs_cost: bool = False) -> dict:
    return {"key": key, "label": label, "value": r2(value), "format": fmt, "definition": definition, "href": href, "previous": None if previous is None else r2(previous), "needs_cost": needs_cost}


async def build(db: AsyncSession, actor: Principal, params: dict[str, Any]) -> dict:
    actor.require("dashboard.dashboard.view")
    today = datetime.now(UTC).date()
    frm = reports._d(params.get("dateFrom")) or today
    to = reports._d(params.get("dateTo")) or today
    ctx = Ctx(db, actor, {k: v for k, v in params.items() if k in ("branchId",)})
    branches = ctx.branches()
    sees_cost = actor.sees_cost
    variant = variant_for(actor.role_codes)
    current = await _period(ctx, frm, to)
    span = (to - frm).days
    prev_to = frm - timedelta(days=1)
    previous = await _period(ctx, prev_to - timedelta(days=span), prev_to)

    warehouses = stock.visible_warehouses(actor)
    if branches is not None:
        warehouses = select(Warehouse.id).where(Warehouse.id.in_(stock.visible_warehouses(actor)), Warehouse.branch_id.in_(branches))
    loc_ids = select(WarehouseLocation.id).where(WarehouseLocation.warehouse_id.in_(warehouses), WarehouseLocation.location_type != "IN_TRANSIT")
    inventory_value = Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand * Product.avg_cost), 0)).join(Product, Product.id == InventoryBalance.product_id)
                                              .where(InventoryBalance.location_id.in_(loc_ids))) or 0)
    alerts_q = select(InventoryAlert).where(InventoryAlert.company_id == actor.company_id, InventoryAlert.status.in_(("OPEN", "ACKNOWLEDGED")),
                                            InventoryAlert.warehouse_id.in_(warehouses) | InventoryAlert.warehouse_id.is_(None)).order_by(InventoryAlert.created_at.desc())
    open_alerts = list(await db.scalars(alerts_q))
    low = sum(1 for a in open_alerts if a.type == "LOW_STOCK")
    out = sum(1 for a in open_alerts if a.type == "OUT_OF_STOCK")
    expiring = sum(1 for a in open_alerts if a.type == "EXPIRING")
    start = datetime.combine(frm, datetime.min.time(), UTC)
    end = datetime.combine(to + timedelta(days=1), datetime.min.time(), UTC)
    purchase_value = Decimal(await db.scalar(select(func.coalesce(func.sum(GoodsReceipt.total_cost), 0)).where(
        GoodsReceipt.company_id == actor.company_id, GoodsReceipt.status == "POSTED", GoodsReceipt.warehouse_id.in_(warehouses), GoodsReceipt.posted_at >= start, GoodsReceipt.posted_at < end)) or 0)
    pays, refunds = await payments_received(ctx, current["sales"], current["returns"])
    received = sum((p.amount_applied for p in pays), Decimal(0)) - sum((r.amount_applied for r in refunds), Decimal(0))
    sale_scope = [Sale.company_id == actor.company_id] + ([Sale.branch_id.in_(branches)] if branches is not None else [])
    voids = await db.scalar(select(func.count()).select_from(Sale).where(*sale_scope, Sale.status == "VOIDED", Sale.voided_at >= start, Sale.voided_at < end)) or 0
    session_scope = [CashierSession.company_id == actor.company_id] + ([CashierSession.branch_id.in_(branches)] if branches is not None else [])
    variances = await db.scalar(select(func.count()).select_from(CashierSession).where(*session_scope, CashierSession.closed_at >= start, CashierSession.closed_at < end,
                                                                                         (CashierSession.variance_usd != 0) | (CashierSession.variance_khr != 0))) or 0
    transit = await stock.in_transit_location(db, actor.company_id)
    in_transit = Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(InventoryBalance.location_id == transit.id)) or 0)

    approvals: list[dict] = []
    if actor.can("purchasing.order.approve"):
        approvals += [{"id": str(p.id), "kind": "Purchase order", "label": f"{p.po_no} · {p.total:.2f} USD", "href": "/purchases"}
                      for p in await db.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == actor.company_id, PurchaseOrder.status == "PENDING_APPROVAL",
                                                                           PurchaseOrder.warehouse_id.in_(warehouses), PurchaseOrder.created_by != actor.user_id))]
    if actor.can("inventory.adjustment.approve"):
        approvals += [{"id": str(a.id), "kind": "Adjustment", "label": a.adjustment_no, "href": "/inventory/adjustments"}
                      for a in await db.scalars(select(StockAdjustment).where(StockAdjustment.company_id == actor.company_id, StockAdjustment.status == "SUBMITTED",
                                                                             StockAdjustment.warehouse_id.in_(warehouses), StockAdjustment.created_by != actor.user_id))]
        approvals += [{"id": str(g.id), "kind": "Goods receipt", "label": g.receipt_no, "href": "/purchases/receiving"}
                      for g in await db.scalars(select(GoodsReceipt).where(GoodsReceipt.company_id == actor.company_id, GoodsReceipt.status == "PENDING_APPROVAL", GoodsReceipt.warehouse_id.in_(warehouses)))]
    if actor.can("inventory.transfer.approve"):
        approvals += [{"id": str(t.id), "kind": "Transfer", "label": t.transfer_no, "href": "/inventory/transfers"}
                      for t in await db.scalars(select(StockTransfer).where(StockTransfer.company_id == actor.company_id, StockTransfer.status == "REQUESTED", StockTransfer.source_warehouse_id.in_(warehouses)))]
    if actor.can("cash.session.approve"):
        approvals += [{"id": str(s.id), "kind": "Session variance", "label": s.session_no, "href": "/cashier-sessions"}
                      for s in await db.scalars(select(CashierSession).where(*session_scope, CashierSession.status == "CLOSING", CashierSession.cashier_id != actor.user_id))]

    rng = f"dateFrom={frm.isoformat()}&dateTo={to.isoformat()}"
    sales_ref = f"/reports/RPT-01?{rng}"
    if variant == "MANAGER":
        kpis = [
            _kpi("net", "Daily sales", current["net"], "money", "Net sales for the selected period.", sales_ref, previous["net"]),
            _kpi("tx", "Transactions", current["transactions"], "number", "Count of finalized sales.", "/sales", previous["transactions"]),
            _kpi("refunds", "Refunds", current["returns_value"], "money", "Net value of returned lines by return date.", f"/reports/RPT-10?{rng}", previous["returns_value"]),
            _kpi("voids", "Voided sales", voids, "number", "Count of sales voided in the period.", f"/reports/RPT-11?{rng}"),
            _kpi("disc", "Discounts", current["discounts"], "money", "Line and order discounts on finalized sales.", f"/reports/RPT-09?{rng}", previous["discounts"]),
            _kpi("variance", "Session discrepancies", variances, "number", "Sessions closed in the period with a cash variance.", "/cashier-sessions"),
            _kpi("alerts", "Stock alerts", len(open_alerts), "number", "Open inventory alerts.", "/inventory/alerts"),
            _kpi("appr", "Pending approvals", len(approvals), "number", "Requests waiting for you.", "/dashboard"),
        ]
    elif variant == "INVENTORY":
        skus = await db.scalar(select(func.count(func.distinct(InventoryBalance.product_id))).where(InventoryBalance.location_id.in_(loc_ids), InventoryBalance.on_hand != 0)) or 0
        kpis = [
            _kpi("skus", "Products in stock", skus, "number", "Products with a non-zero balance in scope.", "/inventory"),
            _kpi("invValue", "Stock value", inventory_value, "money", "On hand × average cost.", "/reports/RPT-15", needs_cost=True),
            _kpi("low", "Low stock", low, "number", "Open low-stock alerts.", "/inventory/alerts"),
            _kpi("out", "Out of stock", out, "number", "Open out-of-stock alerts.", "/inventory/alerts"),
            _kpi("exp", "Expiring soon", expiring, "number", "Batches expiring within the warning window.", "/inventory/expiring"),
            _kpi("transit", "Units in transit", in_transit, "number", "Units dispatched and not yet received.", "/inventory/transfers"),
        ]
    elif variant == "PURCHASING":
        open_pos = list(await db.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == actor.company_id, PurchaseOrder.status.in_(("APPROVED", "SENT", "PARTIALLY_RECEIVED")),
                                                                     PurchaseOrder.warehouse_id.in_(warehouses))))
        pending = await db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.company_id == actor.company_id, PurchaseOrder.status == "PENDING_APPROVAL")) or 0
        kpis = [
            _kpi("open", "Open purchase orders", len(open_pos), "number", "Approved, sent or partially received orders.", "/purchases"),
            _kpi("openValue", "Open PO value", sum((p.total for p in open_pos), Decimal(0)), "money", "Total value of open purchase orders.", "/purchases", needs_cost=True),
            _kpi("purchases", "Goods received", purchase_value, "money", "Value of receipts posted in the period.", "/purchases/receiving", needs_cost=True),
            _kpi("low", "Reorder alerts", low, "number", "Open low-stock alerts.", "/inventory/alerts"),
            _kpi("appr", "Awaiting approval", pending, "number", "Purchase orders waiting for approval.", "/purchases"),
        ]
    elif variant == "CASHIER":
        kpis = []
    else:
        kpis = [
            _kpi("gross", "Total sales", current["gross"], "money", "Line amounts before discounts, excluding tax, on finalized sales.", sales_ref, previous["gross"]),
            _kpi("net", "Net sales", current["net"], "money", "Gross sales − discounts − returns, excluding tax.", sales_ref, previous["net"]),
            _kpi("gp", "Gross profit", current["gp"], "money", "Net sales − COGS at the cost stored on each sale line.", f"/reports/RPT-13?{rng}", previous["gp"], True),
            _kpi("margin", "Gross margin", current["margin"], "percent", "Gross profit ÷ net sales × 100.", f"/reports/RPT-13?{rng}", previous["margin"], True),
            _kpi("purchases", "Total purchases", purchase_value, "money", "Value of goods receipts posted in the period.", f"/reports/RPT-28?{rng}", None, True),
            _kpi("received", "Payments received", received, "money", "Completed payments less refunds. Cash received, not revenue.", f"/reports/RPT-08?{rng}"),
            _kpi("invValue", "Inventory value", inventory_value, "money", "On hand × average cost, now.", "/reports/RPT-15", None, True),
            _kpi("low", "Low-stock products", low, "number", "Open low-stock alerts.", "/inventory/alerts"),
            _kpi("out", "Out of stock", out, "number", "Open out-of-stock alerts.", "/inventory/alerts"),
        ]
    kpis = [k for k in kpis if not k["needs_cost"] or sees_cost]

    facts, sales = current["facts"], current["sales"]
    tx_by_date, tx_by_branch, tx_by_cashier, tx_by_terminal = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    for s in sales:
        tx_by_date[s.business_date.isoformat()] += 1
        tx_by_branch[s.branch_id] += 1
        tx_by_cashier[s.cashier_id] += 1
        tx_by_terminal[s.terminal_id] += 1
    gp = (lambda r: {"gross_profit": r["grossProfit"]}) if sees_cost else (lambda r: {})
    trend = [{"date": r["date"], "net_sales": r["netSales"], "transactions": tx_by_date.get(r["date"], 0), **gp(r)}
             for r in sorted(aggregate(facts, lambda f: f.date.isoformat(), lambda f: {"date": f.date.isoformat()}), key=lambda r: r["date"])]
    cats = {c.id: c.name_en for c in await db.scalars(select(Category).where(Category.company_id == actor.company_id))}
    by_category = [{"name": cats.get(r["cid"], "Uncategorised"), "net_sales": r["netSales"]} for r in sorted(aggregate(facts, lambda f: f.category_id, lambda f: {"cid": f.category_id}), key=lambda r: -r["netSales"])]
    method_totals: dict[str, Decimal] = defaultdict(Decimal)
    for p in pays:
        method_totals[p.method] += p.amount_applied
    by_payment = sorted(({"name": m.replace("_", " "), "amount": r2(v)} for m, v in method_totals.items()), key=lambda r: -r["amount"])
    branch_comparison = [{"name": r["name"], "net_sales": r["netSales"], "transactions": tx_by_branch.get(r["id"], 0), **gp(r)}
                         for r in sorted(aggregate(facts, lambda f: f.branch_id, lambda f: {"name": f.branch, "id": f.branch_id}), key=lambda r: -r["netSales"])]
    top = sorted(aggregate(facts, lambda f: f.product_id, lambda f: {"pid": f.product_id, "sku": f.sku, "name": f.name}), key=lambda r: -r["netSales"])[:8]
    top_products = [{"rank": i + 1, "product_id": str(r["pid"]), "sku": r["sku"], "name": r["name"], "quantity": r["qty"], "net_sales": r["netSales"], **gp(r)} for i, r in enumerate(top)]
    company = await db.get(Company, actor.company_id)
    slow_days = int((company.settings or {}).get("slow_moving_days", 60)) if company else 60
    sold_facts, _, _ = await sales_facts(ctx, date_from=today - timedelta(days=slow_days), date_to=today, override_range=True)
    sold: dict = defaultdict(Decimal)
    for f in sold_facts:
        sold[f.product_id] += f.qty
    on_hand_rows = await db.execute(select(Product.id, Product.sku, Product.name_en, func.sum(InventoryBalance.on_hand)).join(InventoryBalance, InventoryBalance.product_id == Product.id)
                                    .where(InventoryBalance.location_id.in_(loc_ids), Product.status == "ACTIVE").group_by(Product.id, Product.sku, Product.name_en))
    slow_products = sorted(({"product_id": str(pid), "sku": sku, "name": name, "on_hand": r2(qty, 3), "sold_qty": r2(sold.get(pid, 0), 3)} for pid, sku, name, qty in on_hand_rows if qty and qty > 0),
                           key=lambda r: (r["sold_qty"], -r["on_hand"]))[:8]
    by_cashier = [{"name": r["name"], "net_sales": r["netSales"], "transactions": tx_by_cashier.get(r["id"], 0)}
                  for r in sorted(aggregate(facts, lambda f: f.cashier_id, lambda f: {"name": f.cashier, "id": f.cashier_id}), key=lambda r: -r["netSales"])]
    by_terminal = [{"name": r["name"], "net_sales": r["netSales"], "transactions": tx_by_terminal.get(r["id"], 0)}
                   for r in sorted(aggregate(facts, lambda f: f.terminal_id, lambda f: {"name": f.terminal, "id": f.terminal_id}), key=lambda r: -r["netSales"])]
    recent_q = select(Sale).where(*sale_scope, Sale.status == "FINALIZED").order_by(Sale.finalized_at.desc()).limit(8)
    if not actor.can("sales.sale.view_all"):
        recent_q = recent_q.where(Sale.cashier_id == actor.user_id)
    recent = [{"id": str(s.id), "receipt_no": s.receipt_no or "", "at": s.finalized_at, "customer": s.customer_name or "Walk-in", "total": r2(s.grand_total), "status": s.status,
               "payment_status": s.payment_status} for s in await db.scalars(recent_q)]
    products = {p.id: p.name_en for p in await db.scalars(select(Product).where(Product.id.in_([a.product_id for a in open_alerts[:6]])))} if open_alerts else {}

    async def summary(label: str, days: int) -> dict:
        p = await _period(ctx, today - timedelta(days=days - 1), today)
        return {"label": label, "net_sales": r2(p["net"]), "transactions": p["transactions"], **({"gross_profit": r2(p["gp"])} if sees_cost else {})}

    cashier = None
    if variant == "CASHIER":
        session = await db.scalar(select(CashierSession).where(CashierSession.cashier_id == actor.user_id, CashierSession.status.in_(("OPEN", "CLOSING"))))
        if session is not None:
            flows = await cash_sessions.cash_flows(db, session.id)
            count = await db.scalar(select(func.count()).select_from(Sale).where(Sale.session_id == session.id, Sale.status == "FINALIZED")) or 0
            pending = await db.scalar(select(func.count()).select_from(SalePayment).where(SalePayment.session_id == session.id, SalePayment.status == "PENDING")) or 0
            terminal = await db.get(PosTerminal, session.terminal_id)
            cashier = {"shift": session.opened_at.strftime("%H:%M"), "terminal": terminal.name if terminal else "", "status": session.status, "sales_completed": count,
                       "cash_received": r2(flows["cash_sales"]["USD"]), "pending": pending, "session_id": str(session.id)}
        else:
            cashier = {"shift": "No open shift", "terminal": "", "status": "CLOSED", "sales_completed": 0, "cash_received": 0.0, "pending": 0, "session_id": None}

    return {
        "variant": variant, "kpis": kpis, "trend": trend, "by_category": by_category, "by_payment": by_payment, "branch_comparison": branch_comparison, "top_products": top_products,
        "slow_products": slow_products, "by_cashier": by_cashier, "by_terminal": by_terminal, "recent_transactions": recent,
        "alerts": [{"id": str(a.id), "type": a.type, "message": a.message, "product_name": products.get(a.product_id, "")} for a in open_alerts[:6]], "approvals": approvals,
        "summaries": [await summary("Today", 1), await summary("Last 7 days", 7), await summary("Last 30 days", 30)], "cashier": cashier,
    }
