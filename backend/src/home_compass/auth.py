"""인증·권한 — SPEC 6.1(권한 매트릭스) · 6.3(인증).

**`api` 컴포넌트의 일부다** (SPEC 1.1). 새 컴포넌트가 생긴 것이 아니라 `main.py` 가 파일
하나로 나뉜 것이다. `store` 만 본다 — `engines` · `llm` · `ingest` 를 import 하지 않는다
(SPEC 1.2). 판정과 LLM 은 인증이 알 이유가 없고, 아키텍처 테스트가 그것을 강제한다.

이 모듈이 지고 있는 것 넷.

  1. 비밀번호는 **Argon2id** 로만 저장·검증한다 (Part 0-E [공인 표준으로 채운 것])
  2. 세션은 **서버가 들고**, 쿠키는 `HttpOnly` 라 JS 가 읽지 않는다 (OWASP ASVS)
  3. **상태변경 요청**에 CSRF 토큰을 요구한다 (OWASP CSRF CS)
  4. 권한 검사는 **API 계층**에서 한다. 화면에서 버튼을 숨기는 것으로 대신하지 않는다 (SPEC 6.1)

넷 중 4가 이 단계의 산출물이다. SPEC 10.2 의 4단계 완료 기준 넷 중 셋이 [~하면 거부된다]
[~가 없다] 형태이므로, **여기서 만드는 것은 기능이 아니라 거부**다.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .store import AuditEvent, Store, User

# --------------------------------------------------------------------------
# 1. 비밀번호 — Argon2id (Part 0-E · SPEC 6.3)
# --------------------------------------------------------------------------
#
# 출처: OWASP Password Storage Cheat Sheet — Argon2id 절.
#   https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
#   "Use Argon2id with a minimum configuration of 19 MiB of memory, an iteration
#    count of 2, and 1 degree of parallelism."
#
# 값을 여기 적고 `argon2-cffi` 의 자체 기본값(m=64MiB · t=3 · p=4)을 쓰지 않는 이유는
# **인용 가능성**이다. 라이브러리 기본값은 버전이 올라가면 조용히 바뀌고, 그러면 우리가
# 무엇을 근거로 골랐는지가 사라진다. 여기 적어 두면 바뀌는 것이 diff 에 남는다.
#
# `ModelConstant` 로 등재하지 않는다 (코디네이터 승인, Q2). Part 0-E 의 [공인 표준으로
# 채운 것]과 [(d) 규범적 선택]은 다른 칸이고, 표준 인용을 `our_choice` 로 등재하면
# 감도분석이 **표준을 흔들어 보는** 표가 된다.
ARGON2_MEMORY_COST_KIB = 19_456  # 19 MiB
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1

_HASHER = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
)

#: 존재하지 않는 사용자에게도 **같은 일을 시키기 위한** 더미 해시.
#: 없으면 「없는 아이디」는 즉시 돌아오고 「있는 아이디 + 틀린 비밀번호」는 20~30ms 걸려서,
#: 응답 시간만으로 계정 존재 여부가 새어 나간다. 모듈 적재 시 1회 계산한다.
_ABSENT_USER_HASH = _HASHER.hash(secrets.token_urlsafe(32))


def hash_password(raw: str) -> str:
    """Argon2id 해시 문자열. 저장소에게는 불투명한 문자열이다 (`store.models.User`)."""
    return _HASHER.hash(raw)


def verify_password(stored_hash: str, raw: str) -> bool:
    """맞으면 True. **예외를 밖으로 내보내지 않는다** — 틀린 비밀번호와 깨진 해시가
    호출부에서 다른 경로를 타면 그 차이가 곧 정보 노출이다."""
    try:
        _HASHER.verify(stored_hash, raw)
    except (VerificationError, InvalidHashError):
        return False
    return True


def burn_absent_user_time(raw: str) -> None:
    """사용자가 없을 때도 해시 1회를 태운다. 반환값이 없는 것이 핵심이다."""
    verify_password(_ABSENT_USER_HASH, raw)


# --------------------------------------------------------------------------
# 2. 세션 만료 상수 (SPEC 6.3 · Part 0-E #4)
# --------------------------------------------------------------------------
#
# **코드에 숫자를 박지 않는다.** 값은 `ModelConstant` 에 (d) `our_choice` 로 등재되어
# 있고 여기서는 키만 안다. 저장소에 없으면 `constants[...]` 가 `KeyError` 를 내고 기동이
# 거부된다 — SPEC 5.1.1 fail-closed 가 상수 하나에 걸리는 것과 같은 자리다.
#
# SPEC 6.3 은 [값은 미정. 8단계 리허설 뒤에 정한다]고 적었다. 그때 바뀌는 것은 저장소의
# 값 하나이고 이 파일은 다시 바뀌지 않는다.
SESSION_IDLE_TIMEOUT_KEY = "auth.session_idle_timeout_seconds"
SESSION_ABSOLUTE_TIMEOUT_KEY = "auth.session_absolute_timeout_seconds"

#: 기동 시 전수 존재를 확인하는 키. `engines.required_constant_keys()` 의 인증 쪽 대응물이다.
AUTH_CONSTANT_KEYS = (SESSION_IDLE_TIMEOUT_KEY, SESSION_ABSOLUTE_TIMEOUT_KEY)


# --------------------------------------------------------------------------
# 3. 쿠키 · CSRF (SPEC 6.2 동일 오리진 · 6.3)
# --------------------------------------------------------------------------

SESSION_COOKIE_NAME = "home_compass_session"
CSRF_COOKIE_NAME = "home_compass_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

#: 세션 쿠키는 `HttpOnly` 다 — **JS 에서 읽지 않는다** (Part 0-E · ASVS).
#: CSRF 쿠키는 반대로 JS 가 읽어야 헤더에 실을 수 있으므로 `HttpOnly` 가 아니다.
#: 그 둘이 다른 이유가 곧 double-submit 의 작동 원리다 — 공격자 오리진은 쿠키를
#: **딸려 보낼 수는 있어도 읽을 수는 없으므로** 헤더를 맞출 수 없다.
#:
#: `secure=True` 를 걸지 않는 이유는 D-8 이다. 시연은 `http://127.0.0.1` 로 돌고
#: `Secure` 쿠키는 그 위에서 전송되지 않아 로그인 자체가 불가능해진다. HTTPS 는
#: 부록 A 의 [배포 시 추가로 필요한 것] 목록에 이미 들어 있다.
COOKIE_SAMESITE = "strict"
COOKIE_PATH = "/"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(session: "Session", presented: str | None) -> bool:
    """상수 시간 비교. `==` 로 비교하면 일치 길이가 응답 시간에 실린다."""
    if not presented:
        return False
    return secrets.compare_digest(session.csrf_token, presented)


# --------------------------------------------------------------------------
# 4. 세션 원장
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Session:
    """서버가 들고 있는 세션 하나. 쿠키에는 `id` 만 나간다.

    `role` 을 세션에 복사해 두는 이유는 권한 판정을 **요청마다 저장소 왕복 없이** 하기
    위해서가 아니다 — 그 목적이면 캐시이고 SPEC 2.3 의 금지 대상이다. 여기 있는 이유는
    로그인 시점의 역할을 **감사 기록에 고정**하기 위함이며, 권한 검사는 `resolve()` 가
    돌려준 이 값으로 한다. 역할 변경 기능이 생기면(현재 없다) 그때 세션 무효화가
    함께 와야 한다는 사실을 여기 적어 둔다.
    """

    id: str
    user_id: str
    username: str
    role: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime


#: `resolve()` 가 왜 실패했는가. 401 로 뭉뚱그리면 감사 로그가 [만료]와 [세션 없음]을
#: 구분하지 못하고, 그 둘은 운영에서 완전히 다른 사건이다.
SESSION_OK = "ok"
SESSION_ABSENT = "absent"
SESSION_IDLE_EXPIRED = "idle_expired"
SESSION_ABSOLUTE_EXPIRED = "absolute_expired"


@dataclass(frozen=True)
class SessionLookup:
    session: Session | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.session is not None


class SessionStore:
    """세션 원장. **api 프로세스 메모리에 있다** (코디네이터 결정, Q7).

    근거: SPEC 2.2 의 엔티티 표에 `Session` 이 없고 추가는 SPEC 변경이다. D-8 이 로컬
    단일 호스트를 못박았고 `scripts/dev.bat` 은 uvicorn 을 워커 1개로 띄운다.

    **대가를 숨기지 않는다. 둘 다 실재하는 제약이다.**

      · 서버를 재기동하면 **세션이 전부 끊긴다.** 로그인부터 다시 해야 한다.
      · `uvicorn --workers 2` 이상이면 **깨진다.** 워커마다 원장이 따로 생겨 요청이
        어느 워커에 걸리느냐에 따라 로그인 상태가 오락가락한다. `dev.bat` 이 워커 수를
        지정하지 않아 지금은 1개지만, 그것은 **uvicorn 기본값에 기대고 있는 것**이다.
        누가 `--workers` 를 붙이는 순간 조용히 깨진다.

    `threading.Lock` 을 두는 이유는 FastAPI 의 **동기 엔드포인트가 워커 스레드에서**
    돌기 때문이다. 단일 프로세스라도 요청은 동시에 들어온다.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user: User, *, now: datetime) -> Session:
        session = Session(
            id=secrets.token_urlsafe(32),
            user_id=user.id,
            username=user.username,
            role=user.role,
            csrf_token=new_csrf_token(),
            created_at=now,
            last_seen_at=now,
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def resolve(
        self,
        session_id: str | None,
        *,
        now: datetime,
        idle_timeout_seconds: int,
        absolute_timeout_seconds: int,
    ) -> SessionLookup:
        """유효하면 세션을, 아니면 이유를 돌려준다. **유휴 시계는 여기서 갱신된다.**

        만료된 세션은 즉시 원장에서 지운다 — 남겨 두면 [만료됐지만 존재하는] 상태가
        생기고, 그 상태를 나중에 누가 되살릴 수 있는지가 애매해진다.

        SPEC 6.3 이 요구한 **유휴 만료와 절대 만료를 둘 다** 본다. 절대 만료를 먼저
        보는 이유는 그쪽이 더 강한 조건이기 때문이다 — 계속 쓰고 있어도 8시간이 지나면
        끊긴다는 것이 절대 만료의 정의이고, 유휴를 먼저 통과시키면 그 정의가 흐려진다.
        """
        if not session_id:
            return SessionLookup(None, SESSION_ABSENT)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return SessionLookup(None, SESSION_ABSENT)
            if now - session.created_at >= timedelta(seconds=absolute_timeout_seconds):
                del self._sessions[session_id]
                return SessionLookup(None, SESSION_ABSOLUTE_EXPIRED)
            if now - session.last_seen_at >= timedelta(seconds=idle_timeout_seconds):
                del self._sessions[session_id]
                return SessionLookup(None, SESSION_IDLE_EXPIRED)
            refreshed = Session(
                id=session.id,
                user_id=session.user_id,
                username=session.username,
                role=session.role,
                csrf_token=session.csrf_token,
                created_at=session.created_at,
                last_seen_at=now,
            )
            self._sessions[session_id] = refreshed
        return SessionLookup(refreshed, SESSION_OK)

    def delete(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


# --------------------------------------------------------------------------
# 5. 권한 매트릭스 (SPEC 6.1)
# --------------------------------------------------------------------------

ROLE_COUNSELOR = "counselor"
ROLE_RULE_MANAGER = "rule_manager"

#: SPEC 6.1 표의 **기계 판독본**. 값이 빈 튜플이면 익명 포함 전원 허용이다.
#:
#: 표의 [요약본 출력] 행이 여기 없는 이유는 그것이 **화면 기능**(6단계 · `web` 소유)
#: 이고 이 단계가 집행할 API 동작이 아직 없기 때문이다. 없는 것을 표에 적어 두면
#: 검사되지 않는 규칙이 되고, 그것이 이 저장소가 가장 싫어하는 형태다.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    # 판정 조회 — 시민(익명) 포함 전원
    "analysis.read": (),
    # 자기 세션 종료. 표에 없는 행이지만 **계정이 있는 역할만 할 수 있는 동작**이라
    # 여기 있어야 로그아웃도 같은 게이트를 지난다. 익명은 끝낼 세션이 없다.
    "session.end": (ROLE_COUNSELOR, ROLE_RULE_MANAGER),
    # 내부 정보 (규칙 버전 · 신선도 · 부적격 상세)
    "analysis.internal": (ROLE_COUNSELOR, ROLE_RULE_MANAGER),
    # 규칙 초안 조회
    "draft.read": (ROLE_RULE_MANAGER,),
    # ★ 규칙 승인·반려 — **상담원은 여기 없다.** 이 한 줄이 SoD 다.
    "draft.decide": (ROLE_RULE_MANAGER,),
    # 감사 로그 조회
    "audit.read": (ROLE_RULE_MANAGER,),
    # 이상 신고 (SPEC 6.4) — 올리는 것은 **계정이 있는 역할 둘 다**, 익명은 아니다.
    # 6.1 의 표에 없는 행이지만 6.4 본문이 요구하는 동작이며, 상담원이 「판정 조회 ·
    # 내부 정보」를 갖는 그 자리에서 나온다. 신고는 **제안이지 변경이 아니므로**
    # `draft.decide` 와 같은 줄에 서지 않는다 — 이 구분이 SoD 다.
    "report.create": (ROLE_COUNSELOR, ROLE_RULE_MANAGER),
    # 신고 큐 조회는 규칙관리자의 작업대다 (「규칙 초안 조회」 행과 같은 성격).
    "report.read": (ROLE_RULE_MANAGER,),
    # 7단계 상태 화면 (SPEC 7.2 · 7.3). `audit.read` 를 그대로 쓰지 않는 이유는 둘이
    # 다른 것을 열기 때문이다 — 감사 조회는 **행 하나하나**(행위자·대상 포함)를 보여 주고,
    # 지표는 그것을 센 수다. 한 키로 묶으면 나중에 지표만 여는 역할을 만들 수 없다.
    # 지금은 둘 다 규칙관리자뿐이므로 **화면에 보이는 차이는 없다** — 자리를 가르는 것이
    # 목적이며, 그 사실을 숨기지 않는다.
    "status.read": (ROLE_RULE_MANAGER,),
}


def allows(action: str, role: str | None) -> bool:
    """`action` 을 `role` 이 할 수 있는가. `role=None` 은 익명이다.

    모르는 동작은 **거부한다.** 게이트의 기본값은 느슨한 쪽이 아니라 엄격한 쪽이다
    (SPEC Part 10 의 [게이트는 엄격한 쪽으로 기본값을 둔다]와 같은 규율).
    """
    if action not in PERMISSIONS:
        return False
    allowed = PERMISSIONS[action]
    if not allowed:
        return True
    return role in allowed


# --------------------------------------------------------------------------
# 6. 감사 기록 (SPEC 7.1 필수 기록)
# --------------------------------------------------------------------------
#
# 7.1 의 필수 기록 넷 중 둘이 이 모듈 소관이다 — **로그인 및 실패**, **권한 거부**.
# (규칙 승인·반려는 `main.py` 의 승인 엔드포인트가, 배치 실행 결과는 `ingest` 가 낸다.)

AUDIT_LOGIN = "auth.login"
AUDIT_LOGOUT = "auth.logout"
AUDIT_DENIED = "authz.denied"

#: 익명 요청의 행위자 표기. `None` 을 넣으면 `AuditEvent.actor` 가 NOT NULL 이라 터진다.
ANONYMOUS_ACTOR = "anonymous"


def record(
    store: Store,
    *,
    actor: str,
    at: datetime,
    action: str,
    target: str,
    outcome: str,
    after: dict | None = None,
) -> AuditEvent:
    """`AuditEvent` 하나를 남긴다.

    **요청 본문을 넣지 않는다** (SPEC 7.1 의 표 — 파일 로그도 저장소도 같은 규칙이다).
    비밀번호는 물론이고 시민의 판정 프로필도 여기 실리지 않는다. `after` 에 무엇을
    넣을지는 호출부의 책임이며, 저장소는 그것을 강제하지 못한다.
    """
    return store.audit.append(
        AuditEvent(
            id=f"{action}:{uuid.uuid4().hex}",
            actor=actor,
            at=at,
            action=action,
            target=target,
            outcome=outcome,
            before=None,
            after=after,
        )
    )


# --------------------------------------------------------------------------
# 7. 거부 (SPEC 6.1 · 10.2 4단계)
# --------------------------------------------------------------------------

class AuthError(Exception):
    """HTTP 계층이 오류 봉투로 바꿀 거부. `main.py` 가 잡아서 감사 기록을 남긴다."""

    def __init__(self, status: int, code: str, message: str, *, action: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        #: 어떤 권한 동작에서 막혔는가. 감사 기록의 `target` 이 된다.
        self.action = action


UNAUTHENTICATED_MESSAGE = "로그인이 필요합니다."
EXPIRED_MESSAGE = "세션이 만료되었습니다. 다시 로그인해 주세요."
FORBIDDEN_MESSAGE = "이 작업을 수행할 권한이 없습니다."
CSRF_MESSAGE = "CSRF 토큰이 없거나 일치하지 않습니다."

#: `resolve()` 의 실패 이유 -> 오류 코드. 만료를 [세션 없음]과 같은 코드로 내보내면
#: 클라이언트가 [로그인한 적 없음]과 [끊겼음]을 구분해 안내할 수 없다.
_REASON_CODE = {
    SESSION_ABSENT: ("unauthenticated", UNAUTHENTICATED_MESSAGE),
    SESSION_IDLE_EXPIRED: ("session_expired", EXPIRED_MESSAGE),
    SESSION_ABSOLUTE_EXPIRED: ("session_expired", EXPIRED_MESSAGE),
}


def unauthenticated_error(reason: str, *, action: str | None = None) -> AuthError:
    code, message = _REASON_CODE.get(reason, ("unauthenticated", UNAUTHENTICATED_MESSAGE))
    return AuthError(401, code, message, action=action)


def forbidden_error(action: str) -> AuthError:
    return AuthError(403, "forbidden", FORBIDDEN_MESSAGE, action=action)


def csrf_error(action: str | None = None) -> AuthError:
    return AuthError(403, "csrf_failed", CSRF_MESSAGE, action=action)


# --------------------------------------------------------------------------
# 8. 시드 계정 (SPEC 6.3 · 부록 A)
# --------------------------------------------------------------------------
#
# **비밀번호를 저장소에 커밋하지 않는다.** 기동 시 환경변수로 주입하고, 주입되지 않으면
# 무작위로 만들어 콘솔에 1회만 출력한다. 이것이 SPEC 10.2 4단계 완료 기준의 하나다.
#
# `.env` 를 경로로 쓰지 않는 이유는 부록 A 다 — [.env 는 로컬 편의 수단일 뿐 유일 경로가
# 아니다]. `config.ENV_KEYS` 는 LLM 키만 허용하는 allowlist 이고, 비밀번호를 거기 더하면
# **비밀이 파일로 들어오는 경로를 우리가 새로 만드는 것**이 된다.
#
# 시민 계정은 만들지 않는다 — D-9 가 [시민은 익명이므로 계정이 없다]고 못박았다.

COUNSELOR_PASSWORD_ENV = "HOME_COMPASS_SEED_COUNSELOR_PASSWORD"
RULE_MANAGER_PASSWORD_ENV = "HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"


@dataclass(frozen=True)
class SeedAccount:
    username: str
    role: str
    env_var: str


SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    SeedAccount(username="counselor", role=ROLE_COUNSELOR, env_var=COUNSELOR_PASSWORD_ENV),
    SeedAccount(username="rulemanager", role=ROLE_RULE_MANAGER, env_var=RULE_MANAGER_PASSWORD_ENV),
)


@dataclass(frozen=True)
class SeedAccountResult:
    username: str
    role: str
    #: 이번 기동에서 만들어졌는가. 이미 있으면 손대지 않는다 (재기동 멱등).
    created: bool
    #: 환경변수가 없어 우리가 만든 비밀번호. 환경변수로 주입됐으면 **None** 이다 —
    #: 주입된 비밀번호를 되돌려주면 그것이 곧 유출 경로가 된다.
    generated_password: str | None


def _announce(lines: list[str]) -> None:
    """**stderr 로 낸다.**

    stdout 이 아닌 이유가 있다. `scripts/gen_contracts.py --stdout` 은 계약 파일 **바이트**를
    stdout 으로 흘리는데, 그 스크립트가 `home_compass.main` 을 import 하는 것이 곧 기동이다.
    여기서 stdout 에 한 줄이라도 찍으면 생성물 앞에 그 줄이 붙어 계약이 깨진다.
    """
    for line in lines:
        print(line, file=sys.stderr)


def ensure_seed_accounts(
    store: Store,
    *,
    now: datetime,
    environ: Mapping[str, str] | None = None,
    announce: Callable[[list[str]], None] | None = None,
) -> list[SeedAccountResult]:
    """상담원·규칙관리자 계정이 있는지 보고, 없으면 만든다. 두 번 돌려도 결과가 같다.

    이미 있는 계정의 비밀번호는 **덮어쓰지 않는다.** 환경변수를 바꿔 재기동하는 것이
    비밀번호 변경 경로가 되면, 그 순간 [기동할 때마다 계정이 초기화되는] 시스템이 된다.
    """
    env = os.environ if environ is None else environ
    emit = _announce if announce is None else announce

    results: list[SeedAccountResult] = []
    for account in SEED_ACCOUNTS:
        if store.users.get_by_username(account.username) is not None:
            results.append(SeedAccountResult(account.username, account.role, False, None))
            continue
        injected = (env.get(account.env_var) or "").strip()
        generated = None if injected else secrets.token_urlsafe(12)
        store.users.add(
            User(
                id=f"user:{account.username}",
                username=account.username,
                role=account.role,
                password_hash=hash_password(injected or generated or ""),
                created_at=now,
            )
        )
        results.append(
            SeedAccountResult(account.username, account.role, True, generated)
        )

    announced = [r for r in results if r.generated_password]
    if announced:
        lines = [
            "",
            "[인증] 시드 계정 비밀번호가 환경변수로 주입되지 않아 무작위로 만들었습니다.",
            "[인증] 이 값은 지금 한 번만 출력됩니다. 저장소에도 로그에도 남지 않습니다.",
        ]
        lines += [
            f"[인증]   {r.username} ({r.role}) : {r.generated_password}" for r in announced
        ]
        lines += [
            "[인증] 고정하려면 기동 전에 환경변수를 지정하세요: "
            + ", ".join(a.env_var for a in SEED_ACCOUNTS),
            "",
        ]
        emit(lines)
    return results
