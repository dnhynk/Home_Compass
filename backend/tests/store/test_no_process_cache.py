"""SPEC 2.3 — 프로세스 수명 캐시 금지.

현행 `engines/__init__.py` 는 `load_regions` · `load_policies` 를 `lru_cache(maxsize=1)` 로
감싸 프로세스가 사는 동안 파일을 다시 읽지 않는다. 이 상태로 저장소를 붙이면 **배치가 갱신해도,
규칙관리자가 승인해도 재기동 전까지 판정에 반영되지 않는다.** 핵심 시연 장면
(승인 -> 시민 화면 변화)이 그 자리에서 무너진다.

여기서는 저장소 계층이 그 결함을 반복하지 않음을 두 방향으로 고정한다.
  - 구조: store/ 소스에 메모이제이션 데코레이터가 존재하지 않는다
  - 행동: 재기동 없이 갱신이 다음 조회에 보인다
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import T0, make_constant, make_region, make_rule_version

import firsthome.store
from firsthome.store import create_store

STORE_DIR = Path(firsthome.store.__file__).resolve().parent


# --------------------------------------------------------------------------
# 구조 — 메모이제이션 자체가 없다
# --------------------------------------------------------------------------


def test_store_package_uses_no_memoisation_decorator():
    """`lru_cache` 는 여기서 금지어다. 있으면 그 자리가 곧 결함이다."""
    banned = re.compile(r"@(functools\.)?(lru_cache|cache)\b|\blru_cache\s*\(")
    offenders = []
    for path in sorted(STORE_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line):
                offenders.append(f"{path.relative_to(STORE_DIR)}:{lineno}: {line.strip()}")
    assert not offenders, "저장소에 프로세스 수명 캐시가 들어왔다:\n" + "\n".join(offenders)


def test_store_package_does_not_import_lru_cache():
    offenders = [
        str(p.relative_to(STORE_DIR))
        for p in sorted(STORE_DIR.rglob("*.py"))
        if "lru_cache" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


# --------------------------------------------------------------------------
# 행동 — 재기동 없이 보인다
# --------------------------------------------------------------------------


def test_region_update_is_visible_on_the_next_read(store):
    store.regions.upsert(make_region("11440", jeonse_median_krw=280_000_000))
    assert store.regions.get("11440").jeonse_median_krw == 280_000_000

    store.regions.upsert(make_region("11440", jeonse_median_krw=310_000_000))
    assert store.regions.get("11440").jeonse_median_krw == 310_000_000, "배치 갱신이 조회에 반영되지 않았다"


def test_model_constant_update_is_visible_on_the_next_read(store):
    store.model_constants.put(make_constant("affordability.buffer_ratio", value=0.10))
    assert store.model_constants.as_mapping()["affordability.buffer_ratio"] == 0.10

    store.model_constants.put(make_constant("affordability.buffer_ratio", value=0.15))
    assert store.model_constants.as_mapping()["affordability.buffer_ratio"] == 0.15


def test_the_demo_scene_survives_without_a_restart(store):
    """승인 -> 시민 화면 변화. 재기동이 끼면 시연이 그 자리에서 무너진다."""
    before = store.rule_versions.active(T0)
    assert before == []

    store.rule_versions.add(make_rule_version("rv-1", effective_from=None))

    after = store.rule_versions.active(T0)
    assert [v.id for v in after] == ["rv-1"], "승인 직후 조회가 이전 결과를 재사용했다"


def test_a_cutover_is_visible_immediately_after_supersede(store):
    store.rule_versions.add(make_rule_version("rv-1", effective_from=None))
    cutover = T0 + timedelta(days=1)

    assert [v.id for v in store.rule_versions.active(cutover)] == ["rv-1"]

    store.rule_versions.supersede(
        "rv-1",
        make_rule_version("rv-2", effective_from=cutover, supersedes="rv-1"),
        at=cutover,
    )

    assert [v.id for v in store.rule_versions.active(cutover)] == ["rv-2"]


def test_a_second_store_instance_sees_committed_writes(sqlite_url):
    """같은 프로세스 안의 다른 인스턴스가 이전 스냅샷을 붙들고 있으면 안 된다.

    이것이 실제 배치·API 배치도다 — 배치가 쓰고 API 가 읽는다.
    """
    with create_store(sqlite_url) as writer, create_store(sqlite_url) as reader:
        assert reader.regions.get("11440") is None

        writer.regions.upsert(make_region("11440", jeonse_median_krw=280_000_000))
        assert reader.regions.get("11440").jeonse_median_krw == 280_000_000

        writer.regions.upsert(make_region("11440", jeonse_median_krw=310_000_000))
        assert reader.regions.get("11440").jeonse_median_krw == 310_000_000


def test_reopening_the_same_file_returns_the_persisted_state(sqlite_url):
    with create_store(sqlite_url) as store:
        store.regions.upsert(make_region("11440", jeonse_median_krw=280_000_000))

    with create_store(sqlite_url) as reopened:
        assert reopened.regions.get("11440").jeonse_median_krw == 280_000_000


@pytest.mark.parametrize("reads", [1, 2, 5])
def test_repeated_reads_do_not_freeze_the_first_answer(store, reads):
    store.regions.upsert(make_region("11440", jeonse_median_krw=100))
    for _ in range(reads):
        store.regions.list()

    store.regions.upsert(make_region("11440", jeonse_median_krw=200))
    assert [r.jeonse_median_krw for r in store.regions.list()] == [200]
