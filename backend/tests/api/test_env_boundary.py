"""배포 경계 값의 도달과 침묵 (SPEC 6.3 · 부록 A, 소유자: `api`).

여기서 지키는 것은 기능이 아니라 **말하기**다. 두 결함 모두 [잘못된 값이 적용된 것]이
아니라 [적용되지 않았는데 아무도 그렇게 말하지 않은 것]이었고, 회수 시점이 각각
[HTTPS 에 Secure 없는 쿠키가 이미 나간 뒤]와 [로그인이 안 될 때]였다.

  ★ `.env` 의 배포 경계 키는 읽히지 않고, 읽지 않았다고 말한다  -> `TestProcessOnlyKeys`
  ★ 올바른 설정에서는 경고가 뜨지 않는다                        -> `TestWarningIsNotNoise`
  ★ 이미 있는 계정의 주입 비밀번호를 버렸다고 말한다            -> `TestSeedPasswordIsNotSilent`
  ★ 런북이 적은 회전 절차가 실제로 동작한다                     -> `TestDocumentedRotationPath`

허용목록(`config.ENV_KEYS`)을 넓히지 않는 것이 이 파일의 전제다. 넓히면 `.env.example`
사본이 배포의 쿠키 보안을 정하게 된다 — 근거는 `config.PROCESS_ONLY_KEYS` 주석에 있다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from home_compass import auth as auth_module
from home_compass.auth import (
    COUNSELOR_PASSWORD_ENV,
    RULE_MANAGER_PASSWORD_ENV,
    COOKIE_SECURE_ENV,
    cookie_secure,
    ensure_seed_accounts,
    verify_password,
)
from home_compass.config import (
    ENV_KEYS,
    LOG_FILE_ENV,
    PROCESS_ONLY_KEYS,
    ignored_process_only_keys,
    load_env_file,
    parse_env_text,
)
from home_compass.store import STORE_URL_ENV, create_store

REPO_ROOT = Path(__file__).resolve().parents[3]

T0 = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# ★ 배포 경계 키는 `.env` 에서 읽히지 않고, 읽지 않았다고 말한다
# --------------------------------------------------------------------------

class TestProcessOnlyKeys:
    def test_cookie_secure_in_a_dotenv_file_is_not_applied(self, tmp_path, monkeypatch):
        """재현: `.env` 에 true 를 적어도 `cookie_secure()` 는 False 다.

        이 단언이 뒤집히면 허용목록이 넓어진 것이고, 그때 `.env.example` 사본의
        `false` 가 HTTPS 배포에서 Secure 를 끄는 실효 설정이 된다.
        """
        env_file = tmp_path / ".env"
        env_file.write_text(f"{COOKIE_SECURE_ENV}=true\n", encoding="utf-8")
        monkeypatch.delenv(COOKIE_SECURE_ENV, raising=False)

        applied = load_env_file(env_file, warn=lambda lines: None)

        assert COOKIE_SECURE_ENV not in applied
        assert COOKIE_SECURE_ENV not in __import__("os").environ
        assert cookie_secure() is False

    def test_the_loader_says_which_keys_it_dropped(self, tmp_path, monkeypatch):
        """★ 결함의 본체. 버린 키를 말하지 않으면 운영자는 적용된 줄 안다."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"{COOKIE_SECURE_ENV}=true\nHOME_COMPASS_ENV=production\nOPENAI_API_KEY=sk-x\n",
            encoding="utf-8",
        )
        for key in (COOKIE_SECURE_ENV, "HOME_COMPASS_ENV", "OPENAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        warned: list[list[str]] = []

        load_env_file(env_file, warn=warned.append)

        assert len(warned) == 1, "버린 키가 있는데 말하지 않았다"
        printed = "\n".join(warned[0])
        assert COOKIE_SECURE_ENV in printed
        assert "HOME_COMPASS_ENV" in printed
        assert "적용되지 않은" in printed, "버렸다는 사실이 문장으로 없다"

    def test_process_only_keys_stay_in_sync_with_their_owners(self):
        """이름이 두 곳에 적혀 있으므로 어긋나면 경고가 조용히 죽는다.

        `config` 는 최하위 계층이라 `auth`·`store` 를 import 하지 않는다. 그 대가가
        리터럴 중복이고, 그것을 여기서 갚는다.
        """
        for name in (
            COOKIE_SECURE_ENV,
            COUNSELOR_PASSWORD_ENV,
            RULE_MANAGER_PASSWORD_ENV,
            LOG_FILE_ENV,
            STORE_URL_ENV,
        ):
            assert name in PROCESS_ONLY_KEYS, f"{name} 이 경고 대상에서 빠졌다"

        # `scripts/start_server.py:29` 의 `DEPLOYMENT_ENV`. 그 파일은 패키지가 아니라
        # import 하지 않고 이름만 맞춘다 — fail-closed 게이트가 이 키에 걸려 있다.
        assert "HOME_COMPASS_ENV" in PROCESS_ONLY_KEYS

    def test_no_key_is_in_both_lists(self):
        """한 키가 [읽는다]와 [읽지 않는다]에 동시에 있으면 경고가 거짓말이 된다."""
        assert not set(ENV_KEYS) & set(PROCESS_ONLY_KEYS)

    def test_the_template_never_assigns_a_key_it_cannot_apply(self):
        """★ `.env.example` 이 동작하지 않는 값을 동작하는 것처럼 보여주지 않는다.

        주석으로 이름을 적는 것은 괜찮다. `KEY=값` 으로 적는 것이 거짓이다.
        """
        template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assigned = set(parse_env_text(template))
        offenders = sorted(assigned & set(PROCESS_ONLY_KEYS))
        assert not offenders, f".env.example 이 도달하지 않는 키에 값을 준다: {offenders}"


# --------------------------------------------------------------------------
# ★ 올바른 설정에서 뜨는 경고는 경고 전체를 무시하게 만든다
# --------------------------------------------------------------------------

class TestWarningIsNotNoise:
    def test_molit_key_does_not_warn(self, tmp_path, monkeypatch):
        """`MOLIT_API_KEY` 는 `.env` 에 있는 것이 **정상**이다.

        `config.ENV_KEYS` 가 os.environ 에 싣지 않을 뿐,
        `ingest.market.source.resolve_api_key()` 가 이 파일을 직접 읽어 쓴다. 그래서
        허용목록 밖 키 전부를 보고하면 올바른 설정에서 매 기동 경고가 뜬다.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("MOLIT_API_KEY=abc123\nOPENAI_API_KEY=sk-x\n", encoding="utf-8")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        warned: list[list[str]] = []

        load_env_file(env_file, warn=warned.append)

        assert warned == [], "정상 설정에서 경고가 떴다"

    def test_the_shipped_template_is_silent(self, monkeypatch):
        """템플릿을 그대로 복사한 운영자에게는 아무 경고도 뜨지 않아야 한다."""
        template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert ignored_process_only_keys(parse_env_text(template)) == []


# --------------------------------------------------------------------------
# ★ 이미 있는 계정의 주입 비밀번호를 버렸다고 말한다 (H2)
# --------------------------------------------------------------------------

class TestSeedPasswordIsNotSilent:
    def test_a_changed_password_on_an_existing_account_is_announced(self, tmp_path):
        """영구 디스크 위의 재배포를 재현한다. 시드 멱등성은 그대로 두고 침묵만 고친다."""
        url = f"sqlite://{tmp_path / 'redeploy.db'}"
        first = {COUNSELOR_PASSWORD_ENV: "first-password-0000"}
        second = {COUNSELOR_PASSWORD_ENV: "second-password-999"}
        announced: list[list[str]] = []

        with create_store(url) as store:
            ensure_seed_accounts(store, now=T0, environ=first, announce=lambda _: None)
            results = ensure_seed_accounts(store, now=T0, environ=second, announce=announced.append)
            stored = store.users.get_by_username("counselor").password_hash

        counselor = next(r for r in results if r.username == "counselor")
        assert counselor.created is False, "멱등성이 깨졌다 — 계정을 다시 만들었다"
        assert counselor.injected_password_ignored is True
        assert verify_password(stored, "first-password-0000"), "기존 비밀번호가 바뀌었다"
        assert not verify_password(stored, "second-password-999")

        assert len(announced) == 1, "버린 사실을 말하지 않았다"
        printed = "\n".join(announced[0])
        assert "counselor" in printed
        assert "SUBMISSION_RUNBOOK" in printed, "회수 경로를 가리키지 않는다"

    def test_the_announcement_leaks_neither_the_password_nor_its_hash(self, tmp_path):
        """★ 값이나 해시를 찍으면 그것이 원래 결함보다 큰 결함이다."""
        url = f"sqlite://{tmp_path / 'noleak.db'}"
        old, new = "first-password-0000", "second-password-999"
        announced: list[list[str]] = []

        with create_store(url) as store:
            ensure_seed_accounts(
                store, now=T0, environ={COUNSELOR_PASSWORD_ENV: old}, announce=lambda _: None
            )
            ensure_seed_accounts(
                store, now=T0, environ={COUNSELOR_PASSWORD_ENV: new}, announce=announced.append
            )
            stored = store.users.get_by_username("counselor").password_hash

        printed = "\n".join(announced[0])
        assert old not in printed
        assert new not in printed
        assert stored not in printed
        assert not re.search(r"\$argon2", printed), "해시 조각이 새어 나갔다"

    def test_nothing_is_announced_when_nothing_was_dropped(self, tmp_path):
        """주입 없이 재기동하는 평범한 경우에는 조용해야 한다 — 경고의 신호대잡음."""
        url = f"sqlite://{tmp_path / 'quiet.db'}"
        announced: list[list[str]] = []

        with create_store(url) as store:
            ensure_seed_accounts(
                store,
                now=T0,
                environ={a.env_var: "seeded-password-0000" for a in auth_module.SEED_ACCOUNTS},
                announce=lambda _: None,
            )
            ensure_seed_accounts(store, now=T0, environ={}, announce=announced.append)

        assert announced == []


# --------------------------------------------------------------------------
# ★ 런북이 적은 회전 절차가 실제로 동작한다
# --------------------------------------------------------------------------

class TestDocumentedRotationPath:
    def test_deleting_the_seed_rows_rotates_without_touching_the_ledger(self, tmp_path):
        """`DELETE FROM app_user` 뒤 재기동하면 새 비밀번호가 적용된다.

        런북이 [디스크를 비워라]라고 적으면 승인된 RuleVersion 과 감사원장이 함께 죽는다.
        이 절차가 그 대안이며, **문서에 적기 전에 여기서 돌려 본다.**

        사용자 id 가 `user:{username}` 로 결정적이라(`auth.py`) 재시드가 같은 id 를
        복구한다 — 그래서 `approval_record.actor_user_id` 같은 참조가 끊기지 않는다.
        """
        url = f"sqlite://{tmp_path / 'rotate.db'}"
        old, new = "first-password-0000", "rotated-password-77"

        with create_store(url) as store:
            ensure_seed_accounts(
                store, now=T0, environ={COUNSELOR_PASSWORD_ENV: old}, announce=lambda _: None
            )
            before_id = store.users.get_by_username("counselor").id

        # 런북 절차: 시드 계정 행만 지운다. 스키마는 건드리지 않는다.
        import sqlite3

        with sqlite3.connect(tmp_path / "rotate.db") as conn:
            conn.execute(
                "DELETE FROM app_user WHERE username IN ('counselor', 'rulemanager')"
            )

        with create_store(url) as store:
            results = ensure_seed_accounts(
                store, now=T0, environ={COUNSELOR_PASSWORD_ENV: new}, announce=lambda _: None
            )
            after = store.users.get_by_username("counselor")

        assert [r.created for r in results] == [True, True], "재시드가 계정을 만들지 않았다"
        assert after.id == before_id, "id 가 달라지면 승인·감사 참조가 끊긴다"
        assert verify_password(after.password_hash, new), "새 비밀번호가 적용되지 않았다"
        assert not verify_password(after.password_hash, old)
