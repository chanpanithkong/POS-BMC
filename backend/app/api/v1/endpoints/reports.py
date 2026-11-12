"""Report catalogue, report runs, CSV/XLSX exports and the dashboard (RPT, DSH, EXP; Phase 7).

Filters are query parameters: dateFrom, dateTo, asOf, branchId, warehouseId, categoryId,
terminalId, cashierId, paymentMethod, supplierId. Add `format=csv` or `format=xlsx` to
download (needs reports.data.export; every export is audited).
"""

import csv
import io
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.api.deps import CurrentPrincipal, DbSession, require
from app.schemas.common import Command, ListResponse, Out, error_responses
from app.services import dashboard, reports
from app.services.common import record_audit
from app.services.principal import Principal

router = APIRouter(tags=["Reports and dashboard"])
ERR = error_responses(401, 403, 404, 422)
FILTER_KEYS = ("dateFrom", "dateTo", "asOf", "branchId", "warehouseId", "categoryId", "terminalId", "cashierId", "paymentMethod", "supplierId", "days")
ALIASES = {"sales": "RPT-01", "inventory": "RPT-14", "gross-profit": "RPT-13", "cashier-sessions": "RPT-30"}


class ReportDefinitionOut(Out):
    id: str
    name: str
    group: str
    purpose: str
    permission: str
    needs_cost: bool
    filters: list[str]


class ReportResultOut(Out):
    definition: ReportDefinitionOut
    basis: str
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    chart: dict[str, Any] | None
    checks: list[dict[str, Any]]
    generated_at: Any
    generated_by: str


class ExportAudit(Command):
    name: str = Field(min_length=1, max_length=100)
    format: str = Field(min_length=1, max_length=10)
    rows: int = Field(ge=0)


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def _params(request: Request) -> dict[str, str]:
    """Accepts dateFrom or date_from (the frontend client sends snake_case query names)."""
    params = {_camel(k): v for k, v in request.query_params.items() if v}
    return {k: v for k, v in params.items() if k in FILTER_KEYS}


def _cell(value: Any) -> Any:
    return "" if value is None else value


def _file(result: dict, fmt: str) -> tuple[bytes, str, str]:
    columns = result["columns"]
    header = [c["label"] for c in columns]
    body = [[_cell(row.get(c["key"])) for c in columns] for row in result["rows"]]
    if result.get("totals"):
        body.append([_cell(result["totals"].get(c["key"])) for c in columns])
    title = f"{result['definition']['id']} {result['definition']['name']}"
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([title])
        writer.writerow([result["basis"]])
        writer.writerow(header)
        writer.writerows(body)
        # The byte-order mark lets Excel open Khmer text correctly.
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "csv"
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = result["definition"]["id"]
    ws.append([title])
    ws.append([result["basis"]])
    ws.append(header)
    for cell in ws[3]:
        cell.font = Font(bold=True)
    for row in body:
        ws.append(row)
    for i, column in enumerate(columns, start=1):
        if column["type"] in ("money", "number", "percent"):
            for (cell,) in ws.iter_rows(min_row=4, min_col=i, max_col=i):
                cell.number_format = "#,##0.00" if column["type"] == "money" else "#,##0.###"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"


@router.get("/reports", response_model=ListResponse[ReportDefinitionOut], summary="Reports you can run", responses=ERR)
async def catalogue(actor: CurrentPrincipal) -> dict:
    items = reports.catalogue(actor)
    return {"items": items, "total": len(items)}


async def _run(request: Request, actor: Principal, db: DbSession, report_id: str, fmt: str | None) -> Any:
    result = await reports.run(db, actor, report_id, _params(request))
    if fmt is None:
        return result
    actor.require("reports.data.export")
    content, media, ext = _file(result, fmt)
    await record_audit(db, actor, "REPORT_EXPORTED", "RPT", "report", result["definition"]["id"], after={"format": fmt, "rows": len(result["rows"]), "filters": _params(request)})
    await db.commit()
    return StreamingResponse(iter([content]), media_type=media, headers={"Content-Disposition": f'attachment; filename="{result["definition"]["id"]}.{ext}"'})


@router.get("/reports/{alias}", response_model=ReportResultOut, summary="Run a report (RPT-01 to RPT-34, or sales / inventory / gross-profit / cashier-sessions)", responses=ERR,
            description="Filters: dateFrom, dateTo, asOf, branchId, warehouseId, categoryId, terminalId, cashierId, paymentMethod, supplierId. format=csv or xlsx downloads the report.")
async def run_report(alias: str, request: Request, actor: CurrentPrincipal, db: DbSession, format: Literal["csv", "xlsx"] | None = None) -> Any:  # noqa: A002
    return await _run(request, actor, db, ALIASES.get(alias, alias), format)


@router.post("/exports/audit", status_code=204, summary="Record an export or print made in the browser", responses=ERR)
async def audit_export(body: ExportAudit, actor: CurrentPrincipal, db: DbSession) -> None:
    await record_audit(db, actor, "REPORT_EXPORTED", "RPT", "report", body.name[:64], after={"format": body.format, "rows": body.rows, "source": "browser"})
    await db.commit()


@router.get("/dashboard", summary="Role dashboard: KPIs, trends, top and slow products, alerts, approvals", responses=ERR,
            description="dateFrom and dateTo default to today; branchId narrows to one branch. KPIs compare with the previous period of the same length.")
async def get_dashboard(request: Request, actor: Annotated[Principal, Depends(require("dashboard.dashboard.view"))], db: DbSession) -> dict:
    return await dashboard.build(db, actor, _params(request))
