"""SPEC 5.1 상수 외부화의 집행 지점 — 리터럴 검사 · 주입 형식 · fail-closed.

여기서 고정하는 것은 넷이다.

1. `engines/` 하위에 **판정 숫자를 바꾸는 리터럴이 남아 있지 않다** (5.1.2).
   AST 로 전수를 훑고, 아래 허용 목록에 없으면 실패시킨다.
   **허용 목록의 각 줄에는 근거가 붙어 있다. 목록이 커지는 것이 곧 규율이 무너지는 신호다.**
2. 엔진 함수는 상수 매핑을 **명시적 인자로 받는다** (5.1.1). 빼먹으면 TypeError 다.
3. **조회 실패 시 기본값을 쓰지 않는다** (5.1.1 fail-closed). 상수 하나가 빠지면 기동이
   거부되고, 기동을 건너뛰더라도 엔진이 그 자리에서 KeyError 로 터진다.
4. `required_constant_keys()` 가 실제 조회 지점 · 레지스트리와 **셋 다 일치**한다.
   선언만 있고 안 쓰는 키, 쓰는데 선언 안 된 키를 둘 다 잡는다.

── 이 검사가 잡지 못하는 것 (알고 남긴 구멍) ─────────────────────────────
값이 허용 목록의 항등값과 우연히 같은 모델 파라미터는 AST 상 구분할 수 없다.
실례가 있다 — `eligibility.age_cap_imminent_years` 는 값이 `1` 이라 인덱스·항등원 `1` 과
같아 보인다. 만약 이 상수가 외부화되지 않은 채 인라인으로 남아 있었다면 리터럴 검사는
그것을 통과시켰을 것이다. 그래서 이 값을 실제로 막는 것은 리터럴 검사가 아니라
**레지스트리 등재 + `test_required_keys_match_the_registry`** 다.
검사가 만능이라고 적어 두면 그 자체가 거짓말이므로 여기 남긴다.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from firsthome.engines import analyze, required_constant_keys  # noqa: E402
from firsthome.engines.affordability import assess_affordability  # noqa: E402
from firsthome.engines.eligibility import evaluate_policies  # noqa: E402
from firsthome.engines.risk import scan_deposit_risk  # noqa: E402
from firsthome.engines.tco import build_scenarios  # noqa: E402
from firsthome.main import load_model_constants  # noqa: E402
from firsthome.store import create_store, store_from_env  # noqa: E402
from firsthome.store.seed import seed_model_constants  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed, load_registry  # noqa: E402
from snapshot_util import dumps, load_profiles, split_snapshot  # noqa: E402

ENGINES_DIR = Path(__file__).resolve().parents[1] / "src" / "firsthome" / "engines"

# SPEC 2.3 컷오버 — 지역·정책도 주입받는다. 여기서 흔드는 축은 **상수 하나**이므로
# 이 둘은 고정한다 (`decision_inputs.py`).
REGIONS = store_regions()
POLICIES = store_policies(FROZEN_NOW)

BASE_PROFILE = {
    "age": 28,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 3_000_000,
    "liquidAssetsKRW": 40_000_000,
    "existingDebtMonthlyKRW": 300_000,
    "householdSize": 1,
    "regionCode": "11440",
    "isHomeless": True,
    "isNewlywed": False,
    "isSMEEmployee": True,
    "preferredType": "any",
}


# ==========================================================================
# 허용 목록 (SPEC 5.1.2 비대상). 키는 repr(value) — 0 과 0.0 을 섞지 않기 위해서다.
# ==========================================================================

ALWAYS_ALLOWED = {
    "0": "항등원·하한·인덱스 0. 판정 숫자를 만들지 않는다 (5.1.2 '0·1·100 같은 항등').",
    "1": "항등원·인덱스 1·최소 가구원수 하한·round() 자릿수. 위와 같은 근거.",
    "0.0": "float 항등원. 비율·금리의 '없음' 표현.",
    "1.0": "float 항등원. 배수 1배 = 가중치 미적용.",
    "100": "백분율 환산 (5.1.2 '백분율 환산' 명시 비대상).",
    "100.0": "위와 같음 (float 형). 참/거짓을 0~100 척도에 얹는 표시값이지 선택된 수준이 아니다 — "
             "임의 수준인 risk.market_value_pct_* 와 달리 '가입 가능=전부'의 항등 표현이다.",
    "12": "연->월 환산 (5.1.2 '연→월 환산의 12' 명시 비대상).",
}

ALLOWED_BY_MODULE = {
    "__init__.py": {
        "2": "튜플 정렬키 앞 2개 비교 · 요약문에 실을 정책 2건 슬라이스. 표시·정렬용이며 금액을 만들지 않는다.",
    },
    "eligibility.py": {
        "2": "status 정렬 순위(ineligible=2) · 요약문 2건 슬라이스. 판정이 아니라 나열 순서다.",
        "3": "정렬 순위의 미지 status 폴백. 알 수 없는 상태를 맨 뒤로 보낼 뿐 판정을 바꾸지 않는다.",
    },
    "tco.py": {
        "2": "pct()/round() 의 소수 자릿수. 반올림 규칙은 계약 파일 소관이다 (5.1.2 비대상).",
        "3": "보증료율 표시의 소수 자릿수. HUG 요율표의 칸은 0.097~0.211 이라 2자리로 적으면 "
             "0.20% 처럼 뭉개져 어느 칸인지 사라진다 (F-3). 표시 자릿수이지 요율 자체가 아니다.",
    },
}

# ── 임시 등재 (현재 비어 있음) ────────────────────────────────────────────
# 레지스트리 v1.1.0 (PR #5) 이 인라인 가중치·구간 경계 41키를 등재했고, 이 PR 이 전수를
# 외부화했다. 그래서 이 표는 **비어 있다.** 항목이 다시 생긴다면 그것은 "등재되지 않은
# 모델 파라미터가 코드에 들어왔다" 는 뜻이며, 비어 있는 상태가 정상이다.
PENDING_REGISTRATION: dict[str, dict[str, str]] = {}


def _literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            yield node.lineno, node.value


def test_no_model_parameter_literals_in_engines():
    """SPEC 5.1.2 — engines/ 의 숫자 리터럴은 허용 목록에 있는 것뿐이어야 한다."""
    offenders = []
    for path in sorted(ENGINES_DIR.glob("*.py")):
        allowed = dict(ALLOWED_BY_MODULE.get(path.name, {}))
        allowed.update(PENDING_REGISTRATION.get(path.name, {}))
        for lineno, value in _literals(path):
            key = repr(value)
            if key in ALWAYS_ALLOWED or key in allowed:
                continue
            offenders.append(f"{path.name}:{lineno} -> {key}")
    assert not offenders, (
        "허용 목록에 없는 숫자 리터럴이 engines/ 에 있다 (SPEC 5.1.2).\n"
        "상수라면 레지스트리에 등재해 주입받고, 비대상이라면 허용 목록에 **근거와 함께** 추가하라.\n"
        + "\n".join(offenders)
    )


def test_allow_list_has_a_reason_on_every_line():
    """근거 없는 허용은 허용이 아니다 (SPEC 5.1.2 '그 줄에 근거를 적는다')."""
    tables = [("ALWAYS_ALLOWED", ALWAYS_ALLOWED)]
    tables += [(f"ALLOWED_BY_MODULE[{k}]", v) for k, v in ALLOWED_BY_MODULE.items()]
    tables += [(f"PENDING_REGISTRATION[{k}]", v) for k, v in PENDING_REGISTRATION.items()]
    for name, table in tables:
        for value, reason in table.items():
            assert isinstance(reason, str) and len(reason.strip()) >= 10, f"{name}[{value}]"


def test_allow_list_has_no_dead_entries():
    """코드에 없는 값을 허용 목록이 붙들고 있으면 목록만 자란다."""
    per_module = {}
    for path in sorted(ENGINES_DIR.glob("*.py")):
        per_module[path.name] = {repr(v) for _, v in _literals(path)}
    everywhere = set().union(*per_module.values()) if per_module else set()

    dead_global = [k for k in ALWAYS_ALLOWED if k not in everywhere]
    assert not dead_global, f"ALWAYS_ALLOWED 에 죽은 항목: {dead_global}"

    for table_name, table in (("ALLOWED_BY_MODULE", ALLOWED_BY_MODULE),
                              ("PENDING_REGISTRATION", PENDING_REGISTRATION)):
        for module, entries in table.items():
            dead = [k for k in entries if k not in per_module.get(module, set())]
            assert not dead, f"{table_name}[{module}] 에 죽은 항목: {dead}"


# ==========================================================================
# 주입 형식 (SPEC 5.1.1)
# ==========================================================================

ENTRY_POINTS = (
    (assess_affordability, {"monthly_net_income_krw": 3_000_000}),
    (evaluate_policies, {"profile": BASE_PROFILE, "policies": []}),
    (
        scan_deposit_risk,
        {
            "deposit_krw": 100_000_000,
            "jeonse_ratio_pct": 70.0,
            "guarantee_deposit_cap_krw": 700_000_000,
        },
    ),
    (analyze, {"profile": BASE_PROFILE}),
)


@pytest.mark.parametrize("func, kwargs", ENTRY_POINTS, ids=lambda x: getattr(x, "__name__", ""))
def test_entry_point_requires_the_constants_mapping(func, kwargs):
    """상수 매핑을 빼먹으면 조용히 기본값을 쓰는 게 아니라 호출 자체가 실패한다."""
    with pytest.raises(TypeError):
        func(**kwargs)


def test_build_scenarios_requires_the_constants_mapping():
    constants = frozen_seed()
    affordability = assess_affordability(monthly_net_income_krw=3_000_000, constants=constants)
    with pytest.raises(TypeError):
        build_scenarios(
            region={},
            profile=BASE_PROFILE,
            affordability=affordability,
            guarantee_deposit_cap_krw=700_000_000,
        )


@pytest.mark.parametrize("missing", sorted(required_constant_keys()))
def test_a_missing_constant_never_falls_back_to_a_default(missing):
    """상수 하나를 지우면 판정이 **거부되거나, 애초에 그 가지를 밟지 않았거나** 둘 중 하나다.

    조회는 가지 안에서 일어난다 — 예컨대 `risk.deposit_size_weight_3` 은 보증금이 한도의
    90% 를 넘는 사례에서만 읽힌다. 그래서 "모든 키에서 KeyError 가 난다" 는 성립할 수 없고,
    그걸 통과시키려 조회를 함수 머리로 끌어올리는 것은 검사를 위해 코드를 비트는 짓이다.

    대신 **기본값이 끼어들 자리가 없음**을 본다. 키를 지웠을 때 가능한 결과는 둘뿐이다.
      · KeyError — 그 가지를 밟았고, 기본값 없이 터졌다
      · 결과가 바이트 단위로 동일 — 그 가지를 밟지 않았다
    셋째(터지지도 않았는데 결과가 달라짐)가 나오면 어딘가에서 기본값이 값을 만든 것이다.

    전 키에 대한 존재 검증은 이것과 별개로 **기동 시** 수행된다
    (`test_boot_is_refused_when_any_constant_is_missing`, SPEC 5.1.1 · Part 0-E #2).
    """
    intact = frozen_seed()
    crippled = frozen_seed()
    del crippled[missing]

    for case in load_profiles():
        profile = case["profile"]
        try:
            baseline = analyze(profile, constants=intact, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
        except ValueError:
            continue
        try:
            actual = analyze(profile, constants=crippled, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
        except KeyError as exc:
            assert missing in str(exc)
            return
        assert dumps(split_snapshot(actual)[0]) == dumps(split_snapshot(baseline)[0]), (
            f"'{missing}' 없이도 판정이 나왔고 값까지 달라졌다 — 기본값이 끼어들었다는 뜻이다. "
            f"사례: {case['id']}"
        )


@pytest.fixture(scope="module")
def seeded_template_db(tmp_path_factory) -> Path:
    """상수 전수가 시드된 SQLite 파일 하나. 케이스마다 복사해서 한 행씩 지운다.

    67 케이스가 각자 시드하면 4,489건을 다시 넣는다. 파일 복사가 같은 상태를 훨씬
    싸게 만든다 — 그리고 케이스끼리 같은 저장소를 공유하지 않는다.
    """
    path = tmp_path_factory.mktemp("boot-template") / "seeded.db"
    with create_store(f"sqlite://{path}") as store:
        seed_model_constants(store)
    return path


@pytest.mark.parametrize("missing", sorted(required_constant_keys()))
def test_boot_is_refused_when_any_constant_is_missing(missing, tmp_path, seeded_template_db):
    """상수 하나를 지우면 기동이 거부된다 (SPEC 10.2 1-① 완료 기준 · Part 0-E #2).

    기동 검증 자체는 api 소유지만, **무엇을 검증해야 하는지**를 정하는 것은 engines 다
    (`required_constant_keys()`). 그 둘이 맞물리는 지점을 여기서 고정한다.

    Wave 2 컷오버 후 값의 정본은 저장소이므로, 계약 파일 임시본이 아니라 **저장소의
    상수 행**을 지운다. 런타임에 실제로 일어나는 사고에 그쪽이 가깝다 —
    계약 파일은 기동 경로가 더 이상 읽지 않는다.
    """
    db = tmp_path / "boot.db"
    shutil.copy(seeded_template_db, db)

    # 인터페이스에 delete 가 없다 (그것이 저장소 계층의 보장이다). 사고를 흉내 내려면
    # DB 를 직접 열어 지우는 수밖에 없고, 그것이 곧 이 검사가 상정하는 사고다.
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("DELETE FROM model_constant WHERE key = ?", (missing,))
    conn.close()

    url = f"sqlite://{db}"
    # 격리 — 이 케이스가 세션 저장소(conftest)를 건드리지 않았음을 URL 로 못 박는다.
    assert url != os.environ.get("FIRSTHOME_STORE_URL")

    with create_store(url) as store:
        with pytest.raises(RuntimeError) as caught:
            load_model_constants(store)
    assert missing in str(caught.value)

    # 지운 것은 사본뿐이다. 세션 저장소는 전수를 그대로 갖고 있어야 한다.
    with store_from_env() as session_store:
        assert missing in session_store.model_constants.as_mapping()


def test_boot_loader_and_test_seed_agree():
    """테스트가 만드는 매핑과 기동이 만드는 매핑이 같아야 한다.

    다르면 테스트는 실제로 도는 것과 다른 물건을 검증하게 된다. 컷오버 후 기동 쪽 변은
    저장소에서 오므로, 이 등식은 SQLite 왕복(JSON 은 int 키도 tuple 도 모른다)까지
    함께 붙든다.
    """
    with store_from_env() as store:
        assert load_model_constants(store) == frozen_seed()


# ==========================================================================
# 매니페스트 정합성
# ==========================================================================

def _looked_up_keys() -> set[str]:
    """engines/ 에서 실제로 `constants["..."]` 로 조회하는 키를 AST 로 걷는다."""
    found: set[str] = set()
    for path in sorted(ENGINES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            if not (isinstance(node.value, ast.Name) and node.value.id == "constants"):
                continue
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                found.add(index.value)
    return found


def test_required_keys_match_the_actual_lookup_sites():
    assert set(required_constant_keys()) == _looked_up_keys()


def test_required_keys_match_the_registry():
    """레지스트리의 **엔진 소비 키** 전수가 주입되고 소비된다 (10.2 1-① '상수 전수가 등재').

    전체 키가 아니라 엔진 소비 키인 이유는 SPEC Part 0-E #4 다 — (d) 성격의 운영 임계
    (신선도 임계 · 7.3 SLA N일 · 4.5 강등 임계 등)를 `별도 설정 개념을 새로 만들지 않고`
    ModelConstant 로 등재하라고 했고, 그것들은 엔진이 조회하지 않는다. 전체와 등호로 묶으면
    계약이 SPEC 보다 좁아진다. 구분의 정본은 계약 파일의 `engineConsumers` 다.
    """
    registry = load_registry()
    consumers = set(registry["engineConsumers"]["engines"])
    engine_keys = {e["key"] for e in registry["entries"] if e["engine"] in consumers}
    assert set(required_constant_keys()) == engine_keys


def test_engines_never_use_get_with_a_default_for_constants():
    """`constants.get(key, 기본값)` 금지 (injectionContract.lookupRule)."""
    offenders = []
    for path in sorted(ENGINES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get":
                continue
            if isinstance(func.value, ast.Name) and func.value.id == "constants":
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"constants.get() 은 금지다 (fail-closed): {offenders}"


def test_engines_do_not_import_store_or_llm():
    """SPEC 1.2 — 매핑은 호출자가 주입한다. engines 는 아무것도 끌어오지 않는다."""
    offenders = []
    for path in sorted(ENGINES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if any(part in ("store", "llm") for part in name.split(".")):
                    offenders.append(f"{path.name}:{node.lineno} -> {name}")
    assert not offenders, offenders
