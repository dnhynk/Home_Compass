"""Home_Compass — FastAPI entry point.

Thin HTTP layer over the deterministic engines. It does three things and
nothing else: validate input, call `engines.analyze()` / `engines.agent.chat()`,
and serve the vanilla frontend as static files.

Run:  python -m uvicorn home_compass.main:app --host 127.0.0.1 --port 8000
      (from backend/src)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import (
    ANONYMOUS_ACTOR,
    AUDIT_DENIED,
    AUDIT_LOGIN,
    AUDIT_LOGOUT,
    AUTH_CONSTANT_KEYS,
    COOKIE_PATH,
    COOKIE_SAMESITE,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_ABSOLUTE_TIMEOUT_KEY,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TIMEOUT_KEY,
    AuthError,
    Session,
    SessionStore,
    allows,
    burn_absent_user_time,
    cookie_secure,
    csrf_error,
    csrf_matches,
    ensure_seed_accounts,
    forbidden_error,
    record,
    unauthenticated_error,
    verify_password,
)
from .config import log_file_path
from .engines import (
    DISCLAIMER,
    ENGINE_VERSION,
    analyze,
    required_constant_keys,
)
from .llm.agent import chat, get_llm_mode
from .store import (
    AnomalyReport,
    ApprovalRecord,
    DraftAlreadyDecidedError,
    Provenance,
    RecordNotFoundError,
    Region,
    RuleVersion,
    Store,
    store_from_env,
)
# 계약 디렉터리의 위치는 `store` 가 이미 정했다 (환경변수 `HOME_COMPASS_CONTRACTS_DIR`).
# 두 번 정의하면 한쪽만 갈아끼울 때 조용히 갈라진다 — `ingest.extraction_verify` 가
# 같은 이유로 같은 것을 쓴다. `api -> store` 는 허용된 방향이다 (SPEC 1.2).
from .store.provenance import contracts_dir
# 지역의 **사실 필드 이름**은 저장소가 정한다 (`models.REGION_FACT_FIELDS`). api 가 다시
# 적으면 D-13 의 `targets` 가 저장소와 다른 이름으로 응답 위치를 가리키게 된다 —
# `scripts/gen_contracts.py` 가 프론트 생성물의 `$factFields` 를 만들 때와 같은 경로다.
from .store.models import (
    POLICY_REPORT_FIELDS,
    REGION_FACT_FIELDS,
    REPORT_TARGET_KINDS,
)

FRONTEND_DIR = Path(
    os.environ.get("HOME_COMPASS_FRONTEND_DIR")
    or Path(__file__).resolve().parents[3] / "frontend"
)

#: 규칙 관리 화면 (SPEC 6.2 「동일 오리진」). **별도 포트를 만들지 않는다** — 쿠키 세션이
#: `SameSite` 로 서 있고(6.3), 오리진을 가르는 순간 CORS 와 CSRF 를 새로 설계해야 한다.
#: `web` 이 `/` 에 서는 것과 같은 방식으로 `admin` 은 `/admin` 에 선다.
ADMIN_DIR = Path(
    os.environ.get("HOME_COMPASS_ADMIN_DIR")
    or Path(__file__).resolve().parents[3] / "admin"
)

# --------------------------------------------------------------------------
# Model constants — injected into the engines, never read by them (SPEC 5.1.1)
# --------------------------------------------------------------------------
#
# 값의 정본은 `store` 의 `ModelConstant` 다 (SPEC 1.2 생성 방향 `store -> api ->
# engines` · contracts/README "이 파일은 값의 정본이 아니다"). 런타임에
# `contracts/model_constants.json` 을 읽는 경로는 없다 — 있으면 그 계약이 거짓이 된다.
#
# **검증 대상 키 목록의 정본은 `engines.required_constant_keys()` 다.**
#   - 수요측(엔진이 실제로 `constants[...]` 로 조회하는 키)만이 "없으면 판정이 불가능한
#     키"를 정의한다. 계약 파일을 정본으로 삼으면 api 가 계약 파일을 다시 런타임에 읽게
#     되어 컷오버가 무의미해지고, 저장소를 정본으로 삼으면 "저장소에 있는 것이 곧 필요한
#     것"이 되어 fail-closed 가 항등식으로 무너진다 (빠진 키는 정의상 검출되지 않는다).
#   - 계약 파일은 **키 공간의 계약**이며 시드(빌드 시점)와 테스트가 읽는다. 셋이 어긋나는
#     경우는 테스트로 고정한다 — 계약↔엔진은 `tests/test_engine_constants.py`,
#     계약↔저장소↔엔진은 `tests/crosscheck/test_constant_key_sources.py` 다.


def load_model_constants(store: Store) -> dict:
    """Read the constant mapping from the store and verify it is complete.

    Fail-closed (Part 0-E #2 · SPEC 5.1.1): a missing constant refuses the boot
    instead of letting a runtime default decide someone's housing budget. The
    engines never fall back either — they subscript the mapping directly, so a
    key that slipped past this check still raises `KeyError` at its use site.

    `as_mapping()` already restores the types JSON cannot carry (int household
    keys, the priority tuples) from each row's `value_type`, so nothing is
    re-decoded here.
    """
    mapping = store.model_constants.as_mapping()
    # 인증의 세션 만료 상수도 같은 자리에서 본다 (SPEC 6.3 · Part 0-E #4). 별도 설정
    # 개념을 새로 만들지 않았으므로 검사도 새로 만들지 않는다 — 없으면 **기동이 거부된다.**
    # 런타임에 [만료 없는 세션] 으로 도는 경로를 남기지 않는 것이 이 한 줄의 목적이다.
    required = set(required_constant_keys()) | set(AUTH_CONSTANT_KEYS)
    missing = sorted(required - set(mapping))
    if missing:
        raise RuntimeError(
            "모델 상수가 누락되어 기동할 수 없습니다 (SPEC 5.1.1 fail-closed). "
            f"저장소에 {len(mapping)}개가 있고 누락된 키: {missing}. "
            "저장소가 비어 있다면 `python scripts/seed_store.py` 를 먼저 실행하세요."
        )
    return mapping


def boot_model_constants() -> dict:
    """기동 시 1회. 저장소를 열어 매핑을 뜨고 곧바로 닫는다.

    연결을 들고 있지 않는 이유는 둘이다. (1) `sqlite3` 연결은 만든 스레드에서만 쓸 수
    있는데 FastAPI 의 동기 엔드포인트는 워커 스레드에서 돈다. (2) 상수는 기동 시점
    검증 대상이므로(SPEC 5.1.1 "기동 시") 요청마다 다시 읽을 이유가 없다.

    SPEC 2.3 의 "프로세스 수명 캐시 금지"는 **활성 규칙·시세**에 걸린 규칙이다 —
    막으려는 사고가 "승인·배치 반영이 재기동 전까지 판정에 안 보이는 것"이기 때문이다.
    모델 상수를 바꾸는 것은 승인도 배치도 아니라 1-② 의 데이터 교체이며 재기동을 동반한다.
    """
    with store_from_env() as store:
        return load_model_constants(store)


MODEL_CONSTANTS = boot_model_constants()


def boot_model_constant_provenance() -> dict[str, dict]:
    """상수 키 -> 계보 (SPEC 2.1 · D-13). 기동 시 1회, `MODEL_CONSTANTS` 와 같은 자리다.

    `as_mapping()` 은 주입 형태(키 -> **값**)라 계보를 담지 않는다. 계보는 응답 조립의
    재료이므로 값과 **같은 순간**에 떠야 한다 — 두 번 열어 따로 읽으면 그 사이에 값과
    계보가 어긋난 조합이 나올 수 있다.

    캐시 판단은 `boot_model_constants` 와 같다: 상수 교체는 승인도 배치도 아니라 1-② 의
    데이터 교체이며 재기동을 동반한다 (SPEC 2.3 의 캐시 금지는 지역·활성 규칙에 걸린 규칙).
    """
    with store_from_env() as store:
        return {c.key: c.provenance.to_dict() for c in store.model_constants.list()}


MODEL_CONSTANT_PROVENANCE = boot_model_constant_provenance()


# --------------------------------------------------------------------------
# 지역 · 정책 — 요청마다 저장소에서 새로 읽는다 (SPEC 2.3)
# --------------------------------------------------------------------------
#
# 상수와 **반대 칸**이다 (계약 결정 #13 의 표). 상수는 배포·재기동을 동반하는 값 교체라
# 기동 시 1회로 충분하지만, 지역은 배치가 갱신하고 규칙은 규칙관리자가 승인한다 —
# 둘 다 **재기동 없이 판정에 보여야** 한다. 그것이 이 제품의 핵심 시연 장면이다.
#
# 그래서 여기에는 캐시가 없다. `lru_cache` 도, 모듈 전역 사본도 두지 않는다. SPEC 2.3 이
# 정한 대로다 — 캐시를 두려면 저장소 갱신에 연동된 무효화가 있어야 하고, 없으면 두지 않는다.
#
# 요청마다 저장소를 새로 여는 이유는 `boot_model_constants` 가 적은 것과 같다:
# `sqlite3` 연결은 만든 스레드에서만 쓸 수 있는데 FastAPI 의 동기 엔드포인트는 워커
# 스레드에서 돈다. 연결을 들고 있으면 스레드가 바뀌는 순간 터진다.

#: 지역 0건은 **판정 입력이 아니라 설정 오류**다 (코디네이터 결정 2026-08-14).
#: 지역은 시드로 들어오는 것이고 0건이면 시딩이 실패한 것이다. 기본값으로 메우면
#: 「출처를 모르는 지역」으로 판정하게 되고 그것은 값을 지어내는 것이다 (Part 0-E #2).
REGIONS_EMPTY_MESSAGE = (
    "저장소에 지역이 0건이라 판정할 수 없습니다. 지역은 시드로 들어오는 데이터이며 "
    "기본값으로 대체하지 않습니다. `python scripts/seed_store.py` 를 먼저 실행하세요."
)


def read_regions(store: Store) -> list[dict]:
    """저장소의 `Region` 을 엔진이 받는 dict 로 만든다. 매번 새로 읽는다.

    변환은 `Region.to_engine_dict()` 하나가 한다 — 필드 대응을 api 가 다시 적으면
    저장소와 엔진 사이에 두 번째 정본이 생긴다.
    """
    return [region.to_engine_dict() for region in read_region_records(store)]


def read_region_records(store: Store) -> list[Region]:
    """`Region` 그대로. 계보(6.1 의 「신선도」)가 필요한 곳이 쓴다.

    `to_engine_dict()` 는 `source`(= `provenance.source_name`) 한 줄로 계보를 접어 버리고,
    상담원에게 보여줄 `verification` · `observed_at` 은 거기서 사라진다.
    """
    return list(store.regions.list())


def read_active_rule_versions(store: Store, at: datetime) -> list[RuleVersion]:
    """SPEC 2.3 — 판정에 참여하는 규칙. **술어를 부르는 자리는 여기 하나다.**

    `active(at)` 는 `status='approved'` 이고 `effective_from <= at < effective_to` 인
    것만 돌려주는 저장소의 유일한 판정용 조회다. **`RuleDraft` 는 어떤 경로로도 여기
    실리지 않는다** — 술어를 api 가 다시 쓰지 않고 그 조회를 그대로 부르는 것이 그
    보장을 지키는 방법이다. `list()` 로 바꾸는 순간 초안·만료 규칙이 판정에 샌다.

    `payload` 가 아니라 `RuleVersion` 을 돌려주는 이유는 6.1 의 내부 정보 때문이다 —
    상담원에게 보여줄 **규칙 버전**(id · origin · 유효기간)이 payload 에는 없다.
    같은 조회의 결과에서 둘을 다 뽑아야 응답의 판정과 계보가 같은 순간을 가리킨다.
    """
    return list(store.rule_versions.active(at))


def read_active_policies(store: Store, at: datetime) -> list[dict]:
    """엔진이 받는 형태 — 위 조회의 `payload` 만 벗겨낸 것이다."""
    return [version.payload for version in read_active_rule_versions(store, at)]


def request_now() -> datetime:
    """이 요청의 시각. **시계를 읽는 곳은 여기 하나다.**

    api 가 읽는다. 엔진은 시계를 건드리지 않고 이 값을 주입받는다 (SPEC 5.3). 쓰이는
    곳은 둘이고 **같은 순간이어야 한다** — 활성 규칙 술어(SPEC 2.3)의 `now` 와 응답의
    `meta.generatedAt`. 두 번 부르면 응답이 「어느 시점 기준의 판정인가」에 두 개의 답을
    갖게 되므로, 엔드포인트는 한 번 불러 변수에 담아 양쪽에 넘긴다.
    """
    return datetime.now(timezone.utc)


def require_regions(store: Store) -> list[Region]:
    """기동 시 1회. 지역이 0건이면 기동을 거부한다 (fail-closed).

    SPEC 5.1.1 의 상수 전수 검사와 **같은 자리·같은 형식**이다. 새 검사 개념을 만들지
    않는다 — 없으면 뜨지 않고, 메시지가 무엇이 없어서 못 뜨는지와 무엇을 하면 되는지를
    말한다.

    이 검사가 기동 이후의 삭제까지 잡지는 못한다. 2.3 때문에 런타임은 매번 새로 읽으므로
    그때는 엔드포인트가 오류 봉투로 답한다 (`REGIONS_EMPTY_MESSAGE`).
    """
    regions = store.regions.list()
    if not regions:
        raise RuntimeError(
            "지역이 없어 기동할 수 없습니다 (설정 오류, fail-closed). "
            "저장소에 Region 이 0개입니다. "
            "저장소가 비어 있다면 `python scripts/seed_store.py` 를 먼저 실행하세요."
        )
    return regions


def boot_require_regions() -> int:
    """기동 시 1회. 저장소를 열어 지역 존재만 확인하고 곧바로 닫는다.

    `boot_model_constants` 와 나란히 선다. 값을 들고 있지 않는 것이 핵심이다 — 여기서
    지역을 떠 두면 그 사본이 곧 프로세스 수명 캐시가 되어 2.3 위반이 검사 자리에서
    되살아난다. 세는 것만 하고 버린다.
    """
    with store_from_env() as store:
        return len(require_regions(store))


boot_require_regions()


def boot_seed_accounts() -> list:
    """기동 시 1회. 상담원·규칙관리자 계정이 없으면 만든다 (SPEC 6.3).

    `boot_model_constants` · `boot_require_regions` 와 같은 자리·같은 형식이다. 다른 점은
    이쪽이 **쓰기**라는 것 하나인데, 그래도 여기 있는 이유는 계정이 없으면 4단계의 어떤
    것도 시연할 수 없기 때문이다. 멱등이므로 재기동이 계정을 초기화하지 않는다.

    비밀번호는 저장소에 커밋되지 않는다 — 환경변수로 주입하거나, 없으면 무작위로 만들어
    **stderr 에 1회만** 출력한다 (`auth.ensure_seed_accounts`).
    """
    with store_from_env() as store:
        return ensure_seed_accounts(store, now=request_now())


boot_seed_accounts()

#: 세션 원장. **프로세스 메모리다** (코디네이터 결정 Q7 — 대가는 `auth.SessionStore` 에 적었다).
SESSIONS = SessionStore()

app = FastAPI(
    title="Home_Compass API",
    version=ENGINE_VERSION,
    description="청년 주거 금융 의사결정 엔진 — 4대 결정론적 엔진 + LLM 상담 레이어",
)

# --------------------------------------------------------------------------
# CORS 미들웨어는 **없다** (SPEC 6.2 — 동일 오리진)
# --------------------------------------------------------------------------
#
# 예선에는 `allow_origins=["*"]` · `allow_credentials=False` 가 있었다. 그 조합은 쿠키
# 세션과 **양립할 수 없다** — 브라우저는 와일드카드 오리진에 자격증명을 실어 보내지 않고,
# 실을 수 있게 고치면 이번에는 아무 사이트나 로그인된 사용자의 세션으로 우리 API 를
# 부를 수 있게 된다. SPEC 6.2 가 그래서 [폐기]라고 적었다.
#
# 대신 `web` · `api` 를 같은 오리진에서 서빙한다. 이 파일 맨 아래의 `StaticFiles` 마운트가
# 그것이고, 그래서 CORS 헤더가 애초에 필요 없다. `admin`(5단계)도 같은 오리진에 붙는다.
# 이것이 CSRF 방어의 절반이기도 하다 (OWASP CSRF CS — 동일 오리진 + 토큰).


# --------------------------------------------------------------------------
# 파일 로그 (SPEC 7.2) — **요청 본문을 찍지 않는다** (SPEC 7.1)
# --------------------------------------------------------------------------
#
# 7.1 의 표가 파일 로그에 거는 규칙은 한 줄이다 —
#   「**파일 로그**(7.2) — 요청 본문을 찍지 않는다. **오류 로그도 예외가 아니다**」
#
# 그 규율을 주석이 아니라 **구조**로 건다. 셋이다.
#
#   (1) 기록자 둘은 `**kwargs` 를 받지 않는다. 실을 수 있는 자리가 인자 목록에만 있고,
#       그 이름들은 아래 `LOG_FIELDS` 로 한 번 더 좁혀진다. 본문을 흘리려면 이 파일을
#       고쳐야 한다 — 실수로는 안 된다.
#   (2) 미들웨어는 `request.body()` 를 **부르지 않는다.** 읽지 않은 것은 샐 수 없다.
#   (3) 예외 경로도 예외의 **타입 이름만** 싣는다. `str(exc)` 를 실으면 검증기가 인용한
#       입력값이 그대로 파일에 남는다 — `_unhandled_handler` 가 응답 본문에 대해 이미
#       같은 규율을 지키고 있고, 파일 로그가 그 규율의 예외가 되면 안 된다.
#
# ★ **경로는 싣고 질의문자열은 싣지 않는다.** 이 API 에 질의문자열을 읽는 엔드포인트가
#   하나도 없으므로 지금은 빈 값이지만, 생기는 날 그것이 본문을 URL 로 옮기는 우회로가
#   된다. 애초에 싣지 않는 편이 [그때 가서 지운다]보다 강하다.
#
# 파수병은 `backend/tests/api/test_log_hygiene.py` 다. 실기동으로 로그를 뜬 뒤 프로필
# 값이 그 안에 있는지 **기계로** 검사한다 — 눈으로 훑는 것은 증거가 아니다.

#: 파일 로그 한 줄에 실릴 수 있는 키 전수. 여기 없는 이름은 파일에 닿지 못한다.
LOG_FIELDS = (
    "at", "event", "method", "path", "status", "durationMs", "error",
    "mode", "outcome", "latencyMs",
)

#: 기록 종류. `http` 는 요청 하나, `llm.chat` 은 프로바이더 호출 하나다.
LOG_EVENT_HTTP = "http"
LOG_EVENT_LLM_CHAT = "llm.chat"

#: 파일에 쓰지 못한 횟수. **삼키지 않는다** — 상태 화면이 이 수를 그대로 보인다.
#: 0 이 아닌 값이 보이면 그 화면의 LLM 지표는 실제보다 적게 세고 있다는 뜻이다.
_LOG_WRITE_FAILURES = 0


def _emit_log(record: dict) -> None:
    """JSONL 한 줄을 덧붙인다. **호출자는 아래 두 기록자뿐이다.**

    허용 키 밖의 이름이 오면 **터진다.** 조용히 버리면 [적었다고 믿는데 안 적힌] 상태가
    되고, 그것은 이 단계가 만들려는 증거를 통째로 무효로 만든다. 이 예외는 사람이 필드를
    더할 때만 나며 그때는 테스트가 먼저 잡는다.
    """
    global _LOG_WRITE_FAILURES
    unknown = sorted(set(record) - set(LOG_FIELDS))
    if unknown:
        raise ValueError(f"파일 로그에 허용되지 않은 필드 (SPEC 7.1): {unknown}")
    path = log_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # 로그를 못 쓴다고 요청을 죽이지 않는다. 대신 **세어서 화면에 내보낸다** —
        # 삼키면 화면이 [호출이 없었다] 와 [적지 못했다] 를 같은 그림으로 그린다.
        _LOG_WRITE_FAILURES += 1


def log_http(*, method: str, path: str, status: int, duration_ms: float,
             error: str | None = None) -> None:
    """요청 하나. **본문도 질의문자열도 받지 않는다** — 인자에 그 자리가 없다."""
    record = {
        "at": request_now().isoformat(),
        "event": LOG_EVENT_HTTP,
        "method": method,
        "path": path,
        "status": status,
        "durationMs": round(duration_ms, 1),
    }
    if error is not None:
        record["error"] = error
    _emit_log(record)


def log_llm_chat(*, mode: str, outcome: str, latency_ms: float) -> None:
    """프로바이더 호출 하나 (SPEC 7.2 「LLM 호출 성공률과 지연」).

    ★ **내용은 인자에 없다.** SPEC 7.1 이 「프로바이더로 나가는 내용은 로컬에 남기지
      않는다」고 적었고, 질문도 답변도 토큰 수도 여기 실리지 않는다. 남는 것은 셋뿐이다 —
      어느 모드로 불렀나 · 성공했나 · 얼마나 걸렸나.

    ★ 이것을 `AuditEvent` 로 남기지 않는 이유. `/api/chat` 은 **익명 경로**다. 감사기록은
      append-only 이고 지우는 경로가 구조상 없으므로, 인증되지 않은 트래픽이 원장을
      무한히 불리게 된다. 감사추적(7.1)과 관측 지표(7.2)는 다른 것이고 SPEC 이 후자에
      **파일 로그**를 배정했다.
    """
    _emit_log({
        "at": request_now().isoformat(),
        "event": LOG_EVENT_LLM_CHAT,
        "mode": mode,
        "outcome": outcome,
        "latencyMs": round(latency_ms, 1),
    })


def read_log_records() -> tuple[list[dict], int]:
    """파일 로그를 읽어 `(해석된 줄, 해석 실패한 줄 수)` 를 낸다.

    깨진 줄을 **세어서 돌려준다.** 조용히 건너뛰면 화면의 분모가 이유 없이 줄고, 그러면
    성공률이 실제보다 좋아 보인다. 파일이 아예 없으면 `([], 0)` 이며 그것은 「호출이
    없었다」가 아니라 「아직 아무것도 안 적혔다」다 — 그 구분은 화면이 진다.
    """
    path = log_file_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], 0
    records: list[dict] = []
    broken = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            broken += 1
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
        else:
            broken += 1
    return records, broken


@app.middleware("http")
async def _observe_request(request: Request, call_next):
    """요청 하나를 파일 로그에 남긴다 (SPEC 7.2).

    ★ 실패 경로가 성공 경로와 **같은 자리**를 지난다. 예외를 잡아 적고 그대로 다시
      던지므로, 500 도 422 도 기록에서 빠지지 않는다 — 오류만 안 남는 로그는 문제가
      없다는 그림을 그린다.
    """
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_http(
            method=request.method,
            path=request.url.path,
            status=500,
            duration_ms=(time.perf_counter() - started) * 1000,
            # 타입 이름만. 메시지에는 입력값이 실릴 수 있다 (SPEC 7.1 「오류 로그도 예외가 아니다」).
            error=type(exc).__name__,
        )
        raise
    log_http(
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    return response


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------

class ProfileRequest(BaseModel):
    age: int = Field(default=28, ge=0, le=120)
    annualIncomeKRW: int = Field(default=0, ge=0, le=100_000_000_000)
    monthlyNetIncomeKRW: int = Field(default=0, ge=0, le=1_000_000_000)
    liquidAssetsKRW: int = Field(default=0, ge=0, le=100_000_000_000)
    existingDebtMonthlyKRW: int = Field(default=0, ge=0, le=1_000_000_000)
    householdSize: int = Field(default=1, ge=1, le=15)
    regionCode: str = Field(default="")
    isHomeless: bool = True
    isNewlywed: bool = False
    isSMEEmployee: bool = False
    preferredType: Literal["jeonse", "monthly", "any"] = "any"


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    message: str = ""
    profile: ProfileRequest = Field(default_factory=ProfileRequest)
    history: list[ChatMessage] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Response models — **문서 전용이다** (D-12)
# --------------------------------------------------------------------------
#
# `response_model=` 로 걸지 않고 `responses={...: {"model": ...}}` 로만 건다. 전자는
# 런타임에 응답을 걸러내므로 판정 숫자·필드가 바뀔 수 있고, 그것은 골든 스냅샷과
# 1-① 완료 기준("판정 숫자가 이전과 동일")에 정면으로 걸린다. 이 모델들이 하는 일은
# 계약 파일에 스키마를 싣는 것 하나다.
#
# `extra="forbid"` 인 이유 — 계약에 없는 필드가 응답에 실리면 스모크가 잡아야 한다.
# 응답 스키마가 빈 객체면 SPEC 9.1.2 의 "2xx 만으로는 불합격"이 이름만 남는다.

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(_Strict):
    code: str
    message: str


class ErrorEnvelope(_Strict):
    """모든 4xx·5xx 가 이 형태다 (SPEC 8.1 — 오류 봉투도 계약이다)."""

    error: ErrorBody


class HealthBatch(_Strict):
    """SPEC 8.1 배치 상태 — **마지막 실행의 성공/실패와 그 시각뿐이다.**

    실행 식별자(`after.runId`) · 오류 본문 · 대상 지역 목록은 **싣지 않는다.**
    `/api/health` 는 익명 경로이고, 운영 정보를 익명에 여는 것은 최소여야 한다.
    전수(실행 횟수 · 성공률 · 분모 문장)는 `rule_manager` 전용
    `/api/admin/status` 의 `batch` 가 계속 진다 (SPEC 7.2).
    """

    lastRunAt: str | None
    lastOutcome: str | None


class HealthFreshness(_Strict):
    """SPEC 8.1 데이터 신선도 — **요약 하나뿐이다.**

    필드별 계보와 `provenance` 전문은 `/api/analyze` 의 몫이다 (D-13). 여기 오지 않는다.

    ★ **`fetched_at` 이 아니라 `observed_at` 이다.** 취득 시각은 바로 위
      `batch.lastRunAt` 이 이미 말한다 — 신선도 칸이 그것을 다시 말하면 두 칸이 같은
      사실을 두 번 말하면서 **데이터가 언제 시점의 것인지는 아무도 말하지 않게** 된다.
      (`/api/admin/status` 의 7.2 신선도는 `oldestFetchedAt` 그대로다. 그 계약은
      건드리지 않았다 — 두 화면이 서로 다른 것을 묻고 있으므로 다른 값이 맞다.)

    **판정하지 않는다.** 며칠부터 stale 인지가 미정이므로(SPEC 2.4 · 계약 결정 #39)
    등급도 임계도 여기 실리지 않는다.
    """

    oldestObservedAt: str | None


class HealthResponse(_Strict):
    status: str
    llm: str

    #: SPEC 8.1 이 이름으로 지시한 추가 둘. **순수 추가다** — `status` · `llm` 은 이름도
    #: 뜻도 그대로이며, `status` 는 여전히 [프로세스가 살아 있다] 이지 데이터 상태가 아니다.
    #:
    #: **블록 자체가 `null` 이면 저장소를 읽지 못한 것**이고, 블록 **안**의 `null` 은
    #: [읽었으나 아직 없다] 다. 두 사실을 한 값으로 뭉치지 않는다.
    #:
    #: `dataGrade` 는 **여기 없다.** 등급은 판정에 쓰인 사실에 걸리는 것이고
    #: `/api/health` 에는 판정이 없다 (코디네이터 경계).
    batch: HealthBatch | None
    freshness: HealthFreshness | None


class MetaResponse(_Strict):
    engineVersion: str
    llm: str
    disclaimer: str


class RegionRef(_Strict):
    code: str
    name: str
    jeonseMedianKRW: int
    monthlyDepositKRW: int
    monthlyRentKRW: int
    maintenanceFeeKRW: int
    jeonseRatioPct: float
    source: str


class RegionsResponse(_Strict):
    regions: list[RegionRef]


class AffordabilityBreakdown(_Strict):
    netIncome: int
    livingCost: int
    existingDebt: int
    buffer: int


class Affordability(_Strict):
    maxMonthlyHousingCostKRW: int
    recommendedMonthlyHousingCostKRW: int
    #: SPEC 5.2.1 — `schwabeIndexPct` 는 **여기 없다.** 1-③ 이 `scenarios[]` 로 옮겼다
    #: (SPEC 8.1 이 명시한 「이미 확정된 예외 1건」). 대체 필드도 두지 않는다 —
    #: 권장액의 소득 대비 비율은 `recommendedMonthlyHousingCostKRW / breakdown.netIncome`
    #: 으로 재현되며, 둘 다 이 스키마에 있다.
    band: Literal["safe", "caution", "risk"]
    breakdown: AffordabilityBreakdown
    rationale: list[str]


class ScenarioComponents(_Strict):
    interest: int
    rent: int
    maintenance: int
    opportunityCost: int
    insurance: int


class Scenario(_Strict):
    id: str
    label: str
    type: Literal["jeonse", "monthly"]
    depositKRW: int
    monthlyRentKRW: int
    loanAmountKRW: int
    loanRatePct: float
    monthlyEquivalentCostKRW: int
    tco5yKRW: int
    npv5yKRW: int
    components: ScenarioComponents
    fitScore: int
    #: SPEC 5.2.1 F-1 — 이 시나리오의 월환산비용 ÷ 월 실수령액. **측정값이다.**
    #: 상한이 없다 (SPEC 5.3 은 `0 <=` 만 남겼다) — 주거비가 소득을 넘는 시나리오가
    #: 실재하므로 0~100 척도를 전제하는 소비자는 표시 방식을 함께 바꿔야 한다.
    schwabeIndexPct: float | None = Field(
        description=(
            "이 시나리오의 월환산비용 ÷ 월 실수령액(퍼센트 포인트). "
            "**월 실수령액이 0이면 이 비율은 정의되지 않으므로 `null` 이다.** "
            "0.0 과 `null` 은 다른 사실이다 — 0.0 은 「주거비가 0이다」이고 "
            "`null` 은 「소득이 없어 잴 수 없다」다. 소비자는 `null` 을 0으로 "
            "대체하지 않는다."
        )
    )
    verdict: Literal["affordable", "stretch", "unaffordable"]
    rationale: list[str]


class Policy(_Strict):
    id: str
    name: str
    #: 정책 데이터가 정하는 값이라 열거하지 않는다 — 새 제도가 들어오면 늘어난다.
    category: str
    status: Literal["eligible", "conditional", "ineligible"]
    reasons: list[str]
    #: `reasons` 중 **이 정책을 떨어뜨린 것들**. `reasons` 의 부분집합이며 원문 그대로다.
    #:
    #: 왜 별도 필드인가 — 화면이 충족 사유와 미충족 사유를 갈라 그리려면 그 구분이
    #: **계약에 있어야** 한다. 없으면 프런트가 사유 문자열에서 「미충족」을 찾는 수밖에
    #: 없고, 그것은 SPEC 5.3(문자열은 계약이 아니다)이 금지한 결합이다 — 문구를 한 번
    #: 다듬으면 시민 화면이 조용히 깨진다.
    #:
    #: 기본값이 빈 배열인 이유는 이 필드를 **추가하는 변경과 채우는 변경을 나누기**
    #: 위해서다 (SPEC 8.2 #5 — 계약 변경은 코디네이터만). 엔진이 아직 안 실어도
    #: 계약은 성립하고 CI 는 초록이다.
    failures: list[str] = []
    maxAmountKRW: int
    rateRangePct: list[float]
    source: str
    disclaimer: str


class RiskFactor(_Strict):
    name: str
    valuePct: float
    impact: Literal["low", "medium", "high"]
    note: str


class Risk(_Strict):
    score: int
    band: Literal["low", "medium", "high"]
    factors: list[RiskFactor]
    rationale: list[str]


class AnalyzeMetaRegion(_Strict):
    code: str
    name: str


class AnalyzeMeta(_Strict):
    #: SPEC 2.1 — 이 필드만 `Z` 표기다. Provenance 의 시각 표기와 별개 필드다.
    generatedAt: str
    engineVersion: str
    region: AnalyzeMetaRegion
    disclaimer: str


# --------------------------------------------------------------------------
# 내부 정보 (SPEC 6.1 · Part 0-E #1) — **부가 필드이지 별도 스키마가 아니다**
# --------------------------------------------------------------------------
#
# `/api/analyze` 는 역할에 따라 스키마가 갈리지 않는다. 갈랐다면 같은 판정을 두 번
# 계산하게 되고 둘이 어긋날 수 있다 — 그것이 Part 0-A 에 기록된 실패 유형이다.
#
# 아래 셋은 전부 **저장소에서 그대로 꺼낸 값**이다. 판정을 다시 하지 않는다. 그래서
# `engines/` 는 이 단계에서 한 줄도 바뀌지 않았고, **익명 응답은 바이트 동일**이다.

class InternalRuleVersion(_Strict):
    """이 판정에 참여한 승인 규칙 (SPEC 6.1 「규칙 버전」).

    상담원이 [지금 이 답이 어느 버전 규칙으로 나온 것인가] 를 말할 수 있게 하는 값이다.
    `status='approved'` 인 것만 실린다 — 판정에 참여한 것이 곧 이 목록이기 때문이다.
    """

    policyId: str
    ruleVersionId: str
    origin: str
    effectiveFrom: str | None
    effectiveTo: str | None


class InternalFreshness(_Strict):
    """판정에 쓰인 지역 시세의 계보 (SPEC 6.1 「신선도」).

    `Region` 의 **레코드 단위 요약**이며 필드별 계보의 최악값이다 (SPEC 2.4).
    공개 응답의 `regions[].source` 는 화면 문구용 한 줄이라 `verification` 이 없다.
    """

    regionCode: str
    verification: str
    observedAt: str | None
    fetchedAt: str | None


class InternalIneligiblePolicy(_Strict):
    """부적격·조건부 정책의 **문턱** (SPEC 6.1 「부적격 상세」).

    ★ `reasons` 를 다시 싣지 않는다 (코디네이터 결정 Q6). 그것은 이미 공개 응답의
      `policies[].reasons` 에 있다. 내부 정보의 값은 [왜 안 됐는지] 가 아니라
      **[문턱이 얼마인지]** 다 — 상담원이 고객 앞에서 [연소득 때문에 안 됩니다] 가 아니라
      [3,000만원이 문턱인데 4,200만원이십니다] 를 말할 수 있게 하는 것이 6.1 이 상담원에게
      내부 정보를 주는 이유다.

    `criteria` 를 열거하지 않고 불투명 객체로 두는 이유는 정본이 하나여야 하기 때문이다 —
    그 모양은 `contracts/rule_draft.schema.json` 과 규칙 payload 가 정하고, 여기서 다시
    적으면 세 번째 정본이 생긴다.
    """

    policyId: str
    status: str
    criteria: dict


class AnalyzeInternal(_Strict):
    ruleVersions: list[InternalRuleVersion]
    dataFreshness: InternalFreshness
    ineligiblePolicies: list[InternalIneligiblePolicy]


# --------------------------------------------------------------------------
# 계보 · 데이터 등급 (SPEC 2.1 · 2.4 · D-13) — **역할과 무관한 최상단 필드다**
# --------------------------------------------------------------------------
#
# `internal` 과 반대 칸이다. 내부 정보는 상담원에게만 보이지만 계보는 **시민이 받는다** —
# D-5 가 "거부하지 않고 등급을 붙인다"고 한 것이 그 뜻이고, 등급을 시민에게 감추면
# 남는 것은 출처 없는 숫자뿐이다.

class ProvenanceRecord(_Strict):
    """SPEC 2.1. 정본은 `contracts/provenance.schema.json` 이며 이 모델은 그 거울이다.

    필드를 늘리거나 줄이지 않는다. 좁은 제약(분류별 필수 여부 · `our_choice` 는
    `normative` 전용)은 계약 스키마가 걸고 저장 시점에 이미 통과했으므로 여기 다시 쓰지
    않는다 — 두 벌을 쓰면 그 둘이 갈라진다.
    """

    source_kind: Literal["statute", "statistic", "market", "normative"]
    source_name: str | None
    source_ref: str | None
    observed_at: str | None
    fetched_at: str | None
    verification: Literal["verified", "unverified", "stale", "our_choice"]
    #: **값이 없으면 키도 없다** (`store.Provenance.OMITTED_WHEN_UNSET`). `null` 로 채우면
    #: 저장소가 내보내는 6키 레코드와 계약이 어긋난다.
    observed_at_unstated: Literal[True] | None = None


class ProvenanceItem(_Strict):
    """계보 배열의 한 항목 — **사실 하나**다 (D-13).

    `provenance` 를 통째로 중첩하는 이유는 계약 결정 #34 다. 생성물의 계보와 **같은
    모양**이어야 화면이 하나의 렌더러로 양쪽을 그린다. 평평하게 펴면 그 순간 응답의
    계보와 생성물의 계보가 다른 물건이 된다.
    """

    fact: str = Field(description="사람이 읽는 사실 이름. 기계 판독은 `factKind` 와 `provenance` 로 한다.")
    factKind: Literal["region_field", "rule_version", "model_constant"] = Field(
        description=(
            "데이터(D-5)와 모델 상수(Part 0-C)는 **같은 배열**에 들어간다 (D-13). "
            "구분은 이 필드와 `provenance.source_kind` 가 진다."
        )
    )
    provenance: ProvenanceRecord
    targets: list[str] = Field(
        description=(
            "이 사실이 근거짓는 **응답 위치**의 JSON Pointer 목록 (RFC 6901 · SPEC 2.1). "
            "좁게 특정할 수 없는 곳은 그 부분트리를 가리킨다."
        )
    )


class DataGradeReason(_Strict):
    """등급 사유 하나. **원인 유형을 구분해 담는다** (SPEC 2.4).

    한 글자 등급으로 뭉치면 대응 주체의 구분이 사라진다 — `unverified`·`stale` 은 배치가,
    `pending_review` 는 규칙관리자가 푼다.
    """

    type: Literal["unverified", "stale", "pending_review", "freshness_not_evaluated"]
    #: 이 사유를 만든 사실의 `provenance` 배열 인덱스. **사실에 걸리지 않는 사유는
    #: `null`** 이다 — `freshness_not_evaluated` 는 특정 사실의 결함이 아니라 판정 자체가
    #: 서지 않은 상태이므로 어느 한 항목을 가리키면 거짓이 된다.
    provenanceIndex: int | None
    fact: str | None
    message: str


class DataGrade(_Strict):
    """SPEC 2.4 — 등급값 + 사유 목록. 산정 대상은 `verification != our_choice` 다."""

    grade: Literal["A", "B", "C"] | None = Field(
        description=(
            "`C` > `B` > `A` — 가장 나쁜 것이 이긴다 (SPEC 2.4). "
            "**`null` 은 「등급을 산정할 수 없다」이지 「문제 없음」이 아니다.** "
            "2.4 의 `A` 는 「입력 전부 `verified` **이며** 신선도 기준 이내」라는 두 조건의 "
            "곱인데 신선도 임계가 아직 없어 뒤 절이 확정되지 않는다. 확정되지 않은 것을 "
            "참으로 읽어 `A` 를 내면 그것이 낙관적 등급이다. `null` 일 때 그 이유는 "
            "`reasons` 에 `freshness_not_evaluated` 로 **반드시** 실린다 — 사유 없는 "
            "`null` 은 소비자에게 「깨끗함」으로 읽힌다."
        )
    )
    reasons: list[DataGradeReason]


class AnalyzeResponse(_Strict):
    affordability: Affordability
    scenarios: list[Scenario]
    policies: list[Policy]
    risk: Risk
    summary: str
    meta: AnalyzeMeta
    #: D-13 — 최상단 배열. 사실 단위다. `policies[].source` · `meta.disclaimer` 와
    #: **병존**하며, 그쪽은 화면 문구이고 **기계 판독의 정본은 이쪽**이다.
    provenance: list[ProvenanceItem]
    dataGrade: DataGrade
    #: SPEC 6.1 · Part 0-E #1 — **인증된 요청에만 채워지는 부가 필드.**
    #: 익명 응답에는 이 키가 아예 없다(`null` 이 아니라 부재다). 그 사실을 권한
    #: 테스트가 고정한다 (SPEC 9.2 #3 · 10.2 4단계).
    internal: AnalyzeInternal | None = Field(
        default=None,
        json_schema_extra={"x-requires-role": "counselor"},
        description=(
            "규칙 버전 · 신선도 · 부적격 상세 (SPEC 6.1). **인증된 요청에만 실린다.** "
            "익명 응답에는 이 키가 존재하지 않는다 — `null` 과 부재는 다른 사실이다. "
            "`x-requires-role` 의 값은 이 필드를 받는 **가장 낮은 역할**이며, "
            "상위 역할(rule_manager)도 함께 받는다."
        ),
    )


class ChatToolCall(_Strict):
    tool: str
    args: dict
    resultSummary: str


class ChatResponse(_Strict):
    reply: str
    toolCalls: list[ChatToolCall]
    mode: str
    provider: str


# --------------------------------------------------------------------------
# 인증·관리 스키마 (SPEC 8.1 신규 엔드포인트)
# --------------------------------------------------------------------------

class SessionResponse(_Strict):
    """현재 세션. 익명이어도 200 이고 `authenticated=false` 다.

    익명에 401 을 주지 않는 이유는 이 엔드포인트의 용도가 [로그인했는가] 를 묻는 것이기
    때문이다. 물음에 401 로 답하면 화면이 [모름] 과 [아님] 을 구분하지 못한다.
    """

    authenticated: bool
    username: str | None
    role: str | None
    #: 상태변경 요청의 `X-CSRF-Token` 헤더에 실을 값. 쿠키로도 같은 값이 나간다
    #: (double-submit). 세션 쿠키와 달리 이쪽은 JS 가 읽어도 되는 값이다.
    csrfToken: str | None


class LogoutResponse(_Strict):
    ok: bool
    message: str


class DraftRef(_Strict):
    """`RuleDraft` 요약. `payload` 는 싣지 않는다 — 검토 화면은 5단계다."""

    id: str
    policyId: str
    policySourceId: str
    status: str
    createdAt: str
    failureReason: str | None


class DraftListResponse(_Strict):
    drafts: list[DraftRef]


# --- 검토 화면의 재료 (SPEC 4.4) --------------------------------------------

class SourceSegment(_Strict):
    """원문의 한 조각. **이어 붙이면 `PolicySource.text` 와 같아야 한다.**

    ★ 오프셋 산술은 서버에 있다 (코디네이터 결정 2026-08-14). SPEC 4.2.1 이 span 단위를
      **코드포인트**로 못박았는데 JS 문자열 인덱스는 UTF-16 코드유닛이라 화면이 직접
      자르면 단위 변환이 끼어든다. 이 저장소에는 JS 실행 하네스가 없어(결정 #31 — CI 는
      파이썬 전용) 그 변환을 검증할 수 없다. 검증할 수 없는 변환은 두지 않는다.
    """

    text: str
    #: 이 조각을 근거로 삼는 필드들. **배열인 이유는 겹침 때문이다** — 한 구간이 두
    #: 필드의 근거일 수 있고, 포함 관계일 수도 있다. 비어 있으면 어떤 근거도 아니다.
    fieldPaths: list[str]


class SourceView(_Strict):
    """검토자가 보는 원문. 계약 결정 #17 — **출처표시가 화면까지 전달**되어야 한다."""

    id: str
    sourceRef: str | None
    attribution: str | None
    fetchedAt: str | None
    #: 코드포인트 수. 바이트도 UTF-16 코드유닛도 아니다 (SPEC 4.2.1).
    length: int
    segments: list[SourceSegment]


class SpanView(_Strict):
    fieldPath: str
    start: int
    end: int
    #: `text[start:end]` 을 저장소가 되살린 것 (SPEC 4.2.1). 인용은 저장되지 않는다.
    quote: str
    #: 이 인용이 원문에 몇 번 나타나는가. 2 이상이면 **어느 조항에서 나온 근거인지가
    #: 확정되지 않았다** — `extraction_verify` 가 이 수를 세면서 [대조 표시가 지어지는
    #: 5단계에 정할 문제]로 남겨 둔 것이다. 실패시키지 않고 검토자에게 보인다.
    occurrences: int
    ambiguous: bool


class FieldChange(_Strict):
    """필드 하나의 변경 (SPEC 4.4 #3). **병합 규칙과 같은 것을 말한다.**"""

    path: str
    label: str
    #: `draft` = 초안이 덮을 수 있는 필드 / `inherited` = 표시 전용이라 물려받는 필드.
    origin: Literal["draft", "inherited"]
    mergeMode: Literal["key_merge", "replace", "inherit_only"]
    #: 초안이 이 자리에 대해 **무엇을 말했는가**. `not_found`(모름)와 `explicit_null`
    #: (없음)이 갈리는 자리이며, 둘을 구분해 보이지 않으면 검토자가 가를 수 없다.
    draftSaid: Literal["value", "explicit_null", "not_found", "silent", "not_applicable"]
    changed: bool
    before: object | None
    beforePresent: bool
    after: object | None
    afterPresent: bool
    #: 통째 교체가 이전 목록을 **전부 지우는가.** `criteria` 의 키 단위 병합과 다른 사실이다.
    wipesPrevious: bool
    evidence: SpanView | None
    #: 이 필드에 근거 구간이 **있어야 하는가.** `not_found` 는 없어야 정상이므로
    #: (SPEC 4.2.2) 화면이 그것을 「누락」으로 그리지 않게 한다.
    evidenceExpected: bool
    note: str
    #: `/conditionalChecks` 에만 있다 — 근거가 항목마다 붙기 때문이다.
    evidenceItems: list[SpanView | None] | None = None


class CurrentRuleVersion(_Strict):
    ruleVersionId: str
    policyId: str
    origin: str
    effectiveFrom: str | None
    effectiveTo: str | None
    payload: dict


class DraftDetail(_Strict):
    id: str
    policyId: str
    policySourceId: str
    status: str
    createdAt: str
    failureReason: str | None
    #: 추출된 규칙 본문 그대로. 계약은 `contracts/rule_draft.schema.json` 이다.
    payload: dict
    notFound: list[str]


class DraftDetailResponse(_Strict):
    """SPEC 4.4 의 ①②③ 중 #1 · #3 을 이 하나가 진다. #2 는 `/impact` 다."""

    draft: DraftDetail
    source: SourceView | None
    spans: list[SpanView]
    current: CurrentRuleVersion | None
    #: 승인하면 쓰일 payload. **저장하지 않는다** — 승인은 아직 일어나지 않았다.
    merged: dict
    #: SPEC 4.3 — ① 신규 제도 신설 / ② 요건 변경. ③ 경량 검토는 만들지 않았다
    #: (Part 10: 판별 규칙이 확정되기 전에는 모든 변경을 ①/② 절차로 처리한다).
    changeType: Literal["new", "requirement_change"]
    fields: list[FieldChange]
    #: ★ SPEC 6.4 의 **잠정** 병합 — 같은 정책을 겨눈 현장 신고를 초안의 **컨텍스트**로
    #: 첨부한다. 검토자는 「기계가 이렇게 추출했고, 현장에서는 이런 문제가 보고됐다」를
    #: 함께 본다. 병합해도 두 `AuditEvent` 는 각각 독립적으로 남는다 — 여기 실리는 것은
    #: 화면 조립이지 기록의 통합이 아니다.
    reports: list[ReportRef]
    #: 이 화면이 **할 수 없는 것.** 없는 기능을 있는 것처럼 그리지 않기 위해 상시 실린다.
    limitations: list[str]


class ImpactChange(_Strict):
    path: str
    before: object | None
    after: object | None


class ProfileImpact(_Strict):
    id: str
    #: 이 프로필이 여는 분기 (`contracts/regression_profiles.json` 의 `axes`).
    #: [무엇을 재는 프로필인가]가 없으면 12줄의 표는 판단 근거가 못 된다.
    axis: str
    changed: bool
    changes: list[ImpactChange]
    policyBefore: dict | None
    policyAfter: dict | None
    #: 판정을 **못 잰** 프로필의 사유. `unknown_region` 축이 여기 걸린다 (SPEC 9.2.2).
    #: 숨기지 않는다 — 조용히 빼면 검토자는 전 건을 다 봤다고 믿는다.
    errorBefore: str | None
    errorAfter: str | None


class ImpactResponse(_Strict):
    """SPEC 4.4 #2 — 승인 시 판정이 어떻게 바뀌는지의 실제 사례.

    모집단은 `contracts/regression_profiles.json` 이다 (SPEC 9.2.2). 7.1 이 시민 프로필
    저장을 금지하므로 실사용 데이터는 애초에 쓸 것이 없다.
    """

    draftId: str
    policyId: str
    profileSetVersion: str
    profileCount: int
    changedCount: int
    mergedPayload: dict
    profiles: list[ProfileImpact]


class DecisionResponse(_Strict):
    """승인·반려의 결과. `ruleVersionId` 는 반려면 `null` 이다."""

    draftId: str
    decision: str
    ruleVersionId: str | None
    approvalRecordId: str
    at: str


class BatchDecisionResponse(_Strict):
    """일괄 승인의 결과 (SPEC 4.5 · 4.6).

    `results` 가 **건별**이다 — 묶었다고 하나로 합치지 않는다. 원자성은 반영에 걸리므로
    이 응답이 200 이면 목록 전체가 반영된 것이고, 하나라도 실패했으면 이 응답 자체가
    나오지 않는다.
    """

    decision: str
    at: str
    results: list[DecisionResponse]


class ReportRef(_Strict):
    """이상 신고 하나 (SPEC 6.4 · 계약 결정 #38). **`DraftRef` 와 별개 스키마다.**

    합치지 않는 이유가 곧 6.4 의 요구다 — 큐에서 **별도 유형**으로 보여야 하고, 초안에
    걸리는 것(payload · span · 상태 전이)이 신고에는 하나도 없다.
    """

    id: str
    #: 신고자. 익명은 없다 (SPEC 6.4).
    reporter: str
    at: str
    targetKind: Literal["policy", "region"]
    targetId: str
    targetField: str
    #: 자유 입력. 규칙관리자가 읽어야 하는 내용 전부다.
    reason: str
    status: str
    #: ★ SPEC 6.4 의 **잠정** 병합 규칙. 대상 정책이 같은 `pending` 초안이 있으면 그
    #: 초안과 하나의 검토 항목으로 묶인다(신고는 초안의 **컨텍스트**가 된다). 비어 있으면
    #: 신고 단독 항목으로 큐에 남는다.
    #:
    #: **목록인 이유** — 같은 정책을 가리키는 `pending` 초안이 둘일 수 있다(일괄 승인이
    #: 그 조합을 409 로 거부하는 것이 그 상태가 실재한다는 뜻이다). 하나만 싣고 나머지를
    #: 버리면 화면이 [신고가 붙지 않은 초안]을 보여 주게 된다.
    mergedDraftIds: list[str]


class ReportListResponse(_Strict):
    reports: list[ReportRef]


class AuditEventRef(_Strict):
    id: str
    actor: str
    at: str
    action: str
    target: str
    outcome: str
    before: dict | None
    after: dict | None


class AuditListResponse(_Strict):
    events: list[AuditEventRef]


# --- 7.2 관측 지표 ----------------------------------------------------------
#
# ★ **없는 값을 0 으로 채우지 않는다.** 「0% 실패율」과 「아직 한 번도 안 돌았다」는 다른
#   사실이고, 0 으로 그리면 화면이 [문제 없음]을 말한다. 그래서 비율·기간 필드는 전부
#   `| None` 이고, 분자·분모가 될 **관측된 건수**만 정수다.
#
# ★ **판정선을 만들지 않는다.** 추출 실패율에는 합격선이 없고(계약 결정 #33), 신선도에는
#   임계가 없고(결정 #39), 대기 큐에는 SLA N 이 없다(SPEC 7.3). 셋 다 노출만 한다.

class StatusLatency(_Strict):
    """지연 분포. 표본이 0 이면 값이 아니라 `null` 이다."""

    samples: int
    p50: float | None
    max: float | None
    unit: str


class StatusBatch(_Strict):
    """SPEC 7.2 배치 성공률. **분모를 화면 옆에 적는다** (코디네이터 지시)."""

    runs: int
    succeeded: int
    failed: int
    successRatePct: float | None
    lastRunAt: str | None
    lastOutcome: str | None
    denominator: str


class StatusFreshness(_Strict):
    regions: int
    oldestFetchedAt: str | None
    newestFetchedAt: str | None
    oldestAgeDays: float | None
    verification: dict[str, int]
    thresholdEvaluated: bool
    note: str


class StatusLlmChannel(_Strict):
    calls: int
    succeeded: int
    failed: int
    successRatePct: float | None
    latency: StatusLatency
    source: str


class StatusLlm(_Strict):
    chat: StatusLlmChannel
    extraction: StatusLlmChannel


class StatusExtraction(_Strict):
    drafts: int
    failed: int
    failureRatePct: float | None
    codes: dict[str, int]
    passLine: None
    note: str


class StatusQueue(_Strict):
    pending: int
    oldestPendingAt: str | None
    longestWaitDays: float | None
    overdue: None
    overdueNote: str


class StatusReports(_Strict):
    open: int
    total: int
    oldestOpenAt: str | None
    longestOpenDays: float | None
    note: str


class StatusLog(_Strict):
    path: str
    exists: bool
    records: int
    unreadableLines: int
    writeFailures: int


class StatusResponse(_Strict):
    generatedAt: str
    batch: StatusBatch
    freshness: StatusFreshness
    llm: StatusLlm
    extraction: StatusExtraction
    queue: StatusQueue
    reports: StatusReports
    log: StatusLog


# --- 요청 스키마 ------------------------------------------------------------
#
# `_Strict` 를 쓰지 않는다. 받는 것에는 관대한 쪽이 맞다는 기존 규약 그대로다
# (`test_request_schemas_stay_lenient` 가 기존 요청 스키마에 걸어 둔 것과 같은 이유).

class LoginRequest(BaseModel):
    username: str = Field(default="", max_length=200)
    #: 길이 상한이 있는 이유는 Argon2id 가 **일부러 느리기** 때문이다. 상한이 없으면
    #: 거대한 본문 하나로 CPU 를 태울 수 있고, 그것이 인증 엔드포인트의 통상적 남용 경로다.
    password: str = Field(default="", max_length=1024)


class DecisionRequest(BaseModel):
    #: 반려는 사유가 **필수**다 (SPEC 10.2 5단계 · 저장소 CHECK 제약). 승인은 선택이다.
    reason: str | None = Field(default=None, max_length=2000)


class BatchApproveRequest(BaseModel):
    """일괄 승인 요청 (SPEC 4.5).

    **건수 상한을 두지 않는다.** 상한은 (d) 규범적 선택이라 `ModelConstant` 에 Provenance
    와 함께 등재돼야 하는데(Part 0-C), 그 값을 뒷받침할 준거가 없다. 근거 없는 숫자를
    코드에 박는 대신 두지 않는 쪽을 골랐다 — 결정 #33 이 추출 성공률 합격선에 대해 내린
    것과 같은 규율이다.
    """

    draftIds: list[str] = Field(default_factory=list)
    #: 일괄 승인의 사유는 **선택**이다. 반려만 필수다 (저장소 CHECK 제약). 적으면 목록의
    #: 모든 `ApprovalRecord` 에 같은 사유가 실린다 — 건별로 다른 사유가 필요하면 그것은
    #: 묶어서 볼 일이 아니므로 단건 승인으로 간다.
    reason: str | None = Field(default=None, max_length=2000)


class ReportRequest(BaseModel):
    """이상 신고 (SPEC 6.4).

    ★ **대상을 자유 텍스트로 받지 않는다** (SPEC 7.1 · 계약 결정 #38). `targetKind` 와
      `targetField` 는 닫힌 목록이고, 그 목록의 정본은 저장소다 — 여기서 `Literal` 로
      다시 적으면 목록이 두 벌이 되고 한쪽만 늘어날 때 조용히 어긋난다. 그래서 타입은
      느슨하게 두고(받는 것에는 관대하게), 판정은 `_report_target_error()` 한 곳이 한다.

    `reason` 의 길이 상한은 자유 입력에 거는 유일한 기계적 제약이다. 내용은 막을 수
    없다 — 그 사실을 숨기지 않는다 (계약 결정 #38 의 마지막 문단).
    """

    targetKind: str = Field(default="", max_length=32)
    targetId: str = Field(default="", max_length=200)
    targetField: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=2000)


_JSON_ERROR = {"model": ErrorEnvelope, "description": "오류 봉투 (SPEC 8.1)"}


# --------------------------------------------------------------------------
# Error envelope — every 4xx/5xx follows {"error": {"code", "message"}}
# --------------------------------------------------------------------------

def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
    return _error(
        422, "validation_error", f"입력값이 올바르지 않습니다 ({field}): {first.get('msg', '')}"
    )


@app.exception_handler(StarletteHTTPException)
async def _http_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return _error(exc.status_code, f"http_{exc.status_code}", detail)


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    return _error(
        500, "internal_error", f"서버 내부 오류가 발생했습니다: {type(exc).__name__}"
    )


# --------------------------------------------------------------------------
# 인증·권한 배선 (SPEC 6.1 · 6.3)
# --------------------------------------------------------------------------
#
# **권한 검사는 여기서 한다.** 화면에서 버튼을 숨기는 것으로 대신하지 않는다 (SPEC 6.1).
# 그래서 아래 `authorize()` 는 화면이 무엇을 보여주는지 전혀 모른다 — 세션과 역할만 본다.

@app.exception_handler(AuthError)
async def _auth_error_handler(request: Request, exc: AuthError):
    """거부도 계약이다 — 오류 봉투를 그대로 쓴다 (SPEC 8.1)."""
    return _error(exc.status, exc.code, exc.message)


def session_timeouts() -> tuple[int, int]:
    """(유휴, 절대) 초. **이 파일에 숫자가 없다** — 값은 `ModelConstant` 가 갖는다.

    키가 저장소에 없으면 기동이 이미 거부됐다 (`load_model_constants`). 그러므로 여기서
    `KeyError` 를 방어하지 않는다 — 방어하면 그 자리가 곧 런타임 기본값이 된다.
    """
    return (
        MODEL_CONSTANTS[SESSION_IDLE_TIMEOUT_KEY],
        MODEL_CONSTANTS[SESSION_ABSOLUTE_TIMEOUT_KEY],
    )


def resolve_session(request: Request, *, now: datetime):
    """쿠키에서 세션을 찾는다. 유휴 시계는 이 호출에서 갱신된다."""
    idle, absolute = session_timeouts()
    return SESSIONS.resolve(
        request.cookies.get(SESSION_COOKIE_NAME),
        now=now,
        idle_timeout_seconds=idle,
        absolute_timeout_seconds=absolute,
    )


def _record_denial(store: Store, *, actor: str, at: datetime, action: str, code: str) -> None:
    """SPEC 7.1 필수 기록 — **권한 거부**.

    거부가 조용하면 SoD 는 증명되지 않는다. 상담원이 승인을 시도했다는 사실 자체가
    감사 대상이며, 그것이 남지 않으면 [아무도 시도한 적 없다] 와 [시도했지만 막혔다] 가
    사후에 구분되지 않는다.

    `after` 에 요청 본문을 넣지 않는다 (SPEC 7.1 의 표). 거부 사유 코드 하나면 충분하다.
    """
    record(
        store,
        actor=actor,
        at=at,
        action=AUDIT_DENIED,
        target=action,
        outcome="denied",
        after={"reason": code},
    )


def authorize(
    request: Request,
    action: str,
    *,
    now: datetime,
    store: Store,
    require_csrf: bool = False,
) -> Session:
    """`action` 을 이 요청이 할 수 있는가. 아니면 `AuthError` 를 던진다.

    순서가 곧 의미다 — **인증(401) -> 권한(403) -> CSRF(403)**. 권한을 CSRF 보다 먼저
    보는 이유는 거부의 정직성이다. 상담원이 승인 API 를 치면 돌아와야 할 답은 [토큰이
    없다] 가 아니라 [권한이 없다] 이고, 순서를 뒤집으면 SoD 거부가 CSRF 오류로 가려진다.
    """
    lookup = resolve_session(request, now=now)
    if lookup.session is None:
        error = unauthenticated_error(lookup.reason, action=action)
        _record_denial(store, actor=ANONYMOUS_ACTOR, at=now, action=action, code=error.code)
        raise error

    session = lookup.session
    if not allows(action, session.role):
        error = forbidden_error(action)
        _record_denial(store, actor=session.username, at=now, action=action, code=error.code)
        raise error

    if require_csrf and not csrf_matches(session, request.headers.get(CSRF_HEADER_NAME)):
        error = csrf_error(action)
        _record_denial(store, actor=session.username, at=now, action=action, code=error.code)
        raise error

    return session


def _set_session_cookies(response: JSONResponse, session: Session) -> JSONResponse:
    """세션 쿠키 + CSRF 쿠키.

    **`max_age` 를 걸지 않는다.** 만료의 정본은 서버의 세션 원장이고, 쿠키에 수명을 적으면
    같은 사실이 두 곳에 생겨 어긋난다 — 브라우저가 살아 있다고 믿는데 서버는 끊은 상태가
    가장 흔한 어긋남이다. 브라우저 세션 쿠키로 두면 창을 닫을 때 정리되고, 그 밖의
    만료 판정은 전부 서버가 한다.
    """
    secure = cookie_secure()
    response.set_cookie(
        SESSION_COOKIE_NAME, session.id,
        httponly=True, secure=secure, samesite=COOKIE_SAMESITE, path=COOKIE_PATH,
    )
    # ★ 이쪽만 `httponly=False` 다. JS 가 읽어 헤더에 실어야 double-submit 이 성립한다.
    #   세션 쿠키는 끝까지 JS 에서 읽지 않는다 (Part 0-E · ASVS).
    response.set_cookie(
        CSRF_COOKIE_NAME, session.csrf_token,
        httponly=False, secure=secure, samesite=COOKIE_SAMESITE, path=COOKIE_PATH,
    )
    return response


def _clear_session_cookies(response: JSONResponse) -> JSONResponse:
    secure = cookie_secure()
    response.delete_cookie(SESSION_COOKIE_NAME, path=COOKIE_PATH, secure=secure)
    response.delete_cookie(CSRF_COOKIE_NAME, path=COOKIE_PATH, secure=secure)
    return response


def optional_session(request: Request, *, now: datetime) -> Session | None:
    """세션이 있으면 돌려주고, 없거나 만료됐으면 `None`.

    **거부하지 않는다.** 판정 조회는 익명 포함 전원에게 열려 있으므로(SPEC 6.1 첫 행),
    끊긴 세션으로 온 요청은 401 이 아니라 그냥 익명 요청이다. 여기서 401 을 내면
    세션이 만료된 상담원의 화면에서 **판정 자체가 죽는다.**
    """
    return resolve_session(request, now=now).session


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def build_internal(
    result: dict,
    region_records: list[Region],
    versions: list[RuleVersion],
) -> dict:
    """SPEC 6.1 의 내부 정보 셋을 조립한다. **전부 pass-through 다.**

    판정을 다시 하지 않는다는 것이 이 함수의 유일한 규율이다. 어느 지역이 쓰였는지도
    다시 고르지 않고 `meta.region.code` 를 읽는다 — 엔진의 선택 규칙(지역코드가 없으면
    첫 번째)을 여기서 다시 쓰면 두 구현이 갈리고, 그게 Part 0-A 의 실패 유형이다.
    """
    used_code = result["meta"]["region"]["code"]
    used_region = next((r for r in region_records if r.code == used_code), None)

    criteria_by_policy = {
        version.payload.get("id"): version.payload.get("criteria") or {}
        for version in versions
    }

    return {
        "ruleVersions": [
            {
                "policyId": version.policy_id,
                "ruleVersionId": version.id,
                "origin": version.origin,
                "effectiveFrom": _iso(version.effective_from),
                "effectiveTo": _iso(version.effective_to),
            }
            for version in versions
        ],
        "dataFreshness": {
            "regionCode": used_code,
            # 지역이 응답에 실렸는데 레코드가 없을 수는 없다 — 같은 목록에서 나왔다.
            # 그래도 방어를 두는 이유는 여기서 터지면 **판정 전체가 500** 이 되기 때문이다.
            "verification": used_region.provenance.verification if used_region else "unverified",
            "observedAt": used_region.provenance.observed_at if used_region else None,
            "fetchedAt": used_region.provenance.fetched_at if used_region else None,
        },
        "ineligiblePolicies": [
            {
                "policyId": policy["id"],
                "status": policy["status"],
                "criteria": criteria_by_policy.get(policy["id"], {}),
            }
            for policy in result["policies"]
            if policy["status"] != "eligible"
        ],
    }


# --------------------------------------------------------------------------
# 계보 조립 (SPEC 2.1 · 2.4 · D-13)
# --------------------------------------------------------------------------
#
# ★ **로컬 판정 경로(`frontend/local_engine.js`)와 같은 규칙이다.** 두 경로가 SPEC 2.4 를
#   각자 읽으면 반드시 어긋나고, 그것이 이 과업의 지배적 실패 양상이다 (계약 결정 #37).
#   같음을 붙드는 것은 주장이 아니라 파수병이다 —
#   `backend/tests/test_frontend_local_engine_equivalence.py` 가 node 로 그 파일을 실행해
#   `dataGrade` · `provenance` 를 이쪽 결과와 대조한다 (계약 결정 #36).
#   **이 절을 고치면 그 파일도 같은 PR 에서 고쳐야 한다.**

#: 어느 사실이 응답의 어느 숫자를 근거짓는가 (RFC 6901). 엔진 접두사 -> 응답 위치.
#: 좁게 특정할 수 없는 곳은 그 부분트리를 가리킨다 — 상수 하나가 시나리오 4종 전부에
#: 흘러들므로 `/scenarios/0` 으로 좁히면 그것이 거짓이 된다.
ENGINE_TARGETS: dict[str, list[str]] = {
    "affordability": ["/affordability"],
    "tco": ["/scenarios"],
    "risk": ["/risk"],
    "eligibility": ["/policies"],
    "engines": ["/scenarios"],
}

#: 신선도 임계로 보이는 `ModelConstant` 키를 알아보는 표지.
#:
#: **값을 여기 적지 않는다.** SPEC 2.4 가 「며칠부터 `stale` 인지는 변경 발생 빈도를 알아야
#: 정할 수 있고, 값을 감으로 정해 코드에 박는 것을 금지한다」고 못박았고 그 값은 아직 없다.
#: 여기 있는 것은 **[임계가 등재되었는가]를 데이터에서 읽는 방법**뿐이다.
FRESHNESS_THRESHOLD_KEY_MARKERS = ("freshness", "stale")


def freshness_threshold_keys(constants: dict) -> list[str]:
    """등재된 신선도 임계 상수의 키. **지금은 0건이다** (SPEC 2.4 · Part 0-E #4).

    0건이면 `stale` 여부를 **판정할 수 없고**, 그 사실이 응답에 `freshness_not_evaluated`
    사유로 실린다. 임계가 등재되는 날 이 함수가 비어 있지 않게 되어 표기가 **자동으로**
    꺼진다 — 어딘가의 `False` 리터럴을 사람이 찾아 지우는 구조로 두지 않는다.

    표기만 꺼지고 판정이 안 들어오면 화면은 그것을 「신선하다」로 읽는다. 그 조용한 전환을
    `backend/tests/api/test_analyze_lineage.py` 의 파수병이 막는다 — 이 목록이 비지 않게
    되는 순간 그 테스트가 깨지고, `stale` 판정을 구현하라고 말한다.
    """
    return sorted(
        key for key in constants
        if any(marker in key.lower() for marker in FRESHNESS_THRESHOLD_KEY_MARKERS)
    )


def build_lineage(
    result: dict,
    region_records: list[Region],
    versions: list[RuleVersion],
    *,
    constants: dict,
    constant_provenance: dict[str, dict],
) -> dict:
    """`provenance`(사실 단위 배열) + `dataGrade`(등급 + 사유) 를 만든다 (D-13).

    `build_internal` 과 같은 규율이다 — **판정을 다시 하지 않는다.** 어느 지역이 쓰였는지도
    다시 고르지 않고 `meta.region.code` 를 읽는다.
    """
    used_code = result["meta"]["region"]["code"]
    used_region = next((r for r in region_records if r.code == used_code), None)

    items: list[dict] = []

    # (1) 지역 시세 — **사실 단위(필드별)** 계보다. 레코드 요약으로 접지 않는다.
    #     지금은 8필드의 계보가 전부 같지만 수집이 실데이터를 넣으면 갈린다 (결정 #34).
    if used_region is not None:
        for field_name in sorted(REGION_FACT_FIELDS):
            items.append({
                "fact": f"지역 시세 · {field_name} ({used_region.name})",
                "factKind": "region_field",
                "provenance": used_region.provenance_for(field_name).to_dict(),
                "targets": ["/scenarios", "/risk"],
            })

    # (2) 판정에 참여한 승인 규칙 — 정책 하나까지 좁혀지므로 인덱스까지 가리킨다.
    policy_index = {policy["id"]: index for index, policy in enumerate(result["policies"])}
    for version in versions:
        index = policy_index.get(version.policy_id)
        items.append({
            "fact": f"정책 규칙 · {version.payload.get('name') or version.policy_id} ({version.id})",
            "factKind": "rule_version",
            "provenance": version.provenance.to_dict(),
            "targets": [f"/policies/{index}"] if index is not None else ["/policies"],
        })

    # (3) 모델 상수 — **엔진이 실제로 조회한 키만** (`required_constant_keys()` 가 수요측
    #     정본이다). 저장소에 있는 것 전부를 싣지 않는다 — `auth.*` · `ingest.*` 는 이
    #     판정에 쓰이지 않았고, 쓰이지 않은 사실이 등급을 움직이면 그 등급은 거짓이다.
    for key in sorted(required_constant_keys()):
        engine = key.split(".")[0]
        if engine not in ENGINE_TARGETS:
            continue
        items.append({
            "fact": f"모델 상수 · {key}",
            "factKind": "model_constant",
            "provenance": constant_provenance[key],
            "targets": ENGINE_TARGETS[engine],
        })

    return {"provenance": items, "dataGrade": grade_facts(items, constants)}


def grade_facts(items: list[dict], constants: dict) -> dict:
    """SPEC 2.4 산정 규칙. 대상은 `verification != our_choice` 인 사실이다.

    `our_choice` 가 빠지는 이유는 Part 0-E #3 이다 — 규범적 선택에는 신선도 개념이 없다.
    **빠지는 것은 등급이지 계보가 아니다.** `provenance` 에는 그대로 실린다.
    """
    reasons: list[dict] = []
    for index, item in enumerate(items):
        verification = item["provenance"]["verification"]
        if verification == "our_choice":
            continue
        if verification not in ("unverified", "stale"):
            continue
        reasons.append({
            "type": verification,
            "provenanceIndex": index,
            "fact": item["fact"],
            "message": (
                f"{item['fact']} 의 출처를 확인하지 못했습니다."
                if verification == "unverified"
                else f"{item['fact']} 의 관측 시점이 신선도 기준을 넘었습니다."
            ),
        })

    # ★ 신선도는 **판정하지 않았다.** 그 사실을 조용히 넘기지 않는다 (SPEC 2.4).
    #   [해당 없음] 으로 처리하면 화면은 그것을 「신선하다」로 읽고, 그것이 침묵 폴백이다.
    if not freshness_threshold_keys(constants):
        reasons.append({
            "type": "freshness_not_evaluated",
            # 특정 사실의 결함이 아니라 판정 자체가 서지 않은 상태다. 한 항목을 가리키면
            # 「그 사실만 문제」로 읽힌다.
            "provenanceIndex": None,
            "fact": None,
            "message": (
                "신선도 임계가 아직 정해지지 않아 stale 여부를 판정하지 않았습니다. "
                "이 등급은 검증 상태만으로 산정된 것이며, 신선도가 확인되었다는 뜻이 아닙니다 "
                "(SPEC 2.4)."
            ),
        })

    # 가장 나쁜 것이 이긴다 (`C` > `B` > `A`).
    types = {reason["type"] for reason in reasons}
    if "unverified" in types:
        grade = "C"
    elif types & {"stale", "pending_review"}:
        grade = "B"
    elif "freshness_not_evaluated" in types:
        # `A` 는 「전부 verified **이며** 신선도 기준 이내」다. 뒤 절이 확정되지 않았으므로
        # `A` 를 낼 수 없다. **`null` 은 「깨끗함」이 아니라 「산정할 수 없음」이다.**
        grade = None
    else:
        grade = "A"

    return {"grade": grade, "reasons": reasons}


# --------------------------------------------------------------------------
# 이상 신고 (SPEC 6.4 · 7.1 · 계약 결정 #38)
# --------------------------------------------------------------------------
#
# 「상담원은 이 시스템에서 가장 자주 쓰는 사용자이자 **데이터 오류의 최전선 탐지자**다.
#  이 피드백 경로가 없으면 현장에서 발견된 오류가 시스템에 들어오지 못한다.」
#
# ★ **신고는 「작은 draft」가 아니다.** 초안은 기계가 낸 것이라 스키마 강제·span 실재성·
#   부분 저장 금지(4.2)가 걸리고, 신고는 사람이 낸 것이라 그런 것이 없다. 그래서 저장소도
#   응답 스키마도 갈라져 있고, 이 절은 그 둘을 **섞지 않는 방식으로만** 연결한다.
#
# ★★ **신고는 규칙을 바꾸지 않는다.** 여기 있는 것은 `add` 하나뿐이고, `RuleVersion` 을
#    만드는 코드도 초안 상태를 옮기는 코드도 없다. 제안이지 변경이 아니다 (SoD 유지).

#: SPEC 6.4 — 신고자·시각·대상·사유를 남긴다. 그 넷이 `AuditEvent` 의 네 자리에 그대로
#: 대응한다: `actor` · `at` · `target` · `after.reason`.
AUDIT_REPORT_CREATED = "report.create"

#: 신고가 큐에 들어갈 때의 상태. **6-A 는 여는 경로만 만든다** — SPEC 6.4 는 신고를 받은
#: 뒤 규칙관리자가 「수동으로 입력하거나 재추출을 지시한다」고만 적었고 닫는 동작을 어느
#: 단계에도 배정하지 않았다. 없는 기능을 만들지 않으므로 이 값은 항상 이것이다.
REPORT_INITIAL_STATUS = "open"


def _report_ref(report, merged_draft_ids: list[str]) -> dict:
    return {
        "id": report.id,
        "reporter": report.reporter,
        "at": _iso(report.at),
        "targetKind": report.target_kind,
        "targetId": report.target_id,
        "targetField": report.target_field,
        "reason": report.reason,
        "status": report.status,
        "mergedDraftIds": merged_draft_ids,
    }


def _pending_drafts_for(store: Store, policy_id: str) -> list[str]:
    """그 정책을 겨눈 **검토 대기 중인** 초안들. 결정이 끝난 초안은 검토 항목이 아니다."""
    return [d.id for d in store.rule_drafts.list(status="pending") if d.policy_id == policy_id]


def _merge_reports(store: Store, reports: list) -> list[dict]:
    """SPEC 6.4 의 충돌 처리 — ★ **잠정 규칙이다.**

    > 잠정 규칙이다. 실제 운영에서 **신고 빈도와 draft 빈도의 비율**을 본 뒤 재검토한다.

    그 문장이 이 함수의 전제다. 지금 고정하는 것은 [이렇게 동작한다] 이지 [이것이 옳다]
    가 아니며, 비율을 본 뒤 바뀔 수 있다.

      · 대상 **정책**이 같은 `pending` 초안이 있으면 하나의 검토 항목으로 묶는다
        (신고가 초안의 **컨텍스트**가 된다)
      · 짝이 없으면 **신고 단독 항목**으로 큐에 남는다
      · 시세 신고는 짝이 없다 — 초안은 정책을 겨누지 지역을 겨누지 않는다

    **병합은 보여 주는 방식이지 기록의 통합이 아니다.** 두 `AuditEvent` 는 각각 그대로
    남으며(10.2 6-A 셋째), 이 함수는 저장소를 **읽기만** 한다.

    초안 목록을 한 번만 읽는다 — 신고마다 물으면 큐 조회가 N+1 이 된다.
    """
    policy_ids = {r.target_id for r in reports if r.target_kind == "policy"}
    if not policy_ids:
        return [_report_ref(report, []) for report in reports]

    pending: dict[str, list[str]] = {policy_id: [] for policy_id in policy_ids}
    for draft in store.rule_drafts.list(status="pending"):
        if draft.policy_id in pending:
            pending[draft.policy_id].append(draft.id)

    return [
        _report_ref(report, list(pending.get(report.target_id, ()))
                    if report.target_kind == "policy" else [])
        for report in reports
    ]


def _reports_for_draft(store: Store, policy_id: str) -> list[dict]:
    """그 정책을 겨눈 현장 신고 — 검토 화면에 **컨텍스트로** 붙는다 (SPEC 6.4, 잠정)."""
    return [
        _report_ref(report, [])
        for report in store.reports.list()
        if report.target_kind == "policy" and report.target_id == policy_id
    ]


def _report_target_error(store: Store, payload: ReportRequest) -> JSONResponse | None:
    """대상이 정책·시세 **항목**인가 (SPEC 7.1 · 계약 결정 #38). 아니면 오류 봉투.

    ★ **오류 문구에 입력값을 싣지 않는다.** 신고 사유는 자유 입력이라 고객 상황이 섞일 수
      있고, 대상 식별자도 클라이언트가 준 문자열이다. 검증 실패 응답이 값을 인용하는
      순간 그 값이 로그·스크린샷·버그리포트로 새어 나간다 — 7.1 의 「요청 본문을 찍지
      않는다」가 오류 경로에도 걸린다는 뜻이다. 대신 **무엇이 허용되는지**를 적는다.

    항목 이름의 허용 목록은 저장소가 정본이고(`validate_report`), 여기서는 **대상이
    실재하는지**를 더한다. 실재 검사가 저장소에 없는 이유는 신고 대상이 사라진 뒤에도
    기록은 되읽을 수 있어야 하기 때문이다.
    """
    if payload.targetKind == "policy":
        allowed = POLICY_REPORT_FIELDS
        known = {policy["id"] for policy in read_active_policies(store, request_now())}
    elif payload.targetKind == "region":
        allowed = REGION_FACT_FIELDS
        known = {region.code for region in store.regions.list()}
    else:
        return _error(400, "unknown_target_kind",
                      f"신고 대상 종류는 {list(REPORT_TARGET_KINDS)} 중 하나여야 합니다.")

    if payload.targetField not in allowed:
        return _error(400, "unknown_target_field",
                      f"신고할 수 있는 항목이 아닙니다. 허용: {list(allowed)}")
    if payload.targetId not in known:
        return _error(400, "unknown_target",
                      "신고 대상을 찾을 수 없습니다. 화면에 표시된 항목만 신고할 수 있습니다.")
    if not payload.reason.strip():
        return _error(400, "reason_required", "신고에는 사유가 필요합니다.")
    return None


# --------------------------------------------------------------------------
# 승인·반려 (SPEC 4.6 · 6.1 · 7.1) — **거부의 대조군이다**
# --------------------------------------------------------------------------
#
# 범위는 코디네이터가 정했다 (Q5). 여기 있는 것: 단일 건 승인·반려, `RuleVersion` 생성과
# `supersede`, `ApprovalRecord`, `AuditEvent`, **중복 승인 거부**.
# 5단계로 미룬 것: 검토 화면(4.4·4.5), 일괄 승인, 변경 유형 ①②③ 차등.

#: SPEC 7.1 필수 기록 — 규칙 승인·반려.
AUDIT_RULE_DECISION = {"approved": "rule.approve", "rejected": "rule.reject"}

#: 초안이 덮어쓰는 필드. 나머지(`name` · `category` · `summary` · `notes` · `source` ·
#: `disclaimer`)는 **표시 전용**이라 추출 대상이 아니며 이전 버전 것을 그대로 물려받는다.
#: 목록의 근거는 `contracts/rule_draft.schema.json` 의 `required` 다 — 초안이 말할 수
#: 있는 것이 곧 이 넷이고, 여기서 더 늘리면 초안이 하지 않은 말을 우리가 지어내는 것이 된다.
_DRAFT_OVERRIDE_FIELDS = ("criteria", "maxAmountKRW", "rateRangePct", "conditionalChecks")


def _merged_payload(previous: RuleVersion | None, draft) -> dict:
    """이전 버전 위에 초안을 얹는다. **`not_found` 는 얹지 않는다.**

    `not_found` 는 SPEC 4.2 의 [추정 금지]가 담기는 자리다 — 원문에 그 값이 **없었다**는
    뜻이지 [값이 없어졌다]가 아니다. 그것을 그대로 덮으면 이미 알고 있던 문턱이 승인
    한 번에 `null` 이 되고, 판정은 그 정책을 조건 없이 통과시키게 된다. 방향이 관대한
    쪽이므로 금지다 (HANDOFF 불변조건 7).

    ★ 잠정 규칙이다. 검토 화면(4.4)이 [무엇이 바뀌는가]를 사람에게 보여주는 것이
      5단계이고, 그때 이 병합이 화면과 같은 것을 말하는지 다시 봐야 한다.
    """
    payload = dict(previous.payload) if previous is not None else {}
    payload["id"] = draft.policy_id
    not_found = set(draft.payload.get("not_found") or ())

    for name in _DRAFT_OVERRIDE_FIELDS:
        if name not in draft.payload or f"/{name}" in not_found:
            continue
        if name != "criteria":
            payload[name] = draft.payload[name]
            continue
        merged = dict((payload.get("criteria") or {}))
        for key, value in (draft.payload.get("criteria") or {}).items():
            if f"/criteria/{key}" in not_found:
                continue
            merged[key] = value
        payload["criteria"] = merged
    return payload


# --------------------------------------------------------------------------
# 검토 화면의 재료 (SPEC 4.4 · D-3 원칙 3) — **판단 근거이지 표시가 아니다**
# --------------------------------------------------------------------------
#
# 4.4 는 네 항목을 「표시하라」고 적었지만 목적은 표시가 아니라 **거수기 방지**다.
# 그래서 아래 함수들이 지는 것은 「필드를 응답에 싣는 것」이 아니라 **「이것만 보고
# 승인·반려를 가를 수 있게 하는 것」** 이며, 그 판정 기준으로 각 함수의 주석을 읽어야 한다.


def _highlight_segments(text: str, spans) -> list[dict]:
    """원문을 **끊어진 조각들**로 내려보낸다. 화면은 순서대로 그리기만 한다.

    ★ 오프셋 산술이 서버에 있는 이유 (코디네이터 결정 2026-08-14). SPEC 4.2.1 은 span
      단위를 **유니코드 코드포인트**로 못박았고 파이썬 `str` 인덱스가 곧 그 단위다.
      JS 문자열 인덱스는 **UTF-16 코드유닛**이라 화면이 직접 자르면 단위 변환이 한 번
      끼어드는데, 이 저장소에는 JS 를 실행하는 테스트 하네스가 없다(결정 #31 — CI 는
      파이썬 전용). 검증할 수 없는 변환을 두느니 변환 자체를 없앤다.
      `ingest.extraction_verify.locate_quote` 가 이미 같은 이유로 파이썬에서 자른다.

    **경계는 모든 span 의 시작·끝을 합집합으로 모은 것이다.** 그래서 각 조각은 어떤
    span 에 대해서도 [완전히 안] 이거나 [완전히 밖] 이고, 겹침·포함이 자연히 처리된다 —
    한 조각이 두 근거에 걸리면 `fieldPaths` 에 **둘 다** 실린다. 겹침은 지금 데이터에
    없지만 구조상 가능하므로 여기서 정해 둔다.

    **이어 붙이면 원문과 같아야 한다.** 한 글자라도 새거나 빠지면 화면이 원문이 아닌
    것을 보여 주게 되고, 그 순간 4.2 의 「핵심 방어」가 화면에서 무력해진다.
    """
    length = len(text)
    bounded = [
        (max(0, min(span.start, length)), max(0, min(span.end, length)), span.field_path)
        for span in spans
    ]
    cuts = {0, length}
    for start, end, _ in bounded:
        cuts.add(start)
        cuts.add(end)

    points = sorted(cuts)
    segments: list[dict] = []
    for start, end in zip(points, points[1:]):
        if start >= end:
            continue
        segments.append({
            "text": text[start:end],
            "fieldPaths": sorted(
                path for span_start, span_end, path in bounded
                if span_start <= start and end <= span_end
            ),
        })
    return segments


#: 화면이 필드 옆에 그대로 적는 이름. **판정에 쓰이는 필드만 있다** — 목록의 근거는
#: `_DRAFT_OVERRIDE_FIELDS` 와 `criteria` 8종이고, 그 둘의 정본은
#: `contracts/rule_draft.schema.json` 이다 (계약 결정 #18).
_FIELD_LABELS = {
    "/criteria/ageMin": "최소 연령",
    "/criteria/ageMax": "최대 연령",
    "/criteria/annualIncomeMaxKRW": "연소득 상한",
    "/criteria/assetMaxKRW": "자산 상한",
    "/criteria/requireHomeless": "무주택 요건",
    "/criteria/requireNewlywed": "신혼부부 요건",
    "/criteria/requireSME": "중소기업 재직 요건",
    "/criteria/regionPrefixes": "적용 지역 접두사",
    "/maxAmountKRW": "지원 한도",
    "/rateRangePct": "금리 구간",
    "/conditionalChecks": "조건부 확인 항목",
    "/name": "제도명",
    "/category": "분류",
    "/summary": "요약",
    "/notes": "비고",
    "/source": "출처 표기",
    "/disclaimer": "고지",
}

#: 초안이 말할 수 없는 필드에 붙는 한 줄. **「안 바뀜」이 아니다** (PR #58 D1).
_INHERITED_NOTE = (
    "초안이 말할 수 있는 필드가 아니다 (표시 전용). 이전 버전 값을 그대로 물려받는다 — "
    "「바뀌지 않았다」가 아니라 「초안이 말할 수 없다」이며, 둘은 다른 사실이다."
)

#: `criteria` 가 키 단위 병합이라는 사실에서 곧바로 나오는 한계 (PR #58 D4).
_SILENT_NOTE = (
    "초안이 이 키를 말하지 않았다. criteria 는 키 단위로 얹히므로 이전 값이 그대로 남는다. "
    "★ 「이 조건이 폐지됐다」를 표현할 방법이 현재 규칙에 없다 — 값이 남은 것이 "
    "「폐지되지 않았다」의 근거가 되지 못한다."
)

_NOT_FOUND_NOTE = (
    "초안이 「원문에서 찾지 못했다」(not_found)고 보고했다 — 즉 「모름」이다. "
    "추정 금지(SPEC 4.2)에 따라 이전 값을 유지한다. 「없음」(null)과 다르다."
)

_EXPLICIT_NULL_NOTE = (
    "초안이 not_found 없이 null 을 실었다 — 즉 「없음」이다. 승인하면 이전 값이 지워진다. "
    "「모름」(not_found)과 달리 이 값은 그대로 반영된다."
)

#: 화면 전체에 한 번 걸리는 한계 목록. **데이터에 우연히 걸릴 때만 나타나서는 안 된다** —
#: 조용한 한계는 검토자가 없다고 믿게 만든다.
REVIEW_LIMITATIONS = (
    "「이 조건이 폐지됐다」를 초안이 표현할 방법이 없다. criteria 는 키 단위 병합이라 "
    "초안이 말하지 않은 키는 이전 값이 남는다 (규칙 변경은 SPEC 8.2 절차 대상이다).",
    "rateRangePct · conditionalChecks 는 통째로 교체된다. 빈 배열을 실으면 "
    "이전 항목이 전부 사라진다 — criteria 의 키 단위 병합과 의미가 다르다.",
    "③ 수치 갱신의 경량 검토 화면(SPEC 4.5)은 만들지 않았다. Part 10 이 「①②③ 판별 규칙이 "
    "확정되기 전에는 모든 변경을 ①/② 절차로 처리한다」고 했기 때문이다. 일괄 승인은 "
    "유형과 무관하게 열려 있으며, 묶는 것은 검토가 아니라 반영이다.",
    "승인이 붙이는 계보의 verification 은 unverified 다. 사람이 승인했다는 사실은 "
    "「추출이 원문과 일치한다」를 말하지 「그 원문이 지금도 유효하다」를 말하지 않는다.",
)


def _field_change(path: str, *, origin: str, merge_mode: str, draft_said: str,
                  before, before_present: bool, after, after_present: bool,
                  evidence: dict | None, evidence_expected: bool,
                  note: str, wipes_previous: bool = False) -> dict:
    return {
        "path": path,
        "label": _FIELD_LABELS.get(path, path.lstrip("/")),
        "origin": origin,
        "mergeMode": merge_mode,
        "draftSaid": draft_said,
        "changed": before_present != after_present or before != after,
        "before": before,
        "beforePresent": before_present,
        "after": after,
        "afterPresent": after_present,
        "wipesPrevious": wipes_previous,
        "evidence": evidence,
        "evidenceExpected": evidence_expected,
        "note": note,
    }


def _field_changes(previous_payload: dict, draft, merged: dict, evidence: dict) -> list[dict]:
    """필드 단위 변경 표 (SPEC 4.4 #3). **병합 규칙과 같은 것을 말해야 한다.**

    `_merged_payload` 가 실제로 하는 일을 사람이 읽을 수 있게 편 것이며, 그래서 이 함수는
    병합을 **다시 계산하지 않고** 그 결과(`merged`)를 받는다. 두 번 계산하면 화면과 승인이
    갈리는 날이 오고, 그것이 이 화면에서 가장 나쁜 결함이다.

    구분되는 다섯 (PR #58 의 병합 규칙 산문에서 그대로 나온다):

        `value`          초안이 값을 실었다
        `explicit_null`  초안이 `not_found` 없이 `null` 을 실었다 — **없음**
        `not_found`      초안이 못 찾았다고 보고했다 — **모름** (이전 값 유지)
        `silent`         초안이 그 키를 아예 말하지 않았다 (`criteria` 만 가능)
        `not_applicable` 초안이 말할 수 있는 필드가 아니다 (표시 전용)
    """
    not_found = set(draft.payload.get("not_found") or ())
    draft_criteria = draft.payload.get("criteria")
    previous_criteria = previous_payload.get("criteria") or {}
    merged_criteria = merged.get("criteria") or {}

    fields: list[dict] = []

    # --- criteria: **키 단위**로 얹힌다 -----------------------------------
    keys = sorted(set(previous_criteria) | set(draft_criteria or {}) | set(merged_criteria))
    for key in keys:
        path = f"/criteria/{key}"
        said_it = isinstance(draft_criteria, dict) and key in draft_criteria
        if not said_it:
            draft_said, note = "silent", _SILENT_NOTE
        elif path in not_found or "/criteria" in not_found:
            draft_said, note = "not_found", _NOT_FOUND_NOTE
        elif draft_criteria[key] is None:
            draft_said, note = "explicit_null", _EXPLICIT_NULL_NOTE
        else:
            draft_said, note = "value", ""
        fields.append(_field_change(
            path,
            origin="draft",
            merge_mode="key_merge",
            draft_said=draft_said,
            before=previous_criteria.get(key),
            before_present=key in previous_criteria,
            after=merged_criteria.get(key),
            after_present=key in merged_criteria,
            evidence=evidence.get(path),
            evidence_expected=draft_said == "value",
            note=note,
        ))

    # --- 나머지 셋: **통째로** 교체된다 -----------------------------------
    for name in _DRAFT_OVERRIDE_FIELDS:
        if name == "criteria":
            continue
        path = f"/{name}"
        if name not in draft.payload:
            draft_said, note = "silent", _SILENT_NOTE
        elif path in not_found:
            draft_said, note = "not_found", _NOT_FOUND_NOTE
        elif draft.payload[name] is None:
            draft_said, note = "explicit_null", _EXPLICIT_NULL_NOTE
        else:
            draft_said, note = "value", ""

        before = previous_payload.get(name)
        after = merged.get(name)
        # 통째 교체는 [비우기]가 가능하다. `criteria` 와 같은 방식으로 그리면 거짓말이 된다.
        wipes = (
            draft_said == "value"
            and isinstance(before, list) and isinstance(after, list)
            and bool(before) and not after
        )
        if wipes:
            note = (
                f"통째로 교체된다 — 이전 항목 {len(before)}개가 전부 사라진다. "
                "criteria 의 키 단위 병합과 의미가 다르다."
            )
        change = _field_change(
            path,
            origin="draft",
            merge_mode="replace",
            draft_said=draft_said,
            before=before,
            before_present=name in previous_payload,
            after=after,
            after_present=name in merged,
            evidence=evidence.get(path),
            evidence_expected=draft_said == "value" and path != "/conditionalChecks",
            note=note,
            wipes_previous=wipes,
        )
        if name == "conditionalChecks":
            # 근거는 **항목마다** 붙는다 (`/conditionalChecks/{i}`) — 필드 하나에
            # 붙지 않는다. `extraction_verify.EVIDENCE_POINTERS` 가 그렇게 나눠 두었고,
            # 화면도 항목 옆에 그려야 검토자가 어느 문장의 근거인지 안다.
            change["evidenceItems"] = [
                evidence.get(f"{path}/{index}")
                for index in range(len(after if isinstance(after, list) else []))
            ]
        fields.append(change)

    # --- 표시 전용: **초안이 말할 수 없다** (D1) ---------------------------
    for name in sorted(set(merged) | set(previous_payload)):
        if name in _DRAFT_OVERRIDE_FIELDS or name == "id":
            continue
        fields.append(_field_change(
            f"/{name}",
            origin="inherited",
            merge_mode="inherit_only",
            draft_said="not_applicable",
            before=previous_payload.get(name),
            before_present=name in previous_payload,
            after=merged.get(name),
            after_present=name in merged,
            evidence=None,
            evidence_expected=False,
            note=_INHERITED_NOTE,
        ))
    return fields


def _approval_provenance(store: Store, draft) -> Provenance:
    """승인된 규칙의 계보 (SPEC 2.1).

    **`verification` 은 `unverified` 다.** 사람이 승인했다는 사실은 [추출이 원문과
    일치한다]를 말하지 [그 원문이 지금도 유효하다]를 말하지 않는다. 후자를 주장하려면
    공표 기준시점(`observed_at`)이 있어야 하는데 제도 문서에서 그것을 구조적으로 얻지
    못하고 있다 (HANDOFF `regionPrefixes` 건과 같은 부류). 기준시점 없이 `verified` 를
    적는 것이 Part 0-C 가 [심사에서 즉시 반박당한다]고 경고한 그것이다.

    시드 규칙과 같은 등급이며, 그래서 승인이 `dataGrade` 를 몰래 올리지 않는다.
    """
    source = store.policy_sources.get(draft.policy_source_id)
    return Provenance(
        source_kind="statute",
        source_name=(source.attribution if source is not None else None) or None,
        source_ref=(source.source_ref if source is not None else None) or None,
        observed_at=None,
        fetched_at=_iso(source.fetched_at) if source is not None else None,
        verification="unverified",
    )


def _not_found(draft_id: str) -> JSONResponse:
    return _error(404, "draft_not_found", f"초안을 찾을 수 없습니다: {draft_id}")


def _already_decided(status: str) -> JSONResponse:
    """순차로 진 쪽과 경합에 진 쪽이 **같은 답**을 받는다.

    호출자에게 [내가 동시에 눌린 쪽인가] 는 구분할 이유가 없는 정보다. 메시지를 갈라 두면
    화면이 둘을 다르게 다루기 시작하고, 그때부터 [한 번만 일어난다] 가 두 갈래가 된다.
    """
    return _error(
        409, "draft_already_decided",
        f"이미 처리된 초안입니다 (현재 상태: {status}). 승인은 한 번만 일어납니다.",
    )


def _pending_draft_or_error(store: Store, draft_id: str):
    """초안을 꺼내되 **pending 이 아니면 거부한다** (SPEC 4.6).

    ★ 이것은 **빠른 거절**이지 원자성이 아니다. 여기서 읽은 상태와 `_decide` 의 쓰기
      사이에는 트랜잭션 경계가 없어서, 두 요청이 그 사이에 겹치면 둘 다 통과한다.
      [승인은 한 번만] 을 실제로 지는 것은 `rule_drafts.claim_pending` 이며 저장소
      계층에 있다. 이 검사가 여기 남는 이유는 404/409 를 **초안을 읽어야만** 가를 수
      있고, 흔한 순차 재클릭을 승인 절차 전체를 태우기 전에 끊어 주기 때문이다.
    """
    draft = store.rule_drafts.get(draft_id)
    if draft is None:
        return _not_found(draft_id)
    if draft.status != "pending":
        return _already_decided(draft.status)
    return draft


def _decide(store: Store, session: Session, draft, *, decision: str,
            reason: str | None, now: datetime):
    """승인·반려를 한 자리에서 처리한다. 둘의 차이는 `RuleVersion` 이 생기는가 하나다.

    **첫 줄이 초안을 선점한다** (SPEC 4.6). 선점이 승인 절차 전체의 관문이며, 이긴 요청
    하나만 `ApprovalRecord` 와 `RuleVersion` 을 만든다. 선점을 뒤로 미루면 — 지금까지가
    그랬다 — 두 요청이 나란히 `_pending_draft_or_error` 를 지나 둘 다 승인 기록을 남기고,
    같은 `RuleVersion` id 에서 부딪혀 500 으로 끝난다.
    """
    try:
        store.rule_drafts.claim_pending(draft.id, decision)
    except DraftAlreadyDecidedError:
        current = store.rule_drafts.get(draft.id)
        return _already_decided(current.status if current is not None else decision)
    except RecordNotFoundError:
        return _not_found(draft.id)

    try:
        return _apply_decision(store, session, draft, decision=decision, reason=reason, now=now)
    except Exception:
        # 선점만 남고 승인의 실체(기록·버전)가 없으면 초안이 결정 상태로 굳어 **재시도조차**
        # 막힌다. 원복은 그 막다른 길을 없애려는 것이고, 원복 뒤 다른 요청이 다시 선점할 수
        # 있는 것은 결함이 아니라 [아직 아무도 승인하지 못했다] 는 사실 그대로다.
        store.rule_drafts.set_status(draft.id, "pending")
        raise


def _apply_decision(store: Store, session: Session, draft, *, decision: str,
                    reason: str | None, now: datetime) -> dict:
    """선점에 이긴 요청만 여기 들어온다. 여기서부터는 이 초안의 유일한 결정자다."""
    rule_version_id = None
    approval_target_kind = "rule_draft"
    approval_target_id = draft.id

    if decision == "approved":
        previous = next(
            (v for v in read_active_rule_versions(store, now) if v.policy_id == draft.policy_id),
            None,
        )
        version = RuleVersion(
            id=f"approval:{draft.id}",
            policy_id=draft.policy_id,
            payload=_merged_payload(previous, draft),
            status="approved",
            origin="human_approval",
            effective_from=now,
            effective_to=None,
            supersedes=previous.id if previous is not None else None,
            approved_by=session.user_id,
            provenance=_approval_provenance(store, draft),
            created_at=now,
        )
        # ★ 순서가 강제된다. 계약 결정 #5 의 트리거가 `approval_record.target_id ==
        #   rule_version.id` 인 행을 **INSERT 시점에** 요구하므로 기록이 먼저다.
        #   승인자 이름만 적고 승인 기록이 없으면 그것은 승인이 아니다.
        approval_target_kind, approval_target_id = "rule_version", version.id
        approval = store.approvals.add(
            ApprovalRecord(
                id=f"approval:{uuid4().hex}",
                actor_user_id=session.user_id,
                at=now,
                target_kind=approval_target_kind,
                target_id=approval_target_id,
                decision=decision,
                reason=reason or None,
            )
        )
        if previous is None:
            store.rule_versions.add(version)
        else:
            store.rule_versions.supersede(previous.id, version, at=now)
        rule_version_id = version.id
    else:
        approval = store.approvals.add(
            ApprovalRecord(
                id=f"approval:{uuid4().hex}",
                actor_user_id=session.user_id,
                at=now,
                target_kind=approval_target_kind,
                target_id=approval_target_id,
                decision=decision,
                reason=reason,
            )
        )

    # 상태는 이미 선점 단계에서 `decision` 으로 넘어갔다 (`_decide`). 여기서 다시 쓰면
    # 조건 없는 덮어쓰기가 되어 원자화가 도로 무의미해진다.
    record(
        store,
        actor=session.username,
        at=now,
        action=AUDIT_RULE_DECISION[decision],
        target=draft.id,
        outcome="success",
        after={"policyId": draft.policy_id, "ruleVersionId": rule_version_id},
    )
    return {
        "draftId": draft.id,
        "decision": decision,
        "ruleVersionId": rule_version_id,
        "approvalRecordId": approval.id,
        "at": _iso(now),
    }


# --------------------------------------------------------------------------
# 일괄 승인 (SPEC 4.5 · 4.6 · 10.2 5단계)
# --------------------------------------------------------------------------
#
# **일괄 승인은 검토를 건너뛰는 것이 아니라 반영을 묶는 것이다** (코디네이터 판정).
# 검토자는 4.4 의 네 항목을 **건별로** 본 뒤 여러 건을 묶어 반영한다. 그래서 여기에
# 유형(①②③) 제한이 없고, 4.5 의 ③ 경량 검토 화면도 만들지 않았다 — Part 10 이
# 「판별 규칙이 확정되기 전에는 모든 변경을 ①/② 절차로 처리한다」고 했기 때문이다.
#
# 두 요구가 **다른 층위**에 걸린다는 것이 이 절의 설계 전부다 (SPEC 4.6):
#
#     반영(`RuleVersion`)                       원자적 — 한 건이라도 실패하면 전체가 없다
#     기록(`ApprovalRecord` · `AuditEvent`)     건별 — 묶었다고 하나로 합치지 않는다
#
# 그래서 반영은 `_apply_decision` 을 **건별로 그대로 재사용**한다. 일괄용 승인 절차를
# 따로 쓰면 [승인이란 무엇인가] 가 두 벌이 되고, 둘 중 하나만 고쳐지는 날이 온다.


def _release_claims(store: Store, drafts) -> None:
    """선점만 하고 반영에 이르지 못한 초안을 `pending` 으로 돌려놓는다.

    되돌리지 않으면 초안이 결정 칸에 갇혀 **재시도조차** 막힌다 (`_decide` 의 원복과
    같은 이유). 조건 없는 `set_status` 를 쓰는 것이 맞는 자리다 — 인터페이스가 이
    용도를 명시적으로 남겨 두었다.
    """
    for draft in drafts:
        store.rule_drafts.set_status(draft.id, "pending")


def _approval_preflight(store: Store, drafts, now: datetime):
    """반영 단계에서 **터질 수 있는 것**을 쓰기 전에 전부 본다. 막히면 오류 응답.

    저장소 인터페이스에 여러 저장소를 걸치는 트랜잭션이 없으므로(부록 A — 그것은
    `store` 소유이고 SPEC 9.4 상 이 과업의 범위 밖이다), 원자성은 **쓰기 단계에서
    실패할 여지를 미리 없애는 것**으로만 얻는다. 되돌릴 수 없는 것을 쓰기 전에 보는
    것이 이 함수다.

    `RuleVersion` 은 불변이고 `supersede` 는 이전 버전을 닫는다 — 둘 다 취소가 없다.
    """
    for draft in drafts:
        version_id = f"approval:{draft.id}"
        if store.rule_versions.get(version_id) is not None:
            return _error(
                409, "rule_version_exists",
                f"이미 이 초안에서 나온 규칙 버전이 있습니다: {version_id}",
            )
        previous = next(
            (v for v in read_active_rule_versions(store, now) if v.policy_id == draft.policy_id),
            None,
        )
        if previous is not None and previous.effective_from is not None and now <= previous.effective_from:
            # 같은 순간에 그 정책의 승인이 이미 한 번 열렸다. `supersede` 가 순서
            # 불변식으로 거부하는데, 그 거부는 쓰기 도중에 나오므로 여기서 먼저 끊는다.
            return _error(
                409, "rule_version_window_conflict",
                f"{draft.policy_id} 의 현행 규칙이 같은 시각에 시작됐습니다. "
                "한 정책의 승인 이력은 같은 순간에 두 번 열릴 수 없습니다.",
            )
    return None


def _batch_approve(store: Store, session: Session, draft_ids: list[str], *,
                   reason: str | None, now: datetime):
    """여러 초안을 한 번에 반영한다. **전부 아니면 전무.**

    순서가 곧 설계다 — 되돌릴 수 없는 쓰기(`ApprovalRecord` · `RuleVersion`)를 마지막에
    두고, 그 앞의 모든 단계는 실패해도 저장소가 그대로이거나 원복 가능해야 한다.

        1. 요청 자체의 모순     빈 목록 · 같은 초안 두 번
        2. 초안 상태 (빠른 거절) 없음 404 · pending 아님 409  — 아직 아무것도 안 썼다
        3. **같은 정책 둘 이상**  409 (아래 참조)
        4. 선점                 하나라도 지면 앞의 것을 전부 원복하고 409/404
        5. 반영 전 검사          막히면 선점을 전부 원복
        6. 반영                 건별 `_apply_decision`

    ★ 3 이 코디네이터 판정이다. 서로 다른 초안 A·B 가 같은 `policy_id` 를 승인하면 둘 다
      선점에 성공하고 `supersede` 에서 하나가 `StoreError` 로 터진다 — 409 가 아니라
      **500** 이다 (PR #58 「검증하지 않은 것」). 근거는 둘이다. (1) 그 요청은 「어느 쪽이
      최종인가」가 애초에 정해지지 않은 요청이고, 순서를 서버가 임의로 정하면 감사추적이
      우연에 실린다. (2) 저장소 계층 수정은 `store/` 소유라 이 과업의 범위 밖이며, 지금
      그것까지 열면 5단계가 두 소유자에 걸린다 (SPEC 9.4).
      **이것은 회피이지 해결이 아니다** — 저장소는 여전히 이 경합을 막지 못한다.
    """
    if not draft_ids:
        return _error(400, "draft_ids_required", "승인할 초안을 하나 이상 지정해야 합니다.")

    if len(set(draft_ids)) != len(draft_ids):
        repeated = sorted({d for d in draft_ids if draft_ids.count(d) > 1})
        return _error(
            409, "duplicate_draft_id",
            f"같은 초안이 한 요청에 두 번 실렸습니다: {', '.join(repeated)}. "
            "승인은 한 번만 일어납니다.",
        )

    drafts = []
    for draft_id in draft_ids:
        draft = _pending_draft_or_error(store, draft_id)
        if isinstance(draft, JSONResponse):
            return draft
        drafts.append(draft)

    by_policy: dict[str, list[str]] = {}
    for draft in drafts:
        by_policy.setdefault(draft.policy_id, []).append(draft.id)
    collisions = {policy: ids for policy, ids in by_policy.items() if len(ids) > 1}
    if collisions:
        detail = "; ".join(f"{policy}: {', '.join(ids)}" for policy, ids in sorted(collisions.items()))
        return _error(
            409, "duplicate_policy_target",
            f"한 요청 안에서 같은 정책을 가리키는 초안이 둘 이상입니다 ({detail}). "
            "어느 쪽이 최종인지 정해지지 않은 요청이므로 아무것도 반영하지 않았습니다. "
            "하나씩 승인하거나, 반영할 초안만 남겨 다시 요청하세요.",
        )

    claimed: list = []
    for draft in drafts:
        try:
            store.rule_drafts.claim_pending(draft.id, "approved")
        except DraftAlreadyDecidedError:
            _release_claims(store, claimed)
            current = store.rule_drafts.get(draft.id)
            return _already_decided(current.status if current is not None else "approved")
        except RecordNotFoundError:
            _release_claims(store, claimed)
            return _not_found(draft.id)
        claimed.append(draft)

    blocked = _approval_preflight(store, drafts, now)
    if blocked is not None:
        _release_claims(store, claimed)
        return blocked

    results = []
    unapplied = list(drafts)
    try:
        for draft in drafts:
            results.append(
                _apply_decision(store, session, draft, decision="approved", reason=reason, now=now)
            )
            unapplied.remove(draft)
    except Exception:
        # 여기까지 왔는데 터졌다면 앞의 것은 이미 반영됐고 되돌릴 수 없다 (`RuleVersion`
        # 은 불변이다). 할 수 있는 것은 **아직 반영되지 않은 초안을 놓아 주는 것**뿐이며,
        # 그래야 남은 초안이 재시도 가능한 상태로 돌아간다. 이 잔여 구간은 PR 본문 ⑥ 에
        # 적혀 있다 — 없앨 수 있는 사람은 `store` 소유자다.
        _release_claims(store, unapplied)
        raise

    return {"decision": "approved", "at": _iso(now), "results": results}


# --------------------------------------------------------------------------
# 승인 영향 사례 (SPEC 4.4 #2 · 4.1 #5 · 9.2.2) — **저장소를 건드리지 않는다**
# --------------------------------------------------------------------------
#
# 「승인 시 기존 판정이 어떻게 바뀌는지를 실제 사례로 제시」가 원칙 3 의 둘째 항목이다.
# 모집단은 `contracts/regression_profiles.json` — **실사용 프로필을 쓰지 않는다** (7.1 이
# 시민 프로필 저장을 금지하므로 애초에 쓸 것이 없다).
#
# ★ 이 계산은 **읽기만 한다.** 승인은 아직 일어나지 않았고, 여기서 저장소가 한 바이트라도
#   움직이면 [승인 없이는 판정이 바뀌지 않는다]가 이 화면에서 깨진다 (10.2 5단계 첫 줄).

REGRESSION_PROFILES_FILE = "regression_profiles.json"


def regression_profile_set() -> dict:
    """계약 원본을 그대로 읽는다. **캐시하지 않는다.**

    `ingest.extraction_verify.rule_draft_schema()` 와 같은 규율이다 — 계약을 고치고
    재기동해야 반영되는 구조를 만들지 않는다. 파일은 작고 이 경로는 검토 화면에서만 돈다.
    """
    path = contracts_dir() / REGRESSION_PROFILES_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def _json_changes(before, after, path: str = "") -> list[dict]:
    """두 판정 사이의 차이를 JSON Pointer 로 편다.

    **규칙 둘로 끝난다.** 키 집합이나 길이가 다르면 그 자리에서 통째로 내고, 같으면
    한 칸 더 들어간다. 「없음」을 표현하는 별도 표식을 만들지 않으려는 것이다 — `null`
    과 부재를 한 필드에 욱여넣으면 화면이 둘을 구분하지 못한다.
    """
    if isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
        changes: list[dict] = []
        for key in before:
            changes += _json_changes(before[key], after[key], f"{path}/{key}")
        return changes
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        changes = []
        for index, (left, right) in enumerate(zip(before, after)):
            changes += _json_changes(left, right, f"{path}/{index}")
        return changes
    if before == after:
        return []
    return [{"path": path or "/", "before": before, "after": after}]


def _verdict_or_error(profile: dict, policies: list[dict], regions: list[dict],
                      now: datetime) -> tuple[dict | None, str | None]:
    """한 프로필의 판정. 못 재면 **숨기지 않고** 사유를 돌려준다.

    `unknown_region` 축은 `analyze` 가 `ValueError` 를 던지도록 설계된 프로필이다
    (SPEC 9.2.2). 그 한 건 때문에 나머지 영향 사례가 통째로 사라지면 화면이 판단 근거를
    잃고, 조용히 빼면 검토자는 12건을 다 봤다고 믿는다.
    """
    try:
        return analyze(
            profile, constants=MODEL_CONSTANTS, regions=regions, policies=policies, now=now
        ), None
    except ValueError as exc:
        return None, str(exc)


def _approval_impact(store: Store, draft, now: datetime) -> dict:
    """승인 **전/후** 판정을 각각 계산해 달라진 프로필과 무엇이 달라졌는지를 낸다.

    「후」는 초안 그대로가 아니라 **병합 결과**다 (`_merged_payload`). 초안을 그대로 태우면
    `not_found` 가 이전 값을 지운 것처럼 보여 화면과 실제 승인 결과가 갈린다.
    """
    profile_set = regression_profile_set()
    regions = [region.to_engine_dict() for region in store.regions.list()]

    active = read_active_rule_versions(store, now)
    previous = next((v for v in active if v.policy_id == draft.policy_id), None)
    merged = _merged_payload(previous, draft)

    before_policies = [json.loads(json.dumps(v.payload)) for v in active]
    after_policies = [json.loads(json.dumps(v.payload)) for v in active]
    replaced = False
    for index, version in enumerate(active):
        if version.policy_id == draft.policy_id:
            after_policies[index] = json.loads(json.dumps(merged))
            replaced = True
    if not replaced:
        after_policies.append(json.loads(json.dumps(merged)))

    axes = profile_set.get("axes") or {}
    entries = []
    for item in profile_set["profiles"]:
        profile = item["profile"]
        before, before_error = _verdict_or_error(profile, before_policies, regions, now)
        after, after_error = _verdict_or_error(profile, after_policies, regions, now)

        if before is None or after is None:
            changes = []
            changed = before_error != after_error
            policy_before = policy_after = None
        else:
            changes = _json_changes(before, after)
            changed = bool(changes)
            policy_before = next(
                (p for p in before["policies"] if p["id"] == draft.policy_id), None
            )
            policy_after = next(
                (p for p in after["policies"] if p["id"] == draft.policy_id), None
            )

        entries.append({
            "id": item["id"],
            "axis": axes.get(item["id"], ""),
            "changed": changed,
            "changes": changes,
            "policyBefore": policy_before,
            "policyAfter": policy_after,
            "errorBefore": before_error,
            "errorAfter": after_error,
        })

    return {
        "draftId": draft.id,
        "policyId": draft.policy_id,
        "profileSetVersion": profile_set.get("setVersion", ""),
        "profileCount": len(entries),
        "changedCount": sum(1 for e in entries if e["changed"]),
        "mergedPayload": merged,
        "profiles": entries,
    }


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def _oldest_observed_at(store: Store) -> str | None:
    """등재된 지역 사실 중 **가장 오래된 관측 기준시점**. 없으면 `null` 이다 (0 이 아니다).

    요약 계보가 아니라 **필드별 계보**를 훑는다. 요약의 `observed_at` 은 필드들 중
    가장 **늦은** 값이므로(`ingest.market.pipeline._commit`), 요약만 보면 가장 오래된
    사실이 가려진다 — 신선도 칸이 실제보다 새것으로 보이게 되고, 그 방향의 오차는
    관측 화면이 낼 수 있는 가장 나쁜 종류다.
    """
    observed: list[datetime] = []
    for region in store.regions.list():
        for name in REGION_FACT_FIELDS:
            parsed = _parse_at(region.provenance_for(name).observed_at)
            if parsed is not None:
                observed.append(parsed)
    return _iso(min(observed)) if observed else None


def build_health_operations(store: Store) -> dict:
    """SPEC 8.1 — `/api/health` 의 배치 상태 · 데이터 신선도. **7.2 를 좁혀 싣는다.**

    배치는 `build_batch_status`(7.2, 아래 `/api/admin/status` 절)를 **그대로 투영**한다.
    같은 사실을 두 번 세지 않는다 — 두 벌로 세면 두 화면이 다른 수를 말할 수 있고,
    그때 어느 쪽이 맞는지는 아무도 모른다. 좁히는 것은 투영이지 재계산이 아니다.
    """
    batch = build_batch_status(store)
    return {
        "batch": {"lastRunAt": batch["lastRunAt"], "lastOutcome": batch["lastOutcome"]},
        "freshness": {"oldestObservedAt": _oldest_observed_at(store)},
    }


@app.get("/api/health", responses={200: {"model": HealthResponse}})
def health() -> dict:
    """Liveness probe.

    `llm` is the active provider: "openai" | "anthropic" | "offline".
    "offline" is a fully working mode, not an error — every feature runs
    without any API key.

    `batch` and `freshness` are the SPEC 8.1 additions. Each block is `null`
    when the store could not be read; a `null` *inside* a block means the
    store was read and there is nothing there yet.
    """
    body = {"status": "ok", "llm": get_llm_mode(), "batch": None, "freshness": None}
    # 저장소를 읽지 못해도 **200 이다.** 여기서 500 을 내면 8.1 의 [순수 추가] 가
    # 「전에 없던 실패 경로를 만든 변경」이 된다 — 계약이 이 오퍼레이션에 선언한 응답은
    # 200 하나뿐이고, 프론트(`app.js checkHealth`)와 관리 화면(`admin/app.js connect`)은
    # 이 경로 하나로 [백엔드 연결됨] 을 판정한다. 저장소가 깨졌다고 화면이 통째로
    # [미연결] 로 넘어가면 그것은 이 변경이 만든 회귀다.
    #
    # **삼키는 것이 아니다** (SPEC 6.2 침묵 폴백 금지). 못 읽었다는 사실은 두 블록이
    # `null` 로 나가는 것으로 응답에 드러나고, 그것은 [읽었으나 아직 없다] 인
    # 블록 **안**의 `null` 과 구분된다.
    try:
        with store_from_env() as store:
            body.update(build_health_operations(store))
    except Exception:
        pass
    return body


# 저장소를 매 요청 새로 읽는다 — 배치가 시세를 갱신하면 재기동 없이 이 목록이 바뀐다.
#
# ★ 이 설명이 주석이지 docstring 이 아닌 이유: FastAPI 는 docstring 을 OpenAPI 의
#   `description` 으로 싣는다. 한 줄만 보태도 `contracts/openapi.json` 이 달라지고,
#   그것은 워커가 계약을 바꾼 것이다 (SPEC 8.2 #5). 재생성 diff 테스트가 실제로 잡았다.
@app.get("/api/regions", responses={200: {"model": RegionsResponse}})
def regions() -> dict:
    """Region reference data used to populate the profile form."""
    keys = (
        "code",
        "name",
        "jeonseMedianKRW",
        "monthlyDepositKRW",
        "monthlyRentKRW",
        "maintenanceFeeKRW",
        "jeonseRatioPct",
        "source",
    )
    with store_from_env() as store:
        available = read_regions(store)
    if not available:
        return _error(500, "regions_unavailable", REGIONS_EMPTY_MESSAGE)
    return {"regions": [{k: region.get(k) for k in keys} for region in available]}


@app.post(
    "/api/analyze",
    responses={200: {"model": AnalyzeResponse}, 400: _JSON_ERROR, 422: _JSON_ERROR},
)
def analyze_endpoint(payload: ProfileRequest, request: Request):
    """Main endpoint — runs E1~E4 and returns the full decision object."""
    now = request_now()
    with store_from_env() as store:
        region_records = read_region_records(store)
        versions_now = read_active_rule_versions(store, now)
        session = optional_session(request, now=now)
    regions_now = [region.to_engine_dict() for region in region_records]
    if not regions_now:
        return _error(500, "regions_unavailable", REGIONS_EMPTY_MESSAGE)
    try:
        result = analyze(
            payload.model_dump(),
            constants=MODEL_CONSTANTS,
            regions=regions_now,
            policies=[version.payload for version in versions_now],
            now=now,
        )
    except ValueError as exc:
        return _error(400, "invalid_region", str(exc))

    # D-13 — 계보와 등급은 **역할과 무관하게** 실린다. 판정은 위에서 끝났고 여기서 다시
    # 계산되지 않는다 (`build_internal` 과 같은 규율).
    result.update(build_lineage(
        result, region_records, versions_now,
        constants=MODEL_CONSTANTS,
        constant_provenance=MODEL_CONSTANT_PROVENANCE,
    ))

    # SPEC 6.1 · Part 0-E #1 — 내부 정보는 **인증된 요청에만** 붙는다.
    # 익명이면 키 자체가 없다. 판정은 위에서 이미 끝났고 여기서 다시 계산되지 않는다.
    if session is not None and allows("analysis.internal", session.role):
        result["internal"] = build_internal(result, region_records, versions_now)
    return result


@app.post(
    "/api/chat",
    # 400 은 본문 자체가 JSON 으로 파싱되지 않는 경우다 (Starlette 가 던지고 우리
    # 오류 봉투 핸들러가 감싼다 — code=`http_400`). 실기동에서 손으로 쳐 보고 발견했다.
    # 계약에 적지 않으면 스모크가 검증할 수 없는 응답이 남는다.
    responses={200: {"model": ChatResponse}, 400: _JSON_ERROR, 422: _JSON_ERROR},
)
def chat_endpoint(payload: ChatRequest) -> dict:
    """Natural-language consultation. Falls back to a template without an API key."""
    history = [turn.model_dump() for turn in payload.history]
    now = request_now()
    with store_from_env() as store:
        regions_now = read_regions(store)
        policies_now = read_active_policies(store, now)
    if not regions_now:
        return _error(500, "regions_unavailable", REGIONS_EMPTY_MESSAGE)
    # SPEC 7.2 「LLM 호출 성공률과 지연」. **계측을 여기서 한다** — `llm/` 을 건드리지
    # 않는 이유는 그쪽이 프로바이더 추상화이고 관측은 api 의 일이기 때문이다 (SPEC 1.1).
    # 남는 것은 모드·성공여부·소요시간 셋뿐이고 대화 내용은 인자에 없다 (SPEC 7.1).
    started = time.perf_counter()
    mode = get_llm_mode()
    try:
        reply = chat(
            payload.message,
            payload.profile.model_dump(),
            history,
            constants=MODEL_CONSTANTS,
            regions=regions_now,
            policies=policies_now,
            now=now,
        )
    except Exception:
        log_llm_chat(mode=mode, outcome="failure",
                     latency_ms=(time.perf_counter() - started) * 1000)
        raise
    log_llm_chat(mode=mode, outcome="success",
                 latency_ms=(time.perf_counter() - started) * 1000)
    return reply


@app.get("/api/meta", responses={200: {"model": MetaResponse}})
def meta() -> dict:
    """Version / disclaimer metadata for the UI footer."""
    return {"engineVersion": ENGINE_VERSION, "llm": get_llm_mode(), "disclaimer": DISCLAIMER}


# --------------------------------------------------------------------------
# /api/auth/* — 인증 (SPEC 6.3 · 8.1 신규 엔드포인트)
# --------------------------------------------------------------------------

@app.post(
    "/api/auth/login",
    responses={200: {"model": SessionResponse}, 401: _JSON_ERROR, 422: _JSON_ERROR},
)
def login_endpoint(payload: LoginRequest, request: Request):
    """Start a server session. Sets an HttpOnly session cookie and a CSRF cookie."""
    now = request_now()
    username = payload.username.strip()
    with store_from_env() as store:
        user = store.users.get_by_username(username) if username else None
        if user is None:
            # 없는 계정에도 **같은 일을 시킨다.** 아니면 응답 시간만으로 계정 존재
            # 여부가 새어 나간다.
            burn_absent_user_time(payload.password)
            authenticated = False
        else:
            authenticated = verify_password(user.password_hash, payload.password)

        if not authenticated:
            # SPEC 7.1 필수 기록 — **로그인 실패.** 비밀번호는 남기지 않는다.
            record(
                store,
                actor=username or ANONYMOUS_ACTOR,
                at=now,
                action=AUDIT_LOGIN,
                target=username or ANONYMOUS_ACTOR,
                outcome="failure",
                after={"reason": "invalid_credentials"},
            )
            # 아이디가 틀렸는지 비밀번호가 틀렸는지 구분해 주지 않는다.
            return _error(
                401, "invalid_credentials", "아이디 또는 비밀번호가 올바르지 않습니다."
            )

        session = SESSIONS.create(user, now=now)
        record(
            store,
            actor=user.username,
            at=now,
            action=AUDIT_LOGIN,
            target=user.username,
            outcome="success",
            after={"role": user.role},
        )

    return _set_session_cookies(
        JSONResponse(
            status_code=200,
            content={
                "authenticated": True,
                "username": session.username,
                "role": session.role,
                "csrfToken": session.csrf_token,
            },
        ),
        session,
    )


@app.post(
    "/api/auth/logout",
    responses={200: {"model": LogoutResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR},
)
def logout_endpoint(request: Request):
    """End the current session. Requires the CSRF token (state-changing)."""
    now = request_now()
    with store_from_env() as store:
        session = authorize(request, "session.end", now=now, store=store, require_csrf=True)
        SESSIONS.delete(session.id)
        record(
            store,
            actor=session.username,
            at=now,
            action=AUDIT_LOGOUT,
            target=session.username,
            outcome="success",
        )
    return _clear_session_cookies(
        JSONResponse(status_code=200, content={"ok": True, "message": "로그아웃되었습니다."})
    )


@app.get("/api/auth/session", responses={200: {"model": SessionResponse}})
def session_endpoint(request: Request):
    """Who am I. Anonymous is a 200 with `authenticated: false`, not a 401."""
    session = optional_session(request, now=request_now())
    if session is None:
        return {"authenticated": False, "username": None, "role": None, "csrfToken": None}
    return {
        "authenticated": True,
        "username": session.username,
        "role": session.role,
        "csrfToken": session.csrf_token,
    }


# --------------------------------------------------------------------------
# /api/reports — 상담원 이상 신고 (SPEC 6.4)
# --------------------------------------------------------------------------
#
# ★ `/api/admin/*` 아래에 두지 않는다. 그쪽은 규칙관리자 전용 구역이고, 이것은
#   **상담원이 여는** 경로다. 큐 조회(`/api/admin/reports`)만 그쪽에 선다.

@app.post(
    "/api/reports",
    responses={
        200: {"model": ReportRef}, 400: _JSON_ERROR, 401: _JSON_ERROR,
        403: _JSON_ERROR, 422: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "counselor"},
)
def create_report_endpoint(payload: ReportRequest, request: Request):
    """File a field anomaly report. A proposal — never a rule change (SPEC 6.4)."""
    now = request_now()
    with store_from_env() as store:
        session = authorize(request, "report.create", now=now, store=store, require_csrf=True)

        invalid = _report_target_error(store, payload)
        if invalid is not None:
            return invalid

        report = store.reports.add(
            AnomalyReport(
                id=f"report:{uuid4().hex}",
                # 신고자는 **세션에서 온다.** 본문에서 받으면 사칭이 가능해지고,
                # 그 순간 6.4 의 「신고자를 남긴다」가 자기 신고에 대해서만 참이 된다.
                reporter=session.username,
                at=now,
                target_kind=payload.targetKind,
                target_id=payload.targetId,
                target_field=payload.targetField,
                reason=payload.reason.strip(),
                status=REPORT_INITIAL_STATUS,
            )
        )

        # SPEC 6.4 — 신고자·시각·대상·사유. 네 자리에 그대로 대응한다.
        #
        # ★ 사유 본문이 여기 실린다. 6.4 가 명시적으로 요구한 것이며(7.1 은 **파일 로그**
        #   에 본문을 찍지 말라고 한 것이지 감사기록을 비우라고 하지 않았다), 그 결과
        #   자유 입력이 append-only 원장에 남는다. 지우는 경로는 구조상 없다 —
        #   기계로 막을 수 없는 부분이며 화면 문구가 그 앞에 서 있을 뿐이다.
        record(
            store,
            actor=report.reporter,
            at=now,
            action=AUDIT_REPORT_CREATED,
            target=f"{report.target_kind}:{report.target_id}#{report.target_field}",
            outcome="created",
            after={"reportId": report.id, "reason": report.reason},
        )
        return _report_ref(report, _pending_drafts_for(store, report.target_id)
                           if report.target_kind == "policy" else [])


# --------------------------------------------------------------------------
# /api/admin/* — 규칙관리자 전용 (SPEC 6.1 · 8.1)
# --------------------------------------------------------------------------
#
# ★ **상담원은 여기 어디에도 들어오지 못한다.** 그것이 이 단계의 산출물이다 (SoD).
#   검사는 `authorize()` 가 하고, 화면이 버튼을 숨기는 것에 기대지 않는다 (SPEC 6.1).

@app.get(
    "/api/admin/drafts",
    responses={200: {"model": DraftListResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR},
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_drafts_endpoint(request: Request):
    """List extraction drafts awaiting review."""
    now = request_now()
    with store_from_env() as store:
        authorize(request, "draft.read", now=now, store=store)
        drafts = [
            {
                "id": draft.id,
                "policyId": draft.policy_id,
                "policySourceId": draft.policy_source_id,
                "status": draft.status,
                "createdAt": _iso(draft.created_at),
                "failureReason": draft.failure_reason,
            }
            for draft in store.rule_drafts.list()
        ]
    return {"drafts": drafts}


def _span_view(store: Store, span, occurrences: int) -> dict:
    return {
        "fieldPath": span.field_path,
        "start": span.start,
        "end": span.end,
        "quote": store.rule_drafts.resolve_span(span),
        "occurrences": occurrences,
        "ambiguous": occurrences > 1,
    }


#: 경로 변수 하나짜리 GET 의 파라미터 선언. **손으로 적는 이유가 있다** — 아래 두
#: 엔드포인트는 `draft_id` 를 함수 인자가 아니라 `request.path_params` 에서 읽는다.
#:
#: FastAPI 는 타입 붙은 파라미터가 하나라도 있으면 **422 를 자동으로 계약에 넣는다.**
#: 그런데 `draft_id: str` 은 어떤 값이 와도 검증에 실패하지 않으므로 그 422 는 **일어날 수
#: 없는 상태**다. 계약에 적힌 상태는 스모크가 실제로 쳐서 확인해야 하고(SPEC 9.1.2 ·
#: `test_every_contracted_status_code_was_exercised`), 칠 수 없는 상태를 적어 두면
#: 계약이 거짓을 말하게 된다. 승인·반려는 **본문**이 있어 422 가 실제로 나므로 그쪽은
#: 그대로 둔다 — 여기만 다른 것이 아니라 **여기만 본문이 없다.**
_DRAFT_ID_PARAM = [{
    "name": "draft_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "RuleDraft.id. 검증 규칙이 없으므로 이 파라미터로는 422 가 발생하지 않는다.",
}]


@app.get(
    "/api/admin/drafts/{draft_id}",
    responses={
        200: {"model": DraftDetailResponse}, 401: _JSON_ERROR,
        403: _JSON_ERROR, 404: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "rule_manager", "parameters": _DRAFT_ID_PARAM},
)
def admin_draft_detail_endpoint(request: Request):
    """One draft with everything a reviewer needs to decide (SPEC 4.4 #1 · #3).

    **읽기만 한다.** 승인은 아직 일어나지 않았으므로 저장소가 움직이면 안 된다.
    """
    draft_id = request.path_params["draft_id"]
    now = request_now()
    with store_from_env() as store:
        authorize(request, "draft.read", now=now, store=store)
        draft = store.rule_drafts.get(draft_id)
        if draft is None:
            return _not_found(draft_id)

        source = store.policy_sources.get(draft.policy_source_id)
        text = source.text if source is not None else ""
        spans = store.rule_drafts.spans_for(draft.id)
        views = {}
        for span in spans:
            quote = store.rule_drafts.resolve_span(span)
            views[span.field_path] = _span_view(store, span, text.count(quote) if quote else 0)

        previous = next(
            (v for v in read_active_rule_versions(store, now) if v.policy_id == draft.policy_id),
            None,
        )
        previous_payload = dict(previous.payload) if previous is not None else {}
        merged = _merged_payload(previous, draft)

        return {
            "draft": {
                "id": draft.id,
                "policyId": draft.policy_id,
                "policySourceId": draft.policy_source_id,
                "status": draft.status,
                "createdAt": _iso(draft.created_at),
                "failureReason": draft.failure_reason,
                "payload": draft.payload,
                "notFound": list(draft.payload.get("not_found") or ()),
            },
            "source": None if source is None else {
                "id": source.id,
                "sourceRef": source.source_ref,
                "attribution": source.attribution,
                "fetchedAt": _iso(source.fetched_at),
                "length": len(text),
                "segments": _highlight_segments(text, spans),
            },
            "spans": [views[span.field_path] for span in spans],
            "current": None if previous is None else {
                "ruleVersionId": previous.id,
                "policyId": previous.policy_id,
                "origin": previous.origin,
                "effectiveFrom": _iso(previous.effective_from),
                "effectiveTo": _iso(previous.effective_to),
                "payload": previous.payload,
            },
            "merged": merged,
            "changeType": "requirement_change" if previous is not None else "new",
            "fields": _field_changes(previous_payload, draft, merged, views),
            # SPEC 6.4 (잠정) — 같은 정책을 겨눈 현장 신고를 컨텍스트로 붙인다.
            "reports": _reports_for_draft(store, draft.policy_id),
            "limitations": list(REVIEW_LIMITATIONS),
        }


@app.get(
    "/api/admin/drafts/{draft_id}/impact",
    responses={
        200: {"model": ImpactResponse}, 401: _JSON_ERROR,
        403: _JSON_ERROR, 404: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "rule_manager", "parameters": _DRAFT_ID_PARAM},
)
def admin_draft_impact_endpoint(request: Request):
    """What approving this draft would do to the verdicts (SPEC 4.4 #2).

    ★ **저장소를 건드리지 않는다.** 승인 전/후 판정을 메모리에서 두 번 계산할 뿐이다.
    """
    draft_id = request.path_params["draft_id"]
    now = request_now()
    with store_from_env() as store:
        authorize(request, "draft.read", now=now, store=store)
        draft = store.rule_drafts.get(draft_id)
        if draft is None:
            return _not_found(draft_id)
        return _approval_impact(store, draft, now)


@app.post(
    "/api/admin/drafts/batch-approve",
    responses={
        200: {"model": BatchDecisionResponse}, 400: _JSON_ERROR, 401: _JSON_ERROR,
        403: _JSON_ERROR, 404: _JSON_ERROR, 409: _JSON_ERROR, 422: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_batch_approve_endpoint(payload: BatchApproveRequest, request: Request):
    """Approve several drafts as one atomic reflection, one ApprovalRecord each.

    ★ 이 라우트는 `/api/admin/drafts/{draft_id}/approve` **앞에** 선언한다. 뒤에 두면
      경로 매칭이 `batch-approve` 를 초안 id 로 읽을 여지가 생긴다 — 지금은 세그먼트
      수가 달라 충돌하지 않지만, 그 사실에 기대는 것과 순서로 못박는 것은 다르다.
    """
    now = request_now()
    with store_from_env() as store:
        session = authorize(request, "draft.decide", now=now, store=store, require_csrf=True)
        return _batch_approve(
            store, session, list(payload.draftIds), reason=payload.reason, now=now
        )


@app.post(
    "/api/admin/drafts/{draft_id}/approve",
    responses={
        200: {"model": DecisionResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR,
        404: _JSON_ERROR, 409: _JSON_ERROR, 422: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_approve_endpoint(draft_id: str, payload: DecisionRequest, request: Request):
    """Approve a draft into a new immutable RuleVersion."""
    now = request_now()
    with store_from_env() as store:
        session = authorize(request, "draft.decide", now=now, store=store, require_csrf=True)
        draft = _pending_draft_or_error(store, draft_id)
        if isinstance(draft, JSONResponse):
            return draft
        return _decide(store, session, draft, decision="approved",
                       reason=payload.reason, now=now)


@app.post(
    "/api/admin/drafts/{draft_id}/reject",
    responses={
        200: {"model": DecisionResponse}, 400: _JSON_ERROR, 401: _JSON_ERROR,
        403: _JSON_ERROR, 404: _JSON_ERROR, 409: _JSON_ERROR, 422: _JSON_ERROR,
    },
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_reject_endpoint(draft_id: str, payload: DecisionRequest, request: Request):
    """Reject a draft. A reason is mandatory and no RuleVersion is created."""
    now = request_now()
    reason = (payload.reason or "").strip()
    with store_from_env() as store:
        session = authorize(request, "draft.decide", now=now, store=store, require_csrf=True)
        draft = _pending_draft_or_error(store, draft_id)
        if isinstance(draft, JSONResponse):
            return draft
        # SPEC 10.2 5단계 — 사유 없이 반려할 수 없다. 저장소의 CHECK 제약이 두 번째 겹이고
        # 여기가 첫 번째다. 400 으로 먼저 답하는 이유는 사용자에게 무엇이 빠졌는지
        # 말해 주기 위해서이며, 이 검사를 지워도 저장소가 여전히 막는다.
        if not reason:
            return _error(400, "reason_required", "반려에는 사유가 필요합니다.")
        return _decide(store, session, draft, decision="rejected", reason=reason, now=now)


@app.get(
    "/api/admin/reports",
    responses={200: {"model": ReportListResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR},
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_reports_endpoint(request: Request):
    """The field-report queue — a **separate type** from extraction drafts (SPEC 6.4)."""
    now = request_now()
    with store_from_env() as store:
        authorize(request, "report.read", now=now, store=store)
        return {"reports": _merge_reports(store, store.reports.list())}


@app.get(
    "/api/admin/audit",
    responses={200: {"model": AuditListResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR},
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_audit_endpoint(request: Request):
    """Read the append-only audit trail (SPEC 7.1)."""
    now = request_now()
    with store_from_env() as store:
        authorize(request, "audit.read", now=now, store=store)
        events = [
            {
                "id": event.id,
                "actor": event.actor,
                "at": _iso(event.at),
                "action": event.action,
                "target": event.target,
                "outcome": event.outcome,
                "before": event.before,
                "after": event.after,
            }
            for event in store.audit.list()
        ]
    return {"events": events}


# --------------------------------------------------------------------------
# /api/admin/status — SPEC 7.2 관측 지표 · 7.3 대기 큐
# --------------------------------------------------------------------------
#
# **외부 APM 을 도입하지 않는다** (SPEC 7.2). 지표의 출처는 둘뿐이다 —
#
#   · **저장소** (`AuditEvent` · `RuleDraft` · `Region` · `AnomalyReport`) — 배치·추출·
#     대기 큐·신선도. 배치는 별도 프로세스이므로 프로세스 메모리에 센 수는 화면에 닿지 않는다.
#   · **파일 로그** — `/api/chat` 의 LLM 호출. 익명 경로라 append-only 원장에 실을 수 없다
#     (`log_llm_chat` 의 주석).
#
# 어느 지표가 어느 출처에서 왔는지는 응답의 `source` · `denominator` 필드가 말한다.
# 출처를 적지 않은 숫자는 나중에 아무도 검증하지 못한다.

#: 배치 실행 단위 기록의 action (`ingest.market.pipeline.ACTION_RUN`).
#:
#: ★ **여기에 다시 적는 이유.** SPEC 1.2 의 의존 그래프에 `api -> ingest` 가 없다.
#:   문자열을 import 로 끌어오면 그 간선이 생긴다. 대신 두 벌이 어긋나는 것을
#:   `backend/tests/api/test_status_metrics.py` 가 잡는다 — 그쪽은 테스트라 양쪽을
#:   다 볼 수 있다. [정본은 저쪽, 어긋남은 테스트가 잡는다] 는 이 저장소의 기존 규약이다.
MARKET_RUN_ACTION = "market.run"

#: 추출 1건의 기록 (`ingest.extraction.EXTRACTION_ACTION`). 같은 규약.
EXTRACTION_ACTION = "rule_draft.extract"

#: 추출 실패를 뜻하는 `outcome`. 성공은 `pending` 이다 — 초안은 승인 전까지 대기다.
EXTRACTION_FAILED_OUTCOME = "extraction_failed"

#: 7.2 배치 성공률의 **분모 정의.** 숫자 옆에 이 문장이 그대로 붙는다.
BATCH_DENOMINATOR = (
    "market.run 감사기록 1행 = 시세 수집 배치 1회. 지역별 market.ingest 행이 아니라 "
    "실행 자체를 센다 — 멱등 재실행은 같은 시각을 쓰므로 시각으로는 두 실행이 구분되지 않는다."
)

#: 신선도 — **판정하지 않는다** (SPEC 2.4 · 계약 결정 #39).
FRESHNESS_NOTE = (
    "며칠부터 stale 인지가 미정이라 신선도를 판정하지 않는다 (SPEC 2.4 · 계약 결정 #39). "
    "아래는 관측된 취득 시각과 계보가 이미 말하고 있는 verification 분포일 뿐이며, "
    "「기준 이내」 여부는 이 화면이 말하지 않는다."
)

#: 추출 실패율 — **합격선이 없다** (계약 결정 #33 · SPEC 4.2.2 · 10.2 2단계).
EXTRACTION_NOTE = (
    "합격선을 두지 않는다 (사용자 결정 2026-08-14 · 계약 결정 #33). 표본 7건에 문턱을 "
    "걸면 한 건이 잡음으로 판정을 뒤집는다. 실패율을 노출만 하고 통과/불통과를 말하지 않는다."
)

#: 대기 큐 — **SLA N 이 없다** (SPEC 7.3).
#:
#: ★ 값 안에는 마크다운을 쓰지 않는다. `admin/app.js` 의 지표 카드가 이 문자열을
#:   `textContent` 로 넣으므로 `**` 가 화면에 별표 그대로 찍힌다. 강조가 필요하면
#:   문장으로 한다 — 이 주석처럼 **코드에서만** 쓴다.
OVERDUE_NOTE = (
    "SLA N값이 미정이라 초과 여부를 판정하지 않는다 (SPEC 7.3 — 변경 유형별 실제 발생 "
    "빈도를 모르면 정할 수 없다). 「초과 0건」이 아니라 판정하지 않았다. 대기 건수와 "
    "최장 대기일은 관측된 사실이므로 그대로 싣는다."
)

#: 신고 — **닫는 경로가 없다** (SPEC 6.4 · 계약 결정 #38).
REPORTS_NOTE = (
    "신고를 큐에서 내보내는 경로가 SPEC 의 어느 단계에도 배정되지 않았다. 초안은 승인·반려로 "
    "큐를 떠나지만 신고는 떠나지 않는다 — 그래서 이 수는 「밀린 일」이 아니라 누적이며 "
    "늘기만 한다. 승인 대기 건수와 더하지 않는 이유가 그것이다."
)


def _rate_pct(numerator: int, denominator: int) -> float | None:
    """비율. **분모가 0 이면 `None` 이다** — 0% 와 「아직 없다」는 다른 사실이다."""
    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator, 1)


def _distribution(values: list[float], unit: str) -> dict:
    """지연 분포. 표본이 없으면 값이 아니라 `null` 이다."""
    if not values:
        return {"samples": 0, "p50": None, "max": None, "unit": unit}
    ordered = sorted(values)
    # p50 은 하위 중앙값이다. 보간하지 않는 이유는 표본이 한 자리 수일 때 보간값이
    # **관측되지 않은 숫자**가 되기 때문이다 — 그것을 관측값 옆에 나란히 두지 않는다.
    return {
        "samples": len(ordered),
        "p50": round(ordered[(len(ordered) - 1) // 2], 1),
        "max": round(ordered[-1], 1),
        "unit": unit,
    }


def _age_days(earlier: datetime, now: datetime) -> float:
    return round((now - earlier).total_seconds() / 86400.0, 2)


def _parse_at(value: str | None) -> datetime | None:
    """계보의 시각 문자열. 못 읽으면 `None` — 지어내지 않는다."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def build_batch_status(store: Store) -> dict:
    """7.2 배치 성공률. 출처는 `market.run` 감사기록이다."""
    runs = store.audit.list(action=MARKET_RUN_ACTION)
    succeeded = sum(1 for e in runs if e.outcome == "success")
    return {
        "runs": len(runs),
        "succeeded": succeeded,
        "failed": len(runs) - succeeded,
        "successRatePct": _rate_pct(succeeded, len(runs)),
        "lastRunAt": _iso(runs[-1].at) if runs else None,
        "lastOutcome": runs[-1].outcome if runs else None,
        "denominator": BATCH_DENOMINATOR,
    }


def build_freshness_status(store: Store, *, now: datetime) -> dict:
    """7.2 데이터 신선도. **판정하지 않는다** (결정 #39)."""
    regions = store.regions.list()
    counts: dict[str, int] = {}
    fetched: list[datetime] = []
    for region in regions:
        for name in REGION_FACT_FIELDS:
            provenance = region.provenance_for(name)
            counts[provenance.verification] = counts.get(provenance.verification, 0) + 1
            parsed = _parse_at(provenance.fetched_at)
            if parsed is not None:
                fetched.append(parsed)
    oldest = min(fetched) if fetched else None
    return {
        "regions": len(regions),
        "oldestFetchedAt": _iso(oldest),
        "newestFetchedAt": _iso(max(fetched)) if fetched else None,
        "oldestAgeDays": None if oldest is None else _age_days(oldest, now),
        "verification": dict(sorted(counts.items())),
        # 임계가 없으므로 판정이 존재할 수 없다. `False` 는 이 화면의 사실이지 값이 아니다.
        "thresholdEvaluated": False,
        "note": FRESHNESS_NOTE,
    }


def build_extraction_status(store: Store) -> tuple[dict, dict]:
    """7.2 추출 스키마 실패율과 **추출 경로의 LLM 지연**을 같은 기록에서 낸다.

    둘을 한 번에 세는 이유는 출처가 같은 행이기 때문이다 — 두 번 순회하면 분모가
    갈라질 수 있고, 갈라진 분모는 두 숫자가 같은 사건을 말하지 않게 만든다.
    """
    events = store.audit.list(action=EXTRACTION_ACTION)
    failed = sum(1 for e in events if e.outcome == EXTRACTION_FAILED_OUTCOME)
    codes: dict[str, int] = {}
    latencies: list[float] = []
    for event in events:
        after = event.after or {}
        for code in after.get("codes", []) or []:
            codes[str(code)] = codes.get(str(code), 0) + 1
        latency = after.get("latency_s")
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))
    extraction = {
        "drafts": len(events),
        "failed": failed,
        "failureRatePct": _rate_pct(failed, len(events)),
        "codes": dict(sorted(codes.items())),
        # 합격선은 **없다.** `null` 이 [아직 안 정했다] 가 아니라 [두지 않기로 했다] 라는
        # 것은 옆의 `note` 가 말한다 (계약 결정 #33).
        "passLine": None,
        "note": EXTRACTION_NOTE,
    }
    llm = {
        "calls": len(events),
        "succeeded": len(events) - failed,
        "failed": failed,
        "successRatePct": _rate_pct(len(events) - failed, len(events)),
        # ★ 지연 표본이 호출 수보다 적을 수 있다. `latency_s` 는 7단계에 들어간 필드라
        #   그 전에 남은 기록에는 없다. `samples` 를 따로 싣는 이유가 그것이다 —
        #   호출 수로 나눠 그리면 옛 기록이 [0ms 였다] 로 읽힌다.
        "latency": _distribution(latencies, "s"),
        "source": "AuditEvent(rule_draft.extract) — 추출 배치가 남긴 기록",
    }
    return extraction, llm


def build_chat_llm_status() -> tuple[dict, dict]:
    """`/api/chat` 의 LLM 호출. 출처는 **파일 로그**다 (SPEC 7.2)."""
    records, broken = read_log_records()
    calls = [r for r in records if r.get("event") == LOG_EVENT_LLM_CHAT]
    succeeded = sum(1 for r in calls if r.get("outcome") == "success")
    latencies = [float(r["latencyMs"]) for r in calls
                 if isinstance(r.get("latencyMs"), (int, float))]
    path = log_file_path()
    channel = {
        "calls": len(calls),
        "succeeded": succeeded,
        "failed": len(calls) - succeeded,
        "successRatePct": _rate_pct(succeeded, len(calls)),
        "latency": _distribution(latencies, "ms"),
        "source": f"파일 로그({LOG_EVENT_LLM_CHAT}) — {path.name}",
    }
    log = {
        "path": str(path),
        "exists": path.exists(),
        "records": len(records),
        # 깨진 줄과 못 쓴 줄을 **화면까지 올린다.** 둘 다 0 이 아니면 위 분모가 모자란다.
        "unreadableLines": broken,
        "writeFailures": _LOG_WRITE_FAILURES,
    }
    return channel, log


def build_queue_status(store: Store, *, now: datetime) -> dict:
    """7.3 대기 큐. **`overdue` 를 판정하지 않는다** — N 이 없으면 그 판정은 존재할 수 없다."""
    pending = [d for d in store.rule_drafts.list(status="pending")]
    oldest = min((d.created_at for d in pending), default=None)
    return {
        "pending": len(pending),
        "oldestPendingAt": _iso(oldest),
        "longestWaitDays": None if oldest is None else _age_days(oldest, now),
        "overdue": None,
        "overdueNote": OVERDUE_NOTE,
    }


def build_reports_status(store: Store, *, now: datetime) -> dict:
    """6.4 현장 신고. **승인 대기 건수와 한 수로 뭉치지 않는다.**

    초안은 승인·반려로 큐를 떠나지만 신고는 떠나는 경로가 없다. 둘을 더하면 그 합은
    「밀린 일」이 아니라 **누적 카운터**가 되고, 늘 커지기만 하는 수는 정보가 아니다.
    """
    reports = store.reports.list()
    open_reports = [r for r in reports if r.status == REPORT_INITIAL_STATUS]
    oldest = min((r.at for r in open_reports), default=None)
    return {
        "open": len(open_reports),
        "total": len(reports),
        "oldestOpenAt": _iso(oldest),
        "longestOpenDays": None if oldest is None else _age_days(oldest, now),
        "note": REPORTS_NOTE,
    }


@app.get(
    "/api/admin/status",
    responses={200: {"model": StatusResponse}, 401: _JSON_ERROR, 403: _JSON_ERROR},
    openapi_extra={"x-requires-role": "rule_manager"},
)
def admin_status_endpoint(request: Request):
    """Observability metrics for the status screen (SPEC 7.2 · 7.3)."""
    now = request_now()
    chat_channel, log_status = build_chat_llm_status()
    with store_from_env() as store:
        authorize(request, "status.read", now=now, store=store)
        extraction, extraction_llm = build_extraction_status(store)
        return {
            "generatedAt": _iso(now),
            "batch": build_batch_status(store),
            "freshness": build_freshness_status(store, now=now),
            "llm": {"chat": chat_channel, "extraction": extraction_llm},
            "extraction": extraction,
            "queue": build_queue_status(store, now=now),
            "reports": build_reports_status(store, now=now),
            "log": log_status,
        }


# --------------------------------------------------------------------------
# 계약 파일 생성 (D-12) — `python scripts/gen_contracts.py`
# --------------------------------------------------------------------------
#
# 생성 방향은 단방향이다 (SPEC 1.2): `api` 가 `contracts/openapi.json` 을 만들고,
# 그 파일에서 프론트 상수 모듈이 나온다(D-11, 다음 웨이브). 생성물을 고쳐 원본에
# 반영하는 역방향은 계약 드리프트의 발생 경로이므로 금지된다.
#
# 재생성 diff 테스트가 커밋본과 **바이트 비교**한다. 그 비교가 성립하려면 직렬화가
# 결정적이어야 한다 — FastAPI 가 뱉는 dict 를 그대로 `json.dumps` 하면 파이썬 dict
# 삽입 순서가 그대로 실려 버전·코드 순서에 따라 흔들린다.

#: `contracts/openapi.json` 의 `info.version` (SPEC 8.4). **`ENGINE_VERSION` 과 분리한다** —
#: 8.4 는 `ENGINE_VERSION` 을 "판정 출력이 달라지면 올린다"로, 이 값을 "8.2 절차로만
#: 변경"으로 각각 규정한다. 묶어 두면 1-② 의 값 교체가 계약 버전을 8.2 절차 없이
#: 올리게 된다. 실제 엔진 버전은 `info.x-engine-version` 으로 함께 싣는다.
#:
#: 1.0.0 -> 2.0.0 (1-③, 8.2 절차 완료 · 코디네이터 승인 2026-08-14): 응답 스키마에서
#: `affordability.schwabeIndexPct` 가 **빠지고** `scenarios[].schwabeIndexPct` 가 생겼다
#: (SPEC 5.2.1 F-1 · 8.1 「이미 확정된 예외 1건」). 필드 제거는 소비자를 깨뜨리므로 major 다.
API_CONTRACT_VERSION = "2.0.0"

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
OPENAPI_PATH = CONTRACTS_DIR / "openapi.json"

#: SPEC 8.2 #4 — 단위를 계약에 명시한다. 예선에서 같은 금액을 백엔드는 내림, 프론트는
#: 반올림해 80만/81만으로 갈렸다. 규칙이 계약에 없으면 양쪽이 각자 정한다.
X_UNITS = {
    "$comment": "SPEC 8.2 #4 · D-12. 필드명 접미사가 단위를 결정한다. 접미사가 없는 수치 필드는 아래에 전수 열거하며, 열거되지 않은 것이 생기면 교차 테스트가 실패한다.",
    "fieldSuffix": {
        "KRW": {
            "unit": "원",
            "jsonType": "integer",
            "note": "원 단위 정수. 응답에 실리는 금액은 엔진 계산값 그대로이며 표시용 반올림이 적용되지 않았다.",
        },
        "Pct": {
            "unit": "퍼센트 포인트",
            "jsonType": "number",
            "note": "60.0 은 60% 그 자체다. 100 으로 나누지 않는다 (model_constants.json 의 percent_level 과 같은 규약).",
        },
    },
    "$keyFormat": "<components.schemas 이름>/<property 이름>",
    "unsuffixedNumericFields": {
        "AffordabilityBreakdown/netIncome": "원",
        "AffordabilityBreakdown/livingCost": "원",
        "AffordabilityBreakdown/existingDebt": "원",
        "AffordabilityBreakdown/buffer": "원",
        "ScenarioComponents/interest": "원",
        "ScenarioComponents/rent": "원",
        "ScenarioComponents/maintenance": "원",
        "ScenarioComponents/opportunityCost": "원",
        "ScenarioComponents/insurance": "원",
        "Scenario/fitScore": "점 (0~100 척도)",
        "Risk/score": "점 (0~100 척도)",
        "ProfileRequest/age": "세",
        "ProfileRequest/householdSize": "명",
        # 5단계 검토 화면 (SPEC 4.4). ★ 아래 셋은 **코드포인트**다 — 바이트도 UTF-16
        # 코드유닛도 아니다 (SPEC 4.2.1). 이 표에 단위를 적어 두는 것이 [화면이 자기
        # 언어의 문자열 인덱스로 자르면 어긋난다]를 계약이 말하는 유일한 자리다.
        "SourceView/length": "코드포인트 (SPEC 4.2.1 · UTF-16 코드유닛 아님)",
        "SpanView/start": "코드포인트 인덱스 (반열린 구간의 시작, 포함)",
        "SpanView/end": "코드포인트 인덱스 (반열린 구간의 끝, 제외)",
        "SpanView/occurrences": "회 (이 인용이 원문에 나타나는 횟수)",
        "ImpactResponse/profileCount": "건 (회귀 프로필 수)",
        "ImpactResponse/changedCount": "건 (판정이 달라진 프로필 수)",
        # D-13 계보. **양이 아니라 위치다** — 그래서 단위 칸에 [단위 없음]을 적는다.
        # 비워 두면 이 검사가 [단위를 못 정한 수치]와 [단위 개념이 없는 수치]를 구분하지
        # 못하고, 다음 사람이 여기에 「건」 같은 것을 채워 넣는다.
        "DataGradeReason/provenanceIndex": (
            "단위 없음 — `provenance` 배열의 0-기반 인덱스다. "
            "사실에 걸리지 않는 사유(`freshness_not_evaluated`)는 `null` 이다."
        ),
        # 7단계 관측 지표 (SPEC 7.2 · 7.3).
        #
        # ★ **「건」과 「일」을 섞지 않는다.** 대기 큐에는 둘이 나란히 있고(대기 건수 ·
        #   최장 대기일) 한쪽을 다른 쪽 단위로 읽으면 화면이 통째로 뒤집힌다.
        # ★ `null` 이 올 수 있는 자리는 단위 설명에 **왜** 를 적는다. 0 과 `null` 의 차이가
        #   이 화면의 전부이므로, 단위표가 그 구분을 말하지 않으면 소비자가 0 으로 채운다.
        "StatusBatch/runs": "회 (market.run 감사 행 수 = 시세 수집 배치 실행 횟수)",
        "StatusBatch/succeeded": "회",
        "StatusBatch/failed": "회",
        "StatusFreshness/regions": "개 (등재된 Region 수)",
        "StatusFreshness/oldestAgeDays": (
            "일 — 가장 오래된 `fetched_at` 으로부터 지난 날짜. **판정이 아니라 관측이다** — "
            "신선도 임계가 미정이라 이 수가 `stale` 을 뜻하지 않는다 (계약 결정 #39). "
            "수집 이력이 없으면 `null` 이며 0 이 아니다."
        ),
        "StatusLatency/samples": "건 (지연이 기록된 호출 수. 호출 수와 다를 수 있다)",
        "StatusLatency/p50": (
            "단위 없음 — 값의 단위는 같은 객체의 `unit` 필드가 싣는다 "
            "(채팅은 `ms`, 추출은 `s`). 표본이 0 이면 `null` 이며 0 이 아니다."
        ),
        "StatusLatency/max": "단위 없음 — `StatusLatency/p50` 와 같다.",
        "StatusLlmChannel/calls": "회 (LLM 호출 수)",
        "StatusLlmChannel/succeeded": "회",
        "StatusLlmChannel/failed": "회",
        "StatusExtraction/drafts": "건 (추출을 시도한 초안 수)",
        "StatusExtraction/failed": "건 (검증에서 거부된 초안 수)",
        "StatusQueue/pending": "건 (승인 대기 중인 초안 수)",
        "StatusQueue/longestWaitDays": (
            "일 — 가장 오래 기다린 초안의 대기 일수. **초과 여부가 아니다** — "
            "SLA N 이 미정이라 이 화면은 초과를 판정하지 않는다 (SPEC 7.3). "
            "대기 건수가 0 이면 `null` 이다."
        ),
        "StatusReports/open": "건 (닫히지 않은 신고 수 — **누적이다**, 밀린 일이 아니다)",
        "StatusReports/total": "건 (신고 전수)",
        "StatusReports/longestOpenDays": "일 — 가장 오래된 미종결 신고의 경과 일수. 없으면 `null`.",
        "StatusLog/records": "줄 (파일 로그에서 읽어낸 JSON 줄 수)",
        "StatusLog/unreadableLines": "줄 (JSON 으로 해석되지 않은 줄 수. 0 이 아니면 위 분모가 모자란다)",
        "StatusLog/writeFailures": "회 (파일에 쓰지 못한 횟수. 0 이 아니면 LLM 지표가 실제보다 적다)",
    },
    "enforcedBy": "backend/tests/crosscheck/test_openapi_contract.py",
}

#: SPEC 8.2 #4 의 반올림 절.
X_ROUNDING = {
    "$comment": "SPEC 8.2 #4. 응답의 수치와 화면 표시 문자열은 다른 규칙을 따른다. 그 구분이 없으면 예선의 80만/81만 사고가 재발한다.",
    "responseValues": "응답의 정수 금액은 엔진이 만든 값이다. 소비자가 다시 반올림하지 않는다.",
    "engineInternal": {
        "floorTo": "backend common.floor_to(value, unit) — unit 단위 내림, 0 하한. 기본 unit 은 10,000원(만원).",
        "depositRoundingUnitKRW": "ModelConstant tco.deposit_rounding_unit_krw",
        "monthlyRoundingUnitKRW": "ModelConstant tco.monthly_rounding_unit_krw",
    },
    "displayFormatting": {
        "$status": "확정 — SPEC 9.1.1 · 계약 결정 #16. 정본 픽스처는 contracts/format_golden.json 이며 파이썬과 JS 두 구현이 **같은 파일에 대해** 테스트된다. 정본을 고른 기준은 언어가 아니라 하나뿐이다 — **정보를 버리지 않는 쪽.**",
        "$arbiter": "contracts/format_golden.json. 이 서술과 픽스처가 어긋나면 픽스처가 정본이다.",
        "money": "만원 단위 **half-up** 반올림(은행가 반올림 아님 — 25,000원은 '3만원'이다). **부호를 보존한다**(-750,000 → '-75만원'). 1억 이상은 '<억>억 <만>만원', 1만 이상은 '<만>만원', 그 미만은 '<원>원'. 억 경계에서 만 자리가 올림되면 자리올림한다(199,999,000 → '2억원').",
        "pct": "**고정 소수 자릿수**. 무의미한 0 을 제거하지 않는다(pct(25.0, 1) → '25.0%'). 제거하면 정확한 25 와 반올림된 25 가 구분되지 않는데, F-1 이후 슈바베지수가 측정값이라 그 정밀도가 정보를 담는다.",
    },
}

#: SPEC 6.1 · Part 0-E #1 — 인증은 4단계지만 **표기 자리는 계약이 먼저 갖는다.**
X_ROLE_ANNOTATIONS = {
    "$comment": "SPEC 6.1 · Part 0-E #1. /api/analyze 는 역할별로 스키마가 갈리지 않는다. 내부 정보는 인증된 요청에만 채워지는 부가 필드로 같은 응답에 실리고, 그 필드에 x-requires-role 을 붙인다. 별도 엔드포인트로 나누면 같은 판정을 두 번 계산하게 되고 둘이 어긋날 수 있다.",
    "extension": "x-requires-role",
    "appliesTo": "components.schemas 의 property. 붙은 필드는 익명 응답에 존재하지 않는다.",
    "roles": ["counselor", "rule_manager"],
    "$rolesComment": "시민은 익명이므로 역할 값이 아니다 — 표기가 없는 필드가 곧 전원 공개다. 어휘는 store 의 ROLES 에서 citizen 을 뺀 것이다.",
    "$valueSemantics": "x-requires-role 의 값은 그 필드를 받는 **가장 낮은 역할** 하나다. 목록이 아닌 이유는 상위 역할이 자동으로 포함되기 때문이며(counselor 를 적으면 rule_manager 도 받는다), 목록으로 두면 새 역할이 생길 때마다 전 필드를 고쳐야 한다.",
    "annotatedProperties": ["AnalyzeResponse/internal"],
    "$annotatedComment": "4단계가 채웠다. AnalyzeResponse.internal 은 SPEC 6.1 의 내부 정보(규칙 버전 · 신선도 · 부적격 상세)를 담으며, **익명 응답에는 이 키가 존재하지 않는다** — null 이 아니라 부재다. 스키마를 역할별로 가르지 않고 부가 필드 하나로 실은 것이 Part 0-E #1 의 요구다.",
    "annotatedOperations": {
        "/api/admin/drafts": {"get": "rule_manager"},
        "/api/admin/drafts/{draft_id}": {"get": "rule_manager"},
        "/api/admin/drafts/{draft_id}/impact": {"get": "rule_manager"},
        "/api/admin/drafts/batch-approve": {"post": "rule_manager"},
        "/api/admin/drafts/{draft_id}/approve": {"post": "rule_manager"},
        "/api/admin/drafts/{draft_id}/reject": {"post": "rule_manager"},
        "/api/admin/audit": {"get": "rule_manager"},
        "/api/admin/status": {"get": "rule_manager"},
    },
    "$operationsComment": "필드가 아니라 **오퍼레이션 전체**가 역할 뒤에 있는 경우다. 같은 확장을 operation 수준에도 붙였고 이 표가 그 거울이다. /api/auth/logout 은 여기 없다 — 자기 세션을 끝내는 것은 역할이 아니라 로그인 여부의 문제다.",
    "enforcedBy": "backend/tests/crosscheck/test_openapi_contract.py",
    "enforcedAlsoBy": "backend/tests/api/test_auth.py (익명 응답에 내부 필드가 없음 · 상담원의 승인 호출이 거부됨 — SPEC 9.2 #3 · 10.2 4단계)",
}

#: 타임아웃 발생 시 동작 (SPEC 8.3 #5). 세 프로필이 같은 규율을 따른다.
_ON_TIMEOUT = {
    "silentFallback": False,
    "display": "폴백했다는 사실을 화면에 명시한다. 침묵 폴백을 금지한다 (SPEC 6.2 오프라인 동작 정의 #3 · D-11).",
}

#: SPEC 8.3 #1 의 [측정에서 유도한다]를 4단계 신규 경로에 대해 **기계 판독 가능하게** 부정한다.
#:
#: `chat` 프로필이 `measured: false` 로 [이 값은 측정에서 나오지 않았다]를 표시하는 것과
#: 같은 규약이며, 다른 점은 단위가 프로필이 아니라 **경로**라는 것뿐이다. 주석으로 적지
#: 않는 이유는 그것이 이 저장소가 이미 배운 것이기 때문이다 — 주석은 테스트가 읽지 못하고,
#: 다음 사람은 `read.measurement.measured: true` 를 보고 [신규 경로도 측정됐구나] 로 읽는다.
UNMEASURED_READ_PATHS = {
    "$comment": "read.appliesTo 중 재현 가능한 측정 근거가 없는 경로. measured:true 가 프로필 전체를 덮는다고 읽히는 것을 막는다.",
    "paths": [
        "/api/auth/login", "/api/auth/logout", "/api/auth/session",
        "/api/admin/drafts", "/api/admin/drafts/{draft_id}",
        "/api/admin/drafts/{draft_id}/impact", "/api/admin/drafts/batch-approve",
        "/api/admin/drafts/{draft_id}/approve",
        "/api/admin/drafts/{draft_id}/reject", "/api/admin/audit",
        "/api/reports", "/api/admin/reports",
        "/api/admin/status",
    ],
    "$whyNotMeasured": "재현 가능한 측정 스크립트가 없다. scripts/measure_latency.py 는 코디네이터 소유라 4단계 워커도 5단계 워커도 경로를 더할 수 없었다. 5단계가 더한 셋(/api/admin/drafts/{draft_id} · .../impact · .../batch-approve)은 앞의 넷보다 무거울 여지가 있다 — 특히 /impact 는 회귀 프로필 12건에 대해 판정을 **두 번씩** 돌린다. 그 사실을 재지 않고 적어 둔다. 6-A 가 더한 둘(/api/reports · /api/admin/reports)도 재지 않았다 — 신고 큐 조회는 신고 수만큼 늘어나는 조회이고, 신고 빈도가 얼마인지는 SPEC 6.4 가 [잠정]이라고 적어 둔 바로 그 미지수다.",
    "$valueOrigin": "이 경로들은 read 프로필의 기존 값(clientTimeoutMs 3000 · serverResponseBudgetMs 500)을 물려받았다. 값이 이 경로들의 측정에서 유도되지 않았다.",
    "loginProbe": {
        "$comment": "참고용. **이 값으로 타임아웃을 정하지 않는다** (chat.measurement.offlineTemplatePath 와 같은 규약). /api/auth/login 만 Argon2id 해싱 때문에 예산에 닿을 여지가 있어 한 번 재 본 것이며, 재현 가능한 커밋된 스크립트가 없으므로 measurement 자리로 승격하지 않는다.",
        "samples": 60,
        "p50Ms": 55.7,
        "p95Ms": 88.1,
        "maxMs": 94.4,
        "measuredAt": "2026-08-14",
        "environment": "Windows 11 / Python 3.13.7 / argon2-cffi 25.1.0 / 개발 머신 (시연 노트북이 아니다)",
        "scope": "루프백 HTTP 왕복. uvicorn 실기동에 60회 순차 로그인.",
        "$verdict": "최악 94.4ms 로 serverResponseBudgetMs=500 의 약 19% 다. 예산을 고칠 이유가 없다. 반대로 이 값이 500ms 를 넘겼다면 고칠 것은 Argon2id 파라미터가 아니라 예산이었을 것이다 — 해싱이 느린 것은 결함이 아니라 그 함수의 목적이다.",
    },
}

#: SPEC 8.1 이 `/api/health` 에 배치 상태·신선도를 더하면서 그 경로가 **저장소를 열게
#: 됐다.** 위 `perPath["/api/health"]` 는 그 전(2026-08-13)에 잰 값이므로 지금 코드를
#: 서술하지 않는다. 그 사실을 주석이 아니라 **계약에** 적는다 — 바뀐 코드에 옛 측정을
#: 말없이 붙여 두는 것이 SPEC 8.3 #1 이 막으려던 것이다.
#:
#: **숫자를 덮어쓰지 않는 이유**는 아래 `$whyNotPromoted` 에 있다. `loginProbe` 와 같은
#: 규약이다 — 참고용 수치를 측정값 자리로 승격하지 않는다.
HEALTH_ROW_PREDATES_SPEC_8_1 = {
    "path": "/api/health",
    "$comment": "이 행은 SPEC 8.1 추가 이전의 코드 경로를 잰 값이다. 그때 /api/health 는 저장소를 열지 않았고 지금은 연다.",
    "changedBy": "SPEC 8.1 — batch · freshness 추가. 요청마다 store_from_env() 로 저장소를 한 번 연다.",
    "reprobe": {
        "$comment": "참고용. 위 perPath 를 대체하지 않는다.",
        "samples": 200,
        "p50Ms": 6.3,
        "p95Ms": 8.8,
        "maxMs": 11.9,
        "measuredAt": "2026-08-15",
        "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
        "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. uvicorn 실기동에 경로당 200회 순차 호출.",
        "script": "scripts/measure_latency.py",
        "control": {
            "$comment": "★ 같은 실행 안의 대조군. 2026-08-13 값과의 차이는 이 변경이 아니라 머신 상태가 대부분이므로(손대지 않은 /api/meta 도 1.4 -> 2.2 로 움직였고 /api/analyze 는 2.8 -> 10.4 다), 비교는 **같은 실행 안에서** 해야 한다.",
            "/api/regions": {"p50Ms": 6.3, "p95Ms": 8.3, "maxMs": 9.7},
            "/api/meta": {"p50Ms": 2.2, "p95Ms": 3.1, "maxMs": 3.9},
            "$reading": "/api/meta 는 저장소를 열지 않고 나머지 둘은 연다. /api/health 가 /api/regions 와 같은 값이 됐다는 것이 이 변경의 비용이 곧 [저장소 열기 한 번] 이라는 뜻이다.",
        },
        "$verdict": "최악 11.9ms 로 serverResponseBudgetMs=500 의 약 2.4% 다. 예산을 고칠 이유가 없다.",
    },
    "$whyNotPromoted": "이 실행의 세 GET 이 2026-08-13 대비 전부 4~6배 느리다 — 손대지 않은 /api/meta 까지 그렇다. 머신 상태 차이를 이 변경의 비용인 척 계약에 새겨 넣지 않는다. /api/health 행만 이 실행의 숫자로 갈아 끼우면 나머지 두 행과 다른 머신의 값이 한 표에 나란히 서고, 그 표는 경로 간 비교가 불가능해진다. 세 행을 다 갈아 끼우는 것은 기준 머신의 측정을 버리는 일이라 코디네이터 판단이다 (SPEC 8.2 #5).",
    "$whenToRemove": "read 프로필을 한 머신에서 다시 전수 측정해 perPath 세 행을 함께 갱신할 때 이 블록을 지운다.",
}

#: SPEC 8.3 — 값은 측정에서 유도한다 (#1). 코디네이터가 8.2 절차로 확정한 값이다
#: (ask 2026-08-13). 코드에 직접 쓰지 않고 여기에만 둔다 (#3).
X_BOUNDARY_CONDITIONS = {
    "$comment": "SPEC 8.3. 타임아웃·재시도는 계약 파일의 x- 확장에만 존재하고 코드에 직접 쓰지 않는다(8.3 #3). 서버와 클라이언트가 같은 파일에서 읽는다(8.3 #4).",
    "$rule": "클라이언트 타임아웃 > 서버 응답 예산 + 마진 (8.3 #2). 역전되면 정상 응답이 폴백으로 처리된다.",
    "$structure": "경로별이다. 평면 구조를 쓰지 않는다 — 셋의 지연 성격이 완전히 다르므로 하나로 뭉치면 chat 기준으로 잡혀 analyze 가 75초를 기다리거나, analyze 기준으로 잡혀 chat 이 다시 잘린다. 후자가 예선 사고 그 자체다. 계약이 그 사고를 다시 가능하게 만드는 형태여서는 안 된다.",
    "$decidedBy": "코디네이터 (SPEC 8.2 #5), W-platform 실측 보고에 근거. 2026-08-13.",

    # 클라이언트가 경로 -> 프로필을 고르는 규칙. `frontend/app.js` 의 `timeoutFor(path)`
    # 분기와 **1:1 대응**한다. D-11 이 이 표에서 JS 상수 모듈을 생성하면 양쪽이 같은
    # 파일에서 읽게 된다 (8.3 #4). 대응이 깨지는지는 교차 테스트가 본다.
    "clientDispatch": {
        "byPath": {"/api/chat": "chat", "/api/analyze": "analyze"},
        "default": "read",
        "$comment": "frontend/app.js 의 timeoutFor(path) 와 같은 모양이다 — 특정 경로 둘을 먼저 가르고 나머지를 기본값으로 떨어뜨린다.",
    },

    "profiles": {
        "analyze": {
            "appliesTo": ["/api/analyze"],
            "clientTimeoutMs": 5000,
            "serverResponseBudgetMs": 1000,
            "budgetIsAPromiseNotAMeasurement": True,
            "$budgetComment": "1,000ms 는 실측 p99 5.1ms 의 약 200배다. 이 간극은 의도된 것이다 — 시연 노트북 사양과 실데이터 유입 후의 정책·지역 순회 증가를 흡수한다. 실측이 더 빨라져도 계약은 바뀌지 않고, 1,000ms 를 넘기면 그것은 회귀다.",
            "retries": 0,
            "$retriesComment": "판정은 결정론적이다(원칙 1). 재시도는 같은 답을 같은 시간에 낼 뿐이므로 지연만 두 배가 된다.",
            "onTimeout": _ON_TIMEOUT,
            "measurement": {
                "measured": True,
                "samples": 800,
                "p50Ms": 2.8, "p90Ms": 3.8, "p95Ms": 4.0, "p99Ms": 5.1, "maxMs": 11.5,
                "coldFirstRequestMs": 22.5,
                "measuredAt": "2026-08-13",
                "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
                "providerMode": "offline",
                "$providerComment": "/api/analyze 는 원칙 1 에 따라 LLM 을 부르지 않으므로 프로바이더 모드가 이 분포에 영향을 주지 않는다.",
                "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. 순차 호출, 커넥션 재사용, 프로필 4종 x 200회.",
                "script": "scripts/measure_latency.py",
                "report": "backend/tests/api/artifacts/analyze_latency.md",
            },
        },
        "read": {
            # 4단계·5단계 신규 경로가 여기 붙는다. 선택지가 하나였다 —
            # `clientDispatch.byPath` 는 `frontend/app.js` 의 `timeoutFor()` 분기와 1:1
            # 대응이 강제되고(교차 테스트), app.js 는 `web` 소유·6단계라 이 과업이 고칠 수
            # 없다. 그래서 신규 경로는 `default` 인 이 프로필로 떨어진다. 미측정 사실은
            # 아래 `unmeasuredPaths` 가 **기계 판독 가능하게** 드러낸다 (코디네이터 지시 Q4).
            #
            # ★ 5단계가 더한 셋 중 `/impact` 는 회귀 프로필 12건 × 판정 2회를 돈다.
            #   `read` 의 500ms 예산이 그것을 견디는지 **재지 않았다** — 그 사실은
            #   `unmeasuredPaths` 에 적혀 있고, 예산을 임의로 늘리지 않는다.
            #   근거 없이 헐거운 타임아웃은 사고를 숨긴다(이 프로필의 `$budgetComment`).
            "appliesTo": [
                "/api/health", "/api/regions", "/api/meta",
                "/api/auth/login", "/api/auth/logout", "/api/auth/session",
                "/api/admin/drafts", "/api/admin/drafts/{draft_id}",
                "/api/admin/drafts/{draft_id}/impact", "/api/admin/drafts/batch-approve",
                "/api/admin/drafts/{draft_id}/approve",
                "/api/admin/drafts/{draft_id}/reject", "/api/admin/audit",
                # 6-A 신규 둘. 같은 이유로 `default` 인 이 프로필로 떨어진다 —
                # 신고 생성은 저장소 쓰기 하나 + 감사기록 하나이고, 큐 조회는 목록
                # 하나에 초안 목록을 한 번 맞춰 보는 것이라 성격이 `read` 와 같다.
                "/api/reports", "/api/admin/reports",
                # 7단계 신규. 같은 이유로 `default` 인 이 프로필로 떨어진다. 성격은
                # `read` 지만 **재지 않았다** — 감사기록 전수를 두 번 순회하고 파일
                # 로그를 통째로 읽으므로 기록이 쌓일수록 선형으로 는다. 그 사실을
                # `unmeasuredPaths` 에 적어 두고 예산을 임의로 늘리지 않는다.
                "/api/admin/status",
            ],
            "clientTimeoutMs": 3000,
            "serverResponseBudgetMs": 500,
            "budgetIsAPromiseNotAMeasurement": True,
            "$budgetComment": "현행 4,500ms 에서 낮춘다. D-8 이 로컬 단일 호스트를 못박았으므로 이 셋이 초 단위로 늘어나면 그것은 사고이고, 헐거운 타임아웃은 사고를 숨긴다.",
            "retries": 0,
            "onTimeout": _ON_TIMEOUT,
            "measurement": {
                "measured": True,
                "samples": 600,
                "perPath": {
                    "/api/health": {"p50Ms": 0.9, "p95Ms": 1.4, "maxMs": 1.9},
                    "/api/regions": {"p50Ms": 1.0, "p95Ms": 1.5, "maxMs": 4.6},
                    "/api/meta": {"p50Ms": 1.4, "p95Ms": 2.0, "maxMs": 2.5},
                },
                "p50Ms": 1.4, "p95Ms": 2.0, "maxMs": 4.6,
                "$aggregateComment": "위 세 값은 경로별 최악값이다. 평균이 아니다 — 타임아웃은 최악을 견뎌야 한다.",
                "$perPathStaleness": HEALTH_ROW_PREDATES_SPEC_8_1,
                "unmeasuredPaths": UNMEASURED_READ_PATHS,
                "measuredAt": "2026-08-13",
                "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
                "providerMode": "offline",
                "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. 경로당 200회.",
                "script": "scripts/measure_latency.py",
                "report": "backend/tests/api/artifacts/analyze_latency.md",
            },
        },
        "chat": {
            "appliesTo": ["/api/chat"],
            "clientTimeoutMs": 75000,
            "serverResponseBudgetMs": None,
            "$budgetComment": "**서버 응답 예산 개념이 성립하지 않는다.** 지연을 정하는 것이 우리 코드가 아니라 외부 프로바이더이므로, 예산을 적으면 지킬 수 없는 약속이 된다.",
            "retries": 0,
            "$retriesComment": "프로바이더 호출에는 이미 서버측 재시도가 있다. 클라이언트가 또 걸면 이중이 되어 최악 지연이 곱해진다.",
            "onTimeout": _ON_TIMEOUT,
            "measurement": {
                # SPEC 8.3 #1 은 "타임아웃은 측정에서 유도한다"이다. 측정하지 않은 값을
                # 측정된 값과 같은 형태로 실으면 그 규칙이 무너진다. Part 0-C 의
                # "(d)를 (a)(b)(c)인 척하지 않는다"와 같은 규율이라 기계 판독으로 구분한다.
                "measured": False,
                "$whyNotMeasured": "라이브 LLM 왕복은 API 키와 호출 비용을 요구한다. 키 없이 도는 offline 템플릿 경로만 쟀고, 그 값은 이 타임아웃의 근거가 되지 못한다 — offline 은 프로바이더를 아예 부르지 않는다.",
                "$valueOrigin": "75,000 은 현행 frontend/app.js 값을 유지한 것이며 측정에서 유도되지 않았다. app.js 주석이 기록한 관측(단일 툴콜 2.7~4.5초, 4툴 턴 약 10초)은 예선 기록이지 우리 측정이 아니다.",
                "$followUp": "라이브 LLM 지연 측정은 실사 항목이다 (코디네이터가 목록에 올린다).",
                "offlineTemplatePath": {
                    "$comment": "참고용. 이 값으로 타임아웃을 정하지 않는다.",
                    "samples": 20, "p50Ms": 3.1, "maxMs": 4.2,
                    "measuredAt": "2026-08-13",
                    "script": "scripts/measure_latency.py",
                },
            },
        },
    },
}

#: 재생성 diff 가 바이트 비교이므로 직렬화 규칙 자체가 계약이다.
X_SERIALIZATION = {
    "$comment": "SPEC D-12 재생성 diff 는 바이트 비교다. FastAPI 가 만드는 dict 를 그대로 쓰면 삽입 순서가 실려 라이브러리 버전에 따라 흔들리고, 그러면 diff 테스트가 계약이 아니라 잡음을 잡는다.",
    "encoding": "UTF-8, BOM 없음",
    "newline": "LF (\\n). 파일 끝에 개행 1개.",
    "indent": 2,
    "sortKeys": True,
    "$sortKeysComment": "객체 키만 정렬한다. 배열 순서는 의미가 있으므로(required, enum, parameters) 건드리지 않는다.",
    "ensureAscii": False,
    "$asciiComment": "한국어 설명문을 유니코드 이스케이프로 부풀리지 않는다. 사람이 리뷰하는 파일이다.",
    "generator": "backend/src/home_compass/main.py: build_openapi_document / render_openapi_document",
    "command": "python scripts/gen_contracts.py",
}


def build_openapi_document() -> dict:
    """계약 문서 하나를 만든다. `app.openapi()` 를 쓰지 않는 이유는 캐시 때문이다.

    `app.openapi()` 는 결과를 `app.openapi_schema` 에 붙여 두고 다음 호출에 같은
    객체를 돌려준다. 생성기가 그 객체를 손대면 이후 `/openapi.json` 응답까지 바뀐다.
    """
    document = get_openapi(
        title=app.title,
        version=API_CONTRACT_VERSION,
        description=app.description,
        routes=app.routes,
    )
    document["info"]["x-engine-version"] = ENGINE_VERSION
    document["x-units"] = X_UNITS
    document["x-rounding"] = X_ROUNDING
    document["x-role-annotations"] = X_ROLE_ANNOTATIONS
    document["x-boundary-conditions"] = X_BOUNDARY_CONDITIONS
    document["x-serialization"] = X_SERIALIZATION
    return document


def render_openapi_document(document: dict | None = None) -> str:
    """`X_SERIALIZATION` 이 적은 그대로 직렬화한다. 이 함수가 그 규칙의 유일한 구현이다."""
    return (
        json.dumps(
            document if document is not None else build_openapi_document(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def write_openapi_document(path: Path = OPENAPI_PATH) -> bool:
    """파일에 쓴다. 내용이 바뀌었으면 True.

    바뀌지 않았으면 파일을 건드리지 않는다 — mtime 만 흔들면 무엇이 바뀌었는지가
    흐려진다.
    """
    rendered = render_openapi_document()
    if path.exists() and path.read_bytes() == rendered.encode("utf-8"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    return True


# --------------------------------------------------------------------------
# Static frontend (mounted last so /api/* always wins)
# --------------------------------------------------------------------------
#
# ★ `/admin` 이 `/` **앞에** 온다. Starlette 는 선언 순서대로 라우트를 맞추므로 `/` 를
#   먼저 마운트하면 그것이 모든 경로를 먹고 `/admin` 은 도달하지 않는다. 순서가 곧
#   동작이며, 그 사실을 `test_admin_screen.py` 가 고정한다.

if ADMIN_DIR.is_dir():
    # 맨몸 `/admin` 은 마운트 정규식(`^/admin(?P<path>/.*)$`)에 걸리지 않는다. 그러면
    # 뒤의 `/` 마운트가 그것을 먹고 `web` 의 404 를 돌려준다 — 주소창에 `/admin` 을 친
    # 사람이 [화면이 없다]로 읽는 자리다. 그래서 명시적으로 넘긴다.
    @app.get("/admin", include_in_schema=False)
    def _admin_index() -> RedirectResponse:
        return RedirectResponse(url="/admin/")

    app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True), name="admin")

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:  # pragma: no cover - only hit before the frontend exists
    @app.get("/", response_class=HTMLResponse)
    def _placeholder() -> str:
        return (
            "<!doctype html><meta charset='utf-8'>"
            "<title>Home_Compass</title>"
            "<h1>Home_Compass 백엔드가 실행 중입니다.</h1>"
            f"<p>프론트엔드({FRONTEND_DIR})가 아직 없습니다.</p>"
            "<p>API 문서: <a href='/docs'>/docs</a></p>"
        )
