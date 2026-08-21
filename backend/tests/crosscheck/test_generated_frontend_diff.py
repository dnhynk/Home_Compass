"""교차 테스트 — 프론트 생성물 diff (SPEC 9.2 #11 · D-11 · 1.2, 코디네이터 소유).

`test_generated_contracts_diff.py` 가 `api ──→ contracts/openapi.json` 을 붙드는
것과 **같은 자리·같은 기법**이다. 여기서 붙드는 것은 SPEC 1.2 생성 방향의 나머지 두 줄이다.

    store ──(승인된 RuleVersion · ModelConstant)──→ frontend/generated/*.js
    contracts/openapi.json ──(x- 확장)───────────→ frontend/generated/contract_constants.js

D-11 이 요구한 것은 「유지하되 손으로 쓰지 않는다」이므로, 손으로 고치면 여기가 깨져야 한다.
정규화하지 않고 **바이트 비교**하는 이유는 openapi 쪽과 같다 — 비교 전에 문자열을 주무르기
시작하면 무엇이든 통과시킬 수 있다.

## 이 파일이 추가로 붙드는 것

- **침묵 폴백 금지** (D-11). 생성물이 비어 있거나 기본값을 담으면 소비자는 「값이 없다」를
  알아채지 못한다. 그래서 빈 생성물을 실패로 고정한다.
- **필드 집합의 일치**. 생성된 정책 규칙의 `criteria` 가 `eligibility.py` 가 실제로 읽는
  키와 다르면 백엔드 판정과 프론트 판정이 갈라진다 (Part 0-A 의 실패 유형).
- **확정값의 유일한 거처** (SPEC 8.3 #3 · #4). 타임아웃·재시도는 계약 파일의 `x-` 확장에만
  존재해야 하므로, 생성물의 값이 커밋된 `contracts/openapi.json` 과 같은지 본다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src"
SCRIPTS = REPO_ROOT / "scripts"
GENERATED = REPO_ROOT / "frontend" / "generated"
OPENAPI = REPO_ROOT / "contracts" / "openapi.json"
GENERATOR = SCRIPTS / "gen_contracts.py"
ELIGIBILITY = SRC / "home_compass" / "engines" / "eligibility.py"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

#: **이 표가 계약이다.** 생성기의 레지스트리를 읽어 오지 않는다 — 그러면 생성기가 무엇을
#: 내든 통과하는 항등식이 된다. 6단계 `web` 워커가 `<script src>` 로 거는 이름과
#: `window` 전역 이름이 여기 박혀 있고, 바뀌면 이 파일이 먼저 깨진다.
ARTIFACTS = {
    "web-model-constants": ("model_constants.js", "HOME_COMPASS_MODEL_CONSTANTS"),
    "web-policy-rules": ("policy_rules.js", "HOME_COMPASS_POLICY_RULES"),
    "web-regions": ("regions.js", "HOME_COMPASS_REGIONS"),
    "web-contract-constants": ("contract_constants.js", "HOME_COMPASS_CONTRACT_CONSTANTS"),
}

_MODULE_RE = re.compile(r"\Awindow\.(?P<name>[A-Z0-9_]+) = (?P<payload>\{.*\});\n\Z", re.DOTALL)


def artifact_path(name: str) -> Path:
    return GENERATED / ARTIFACTS[name][0]


def split_module(text: str) -> tuple[str, str, dict]:
    """`머리말 주석` + `window.<전역> = <JSON>;` 로 갈라 본다.

    빌드툴 없이 `<script>` 하나로 읽히는 평문 JS 여야 한다 (SPEC 6.2 오프라인 정의 #1).
    이 파서가 통과한다는 것이 곧 그 형태라는 뜻이다.
    """
    marker = "*/\n"
    assert marker in text, "머리말 주석이 없다"
    cut = text.index(marker) + len(marker)
    head, body = text[:cut], text[cut:]
    match = _MODULE_RE.match(body)
    assert match is not None, f"평문 JS 전역 대입 형태가 아니다: {body[:120]!r}"
    return head, match["name"], json.loads(match["payload"])


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    """생성기가 **지금** 만들어 내는 것. 저장소는 세션 임시본이다 (conftest 가 시드한다)."""
    import gen_contracts
    from home_compass.store import store_from_env

    with store_from_env() as store:
        return gen_contracts.render_all(store)


@pytest.fixture(scope="module")
def committed() -> dict[str, bytes]:
    return {name: artifact_path(name).read_bytes() for name in ARTIFACTS}


@pytest.fixture(scope="module")
def payloads(committed: dict[str, bytes]) -> dict[str, dict]:
    return {
        name: split_module(raw.decode("utf-8"))[2]
        for name, raw in committed.items()
    }


# --- 생성물이 있는가 --------------------------------------------------------

@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_the_generated_artifact_is_committed(name: str):
    assert artifact_path(name).is_file(), (
        f"{artifact_path(name)} 가 없다. `python scripts/gen_contracts.py` 로 생성해 커밋한다 (D-11)")


def test_the_generated_directory_holds_nothing_but_generated_artifacts():
    """손으로 쓴 파일이 생성물 디렉터리에 섞이면 재생성이 그것을 지키지 못한다.

    SPEC 9.4 의 `web` 소유는 「생성물 디렉터리 제외」이므로 이 디렉터리에 사람이 쓴
    파일이 있다는 것 자체가 경계 위반의 신호다.
    """
    assert GENERATED.is_dir(), f"{GENERATED} 가 없다"
    found = sorted(p.name for p in GENERATED.iterdir())
    assert found == sorted(fname for fname, _ in ARTIFACTS.values()), (
        f"생성물 디렉터리에 생성물 아닌 것이 있다: {found}")


# --- ★ 바이트 비교 ----------------------------------------------------------

@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_committed_artifact_matches_a_fresh_generation_byte_for_byte(
    name: str, rendered: dict[str, str], committed: dict[str, bytes]
):
    """★ D-11 의 핵심 장치. 손으로 고치면 여기가 깨진다."""
    fresh = rendered[name].encode("utf-8")
    current = committed[name]
    if current == fresh:
        return

    detail = ""
    try:
        if split_module(current.decode("utf-8"))[2] == split_module(fresh.decode("utf-8"))[2]:
            detail = (" (JSON 내용은 같다 — 직렬화·개행 차이다. "
                      ".gitattributes 의 frontend/generated/** text eol=lf 를 확인하라)")
    except (AssertionError, UnicodeDecodeError, json.JSONDecodeError):
        detail = " (커밋본이 생성물 형태가 아니다 — 손으로 고친 흔적이다)"

    pytest.fail(
        f"{artifact_path(name).relative_to(REPO_ROOT)} 가 생성기가 만드는 것과 다르다{detail}. "
        f"커밋본 {len(current):,} bytes vs 재생성 {len(fresh):,} bytes. "
        "손으로 고쳤다면 되돌리고, 원본(store · contracts/openapi.json)이 바뀌었다면 "
        "`python scripts/gen_contracts.py` 를 돌린 뒤 결과를 커밋하라 "
        "(SPEC 1.2 — 생성물은 손으로 수정하지 않는다).")


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_the_committed_artifact_uses_lf_only(name: str, committed: dict[str, bytes]):
    """CRLF 가 섞이면 리눅스 CI 는 통과하고 시연 머신인 윈도우에서만 깨진다."""
    raw = committed[name]
    assert b"\r" not in raw, (
        f"{artifact_path(name).name} 에 CR 이 있다. .gitattributes 의 "
        "frontend/generated/** text eol=lf 적용 후 파일을 지우고 "
        "git checkout -- frontend/generated/ 로 다시 받아라 "
        "(git 은 파일이 이미 있으면 필터를 다시 적용하지 않는다)")
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM 이 있다"


# --- 사람이 돌리는 명령 -----------------------------------------------------

def test_the_generator_command_a_human_runs_covers_the_frontend_artifacts():
    """★ 함수가 아니라 **문서에 적힌 명령**을 실제로 돌린다 (Part 0-A "실행 미검증")."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"`python scripts/gen_contracts.py --check` 가 {result.returncode} 로 끝났다.\n"
        f"{result.stdout}\n{result.stderr}")
    for name in ARTIFACTS:
        assert artifact_path(name).name in result.stdout, (
            f"--check 가 {artifact_path(name).name} 를 보지 않는다. "
            "게이트가 openapi 만 보면 프론트 생성물은 손으로 고쳐도 조용히 통과한다.\n"
            f"{result.stdout}")


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_regeneration_is_deterministic_in_a_fresh_process(name: str, committed: dict[str, bytes]):
    """같은 커밋이면 누가 어디서 돌려도 같은 바이트여야 한다.

    한 프로세스 안에서 두 번 부르는 것으로는 해시 시드·import 순서 같은 프로세스 단위
    변동이 드러나지 않는다.
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout", name],
        capture_output=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.replace(b"\r\n", b"\n") == committed[name]


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_stdout_does_not_depend_on_the_console_codec(name: str, committed: dict[str, bytes]):
    """윈도우 cp949 콘솔에서만 죽는 생성기를 만들지 않는다 (PR #20 · #30 과 같은 부류).

    표현력이 가장 좁은 코덱으로 강제한다 — ascii 로 통과하면 cp949 로도 통과한다.
    """
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"}
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout", name],
        capture_output=True, cwd=str(REPO_ROOT), env=env,
    )
    assert result.returncode == 0, (
        "생성기가 콘솔 코덱에 의존한다 — 좁은 코덱 환경에서 죽는다.\n"
        + result.stderr.decode("utf-8", "replace"))
    assert result.stdout == committed[name]


def test_the_artifacts_do_not_carry_the_developers_db_state():
    """개발자 DB 가 생성물에 새면 같은 커밋인데 사람마다 다른 바이트가 나온다.

    `gen_contracts.py` 는 임시 저장소를 스스로 시드해서 읽는다. 오염된 저장소를
    환경변수로 걸어도 결과가 커밋본과 같아야 그 격리가 실제로 작동하는 것이다.
    """
    from home_compass.store import STORE_URL_ENV, create_store
    from home_compass.store.seed import seed_all

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite://{Path(tmp) / 'polluted.db'}"
        with create_store(url) as store:
            seed_all(store, at=datetime(2001, 1, 1, tzinfo=timezone.utc))
            constant = store.model_constants.get("affordability.buffer_ratio")
            store.model_constants.put(type(constant)(**{**constant.__dict__, "value": 0.99}))
            assert store.model_constants.as_mapping()["affordability.buffer_ratio"] == 0.99

        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(REPO_ROOT), env={**os.environ, STORE_URL_ENV: url},
        )
    assert result.returncode == 0, (
        "오염된 저장소가 생성물에 샜다.\n" + result.stdout + result.stderr)


# --- 손으로 고치지 말라는 표시 ----------------------------------------------

@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_the_artifact_says_it_is_generated_and_how_to_regenerate_it(
    name: str, committed: dict[str, bytes]
):
    """표시가 없으면 다음 사람이 이 파일을 고치고, 그 다음에야 테스트가 말해 준다."""
    head, global_name, _ = split_module(committed[name].decode("utf-8"))
    assert global_name == ARTIFACTS[name][1], f"전역 이름이 계약과 다르다: {global_name}"
    assert "손으로 고치지 않는다" in head
    assert "python scripts/gen_contracts.py" in head
    assert "침묵 폴백" in head, "없을 때 어떻게 해야 하는지가 적혀 있지 않다 (D-11)"


# --- 침묵 폴백 금지 — 빈 생성물을 실패로 만든다 -----------------------------

def test_model_constants_cover_the_whole_registry(payloads: dict[str, dict]):
    """레지스트리 전수를 낸다. 부분 생성물은 소비자에게 「없음」이 아니라 「0」으로 보인다."""
    registry = json.loads((REPO_ROOT / "contracts" / "model_constants.json").read_text("utf-8"))
    expected = {entry["key"] for entry in registry["entries"]}
    assert expected, "레지스트리가 비었다 — 이 검사가 무력화된다"
    assert set(payloads["web-model-constants"]["entries"]) == expected


def test_policy_rules_are_not_empty(payloads: dict[str, dict]):
    assert payloads["web-policy-rules"]["ruleVersions"], (
        "정책 규칙 생성물이 비었다. 빈 목록을 내면 프론트는 「부적격 0건」을 판정 결과처럼 "
        "보여주게 된다 — D-11 이 금지한 침묵 폴백이다")


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_every_artifact_carries_the_same_engine_version(name: str, payloads: dict[str, dict]):
    """세 생성물이 같은 실행에서 나왔는지 소비자가 런타임에 확인할 수 있어야 한다."""
    from home_compass.common import ENGINE_VERSION

    assert payloads[name]["$generated"]["engineVersion"] == ENGINE_VERSION


# --- ★ 백엔드 판정 엔진과 필드 집합이 같은가 -------------------------------

def test_policy_criteria_fields_match_exactly_what_the_engine_reads(payloads: dict[str, dict]):
    """★ 다르면 두 판정 경로가 갈라진다 (Part 0-A 의 실패 유형).

    `test_rule_draft_schema.py` 가 계약 스키마에 대해 하는 것과 같은 검사를 생성물에
    대해 한다 — 정본은 `eligibility.py` 가 `crit.get()` 으로 실제 조회하는 키다.
    """
    read_by_engine = set(re.findall(r'crit\.get\("([A-Za-z]+)"', ELIGIBILITY.read_text("utf-8")))
    assert read_by_engine, "정규식이 아무것도 찾지 못했다 — 검사가 무력화된다"

    declared = set(payloads["web-policy-rules"]["criteriaFields"])
    assert declared == read_by_engine, (
        f"생성물에만 있음: {sorted(declared - read_by_engine)} / "
        f"엔진만 읽음: {sorted(read_by_engine - declared)}")


def test_every_generated_policy_carries_every_criteria_field(payloads: dict[str, dict]):
    """한 정책이라도 필드를 빠뜨리면 프론트 평가기가 그 요건을 조용히 건너뛴다."""
    rules = payloads["web-policy-rules"]
    fields = set(rules["criteriaFields"])
    for policy in rules["ruleVersions"]:
        criteria = policy["payload"].get("criteria") or {}
        assert set(criteria) == fields, f"{policy['policyId']}: {sorted(set(criteria) ^ fields)}"


def test_every_generated_policy_carries_its_rule_version_and_provenance(payloads: dict[str, dict]):
    """계보 없이 값만 내면 6단계 화면이 「어느 규칙 버전으로 판정했나」를 말할 수 없다."""
    for policy in payloads["web-policy-rules"]["ruleVersions"]:
        version = policy["ruleVersion"]
        assert version["status"] == "approved", "승인되지 않은 규칙이 실렸다 (SPEC 2.3)"
        assert version["origin"] in ("human_approval", "seed")
        assert set(("id", "effective_from", "effective_to", "supersedes")) <= set(version)
        assert policy["provenance"]["source_kind"] in (
            "statute", "statistic", "market", "normative")
        assert policy["provenance"]["verification"] in (
            "verified", "unverified", "stale", "our_choice")


def test_the_active_rule_predicate_is_carried_as_data(payloads: dict[str, dict]):
    """소비자가 SPEC 2.3 술어를 **자기 시각으로** 적용해야 한다.

    생성 시각으로 미리 걸러 내면 생성물이 「언제 생성됐나」에 의존하게 되고, 시행일이
    미래인 규칙은 그 날이 와도 영영 나오지 않는다.
    """
    rules = payloads["web-policy-rules"]
    assert "effective_from IS NULL" in rules["$activePredicate"]
    assert "effective_to" in rules["$activePredicate"]


# --- 지역 — 시세는 D-5 의 계보 대상이다 -------------------------------------
#
# SPEC 6.2 오프라인 정의 #2 는 「백엔드 없이도 화면이 뜬다 — 단, 판정 숫자는 생성물이
# 있을 때만 나온다」다. 로컬 판정 경로는 시세 없이 아무 숫자도 못 내므로, 손으로 쓴 시세가
# 남아 있으면 그 자리가 정확히 D-11 이 금지한 **침묵 폴백**이 된다.


def test_regions_are_not_empty(payloads: dict[str, dict]):
    """지역 0건은 판정 입력이 아니라 **설정 오류**다 (api 의 REGIONS_EMPTY_MESSAGE 와 같은 규율)."""
    assert payloads["web-regions"]["regions"], (
        "지역 생성물이 비었다. 빈 목록을 내면 프론트는 시세 없이 판정한 숫자를 "
        "보여주게 된다 — D-11 이 금지한 침묵 폴백이다")


def test_region_fact_fields_are_the_stores_eight(payloads: dict[str, dict]):
    """정본은 `store.models.REGION_FACT_FIELDS` 다. 생성기가 목록을 다시 적으면 정본이 둘이 된다."""
    from home_compass.store.models import REGION_FACT_FIELDS

    assert payloads["web-regions"]["$factFields"] == sorted(REGION_FACT_FIELDS)


def test_region_payload_is_exactly_what_the_engine_receives(payloads: dict[str, dict]):
    """★ 골라 담지 않는다 (결정 #34). 프론트 평가기의 입력이 백엔드 엔진의 입력과 같아야 한다.

    `api.read_regions()` 가 엔진에 넘기는 것이 `Region.to_engine_dict()` 의 목록이다.
    여기서 필드를 투영하면 「무엇을 골랐나」가 두 번째 계약이 되고, 저장소가 필드를
    늘려도 생성물은 조용히 예전 것만 낸다.
    """
    from home_compass.store import store_from_env

    with store_from_env() as store:
        expected = [region.to_engine_dict() for region in store.regions.list()]

    got = [entry["payload"] for entry in payloads["web-regions"]["regions"]]
    assert got == expected, "생성물의 지역이 엔진이 받는 것과 다르다 (순서 포함)"


def test_every_region_carries_field_level_provenance(payloads: dict[str, dict]):
    """★ D-5 — 계보는 **사실 단위**다. 레코드 요약 하나로 접으면 화면이 원인 유형을 못 가른다.

    실거래가에 대응물이 없는 3필드(`maintenanceFeeKRW` · `marketRisk` ·
    `guaranteeAvailable`)가 그 구분을 필요로 하는 자리이며, 10.2 6단계 완료 기준의
    「`dataGrade` 사유가 원인 유형별로 구분되어 표시된다」가 여기에 걸린다.
    """
    from home_compass.store.models import REGION_FACT_FIELDS

    for entry in payloads["web-regions"]["regions"]:
        field_provenance = entry["fieldProvenance"]
        assert set(field_provenance) == set(REGION_FACT_FIELDS), entry["code"]
        for name, provenance in field_provenance.items():
            assert provenance["source_kind"] in (
                "statute", "statistic", "market", "normative"), f"{entry['code']}/{name}"
            assert provenance["verification"] in (
                "verified", "unverified", "stale", "our_choice"), f"{entry['code']}/{name}"


def test_the_record_provenance_is_the_worst_of_the_field_provenances(payloads: dict[str, dict]):
    """SPEC 2.4 — 가장 나쁜 것이 이긴다. 요약이 필드보다 좋으면 그 레코드는 거짓말을 한다."""
    from home_compass.store.models import worst_verification

    for entry in payloads["web-regions"]["regions"]:
        worst = worst_verification(
            provenance["verification"] for provenance in entry["fieldProvenance"].values()
        )
        if worst is None:
            continue
        assert entry["provenance"]["verification"] == worst, entry["code"]


# --- 모델 상수는 값만이 아니라 계보를 낸다 (SPEC 10.2 6단계) ----------------

def test_model_constants_carry_value_verification_and_source_kind(payloads: dict[str, dict]):
    """값만 내면 6단계 완료 기준의 「계보 표시」가 성립하지 않는다."""
    entries = payloads["web-model-constants"]["entries"]
    for key, entry in entries.items():
        assert "value" in entry, key
        assert entry["provenance"]["verification"] in (
            "verified", "unverified", "stale", "our_choice"), key
        assert entry["provenance"]["source_kind"] in (
            "statute", "statistic", "market", "normative"), key
        assert entry["spec_class"] in ("a", "b", "c", "d"), key


def test_model_constant_values_are_the_stores_values(payloads: dict[str, dict]):
    """생성물의 값이 곧 판정에 쓰이는 값이어야 한다 — 아니면 사본이 거짓말을 한다."""
    from home_compass.store import store_from_env

    with store_from_env() as store:
        mapping = store.model_constants.as_mapping()

    entries = payloads["web-model-constants"]["entries"]
    for key, expected in mapping.items():
        got = entries[key]["value"]
        # JSON 은 int 키도 튜플도 담지 못한다. 그 둘만 되살려 비교한다.
        if isinstance(expected, dict):
            got = {int(k): v for k, v in got.items()}
        elif isinstance(expected, tuple):
            got = tuple(got)
        assert got == expected, key


# --- ★ 확정값의 유일한 거처는 계약 파일이다 (SPEC 8.3 #3 · #4) --------------

@pytest.mark.parametrize(
    "field, pointer",
    [
        ("boundaryConditions", "x-boundary-conditions"),
        ("units", "x-units"),
        ("rounding", "x-rounding"),
    ],
)
def test_contract_constants_are_the_committed_contract_verbatim(
    field: str, pointer: str, payloads: dict[str, dict]
):
    """생성물이 계약 파일의 `x-` 확장을 **그대로** 옮긴 것이어야 한다.

    투영·요약하면 그 순간 두 번째 정본이 생기고, 8.3 #3 의 「코드에 다시 쓰지 않는다」가
    「생성기 안에 다시 쓴다」로 바뀔 뿐이다.
    """
    contract = json.loads(OPENAPI.read_text("utf-8"))
    assert payloads["web-contract-constants"][field] == contract[pointer]


def test_the_client_timeouts_are_the_ones_the_contract_fixed(payloads: dict[str, dict]):
    """★ 8.3.2 확정값이 실제로 실렸는지 본다.

    현행 `frontend/app.js` 는 analyze 15,000 · GET 4,500 을 들고 있어 **계약보다 낡았다.**
    생성물이 낡은 값을 실어 나르면 D-11 이 아무것도 고치지 못한다.
    """
    profiles = payloads["web-contract-constants"]["boundaryConditions"]["profiles"]
    assert profiles["analyze"]["clientTimeoutMs"] == 5000
    assert profiles["read"]["clientTimeoutMs"] == 3000
    assert profiles["chat"]["clientTimeoutMs"] == 75000
    for profile in profiles.values():
        assert profile["retries"] == 0
        assert profile["onTimeout"]["silentFallback"] is False


def test_the_path_dispatch_rule_travels_with_the_values(payloads: dict[str, dict]):
    """값만 주고 「어느 경로가 어느 프로필인가」를 주지 않으면 소비자가 그것을 발명한다.

    발명하는 순간 8.3 의 정정이 경고한 「분리된 예산을 다시 하나로 합치는」 경로가 열린다.
    """
    boundary = payloads["web-contract-constants"]["boundaryConditions"]
    dispatch = boundary["clientDispatch"]
    assert dispatch["byPath"]["/api/chat"] == "chat"
    assert dispatch["byPath"]["/api/analyze"] == "analyze"
    assert dispatch["default"] == "read"
    assert set(dispatch["byPath"].values()) | {dispatch["default"]} <= set(boundary["profiles"])
