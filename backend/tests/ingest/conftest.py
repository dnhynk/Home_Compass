"""ingest 테스트 공통 픽스처.

`store` 픽스처는 `tests/store/conftest.py` 와 같은 이유로 **두 백엔드로 파라미터화**한다.
적재 경로가 SQLite 에서만 도는 것이면 부록 A 의 "교체 가능"이 ingest 에서 깨진다.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# `tests/store/memory_backend.py` 를 재사용한다. 두 번째 구현을 또 만들면 그때부터
# 두 메모리 백엔드가 서로 갈라진다.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "store"),
)

from home_compass.store import create_store, register_backend  # noqa: E402
from memory_backend import MemoryStore  # noqa: E402

KST = timezone(timedelta(hours=9))

register_backend("memory", MemoryStore.open)


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite://{tmp_path / 'store.db'}"
    else:
        url = f"memory://ingest-{request.node.name}"
    with create_store(url) as opened:
        yield opened


@pytest.fixture
def run_at() -> datetime:
    """배치를 **돌린** 시각. 고정값이다 — 결과가 "언제 돌렸는가"에 의존하면 아무것도 고정하지 못한다.

    `sources.COLLECTION_RUN_AT`(원문을 **취득한** 시각)과 **일부러 다른 값**이다.
    같은 값으로 두면 둘을 뒤바꿔 써도 테스트가 통과한다.
    """
    return datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)
