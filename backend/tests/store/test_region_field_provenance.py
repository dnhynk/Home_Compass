"""SPEC 2.1 · 3.1 — `Region` 의 계보는 **사실 단위**여야 한다.

0단계는 지역당 `Provenance` 하나로 지었다. 시세 수집(3단계)이 실제로 값을 넣기 시작하면
그 단순화가 SPEC 10.2 의 3단계 완료 기준 **둘을 동시에 만족시킬 수 없게** 만든다.

    · 외부 실패 시 이전 값 유지 + `stale` 표시
    · 대응물 없는 3필드가 `unverified` 로 드러난다 (3.1)

3필드(`maintenanceFeeKRW` · `marketRisk` · `guaranteeAvailable`)는 실거래가에 대응물이
없어 **항상** `unverified` 다. 등급은 가장 나쁜 것이 이기므로(2.4) 지역 레코드는 언제나
`unverified` 가 되고, 그러면 `stale` 은 **한 번도 보이지 않는다.** 한 칸으로는 안 된다.

10.2 의 문면이 이미 필드 단위다 — "대응물 없는 **3필드가** unverified 로 드러난다".

레코드 단위 `provenance` 는 **지우지 않고 최악값 요약으로 남긴다.** 그래야 `to_engine_dict()`
와 골든이 움직이지 않는다 — 이 과업은 판정을 건드리지 않는다.
"""

from __future__ import annotations

import pytest
from conftest import UNVERIFIED_MARKET, make_region

from firsthome.store.errors import ProvenanceError, StoreError
from firsthome.store.models import (
    REGION_FACT_FIELDS,
    Provenance,
    Region,
    worst_verification,
)

VERIFIED_MARKET = Provenance(
    source_kind="market",
    source_name="국토교통부 아파트 전월세 실거래가",
    source_ref="https://www.data.go.kr/data/15126474/openapi.do",
    observed_at="2026-06-01T00:00:00+09:00",
    fetched_at="2026-08-14T09:00:00+09:00",
    verification="verified",
)

STALE_MARKET = Provenance(**{**VERIFIED_MARKET.to_dict(), "verification": "stale"})


def _all_fields(provenance: Provenance) -> dict[str, Provenance]:
    return {name: provenance for name in REGION_FACT_FIELDS}


# --------------------------------------------------------------------------
# 1. 왕복 — 두 백엔드 모두에서 필드별 계보가 살아남는가
# --------------------------------------------------------------------------


def test_field_provenance_round_trips(store):
    mixed = _all_fields(VERIFIED_MARKET)
    for name in ("maintenanceFeeKRW", "marketRisk", "guaranteeAvailable"):
        mixed[name] = UNVERIFIED_MARKET

    store.regions.upsert(make_region("11440", field_provenance=mixed, provenance=UNVERIFIED_MARKET))
    region = store.regions.get("11440")

    assert set(region.field_provenance) == set(REGION_FACT_FIELDS)
    assert region.field_provenance["jeonseMedianKRW"] == VERIFIED_MARKET
    assert region.field_provenance["maintenanceFeeKRW"] == UNVERIFIED_MARKET
    # 레코드 요약은 그대로 남는다 — to_engine_dict() 와 골든이 이것을 본다.
    assert region.provenance == UNVERIFIED_MARKET


def test_three_fields_without_a_source_are_unverified_while_the_rest_are_not(store):
    """SPEC 10.2 3단계 — "대응물 없는 3필드가 unverified 로 드러난다".

    이 테스트가 **지역 단위 계보로는 쓸 수 없다.** 그것이 이 변경의 이유 전부다.
    """
    mixed = _all_fields(VERIFIED_MARKET)
    for name in ("maintenanceFeeKRW", "marketRisk", "guaranteeAvailable"):
        mixed[name] = UNVERIFIED_MARKET

    store.regions.upsert(make_region("11440", field_provenance=mixed, provenance=UNVERIFIED_MARKET))
    got = store.regions.get("11440").field_provenance

    unverified = {n for n, p in got.items() if p.verification == "unverified"}
    assert unverified == {"maintenanceFeeKRW", "marketRisk", "guaranteeAvailable"}


def test_stale_and_unverified_are_visible_at_the_same_time(store):
    """두 기준이 **동시에** 관측된다. 한 칸이던 시절에는 불가능했다."""
    mixed = _all_fields(STALE_MARKET)
    for name in ("maintenanceFeeKRW", "marketRisk", "guaranteeAvailable"):
        mixed[name] = UNVERIFIED_MARKET

    store.regions.upsert(make_region("11440", field_provenance=mixed, provenance=UNVERIFIED_MARKET))
    got = store.regions.get("11440").field_provenance

    assert got["jeonseMedianKRW"].verification == "stale"
    assert got["marketRisk"].verification == "unverified"


def test_list_carries_field_provenance_too(store):
    store.regions.upsert(make_region("11440", field_provenance=_all_fields(VERIFIED_MARKET),
                                     provenance=VERIFIED_MARKET))
    store.regions.upsert(make_region("11620", field_provenance=_all_fields(STALE_MARKET),
                                     provenance=STALE_MARKET))

    by_code = {r.code: r for r in store.regions.list()}
    assert by_code["11440"].field_provenance["monthlyRentKRW"].verification == "verified"
    assert by_code["11620"].field_provenance["monthlyRentKRW"].verification == "stale"


def test_upsert_replaces_the_whole_field_provenance_set(store):
    """부분 갱신을 남기지 않는다. 이전 배치의 계보가 새 배치의 계보와 섞이면
    그 레코드가 무엇을 뜻하는지 아무도 말할 수 없다."""
    store.regions.upsert(make_region("11440", field_provenance=_all_fields(VERIFIED_MARKET),
                                     provenance=VERIFIED_MARKET))
    store.regions.upsert(make_region("11440", field_provenance=_all_fields(STALE_MARKET),
                                     provenance=STALE_MARKET))

    got = store.regions.get("11440").field_provenance
    assert set(got) == set(REGION_FACT_FIELDS)
    assert {p.verification for p in got.values()} == {"stale"}


# --------------------------------------------------------------------------
# 2. 없어도 되는가 — 기존 레코드는 그대로 동작해야 한다
# --------------------------------------------------------------------------


def test_field_provenance_is_optional(store):
    """0단계 이전 방식으로 만든 레코드가 계속 돈다. 이 변경은 추가이지 교체가 아니다."""
    store.regions.upsert(make_region("11440"))
    region = store.regions.get("11440")

    assert region.field_provenance == {}
    # 필드별 계보가 없으면 레코드 계보가 그 필드의 계보다.
    assert region.provenance_for("jeonseMedianKRW") is region.provenance


def test_provenance_for_returns_the_field_entry_when_present(store):
    store.regions.upsert(make_region("11440", field_provenance=_all_fields(VERIFIED_MARKET),
                                     provenance=VERIFIED_MARKET))
    region = store.regions.get("11440")
    assert region.provenance_for("marketRisk") == VERIFIED_MARKET


# --------------------------------------------------------------------------
# 3. 불변식 — 요약이 거짓말을 하지 못하게 한다
# --------------------------------------------------------------------------


def test_unknown_field_name_is_refused(store):
    """오타 하나로 계보가 조용히 사라지는 경로를 만들지 않는다."""
    with pytest.raises(StoreError) as exc:
        store.regions.upsert(make_region("11440", field_provenance={"jeonseMedian": VERIFIED_MARKET}))
    assert "jeonseMedian" in str(exc.value)


def test_field_provenance_is_validated_against_the_contract(store):
    """계약 스키마(SPEC 2.1)를 필드별 항목에도 그대로 건다."""
    broken = Provenance(
        source_kind="market",
        source_name=None,  # market 은 source_name 이 필수다
        source_ref=None,
        observed_at=None,
        fetched_at=None,
        verification="verified",
    )
    with pytest.raises(ProvenanceError):
        store.regions.upsert(make_region("11440", field_provenance={"marketRisk": broken}))


def test_record_summary_must_be_the_worst_of_the_fields(store):
    """SPEC 2.4 — 가장 나쁜 등급이 이긴다. 요약이 필드보다 좋으면 거짓말이다.

    이 검사가 없으면 배치가 3필드를 unverified 로 적어 두고도 레코드 요약만
    `verified` 로 올려 등급을 통과시킬 수 있다. 그것이 정확히 SPEC 3.1 이 금지한
    "예시값을 실데이터인 척" 두는 경로다.
    """
    mixed = _all_fields(VERIFIED_MARKET)
    mixed["marketRisk"] = UNVERIFIED_MARKET

    with pytest.raises(StoreError) as exc:
        store.regions.upsert(make_region("11440", field_provenance=mixed, provenance=VERIFIED_MARKET))
    assert "unverified" in str(exc.value)


def test_record_summary_equal_to_the_worst_is_accepted(store):
    mixed = _all_fields(VERIFIED_MARKET)
    mixed["marketRisk"] = UNVERIFIED_MARKET
    store.regions.upsert(make_region("11440", field_provenance=mixed, provenance=UNVERIFIED_MARKET))
    assert store.regions.get("11440").provenance.verification == "unverified"


# --------------------------------------------------------------------------
# 4. 최악값 규칙 자체 (SPEC 2.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "values, expected",
    [
        (["verified"], "verified"),
        (["verified", "stale"], "stale"),
        (["verified", "stale", "unverified"], "unverified"),
        (["stale", "unverified"], "unverified"),
        # our_choice 는 신선도 개념이 없어 등급에 들어가지 않는다 (SPEC 2.4).
        (["verified", "our_choice"], "verified"),
        (["our_choice"], None),
        ([], None),
    ],
)
def test_worst_verification(values, expected):
    assert worst_verification(values) == expected


# --------------------------------------------------------------------------
# 5. 불변성 — 돌려받은 객체를 고쳐도 저장소는 그대로다
# --------------------------------------------------------------------------


def test_returned_field_provenance_cannot_be_mutated(store):
    store.regions.upsert(make_region("11440", field_provenance=_all_fields(VERIFIED_MARKET),
                                     provenance=VERIFIED_MARKET))
    region = store.regions.get("11440")
    with pytest.raises(TypeError):
        region.field_provenance["marketRisk"] = UNVERIFIED_MARKET


def test_region_is_still_frozen():
    region = Region(
        code="11440",
        name="서울 마포구",
        jeonse_median_krw=1,
        monthly_deposit_krw=1,
        monthly_rent_krw=1,
        maintenance_fee_krw=1,
        jeonse_ratio_pct=1.0,
        conversion_rate_pct=1.0,
        market_risk="low",
        guarantee_available=True,
        provenance=UNVERIFIED_MARKET,
    )
    with pytest.raises(Exception):
        region.name = "다른 이름"  # type: ignore[misc]
