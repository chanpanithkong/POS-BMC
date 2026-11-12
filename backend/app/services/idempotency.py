"""Idempotency keys for commands that post stock or money (SRS 13.1, NFR-REL-003).

The key row is written in its own short transaction before the command runs:
- same key and same body again: the stored response is replayed and nothing runs twice;
- same key with a different body: 409 IDEMPOTENCY_KEY_REUSED;
- same key while the first request is still running: 409 REQUEST_IN_PROGRESS.
If the command fails, the key is released so the client can retry.

Document state checks and the unique (source_type, source_line_id, movement_type)
constraint on movements remain the last line of defence if a process dies between
the command's commit and recording its response.
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import AppError, ValidationFailed
from app.db.session import session_factory
from app.models import IdempotencyKey
from app.services.principal import Principal

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")


class IdempotencyConflict(AppError):
    status_code = 409


def _hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(body), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def run(
    request: Request, actor: Principal, key: str | None, body: Any, command: Callable[[], Awaitable[Any]], *,
    response_model: type[BaseModel] | None = None, status_code: int = 200,
) -> JSONResponse:
    if not key:
        raise ValidationFailed("Idempotency-Key", "This request needs an Idempotency-Key header.")
    if not KEY_PATTERN.fullmatch(key):
        raise ValidationFailed("Idempotency-Key", "Idempotency-Key must be 8 to 80 letters, digits, '-', '_', '.' or ':'.")
    scope = f"{actor.company_id}:{actor.user_id}:{request.method} {request.url.path}"[:200]
    digest = _hash(body)
    async with session_factory()() as s:
        inserted = await s.scalar(
            insert(IdempotencyKey).values(scope=scope, key=key, request_hash=digest, status="IN_PROGRESS").on_conflict_do_nothing().returning(IdempotencyKey.key)
        )
        await s.commit()
        if inserted is None:
            existing = await s.scalar(select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key))
            if existing is None:
                raise IdempotencyConflict("Please retry the request.", code="REQUEST_IN_PROGRESS")
            if existing.request_hash != digest:
                raise IdempotencyConflict("This Idempotency-Key was already used for a different request.", code="IDEMPOTENCY_KEY_REUSED")
            if existing.status != "COMPLETED":
                raise IdempotencyConflict("The same request is still being processed.", code="REQUEST_IN_PROGRESS")
            return JSONResponse(existing.response_body, status_code=existing.response_status or 200, headers={"Idempotent-Replayed": "true"})
    try:
        result = await command()
    except BaseException:
        async with session_factory()() as s:
            await s.execute(delete(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key))
            await s.commit()
        raise
    payload = response_model.model_validate(result).model_dump(mode="json", by_alias=True) if response_model else jsonable_encoder(result)
    async with session_factory()() as s:
        await s.execute(update(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key).values(status="COMPLETED", response_status=status_code, response_body=payload))
        await s.commit()
    return JSONResponse(payload, status_code=status_code)
