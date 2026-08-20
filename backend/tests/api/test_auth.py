"""인증·권한 (SPEC 6.1 · 6.3 · 7.1 · 9.2 #3, 소유자: `api`).

**이 파일의 산출물은 기능이 아니라 거부다.** SPEC 10.2 의 4단계 완료 기준 넷 중 셋이
[~하면 거부된다] [~가 없다] [~로 저장된다] 이며, 아래 `★` 표시가 그 넷에 직접 대응한다.

  ★ 상담원 세션의 승인 API 호출이 거부된다   -> `TestSeparationOfDuties`
  ★ 익명 응답에 내부 필드가 없다             -> `TestInternalFieldIsAdditive`
  ★ 비밀번호가 Argon2id 로 저장된다          -> `TestPasswordStorage`
  ★ 시드 계정 비밀번호가 커밋에 없다         -> `TestSeedPasswordsAreNotCommitted`

`TestClient` 를 쓰는 것이 요점이다 — 검사가 **API 계층**에 있는지를 보려면 HTTP 로 쳐야
한다. 함수를 직접 부르면 [화면이 버튼을 숨기는 것으로 대신하지 않는다](SPEC 6.1)를
증명하지 못한다.

격리: 모든 케이스가 자기 `tmp_path` 저장소를 만들어 `FIRSTHOME_STORE_URL` 을 그쪽으로
돌리고 세션 원장을 비운다. `conftest.py` 의 세션 저장소는 여기서 건드리지 않는다.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from firsthome import auth as auth_module
from firsthome import main as main_module
from firsthome.auth import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_ABSOLUTE_TIMEOUT_KEY,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TIMEOUT_KEY,
    ensure_seed_accounts,
)
from firsthome.main import MODEL_CONSTANTS, app, read_active_policies, read_regions
from firsthome.store import STORE_URL_ENV, PolicySource, RuleDraft, create_store
from firsthome.store.seed import seed_all

REPO_ROOT = Path(__file__).resolve().parents[3]

T0 = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)

COUNSELOR_PW = os.environ["FIRSTHOME_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["FIRSTHOME_SEED_RULE_MANAGER_PASSWORD"]

PROFILE = {
    "age": 28,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 3_000_000,
    "liquidAssetsKRW": 40_000_000,
    "existingDebtMonthlyKRW": 300_000,
    "householdSize": 1,
    "regionCode": "11440",
    "isHomeless": True,
    "isNewlywed": False,
    "isSMEEmployee": True,
    "preferredType": "any",
}

#: 승인 흐름에 쓰는 초안. `criteria` 는 시드 정책과 **다른 값**이라 승인이 판정을 실제로
#: 움직인다 — 같은 값이면 [승인이 반영됐다]를 증명할 수 없다.
DRAFT_PAYLOAD = {
    "policy_id": "buttress_youth",
    "criteria": {
        "ageMin": 19,
        "ageMax": 39,
        "annualIncomeMaxKRW": 60_000_000,
        "assetMaxKRW": None,
        "requireHomeless": True,
        "requireNewlywed": False,
        "requireSME": False,
        "regionPrefixes": None,
    },
    "maxAmountKRW": 250_000_000,
    "rateRangePct": [1.8, 3.1],
    "conditionalChecks": [],
    # `assetMaxKRW` 는 원문에 없었다 — 병합이 이 값을 덮으면 안 된다.
    "not_found": ["/criteria/assetMaxKRW"],
}


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'auth.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
    monkeypatch.setenv(STORE_URL_ENV, url)
    return url


@pytest.fixture
def frozen_clock(monkeypatch):
    """시계를 고정한다. 만료 테스트는 `sleep` 이 아니라 이것으로 한다 (SPEC 5.3)."""
    holder = {"now": T0}
    monkeypatch.setattr(main_module, "request_now", lambda: holder["now"])
    return holder


@pytest.fixture
def client(store_url, frozen_clock) -> TestClient:
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def login(client: TestClient, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def as_counselor(client: TestClient) -> str:
    response = login(client, "counselor", COUNSELOR_PW)
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def as_rule_manager(client: TestClient) -> str:
    response = login(client, "rulemanager", RULE_MANAGER_PW)
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def seed_draft(store_url: str, draft_id: str = "draft-1") -> str:
    """`pending` 초안 하나를 심는다. 원문도 함께 넣어야 계보가 성립한다."""
    with create_store(store_url) as store:
        if store.policy_sources.get("src-1") is None:
            store.policy_sources.add(
                PolicySource(
                    id="src-1",
                    text="청년전용 버팀목전세자금대출 신청 연령은 만 19세 이상 39세 이하입니다.",
                    source_ref="https://nhuf.molit.go.kr/",
                    fetched_at=T0,
                    attribution="주택도시기금 공고",
                )
            )
        store.rule_drafts.add(
            RuleDraft(
                id=draft_id,
                policy_source_id="src-1",
                policy_id="buttress_youth",
                status="pending",
                payload=DRAFT_PAYLOAD,
                created_at=T0,
            )
        )
    return draft_id


def audit_actions(store_url: str) -> list[tuple[str, str, str]]:
    with create_store(store_url) as store:
        return [(e.action, e.actor, e.outcome) for e in store.audit.list()]


# --------------------------------------------------------------------------
# ★ 비밀번호가 Argon2id 로 저장된다 (SPEC 10.2 4단계 · Part 0-E)
# --------------------------------------------------------------------------

class TestPasswordStorage:
    def test_the_hash_is_argon2id_with_the_owasp_parameters(self, store_url):
        """해시 문자열 자체가 알고리즘과 파라미터를 말한다. 주장이 아니라 관측이다."""
        with create_store(store_url) as store:
            stored = store.users.get_by_username("counselor").password_hash

        assert stored.startswith("$argon2id$"), stored[:40]
        # OWASP Password Storage CS 권고 — m=19MiB · t=2 · p=1.
        assert f"m={ARGON2_MEMORY_COST_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}" in stored
        assert (ARGON2_MEMORY_COST_KIB, ARGON2_TIME_COST, ARGON2_PARALLELISM) == (19456, 2, 1)

    def test_the_plaintext_is_nowhere_in_the_store(self, store_url):
        """저장소 파일 **바이트**를 뒤진다. 컬럼만 보면 다른 테이블로 새는 것을 놓친다."""
        raw = Path(store_url.removeprefix("sqlite://")).read_bytes()
        assert COUNSELOR_PW.encode() not in raw
        assert RULE_MANAGER_PW.encode() not in raw

    def test_two_accounts_with_the_same_password_get_different_hashes(self, tmp_path):
        """솔트가 실제로 붙는가. 같으면 한 해시가 깨질 때 전부 깨진다."""
        first = auth_module.hash_password("same-password")
        second = auth_module.hash_password("same-password")
        assert first != second
        assert auth_module.verify_password(first, "same-password")
        assert auth_module.verify_password(second, "same-password")

    def test_a_wrong_password_is_rejected_without_raising(self):
        assert auth_module.verify_password(auth_module.hash_password("a"), "b") is False

    def test_a_corrupt_hash_does_not_raise(self):
        """깨진 해시가 예외로 새면 [틀린 비밀번호]와 다른 경로를 타고, 그 차이가 곧 정보다."""
        assert auth_module.verify_password("not-a-hash", "b") is False


# --------------------------------------------------------------------------
# 시드 계정 (SPEC 6.3 · D-9)
# --------------------------------------------------------------------------

class TestSeedAccounts:
    def test_both_staff_roles_exist(self, store_url):
        with create_store(store_url) as store:
            roles = {u.username: u.role for u in store.users.list()}
        assert roles == {"counselor": "counselor", "rulemanager": "rule_manager"}

    def test_no_citizen_account_is_created(self, store_url):
        """D-9 — 시민은 익명이므로 계정이 없다."""
        with create_store(store_url) as store:
            assert not [u for u in store.users.list() if u.role == "citizen"]

    def test_a_missing_env_var_generates_a_password_and_announces_it_once(self, tmp_path):
        """환경변수가 없으면 무작위 생성 + 콘솔 1회 출력 (SPEC 6.3)."""
        url = f"sqlite://{tmp_path / 'generated.db'}"
        announced: list[list[str]] = []
        with create_store(url) as store:
            results = ensure_seed_accounts(
                store, now=T0, environ={}, announce=announced.append
            )

        generated = {r.username: r.generated_password for r in results}
        assert all(generated.values()), "환경변수가 없는데 비밀번호를 만들지 않았다"
        assert len(announced) == 1, "출력이 1회가 아니다"
        printed = "\n".join(announced[0])
        for password in generated.values():
            assert password in printed

    def test_an_injected_password_is_never_echoed(self, tmp_path):
        """주입된 비밀번호를 되돌려주면 그것이 곧 유출 경로다.

        주입값을 **여기서 만들어 쓴다.** 리터럴로 적으면 그 줄 자체가
        `TestSeedPasswordsAreNotCommitted` 가 잡는 [커밋된 시드 비밀번호]가 된다.
        """
        url = f"sqlite://{tmp_path / 'injected.db'}"
        announced: list[list[str]] = []
        injected = {a.env_var: secrets.token_urlsafe(12) for a in auth_module.SEED_ACCOUNTS}
        with create_store(url) as store:
            results = ensure_seed_accounts(
                store, now=T0, environ=injected, announce=announced.append
            )
            stored = {u.username: u.password_hash for u in store.users.list()}

        assert all(r.generated_password is None for r in results)
        assert announced == [], "주입된 경우에는 출력하지 않는다"
        # 주입한 값으로 실제로 인증되는가 — 안 되면 [출력 안 함]은 아무것도 뜻하지 않는다.
        assert auth_module.verify_password(
            stored["counselor"], injected[auth_module.COUNSELOR_PASSWORD_ENV]
        )

    def test_reseeding_changes_nothing(self, store_url):
        """재기동은 계정을 초기화하지 않는다 — 그러면 비밀번호가 매번 바뀐다."""
        with create_store(store_url) as store:
            before = store.users.get_by_username("counselor").password_hash
            again = ensure_seed_accounts(store, now=T0, environ={}, announce=lambda _: None)
            after = store.users.get_by_username("counselor").password_hash
        assert [r.created for r in again] == [False, False]
        assert before == after


# --------------------------------------------------------------------------
# ★ 시드 계정 비밀번호가 커밋에 없다 (SPEC 10.2 4단계)
# --------------------------------------------------------------------------

class TestSeedPasswordsAreNotCommitted:
    #: 잡으려는 것은 [환경변수 이름에 값을 붙여 커밋하는 것] 하나다.
    #: 따옴표 친 리터럴은 어떤 파일에서든 잡고, 따옴표 없는 값은 `.env`·`.bat` 처럼
    #: **그 자체가 값인 파일**에서만 잡는다 (파이썬의 `secrets.token_urlsafe(16)` 은 값이 아니다).
    _QUOTED = re.compile(
        r"FIRSTHOME_SEED_(?:COUNSELOR|RULE_MANAGER)_PASSWORD[\"'\]]*\s*[=:,]\s*[\"']([^\"']+)[\"']"
    )
    _BARE = re.compile(
        r"FIRSTHOME_SEED_(?:COUNSELOR|RULE_MANAGER)_PASSWORD\s*=\s*(\S+)"
    )
    _VALUE_FILE_SUFFIXES = (".env", ".example", ".bat", ".cmd", ".sh", ".yml", ".yaml")

    def _tracked_files(self) -> list[Path]:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        return [REPO_ROOT / name for name in out if name]

    def test_no_tracked_file_assigns_a_seed_password(self):
        offenders = []
        for path in self._tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # 바이너리·다른 코덱 파일은 비밀번호를 담는 자리가 아니다
            for match in self._QUOTED.finditer(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
            if path.name.endswith(self._VALUE_FILE_SUFFIXES):
                for match in self._BARE.finditer(text):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
        assert not offenders, (
            "시드 계정 비밀번호가 저장소에 커밋되어 있다 (SPEC 6.3 · 10.2 4단계). "
            f"환경변수로 주입하거나 무작위 생성에 맡겨라: {offenders}"
        )

    def test_the_running_passwords_appear_in_no_tracked_file(self):
        """지금 실제로 쓰이는 값이 저장소 어디에도 없어야 한다."""
        offenders = []
        for path in self._tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if COUNSELOR_PW in text or RULE_MANAGER_PW in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, offenders


# --------------------------------------------------------------------------
# 로그인 · 세션 전달 (SPEC 6.3 · 7.1)
# --------------------------------------------------------------------------

class TestLogin:
    def test_login_sets_an_httponly_session_cookie(self, client):
        response = login(client, "counselor", COUNSELOR_PW)
        assert response.status_code == 200
        assert response.json()["role"] == "counselor"

        cookie = _set_cookie(response, SESSION_COOKIE_NAME)
        assert "httponly" in cookie.lower(), f"세션 쿠키가 HttpOnly 가 아니다: {cookie}"
        assert "samesite=strict" in cookie.lower(), cookie

    def test_the_csrf_cookie_is_readable_by_js_but_the_session_cookie_is_not(self, client):
        """둘이 다른 이유가 곧 double-submit 의 작동 원리다 (Part 0-E · ASVS)."""
        response = login(client, "counselor", COUNSELOR_PW)
        assert "httponly" not in _set_cookie(response, CSRF_COOKIE_NAME).lower()
        assert "httponly" in _set_cookie(response, SESSION_COOKIE_NAME).lower()

    def test_the_session_id_is_not_the_username(self, client):
        """추측 가능한 세션 식별자는 세션이 아니다."""
        login(client, "counselor", COUNSELOR_PW)
        session_id = client.cookies[SESSION_COOKIE_NAME]
        assert "counselor" not in session_id
        assert len(session_id) >= 32

    @pytest.mark.parametrize(
        "username, password",
        [("counselor", "wrong"), ("nobody", COUNSELOR_PW), ("", ""), ("counselor", "")],
    )
    def test_bad_credentials_are_401_with_one_indistinguishable_answer(
        self, client, username, password
    ):
        """없는 아이디와 틀린 비밀번호가 **같은 답**이어야 계정 열거가 막힌다."""
        response = login(client, username, password)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    def test_a_failed_login_is_audited(self, client, store_url):
        """SPEC 7.1 필수 기록 — 로그인 및 실패."""
        login(client, "counselor", "wrong")
        assert ("auth.login", "counselor", "failure") in audit_actions(store_url)

    def test_a_successful_login_is_audited(self, client, store_url):
        as_counselor(client)
        assert ("auth.login", "counselor", "success") in audit_actions(store_url)

    def test_the_password_is_never_written_to_the_audit_trail(self, client, store_url):
        login(client, "counselor", "wrong")
        as_counselor(client)
        with create_store(store_url) as store:
            blob = repr([(e.actor, e.target, e.before, e.after) for e in store.audit.list()])
        assert COUNSELOR_PW not in blob and "wrong" not in blob

    def test_the_session_endpoint_answers_anonymous_with_200(self, client):
        """[로그인했는가] 라는 물음에 401 로 답하면 화면이 [모름]과 [아님]을 못 가른다."""
        response = client.get("/api/auth/session")
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": False, "username": None, "role": None, "csrfToken": None,
        }

    def test_logout_ends_the_session(self, client):
        csrf = as_counselor(client)
        assert client.get("/api/auth/session").json()["authenticated"] is True

        response = client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})
        assert response.status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is False

    def test_logout_is_audited(self, client, store_url):
        csrf = as_counselor(client)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})
        assert ("auth.logout", "counselor", "success") in audit_actions(store_url)

    def test_a_dead_session_cookie_cannot_be_replayed(self, client):
        csrf = as_counselor(client)
        session_id = client.cookies[SESSION_COOKIE_NAME]
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})

        client.cookies.set(SESSION_COOKIE_NAME, session_id)
        assert client.get("/api/auth/session").json()["authenticated"] is False


def _set_cookie(response, name: str) -> str:
    headers = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    assert headers, f"{name} 쿠키가 없다: {response.headers.get_list('set-cookie')}"
    return headers[0]


# --------------------------------------------------------------------------
# 만료 — 유휴와 절대 **둘 다** (SPEC 6.3 · ASVS)
# --------------------------------------------------------------------------

class TestSessionExpiry:
    def test_the_timeouts_come_from_model_constants(self):
        """코드에 숫자가 없다. 값의 정본은 저장소다 (Part 0-E #4)."""
        assert MODEL_CONSTANTS[SESSION_IDLE_TIMEOUT_KEY] == 1800
        assert MODEL_CONSTANTS[SESSION_ABSOLUTE_TIMEOUT_KEY] == 28800
        source = Path(auth_module.__file__).read_text(encoding="utf-8")
        assert "1800" not in source and "28800" not in source, (
            "만료 시간이 코드에 박혔다 — 8단계 리허설 뒤에 값을 바꾸려면 코드를 고쳐야 한다"
        )

    def test_the_session_dies_after_the_idle_timeout(self, client, frozen_clock):
        as_counselor(client)
        idle = MODEL_CONSTANTS[SESSION_IDLE_TIMEOUT_KEY]

        frozen_clock["now"] = T0 + timedelta(seconds=idle - 1)
        assert client.get("/api/auth/session").json()["authenticated"] is True

        frozen_clock["now"] = T0 + timedelta(seconds=idle - 1) + timedelta(seconds=idle)
        assert client.get("/api/auth/session").json()["authenticated"] is False

    def test_activity_refreshes_the_idle_window(self, client, frozen_clock):
        as_counselor(client)
        idle = MODEL_CONSTANTS[SESSION_IDLE_TIMEOUT_KEY]
        for step in range(1, 6):
            frozen_clock["now"] = T0 + timedelta(seconds=(idle - 60) * step)
            assert client.get("/api/auth/session").json()["authenticated"] is True

    def test_the_absolute_timeout_kills_an_active_session(self, client, frozen_clock):
        """계속 쓰고 있어도 끊긴다 — 그것이 절대 만료의 정의다."""
        as_counselor(client)
        idle = MODEL_CONSTANTS[SESSION_IDLE_TIMEOUT_KEY]
        absolute = MODEL_CONSTANTS[SESSION_ABSOLUTE_TIMEOUT_KEY]

        elapsed = 0
        while elapsed + idle - 60 < absolute:
            elapsed += idle - 60
            frozen_clock["now"] = T0 + timedelta(seconds=elapsed)
            client.get("/api/auth/session")

        frozen_clock["now"] = T0 + timedelta(seconds=absolute)
        assert client.get("/api/auth/session").json()["authenticated"] is False

    def test_an_expired_session_is_refused_by_an_admin_endpoint(self, client, frozen_clock):
        as_rule_manager(client)
        frozen_clock["now"] = T0 + timedelta(seconds=MODEL_CONSTANTS[SESSION_ABSOLUTE_TIMEOUT_KEY])

        response = client.get("/api/admin/drafts")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_expired"


# --------------------------------------------------------------------------
# ★★ SoD — 상담원 세션의 승인 API 호출이 거부된다 (SPEC 6.1 · 10.2 4단계)
# --------------------------------------------------------------------------

class TestSeparationOfDuties:
    """이 클래스가 이 과업의 중심이다.

    SPEC 6.1 의 권한 매트릭스에서 **상담원의 [규칙 승인·반려] 칸은 ✕** 다. 그 ✕ 를
    화면이 아니라 **API 가** 집행하는지를 여기서 본다.
    """

    def test_a_counselor_session_is_refused_by_the_approval_api(self, client, store_url):
        draft_id = seed_draft(store_url)
        csrf = as_counselor(client)

        response = client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "상담원이 승인을 시도한다"},
            headers={CSRF_HEADER_NAME: csrf},
        )

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    def test_the_refused_approval_changes_nothing(self, client, store_url):
        """거부가 [실패한 승인] 이 아니라 **아무 일도 없었음** 이어야 한다."""
        draft_id = seed_draft(store_url)
        with create_store(store_url) as store:
            before_versions = {v.id for v in store.rule_versions.list()}

        csrf = as_counselor(client)
        client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "x"}, headers={CSRF_HEADER_NAME: csrf},
        )

        with create_store(store_url) as store:
            assert {v.id for v in store.rule_versions.list()} == before_versions
            assert store.approvals.list() == []
            assert store.rule_drafts.get(draft_id).status == "pending"

    def test_the_denial_is_audited(self, client, store_url):
        """SPEC 7.1 필수 기록 — **권한 거부**.

        남지 않으면 [아무도 시도한 적 없다] 와 [시도했지만 막혔다] 가 사후에 구분되지 않는다.
        """
        draft_id = seed_draft(store_url)
        csrf = as_counselor(client)
        client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "x"}, headers={CSRF_HEADER_NAME: csrf},
        )

        with create_store(store_url) as store:
            denials = [e for e in store.audit.list() if e.action == "authz.denied"]
        assert denials, "권한 거부가 감사 로그에 없다"
        assert denials[-1].actor == "counselor"
        assert denials[-1].target == "draft.decide"
        assert denials[-1].outcome == "denied"

    @pytest.mark.parametrize(
        "method, path, body",
        [
            ("get", "/api/admin/drafts", None),
            ("get", "/api/admin/audit", None),
            ("post", "/api/admin/drafts/draft-1/approve", {"reason": "x"}),
            ("post", "/api/admin/drafts/draft-1/reject", {"reason": "사유"}),
        ],
    )
    def test_a_counselor_is_refused_by_every_admin_endpoint(
        self, client, store_url, method, path, body
    ):
        seed_draft(store_url)
        csrf = as_counselor(client)
        response = client.request(
            method.upper(), path, json=body, headers={CSRF_HEADER_NAME: csrf}
        )
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"

    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", "/api/admin/drafts"),
            ("get", "/api/admin/audit"),
            ("post", "/api/admin/drafts/draft-1/approve"),
            ("post", "/api/admin/drafts/draft-1/reject"),
        ],
    )
    def test_anonymous_is_refused_with_401_not_403(self, client, store_url, method, path):
        """401 과 403 은 다른 사실이다 — 전자는 [누구인지 모른다], 후자는 [알지만 안 된다]."""
        seed_draft(store_url)
        response = client.request(method.upper(), path, json={"reason": "x"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    def test_permission_is_checked_before_csrf(self, client, store_url):
        """상담원에게 돌아갈 답은 [토큰이 없다] 가 아니라 [권한이 없다] 다.

        순서가 뒤집히면 SoD 거부가 CSRF 오류로 가려지고, 감사 로그에도 그렇게 남는다.
        """
        draft_id = seed_draft(store_url)
        as_counselor(client)  # CSRF 헤더를 **일부러 빼고** 친다
        response = client.post(f"/api/admin/drafts/{draft_id}/approve", json={"reason": "x"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    def test_the_permission_table_keeps_the_counselor_out_of_decisions(self):
        """표 자체를 고정한다. 코드가 아니라 표를 고쳐 권한이 새는 것을 막는다."""
        assert auth_module.allows("draft.decide", "rule_manager") is True
        assert auth_module.allows("draft.decide", "counselor") is False
        assert auth_module.allows("draft.decide", None) is False
        assert auth_module.allows("draft.read", "counselor") is False
        assert auth_module.allows("audit.read", "counselor") is False

    def test_an_unknown_action_is_refused(self):
        """게이트의 기본값은 느슨한 쪽이 아니라 엄격한 쪽이다."""
        assert auth_module.allows("draft.delete_everything", "rule_manager") is False


# --------------------------------------------------------------------------
# CSRF (SPEC 6.3 · OWASP CSRF CS)
# --------------------------------------------------------------------------

class TestCsrf:
    def test_a_state_changing_request_without_the_token_is_refused(self, client, store_url):
        seed_draft(store_url)
        as_rule_manager(client)
        response = client.post("/api/admin/drafts/draft-1/approve", json={"reason": "x"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"

    def test_a_wrong_token_is_refused(self, client, store_url):
        seed_draft(store_url)
        as_rule_manager(client)
        response = client.post(
            "/api/admin/drafts/draft-1/approve",
            json={"reason": "x"},
            headers={CSRF_HEADER_NAME: "not-the-token"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"

    def test_another_sessions_token_is_refused(self, client, store_url):
        """토큰이 세션에 묶여 있는가. 안 묶여 있으면 토큰 하나로 전원을 뚫는다."""
        seed_draft(store_url)
        counselor_csrf = as_counselor(client)
        client.cookies.clear()
        as_rule_manager(client)

        response = client.post(
            "/api/admin/drafts/draft-1/approve",
            json={"reason": "x"},
            headers={CSRF_HEADER_NAME: counselor_csrf},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"

    def test_logout_requires_the_token(self, client):
        as_counselor(client)
        assert client.post("/api/auth/logout").status_code == 403
        assert client.get("/api/auth/session").json()["authenticated"] is True

    def test_read_only_endpoints_do_not_require_the_token(self, client, store_url):
        as_rule_manager(client)
        assert client.get("/api/admin/drafts").status_code == 200
        assert client.get("/api/admin/audit").status_code == 200

    def test_analyze_and_chat_stay_open_to_a_logged_in_user_without_a_token(self, client):
        """★ 근거를 여기 남긴다 (코디네이터 승인).

        SPEC 6.3 은 [**상태변경 요청**에 CSRF 토큰]이라고 적었다. `/api/analyze` 와
        `/api/chat` 은 POST 지만 **상태를 바꾸지 않는다.** 여기에 토큰을 요구하면
        `frontend/app.js`(web 소유 · 6단계라 이 과업이 못 고친다)가 로그인 상태에서
        판정을 못 하게 되고, 그것이 오히려 계약 위반이다.

        [CSRF 가 빠졌다] 로 읽히지 않도록 이 테스트가 그 판단을 고정한다.
        """
        as_counselor(client)
        assert client.post("/api/analyze", json=PROFILE).status_code == 200
        assert client.post("/api/chat", json={"message": "전세와 월세 중 뭐가 나을까요"}).status_code == 200


# --------------------------------------------------------------------------
# ★ 익명 응답에 내부 필드가 없다 (SPEC 6.1 · Part 0-E #1 · 10.2 4단계)
# --------------------------------------------------------------------------

class TestInternalFieldIsAdditive:
    def test_the_anonymous_response_has_no_internal_key(self, client):
        response = client.post("/api/analyze", json=PROFILE)
        assert response.status_code == 200
        assert "internal" not in response.json(), "익명 응답에 내부 정보가 실렸다"
        # 키 자체가 없어야 한다. `null` 이 실리는 것과 다른 사실이다.
        assert b'"internal"' not in response.content

    #: API 가 엔진 출력 위에 얹는 최상단 키의 **전부**. 늘리려면 여기 적어야 하고,
    #: 적는 순간 「무엇을 왜 얹었는가」가 리뷰에 걸린다.
    #:
    #: `internal`(SPEC 6.1)은 인증된 요청에만 붙으므로 익명 응답에는 없다.
    #: `provenance` · `dataGrade`(D-13)는 **역할과 무관하게** 붙는다 — D-5 가
    #: 「거부하지 않고 등급을 붙인다」고 한 대상이 시민이기 때문이다.
    API_ADDED_TOP_LEVEL_KEYS = {"provenance", "dataGrade"}

    def test_the_anonymous_response_leaves_the_engine_output_byte_identical(
        self, client, store_url, frozen_clock
    ):
        """★ API 가 익명 **판정**을 한 바이트도 바꾸지 않았다.

        얹은 것이 있으면 여기서 드러난다. 시계가 고정돼 있으므로 `generatedAt` 까지
        포함해 비교한다 (SPEC 5.3 이 제외 목록을 없앤 뒤의 방식).

        ★ 2026-08-15 D-13 이 이 테스트를 「응답 == 엔진 출력」에서 「응답 - 얹은 키 ==
          엔진 출력」으로 바꿨다. 제외 목록이 아니라 **전수 목록**인 것이 요점이다 —
          위 집합에 없는 키가 하나라도 늘면 아래 두 번째 단언이 떨군다. 느슨해진 것이
          아니라 [무엇이 얹혔는가]가 명시적이 된 것이다.
        """
        from firsthome.engines import analyze as engine_analyze

        with create_store(store_url) as store:
            expected = engine_analyze(
                {**PROFILE},
                constants=MODEL_CONSTANTS,
                regions=read_regions(store),
                policies=read_active_policies(store, frozen_clock["now"]),
                now=frozen_clock["now"],
            )
        actual = client.post("/api/analyze", json=PROFILE).json()

        assert set(actual) - set(expected) == self.API_ADDED_TOP_LEVEL_KEYS, (
            "API 가 계약에 없는 최상단 키를 얹었다")
        assert {k: v for k, v in actual.items()
                if k not in self.API_ADDED_TOP_LEVEL_KEYS} == expected

    def test_a_counselor_gets_internal_and_nothing_else_changes(self, client):
        """스키마가 갈리지 않는다 — 같은 응답에 필드 하나가 더 붙을 뿐이다."""
        anonymous = client.post("/api/analyze", json=PROFILE).json()
        as_counselor(client)
        authenticated = client.post("/api/analyze", json=PROFILE).json()

        assert "internal" in authenticated
        assert {k: v for k, v in authenticated.items() if k != "internal"} == anonymous

    def test_a_rule_manager_also_gets_internal(self, client):
        as_rule_manager(client)
        assert "internal" in client.post("/api/analyze", json=PROFILE).json()

    def test_internal_carries_rule_versions_freshness_and_thresholds(self, client):
        as_counselor(client)
        internal = client.post("/api/analyze", json=PROFILE).json()["internal"]

        assert internal["ruleVersions"], "규칙 버전이 비어 있다"
        assert all(v["ruleVersionId"] for v in internal["ruleVersions"])
        assert internal["dataFreshness"]["regionCode"] == PROFILE["regionCode"]
        # 시드 시세는 출처가 특정되지 않았다 (SPEC 3.1). 그 사실이 그대로 드러나야 한다.
        assert internal["dataFreshness"]["verification"] == "unverified"

    def test_internal_does_not_repeat_the_public_reasons(self, client):
        """내부 정보의 값은 [왜 안 됐는지] 가 아니라 [문턱이 얼마인지] 다 (코디네이터 Q6)."""
        as_counselor(client)
        body = client.post("/api/analyze", json=PROFILE).json()
        for entry in body["internal"]["ineligiblePolicies"]:
            assert "reasons" not in entry
            assert entry["status"] != "eligible"
        # 문턱은 실제로 실려야 한다 — 안 실리면 이 필드가 존재할 이유가 없다.
        assert any(e["criteria"] for e in body["internal"]["ineligiblePolicies"])

    def test_an_expired_session_gets_the_anonymous_response_not_a_401(
        self, client, frozen_clock
    ):
        """세션이 끊긴 상담원의 화면에서 **판정 자체가 죽으면 안 된다.**"""
        as_counselor(client)
        frozen_clock["now"] = T0 + timedelta(
            seconds=MODEL_CONSTANTS[SESSION_ABSOLUTE_TIMEOUT_KEY]
        )
        response = client.post("/api/analyze", json=PROFILE)
        assert response.status_code == 200
        assert "internal" not in response.json()


# --------------------------------------------------------------------------
# 승인 — 거부의 대조군 (SPEC 4.6 · 6.1 · 7.1)
# --------------------------------------------------------------------------

class TestApproval:
    def test_a_rule_manager_can_approve(self, client, store_url):
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)

        response = client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "공고 개정 반영"},
            headers={CSRF_HEADER_NAME: csrf},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "approved"
        assert body["ruleVersionId"]

        with create_store(store_url) as store:
            version = store.rule_versions.get(body["ruleVersionId"])
            assert version.origin == "human_approval"
            assert version.approved_by == "user:rulemanager"
            assert version.supersedes == "seed:buttress_youth"
            assert store.rule_drafts.get(draft_id).status == "approved"
            assert [r.decision for r in store.approvals.list()] == ["approved"]

    def test_a_second_approval_is_refused_with_409(self, client, store_url):
        """★ SPEC 4.6 — 승인은 한 번만 일어나야 한다."""
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)
        first = client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "1차"}, headers={CSRF_HEADER_NAME: csrf},
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "2차"}, headers={CSRF_HEADER_NAME: csrf},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "draft_already_decided"

    def test_the_second_approval_creates_no_second_rule_version(self, client, store_url):
        """409 가 [메시지만 다르고 실은 두 번 승인] 이면 감사추적이 거짓말을 한다."""
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)
        client.post(f"/api/admin/drafts/{draft_id}/approve",
                    json={"reason": "1차"}, headers={CSRF_HEADER_NAME: csrf})
        with create_store(store_url) as store:
            after_first = {v.id for v in store.rule_versions.list()}

        client.post(f"/api/admin/drafts/{draft_id}/approve",
                    json={"reason": "2차"}, headers={CSRF_HEADER_NAME: csrf})

        with create_store(store_url) as store:
            assert {v.id for v in store.rule_versions.list()} == after_first
            assert len(store.approvals.list()) == 1

    def test_the_approved_rule_reaches_the_judgment_without_a_restart(self, client, store_url):
        """SPEC 2.3 의 핵심 시연 장면 — 승인 -> 시민 화면 변화. 같은 프로세스다."""
        draft_id = seed_draft(store_url)
        before = client.post("/api/analyze", json=PROFILE).json()
        before_max = _policy(before, "buttress_youth")["maxAmountKRW"]

        csrf = as_rule_manager(client)
        client.post(f"/api/admin/drafts/{draft_id}/approve",
                    json={"reason": "개정"}, headers={CSRF_HEADER_NAME: csrf})

        after = client.post("/api/analyze", json=PROFILE).json()
        assert _policy(after, "buttress_youth")["maxAmountKRW"] == 250_000_000
        assert before_max != 250_000_000, "초안이 시드와 같은 값이라 아무것도 증명하지 못한다"

    def test_not_found_fields_do_not_overwrite_known_thresholds(self, client, store_url):
        """`not_found` 는 [원문에 없었다] 이지 [값이 없어졌다] 가 아니다.

        덮으면 이미 알고 있던 문턱이 승인 한 번에 사라지고 판정이 관대해진다.
        """
        draft_id = seed_draft(store_url)
        with create_store(store_url) as store:
            seeded = store.rule_versions.get("seed:buttress_youth").payload["criteria"]
        assert seeded["assetMaxKRW"], "픽스처 전제가 깨졌다 — 시드에 자산 상한이 있어야 한다"

        csrf = as_rule_manager(client)
        body = client.post(f"/api/admin/drafts/{draft_id}/approve",
                           json={"reason": "개정"}, headers={CSRF_HEADER_NAME: csrf}).json()

        with create_store(store_url) as store:
            criteria = store.rule_versions.get(body["ruleVersionId"]).payload["criteria"]
        assert criteria["assetMaxKRW"] == seeded["assetMaxKRW"], "not_found 필드가 덮였다"
        assert criteria["ageMax"] == 39, "원문에 있던 값은 반영되어야 한다"

    def test_a_top_level_not_found_field_is_not_overwritten_either(self, client, store_url):
        """`not_found` 는 `/criteria/...` 뿐 아니라 **최상위 필드**도 가리킨다.

        ★ 이 테스트는 변이 심기에서 나왔다. `/criteria/assetMaxKRW` 만 덮던 픽스처로는
          최상위 분기(`f"/{name}" in not_found`)를 지워도 아무도 빨간불을 켜지 않았다 —
          규칙은 있는데 검사가 없는 상태였다. 방향이 관대한 쪽이라 특히 위험하다:
          한도가 `null` 이 되면 그 정책은 금액 제한 없이 통과한다.
        """
        with create_store(store_url) as store:
            store.policy_sources.add(PolicySource(
                id="src-2", text="한도는 공고에 적혀 있지 않다.", source_ref=None,
                fetched_at=T0, attribution="주택도시기금 공고"))
            store.rule_drafts.add(RuleDraft(
                id="draft-2", policy_source_id="src-2", policy_id="buttress_youth",
                status="pending",
                payload={**DRAFT_PAYLOAD, "maxAmountKRW": None,
                         "not_found": ["/maxAmountKRW"]},
                created_at=T0))
            seeded_max = store.rule_versions.get("seed:buttress_youth").payload["maxAmountKRW"]
        assert seeded_max, "픽스처 전제가 깨졌다 — 시드에 한도가 있어야 한다"

        csrf = as_rule_manager(client)
        body = client.post("/api/admin/drafts/draft-2/approve",
                           json={"reason": "개정"}, headers={CSRF_HEADER_NAME: csrf}).json()

        with create_store(store_url) as store:
            payload = store.rule_versions.get(body["ruleVersionId"]).payload
        assert payload["maxAmountKRW"] == seeded_max, (
            "원문에 없던 한도가 기존 값을 null 로 덮었다 — 그 정책이 무제한이 된다")

    def test_the_approved_version_does_not_claim_to_be_verified(self, client, store_url):
        """사람의 승인은 [추출이 원문과 일치한다] 이지 [원문이 지금도 유효하다] 가 아니다."""
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)
        body = client.post(f"/api/admin/drafts/{draft_id}/approve",
                           json={"reason": "개정"}, headers={CSRF_HEADER_NAME: csrf}).json()
        with create_store(store_url) as store:
            provenance = store.rule_versions.get(body["ruleVersionId"]).provenance
        assert provenance.verification == "unverified"
        assert provenance.observed_at is None

    def test_the_approval_is_audited(self, client, store_url):
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)
        client.post(f"/api/admin/drafts/{draft_id}/approve",
                    json={"reason": "개정"}, headers={CSRF_HEADER_NAME: csrf})
        assert ("rule.approve", "rulemanager", "success") in audit_actions(store_url)

    def test_rejecting_without_a_reason_is_refused(self, client, store_url):
        draft_id = seed_draft(store_url)
        csrf = as_rule_manager(client)
        for body in ({}, {"reason": None}, {"reason": "   "}):
            response = client.post(f"/api/admin/drafts/{draft_id}/reject",
                                   json=body, headers={CSRF_HEADER_NAME: csrf})
            assert response.status_code == 400, body
            assert response.json()["error"]["code"] == "reason_required"

    def test_rejecting_creates_no_rule_version(self, client, store_url):
        draft_id = seed_draft(store_url)
        with create_store(store_url) as store:
            before = {v.id for v in store.rule_versions.list()}

        csrf = as_rule_manager(client)
        response = client.post(f"/api/admin/drafts/{draft_id}/reject",
                               json={"reason": "원문과 다르다"}, headers={CSRF_HEADER_NAME: csrf})
        assert response.status_code == 200
        assert response.json()["ruleVersionId"] is None

        with create_store(store_url) as store:
            assert {v.id for v in store.rule_versions.list()} == before
            assert store.rule_drafts.get(draft_id).status == "rejected"
            assert [r.reason for r in store.approvals.list()] == ["원문과 다르다"]

    def test_an_unknown_draft_is_404(self, client, store_url):
        csrf = as_rule_manager(client)
        response = client.post("/api/admin/drafts/nope/approve",
                               json={"reason": "x"}, headers={CSRF_HEADER_NAME: csrf})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "draft_not_found"

    def test_the_draft_list_and_audit_are_readable_by_the_rule_manager(self, client, store_url):
        seed_draft(store_url)
        as_rule_manager(client)

        drafts = client.get("/api/admin/drafts")
        assert drafts.status_code == 200
        assert [d["id"] for d in drafts.json()["drafts"]] == ["draft-1"]

        events = client.get("/api/admin/audit")
        assert events.status_code == 200
        assert any(e["action"] == "auth.login" for e in events.json()["events"])


def _policy(body: dict, policy_id: str) -> dict:
    found = [p for p in body["policies"] if p["id"] == policy_id]
    assert found, f"{policy_id} 가 응답에 없다"
    return found[0]
