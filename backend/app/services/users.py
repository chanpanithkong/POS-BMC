"""User, role and employee administration (FR-AUTH-003, 005, 006, 012, 013)."""

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, NotFound, ValidationFailed
from app.core.permissions import PERMISSIONS, SOD_CONFLICTS
from app.core.security import hash_secret, pin_lookup, pin_problems
from app.models import Branch, Employee, Role, RolePermission, User, UserBranchAccess, UserRole, UserWarehouseAccess, Warehouse
from app.repositories.users import user_view
from app.schemas.users import EmployeeCreate, EmployeeUpdate, RoleCreate, RoleUpdate, UserCreate, UserUpdate
from app.services import audit
from app.services.auth import check_password, revoke_user_sessions
from app.services.principal import Principal


def _actor(p: Principal) -> dict[str, Any]:
    return {"company_id": p.company_id, "user_id": p.user_id, "user_name": p.full_name}


async def get_user(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.company_id != actor.company_id or user.deleted_at is not None:
        raise NotFound("User")
    return user


async def list_users(db: AsyncSession, actor: Principal, *, q: str | None, status: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    query = select(User).where(User.company_id == actor.company_id, User.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(User.full_name).like(like) | func.lower(User.username).like(like) | func.lower(User.email).like(like))
    if status:
        query = query.where(User.status == status)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    users = await db.scalars(query.order_by(User.full_name).limit(limit).offset(offset))
    return [await user_view(db, u) for u in users], total


async def _check_unique(db: AsyncSession, *, username: str | None, email: str | None, exclude: uuid.UUID | None) -> None:
    for column, value, field in ((User.username, username, "username"), (User.email, email, "email")):
        if value is None:
            continue
        query = select(User.id).where(func.lower(column) == value.lower(), User.deleted_at.is_(None))
        if exclude:
            query = query.where(User.id != exclude)
        if await db.scalar(query):
            raise AppError(f"{field.title()} already exists.", code="DUPLICATE", status_code=409, details=[{"field": field, "message": f"{field.title()} already exists."}])


async def _check_ids(db: AsyncSession, company_id: uuid.UUID, model: type, ids: list[uuid.UUID], field: str) -> None:
    if not ids:
        return
    found = set(await db.scalars(select(model.id).where(model.id.in_(ids), model.company_id == company_id)))
    if found != set(ids):
        raise ValidationFailed(field, f"One or more {field.replace('_ids', '')} records do not exist.")


async def _set_links(db: AsyncSession, user_id: uuid.UUID, model: type, column: str, ids: list[uuid.UUID]) -> None:
    await db.execute(delete(model).where(model.user_id == user_id))
    db.add_all(model(user_id=user_id, **{column: value}) for value in dict.fromkeys(ids))


async def create_user(db: AsyncSession, actor: Principal, data: UserCreate) -> dict:
    await _check_unique(db, username=data.username, email=data.email, exclude=None)
    check_password(data.password, data.username)
    await _check_ids(db, actor.company_id, Role, data.role_ids, "role_ids")
    await _check_ids(db, actor.company_id, Branch, data.branch_ids, "branch_ids")
    await _check_ids(db, actor.company_id, Warehouse, data.warehouse_ids, "warehouse_ids")
    user = User(
        company_id=actor.company_id, username=data.username, email=data.email.lower(), full_name=data.full_name, phone=data.phone,
        language=data.language, password_hash=hash_secret(data.password), employee_id=data.employee_id, created_by=actor.user_id,
    )
    db.add(user)
    await db.flush()
    await _set_links(db, user.id, UserRole, "role_id", data.role_ids)
    await _set_links(db, user.id, UserBranchAccess, "branch_id", data.branch_ids)
    await _set_links(db, user.id, UserWarehouseAccess, "warehouse_id", data.warehouse_ids)
    await db.flush()
    view = await user_view(db, user)
    await audit.record(db, action="USER_CREATED", module="AUTH", entity_type="user", entity_id=user.id, after={k: str(v) for k, v in view.items() if k in ("username", "email", "role_ids", "branch_ids")}, **_actor(actor))
    await db.commit()
    return view


async def update_user(db: AsyncSession, actor: Principal, user_id: uuid.UUID, data: UserUpdate) -> dict:
    user = await get_user(db, actor, user_id)
    before = await user_view(db, user)
    changes = data.model_dump(exclude_unset=True)
    scope_change = any(changes.get(k) is not None and changes[k] != before[k] for k in ("role_ids", "branch_ids", "warehouse_ids"))
    if user.id == actor.user_id and scope_change:
        await audit.record(db, action="SELF_PERMISSION_ATTEMPT", module="AUTH", entity_type="user", entity_id=user.id, flagged=True, **_actor(actor))
        await db.commit()
        raise Forbidden("You cannot change your own permissions.")
    await _check_unique(db, username=changes.get("username"), email=changes.get("email"), exclude=user.id)
    for field in ("username", "full_name", "phone", "language", "employee_id"):
        if field in changes:
            setattr(user, field, changes[field])
    if changes.get("email"):
        user.email = changes["email"].lower()
    if changes.get("password"):
        check_password(changes["password"], user.username)
        user.password_hash = hash_secret(changes["password"])
        await revoke_user_sessions(db, user.id, "PASSWORD_RESET_BY_ADMIN")
    for field, model, column, ref in (("role_ids", UserRole, "role_id", Role), ("branch_ids", UserBranchAccess, "branch_id", Branch), ("warehouse_ids", UserWarehouseAccess, "warehouse_id", Warehouse)):
        if changes.get(field) is not None:
            await _check_ids(db, actor.company_id, ref, changes[field], field)
            await _set_links(db, user.id, model, column, changes[field])
    user.updated_by = actor.user_id
    await db.flush()
    after = await user_view(db, user)
    serial = lambda view: {k: [str(x) for x in v] if isinstance(v, list) else str(v) for k, v in view.items() if k in ("username", "email", "full_name", "role_ids", "branch_ids", "warehouse_ids")}  # noqa: E731
    await audit.record(db, action="PERMISSIONS_CHANGED" if scope_change else "USER_UPDATED", module="AUTH", entity_type="user", entity_id=user.id, before=serial(before), after=serial(after), **_actor(actor))
    await db.commit()
    return after


async def set_status(db: AsyncSession, actor: Principal, user_id: uuid.UUID, status: str) -> dict:
    user = await get_user(db, actor, user_id)
    if user.id == actor.user_id:
        raise Forbidden("You cannot change the status of your own account.")
    user.status = status
    if status == "INACTIVE":
        await revoke_user_sessions(db, user.id, "DEACTIVATED")
    await audit.record(db, action="USER_ACTIVATED" if status == "ACTIVE" else "USER_DEACTIVATED", module="AUTH", entity_type="user", entity_id=user.id, **_actor(actor))
    await db.commit()
    return await user_view(db, user)


async def delete_user(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> None:
    """Soft delete: the account stops working, history keeps its references (FR-AUTH-005)."""
    user = await get_user(db, actor, user_id)
    if user.id == actor.user_id:
        raise Forbidden("You cannot delete your own account.")
    user.status = "INACTIVE"
    user.deleted_at = func.now()
    await revoke_user_sessions(db, user.id, "DELETED")
    await audit.record(db, action="USER_DELETED", module="AUTH", entity_type="user", entity_id=user.id, before={"username": user.username}, **_actor(actor))
    await db.commit()


async def unlock(db: AsyncSession, actor: Principal, user_id: uuid.UUID) -> dict:
    user = await get_user(db, actor, user_id)
    user.locked_until, user.failed_login_count, user.first_failed_at = None, 0, None
    await audit.record(db, action="USER_UNLOCKED", module="AUTH", entity_type="user", entity_id=user.id, **_actor(actor))
    await db.commit()
    return await user_view(db, user)


async def set_pin(db: AsyncSession, actor: Principal, user_id: uuid.UUID, pin: str) -> dict:
    if user_id != actor.user_id:
        actor.require("users.user.manage")
    user = await get_user(db, actor, user_id)
    problems = pin_problems(pin)
    if problems:
        raise ValidationFailed("pin", problems[0])
    lookup = pin_lookup(user.company_id, pin)
    # Unique across the company, which is stricter than the SRS per-branch rule and keeps PIN sign-in unambiguous.
    if await db.scalar(select(User.id).where(User.company_id == user.company_id, User.pin_lookup == lookup, User.id != user.id, User.deleted_at.is_(None))):
        raise ValidationFailed("pin", "This PIN is already in use. Choose another.")
    user.pin_hash, user.pin_lookup = hash_secret(pin), lookup
    await audit.record(db, action="PIN_RESET", module="AUTH", entity_type="user", entity_id=user.id, **_actor(actor))
    await db.commit()
    return await user_view(db, user)


# Roles


def sod_conflicts(permissions: set[str]) -> list[str]:
    return [label for a, b, label in SOD_CONFLICTS if a in permissions and b in permissions]


async def role_view(db: AsyncSession, role: Role) -> dict:
    perms = sorted(await db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)))
    return {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "is_system": role.is_system, "permissions": perms, "limits": role.limits, "sod_conflicts": sod_conflicts(set(perms))}


async def list_roles(db: AsyncSession, actor: Principal) -> list[dict]:
    roles = await db.scalars(select(Role).where(Role.company_id == actor.company_id).order_by(Role.is_system.desc(), Role.name))
    return [await role_view(db, r) for r in roles]


async def _get_role(db: AsyncSession, actor: Principal, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None or role.company_id != actor.company_id:
        raise NotFound("Role")
    return role


def _check_permissions(codes: list[str]) -> None:
    unknown = sorted(set(codes) - set(PERMISSIONS))
    if unknown:
        raise ValidationFailed("permissions", f"Unknown permissions: {', '.join(unknown)}")


async def create_role(db: AsyncSession, actor: Principal, data: RoleCreate) -> dict:
    _check_permissions(data.permissions)
    if await db.scalar(select(Role.id).where(Role.company_id == actor.company_id, Role.code == data.code)):
        raise Conflict("A role with this code already exists.", code="DUPLICATE")
    role = Role(company_id=actor.company_id, code=data.code, name=data.name, description=data.description, limits={k: str(v) for k, v in data.limits.model_dump().items()}, created_by=actor.user_id)
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission_code=p) for p in set(data.permissions))
    conflicts = sod_conflicts(set(data.permissions))
    await audit.record(db, action="ROLE_CREATED", module="AUTH", entity_type="role", entity_id=role.id, after={"code": role.code, "permissions": sorted(set(data.permissions)), "sod_conflicts": conflicts}, flagged=bool(conflicts), **_actor(actor))
    await db.commit()
    return await role_view(db, role)


async def update_role(db: AsyncSession, actor: Principal, role_id: uuid.UUID, data: RoleUpdate) -> dict:
    role = await _get_role(db, actor, role_id)
    before = await role_view(db, role)
    held = set(await db.scalars(select(UserRole.role_id).where(UserRole.user_id == actor.user_id)))
    if role.id in held and (data.permissions is not None or data.limits is not None):
        raise Forbidden("You cannot change the permissions of a role you hold.")
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.limits is not None:
        role.limits = {k: str(v) for k, v in data.limits.model_dump().items()}
    if data.permissions is not None:
        _check_permissions(data.permissions)
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(RolePermission(role_id=role.id, permission_code=p) for p in set(data.permissions))
    role.updated_by = actor.user_id
    await db.flush()
    after = await role_view(db, role)
    await audit.record(db, action="ROLE_UPDATED", module="AUTH", entity_type="role", entity_id=role.id, before={"permissions": before["permissions"], "limits": before["limits"]}, after={"permissions": after["permissions"], "limits": after["limits"]}, flagged=bool(after["sod_conflicts"]), **_actor(actor))
    await db.commit()
    return after


async def delete_role(db: AsyncSession, actor: Principal, role_id: uuid.UUID) -> None:
    role = await _get_role(db, actor, role_id)
    if role.is_system:
        raise Conflict("Default roles cannot be deleted.", code="ROLE_IN_USE")
    if await db.scalar(select(UserRole.user_id).where(UserRole.role_id == role.id).limit(1)):
        raise Conflict("This role is assigned to users.", code="ROLE_IN_USE")
    await db.delete(role)
    await audit.record(db, action="ROLE_DELETED", module="AUTH", entity_type="role", entity_id=role_id, before={"code": role.code}, **_actor(actor))
    await db.commit()


# Employees


async def list_employees(db: AsyncSession, actor: Principal) -> list[Employee]:
    return list(await db.scalars(select(Employee).where(Employee.company_id == actor.company_id).order_by(Employee.code)))


async def _get_employee(db: AsyncSession, actor: Principal, employee_id: uuid.UUID) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.company_id != actor.company_id:
        raise NotFound("Employee")
    return employee


async def _unique_employee_code(db: AsyncSession, actor: Principal, code: str, exclude: uuid.UUID | None) -> None:
    query = select(Employee.id).where(Employee.company_id == actor.company_id, Employee.code == code)
    if exclude:
        query = query.where(Employee.id != exclude)
    if await db.scalar(query):
        raise Conflict("Employee code already exists.", code="DUPLICATE", details=[{"field": "code", "message": "Employee code already exists."}])


async def create_employee(db: AsyncSession, actor: Principal, data: EmployeeCreate) -> Employee:
    await _unique_employee_code(db, actor, data.code, None)
    if data.branch_id:
        await _check_ids(db, actor.company_id, Branch, [data.branch_id], "branch_ids")
    employee = Employee(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump())
    db.add(employee)
    await db.flush()
    await audit.record(db, action="EMPLOYEE_CREATED", module="AUTH", entity_type="employee", entity_id=employee.id, after={"code": employee.code}, **_actor(actor))
    await db.commit()
    return employee


async def update_employee(db: AsyncSession, actor: Principal, employee_id: uuid.UUID, data: EmployeeUpdate) -> Employee:
    employee = await _get_employee(db, actor, employee_id)
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes:
        await _unique_employee_code(db, actor, changes["code"], employee.id)
    for field, value in changes.items():
        setattr(employee, field, value)
    employee.updated_by = actor.user_id
    await audit.record(db, action="EMPLOYEE_UPDATED", module="AUTH", entity_type="employee", entity_id=employee.id, after={k: str(v) for k, v in changes.items()}, **_actor(actor))
    await db.commit()
    return employee


async def delete_employee(db: AsyncSession, actor: Principal, employee_id: uuid.UUID) -> None:
    employee = await _get_employee(db, actor, employee_id)
    if await db.scalar(select(User.id).where(User.employee_id == employee.id)):
        raise Conflict("This employee is linked to a user account. Deactivate it instead.", code="IN_USE")
    await db.delete(employee)
    await audit.record(db, action="EMPLOYEE_DELETED", module="AUTH", entity_type="employee", entity_id=employee_id, **_actor(actor))
    await db.commit()
