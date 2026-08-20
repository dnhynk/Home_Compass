"""교차 테스트 — 모델 상수 키의 출처 셋이 어긋나지 않는가 (코디네이터 소유).

Wave 2 컷오버로 값의 정본이 저장소로 옮겨졌다. 그 순간 키 목록의 출처가 셋이 된다.

| 출처 | 무엇을 말하는가 | 누가 읽는가 |
|---|---|---|
| `engines.required_constant_keys()` | **엔진이 실제로 조회하는 키** | 기동 시 전수 검증 |
| `contracts/model_constants.json` | 키 공간·단위·분류의 계약 | 시드(빌드 시점) · 테스트 |
| `store` 의 `ModelConstant` | **값의 정본** | 기동 시 주입 |

셋이 조용히 갈라지는 것이 이 구조의 지배적 실패 양상이다. 계약에 키를 추가했는데
시드를 안 돌렸다거나, 엔진이 새 키를 조회하는데 계약에 없다거나 — 어느 쪽도 런타임까지
가면 사용자의 주거비를 잘못 계산한다. 그래서 여기서 셋을 한자리에 놓고 본다.

**검증 대상 키 목록의 정본은 `required_constant_keys()` 다** (수요측). 근거는
`main.py` 의 주석에 적었다 — 계약 파일을 정본으로 삼으면 api 가 계약 파일을 다시
런타임에 읽게 되어 컷오버가 무의미해지고, 저장소를 정본으로 삼으면 "저장소에 있는
것이 곧 필요한 것"이 되어 fail-closed 가 항등식으로 무너진다.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

REGISTRY_PATH = REPO_ROOT / "contracts" / "model_constants.json"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry_keys() -> set[str]:
    return {entry["key"] for entry in _registry()["entries"]}


@pytest.fixture(scope="module")
def engine_registry_keys() -> set[str]:
    """레지스트리 항목 중 **판정 엔진이 소비하는** 키만.

    등재된 전체 키와 같지 않다. SPEC Part 0-E #4 가 (d) 성격의 운영 임계 —
    신선도 임계 · 7.3 SLA N일 · 4.5 강등 임계 — 를 `별도 설정 개념을 새로 만들지 않고
    ModelConstant + our_choice 로 등재`하라고 명시했고, 그것들은 **엔진이 조회하지 않는다.**
    둘을 등호로 묶으면 계약이 SPEC 보다 좁아져 그 등재 자체가 불가능해진다.
    구분의 정본은 계약 파일의 `engineConsumers` 다.
    """
    registry = _registry()
    engines = set(registry["engineConsumers"]["engines"])
    return {e["key"] for e in registry["entries"] if e["engine"] in engines}


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory) -> Path:
    from firsthome.store import create_store
    from firsthome.store.seed import seed_all

    path = tmp_path_factory.mktemp("key-sources") / "seeded.db"
    with create_store(f"sqlite://{path}") as store:
        seed_all(store, at=datetime(2026, 8, 13, tzinfo=timezone.utc))
    return path


def _mapping(db: Path) -> dict:
    from firsthome.store import create_store

    with create_store(f"sqlite://{db}") as store:
        return store.model_constants.as_mapping()


# --- 셋이 일치하는가 --------------------------------------------------------

def test_all_three_key_sources_agree(registry_keys, engine_registry_keys, seeded_db):
    from firsthome.engines import required_constant_keys

    required = set(required_constant_keys())
    stored = set(_mapping(seeded_db))

    # 등호는 **엔진 소비 키**에 건다. 여기가 계약 드리프트 탐지의 본체다 —
    # 엔진이 조회하는데 계약에 없거나, 계약에 엔진 키가 있는데 엔진이 안 읽으면 잡힌다.
    assert required == engine_registry_keys, (
        "엔진이 조회하는 키와 계약 파일의 엔진 소비 키가 다르다. "
        f"엔진에만: {sorted(required - engine_registry_keys)} / "
        f"계약에만: {sorted(engine_registry_keys - required)}")

    # 비엔진 항목은 엔진이 조회하면 안 된다. 이 방향을 안 걸면 engineConsumers 가
    # 분류만 하고 아무것도 강제하지 않는 장식이 된다.
    non_engine = registry_keys - engine_registry_keys
    assert not (required & non_engine), (
        "엔진이 비엔진 상수를 조회한다. 분류가 틀렸거나 엔진이 남의 상수를 읽는다: "
        f"{sorted(required & non_engine)}")
    assert stored == registry_keys, (
        "시드된 저장소와 계약 파일이 다르다. 시드 규칙(store/seed.py)이 계약을 그대로 "
        f"옮기지 않고 있다. 저장소에만: {sorted(stored - registry_keys)} / "
        f"계약에만: {sorted(registry_keys - stored)}")


# --- 어긋나는 경우를 고정한다 ------------------------------------------------

def test_boot_is_refused_when_the_store_lacks_a_key_the_contract_declares(seeded_db, tmp_path):
    """계약에는 있는데 저장소에 없는 경우 — 시드를 안 돌렸거나 행이 지워졌다.

    이것이 실제로 일어나는 방향이다. 기동이 거부되어야 한다 (SPEC 5.1.1 fail-closed).
    """
    from firsthome.main import load_model_constants
    from firsthome.store import create_store

    db = tmp_path / "short.db"
    shutil.copy(seeded_db, db)
    victim = "tco.discount_rate_pct"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("DELETE FROM model_constant WHERE key = ?", (victim,))
    conn.close()

    with create_store(f"sqlite://{db}") as store:
        with pytest.raises(RuntimeError) as caught:
            load_model_constants(store)
    assert victim in str(caught.value)


def test_boot_still_starts_when_the_store_has_a_key_nobody_needs(seeded_db, tmp_path):
    """저장소에만 있고 엔진이 안 쓰는 키 — 기동은 된다. **이것은 결함이 아니다.**

    fail-closed 가 막는 것은 **부재**이지 잉여가 아니다. 잉여 키로 기동을 막으면
    1-② 가 새 상수를 먼저 등재하고 엔진을 나중에 고치는 순서를 쓸 수 없게 된다.
    잉여는 계약↔엔진 검사(`test_engine_constants.test_required_keys_match_the_registry`)와
    위 `test_all_three_key_sources_agree` 가 잡는다 — 기동이 아니라 테스트의 일이다.
    """
    from firsthome.main import load_model_constants
    from firsthome.store import create_store
    from firsthome.store.models import ModelConstant, Provenance

    db = tmp_path / "extra.db"
    shutil.copy(seeded_db, db)
    with create_store(f"sqlite://{db}") as store:
        store.model_constants.put(ModelConstant(
            key="future.not_used_yet", engine="tco", legacy_symbol=None,
            spec_class="d", value_type="ratio", value=0.5,
            provenance=Provenance("normative", None, None, None, None, "our_choice"),
        ))
        mapping = load_model_constants(store)
    assert mapping["future.not_used_yet"] == 0.5


# --- 컷오버가 실제로 끝났는가 ------------------------------------------------

def test_the_boot_path_opens_no_file_under_contracts(seeded_db, monkeypatch):
    """★ 컷오버의 기계적 강제 — 기동이 `contracts/` 의 어떤 파일도 열지 않는다.

    계약 파일을 런타임에 읽는 경로가 하나라도 남으면 "값의 정본은 store 의
    ModelConstant" 라는 계약이 거짓이 된다 (SPEC 1.2 생성 방향 · contracts/README).

    **소스에서 파일명을 문자열로 찾는 방식은 쓰지 않는다.** 그 검사는 설명 주석이나
    계약 문서의 참조 문구까지 위반으로 잡는 오탐을 냈다 (실제로 그렇게 만들었다가
    이 파일에서 걸렸다). 읽는 것이 문제이므로 **읽기를 관측한다.**
    """
    import builtins

    from firsthome.main import boot_model_constants
    from firsthome.store import STORE_URL_ENV

    contracts_dir = (REPO_ROOT / "contracts").resolve()
    opened: list[str] = []

    def _record(path) -> None:
        try:
            resolved = Path(path).resolve()
        except (TypeError, ValueError, OSError):
            return
        if resolved.is_relative_to(contracts_dir):
            opened.append(str(resolved))

    real_open = builtins.open
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes

    def spy_open(file, *args, **kwargs):
        _record(file)
        return real_open(file, *args, **kwargs)

    def spy_read_text(self, *args, **kwargs):
        _record(self)
        return real_read_text(self, *args, **kwargs)

    def spy_read_bytes(self, *args, **kwargs):
        _record(self)
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read_text)
    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    monkeypatch.setenv(STORE_URL_ENV, f"sqlite://{seeded_db}")

    mapping = boot_model_constants()

    assert set(mapping) >= set(__import__(
        "firsthome.engines", fromlist=["x"]).required_constant_keys())
    assert not opened, (
        "기동이 contracts/ 의 파일을 읽었다. 상수의 정본은 저장소다 (SPEC 1.2): "
        + str(sorted(set(opened))))


def test_the_bootstrap_marker_is_gone():
    """`[BOOTSTRAP-1A]` 는 1-① 한정 임시 경로의 표식이었다. 남아 있으면 컷오버가 안 끝난 것이다."""
    remaining = [
        f"{path.relative_to(REPO_ROOT)}"
        for path in sorted(SRC.rglob("*.py"))
        if "BOOTSTRAP-1A" in path.read_text(encoding="utf-8")
    ]
    assert not remaining, f"[BOOTSTRAP-1A] 표식이 남아 있다: {remaining}"


def test_the_contract_file_is_still_what_the_seed_reads(registry_keys, seeded_db):
    """계약 파일이 쓸모없어진 것은 아니다 — **시드**가 읽는다. 그 경로는 살아 있어야 한다.

    컷오버 후 "계약 파일은 이제 아무도 안 읽는다"고 오해하면 다음 사람이 지운다.
    빌드 시점 소비자가 누구인지를 테스트가 남긴다.
    """
    from firsthome.store.seed import load_registry

    assert {entry["key"] for entry in load_registry()["entries"]} == registry_keys
    assert set(_mapping(seeded_db)) == registry_keys


def test_every_policy_id_in_a_priority_order_actually_exists(seeded_db):
    """우선순위 상수가 **존재하지 않는 정책 ID** 를 가리키지 않는가.

    `_loan_option` 은 `usable.get(policy_id)` 가 비면 조용히 건너뛴다. 그래서 정책이
    사라져도 우선순위 목록에 이름이 남아 있으면 **아무도 모른다** — 실제로 그 상태가
    생길 뻔했다. 낡은 것으로 확인된 `sme_youth_deposit` 를 폐기할 때 그 ID 가
    `engines.jeonse_loan_priority` 와 `engines.monthly_loan_priority` **양쪽에** 남아
    있었고, 어떤 테스트도 그것을 잡지 못했다.

    조용한 건너뛰기가 위험한 이유는 방향이다. 우선순위 앞자리가 죽은 ID 면 그 자리는
    비는 게 아니라 **다음 상품이 올라온다.** 화면에는 여전히 추천이 뜨고, 그 추천이
    설계된 순서가 아니라는 사실만 사라진다.
    """
    from firsthome.store import create_store

    with create_store(f"sqlite://{seeded_db}") as store:
        constants = store.model_constants.as_mapping()
        live = {v.payload["id"] for v in store.rule_versions.list()}

    dangling = {
        key: [pid for pid in constants[key] if pid not in live]
        for key in ("engines.jeonse_loan_priority", "engines.monthly_loan_priority")
    }
    dangling = {k: v for k, v in dangling.items() if v}
    assert not dangling, (
        "우선순위 상수가 존재하지 않는 정책을 가리킨다. 정책을 폐기했다면 우선순위에서도 "
        f"빼야 한다 (계약 변경이므로 코디네이터가 낸다): {dangling}"
    )
