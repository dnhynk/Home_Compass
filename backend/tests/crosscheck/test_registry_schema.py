"""교차 테스트 — 레지스트리 자체의 스키마 검증 (코디네이터 소유, SPEC 9.4).

## 왜 이 파일이 늦게 생겼는가

`contracts/model_constants.json` 은 부트스트랩부터 `"$schema": "./model_constants.registry.schema.json"`
을 적고 있었다. **그 파일이 존재하지 않았다.** 그래서 레지스트리는 26 → 68 키로 자라는 동안
**어떤 스키마 검증도 받지 않았고**, 새 `value_type` 3종이 들어갈 때 아무 저항이 없었다.
W-engines-4 가 자기 과업과 무관하게 그 사실을 보고해 드러났다.

계약 파일 중 가장 자주 고친 것이 가장 오래 무방비였다. 코디네이터가 `provenance.schema.json`
검증은 붙여 두고 **레지스트리 본체는 잊었다.**

## 무엇이 어디를 막는가 — 둘을 합쳐야 계약이 닫힌다

| | 막는 것 |
|---|---|
| `model_constants.registry.schema.json` | **형태** — 필수 필드 · 타입 · 패턴 · `additionalProperties: false` |
| 이 파일 | **교차 불변식** — JSON Schema 2020-12 로는 표현할 수 없는 것 |

JSON Schema 에는 다른 필드의 **값**을 참조하는 수단이 없다(`$data` 는 Ajv 확장이다).
그래서 「`value_type` 이 `valueTypeVocabulary` 에 선언된 것인가」 같은 검사는 여기서 한다.
그 검사가 바로 이번에 뚫렸던 구멍이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
REGISTRY_PATH = CONTRACTS / "model_constants.json"
SCHEMA_PATH = CONTRACTS / "model_constants.registry.schema.json"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return _load("model_constants.json")


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    """`seed_provenance` 의 `$ref` 를 풀기 위해 provenance 스키마를 등록해 둔다."""
    schema = _load("model_constants.registry.schema.json")
    provenance = _load("provenance.schema.json")
    Draft202012Validator.check_schema(schema)
    refs = Registry().with_resource(
        "provenance.schema.json", Resource.from_contents(provenance))
    return Draft202012Validator(schema, registry=refs)


# --- 스키마가 존재하고 실제로 걸려 있는가 -----------------------------------

def test_the_schema_the_registry_points_at_actually_exists():
    """★ 이 검사가 없어서 뚫렸다. `$schema` 가 가리키는 파일이 없어도 아무도 몰랐다."""
    declared = _load("model_constants.json")["$schema"]
    target = (CONTRACTS / declared).resolve()
    assert target.exists(), (
        f"레지스트리의 $schema 가 {declared} 를 가리키는데 파일이 없다. "
        "레지스트리가 무검증 상태다")
    assert target == SCHEMA_PATH.resolve()


def test_the_registry_validates_against_its_own_schema(registry, validator):
    errors = sorted(validator.iter_errors(registry), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors[:10]]


# --- 교차 불변식 — 스키마가 표현할 수 없는 것 -------------------------------

def test_every_value_type_is_declared_in_the_vocabulary(registry):
    """★ 이번에 뚫렸던 바로 그 구멍.

    새 `value_type` 을 어휘에 등록하지 않고 쓰면 그 타입이 무엇을 뜻하는지 아무 데도
    적히지 않는다. 단위 혼동이 예선의 80만/81만 사고의 원인이었다.
    """
    declared = set(registry["valueTypeVocabulary"])
    used = {e["value_type"] for e in registry["entries"]}
    assert used <= declared, f"어휘에 없는 value_type: {sorted(used - declared)}"


def test_the_vocabulary_has_no_dead_entries(registry):
    """쓰지 않는 어휘가 쌓이면 어느 것이 살아 있는지 알 수 없게 된다."""
    declared = set(registry["valueTypeVocabulary"])
    used = {e["value_type"] for e in registry["entries"]}
    assert not (declared - used), f"아무도 쓰지 않는 value_type: {sorted(declared - used)}"


def test_key_starts_with_its_engine(registry):
    """`key` 의 접두사가 `engine` 과 어긋나면 소유가 흐려진다."""
    bad = [e["key"] for e in registry["entries"]
           if not e["key"].startswith(e["engine"] + ".")]
    assert not bad, bad


def test_normative_constants_are_our_choice_and_nothing_else_is(registry):
    """SPEC 2.1 — `our_choice` 는 `normative` 전용. (d) 와 정확히 대응해야 한다.

    provenance 스키마가 `normative` ↔ `our_choice` 는 막지만, **`spec_class: d` 와
    `source_kind: normative` 가 어긋나는 것**은 레지스트리 층에서만 보인다.
    """
    for e in registry["entries"]:
        kind = e["seed_provenance"]["source_kind"]
        if e["spec_class"] == "d":
            assert kind == "normative", f"{e['key']}: (d) 인데 {kind}"
        else:
            assert kind != "normative", f"{e['key']}: ({e['spec_class']}) 인데 normative"


def test_pending_diligence_keeps_its_candidate_out_of_the_provenance(registry):
    """승인 전의 준거 후보를 계보에 적으면 심사에서 반박당한다 (Part 0-C).

    `store` 쪽 `test_seed.py` 가 같은 것을 저장소 층에서 본다. 여기서는 **계약 파일
    자체**가 그 규율을 어기지 않았는지를 본다 — 저장소를 안 거치는 소비자도 있다.
    """
    for e in registry["entries"]:
        if "pending_diligence" not in e:
            continue
        prov = e["seed_provenance"]
        assert prov["source_name"] is None, e["key"]
        assert prov["source_ref"] is None, e["key"]
        assert prov["observed_at"] is None, e["key"]


def test_keys_are_unique(registry):
    keys = [e["key"] for e in registry["entries"]]
    assert len(keys) == len(set(keys))


# --- 스키마가 실제로 막는가 (음성) ------------------------------------------

def _entry(registry: dict) -> dict:
    return json.loads(json.dumps(registry["entries"][0]))


@pytest.mark.parametrize(
    "mutate, why",
    [
        ({"key": "NoEngine"}, "engine 접두사 없는 키"),
        ({"key": "tco.CamelCase"}, "snake_case 아닌 키"),
        ({"spec_class": "e"}, "없는 분류"),
        ({"legacy_symbol": ""}, "빈 문자열로 메운 legacy_symbol"),
        ({"legacy_symbol": "lower_case"}, "대문자 아닌 심볼"),
        ({"frozen_current_value": None}, "값이 null — 시드할 것이 없다"),
        ({"spec_action": ""}, "빈 spec_action"),
        ({"code_ref": ""}, "빈 code_ref"),
        ({"확신도": "높음"}, "발명한 필드 (additionalProperties)"),
    ],
)
def test_schema_rejects_malformed_entries(registry, validator, mutate, why):
    doc = json.loads(json.dumps(registry))
    entry = _entry(registry)
    entry.update(mutate)
    doc["entries"] = [entry]
    assert list(validator.iter_errors(doc)), f"막았어야 한다: {why}"


def test_schema_rejects_a_missing_required_entry_field(registry, validator):
    for field in ("key", "engine", "spec_class", "value_type",
                  "frozen_current_value", "spec_action", "seed_provenance"):
        doc = json.loads(json.dumps(registry))
        entry = _entry(registry)
        del entry[field]
        doc["entries"] = [entry]
        assert list(validator.iter_errors(doc)), f"{field} 없이 통과했다"


def test_schema_rejects_an_invalid_seed_provenance(registry, validator):
    """`$ref` 가 실제로 걸려 있는지 — 안 걸리면 계보가 무검증으로 새어든다."""
    doc = json.loads(json.dumps(registry))
    entry = _entry(registry)
    entry["seed_provenance"] = {
        "source_kind": "statistic", "source_name": None, "source_ref": None,
        "observed_at": None, "fetched_at": None, "verification": "our_choice",
    }
    doc["entries"] = [entry]
    assert list(validator.iter_errors(doc)), (
        "our_choice 를 statistic 에 붙였는데 통과했다 — provenance $ref 가 안 걸려 있다")


def test_schema_rejects_an_empty_vocabulary_description(registry, validator):
    """어휘에 이름만 있고 뜻이 없으면 단위 혼동을 막지 못한다."""
    doc = json.loads(json.dumps(registry))
    doc["valueTypeVocabulary"] = {**doc["valueTypeVocabulary"], "ratio": ""}
    assert list(validator.iter_errors(doc))
