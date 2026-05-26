from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "public"

CONSULTATION_IMAGE = PUBLIC_DIR / "photo_2026-05-08_13-48-34.jpg"
DEBT_IMAGE = PUBLIC_DIR / "photo_2026-05-08_13-48-42.jpg"
AGENT_IMAGE = PUBLIC_DIR / "image.png"
PARTNER_IMAGE = PUBLIC_DIR / "photo_2026-05-08_13-48-57.jpg"


def local_photo(path: Path) -> FSInputFile | None:
    return FSInputFile(path) if path.exists() else None
