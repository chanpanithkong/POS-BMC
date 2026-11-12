"""Small file store for uploads sent as data: URLs (product images, expense attachments).

Files are checked by their first bytes (not the declared type), size-limited, and saved
under a random name inside STORAGE_DIR/<folder>. The returned path is served by the API.
"""

import base64
import binascii
import re
import uuid

from app.core.config import get_settings
from app.core.exceptions import ValidationFailed

SIGNATURES = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",
    b"%PDF-": "pdf",
}
MAX_BYTES = 5 * 1024 * 1024


def store_data_url(folder: str, data_url: str, *, field: str, allowed: tuple[str, ...], max_bytes: int = MAX_BYTES) -> str:
    match = re.fullmatch(r"data:([a-z]+/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", data_url)
    if not match:
        raise ValidationFailed(field, "Upload the file again; it could not be read.")
    try:
        raw = base64.b64decode(match.group(2))
    except binascii.Error as exc:
        raise ValidationFailed(field, "The file could not be read.") from exc
    if len(raw) > max_bytes:
        raise ValidationFailed(field, f"Files must be {max_bytes // (1024 * 1024)} MB or less.")
    ext = next((e for magic, e in SIGNATURES.items() if raw.startswith(magic)), None)
    if ext == "webp" and raw[8:12] != b"WEBP":
        ext = None
    if ext is None or ext not in allowed:
        raise ValidationFailed(field, f"Allowed file types: {', '.join(a.upper() for a in allowed)}.")
    target = get_settings().storage_dir / folder
    target.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (target / name).write_bytes(raw)
    return f"/api/v1/files/{folder}/{name}"


def stored_path(folder: str, name: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp|pdf)", name):
        return None
    path = get_settings().storage_dir / folder / name
    return path if path.is_file() else None
