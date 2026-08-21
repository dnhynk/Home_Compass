"""`api` 의 기동 경로 — 상수 주입과 fail-closed (소유자: `api`, SPEC 9.4).

`test_engine_constants.py` 는 **무엇을 검증해야 하는지**(`required_constant_keys`)를
engines 쪽에서 붙든다. 여기서는 **어떻게 검증하는지** — api 가 저장소를 열고, 타입을
되살리고, 없으면 거부하는 그 경로 — 를 붙든다.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from home_compass.engines import required_constant_keys
from home_compass.main import boot_model_constants, load_model_constants
from home_compass.store import STORE_URL_ENV, create_store, store_from_env
from home_compass.store.seed import seed_all


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("api-boot") / "seeded.db"
    with create_store(f"sqlite://{path}") as store:
        seed_all(store, at=datetime(2026, 8, 13, tzinfo=timezone.utc))
    return path


def _copy(seeded_db: Path, tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copy(seeded_db, target)
    return target


# --- 주입 매핑의 모양 -------------------------------------------------------

def test_the_boot_mapping_covers_every_key_the_engines_look_up(seeded_db):
    with create_store(f"sqlite://{seeded_db}") as store:
        mapping = load_model_constants(store)
    assert set(required_constant_keys()) <= set(mapping)


def test_json_only_types_survive_the_round_trip(seeded_db):
    """JSON 은 dict 의 int 키도 tuple 도 모른다.

    `{1: ...}` 가 `{"1": ...}` 로 돌아오면 `size in by_household` 가 조용히 거짓이 되고
    생활비가 0 이 된다 — 판정이 통째로 갈리는데 예외는 나지 않는다. 가장 위험한 종류의
    결함이라 기동 경로에서 직접 고정한다.
    """
    with create_store(f"sqlite://{seeded_db}") as store:
        mapping = load_model_constants(store)

    households = mapping["affordability.living_cost_by_household"]
    assert all(isinstance(size, int) for size in households), households
    assert households[1] > 0

    for key in ("engines.jeonse_loan_priority", "engines.monthly_loan_priority"):
        assert isinstance(mapping[key], tuple), f"{key}: {type(mapping[key])}"


def test_the_mapping_is_a_copy_not_a_live_view(seeded_db):
    """호출자가 돌려받은 매핑을 고쳐도 저장소는 변하지 않는다 (store 인터페이스 계약)."""
    with create_store(f"sqlite://{seeded_db}") as store:
        mapping = load_model_constants(store)
        mapping["affordability.buffer_ratio"] = 0.99
        assert store.model_constants.as_mapping()["affordability.buffer_ratio"] != 0.99


# --- fail-closed ------------------------------------------------------------

def test_a_missing_constant_refuses_the_boot_and_says_which_one(seeded_db, tmp_path):
    db = _copy(seeded_db, tmp_path, "missing.db")
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("DELETE FROM model_constant WHERE key = 'risk.band_low_max'")
    conn.close()

    with create_store(f"sqlite://{db}") as store:
        with pytest.raises(RuntimeError) as caught:
            load_model_constants(store)

    message = str(caught.value)
    assert "risk.band_low_max" in message
    # 시연 중에 이 메시지만 보고 조치할 수 있어야 한다.
    assert "seed_store.py" in message, "무엇을 하라는 안내가 없다"
    assert "fail-closed" in message


def test_an_empty_store_refuses_the_boot(tmp_path):
    """시드하지 않은 저장소로는 뜨지 않는다. 기동 경로에 자동 시드를 두지 않았기 때문이다.

    자동 시드를 넣으면 "상수 하나를 지우면 기동이 거부된다"(SPEC 10.2 1-①)가 성립하지
    않는다 — 지운 상수가 그 자리에서 되살아난다.
    """
    with create_store(f"sqlite://{tmp_path / 'empty.db'}") as store:
        with pytest.raises(RuntimeError) as caught:
            load_model_constants(store)
    assert "저장소에 0개" in str(caught.value)


# --- 기동이 환경변수를 따르는가 ---------------------------------------------

def test_boot_reads_the_store_the_environment_points_at(seeded_db, tmp_path, monkeypatch):
    """부록 A — 저장소는 설정 하나로 갈린다. 기동이 그 설정을 실제로 따르는지 본다."""
    db = _copy(seeded_db, tmp_path, "pointed.db")
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE model_constant SET value_json = '0.42'"
                     " WHERE key = 'affordability.buffer_ratio'")
    conn.close()

    monkeypatch.setenv(STORE_URL_ENV, f"sqlite://{db}")
    assert boot_model_constants()["affordability.buffer_ratio"] == 0.42


# --- 격리 (코디네이터 요구) --------------------------------------------------

def test_the_session_store_is_not_the_one_these_tests_mutate(seeded_db, tmp_path):
    """상수를 지우는 테스트들이 세션 저장소를 건드리지 않는다.

    conftest 가 세션 시작에 임시 저장소를 시드하고, 지우기 테스트는 전부 자기
    `tmp_path` 사본에서 논다. 그 분리를 여기서 못 박는다 — 새는 순간 뒤에 도는
    테스트가 이유 없이 빨간불이 되고, 원인은 순서에 따라 달라져 재현되지 않는다.
    """
    session_url = os.environ[STORE_URL_ENV]
    assert str(seeded_db) not in session_url
    assert str(tmp_path) not in session_url

    with store_from_env() as store:
        assert set(required_constant_keys()) <= set(store.model_constants.as_mapping())
