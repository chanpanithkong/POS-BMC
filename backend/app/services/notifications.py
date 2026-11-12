"""In-app notifications (NTF; Phase 8).

A notification is addressed to everyone who holds `audience_permission` within
`branch_id` (or to one user). Reading is tracked per user. Notifications are
written in the same transaction as the event that causes them.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, NotificationRead
from app.services.principal import Principal


def notify(db: AsyncSession, company_id: uuid.UUID, kind: str, title: str, message: str, *, link: str | None = None, permission: str | None = None,
           branch_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> None:
    db.add(Notification(company_id=company_id, kind=kind, title=title[:200], message=message, link=link, audience_permission=permission, branch_id=branch_id, user_id=user_id))


def _visible(actor: Principal):
    query = select(Notification).where(Notification.company_id == actor.company_id, or_(Notification.user_id.is_(None), Notification.user_id == actor.user_id))
    query = query.where(or_(Notification.audience_permission.is_(None), Notification.audience_permission.in_(list(actor.permissions) or [""])))
    if actor.branch_ids is not None:
        query = query.where(or_(Notification.branch_id.is_(None), Notification.branch_id.in_(actor.branch_ids)))
    return query


async def list_for(db: AsyncSession, actor: Principal, unread_only: bool = False) -> list[dict]:
    read = set(await db.scalars(select(NotificationRead.notification_id).where(NotificationRead.user_id == actor.user_id)))
    rows = await db.scalars(_visible(actor).order_by(Notification.created_at.desc()).limit(200))
    out = []
    for n in rows:
        if unread_only and n.id in read:
            continue
        out.append({"id": n.id, "kind": n.kind, "title": n.title, "message": n.message, "link": n.link, "read": n.id in read, "created_at": n.created_at,
                    "audience_permission": n.audience_permission, "branch_id": n.branch_id})
    return out


async def mark_read(db: AsyncSession, actor: Principal, ids: list[uuid.UUID] | None) -> int:
    visible = set(await db.scalars(_visible(actor).with_only_columns(Notification.id)))
    targets = visible if ids is None else visible & set(ids)
    if targets:
        await db.execute(insert(NotificationRead).values([{"notification_id": t, "user_id": actor.user_id} for t in targets]).on_conflict_do_nothing())
    await db.commit()
    return len(targets)
