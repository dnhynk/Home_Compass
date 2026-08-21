"""잘못된 Provenance 가 저장소에 들어가면 안 된다.

정본은 `contracts/provenance.schema.json` 이다. 저장소가 그 스키마를 **저장 시점에** 건다.
검증을 응답 조립 시점으로 미루면 이미 들어온 잘못된 계보는 영원히 남는다.

SPEC 2.1 의 두 금지 규칙이 여기서 실제로 막히는지를 본다.
  - `our_choice` 는 `normative` 전용이다
  - `observed_at` · `fetched_at` 은 RFC 3339 **숫자 오프셋**이다. `Z` 로 뭉개지 않는다
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import OUR_CHOICE, make_constant, make_region, make_rule_version

from home_compass.store.errors import ProvenanceError
from home_compass.store.models import Provenance
from home_compass.store.provenance import provenance_schema, validate_provenance_dict

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_the_schema_the_store_enforces_is_the_contract_file_itself():
    """저장소가 자기만의 사본을 들고 있으면 계약이 갈라진다."""
    on_disk = json.loads((CONTRACTS / "provenance.schema.json").read_text(encoding="utf-8"))
    assert provenance_schema() == on_disk


def test_provenance_has_exactly_the_contract_fields():
    """필드를 늘리거나 줄이면 계약 위반이다.

    개수를 이름에 박지 않는다 — `observed_at_unstated` 가 6번째 뒤에 붙었을 때
    이 테스트가 잡아준 것이 SPEC 8.2 #3 이 원하는 동작이고, 그때 이름만 낡았다.
    """
    on_disk = json.loads((CONTRACTS / "provenance.schema.json").read_text(encoding="utf-8"))
    assert set(Provenance.__dataclass_fields__) == set(on_disk["properties"])


def test_the_omitted_when_unset_set_matches_the_contracts_optional_fields():
    """어느 필드가 '없어도 되는가' 는 계약의 `required` 가 정한다.

    이 목록을 손으로 관리하면, 계약이 다음 필드를 선택으로 만들 때 저장소가
    그것을 무조건 내보내 시드 레코드와 바이트 동일성이 조용히 깨진다.
    """
    on_disk = json.loads((CONTRACTS / "provenance.schema.json").read_text(encoding="utf-8"))
    optional = set(on_disk["properties"]) - set(on_disk["required"])
    assert set(Provenance.OMITTED_WHEN_UNSET) == optional


BAD_PROVENANCE = [
    pytest.param(
        dict(source_kind="statistic", source_name=None, source_ref=None,
             observed_at=None, fetched_at=None, verification="our_choice"),
        id="our_choice-on-a-non-normative-fact",
    ),
    pytest.param(
        dict(source_kind="normative", source_name=None, source_ref=None,
             observed_at=None, fetched_at=None, verification="unverified"),
        id="normative-must-always-be-our_choice",
    ),
    pytest.param(
        dict(source_kind="market", source_name="한국은행", source_ref="KOFR",
             observed_at="2026-08-13T00:00:00Z", fetched_at=None, verification="verified"),
        id="Z-notation-is-banned",
    ),
    pytest.param(
        dict(source_kind="statistic", source_name="가계동향조사", source_ref="KOSIS-XXX",
             observed_at=None, fetched_at=None, verification="verified"),
        id="verified-without-an-observation-instant",
    ),
    pytest.param(
        dict(source_kind="hearsay", source_name=None, source_ref=None,
             observed_at=None, fetched_at=None, verification="our_choice"),
        id="unknown-source_kind",
    ),
]


@pytest.mark.parametrize("bad", BAD_PROVENANCE)
def test_validator_rejects_forbidden_provenance(bad):
    with pytest.raises(ProvenanceError):
        validate_provenance_dict(bad)


@pytest.mark.parametrize("bad", BAD_PROVENANCE)
def test_region_write_rejects_forbidden_provenance(store, bad):
    with pytest.raises(ProvenanceError):
        store.regions.upsert(make_region("11440", provenance=Provenance(**bad)))
    assert store.regions.get("11440") is None, "거부된 뒤에도 행이 남았다"


@pytest.mark.parametrize("bad", BAD_PROVENANCE)
def test_model_constant_write_rejects_forbidden_provenance(store, bad):
    with pytest.raises(ProvenanceError):
        store.model_constants.put(make_constant(provenance=Provenance(**bad)))
    assert store.model_constants.list() == []


@pytest.mark.parametrize("bad", BAD_PROVENANCE)
def test_rule_version_write_rejects_forbidden_provenance(store, bad):
    with pytest.raises(ProvenanceError):
        store.rule_versions.add(make_rule_version("rv-1", provenance=Provenance(**bad)))
    assert store.rule_versions.list() == []


def test_a_valid_normative_provenance_round_trips_unchanged(store):
    store.model_constants.put(make_constant("affordability.buffer_ratio", provenance=OUR_CHOICE))
    stored = store.model_constants.get("affordability.buffer_ratio")
    assert stored.provenance == OUR_CHOICE


def test_a_verified_provenance_with_a_numeric_offset_is_accepted(store):
    kst = Provenance(
        source_kind="statistic",
        source_name="통계청 가계동향조사",
        source_ref="KOSIS-101",
        observed_at="2026-06-30T00:00:00+09:00",
        fetched_at="2026-08-13T09:00:00+09:00",
        verification="verified",
    )
    store.regions.upsert(make_region("11440", provenance=kst))
    assert store.regions.get("11440").provenance.observed_at == "2026-06-30T00:00:00+09:00"


# --------------------------------------------------------------------------
# observed_at_unstated (계약 결정 #10)
#
# 스키마가 이미 좁게 제약하고 교차 테스트에 음성 6건이 있다. 여기서는 저장소가
# **그 값을 온전히 실어 나르는지**만 본다 — 중복 검증을 쓰지 않는다.
# --------------------------------------------------------------------------

#: 실사에서 나온 실제 형태 — 원문은 확인했는데 그 원문이 기준시점을 안 밝힌 경우.
UNSTATED = Provenance(
    source_kind="statute",
    source_name="주택도시보증공사(HUG)",
    source_ref="https://www.khug.or.kr/",
    observed_at=None,
    fetched_at="2026-08-13T09:00:00+09:00",
    verification="verified",
    observed_at_unstated=True,
)


def test_the_unstated_flag_is_accepted_by_the_contract():
    validate_provenance_dict(UNSTATED.to_dict())


@pytest.mark.parametrize(
    "write, read",
    [
        ("regions", lambda s: s.regions.get("11440").provenance),
        ("model_constants", lambda s: s.model_constants.get("x.y").provenance),
        ("rule_versions", lambda s: s.rule_versions.get("rv-1").provenance),
    ],
)
def test_the_unstated_flag_round_trips_with_its_type(store, write, read):
    """`True` 로 넣은 것이 `1` 이나 `"true"` 로 돌아오면 `const: true` 를 더 이상 만족하지 못한다.

    SQLite 에는 boolean 이 없다 — JSON 을 거치는 경로가 그것을 지켜주는지 확인한다.
    """
    {
        "regions": lambda: store.regions.upsert(make_region("11440", provenance=UNSTATED)),
        "model_constants": lambda: store.model_constants.put(make_constant("x.y", provenance=UNSTATED)),
        "rule_versions": lambda: store.rule_versions.add(make_rule_version("rv-1", provenance=UNSTATED)),
    }[write]()

    stored = read(store)
    assert stored == UNSTATED
    assert stored.observed_at_unstated is True, f"타입이 바뀌었다: {stored.observed_at_unstated!r}"
    assert stored.observed_at is None, "기준시점을 모른다는 사실이 지워지면 안 된다"
    assert stored.verification == "verified"


def test_a_record_carrying_the_flag_serialises_it(store):
    store.regions.upsert(make_region("11440", provenance=UNSTATED))
    assert "observed_at_unstated" in store.regions.get("11440").provenance.to_dict()


def test_a_record_without_the_flag_has_no_such_key(store):
    """요건 1 — 값이 없으면 키도 없다. 기존 67개 시드 레코드가 여기 걸린다."""
    store.regions.upsert(make_region("11440"))
    emitted = store.regions.get("11440").provenance.to_dict()

    assert "observed_at_unstated" not in emitted
    assert set(emitted) == set(
        json.loads((CONTRACTS / "provenance.schema.json").read_text(encoding="utf-8"))["required"]
    )


def test_every_seed_provenance_in_the_registry_passes(store):
    """계약이 시드하라고 적어둔 값이 저장소 검증을 통과하지 못하면 0단계가 성립하지 않는다."""
    registry = json.loads((CONTRACTS / "model_constants.json").read_text(encoding="utf-8"))
    for entry in registry["entries"]:
        validate_provenance_dict(entry["seed_provenance"])
