"""Environment discovery and LLM provider resolution.

Two jobs:

1. Find and parse a `.env` file by walking up from `prototype/backend/` toward
   the repository root. Deliberately dependency-free — no python-dotenv — so a
   judge can run the prototype with nothing but the packages in
   requirements.txt, and so the parsing rules below are auditable in one place.

2. Decide which LLM provider is available, in priority order:
       OPENAI_API_KEY  ->  "openai"
       ANTHROPIC_API_KEY -> "anthropic"
       neither          -> "offline"   (rule-based Korean template)

The offline path is never removed: the whole product must run with no API key
at all.
"""

from __future__ import annotations

import os
from pathlib import Path

# Search this many directory levels up from backend/ for a .env file.
ENV_SEARCH_DEPTH = 5
ENV_FILENAME = ".env"

# Keys we are willing to import from a .env file. An allowlist, not a blanket
# import, so a stray .env cannot inject arbitrary environment variables.
ENV_KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OFFLINE = "offline"

# Verified against this account with `client.models.list()` and a live
# function-calling probe on 2026-08-03 — see README §7.
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

_STRIP_CHARS = " \t\r\n\"'<>"


def clean_env_value(raw: str) -> str:
    """Normalise a value copied out of a dashboard or a chat message.

    Handles the mistakes people actually make when pasting a key:
      `  sk-proj-abc  `      -> `sk-proj-abc`   (surrounding whitespace)
      `"sk-proj-abc"`        -> `sk-proj-abc`   (quotes)
      `<sk-proj-abc>`        -> `sk-proj-abc`   (angle-bracket placeholders)
      `"<sk-proj-abc>"`      -> `sk-proj-abc`   (both, in either order)

    Stripping repeats until the value stops changing so nesting order does not
    matter. Characters inside the value are never touched.
    """
    value = raw or ""
    while True:
        stripped = value.strip(_STRIP_CHARS)
        if stripped == value:
            return stripped
        value = stripped


def parse_env_text(text: str) -> dict:
    """Parse .env text into a dict. Tolerates BOM, CRLF, blank lines, `export`."""
    result: dict[str, str] = {}
    for line in (text or "").lstrip("﻿").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip().lstrip("﻿")
        if not key:
            continue
        result[key] = clean_env_value(value)
    return result


def find_env_file(start: Path | None = None, depth: int = ENV_SEARCH_DEPTH) -> Path | None:
    """Walk upward from `start` (default: backend/) looking for a .env file."""
    current = (start or Path(__file__).resolve().parent.parent).resolve()
    for _ in range(depth + 1):
        candidate = current / ENV_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def load_env_file(path: Path | None = None, override: bool = False) -> dict:
    """Load allowlisted keys from a .env file into os.environ.

    A real environment variable always wins unless `override=True`, so
    `set OPENAI_API_KEY=` in a shell can deliberately blank the file value.
    Returns the keys that were applied. Never raises on a missing or
    unreadable file.
    """
    env_path = path or find_env_file()
    if env_path is None:
        return {}
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}

    applied = {}
    for key, value in parse_env_text(text).items():
        if key not in ENV_KEYS or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


# --------------------------------------------------------------------------
# 파일 로그의 위치 (SPEC 7.2)
# --------------------------------------------------------------------------
#
# SPEC 7.2 는 「로컬 실행이므로 외부 APM을 도입하지 않는다. 파일 로그 + 상태 화면으로
# 충분하다」고 적었다. 그 파일이 어디에 놓이는지는 **설정**이므로 환경변수로 주입한다
# (부록 A — 비밀·설정은 환경변수로 주입하고 `.env` 는 유일 경로가 아니다).
#
# 기본값이 `backend/var/` 인 이유는 `DEFAULT_STORE_URL` 이 이미 거기 있고 `.gitignore`
# 가 그 디렉터리를 통째로 빼고 있기 때문이다. 로그는 **커밋되면 안 되는 산출물**이다 —
# 본문을 찍지 않더라도 운영 흔적이고, 커밋된 실행 산출물이 코드보다 오래 살아남아
# 거짓이 되는 것을 이 저장소는 이미 한 번 겪었다 (`.gitignore` 의 QA 산출물 항목).

#: 파일 로그 경로의 환경변수. 없으면 아래 기본값.
LOG_FILE_ENV = "FIRSTHOME_LOG_FILE"

#: `backend/` 기준 상대 경로.
DEFAULT_LOG_FILE = "var/observability.jsonl"


def log_file_path() -> Path:
    """파일 로그의 경로. **매 호출 새로 읽는다** — 캐시하면 테스트가 서로 격리되지 않는다.

    `resolve_provider()` 가 키를 매번 새로 읽는 것과 같은 규약이다.
    """
    override = clean_env_value(os.environ.get(LOG_FILE_ENV, ""))
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / DEFAULT_LOG_FILE


def resolve_provider() -> str:
    """Return the active provider. Read fresh every call — never cached."""
    if clean_env_value(os.environ.get("OPENAI_API_KEY", "")):
        return PROVIDER_OPENAI
    if clean_env_value(os.environ.get("ANTHROPIC_API_KEY", "")):
        return PROVIDER_ANTHROPIC
    return PROVIDER_OFFLINE


def openai_model() -> str:
    return clean_env_value(os.environ.get("OPENAI_MODEL", "")) or DEFAULT_OPENAI_MODEL


def anthropic_model() -> str:
    return clean_env_value(os.environ.get("ANTHROPIC_MODEL", "")) or DEFAULT_ANTHROPIC_MODEL


# Populate os.environ once at import so uvicorn workers and pytest both see it.
LOADED_ENV_PATH = find_env_file()
load_env_file(LOADED_ENV_PATH)
