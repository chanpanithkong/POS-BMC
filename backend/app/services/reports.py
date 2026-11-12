"""Reports RPT-01 to RPT-34 and the role dashboard (RPT, DSH; Phase 7).

Sales figures come from finalized sale lines by business date (voids excluded) and
return lines by return date, using the cost stored on each line at the time of sale
(BR-CST-003), so later cost changes never rewrite history. Net sales exclude tax.
Every report states its basis and, where a cross-check is possible, includes checks
(for example, daily net sales against payments received).

Reports are read-only queries scoped to the caller's branches and warehouses.
Reports that need cost are refused without inventory.cost.view, and cost columns are
dropped from mixed reports.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, literal_column, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound
from app.models import (
    AuditLog,
    Branch,
    CashierSession,
    CashMovement,
    Category,
    Company,
    Expense,
    GoodsReceipt,
    GoodsReceiptLine,
    InventoryBalance,
    InventoryBatch,
    InventoryMovement,
    PosTerminal,
    Product,
    ProductWarehouseSetting,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    Refund,
    Sale,
    SaleLine,
    SalePayment,
    SalesReturn,
    SalesReturnLine,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
    Supplier,
    Unit,
    User,
    Warehouse,
    WarehouseLocation,
)
from app.services import cash_sessions, stock
from app.services.principal import Principal

SALES_BASIS = "Finalized sales by business date; voids excluded; returns shown separately by return date. Net sales exclude tax. Currency: USD."
SF = ["dateRange", "branch"]


def r2(value: Any, places: int = 2) -> float:
    return round(float(value or 0), places)


def col(key: str, label: str, kind: str = "text") -> dict:
    return {"key": key, "label": label, "type": kind}


def money(key: str, label: str) -> dict:
    return col(key, label, "money")


def check(label: str, expected: Any, actual: Any, tolerance: float = 0.01) -> dict:
    e, a = r2(expected), r2(actual)
    return {"label": label, "expected": e, "actual": a, "passed": abs(e - a) <= tolerance}


def totals_of(rows: list[dict], keys: list[str], label_key: str) -> dict | None:
    if not rows:
        return None
    out: dict[str, Any] = {label_key: "Total"}
    for k in keys:
        out[k] = r2(sum(float(r.get(k) or 0) for r in rows), 4)
    return out


def bar(x: str, key: str, label: str) -> dict:
    return {"type": "bar", "x_key": x, "series": [{"key": key, "label": label}]}


@dataclass
class Ctx:
    db: AsyncSession
    actor: Principal
    params: dict[str, Any]
    today: date = field(default_factory=lambda: datetime.now(UTC).date())

    @property
    def date_from(self) -> date | None:
        return _d(self.params.get("dateFrom"))

    @property
    def date_to(self) -> date | None:
        return _d(self.params.get("dateTo"))

    def id_param(self, key: str) -> uuid.UUID | None:
        value = self.params.get(key)
        try:
            return uuid.UUID(str(value)) if value else None
        except ValueError:
            return None

    @property
    def sees_cost(self) -> bool:
        return self.actor.sees_cost

    def branches(self) -> list[uuid.UUID] | None:
        """Branch filter combined with the caller's scope; None means every branch."""
        chosen = self.id_param("branchId")
        if chosen:
            self.actor.assert_branch(chosen)
            return [chosen]
        return list(self.actor.branch_ids) if self.actor.branch_ids is not None else None

    def in_range(self, column):
        conds = []
        if self.date_from:
            conds.append(column >= self.date_from)
        if self.date_to:
            conds.append(column <= self.date_to)
        return and_(*conds) if conds else true()

    def datetime_range(self, column):
        conds = []
        if self.date_from:
            conds.append(column >= datetime.combine(self.date_from, datetime.min.time(), UTC))
        if self.date_to:
            conds.append(column < datetime.combine(self.date_to + timedelta(days=1), datetime.min.time(), UTC))
        return and_(*conds) if conds else true()


def _d(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# Facts

@dataclass
class Fact:
    date: date
    branch_id: uuid.UUID
    branch: str
    terminal_id: uuid.UUID
    terminal: str
    cashier_id: uuid.UUID
    cashier: str
    product_id: uuid.UUID
    sku: str
    name: str
    category_id: uuid.UUID | None
    qty: Decimal
    gross: Decimal
    discount: Decimal
    returns: Decimal
    tax: Decimal
    cogs: Decimal
    tax_code: str
    tax_rate: Decimal


async def sales_facts(ctx: Ctx, *, date_from: date | None = None, date_to: date | None = None, override_range: bool = False) -> tuple[list[Fact], list[Sale], list[SalesReturn]]:
    db = ctx.db
    frm, to = (date_from, date_to) if override_range else (ctx.date_from, ctx.date_to)
    branches = ctx.branches()
    sale_q = select(Sale).where(Sale.company_id == ctx.actor.company_id, Sale.status == "FINALIZED")
    if frm:
        sale_q = sale_q.where(Sale.business_date >= frm)
    if to:
        sale_q = sale_q.where(Sale.business_date <= to)
    if branches is not None:
        sale_q = sale_q.where(Sale.branch_id.in_(branches))
    for key, column in (("terminalId", Sale.terminal_id), ("cashierId", Sale.cashier_id)):
        if ctx.id_param(key):
            sale_q = sale_q.where(column == ctx.id_param(key))
    sales = list(await db.scalars(sale_q))
    names = await _names(db)
    category_filter = ctx.id_param("categoryId")
    facts: list[Fact] = []
    sale_ids = [s.id for s in sales]
    by_sale = {s.id: s for s in sales}
    products = names["products"]
    if sale_ids:
        for line in await db.scalars(select(SaleLine).where(SaleLine.sale_id.in_(sale_ids))):
            product = products.get(line.product_id)
            cat = product.category_id if product else None
            if category_filter and cat != category_filter:
                continue
            s = by_sale[line.sale_id]
            net_ex_tax = line.line_total - line.tax_amount
            discount = line.discount_amount + line.order_discount_share
            facts.append(Fact(s.business_date, s.branch_id, names["branches"].get(s.branch_id, ""), s.terminal_id, names["terminals"].get(s.terminal_id, ""), s.cashier_id,
                              names["users"].get(s.cashier_id, ""), line.product_id, line.sku, line.name_en, cat, line.quantity_base, net_ex_tax + discount, discount, Decimal(0),
                              line.tax_amount, line.cost_total or Decimal(0), line.tax_code, line.tax_rate))
    ret_q = select(SalesReturn, Sale).join(Sale, Sale.id == SalesReturn.original_sale_id).where(SalesReturn.company_id == ctx.actor.company_id)
    if frm:
        ret_q = ret_q.where(SalesReturn.business_date >= frm)
    if to:
        ret_q = ret_q.where(SalesReturn.business_date <= to)
    if branches is not None:
        ret_q = ret_q.where(SalesReturn.branch_id.in_(branches))
    for key, column in (("terminalId", Sale.terminal_id), ("cashierId", Sale.cashier_id)):
        if ctx.id_param(key):
            ret_q = ret_q.where(column == ctx.id_param(key))
    returns = []
    for ret, sale in await db.execute(ret_q):
        returns.append(ret)
        for rl, sl in await db.execute(select(SalesReturnLine, SaleLine).join(SaleLine, SaleLine.id == SalesReturnLine.sale_line_id).where(SalesReturnLine.return_id == ret.id)):
            product = products.get(rl.product_id)
            cat = product.category_id if product else None
            if category_filter and cat != category_filter:
                continue
            facts.append(Fact(ret.business_date, ret.branch_id, names["branches"].get(ret.branch_id, ""), sale.terminal_id, names["terminals"].get(sale.terminal_id, ""), sale.cashier_id,
                              names["users"].get(sale.cashier_id, ""), rl.product_id, rl.sku, rl.name, cat, -rl.quantity_base, Decimal(0), Decimal(0), rl.net_amount, -rl.tax_amount,
                              -((rl.unit_cost or Decimal(0)) * rl.quantity_base), sl.tax_code, sl.tax_rate))
    return facts, sales, returns


async def _names(db: AsyncSession) -> dict[str, dict]:
    return {
        "branches": {b.id: b.name_en for b in await db.scalars(select(Branch))},
        "terminals": {t.id: t.name for t in await db.scalars(select(PosTerminal))},
        "users": {u.id: u.full_name for u in await db.scalars(select(User))},
        "products": {pr.id: pr for pr in await db.scalars(select(Product))},
        "categories": {c.id: c.name_en for c in await db.scalars(select(Category))},
    }


def aggregate(facts: list[Fact], key: Callable[[Fact], Any], seed: Callable[[Fact], dict]) -> list[dict]:
    groups: dict[Any, dict] = {}
    for f in facts:
        k = key(f)
        row = groups.get(k)
        if row is None:
            row = groups[k] = {**seed(f), "gross": Decimal(0), "discount": Decimal(0), "returns": Decimal(0), "tax": Decimal(0), "cogs": Decimal(0), "qty": Decimal(0)}
        for attr in ("gross", "discount", "returns", "tax", "cogs", "qty"):
            row[attr] += getattr(f, attr)
    out = []
    for row in groups.values():
        net = row["gross"] - row["discount"] - row["returns"]
        gp = net - row["cogs"]
        out.append({**row, "netSales": r2(net), "gross": r2(row["gross"]), "discount": r2(row["discount"]), "returns": r2(row["returns"]), "tax": r2(row["tax"]),
                    "cogs": r2(row["cogs"]), "qty": r2(row["qty"], 3), "grossProfit": r2(gp), "margin": r2(gp / net * 100, 1) if net else 0.0})
    return out


def net_total(facts: list[Fact]) -> Decimal:
    return sum((f.gross - f.discount - f.returns for f in facts), Decimal(0))


SALES_METRIC_COLS = [col("qty", "Qty", "number"), money("netSales", "Net sales"), money("cogs", "COGS"), money("grossProfit", "Gross profit"), col("margin", "Margin %", "percent")]


async def gross_group(ctx: Ctx, key, seed, columns: list[dict], label_key: str, show_margin: bool = True) -> dict:
    facts, _, _ = await sales_facts(ctx)
    show_cost = ctx.sees_cost and show_margin
    rows = sorted(aggregate(facts, key, seed), key=lambda r: -r["netSales"])
    cols = columns + [c for c in SALES_METRIC_COLS if show_cost or c["key"] in ("qty", "netSales")]
    keys = [c["key"] for c in cols if c["type"] in ("money", "number")]
    rows = [{k: v for k, v in r.items() if k in {c["key"] for c in cols}} for r in rows]
    return {"columns": cols, "rows": rows, "totals": totals_of(rows, keys, label_key), "chart": bar(label_key, "netSales", "Net sales"),
            "checks": [check("Sum equals daily sales net", net_total(facts), sum(r["netSales"] for r in rows), 0.005 * len(rows) + 0.01)], "basis": SALES_BASIS}


async def payments_received(ctx: Ctx, sales: list[Sale], returns: list[SalesReturn]) -> tuple[list[SalePayment], list[Refund]]:
    payments = list(await ctx.db.scalars(select(SalePayment).where(SalePayment.sale_id.in_([s.id for s in sales]), SalePayment.status.in_(("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED"))))) if sales else []
    refunds = list(await ctx.db.scalars(select(Refund).where(Refund.return_id.in_([r.id for r in returns]), Refund.status == "COMPLETED"))) if returns else []
    return payments, refunds


# Report implementations

async def rpt01(ctx: Ctx) -> dict:
    facts, sales, returns = await sales_facts(ctx)
    tx = defaultdict(int)
    for s in sales:
        tx[(s.business_date, s.branch_id)] += 1
    rows = []
    for r in aggregate(facts, lambda f: (f.date, f.branch_id), lambda f: {"date": f.date.isoformat(), "branch": f.branch, "_k": (f.date, f.branch_id)}):
        n = tx.get(r["_k"], 0)
        rows.append({k: r[k] for k in ("date", "branch", "gross", "discount", "returns", "netSales", "tax")} | {"transactions": n, "basket": r2((r["gross"] - r["discount"]) / n) if n else 0.0})
    rows.sort(key=lambda r: r["date"], reverse=True)
    payments, refunds = await payments_received(ctx, sales, returns)
    paid = sum((p.amount_applied for p in payments), Decimal(0)) - sum((x.amount_applied for x in refunds), Decimal(0))
    return {
        "columns": [col("date", "Business date", "date"), col("branch", "Branch"), money("gross", "Gross"), money("discount", "Discounts"), money("returns", "Returns"), money("netSales", "Net sales"),
                    money("tax", "Tax"), col("transactions", "Transactions", "number"), money("basket", "Avg basket")],
        "rows": rows, "totals": totals_of(rows, ["gross", "discount", "returns", "netSales", "tax", "transactions"], "date"), "basis": SALES_BASIS,
        "chart": {"type": "line", "x_key": "date", "series": [{"key": "netSales", "label": "Net sales"}]},
        "checks": [check("Net sales + tax = payments received − refunds", sum((f.gross - f.discount - f.returns + f.tax for f in facts), Decimal(0)), paid, 0.05)],
    }


async def rpt02(ctx: Ctx) -> dict:
    facts, sales, _ = await sales_facts(ctx)
    tx = defaultdict(int)
    for s in sales:
        tx[s.business_date.strftime("%Y-%m")] += 1
    rows = [{"month": r["month"], "netSales": r["netSales"], **({"grossProfit": r["grossProfit"]} if ctx.sees_cost else {}), "transactions": tx.get(r["month"], 0)}
            for r in aggregate(facts, lambda f: f.date.strftime("%Y-%m"), lambda f: {"month": f.date.strftime("%Y-%m")})]
    rows.sort(key=lambda r: r["month"], reverse=True)
    return {"columns": [col("month", "Month"), money("netSales", "Net sales"), *([money("grossProfit", "Gross profit")] if ctx.sees_cost else []), col("transactions", "Transactions", "number")],
            "rows": rows, "totals": totals_of(rows, ["netSales", "transactions", *(["grossProfit"] if ctx.sees_cost else [])], "month"), "chart": bar("month", "netSales", "Net sales"),
            "basis": SALES_BASIS, "checks": [check("Month total = sum of daily sales", net_total(facts), sum(r["netSales"] for r in rows))]}


async def rpt04(ctx: Ctx) -> dict:
    cats = {c.id: c.name_en for c in await ctx.db.scalars(select(Category))}
    return await gross_group(ctx, lambda f: f.category_id, lambda f: {"category": cats.get(f.category_id, "")}, [col("category", "Category")], "category")


async def rpt08(ctx: Ctx) -> dict:
    _, sales, returns = await sales_facts(ctx)
    payments, refunds = await payments_received(ctx, sales, returns)
    wanted = ctx.params.get("paymentMethod")
    methods = sorted({p.method for p in payments} | {r.method for r in refunds})
    rows = []
    for m in methods:
        if wanted and m != wanted:
            continue
        collected = sum((p.amount_applied for p in payments if p.method == m), Decimal(0))
        refunded = sum((r.amount_applied for r in refunds if r.method == m), Decimal(0))
        rows.append({"method": m.replace("_", " "), "count": sum(1 for p in payments if p.method == m), "collected": r2(collected), "refunded": r2(refunded), "net": r2(collected - refunded)})
    rows.sort(key=lambda r: -r["net"])
    return {"columns": [col("method", "Method"), col("count", "Payments", "number"), money("collected", "Collected"), money("refunded", "Refunded"), money("net", "Net received")],
            "rows": rows, "totals": totals_of(rows, ["count", "collected", "refunded", "net"], "method"), "chart": {"type": "pie", "x_key": "method", "series": [{"key": "net", "label": "Net received"}]},
            "basis": "Completed payments on finalized sales, less completed refunds on returns in the period. Payments are cash received, not revenue."}


async def rpt09(ctx: Ctx) -> dict:
    _, sales, _ = await sales_facts(ctx)
    users = {u.id: u.full_name for u in await ctx.db.scalars(select(User))}
    rows = []
    expected = Decimal(0)
    for s in sales:
        expected += s.discount_total
        lines = list(await ctx.db.scalars(select(SaleLine).where(SaleLine.sale_id == s.id)))
        for ln in lines:
            if ln.line_discount:
                rows.append({"date": s.business_date.isoformat(), "receipt": s.receipt_no, "level": "Line", "detail": ln.name_en, "source": ln.line_discount.get("source"), "reason": ln.line_discount.get("reason"),
                             "cashier": users.get(s.cashier_id, ""), "approver": ln.line_discount.get("approved_by") or "", "amount": r2(ln.discount_amount)})
        if s.order_discount:
            rows.append({"date": s.business_date.isoformat(), "receipt": s.receipt_no, "level": "Order", "detail": "Order discount", "source": s.order_discount.get("source"), "reason": s.order_discount.get("reason"),
                         "cashier": users.get(s.cashier_id, ""), "approver": s.order_discount.get("approved_by") or "", "amount": r2(sum((ln.order_discount_share for ln in lines), Decimal(0)))})
    rows.sort(key=lambda r: -r["amount"])
    return {"columns": [col("date", "Date", "date"), col("receipt", "Receipt"), col("level", "Level"), col("detail", "Detail"), col("source", "Source"), col("reason", "Reason"), col("cashier", "Cashier"),
                        col("approver", "Approver"), money("amount", "Amount")], "rows": rows, "totals": totals_of(rows, ["amount"], "date"), "basis": SALES_BASIS,
            "checks": [check("Sum equals sales discount totals", expected, sum(r["amount"] for r in rows), 0.1)]}


async def rpt10(ctx: Ctx) -> dict:
    _, _, returns = await sales_facts(ctx)
    rows = []
    for r in returns:
        sale = await ctx.db.get(Sale, r.original_sale_id)
        reason = await ctx.db.scalar(select(SalesReturnLine.reason).where(SalesReturnLine.return_id == r.id).limit(1))
        rows.append({"date": r.business_date.isoformat(), "returnNo": r.return_no, "receipt": sale.receipt_no if sale else "", "type": r.type, "reason": reason or "", "method": r.refund_method,
                     "by": r.created_by_name, "approver": r.approved_by or "", "amount": r2(r.refund_total)})
    return {"columns": [col("date", "Date", "date"), col("returnNo", "Return no."), col("receipt", "Original receipt"), col("type", "Type"), col("reason", "Reason"), col("method", "Method"),
                        col("by", "Created by"), col("approver", "Approver"), money("amount", "Refund")], "rows": rows, "totals": totals_of(rows, ["amount"], "date"), "basis": "Returns by return business date."}


async def rpt11(ctx: Ctx) -> dict:
    q = select(Sale).where(Sale.company_id == ctx.actor.company_id, Sale.status.in_(("VOIDED", "CANCELLED")), ctx.datetime_range(Sale.created_at))
    branches = ctx.branches()
    if branches is not None:
        q = q.where(Sale.branch_id.in_(branches))
    users = {u.id: u.full_name for u in await ctx.db.scalars(select(User))}
    rows = []
    for s in await ctx.db.scalars(q.order_by(Sale.created_at.desc())):
        if s.status == "CANCELLED" and not await ctx.db.scalar(select(SaleLine.id).where(SaleLine.sale_id == s.id).limit(1)):
            continue
        rows.append({"date": s.created_at.date().isoformat(), "receipt": s.receipt_no or "—", "status": s.status, "cashier": users.get(s.cashier_id, ""), "reason": s.void_reason or s.cancel_reason or "",
                     "approver": s.voided_by or "", "amount": r2(s.grand_total)})
    return {"columns": [col("date", "Date", "date"), col("receipt", "Receipt"), col("status", "Status"), col("cashier", "Cashier"), col("reason", "Reason"), col("approver", "Approver"), money("amount", "Value")],
            "rows": rows, "totals": totals_of(rows, ["amount"], "date"), "basis": "Voided sales and cancelled sales with items, by creation date."}


async def rpt12(ctx: Ctx) -> dict:
    facts, _, _ = await sales_facts(ctx)
    company = await ctx.db.get(Company, ctx.actor.company_id)
    inclusive = bool(company and (company.settings or {}).get("tax_inclusive"))
    rows = sorted(({"code": r["code"] or "(none)", "rate": r2(r["rate"], 4), "netSales": r["netSales"], "tax": r["tax"]}
                   for r in aggregate(facts, lambda f: (f.tax_code, f.tax_rate), lambda f: {"code": f.tax_code, "rate": f.tax_rate})), key=lambda r: r["code"])
    return {"columns": [col("code", "Tax code"), col("rate", "Rate %", "percent"), money("netSales", "Taxable base"), money("tax", "Tax")], "rows": rows,
            "totals": totals_of(rows, ["netSales", "tax"], "code"),
            "basis": f"Prices {'include' if inclusive else 'exclude'} tax (company setting). Tax rates are configuration to confirm with your accountant (V-01)."}


async def rpt13(ctx: Ctx) -> dict:
    out = await gross_group(ctx, lambda f: f.product_id, lambda f: {"sku": f.sku, "product": f.name}, [col("sku", "SKU"), col("product", "Product")], "product")
    out["rows"].sort(key=lambda r: -r.get("grossProfit", 0))
    out["chart"] = bar("product", "grossProfit", "Gross profit")
    out["basis"] = SALES_BASIS + " Gross profit = net sales − COGS at the cost stored on each sale line. Costing: weighted average, company scope (D-05)."
    return out


async def _warehouses(ctx: Ctx) -> list[Warehouse]:
    q = select(Warehouse).where(Warehouse.id.in_(stock.visible_warehouses(ctx.actor)))
    branches = ctx.branches()
    if branches is not None:
        q = q.where(Warehouse.branch_id.in_(branches))
    if ctx.id_param("warehouseId"):
        q = q.where(Warehouse.id == ctx.id_param("warehouseId"))
    return list(await ctx.db.scalars(q.order_by(Warehouse.code)))


async def _products(ctx: Ctx) -> list[Product]:
    q = select(Product).where(Product.company_id == ctx.actor.company_id, Product.deleted_at.is_(None), Product.type.in_(("STANDARD", "WEIGHED")))
    if ctx.id_param("categoryId"):
        q = q.where(Product.category_id == ctx.id_param("categoryId"))
    return list(await ctx.db.scalars(q.order_by(Product.sku)))


async def rpt14(ctx: Ctx) -> dict:
    whs = {w.id: w for w in await _warehouses(ctx)}
    products = {p.id: p for p in await _products(ctx)}
    rows = []
    q = (select(InventoryBalance, WarehouseLocation).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
         .where(InventoryBalance.warehouse_id.in_(list(whs)), InventoryBalance.product_id.in_(list(products)), InventoryBalance.on_hand != 0))
    for b, loc in await ctx.db.execute(q):
        p = products[b.product_id]
        rows.append({"warehouse": whs[b.warehouse_id].name, "location": loc.name, "sku": p.sku, "product": p.name_en, "onHand": r2(b.on_hand, 4), "reserved": r2(b.reserved, 4),
                     "available": r2(b.on_hand - b.reserved, 4) if loc.is_available_for_sale else 0.0})
    rows.sort(key=lambda r: (r["warehouse"], r["sku"], r["location"]))
    recon = await stock.reconcile(ctx.db, ctx.actor)
    return {"columns": [col("warehouse", "Warehouse"), col("location", "Location"), col("sku", "SKU"), col("product", "Product"), col("onHand", "On hand", "number"), col("reserved", "Reserved", "number"),
                        col("available", "Available", "number")], "rows": rows, "totals": totals_of(rows, ["onHand", "reserved", "available"], "warehouse"),
            "basis": "Posted movements as of now.", "checks": [check("Balances with differences to movements", 0, len(recon["differences"]), 0)]}


async def rpt15(ctx: Ctx) -> dict:
    whs = await _warehouses(ctx)
    loc_ids = set(await ctx.db.scalars(select(WarehouseLocation.id).where(WarehouseLocation.warehouse_id.in_([w.id for w in whs]))))
    cats = {c.id: c.name_en for c in await ctx.db.scalars(select(Category))}
    as_of = _d(ctx.params.get("asOf"))
    rows = []
    for p in await _products(ctx):
        if as_of is None:
            qty = Decimal(await ctx.db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(InventoryBalance.product_id == p.id, InventoryBalance.location_id.in_(loc_ids))) or 0)
            value = qty * p.avg_cost
        else:
            qty = value = Decimal(0)
            moves = await ctx.db.scalars(select(InventoryMovement).where(InventoryMovement.product_id == p.id, InventoryMovement.business_date <= as_of,
                                                                         or_(InventoryMovement.to_location_id.in_(loc_ids), InventoryMovement.from_location_id.in_(loc_ids))))
            for m in moves:
                delta = (1 if m.to_location_id in loc_ids else 0) - (1 if m.from_location_id in loc_ids else 0)
                qty += delta * m.quantity_base
                value += delta * m.total_cost
        if qty == 0:
            continue
        rows.append({"sku": p.sku, "product": p.name_en, "category": cats.get(p.category_id, ""), "qty": r2(qty, 4), "avgCost": r2(value / qty, 4), "value": r2(value)})
    rows.sort(key=lambda r: -r["value"])
    return {"columns": [col("sku", "SKU"), col("product", "Product"), col("category", "Category"), col("qty", "Quantity", "number"), money("avgCost", "Avg cost"), money("value", "Value")],
            "rows": rows, "totals": totals_of(rows, ["qty", "value"], "sku"),
            "basis": f"{f'As of {as_of.isoformat()}, from movement costs' if as_of else 'Current, at average cost'}. Costing: weighted average, company scope (D-05)."}


async def _movements(ctx: Ctx, extra=None) -> list[tuple]:
    whs = [w.id for w in await _warehouses(ctx)]
    q = (select(InventoryMovement, Product.sku, Product.name_en).join(Product, Product.id == InventoryMovement.product_id)
         .where(InventoryMovement.warehouse_id.in_(whs), ctx.in_range(InventoryMovement.business_date)))
    if extra is not None:
        q = q.where(extra)
    return list(await ctx.db.execute(q.order_by(InventoryMovement.id.desc()).limit(2000)))


async def rpt16(ctx: Ctx) -> dict:
    locs = {loc.id: loc.name for loc in await ctx.db.scalars(select(WarehouseLocation))}
    rows = [{"date": m.posted_at.isoformat(), "type": m.movement_type, "sku": sku, "product": name, "from": locs.get(m.from_location_id, ""), "to": locs.get(m.to_location_id, ""),
             "qty": r2(m.quantity_base, 4), "reference": m.source_no, "user": m.user_name} for m, sku, name in await _movements(ctx)]
    return {"columns": [col("date", "Posted", "datetime"), col("type", "Type"), col("sku", "SKU"), col("product", "Product"), col("from", "From"), col("to", "To"), col("qty", "Base qty", "number"),
                        col("reference", "Reference"), col("user", "User")], "rows": rows, "basis": "Posted movements, latest 2,000."}


async def _levels(ctx: Ctx) -> list[dict]:
    out = []
    for w in await _warehouses(ctx):
        for p in await _products(ctx):
            if p.status != "ACTIVE":
                continue
            override = await ctx.db.get(ProductWarehouseSetting, (p.id, w.id))
            reorder = override.reorder_level if override else p.reorder_level
            max_level = override.max_level if override else p.max_level
            on_hand, available = (await ctx.db.execute(
                select(func.coalesce(func.sum(InventoryBalance.on_hand), 0),
                       func.coalesce(func.sum(InventoryBalance.on_hand - InventoryBalance.reserved).filter(WarehouseLocation.is_available_for_sale.is_(True)), 0))
                .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).where(InventoryBalance.product_id == p.id, InventoryBalance.warehouse_id == w.id))).one()
            out.append({"w": w, "p": p, "reorder": reorder, "max": max_level, "on_hand": Decimal(on_hand), "available": Decimal(available)})
    return out


async def rpt17(ctx: Ctx) -> dict:
    rows = [{"warehouse": x["w"].name, "sku": x["p"].sku, "product": x["p"].name_en, "available": r2(x["available"], 4), "reorder": r2(x["reorder"], 4),
             "shortfall": r2((x["max"] or x["reorder"]) - x["available"], 3)} for x in await _levels(ctx) if x["reorder"] > 0 and 0 < x["available"] <= x["reorder"]]
    rows.sort(key=lambda r: -r["shortfall"])
    return {"columns": [col("warehouse", "Warehouse"), col("sku", "SKU"), col("product", "Product"), col("available", "Available", "number"), col("reorder", "Reorder level", "number"),
                        col("shortfall", "Suggested qty", "number")], "rows": rows, "basis": "Available is at or below the reorder level."}


async def rpt18(ctx: Ctx) -> dict:
    rows = [{"warehouse": x["w"].name, "sku": x["p"].sku, "product": x["p"].name_en, "available": r2(x["available"], 4), "reorder": r2(x["reorder"], 4)}
            for x in await _levels(ctx) if x["available"] <= 0 and (x["reorder"] > 0 or x["on_hand"] != 0 or x["p"].has_movements)]
    return {"columns": [col("warehouse", "Warehouse"), col("sku", "SKU"), col("product", "Product"), col("available", "Available", "number"), col("reorder", "Reorder level", "number")],
            "rows": rows, "basis": "Active stocked products with no available stock."}


async def rpt19(ctx: Ctx) -> dict:
    rows = [{"warehouse": x["w"].name, "sku": x["p"].sku, "product": x["p"].name_en, "onHand": r2(x["on_hand"], 4), "max": r2(x["max"], 4), "excess": r2(x["on_hand"] - x["max"], 3)}
            for x in await _levels(ctx) if x["max"] > 0 and x["on_hand"] > x["max"]]
    rows.sort(key=lambda r: -r["excess"])
    return {"columns": [col("warehouse", "Warehouse"), col("sku", "SKU"), col("product", "Product"), col("onHand", "On hand", "number"), col("max", "Maximum", "number"), col("excess", "Excess", "number")],
            "rows": rows, "basis": "On hand above the maximum level."}


async def _batches(ctx: Ctx, expired: bool) -> dict:
    whs = [w.id for w in await _warehouses(ctx)]
    company = await ctx.db.get(Company, ctx.actor.company_id)
    days = int(ctx.params.get("days") or (company.settings or {}).get("expiry_warning_days", 30))
    horizon = ctx.today + timedelta(days=days)
    q = (select(InventoryBalance, InventoryBatch, Product, WarehouseLocation)
         .join(InventoryBatch, and_(InventoryBatch.product_id == InventoryBalance.product_id, InventoryBatch.batch_no == InventoryBalance.batch_no))
         .join(Product, Product.id == InventoryBalance.product_id).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
         .where(InventoryBalance.warehouse_id.in_(whs), InventoryBalance.on_hand > 0, InventoryBatch.expiry_date.is_not(None)))
    q = q.where(InventoryBatch.expiry_date < ctx.today) if expired else q.where(InventoryBatch.expiry_date >= ctx.today, InventoryBatch.expiry_date <= horizon)
    rows = [{"sku": p.sku, "product": p.name_en, "batch": batch.batch_no, "expiry": batch.expiry_date.isoformat(), "location": loc.name, "qty": r2(b.on_hand, 4),
             **({"value": r2(b.on_hand * p.avg_cost)} if ctx.sees_cost else {})} for b, batch, p, loc in await ctx.db.execute(q.order_by(InventoryBatch.expiry_date))]
    return {"columns": [col("sku", "SKU"), col("product", "Product"), col("batch", "Batch"), col("expiry", "Expiry", "date"), col("location", "Location"), col("qty", "Qty", "number"),
                        *([money("value", "Value")] if ctx.sees_cost else [])], "rows": rows, "totals": totals_of(rows, ["qty", *(["value"] if ctx.sees_cost else [])], "sku"),
            "basis": f"Batch balances for expiry-tracked products{'' if expired else f', expiring within {days} days'}."}


async def rpt20(ctx: Ctx) -> dict:
    return await _batches(ctx, False)


async def rpt21(ctx: Ctx) -> dict:
    return await _batches(ctx, True)


async def rpt22(ctx: Ctx) -> dict:
    damaged = select(WarehouseLocation.id).where(WarehouseLocation.location_type.in_(("DAMAGED", "EXPIRED")))
    rows = [{"date": m.business_date.isoformat(), "sku": sku, "product": name, "reason": m.reason_code or m.movement_type, "qty": r2(m.quantity_base, 4), "value": r2(m.total_cost),
             "user": m.user_name, "approver": m.approved_by or ""}
            for m, sku, name in await _movements(ctx, or_(InventoryMovement.movement_type.in_(("DAMAGE", "EXPIRY", "WRITE_OFF", "LOSS")), InventoryMovement.to_location_id.in_(damaged)))]
    return {"columns": [col("date", "Date", "date"), col("sku", "SKU"), col("product", "Product"), col("reason", "Reason"), col("qty", "Qty", "number"), money("value", "Value"), col("user", "User"),
                        col("approver", "Approver")], "rows": rows, "totals": totals_of(rows, ["qty", "value"], "date"), "basis": "Damage, expiry, loss and write-off movements, and stock moved into damaged or expired locations."}


async def rpt23(ctx: Ctx) -> dict:
    rows = []
    for m, sku, name in await _movements(ctx, InventoryMovement.source_type == "ADJUSTMENT"):
        sign = 1 if m.to_location_id else -1
        rows.append({"date": m.business_date.isoformat(), "reference": m.source_no, "type": m.movement_type, "sku": sku, "product": name, "reason": m.reason_code or "",
                     "qty": r2(sign * m.quantity_base, 4), "value": r2(sign * m.total_cost), "user": m.user_name, "approver": m.approved_by or ""})
    return {"columns": [col("date", "Date", "date"), col("reference", "Reference"), col("type", "Type"), col("sku", "SKU"), col("product", "Product"), col("reason", "Reason"), col("qty", "Qty", "number"),
                        money("value", "Value"), col("user", "User"), col("approver", "Approver")], "rows": rows, "totals": totals_of(rows, ["qty", "value"], "date"),
            "basis": "Posted adjustment movements; removals are negative."}


async def rpt24(ctx: Ctx) -> dict:
    whs = [w.id for w in await _warehouses(ctx)]
    rows = []
    q = (select(StockCount, StockCountLine, Product, WarehouseLocation).join(StockCountLine, StockCountLine.count_id == StockCount.id).join(Product, Product.id == StockCountLine.product_id)
         .join(WarehouseLocation, WarehouseLocation.id == StockCountLine.location_id).where(StockCount.warehouse_id.in_(whs), StockCount.status == "POSTED"))
    for c, ln, p, loc in await ctx.db.execute(q.order_by(StockCount.posted_at.desc())):
        variance = (ln.counted_qty or 0) - ln.snapshot_qty
        if not variance:
            continue
        rows.append({"count": c.count_no, "location": loc.name, "sku": p.sku, "product": p.name_en, "snapshot": r2(ln.snapshot_qty, 4), "counted": r2(ln.counted_qty, 4), "variance": r2(variance, 4),
                     "value": r2(variance * ln.unit_cost), "reason": ln.reason})
    return {"columns": [col("count", "Count"), col("location", "Location"), col("sku", "SKU"), col("product", "Product"), col("snapshot", "Snapshot", "number"), col("counted", "Counted", "number"),
                        col("variance", "Variance", "number"), money("value", "Value variance"), col("reason", "Reason")], "rows": rows, "totals": totals_of(rows, ["variance", "value"], "count"),
            "basis": "Posted stock counts; value at the cost when posted."}


async def rpt25(ctx: Ctx) -> dict:
    visible = stock.visible_warehouses(ctx.actor)
    whs = {w.id: w.name for w in await ctx.db.scalars(select(Warehouse))}
    q = select(StockTransfer).where(StockTransfer.company_id == ctx.actor.company_id, ctx.datetime_range(StockTransfer.created_at),
                                    StockTransfer.source_warehouse_id.in_(visible) | StockTransfer.destination_warehouse_id.in_(visible))
    rows = []
    for t in await ctx.db.scalars(q.order_by(StockTransfer.created_at.desc())):
        lines = list(await ctx.db.scalars(select(StockTransferLine).where(StockTransferLine.transfer_id == t.id)))
        dispatched = sum((ln.quantity_dispatched for ln in lines), Decimal(0))
        received = sum((ln.quantity_received + ln.quantity_damaged for ln in lines), Decimal(0))
        variance = sum((ln.quantity_short - ln.quantity_excess for ln in lines), Decimal(0))
        rows.append({"date": t.created_at.date().isoformat(), "transfer": t.transfer_no, "source": whs.get(t.source_warehouse_id, ""), "destination": whs.get(t.destination_warehouse_id, ""),
                     "status": t.status, "dispatched": r2(dispatched, 4), "received": r2(received, 4), "variance": r2(variance, 4)})
    done = [r for r in rows if r["status"] in ("RECEIVED", "CLOSED")]
    return {"columns": [col("date", "Date", "date"), col("transfer", "Transfer"), col("source", "Source"), col("destination", "Destination"), col("status", "Status"),
                        col("dispatched", "Dispatched", "number"), col("received", "Received", "number"), col("variance", "Variance", "number")], "rows": rows,
            "basis": "Transfers by request date. Received includes damaged-on-arrival; variance is short minus excess.",
            "checks": [check("Dispatched = received + variance (completed)", sum(r["dispatched"] for r in done), sum(r["received"] + r["variance"] for r in done))]}


async def rpt26(ctx: Ctx) -> dict:
    facts, _, _ = await sales_facts(ctx)
    start = ctx.date_from or (ctx.today - timedelta(days=29))
    end = ctx.date_to or ctx.today
    days = max(1, (end - start).days + 1)
    whs = [w.id for w in await _warehouses(ctx)]
    rows = []
    for p in await _products(ctx):
        own = [f for f in facts if f.product_id == p.id]
        cogs = sum((f.cogs for f in own), Decimal(0))
        units = sum((f.qty for f in own), Decimal(0))
        on_hand = Decimal(await ctx.db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(InventoryBalance.product_id == p.id, InventoryBalance.warehouse_id.in_(whs))) or 0)
        value = on_hand * p.avg_cost
        rows.append({"sku": p.sku, "product": p.name_en, "sold": r2(units, 3), "closing": r2(on_hand, 3), "cogs": r2(cogs), "turnover": r2(cogs / value, 2) if value else 0.0,
                     "daysInv": r2(value / (cogs / days), 0) if cogs > 0 else 0.0, "sellThrough": r2(units / (units + on_hand) * 100, 1) if units + on_hand > 0 else 0.0,
                     "slow": "Slow-moving" if units <= 0 and on_hand > 0 else ""})
    rows.sort(key=lambda r: r["turnover"])
    return {"columns": [col("sku", "SKU"), col("product", "Product"), col("sold", "Units sold", "number"), col("closing", "Closing units", "number"), money("cogs", "COGS"), col("turnover", "Turnover", "number"),
                        col("daysInv", "Days of inventory", "number"), col("sellThrough", "Sell-through %", "percent"), col("slow", "Flag")], "rows": rows,
            "basis": f"COGS from sale-line costs over {days} days; turnover = COGS ÷ closing stock value (closing value approximates average inventory)."}


async def rpt27(ctx: Ctx) -> dict:
    q = select(PurchaseOrder, Supplier.name_en).join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
        PurchaseOrder.company_id == ctx.actor.company_id, PurchaseOrder.warehouse_id.in_(stock.visible_warehouses(ctx.actor)), ctx.datetime_range(PurchaseOrder.created_at))
    if ctx.id_param("supplierId"):
        q = q.where(PurchaseOrder.supplier_id == ctx.id_param("supplierId"))
    rows = []
    for po, supplier in await ctx.db.execute(q.order_by(PurchaseOrder.created_at.desc())):
        ordered, received, cancelled = (await ctx.db.execute(select(func.coalesce(func.sum(PurchaseOrderLine.quantity_base), 0), func.coalesce(func.sum(PurchaseOrderLine.received_base), 0),
                                                                    func.coalesce(func.sum(PurchaseOrderLine.cancelled_base), 0)).where(PurchaseOrderLine.po_id == po.id))).one()
        rows.append({"date": po.created_at.date().isoformat(), "po": po.po_no, "supplier": supplier, "status": po.status, "ordered": r2(ordered, 4), "received": r2(received, 4),
                     "open": r2(max(ordered - received - cancelled, 0), 4) if po.status not in ("CANCELLED", "SHORT_CLOSED") else 0.0, "total": r2(po.total)})
    return {"columns": [col("date", "Date", "date"), col("po", "PO"), col("supplier", "Supplier"), col("status", "Status"), col("ordered", "Ordered", "number"), col("received", "Received", "number"),
                        col("open", "Open", "number"), money("total", "Value")], "rows": rows, "totals": totals_of(rows, ["ordered", "received", "open", "total"], "date"),
            "basis": "Open = ordered − received − cancelled (base units)."}


async def rpt28(ctx: Ctx) -> dict:
    q = (select(GoodsReceipt, GoodsReceiptLine, Supplier.name_en, Product, Unit.code).join(GoodsReceiptLine, GoodsReceiptLine.receipt_id == GoodsReceipt.id)
         .join(Supplier, Supplier.id == GoodsReceipt.supplier_id).join(Product, Product.id == GoodsReceiptLine.product_id).join(Unit, Unit.id == GoodsReceiptLine.unit_id)
         .where(GoodsReceipt.company_id == ctx.actor.company_id, GoodsReceipt.status == "POSTED", GoodsReceipt.warehouse_id.in_(stock.visible_warehouses(ctx.actor)), ctx.datetime_range(GoodsReceipt.posted_at)))
    if ctx.id_param("supplierId"):
        q = q.where(GoodsReceipt.supplier_id == ctx.id_param("supplierId"))
    if ctx.id_param("warehouseId"):
        q = q.where(GoodsReceipt.warehouse_id == ctx.id_param("warehouseId"))
    rows, receipt_ids = [], set()
    for g, ln, supplier, p, unit in await ctx.db.execute(q.order_by(GoodsReceipt.posted_at.desc())):
        receipt_ids.add(str(g.id))
        qty = ln.quantity_received + ln.quantity_damaged
        if qty:
            rows.append({"date": g.posted_at.date().isoformat(), "receipt": g.receipt_no, "supplier": supplier, "sku": p.sku, "product": p.name_en, "qty": r2(qty, 4), "unit": unit, "value": r2(qty * ln.unit_cost)})
    movement_value = await ctx.db.scalar(select(func.coalesce(func.sum(InventoryMovement.total_cost), 0)).where(InventoryMovement.movement_type == "PURCHASE_RECEIPT", InventoryMovement.source_id.in_(receipt_ids))) if receipt_ids else 0
    return {"columns": [col("date", "Date", "date"), col("receipt", "Receipt"), col("supplier", "Supplier"), col("sku", "SKU"), col("product", "Product"), col("qty", "Qty", "number"), col("unit", "Unit"),
                        money("value", "Value")], "rows": rows, "totals": totals_of(rows, ["value"], "date"), "basis": "Posted goods receipts, at the received cost.",
            "checks": [check("Sum equals purchase receipt movements", movement_value, sum(r["value"] for r in rows), 0.05 + 0.01 * len(rows))]}


async def rpt29(ctx: Ctx) -> dict:
    supplier_filter = ctx.id_param("supplierId")
    suppliers = {s.id: s.name_en for s in await ctx.db.scalars(select(Supplier).where(Supplier.company_id == ctx.actor.company_id))}
    visible = stock.visible_warehouses(ctx.actor)
    rows = []
    rq = select(PurchaseReturn).where(PurchaseReturn.company_id == ctx.actor.company_id, PurchaseReturn.warehouse_id.in_(visible), ctx.datetime_range(PurchaseReturn.created_at), PurchaseReturn.status != "CANCELLED")
    gq = select(GoodsReceipt).where(GoodsReceipt.company_id == ctx.actor.company_id, GoodsReceipt.warehouse_id.in_(visible), ctx.datetime_range(GoodsReceipt.created_at))
    if supplier_filter:
        rq, gq = rq.where(PurchaseReturn.supplier_id == supplier_filter), gq.where(GoodsReceipt.supplier_id == supplier_filter)
    for r in await ctx.db.scalars(rq):
        rows.append({"date": r.created_at.date().isoformat(), "kind": "Return", "reference": r.return_no, "supplier": suppliers.get(r.supplier_id, ""), "detail": r.reason, "value": r2(r.total)})
    for g in await ctx.db.scalars(gq):
        for d in g.discrepancies or []:
            rows.append({"date": g.created_at.date().isoformat(), "kind": "Discrepancy", "reference": g.receipt_no, "supplier": suppliers.get(g.supplier_id, ""), "detail": d, "value": 0.0})
    return {"columns": [col("date", "Date", "date"), col("kind", "Kind"), col("reference", "Reference"), col("supplier", "Supplier"), col("detail", "Detail"), money("value", "Value")], "rows": rows,
            "totals": totals_of(rows, ["value"], "date"), "basis": "Purchase returns and goods-receipt discrepancies."}


async def rpt30(ctx: Ctx) -> dict:
    q = select(CashierSession).where(CashierSession.company_id == ctx.actor.company_id, ctx.datetime_range(CashierSession.opened_at))
    branches = ctx.branches()
    if branches is not None:
        q = q.where(CashierSession.branch_id.in_(branches))
    if not ctx.actor.can("cash.session.view_all"):
        q = q.where(CashierSession.cashier_id == ctx.actor.user_id)
    for key, column in (("cashierId", CashierSession.cashier_id), ("terminalId", CashierSession.terminal_id)):
        if ctx.id_param(key):
            q = q.where(column == ctx.id_param(key))
    users = {u.id: u.full_name for u in await ctx.db.scalars(select(User))}
    terminals = {t.id: t.name for t in await ctx.db.scalars(select(PosTerminal))}
    rows = []
    for s in await ctx.db.scalars(q.order_by(CashierSession.opened_at.desc())):
        flows = await cash_sessions.cash_flows(ctx.db, s.id)
        m = flows["movement_totals"]
        counted = s.status != "OPEN"
        rows.append({"session": s.session_no, "opened": s.opened_at.isoformat(), "cashier": users.get(s.cashier_id, ""), "terminal": terminals.get(s.terminal_id, ""), "status": s.status,
                     "opening": r2(s.opening_usd), "cashSales": r2(flows["cash_sales"]["USD"]), "refunds": r2(flows["cash_refunds"]["USD"]), "cashIn": r2(m["CASH_IN"]["USD"]),
                     "out": r2(m["CASH_OUT"]["USD"] + m["PAID_OUT"]["USD"]), "drops": r2(m["DROP"]["USD"]), "expected": r2(s.expected_usd) if counted and s.expected_usd is not None else None,
                     "counted": r2(s.counted_usd) if s.counted_usd is not None else None, "variance": r2(s.variance_usd) if s.variance_usd is not None else None})
    return {"columns": [col("session", "Session"), col("opened", "Opened", "datetime"), col("cashier", "Cashier"), col("terminal", "Terminal"), col("status", "Status"), money("opening", "Opening"),
                        money("cashSales", "Cash sales"), money("refunds", "Refunds"), money("cashIn", "Cash in"), money("out", "Cash out"), money("drops", "Drops"), money("expected", "Expected"),
                        money("counted", "Counted"), money("variance", "Variance")], "rows": rows, "totals": totals_of(rows, ["variance"], "session"),
            "basis": "USD drawer figures (KHR is tracked per session). Expected = opening + cash sales + cash in − refunds − cash out − paid-outs − drops. Expected is shown only after the count."}


async def rpt31(ctx: Ctx) -> dict:
    q = select(CashMovement, CashierSession.session_no).join(CashierSession, CashierSession.id == CashMovement.session_id).where(
        CashierSession.company_id == ctx.actor.company_id, ctx.datetime_range(CashMovement.at))
    branches = ctx.branches()
    if branches is not None:
        q = q.where(CashierSession.branch_id.in_(branches))
    rows = [{"at": m.at.isoformat(), "session": no, "kind": m.kind, "currency": m.currency, "amount": r2(m.amount), "reason": m.reason, "by": m.by_name, "approver": m.approved_by or ""}
            for m, no in await ctx.db.execute(q.order_by(CashMovement.at.desc()))]
    return {"columns": [col("at", "Time", "datetime"), col("session", "Session"), col("kind", "Type"), col("currency", "Currency"), col("amount", "Amount", "number"), col("reason", "Reason"),
                        col("by", "By"), col("approver", "Approver")], "rows": rows, "basis": "Cash movements per session, in their own currency."}


async def rpt32(ctx: Ctx) -> dict:
    q = (select(SalePayment, Sale.receipt_no, Sale.business_date).join(Sale, Sale.id == SalePayment.sale_id)
         .where(SalePayment.company_id == ctx.actor.company_id, SalePayment.method.in_(("CARD", "QR", "BANK_TRANSFER")), ctx.in_range(SalePayment.business_date)))
    branches = ctx.branches()
    if branches is not None:
        q = q.where(Sale.branch_id.in_(branches))
    if ctx.params.get("paymentMethod"):
        q = q.where(SalePayment.method == ctx.params["paymentMethod"])
    rows = [{"date": p.business_date.isoformat(), "receipt": receipt or "—", "method": p.method, "provider": p.provider or "", "reference": p.reference or "", "status": p.status,
             "reconciled": "Matched" if p.reconciled else "Unmatched", "amount": r2(p.amount_applied)} for p, receipt, _ in await ctx.db.execute(q.order_by(SalePayment.created_at.desc()))]
    completed = [r for r in rows if r["status"] in ("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED")]
    return {"columns": [col("date", "Date", "date"), col("receipt", "Receipt"), col("method", "Method"), col("provider", "Provider"), col("reference", "Reference"), col("status", "Status"),
                        col("reconciled", "Reconciliation"), money("amount", "Amount")], "rows": rows, "totals": totals_of(rows, ["amount"], "date"),
            "basis": "Electronic payments, including pending ones. Matching to provider or bank statements is recorded manually until statement import (Phase 8).",
            "checks": [check("Completed value matched", sum(r["amount"] for r in completed), sum(r["amount"] for r in completed if r["reconciled"] == "Matched"))]}


async def rpt33(ctx: Ctx) -> dict:
    facts, _, _ = await sales_facts(ctx)
    rows = []
    month = func.to_char(Expense.date, literal_column("'YYYY-MM'")).label("month")
    eq = select(month, func.sum(Expense.amount_base)).where(Expense.company_id == ctx.actor.company_id, Expense.status == "APPROVED", ctx.in_range(Expense.date))
    branches = ctx.branches()
    if branches is not None:
        eq = eq.where(Expense.branch_id.in_(branches))
    by_month = {m: Decimal(v) for m, v in await ctx.db.execute(eq.group_by(month))}
    periods = {r["period"]: r for r in aggregate(facts, lambda f: f.date.strftime("%Y-%m"), lambda f: {"period": f.date.strftime("%Y-%m")})}
    for month in by_month:
        periods.setdefault(month, {"period": month, "netSales": 0.0, "cogs": 0.0, "grossProfit": 0.0, "margin": 0.0})
    for r in sorted(periods.values(), key=lambda r: r["period"]):
        expenses = r2(by_month.get(r["period"], 0))
        rows.append({"period": r["period"], "netSales": r["netSales"], "cogs": r["cogs"], "grossProfit": r["grossProfit"], "margin": r["margin"], "expenses": expenses, "indicative": r2(r["grossProfit"] - expenses)})
    return {"columns": [col("period", "Period"), money("netSales", "Net sales"), money("cogs", "COGS"), money("grossProfit", "Gross profit"), col("margin", "Margin %", "percent"),
                        money("expenses", "Operating expenses"), money("indicative", "Indicative operating result")], "rows": rows,
            "totals": totals_of(rows, ["netSales", "cogs", "grossProfit", "expenses", "indicative"], "period"),
            "chart": {"type": "line", "x_key": "period", "series": [{"key": "netSales", "label": "Net sales"}, {"key": "grossProfit", "label": "Gross profit"}]},
            "basis": "Indicative operating result is gross profit less approved operating expenses (by expense date); it is not net profit (BR-RPT-002)."}


EXCEPTION_ACTIONS = ("SALE_VOIDED", "RECEIPT_REPRINTED", "SESSION_FORCE_CLOSED", "SESSION_VARIANCE_APPROVED", "SELF_PERMISSION_ATTEMPT", "ACCOUNT_LOCKED", "APPROVAL_GRANTED",
                     "MOVEMENT_REVERSED", "SETTINGS_CHANGED", "REFRESH_TOKEN_REUSE", "RECONCILIATION_MISMATCH", "GRN_POST", "GRN_APPROVE", "GRN_CREATED", "RETURN_CREATED", "SALE_CANCELLED")


async def rpt34(ctx: Ctx) -> dict:
    q = select(AuditLog).where(AuditLog.company_id == ctx.actor.company_id, ctx.datetime_range(AuditLog.occurred_at), or_(AuditLog.flagged.is_(True), AuditLog.action.in_(("SALE_VOIDED", "SESSION_FORCE_CLOSED", "RECEIPT_REPRINTED"))))
    if ctx.actor.branch_ids is not None:
        q = q.where(AuditLog.branch_id.is_(None) | AuditLog.branch_id.in_(ctx.actor.branch_ids))
    rows = [{"at": a.occurred_at.isoformat(), "event": a.action, "user": a.user_name, "entity": f"{a.entity_type}:{a.entity_id[:12]}", "detail": ", ".join(f"{k}={v}" for k, v in (a.after or {}).items())[:300]}
            for a in await ctx.db.scalars(q.order_by(AuditLog.id.desc()).limit(2000))]
    return {"columns": [col("at", "Time", "datetime"), col("event", "Event"), col("user", "User"), col("entity", "Record"), col("detail", "Detail")], "rows": rows,
            "basis": "Flagged audit events (self-approvals, overrides, lockouts, token reuse, risky settings, receipts without PO, mismatches) plus voids, forced closes and reprints."}


@dataclass
class Definition:
    id: str
    name: str
    group: str
    purpose: str
    permission: str
    needs_cost: bool
    filters: list[str]
    run: Callable


async def _product_report(ctx: Ctx) -> dict:
    return await gross_group(ctx, lambda f: f.product_id, lambda f: {"sku": f.sku, "product": f.name}, [col("sku", "SKU"), col("product", "Product")], "product")


async def _branch_report(ctx: Ctx) -> dict:
    return await gross_group(ctx, lambda f: f.branch_id, lambda f: {"branch": f.branch}, [col("branch", "Branch")], "branch")


async def _cashier_report(ctx: Ctx) -> dict:
    return await gross_group(ctx, lambda f: f.cashier_id, lambda f: {"cashier": f.cashier}, [col("cashier", "Cashier")], "cashier", False)


async def _terminal_report(ctx: Ctx) -> dict:
    return await gross_group(ctx, lambda f: f.terminal_id, lambda f: {"terminal": f.terminal}, [col("terminal", "Terminal")], "terminal", False)


S, I_, PU, CA = "reports.sales.view", "reports.inventory.view", "reports.purchasing.view", "reports.cash.view"
REPORTS: list[Definition] = [
    Definition("RPT-01", "Daily sales", "Sales", "End-of-day performance", S, False, ["dateRange", "branch", "terminal"], rpt01),
    Definition("RPT-02", "Monthly sales", "Sales", "Monthly trend", S, False, SF, rpt02),
    Definition("RPT-03", "Sales by product", "Sales", "Item performance", S, False, [*SF, "category"], _product_report),
    Definition("RPT-04", "Sales by category", "Sales", "Category mix", S, False, SF, rpt04),
    Definition("RPT-05", "Sales by branch", "Sales", "Branch comparison", S, False, ["dateRange"], _branch_report),
    Definition("RPT-06", "Sales by cashier", "Sales", "Cashier performance and control", S, False, [*SF, "cashier"], _cashier_report),
    Definition("RPT-07", "Sales by terminal", "Sales", "Terminal activity", S, False, [*SF, "terminal"], _terminal_report),
    Definition("RPT-08", "Sales by payment method", "Sales", "Payment mix", S, False, [*SF, "paymentMethod"], rpt08),
    Definition("RPT-09", "Discounts", "Sales", "Discount control", S, False, SF, rpt09),
    Definition("RPT-10", "Refunds", "Sales", "Refund control", S, False, SF, rpt10),
    Definition("RPT-11", "Voided and cancelled transactions", "Sales", "Void control", S, False, SF, rpt11),
    Definition("RPT-12", "Sales tax summary", "Sales", "Tax preparation support", "reports.tax.view", False, SF, rpt12),
    Definition("RPT-13", "Gross profit and margin", "Sales", "Profitability", "reports.profit.view", True, [*SF, "category"], rpt13),
    Definition("RPT-14", "Current stock", "Inventory", "Stock position", I_, False, ["branch", "warehouse", "category"], rpt14),
    Definition("RPT-15", "Stock valuation", "Inventory", "Inventory value", I_, True, ["asOf", "warehouse", "category", "branch"], rpt15),
    Definition("RPT-16", "Stock movement history", "Inventory", "Traceability and reconciliation", I_, False, ["dateRange", "branch", "warehouse"], rpt16),
    Definition("RPT-17", "Low-stock products", "Inventory", "Replenishment", I_, False, ["branch", "warehouse", "category"], rpt17),
    Definition("RPT-18", "Out-of-stock products", "Inventory", "Lost-sales risk", I_, False, ["branch", "warehouse"], rpt18),
    Definition("RPT-19", "Overstock", "Inventory", "Excess inventory", I_, False, ["branch", "warehouse"], rpt19),
    Definition("RPT-20", "Expiring products", "Inventory", "Waste prevention", I_, False, ["branch", "warehouse"], rpt20),
    Definition("RPT-21", "Expired products", "Inventory", "Disposal", I_, False, ["branch", "warehouse"], rpt21),
    Definition("RPT-22", "Damaged inventory", "Inventory", "Loss tracking", I_, True, ["dateRange", "branch", "warehouse"], rpt22),
    Definition("RPT-23", "Stock adjustments", "Inventory", "Adjustment control", I_, True, ["dateRange", "branch", "warehouse"], rpt23),
    Definition("RPT-24", "Stocktake variances", "Inventory", "Count accuracy", I_, True, ["branch", "warehouse"], rpt24),
    Definition("RPT-25", "Transfer history", "Inventory", "Transfer tracking", I_, False, ["dateRange"], rpt25),
    Definition("RPT-26", "Inventory turnover and slow-moving stock", "Inventory", "Velocity", I_, True, ["dateRange", "category", "branch"], rpt26),
    Definition("RPT-27", "Purchase orders and outstanding POs", "Purchasing", "Procurement status", PU, True, ["dateRange", "supplier"], rpt27),
    Definition("RPT-28", "Goods received; purchases by supplier and product", "Purchasing", "Receiving and spend", PU, True, ["dateRange", "supplier", "warehouse"], rpt28),
    Definition("RPT-29", "Purchase returns and delivery discrepancies", "Purchasing", "Supplier quality", PU, True, ["dateRange", "supplier"], rpt29),
    Definition("RPT-30", "Cashier session report", "Cash", "Cash accountability (overage and shortage)", CA, False, ["dateRange", "branch", "cashier", "terminal"], rpt30),
    Definition("RPT-31", "Cash movement report", "Cash", "Cash in/out, paid-outs, drops", CA, False, ["dateRange", "branch"], rpt31),
    Definition("RPT-32", "Payment reconciliation", "Cash", "Provider and bank matching; pending payments", CA, False, ["dateRange", "branch", "paymentMethod"], rpt32),
    Definition("RPT-33", "Business performance", "Business", "Revenue and gross-profit trends, best and worst sellers, operating result", "reports.business.view", True, SF, rpt33),
    Definition("RPT-34", "Control exceptions", "Control", "Overrides, self-approvals, reprints, voids, negative stock, receipts without PO", "reports.exceptions.view", False, ["dateRange"], rpt34),
]
BY_ID = {d.id: d for d in REPORTS}


def definition_view(d: Definition) -> dict:
    return {"id": d.id, "name": d.name, "group": d.group, "purpose": d.purpose, "permission": d.permission, "needs_cost": d.needs_cost, "filters": d.filters}


def catalogue(actor: Principal) -> list[dict]:
    return [definition_view(d) for d in REPORTS if actor.can(d.permission) and (not d.needs_cost or actor.sees_cost)]


async def run(db: AsyncSession, actor: Principal, report_id: str, params: dict[str, Any]) -> dict:
    d = BY_ID.get(report_id.upper())
    if d is None:
        raise NotFound("Report")
    actor.require(d.permission)
    if d.needs_cost and not actor.sees_cost:
        raise Forbidden("This report needs cost visibility (inventory.cost.view).")
    out = await d.run(Ctx(db, actor, params))
    return {"definition": definition_view(d), "basis": out.get("basis", ""), "columns": out["columns"], "rows": out["rows"], "totals": out.get("totals"), "chart": out.get("chart"),
            "checks": out.get("checks", []), "generated_at": datetime.now(UTC), "generated_by": actor.full_name}

