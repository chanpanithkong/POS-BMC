"""Background worker (Phase 8).

Run:  .venv\\Scripts\\python.exe -m app.workers.run            (every 60 seconds)
      .venv\\Scripts\\python.exe -m app.workers.run --once     (one pass, e.g. from a scheduler)

Each task runs in its own transaction and is safe to run again:
- release stock reservations whose time ran out (BR-INV-009);
- re-check inventory alerts for every company;
- send queued password-reset emails from the outbox (only when SMTP is configured);
- remind cashiers and managers of sessions open for more than 12 hours;
- delete completed idempotency keys older than 7 days and expired import previews (SRS 11.10).
"""

import argparse
import asyncio
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.permissions import PERMISSIONS
from app.core.runtime import use_selector_loop
from app.db.session import dispose_engine, session_factory
from app.models import CashierSession, Company, IdempotencyKey, ImportPreview, Notification, OutboxEvent
from app.services import alerts, notifications, sales
from app.services.principal import LIMIT_KEYS, Principal

log = logging.getLogger("pims.worker")
MAX_ATTEMPTS = 10


def system_principal(company_id) -> Principal:
    """Acts for the system in scheduled jobs; audit entries show the user 'System'."""
    return Principal(user_id=None, company_id=company_id, session_id=None, username="system", full_name="System",  # type: ignore[arg-type]
                     permissions=frozenset(PERMISSIONS), limits={k: Decimal(0) for k in LIMIT_KEYS}, role_codes=[], branch_ids=None, warehouse_ids=None)


async def release_reservations() -> int:
    released = 0
    async with session_factory()() as db:
        for company_id in list(await db.scalars(select(Company.id))):
            released += await sales.release_expired(db, company_id)
        await db.commit()
    return released


async def evaluate_alerts() -> int:
    async with session_factory()() as db:
        companies = list(await db.scalars(select(Company.id)))
    raised = 0
    for company_id in companies:
        async with session_factory()() as db:
            raised += (await alerts.evaluate(db, system_principal(company_id)))["raised"]
    return raised


def _send(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


async def send_emails() -> int:
    settings = get_settings()
    sent = 0
    async with session_factory()() as db:
        events = list(await db.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "PASSWORD_RESET_REQUESTED", OutboxEvent.published_at.is_(None), OutboxEvent.attempts < MAX_ATTEMPTS)
            .order_by(OutboxEvent.id).limit(50).with_for_update(skip_locked=True)
        ))
        for event in events:
            event.attempts += 1
            if not settings.smtp_host:
                event.last_error = "SMTP is not configured (SMTP_HOST); the email stays queued."
                continue
            link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={event.payload.get('token', '')}"
            body = f"Use this link within 30 minutes to set a new password:\n\n{link}\n\nIf you did not ask for this, ignore this email."
            try:
                await asyncio.to_thread(_send, event.payload["email"], "Reset your PIMS password", body)
            except Exception as exc:  # noqa: BLE001 - recorded on the event and retried
                event.last_error = str(exc)[:500]
                continue
            # The token is a secret: once delivered it is removed from the stored payload.
            event.payload = {**event.payload, "token": "[sent]"}
            event.published_at, event.last_error = datetime.now(UTC), None
            sent += 1
        await db.commit()
    return sent


async def remind_open_sessions() -> int:
    reminded = 0
    async with session_factory()() as db:
        cutoff = datetime.now(UTC) - timedelta(hours=12)
        for s in list(await db.scalars(select(CashierSession).where(CashierSession.status == "OPEN", CashierSession.opened_at < cutoff))):
            link = f"/cashier-sessions?session={s.id}"
            if await db.scalar(select(Notification.id).where(Notification.link == link, Notification.kind == "SESSION_REMINDER").limit(1)):
                continue
            message = f"{s.session_no} has been open for more than 12 hours."
            notifications.notify(db, s.company_id, "SESSION_REMINDER", "Cashier session still open", message, link=link, user_id=s.cashier_id)
            notifications.notify(db, s.company_id, "SESSION_REMINDER", "Cashier session still open", message, link=link, permission="cash.session.approve", branch_id=s.branch_id)
            reminded += 1
        await db.commit()
    return reminded


async def cleanup() -> int:
    async with session_factory()() as db:
        old = datetime.now(UTC) - timedelta(days=7)
        keys = await db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < old, IdempotencyKey.status == "COMPLETED"))
        previews = await db.execute(delete(ImportPreview).where(ImportPreview.expires_at < datetime.now(UTC)))
        await db.commit()
        return (keys.rowcount or 0) + (previews.rowcount or 0)


TASKS = {"reservations": release_reservations, "alerts": evaluate_alerts, "emails": send_emails, "sessions": remind_open_sessions, "cleanup": cleanup}


async def run_once() -> dict[str, int | str]:
    results: dict[str, int | str] = {}
    for name, task in TASKS.items():
        try:
            results[name] = await task()
        except Exception as exc:  # noqa: BLE001 - one failing task must not stop the others
            log.exception("worker task %s failed", name)
            results[name] = f"error: {exc.__class__.__name__}"
    return results


async def main(once: bool, interval: int) -> None:
    configure_logging()
    try:
        while True:
            log.info("worker pass %s", await run_once())
            if once:
                break
            await asyncio.sleep(interval)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PIMS background worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    use_selector_loop()
    asyncio.run(main(args.once, args.interval))
