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
import sys
from pathlib import Path
from typing import Callable, Mapping

# Search this many directory levels up from backend/ for a .env file.
ENV_SEARCH_DEPTH = 5
ENV_FILENAME = ".env"

# Keys we are willing to import from a .env file. An allowlist, not a blanket
# import, so a stray .env cannot inject arbitrary environment variables.
ENV_KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")

# 배포 경계를 정하는 키들. **`.env` 에서 읽지 않는다** — 그리고 그것이 의도다.
#
# 이 값들은 [지금 프로덕션인가] [쿠키에 Secure 를 붙이는가] 처럼 배포 경계를 세우거나,
# 시드 비밀번호처럼 비밀이다. 경계는 커밋되어 리뷰를 거치는 매니페스트(`render.yaml`)나
# 명시적인 `docker run -e` 가 세워야 한다. `.gitignore` 된 작업 파일이 세우면 안 된다.
#
# ★ 허용목록을 넓히면 오히려 나빠진다. `load_env_file` 은 `os.environ` 에 **없을 때만**
#   파일 값을 싣고, README 는 `.env.example` 을 `.env` 로 복사하라고 한다. 이 키들을
#   허용목록에 넣으면 그 복사본이 [플랫폼이 값을 주지 않는 배포]에서 Secure 를 끄는
#   실효 설정이 된다 — 아무도 읽지 않는 파일이 HTTPS 배포의 쿠키 보안을 정하게 된다.
#   그래서 `.env.example` 은 이 키들에 값을 주지 않는다.
#
# 이름을 `auth`·`store` 에서 import 하지 않고 리터럴로 적는 이유는 이 모듈이 최하위
# 계층이기 때문이다 (둘 중 어느 것도 import 하지 않는다). 어긋나면
# `tests/api/test_env_boundary.py` 가 깨진다.
PROCESS_ONLY_KEYS = (
    "HOME_COMPASS_ENV",
    "HOME_COMPASS_COOKIE_SECURE",
    "HOME_COMPASS_STORE_URL",
    "HOME_COMPASS_LOG_FILE",
    # 시드 비밀번호는 `.env` 로 들어오면 안 되고, 들어와도 버려진다 — 그래서 경고 대상이다.
    "HOME_COMPASS_SEED_COUNSELOR_PASSWORD",
    # (이름 둘 사이에 이 주석이 있는 이유: 인접한 두 따옴표 리터럴은
    #  `test_auth.TestSeedPasswordsAreNotCommitted` 의 [이름 = "값"] 패턴과 모양이 같다.
    #  그 검사를 약하게 만드는 대신 여기 한 줄을 둔다.)
    "HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD",
)

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


def _warn(lines: list[str]) -> None:
    """**stderr 로 낸다.** `scripts/gen_contracts.py --stdout` 이 계약 파일 바이트를
    stdout 으로 흘리는데 이 모듈의 적재가 그 경로에 들어 있다 — stdout 에 한 줄이라도
    찍으면 생성물 앞에 그 줄이 붙어 계약이 깨진다 (`auth._announce` 와 같은 이유)."""
    for line in lines:
        print(line, file=sys.stderr)


def ignored_process_only_keys(parsed: Mapping[str, str]) -> list[str]:
    """`.env` 에 적혔지만 이 로더가 싣지 않는 배포 경계 키. 정렬해 돌려준다.

    **허용목록 밖 키 전부를 보고하지 않는다.** `MOLIT_API_KEY` 는 `.env` 에 있는 것이
    정상이고 `ingest.market.source.resolve_api_key()` 가 파일을 직접 읽어 쓴다. 올바른
    설정에서 뜨는 경고는 운영자가 경고 전체를 무시하도록 길들인다. 그래서 [뜻이 있는데
    이 경로로는 도달하지 않는 키]인 `PROCESS_ONLY_KEYS` 만 본다.
    """
    return sorted(k for k in parsed if k in PROCESS_ONLY_KEYS)


def load_env_file(
    path: Path | None = None,
    override: bool = False,
    warn: Callable[[list[str]], None] | None = None,
) -> dict:
    """Load allowlisted keys from a .env file into os.environ.

    A real environment variable always wins unless `override=True`, so
    `set OPENAI_API_KEY=` in a shell can deliberately blank the file value.
    Returns the keys that were applied. Never raises on a missing or
    unreadable file.

    파일에 배포 경계 키(`PROCESS_ONLY_KEYS`)가 있으면 **버렸다고 말한다.** 조용히
    넘어가면 운영자는 `.env` 에 적은 `HOME_COMPASS_COOKIE_SECURE=true` 가 적용된 줄
    알고 HTTPS 에 Secure 없는 쿠키를 내보내게 된다.
    """
    env_path = path or find_env_file()
    if env_path is None:
        return {}
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}

    parsed = parse_env_text(text)
    applied = {}
    for key, value in parsed.items():
        if key not in ENV_KEYS or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            applied[key] = value

    ignored = ignored_process_only_keys(parsed)
    if ignored:
        emit = _warn if warn is None else warn
        emit([
            "",
            f"[설정] {env_path} 의 다음 키는 읽지 않았습니다: {', '.join(ignored)}",
            "[설정] 배포 경계와 비밀은 `.env` 가 아니라 프로세스 환경변수로 주입합니다 —",
            "[설정] render.yaml 의 envVars 또는 `docker run -e KEY=값`.",
            "[설정] 지금 이 값들은 **적용되지 않은 상태**입니다.",
            "",
        ])
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
LOG_FILE_ENV = "HOME_COMPASS_LOG_FILE"

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
