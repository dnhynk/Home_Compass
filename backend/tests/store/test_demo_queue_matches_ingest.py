"""굳힌 원문이 **적재 경로가 낸 것과 같은가** (계약 결정 #15 · #42).

`store/seed.py` 는 `PolicySource` 를 스스로 만든다. 적재를 다시 구현해서가 아니라
`ingest.loader` 를 부를 수 없기 때문이다 — SPEC 1.2 가 `store -> ingest` 를 금지하고
`crosscheck/test_architecture.py` 가 그것을 잡는다.

**그 제약이 만드는 위험이 하나 있다.** 적재 경로에는 게이트가 걸려 있다 — 이용조건이
확인되지 않은 원문은 적재하지 않고(`LICENCES_CLEARED`), 출처표시가 없으면 예외로 터진다
(계약 결정 #15). 시드가 그 게이트를 통과하지 않고 같은 표를 만들면, **게이트가 없는 두 번째
입구**가 생긴다. 굳힐 때의 그 배치는 게이트를 통과했지만, 그 사실은 굳힌 파일 안에서
조용히 낡을 수 있다.

그래서 여기서 둘을 실제로 돌려 대조한다. 시드가 만든 표와 적재가 만든 표가 한 글자라도
다르면 이 파일이 터진다. **테스트는 `src/home_compass` 밖이므로 `ingest` 를 부를 수 있다** —
금지는 제품 코드의 의존 방향에 걸린 것이지 검사에 걸린 것이 아니다.
"""

from __future__ import annotations

import dataclasses

from conftest import T0

from home_compass.ingest.loader import load_policy_sources
from home_compass.ingest.sources import loadable_sources
from home_compass.store import create_store
from home_compass.store.seed import load_demo_queue, seed_policy_sources


def _rows(store) -> dict:
    return {s.id: dataclasses.asdict(s) for s in store.policy_sources.list()}


def test_the_seeded_sources_are_what_the_ingest_path_produces(tmp_path):
    """★ 이 파일의 전부. 두 입구가 같은 표를 만드는지 실제로 돌려 확인한다."""
    with create_store(f"sqlite://{tmp_path / 'seeded.db'}") as seeded:
        seed_policy_sources(seeded)
        by_seed = _rows(seeded)

    with create_store(f"sqlite://{tmp_path / 'ingested.db'}") as ingested:
        load_policy_sources(ingested, run_at=T0)
        by_ingest = _rows(ingested)

    assert by_seed == by_ingest, (
        "굳힌 원문이 적재 경로의 산출물과 다르다. 시드가 게이트 없는 두 번째 입구가 됐다는 "
        "뜻이므로, 초안을 다시 굳혀라 (rule_drafts.json 의 _regeneration)."
    )


def test_the_fixture_covers_exactly_the_loadable_ledger_rows():
    """대장이 늘거나 줄면 굳힌 것과 어긋난다.

    조용히 어긋나면 **적재는 되는데 초안이 없는 원문**이 생기고, 큐에서 그 제도만 사라진다.
    빠진 것을 눈에 보이게 하려고 양방향으로 조인다.
    """
    declared = {s["id"] for s in load_demo_queue()["policySources"]}
    ledger = {s.source_id for s in loadable_sources()}

    assert not ledger - declared, (
        f"적재 대장에 있는데 굳혀지지 않았다: {sorted(ledger - declared)} — 다시 굳혀라")
    assert not declared - ledger, (
        f"굳혀졌는데 적재 대장에 없다: {sorted(declared - ledger)} — 이용조건이 회수됐는지 본다")


def test_the_attribution_the_fixture_carries_is_the_one_the_ledger_requires():
    """계약 결정 #15 — 출처표시 없이는 적재하지 않는다. 굳힌 것도 예외가 아니다."""
    declared = {s["id"]: s for s in load_demo_queue()["policySources"]}
    for source in loadable_sources():
        entry = declared[source.source_id]
        assert entry["attribution"] == source.attribution, source.source_id
        assert entry["sourceRef"] == source.url, source.source_id
