"""User, role, permission, employee and audit-log endpoints (AUTH, AUDIT)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentPrincipal, DbSession, require
from app.core.permissions import PERMISSIONS
from app.models import AuditLog
from app.repositories.users import user_view
from app.schemas.common import ListResponse, error_responses
from app.schemas.users import (
    AuditLogOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PermissionOut,
    PinUpdate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    StatusUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import users as service
from app.services.audit import verify_chain
from app.services.principal import Principal

router = APIRouter()
UserViewer = Annotated[Principal, Depends(require("users.user.view", "users.user.manage"))]
UserAdmin = Annotated[Principal, Depends(require("users.user.manage"))]
RoleViewer = Annotated[Principal, Depends(require("users.role.view", "users.role.manage"))]
RoleAdmin = Annotated[Principal, Depends(require("users.role.manage"))]
ERR = error_responses(401, 403, 404, 409, 422)


# Users

@router.get("/users", response_model=ListResponse[UserOut], tags=["Users"], summary="List users", responses=ERR)
async def list_users(actor: UserViewer, db: DbSession, q: str | None = None, status_filter: Annotated[str | None, Query(alias="status", pattern="^(ACTIVE|INACTIVE)$")] = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    items, total = await service.list_users(db, actor, q=q, status=status_filter, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, tags=["Users"], summary="Create a user", responses=ERR)
async def create_user(body: UserCreate, actor: UserAdmin, db: DbSession) -> dict:
    return await service.create_user(db, actor, body)


@router.get("/users/{user_id}", response_model=UserOut, tags=["Users"], summary="Get a user", responses=ERR)
async def get_user(user_id: uuid.UUID, actor: UserViewer, db: DbSession) -> dict:
    return await user_view(db, await service.get_user(db, actor, user_id))


@router.patch("/users/{user_id}", response_model=UserOut, tags=["Users"], summary="Update a user, their roles and scope", responses=ERR,
              description="Changing your own roles or scope is refused and flagged in the audit log.")
async def update_user(user_id: uuid.UUID, body: UserUpdate, actor: UserAdmin, db: DbSession) -> dict:
    return await service.update_user(db, actor, user_id, body)


@router.put("/users/{user_id}", response_model=UserOut, tags=["Users"], summary="Update a user (same as PATCH; kept for the frontend)", responses=ERR, include_in_schema=False)
async def put_user(user_id: uuid.UUID, body: UserUpdate, actor: UserAdmin, db: DbSession) -> dict:
    return await service.update_user(db, actor, user_id, body)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"], summary="Soft-delete a user", responses=ERR)
async def delete_user(user_id: uuid.UUID, actor: UserAdmin, db: DbSession) -> Response:
    await service.delete_user(db, actor, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/status", response_model=UserOut, tags=["Users"], summary="Activate or deactivate a user", responses=ERR)
async def set_status(user_id: uuid.UUID, body: StatusUpdate, actor: UserAdmin, db: DbSession) -> dict:
    return await service.set_status(db, actor, user_id, body.status)


@router.post("/users/{user_id}/unlock", response_model=UserOut, tags=["Users"], summary="Unlock a locked account", responses=ERR)
async def unlock(user_id: uuid.UUID, actor: UserAdmin, db: DbSession) -> dict:
    return await service.unlock(db, actor, user_id)


@router.post("/users/{user_id}/pin", response_model=UserOut, tags=["Users"], summary="Set a PIN (own PIN, or any user's with users.user.manage)", responses=ERR)
async def set_pin(user_id: uuid.UUID, body: PinUpdate, actor: CurrentPrincipal, db: DbSession) -> dict:
    return await service.set_pin(db, actor, user_id, body.pin)


# Roles and permissions

@router.get("/roles", response_model=list[RoleOut], tags=["Roles"], summary="List roles with permissions, limits and SoD conflicts", responses=ERR)
async def list_roles(actor: RoleViewer, db: DbSession) -> list[dict]:
    return await service.list_roles(db, actor)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED, tags=["Roles"], summary="Create a custom role", responses=ERR)
async def create_role(body: RoleCreate, actor: RoleAdmin, db: DbSession) -> dict:
    return await service.create_role(db, actor, body)


@router.patch("/roles/{role_id}", response_model=RoleOut, tags=["Roles"], summary="Update a role", responses=ERR,
              description="Changing the permissions of a role you hold is refused.")
async def update_role(role_id: uuid.UUID, body: RoleUpdate, actor: RoleAdmin, db: DbSession) -> dict:
    return await service.update_role(db, actor, role_id, body)


@router.put("/roles/{role_id}", response_model=RoleOut, tags=["Roles"], include_in_schema=False)
async def put_role(role_id: uuid.UUID, body: RoleUpdate, actor: RoleAdmin, db: DbSession) -> dict:
    return await service.update_role(db, actor, role_id, body)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Roles"], summary="Delete an unused custom role", responses=ERR)
async def delete_role(role_id: uuid.UUID, actor: RoleAdmin, db: DbSession) -> Response:
    await service.delete_role(db, actor, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/permissions", response_model=list[PermissionOut], tags=["Roles"], summary="Permission catalogue", responses=ERR)
async def list_permissions(_: RoleViewer) -> list[dict]:
    return [{"code": code, "module": code.split(".")[0], "description": text} for code, text in PERMISSIONS.items()]


# Employees

@router.get("/employees", response_model=list[EmployeeOut], tags=["Users"], summary="List employees", responses=ERR)
async def list_employees(actor: UserViewer, db: DbSession) -> list:
    return await service.list_employees(db, actor)


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, tags=["Users"], summary="Create an employee", responses=ERR)
async def create_employee(body: EmployeeCreate, actor: UserAdmin, db: DbSession) -> object:
    return await service.create_employee(db, actor, body)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut, tags=["Users"], summary="Update an employee", responses=ERR)
async def update_employee(employee_id: uuid.UUID, body: EmployeeUpdate, actor: UserAdmin, db: DbSession) -> object:
    return await service.update_employee(db, actor, employee_id, body)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"], summary="Delete an employee with no user account", responses=ERR)
async def delete_employee(employee_id: uuid.UUID, actor: UserAdmin, db: DbSession) -> Response:
    await service.delete_employee(db, actor, employee_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Audit log

@router.get("/audit-logs", response_model=ListResponse[AuditLogOut], tags=["Audit"], summary="Search the audit log", responses=ERR)
async def audit_logs(actor: Annotated[Principal, Depends(require("audit.log.view"))], db: DbSession,
                     module: str | None = None, action: str | None = None, user_id: uuid.UUID | None = None, entity_type: str | None = None, entity_id: str | None = None,
                     flagged: bool | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    query = select(AuditLog).where(AuditLog.company_id == actor.company_id)
    for column, value in ((AuditLog.module, module), (AuditLog.action, action), (AuditLog.user_id, user_id), (AuditLog.entity_type, entity_type), (AuditLog.entity_id, entity_id), (AuditLog.flagged, flagged)):
        if value is not None:
            query = query.where(column == value)
    if date_from:
        query = query.where(AuditLog.occurred_at >= date_from)
    if date_to:
        query = query.where(AuditLog.occurred_at < date_to)
    if actor.branch_ids is not None:
        query = query.where(AuditLog.branch_id.is_(None) | AuditLog.branch_id.in_(actor.branch_ids))
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = await db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    return {"items": list(rows), "total": total}


@router.get("/audit-logs/verify", tags=["Audit"], summary="Verify the audit hash chain", responses=ERR)
async def verify_audit(actor: Annotated[Principal, Depends(require("audit.log.view"))], db: DbSession) -> dict:
    intact, broken_at = await verify_chain(db, actor.company_id)
    return {"intact": intact, "first_broken_id": broken_at}
