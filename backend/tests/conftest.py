import atexit
import os
import secrets
import shutil
import sys
import tempfile

import pytest

# Make `src/` importable without an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# --------------------------------------------------------------------------
# Wave 2 컷오버 — 기동이 저장소를 요구한다 (SPEC 1.2 생성 방향 · 5.1.1)
# --------------------------------------------------------------------------
#
# `home_compass.main` 을 import 하는 것이 곧 기동이다. 모듈 최상단에서 모델 상수 전수
# 존재를 검증하고, 컷오버 후 그 출처는 저장소다. 시드된 저장소가 없으면
# `tests/test_engines.py` 는 테스트가 한 건도 돌기 전에 collection 단계에서 죽는다.
#
# **개발자 로컬 DB(`backend/var/home_compass.db`)에 기대지 않는다.** 그것이 있으면 통과하고
# 없으면 깨지는 테스트는 신규 클론과 CI 에서만 빨간불이 되며, 그것이 Part 0-A 의
# "각자는 맞는데 합치면 틀린" 유형이다. 세션 전용 임시 저장소를 여기서 시드한다.
#
# 픽스처가 아니라 모듈 최상단인 이유: 테스트 모듈이 **collection 시점에**
# `home_compass.main` 을 import 하므로 세션 스코프 픽스처는 이미 늦다.
#
# 격리: 이 저장소는 읽기 전용으로만 쓰인다. 상수를 지워 기동 거부를 확인하는 테스트
# (`test_engine_constants.test_boot_is_refused_when_any_constant_is_missing`)는 자기
# `tmp_path` 에 별도 저장소를 만들며, 그 안에서 URL 이 여기와 다른지를 직접 확인한다.
_STORE_DIR = tempfile.mkdtemp(prefix="home_compass-tests-")
atexit.register(shutil.rmtree, _STORE_DIR, ignore_errors=True)
os.environ["HOME_COMPASS_STORE_URL"] = f"sqlite://{os.path.join(_STORE_DIR, 'session.db')}"

# --------------------------------------------------------------------------
# 4단계 — 시드 계정 비밀번호를 **환경변수로** 주입한다 (SPEC 6.3 · 부록 A)
# --------------------------------------------------------------------------
#
# `home_compass.main` 을 import 하면 기동 훅이 상담원·규칙관리자 계정을 만든다. 환경변수가
# 없으면 무작위 비밀번호를 만들어 stderr 에 찍고 버리는데, 그러면 테스트가 로그인할 수
# 없다. 여기서 거는 이유는 그 값이 **테스트용 상수**여야 하기 때문이지 편의가 아니다.
#
# 그리고 이것이 곧 SPEC 6.3 이 정한 주입 경로를 **테스트가 실제로 지나간다**는 뜻이다 —
# 무작위 생성 경로는 `tests/api/test_auth.py` 가 빈 환경으로 직접 부른다. 둘 다 덮인다.
#
# ★ 값을 **여기 적지 않는다.** 리터럴을 적으면 그것이 곧 [시드 계정 비밀번호가 커밋에
#   있는 상태]가 되고, SPEC 10.2 4단계 완료 기준의 하나가 테스트 픽스처에서 무너진다.
#   매 세션 무작위로 만들고 테스트는 `os.environ` 에서 읽는다.
#
# `setdefault` 인 이유: 진짜 환경변수가 이미 있으면 그쪽이 이긴다 (부록 A 의 주입 원칙).
os.environ.setdefault("HOME_COMPASS_SEED_COUNSELOR_PASSWORD", secrets.token_urlsafe(16))
os.environ.setdefault("HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD", secrets.token_urlsafe(16))

from home_compass.store import store_from_env  # noqa: E402
from home_compass.store.seed import seed_all  # noqa: E402

with store_from_env() as _session_store:
    seed_all(_session_store)


@pytest.fixture(autouse=True)
def offline_providers_by_default(monkeypatch):
    """Tests use deterministic providers unless they explicitly inject a mock key.

    A developer's .env and keys loaded by another test must never turn the test
    suite into paid API calls or make its result depend on network access.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
