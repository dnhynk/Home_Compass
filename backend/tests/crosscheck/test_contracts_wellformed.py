"""교차 테스트 — 계약 파일 자체의 정합성 (코디네이터 소유, SPEC 9.4).

이 파일이 깨지는 것은 곧 계약 경계 위반 신호다. 워커의 코드가 아니라
`contracts/` 의 원본이 스스로 모순되었는지를 본다.

지키는 것:
  1. 계약 파일이 파싱된다
  2. `provenance.schema.json` 이 유효한 JSON Schema 2020-12 이고, 자기 예제를 통과시킨다
  3. `model_constants.json` 의 모든 `seed_provenance` 가 그 스키마를 통과한다
     -> W-store 가 이 파일을 그대로 시드해도 잘못된 Provenance 가 저장소에 들어갈 수 없다
  4. SPEC 2.1 의 금지 규칙이 실제로 막히는지 (음성 케이스)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def provenance_schema() -> dict:
    return _load("provenance.schema.json")


@pytest.fixture(scope="module")
def validator(provenance_schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(provenance_schema)
    return Draft202012Validator(provenance_schema)


@pytest.fixture(scope="module")
def registry() -> dict:
    return _load("model_constants.json")


def test_provenance_schema_accepts_its_own_examples(provenance_schema, validator):
    for example in provenance_schema["examples"]:
        validator.validate(example)


def test_every_seed_provenance_is_valid(registry, validator):
    for entry in registry["entries"]:
        errors = sorted(validator.iter_errors(entry["seed_provenance"]), key=str)
        assert not errors, f"{entry['key']}: {[e.message for e in errors]}"


def test_registry_keys_are_unique(registry):
    keys = [e["key"] for e in registry["entries"]]
    assert len(keys) == len(set(keys))


ENGINES_DIR = Path(__file__).resolve().parents[2] / "src" / "home_compass" / "engines"

# 판정 결과를 바꾸지 않는 구조/열거 상수는 SPEC 5.1.2 의 비대상이다.
NOT_MODEL_PARAMETERS = {
    "BANDS", "VERDICTS", "IMPACTS", "STATUSES",  # 열거형 라벨
    "HORIZON_MONTHS",                            # HORIZON_YEARS 의 파생값
    "DATA_DIR",                                  # 파일시스템 경로 = 구조 상수. 0단계에 store 로 사라진다
}

# 아직 외부화되지 않은 키. 인라인 리터럴이라 legacy_symbol 이 없고 constants[...] 참조도 없다.
#
# 이 목록은 **스스로 지워지게** 설계했다. W-engines 가 어떤 키를 외부화하면
# test_pending_list_shrinks_when_externalization_lands 가 즉시 빨간불이 되어
# 코디네이터에게 목록 축소를 강제한다. 잊고 방치하는 경로가 없다.
# SPEC 5.1.2 의 허용목록과 같은 규율이다 — 목록이 줄지 않는 것이 곧 신호다.
# 2026-08-13 · 비었다. 1-①(PR #8)이 41키 전수를 외부화했고, 레지스트리 67키 모두
# engines/ 에서 constants['<key>'] 로 참조된다. 장치는 설계대로 작동했다 —
# 목록에 남아 있던 키가 외부화되자 test_pending_list_shrinks_when_externalization_lands
# 가 41건 전수에서 빨간불이 났고, 그것이 이 목록을 비우게 만들었다.
#
# 앞으로 새 인라인 리터럴을 레지스트리에 등재하되 아직 외부화하지 못했다면 여기에 키를
# 적고 그 줄에 근거를 남긴다. 외부화가 끝나면 위 테스트가 다시 빨간불로 알려 준다.
PENDING_EXTERNALIZATION: frozenset[str] = frozenset()

# 비엔진 소비자(SPEC Part 0-E #4)의 키 중 **아직 그 소비자 코드가 없는** 것.
# 위 PENDING_EXTERNALIZATION 과 같은 자기소거 장치이며, 목적만 다르다 —
# 저쪽은 「리터럴이 아직 안 걷혔다」, 이쪽은 「소비자가 아직 안 지어졌다」다.
# 계약이 코드보다 먼저 서야 하는 경우가 있기 때문에 필요하다: 추출 파이프라인은
# constants[...] 를 fail-closed 로 조회하므로(5.1.1) 키가 저장소에 먼저 시드돼야
# 착수할 수 있다. 소비자가 키를 참조하는 순간 아래 shrink 테스트가 빨간불을 켠다.
PENDING_CONSUMER_WIRING: frozenset[str] = frozenset()


def _module_level_symbols() -> set[str]:
    found: set[str] = set()
    for path in sorted(ENGINES_DIR.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line[:1].isupper() and "=" in line and not line.lstrip().startswith("#"):
                symbol = line.split("=", 1)[0].strip()
                if symbol.isupper() and symbol.replace("_", "").isalnum():
                    found.add(symbol)
    return found


def _engines_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(ENGINES_DIR.glob("*.py")))


def _non_engine_source() -> str:
    """`engines/` **밖의** 백엔드 소스 전부.

    비엔진 상수의 소비자는 엔진이 아니므로 `engines/` 만 뒤지면 항상 죽은 키로 보인다.
    소비자별 디렉터리 대응표를 계약에 새로 만들지는 않는다 — 그 표 자체가 또 하나의
    드리프트 대상이 된다. 죽은 키를 잡는다는 목적에는 이 범위로 충분하다.
    """
    root = ENGINES_DIR.parent
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.py"))
        if ENGINES_DIR not in p.parents
    )


def _engine_keys(registry: dict) -> set[str]:
    consumers = set(registry["engineConsumers"]["engines"])
    return {e["key"] for e in registry["entries"] if e["engine"] in consumers}


def _is_referenced(key: str, source: str) -> bool:
    """constants['<key>'] 참조가 engines/ 에 있는가 (SPEC 5.1.1 주입 경로)."""
    return f'"{key}"' in source or f"'{key}'" in source


def test_no_module_level_engine_constant_is_unregistered():
    """코드에 있는데 레지스트리에 없는 모델 파라미터를 잡는다.

    이 방향은 1-① 전후로 의미가 변하지 않는다. 외부화가 끝나면 모듈 전역이 비므로
    자연히 공집합이 되고, 누가 새 전역 상수를 추가하면 다시 잡힌다.
    """
    declared = {e["legacy_symbol"] for e in _load("model_constants.json")["entries"]}
    missing = _module_level_symbols() - declared - NOT_MODEL_PARAMETERS
    assert not missing, f"레지스트리에 없는 엔진 상수: {sorted(missing)}"


def test_every_registry_key_is_live_somewhere(registry):
    """등재만 되고 아무도 쓰지 않는 죽은 키를 잡는다.

    각 키는 둘 중 한 형태로 살아 있어야 한다 — 전이 전·중·후 모두에서 성립한다.
      (a) legacy_symbol 이 engines/ 모듈 전역에 남아 있다     <- 외부화 전
      (b) constants['<key>'] 참조가 engines/ 에 등장한다       <- 외부화 후 (SPEC 5.1.1)
    아직 외부화되지 않은 인라인 리터럴은 PENDING_EXTERNALIZATION 이 면제한다.
    """
    globals_ = _module_level_symbols()
    source = _engines_source()
    engine_keys = _engine_keys(registry)
    dead = [
        e["key"] for e in registry["entries"]
        if e["key"] in engine_keys
        and e["key"] not in PENDING_EXTERNALIZATION
        and e["legacy_symbol"] not in globals_
        and not _is_referenced(e["key"], source)
    ]
    assert not dead, f"등재됐지만 코드 어디서도 살아 있지 않은 키: {sorted(dead)}"


def test_every_non_engine_registry_key_is_live_somewhere(registry):
    """비엔진 소비자의 키도 죽은 채 남지 않는다 (SPEC Part 0-E #4).

    엔진 키와 **같은 목적, 다른 탐색 범위**다. 이 절반을 두지 않으면 비엔진으로
    분류하는 것만으로 죽은 키 검사를 영원히 피해 갈 수 있게 되고, 그러면
    `engineConsumers` 가 분류가 아니라 도피처가 된다.
    """
    source = _non_engine_source()
    engine_keys = _engine_keys(registry)
    dead = [
        e["key"] for e in registry["entries"]
        if e["key"] not in engine_keys
        and e["key"] not in PENDING_CONSUMER_WIRING
        and not _is_referenced(e["key"], source)
    ]
    assert not dead, f"비엔진 소비자에 등재됐지만 코드 어디서도 살아 있지 않은 키: {sorted(dead)}"


def test_pending_consumer_list_shrinks_when_the_consumer_lands(registry):
    """소비자가 배선되면 PENDING_CONSUMER_WIRING 이 스스로 줄게 만든다."""
    source = _non_engine_source()
    already_live = sorted(k for k in PENDING_CONSUMER_WIRING if _is_referenced(k, source))
    assert not already_live, (
        "소비자가 배선된 키가 PENDING_CONSUMER_WIRING 에 남아 있다. 목록에서 지워라: "
        f"{already_live}")


def test_pending_consumer_keys_all_exist_in_registry(registry):
    keys = {e["key"] for e in registry["entries"]}
    assert PENDING_CONSUMER_WIRING <= keys, sorted(PENDING_CONSUMER_WIRING - keys)


def test_pending_list_shrinks_when_externalization_lands(registry):
    """PENDING 목록이 스스로 지워지게 만드는 장치.

    W-engines 가 어떤 키를 외부화하면 그 키는 더 이상 pending 이 아니므로 여기서
    빨간불이 나고, 코디네이터가 목록을 줄이게 된다. 방치 경로를 없앤다.
    """
    globals_ = _module_level_symbols()
    source = _engines_source()
    already_live = sorted(
        key for key in PENDING_EXTERNALIZATION
        if _is_referenced(key, source)
        or any(e["legacy_symbol"] in globals_
               for e in registry["entries"] if e["key"] == key and e["legacy_symbol"])
    )
    assert not already_live, (
        "외부화가 끝난 키가 PENDING_EXTERNALIZATION 에 남아 있다. 목록에서 지워라: "
        f"{already_live}")


def test_pending_keys_all_exist_in_registry(registry):
    keys = {e["key"] for e in registry["entries"]}
    assert PENDING_EXTERNALIZATION <= keys, sorted(PENDING_EXTERNALIZATION - keys)


@pytest.mark.parametrize(
    "bad, why",
    [
        (
            {
                "source_kind": "statistic",
                "source_name": "가계동향조사",
                "source_ref": "KOSIS-XXX",
                "observed_at": None,
                "fetched_at": None,
                "verification": "verified",
            },
            "verified 인데 observed_at 이 없다 (SPEC 2.1 기준시점 필수)",
        ),
        (
            {
                "source_kind": "statistic",
                "source_name": None,
                "source_ref": None,
                "observed_at": None,
                "fetched_at": None,
                "verification": "our_choice",
            },
            "our_choice 는 normative 전용이다 (SPEC 2.1)",
        ),
        (
            {
                "source_kind": "normative",
                "source_name": None,
                "source_ref": None,
                "observed_at": None,
                "fetched_at": None,
                "verification": "unverified",
            },
            "normative 의 verification 은 항상 our_choice 여야 한다",
        ),
        (
            {
                "source_kind": "market",
                "source_name": "한국은행",
                "source_ref": "KOFR",
                "observed_at": "2026-08-13T00:00:00Z",
                "fetched_at": None,
                "verification": "verified",
            },
            "Z 표기는 금지 — UTC 로 뭉개지 않는다 (SPEC 2.1)",
        ),
        (
            {
                "source_kind": "normative",
                "source_name": None,
                "source_ref": None,
                "observed_at": None,
                "fetched_at": None,
                "verification": "our_choice",
                "confidence": 0.9,
            },
            "additionalProperties: false",
        ),
    ],
)
def test_schema_rejects_forbidden_shapes(validator, bad, why):
    assert list(validator.iter_errors(bad)), f"막았어야 한다: {why}"


# --- observed_at_unstated (코디네이터 결정, 실사 6.3) -------------------------
#
# 원문을 확인했는데 그 원문이 기준시점을 밝히지 않은 행이 실사에서 7건 나왔다.
# 이 통로가 너무 넓으면 "날짜를 못 찾았으니 unstated 로 하자"가 되어 계보가 무너진다.
# 그래서 열리는 조건과 닫히는 조건을 양쪽에서 고정한다.

_UNSTATED_OK = {
    "source_kind": "statute",
    "source_name": "주택도시보증공사 전세보증금반환보증 보증료율표",
    "source_ref": "https://www.khug.or.kr/hug/web/ig/dr/igdr000001.jsp",
    "observed_at": None,
    "fetched_at": "2026-08-13T00:00:00+09:00",
    "verification": "verified",
    "observed_at_unstated": True,
}


def test_unstated_observed_at_allows_verified(validator):
    """원문확인했으나 원문에 기준시점이 없는 행이 verified 로 살아남는다."""
    assert not list(validator.iter_errors(_UNSTATED_OK))


@pytest.mark.parametrize(
    "mutate, why",
    [
        ({"observed_at": "2026-01-01T00:00:00+09:00"},
         "observed_at 이 있는데 unstated 를 붙였다 — 둘은 배타적이다"),
        ({"source_kind": "normative", "verification": "our_choice"},
         "normative 에는 관측 기준시점 개념이 없어 '원문이 밝히지 않았다'가 성립하지 않는다"),
        ({"verification": "unverified"},
         "unverified 는 값을 확인하지 못한 것이다. unstated 를 붙일 자리가 아니다"),
        ({"source_ref": None},
         "원문을 확인했다면서 출처 참조가 없다"),
        ({"source_name": None},
         "원문을 확인했다면서 출처기관이 없다"),
        ({"observed_at_unstated": False},
         "const: true — 끄려면 필드를 빼야 한다. false 를 허용하면 두 표현이 공존한다"),
    ],
)
def test_unstated_observed_at_is_narrow(validator, mutate, why):
    bad = {**_UNSTATED_OK, **mutate}
    assert list(validator.iter_errors(bad)), f"막았어야 한다: {why}"
