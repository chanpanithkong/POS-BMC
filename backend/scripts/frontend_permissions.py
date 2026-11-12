r"""Writes frontend/src/lib/api/permission-map.ts from FRONTEND_KEY_MAP so the two never drift.

Run:  .venv\Scripts\python.exe -m scripts.frontend_permissions
"""

from app.core.config import BACKEND_DIR
from app.core.permissions import FRONTEND_KEY_MAP

TARGET = BACKEND_DIR.parent / "frontend" / "src" / "lib" / "api" / "permission-map.ts"
HEADER = """/**
 * Frontend permission keys and the backend codes they stand for (SRS 4.2 `module.resource.action`).
 * Generated from backend/app/core/permissions.py FRONTEND_KEY_MAP by backend/scripts/frontend_permissions.py. Do not edit by hand.
 */
import type { Permission } from "@/types";

export const FRONTEND_TO_BACKEND: Record<Permission, string> = {
"""


def main() -> None:
    body = "".join(f'  "{key}": "{code}",\n' for key, code in FRONTEND_KEY_MAP.items())
    TARGET.write_text(HEADER + body + "};\n", encoding="utf-8")
    print(f"Wrote {TARGET} ({len(FRONTEND_KEY_MAP)} keys)")


if __name__ == "__main__":
    main()
