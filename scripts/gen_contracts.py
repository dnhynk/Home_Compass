"""생성물 만들기 — `python scripts/gen_contracts.py`

SPEC 1.2 의 생성 방향은 단방향이고 세 줄이다. **이 스크립트가 그 셋을 전부 낸다.**

    api   ──(OpenAPI 3.1)──────────────→ contracts/openapi.json          (D-12)
    contracts/openapi.json ──(x- 확장)─→ frontend/generated/*.js         (D-12 · 8.3 #4)
    store ──(ModelConstant · 승인된 RuleVersion · Region)→ frontend/generated/*.js (D-11 · D-5)

생성물은 손으로 고치지 않는다. 재생성 diff 테스트가 커밋본과 바이트 비교하므로, 손으로
고친 것은 다음 실행에서 되돌아가고 그 전에 테스트가 먼저 빨간불이 된다
(`test_generated_contracts_diff.py` · `test_generated_frontend_diff.py`).

    python scripts/gen_contracts.py                    # 전부 생성해서 쓴다
    python scripts/gen_contracts.py --check            # 쓰지 않고 커밋본과 다른지만 본다 (종료코드 1)
    python scripts/gen_contracts.py --stdout [NAME]    # 생성물 하나를 표준출력으로만

**왜 스크립트를 하나로 두는가.** D-12 가 「D-11 생성물과 같은 파이프라인이다」라고 적었고,
게이트를 둘로 나누면 한쪽만 도는 경로가 생긴다 — CI 단계도, `--check` 도, 사람이 외우는
명령도 둘이 된다. 파일이 아니라 **레지스트리**(`ARTIFACTS`)를 늘리는 형태로 얹는다.

**저장소를 요구한다.** `home_compass.main` 을 import 하는 것이 곧 기동이고, 기동은 모델
상수 전수 존재를 저장소에서 검증한다 (SPEC 5.1.1). 개발자 DB 상태가 생성물에 새어들지
않도록 여기서는 **임시 저장소를 시드해서 쓴다** — 같은 커밋이면 누가 어디서 돌려도 같은
바이트가 나와야 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _console import force_utf8_stdout

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

CONTRACTS_DIR = REPO_ROOT / "contracts"

#: SPEC 9.4 신설 — `web` 소유는 「생성물 디렉터리 **제외**」다. 여기는 코디네이터 소유다.
GENERATED_DIR = REPO_ROOT / "frontend" / "generated"

GENERATE_COMMAND = "python scripts/gen_contracts.py"

#: 생성물의 모양과 그 근거를 적는 곳. 머리말이 사람을 여기로 보낸다.
SHAPE_DOC = "contracts/README.md 결정 #34"


def _prepare_isolated_store(tmp_dir: str) -> None:
    """`home_compass.main` import 전에 시드된 임시 저장소를 환경변수로 건다."""
    from home_compass.store import STORE_URL_ENV, create_store
    from home_compass.store.seed import seed_all

    url = f"sqlite://{Path(tmp_dir) / 'contracts-gen.db'}"
    with create_store(url) as store:
        seed_all(store, at=datetime.now(timezone.utc))
    os.environ[STORE_URL_ENV] = url


# --------------------------------------------------------------------------
# 평문 JS 직렬화 (SPEC 6.2 오프라인 정의 #1 — 빌드툴·CDN 없이 <script> 로 읽힌다)
# --------------------------------------------------------------------------
#
# 바이트 비교가 성립하려면 직렬화가 결정적이어야 한다. openapi 쪽과 **같은 규칙**을 쓴다
# (`main.X_SERIALIZATION`) — UTF-8 · BOM 없음 · LF · indent 2 · sort_keys · ensure_ascii=False.
# 규칙을 하나 더 만들면 두 생성물이 다른 이유로 흔들리고, 그때 diff 는 계약이 아니라
# 잡음을 잡게 된다.

#: JSON 은 U+2028 · U+2029 를 그대로 두지만 ES2019 이전 JS 파서는 그 둘을 **줄바꿈**으로
#: 읽어 문자열 리터럴이 그 자리에서 끊긴다. 지금 데이터에는 없지만, 공고문에서 추출된
#: 규칙 문구가 그대로 실리는 경로이므로 언젠가 들어온다. 들어오는 날 깨지는 대신 지금 막는다.
_JS_UNSAFE = {code: chr(92) + "u%04x" % code for code in (0x2028, 0x2029)}


def _js_payload(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    return body.translate(_JS_UNSAFE)


def _js_module(*, global_name: str, source: str, payload: dict) -> str:
    """`머리말 주석` + `window.<전역> = <JSON>;` 한 줄. 그 이상을 만들지 않는다.

    함수를 내보내지 않는다 (D-11). 현행 `POLICY_CATALOG` 의 명령형 `rule` 함수가 생성
    대상이 아닌 이유가 여기 있다 — 생성물이 코드를 담기 시작하면 그 코드는 백엔드 엔진과
    별개로 자라고, 그것이 D-11 이 없애려는 **두 번째 판정 경로** 그 자체다.
    """
    head = (
        "/* ============================================================\n"
        "   생성물이다. 손으로 고치지 않는다 (SPEC D-11 · 1.2).\n"
        "\n"
        f"   재생성 : {GENERATE_COMMAND}\n"
        f"   검사   : {GENERATE_COMMAND} --check\n"
        f"   원본   : {source}\n"
        f"   모양   : {SHAPE_DOC}\n"
        "\n"
        "   손으로 고치면 backend/tests/crosscheck/test_generated_frontend_diff.py 의\n"
        "   바이트 비교가 깨진다. 되돌리려면 위 재생성 명령을 돌린다.\n"
        "\n"
        f"   이 파일이 없거나 로드에 실패하면 window.{global_name} 은 undefined 다.\n"
        "   소비자는 그 자리에서 로컬 판정 경로를 끄고 화면에 명시한다 — 기본값으로 메우는\n"
        "   침묵 폴백을 금지한다 (SPEC D-11 · 6.2 오프라인 동작 정의 #3).\n"
        "   ============================================================ */\n"
    )
    return f"{head}window.{global_name} = {_js_payload(payload)};\n"


def _generated_block(*, artifact: str, global_name: str, source: str, extra: dict | None = None) -> dict:
    """세 생성물이 공유하는 자기소개. 런타임에 기계가 읽는 자리다.

    `engineVersion` 은 **약한 신선도 토큰**이다. 셋이 같은 실행에서 나왔는지, 그리고
    백엔드가 닿을 때는 `/api/meta` 의 `engineVersion` 과 같은지를 소비자가 확인할 수 있다.
    SPEC 8.4 가 이 값을 「판정 출력이 달라지면 올린다」로 규정하므로, **판정 숫자를 바꾸지
    않는 변경은 잡지 못한다.** 그 한계까지가 이 토큰이 약속하는 전부다.
    """
    from home_compass.common import ENGINE_VERSION

    block = {
        "artifact": artifact,
        "global": global_name,
        "command": GENERATE_COMMAND,
        "doNotEdit": True,
        "source": source,
        "shapeDocumentedIn": SHAPE_DOC,
        "engineVersion": ENGINE_VERSION,
        "noSilentFallback": (
            f"이 파일이 없으면 window.{global_name} 은 undefined 다. 기본값·빈 값으로 "
            "대체하지 않는다. 판정 경로를 끄고 화면에 명시한다 (SPEC D-11)."
        ),
    }
    block.update(extra or {})
    return block


# --------------------------------------------------------------------------
# (가) 모델 상수 — ModelConstant 레지스트리에서
# --------------------------------------------------------------------------


def render_model_constants(store) -> str:
    """값 + 계보. **값만 내지 않는다.**

    SPEC 10.2 6단계 완료 기준이 「로컬 판정 경로가 생성물 기반」이고 그 화면은 계보를
    보여야 하므로, `verification` · `source_kind` 가 값과 같은 자리에 실려야 한다.
    값만 실으면 프론트는 「왜 이 숫자인가」를 영영 말하지 못한다.

    키 표기는 저장소·레지스트리의 snake_case 를 **그대로** 옮긴다. 여기서 표기를 다시
    정하면 그 매핑 자체가 두 번째 계약이 되고, 어긋나도 아무도 모른다.
    """
    from home_compass.store.seed import load_registry

    constants = sorted(store.model_constants.list(), key=lambda c: c.key)
    if not constants:
        raise RuntimeError(
            "저장소에 ModelConstant 가 0건이다. 빈 생성물을 쓰지 않는다 — 소비자에게는 "
            "「값이 없다」가 아니라 「0」으로 보인다 (SPEC D-11 침묵 폴백 금지).")

    payload = {
        "$generated": _generated_block(
            artifact="web-model-constants",
            global_name="HOME_COMPASS_MODEL_CONSTANTS",
            source="store 의 ModelConstant (SPEC 1.2 · D-11)",
            extra={"registryVersion": load_registry()["registryVersion"]},
        ),
        "$valueTypes": (
            "값의 해석은 contracts/model_constants.json 의 valueTypeVocabulary 를 따른다. "
            "percent_rate 는 /100 을 거치고 percent_level 은 거치지 않는다 — 섞으면 예선의 "
            "80만/81만 부류 단위 사고가 난다."
        ),
        "$objectKeys": (
            "krw_by_household 의 키는 JSON 에 정수가 없어 문자열이다 (\"1\" · \"2\" …). "
            "가구원수로 조회할 때 String(n) 으로 맞춘다."
        ),
        "entries": {
            c.key: {
                "key": c.key,
                "engine": c.engine,
                "legacy_symbol": c.legacy_symbol,
                "spec_class": c.spec_class,
                "value_type": c.value_type,
                "value": c.value,
                "provenance": c.provenance.to_dict(),
            }
            for c in constants
        },
    }
    return _js_module(
        global_name="HOME_COMPASS_MODEL_CONSTANTS",
        source="store 의 ModelConstant (SPEC D-11 · 5.1.4)",
        payload=payload,
    )


# --------------------------------------------------------------------------
# (나) 정책 규칙 — 승인된 RuleVersion 에서. **데이터로 낸다. 함수로 내지 않는다.**
# --------------------------------------------------------------------------

#: SPEC 2.3 의 술어. 문자열로 싣는 이유는 소비자가 **자기 시각으로** 적용해야 하기 때문이다.
#: 생성 시각으로 미리 걸러 두면 생성물이 「언제 생성됐나」에 의존하게 되고, 시행일이 미래인
#: 규칙은 그 날이 와도 영영 나오지 않는다. `store.rule_versions.active(at)` 의 SQL 그대로다.
ACTIVE_PREDICATE = (
    "status = 'approved' AND (effective_from IS NULL OR effective_from <= now) "
    "AND (effective_to IS NULL OR now < effective_to) — SPEC 2.3. "
    "이 배열은 승인된 규칙 **전부**이며, 소비자가 자기 시각으로 이 술어를 적용한다. "
    "적용하지 않으면 종료된 규칙이 판정에 실린다."
)


def _criteria_fields() -> list[str]:
    """판정이 읽는 `criteria` 필드 집합. 정본은 계약 스키마다.

    `contracts/rule_draft.schema.json` 이 이 집합을 고정하고, 그것이 `eligibility.py` 가
    `crit.get()` 으로 실제 조회하는 키와 같은지는 `test_rule_draft_schema.py` 가 이미
    붙들고 있다. 생성기가 목록을 다시 적으면 정본이 셋이 된다.
    """
    schema = json.loads((CONTRACTS_DIR / "rule_draft.schema.json").read_text(encoding="utf-8"))
    fields = sorted(schema["properties"]["criteria"]["properties"])
    if not fields:
        raise RuntimeError("rule_draft.schema.json 에서 criteria 필드를 읽지 못했다")
    return fields


def render_policy_rules(store) -> str:
    """승인된 `RuleVersion` 을 **payload 그대로** 낸다.

    투영하지 않는 이유가 핵심이다. `read_active_policies()` 가 엔진에 넘기는 것이 바로 이
    `payload` 이므로, 그대로 실으면 프론트 평가기의 입력이 백엔드 엔진의 입력과 **같은
    객체**가 된다. 필드를 골라 담는 순간 「무엇을 골랐나」가 두 번째 계약이 되고, 엔진이
    새 필드를 읽기 시작해도 생성물은 조용히 예전 것만 낸다.

    `created_at` 은 싣지 않는다 — 시드 실행 시각이라 재생성마다 달라진다. 판정에 쓰이지도
    않는다 (판정에 쓰이는 시각은 `effective_from`/`effective_to` 다).
    """
    versions = store.rule_versions.list()
    if not versions:
        raise RuntimeError(
            "저장소에 RuleVersion 이 0건이다. 빈 생성물을 쓰지 않는다 — 프론트는 그것을 "
            "「해당 제도 없음」이라는 판정 결과처럼 보여주게 된다 (SPEC D-11 침묵 폴백 금지).")

    payload = {
        "$generated": _generated_block(
            artifact="web-policy-rules",
            global_name="HOME_COMPASS_POLICY_RULES",
            source="store 의 승인된 RuleVersion (SPEC 1.2 · D-11 · 2.3)",
        ),
        "$activePredicate": ACTIVE_PREDICATE,
        "$noRuleFunctions": (
            "요건은 데이터다. 이 파일은 판정 함수를 담지 않는다 — 해석기는 소비자가 쓰고, "
            "그 해석은 backend/src/home_compass/engines/eligibility.py 와 같아야 한다 (SPEC D-11)."
        ),
        "criteriaFields": _criteria_fields(),
        "ruleVersions": [
            {
                "policyId": version.policy_id,
                "ruleVersion": {
                    "id": version.id,
                    "status": version.status,
                    "origin": version.origin,
                    "effective_from": _iso(version.effective_from),
                    "effective_to": _iso(version.effective_to),
                    "supersedes": version.supersedes,
                    "approved_by": version.approved_by,
                },
                "provenance": version.provenance.to_dict(),
                "payload": version.payload,
            }
            for version in versions
        ],
    }
    return _js_module(
        global_name="HOME_COMPASS_POLICY_RULES",
        source="store 의 승인된 RuleVersion (SPEC D-11 · 2.3)",
        payload=payload,
    )


def _iso(value: datetime | None) -> str | None:
    """`None` 은 그대로 `null` 이다 — 계약 결정 #6 의 「미상 · 무기한」이 그 표현이다."""
    return None if value is None else value.isoformat()


# --------------------------------------------------------------------------
# (다) 지역 시세 — store 의 Region 에서. 계보는 **사실 단위**다 (D-5)
# --------------------------------------------------------------------------


def render_regions(store) -> str:
    """엔진이 받는 지역 + **필드별** 계보.

    **왜 이것이 생성물이어야 하는가.** SPEC 6.2 오프라인 정의 #2 는 「백엔드 없이도 화면이
    뜬다 — 단, 판정 숫자는 생성물이 있을 때만 나온다」다. 로컬 판정 경로는 시세 없이 아무
    숫자도 내지 못하므로, 손으로 쓴 시세가 남아 있으면 그 자리가 정확히 D-11 이 금지한
    **침묵 폴백**이 된다. 상수·규칙만 생성물로 바꾸고 시세를 남겨 두면 절반만 고친 것이다.

    **`payload` 는 `to_engine_dict()` 그대로다** — `api.read_regions()` 가 엔진에 넘기는
    바로 그 객체다. 골라 담지 않는 이유는 정책 규칙 쪽과 같다.

    **계보를 두 층으로 싣는다.** `to_engine_dict()` 의 `source` 는 `source_name` 한 줄로
    접힌 화면 문구이고, 거기서 `verification` · `observed_at` 은 사라진다. 6단계 화면은
    `dataGrade` 사유를 **원인 유형별로** 보여야 하므로(10.2 6단계) 접히기 전의 것이 필요하다.
    실거래가에 대응물이 없는 3필드(`maintenanceFeeKRW` · `marketRisk` ·
    `guaranteeAvailable`)가 바로 그 구분을 요구하는 자리다.
    """
    from home_compass.store.models import REGION_FACT_FIELDS

    regions = store.regions.list()
    if not regions:
        raise RuntimeError(
            "저장소에 Region 이 0건이다. 빈 생성물을 쓰지 않는다 — 지역 0건은 판정 입력이 "
            "아니라 설정 오류다 (api 의 REGIONS_EMPTY_MESSAGE 와 같은 규율).")

    payload = {
        "$generated": _generated_block(
            artifact="web-regions",
            global_name="HOME_COMPASS_REGIONS",
            source="store 의 Region (SPEC 1.2 · D-11 · D-5)",
        ),
        "$factFields": sorted(REGION_FACT_FIELDS),
        "$provenanceLayers": (
            "payload.source 는 provenance.source_name 이 한 줄로 접힌 화면 문구다. "
            "기계 판독의 정본은 provenance(레코드 요약)와 fieldProvenance(사실 단위)이며, "
            "요약은 필드별 계보의 최악값이다 (SPEC 2.4 — 가장 나쁜 것이 이긴다)."
        ),
        # ★ 이 항목의 앞 판은 「지금은 8필드의 계보가 전부 같다」고 적었다. 8단계 1부
        #   (결정 #40, 시드를 실수집으로 굳힘)가 5필드를 verified 로 가르면서 **조용히
        #   거짓이 됐고**, 키 이름(`$seedFieldsAreNotYetDifferentiated`) 자체가 거짓을
        #   말하고 있었다. 리허설 워커의 ⑥ 이 그것을 잡았다.
        #
        #   그래서 **현재 값을 다시 적지 않는다.** 「지금 5개가 verified 다」로 갈아 끼우면
        #   3단계 수집이 한 번 더 돌 때 같은 자리에서 같은 방식으로 또 거짓이 된다.
        #   시점을 적는 대신 **불변식과 지시**만 남기고, 값이 지금 어떤지는 이 파일의
        #   `fieldProvenance` 가 직접 말하게 한다.
        "$readFieldProvenanceNotTheRecordSummary": (
            "필드별 계보는 **서로 다를 수 있다.** 레코드 요약(provenance)은 그 최악값이므로 "
            "(SPEC 2.4 — 가장 나쁜 것이 이긴다) 요약으로 접으면 더 나은 계보를 가진 필드가 "
            "과소 진술된다. 소비자는 fieldProvenance 를 필드 단위로 읽고, 값이 같아 보인다고 "
            "레코드 요약으로 접지 않는다. ★ 이 문장은 시점을 적지 않는다 — 앞 판이 "
            "「지금은 8필드가 전부 같다」고 적었다가 8단계 1부(결정 #40)가 시드를 실수집으로 "
            "굳히면서 조용히 거짓이 됐다. 지금 어떤지는 이 파일의 fieldProvenance 가 말한다."
        ),
        "regions": [
            {
                "code": region.code,
                "name": region.name,
                "payload": region.to_engine_dict(),
                "provenance": region.provenance.to_dict(),
                "fieldProvenance": {
                    name: region.provenance_for(name).to_dict()
                    for name in REGION_FACT_FIELDS
                },
            }
            for region in regions
        ],
    }
    return _js_module(
        global_name="HOME_COMPASS_REGIONS",
        source="store 의 Region (SPEC D-11 · D-5 · 6.2 오프라인 정의 #2)",
        payload=payload,
    )


# --------------------------------------------------------------------------
# (라) 계약 상수 — contracts/openapi.json 의 x- 확장에서
# --------------------------------------------------------------------------


def render_contract_constants(document: dict) -> str:
    """`x-` 확장을 **그대로** 옮긴다. 투영하지 않는다.

    SPEC 8.3 #3 은 확정값이 계약 파일의 `x-` 확장에만 존재하라고 하고 #4 는 서버·클라이언트가
    같은 파일에서 읽으라고 한다. 여기서 값을 골라 담거나 이름을 바꿔 요약하면 그 순간
    **생성기 안에 두 번째 정본**이 생긴다. 그래서 블록째로 싣고, 커밋된 openapi.json 과
    같은지는 `test_generated_frontend_diff.py` 가 본다.

    최상단 키만 `x-` 접두를 떼고 camelCase 로 바꾼다 — JS 에서 `obj["x-units"]` 는 대괄호
    없이 읽히지 않는다. 그 대응은 `$generated.sourcePointers` 에 RFC 6901 로 적는다.
    """
    return _js_module(
        global_name="HOME_COMPASS_CONTRACT_CONSTANTS",
        source="contracts/openapi.json 의 x- 확장 (SPEC D-12 · 8.3 #3 · #4)",
        payload={
            "$generated": _generated_block(
                artifact="web-contract-constants",
                global_name="HOME_COMPASS_CONTRACT_CONSTANTS",
                source="contracts/openapi.json 의 x- 확장 (SPEC 8.3 #3 · #4)",
                extra={
                    "sourcePointers": {
                        "apiContractVersion": "/info/version",
                        "boundaryConditions": "/x-boundary-conditions",
                        "rounding": "/x-rounding",
                        "units": "/x-units",
                    },
                },
            ),
            "$timeoutLookup": (
                "clientDispatch.byPath[path] 로 프로필 이름을 찾고, 없으면 "
                "clientDispatch.default 를 쓴다. 그 프로필의 clientTimeoutMs 가 값이다. "
                "경로별 예산을 하나로 합치지 않는다 (SPEC 8.3 #6 · 8.3 정정)."
            ),
            "apiContractVersion": document["info"]["version"],
            "boundaryConditions": document["x-boundary-conditions"],
            "rounding": document["x-rounding"],
            "units": document["x-units"],
        },
    )


# --------------------------------------------------------------------------
# 레지스트리 — 새 생성물은 여기 한 줄로 는다
# --------------------------------------------------------------------------


def artifact_paths() -> dict[str, Path]:
    from home_compass.main import OPENAPI_PATH

    return {
        "openapi": OPENAPI_PATH,
        "web-model-constants": GENERATED_DIR / "model_constants.js",
        "web-policy-rules": GENERATED_DIR / "policy_rules.js",
        "web-regions": GENERATED_DIR / "regions.js",
        "web-contract-constants": GENERATED_DIR / "contract_constants.js",
    }


#: `--stdout` 이 받는 이름. 순서가 곧 `--help` 와 출력 순서다.
ARTIFACTS = (
    "openapi",
    "web-model-constants",
    "web-policy-rules",
    "web-regions",
    "web-contract-constants",
)


def render_all(store) -> dict[str, str]:
    """생성물 전부를 문자열로. 파일에 쓰지 않는다 — 쓰는 것은 호출자의 결정이다."""
    from home_compass.main import build_openapi_document, render_openapi_document

    document = build_openapi_document()
    return {
        "openapi": render_openapi_document(document),
        "web-model-constants": render_model_constants(store),
        "web-policy-rules": render_policy_rules(store),
        "web-regions": render_regions(store),
        "web-contract-constants": render_contract_constants(document),
    }


def _write(path: Path, rendered: str) -> bool:
    """바뀌었으면 True. 바뀌지 않았으면 파일을 건드리지 않는다 — mtime 만 흔들면
    무엇이 바뀌었는지가 흐려진다. 텍스트 모드를 쓰지 않는다(윈도우에서 CRLF 가 된다)."""
    data = rendered.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="생성물 만들기 (SPEC D-11 · D-12)")
    parser.add_argument("--check", action="store_true",
                        help="쓰지 않는다. 하나라도 커밋본과 다르면 종료코드 1")
    parser.add_argument("--stdout", nargs="?", const="openapi", choices=ARTIFACTS,
                        metavar="NAME",
                        help=f"생성물 하나를 표준출력으로만 낸다. 이름 생략 시 openapi. "
                             f"이름: {' · '.join(ARTIFACTS)}")
    args = parser.parse_args(argv)

    tmp_dir = tempfile.mkdtemp(prefix="home_compass-gen-")
    try:
        _prepare_isolated_store(tmp_dir)
        from home_compass.store import store_from_env

        with store_from_env() as store:
            rendered = render_all(store)
        paths = artifact_paths()

        if args.stdout:
            # 텍스트 스트림으로 쓰지 않는다. 생성물은 UTF-8 **바이트**이고, 콘솔 코덱을
            # 거치면 그 코덱이 표현하지 못하는 문자에서 터진다 — 윈도우 cp949 콘솔에서
            # em dash 하나로 UnicodeEncodeError 가 났다. 리눅스 CI 는 UTF-8 이라 통과하고
            # **시연 머신인 윈도우에서만 깨진다.** contracts/** eol=lf 와 같은 부류다.
            sys.stdout.buffer.write(rendered[args.stdout].encode("utf-8"))
            sys.stdout.buffer.flush()
            return 0

        if args.check:
            stale = []
            for name in ARTIFACTS:
                path = paths[name]
                rel = path.relative_to(REPO_ROOT)
                current = path.read_bytes() if path.exists() else b""
                if current == rendered[name].encode("utf-8"):
                    print(f"OK  {rel} 는 코드와 일치한다")
                else:
                    print(f"[!] {rel} 가 코드와 다르다")
                    stale.append(str(rel))
            if stale:
                print(f"{len(stale)}건이 낡았다: {', '.join(stale)}. "
                      f"`{GENERATE_COMMAND}` 를 돌리고 결과를 커밋하세요.")
                return 1
            return 0

        for name in ARTIFACTS:
            path = paths[name]
            changed = _write(path, rendered[name])
            size = len(rendered[name].encode("utf-8"))
            print(f"{'갱신' if changed else '변화 없음'}  "
                  f"{path.relative_to(REPO_ROOT)}  ({size:,} bytes)")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
