"""교차 테스트 — 발표 자료가 생성기와 어긋나지 않는다 (SPEC 9.4).

## 왜 이 파일이 생겼나

**PR #76 이 `build_ppt.py` 22곳을 고치고 `.pptx` 를 다시 뽑지 않았다.** 그래서 심사위원이
받는 파일에는 옛 거짓이 그대로 남아 있었다 — 위험 밴드 `0–39/40–69/70–100`(실제
`0–34/35–64/65–100`) · `Python 3.13`(실제 `>=3.11`) · `run.bat`(없다) · `app.py`(`main.py`) ·
`CORS 허용`(없다) · `MOCK_RESPONSE 폴백`(삭제됨) · 존재하지 않는 rationale 8줄.

**아무도 못 잡은 이유는 검사가 없었기 때문이다.** `frontend/generated/` 는 바이트 비교가
같은 사고를 막고 있었고 `docs/competition/` 에는 그것이 없었다. 이 파일이 그 빈자리다.

현재 생성기는 Artifact Tool 기반의 `build_ppt.mjs`이고, Python 진입점이 생성기·PPTX의
해시와 본문 해시를 매니페스트에 기록한다. CI는 저작 런타임 없이도 세 파일의 어긋남을
검출한다. 실제 생성 명령은 `python docs/competition/build_ppt.py`다.

## `python-pptx` 가 없으면 **건너뛰지 않는다**

`skip` 은 침묵 폴백이다 (계약 결정 #36 조건 ② · `test_undrained_server_pipe` 의 같은 규율).
없으면 **무엇을 설치해야 하는지 말하고 실패한다.** CI 는 `docs/competition/requirements.txt`
를 설치하므로 거기서는 늘 돈다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DECK_DIR = REPO_ROOT / "docs" / "competition"
BUILDER = DECK_DIR / "build_ppt.py"
JS_BUILDER = DECK_DIR / "build_ppt.mjs"
MANIFEST = DECK_DIR / "technical_deck_manifest.json"
DECK = DECK_DIR / "기술설명서_Home_Compass.pptx"


def _require_pptx():
    if importlib.util.find_spec("pptx") is None:
        pytest.fail(
            "python-pptx 가 없어서 발표 자료 대조를 할 수 없다. **건너뛰지 않는다** — "
            "이 검사가 없는 동안 생성기와 생성물이 어긋난 채로 커밋됐다(PR #76). "
            "`pip install -r docs/competition/requirements.txt` 로 설치한다."
        )


@pytest.fixture(scope="module")
def builder():
    _require_pptx()
    sys.path.insert(0, str(DECK_DIR))
    spec = importlib.util.spec_from_file_location("build_ppt", BUILDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_ppt"] = module
    spec.loader.exec_module(module)
    return module


# --- 인용한 판정 문구가 엔진과 어긋나지 않는다 ------------------------------
#
# ★ **이 파수병이 없는 동안 덱은 엔진이 내지 않는 문장을 「실제 반환 문자열」이라며
#   인용하고 있었다** — `(safe)` · `(conditional)` · `(stretch)` 셋이다. 셋 다 원시 enum 이
#   시민 화면에 새던 것을 걷어내면서 엔진에서 사라졌는데 **덱만 그대로 들고 있었다.**
#   PR #76 이 만든 사고(생성기를 고치고 생성물을 안 뽑음)와 **같은 부류의 반대 방향**이다 —
#   이번에는 코드가 앞서갔고 제출물이 뒤에 남았다.
#
# 왜 숫자까지 대조하지 않는가. 덱의 `_rationale_box` 는 자체 예시 프로필(연소득 4,200만원 ·
# 보증금 2억 8,000만원)을 쓰고 회귀 프로필과 값이 다르다. 그것은 거짓이 아니라 예시다 —
# 상자 머리글이 「형식 예시」라고 밝힌다. **거짓이 되는 것은 판정 어휘 쪽이다:** 엔진이
# 괄호로 내지 않는 enum 을 덱이 괄호로 달면 심사위원은 없는 출력을 본다.
#
# 그래서 대조 대상을 **괄호 안의 판정 enum** 으로 좁힌다. 골든(`rationale.json`)이 엔진
# 출력의 정본이므로, 덱이 쓰는 `(enum)` 은 거기 실재해야 한다.

#: `Literal[...]` 로 계약에 박혀 있는 판정 어휘. 여기 없는 괄호는 이 검사의 대상이 아니다
#: (예: `(아파트/기타)` 같은 설명 괄호).
_VERDICT_ENUMS = (
    "safe", "caution", "risk",
    "low", "medium", "high",
    "affordable", "stretch", "unaffordable",
    "eligible", "conditional", "ineligible",
)

_ENUM_IN_PARENS = re.compile(r"\((%s)\)" % "|".join(_VERDICT_ENUMS))

GOLDEN_RATIONALE = REPO_ROOT / "backend" / "tests" / "golden" / "rationale.json"


def _engine_strings():
    """골든에 담긴 **모든** 문자열. 엔진이 실제로 낸 것의 정본이다."""

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, str):
            yield node

    return list(walk(json.loads(GOLDEN_RATIONALE.read_text(encoding="utf-8"))))


def deck_enum_drift(source: str, engine_strings: list[str]) -> list[str]:
    """덱이 괄호로 다는 판정 enum 중 엔진이 내지 않는 것. 없으면 빈 목록이다."""
    emitted = {
        match.group(0)
        for line in engine_strings
        for match in _ENUM_IN_PARENS.finditer(line)
    }
    used = {match.group(0) for match in _ENUM_IN_PARENS.finditer(source)}
    return sorted(used - emitted)


class TestTheQuotedVerdictWordsExistInTheEngine:
    def test_the_real_builder_matches(self):
        drift = deck_enum_drift(JS_BUILDER.read_text(encoding="utf-8"), _engine_strings())
        assert drift == [], (
            f"덱이 엔진에 없는 판정 어휘를 인용한다: {drift}. "
            "엔진에서 원시 enum 을 걷어냈다면 덱의 인용도 함께 고쳐야 한다."
        )

    def test_a_vanished_enum_is_caught(self):
        """엔진이 어휘를 지웠는데 덱에 남은 것을 실제로 잡는지 — 프로브."""
        engine = [s for s in _engine_strings() if "(low)" not in s]
        drift = deck_enum_drift(JS_BUILDER.read_text(encoding="utf-8"), engine)
        assert "(low)" in drift, (
            f"엔진이 (low) 를 지웠는데 덱에 남은 것을 못 잡았다: {drift}")

    def test_a_planted_enum_is_caught(self):
        """덱이 없는 어휘를 새로 다는 것을 잡는지 — 프로브."""
        planted = JS_BUILDER.read_text(encoding="utf-8").replace(
            "(low)", "(caution)", 1)
        drift = deck_enum_drift(planted, _engine_strings())
        assert "(caution)" in drift, f"덱에 심은 (caution) 을 못 잡았다: {drift}"


# --- 있어야 할 것들 ---------------------------------------------------------

def test_the_builder_and_the_deck_both_exist():
    """둘 중 하나가 사라지면 아래 검사가 **조용히 0건을 통과시킨다.**"""
    assert BUILDER.is_file(), f"생성기가 없다: {BUILDER}"
    assert JS_BUILDER.is_file(), f"슬라이드 소스가 없다: {JS_BUILDER}"
    assert MANIFEST.is_file(), f"검증 매니페스트가 없다: {MANIFEST}"
    assert DECK.is_file(), f"생성물이 없다: {DECK}"


# --- 핵심 — 커밋된 덱이 지금 코드와 같은가 ----------------------------------

def test_the_committed_deck_matches_its_source_manifest(builder):
    """생성기나 PPTX만 바뀌면 매니페스트 검증이 실패한다."""
    assert builder.deck_text(str(DECK)), "커밋된 덱에서 본문을 한 줄도 못 읽었다"
    assert builder.verify() == 0


def test_a_planted_drift_is_caught(builder):
    """매니페스트가 본문 한 글자 차이를 구분하는지 확인한다."""
    fresh = builder.deck_text(str(DECK))
    drifted = [*fresh]
    drifted[0] += " (심어 넣은 어긋남)"
    assert builder._text_sha256(DECK) != __import__("hashlib").sha256(
        json.dumps(drifted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# --- 수를 문장에 박지 않는다 ------------------------------------------------

def test_the_endpoint_count_is_counted_not_typed(builder):
    """★ 「15종」을 손으로 적어 둔 뒤 6-A 신고 둘과 7단계 감사 하나가 늘어 **18종이 됐다.**

    같은 부류를 이 저장소가 반복해서 잡아왔다 (`ingest` 주석의 10건 · `regions.js` 의
    시점 주석). 그래서 계약에서 세게 했고, 여기서 그 값이 계약과 같은지 본다.
    """
    spec = json.loads((REPO_ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    methods = {"get", "post", "put", "delete", "patch"}
    ops = [(p, m) for p, item in spec["paths"].items() for m in item if m in methods]
    admin = sum(1 for p, _ in ops if p.startswith("/api/admin/"))
    auth = sum(1 for p, _ in ops if p.startswith("/api/auth/"))

    citizen, admin_count, total = builder._endpoint_counts()
    assert (citizen, admin_count, total) == (len(ops) - admin - auth, admin, len(ops))

    source = JS_BUILDER.read_text(encoding="utf-8")
    assert "계약 전체는 15종" not in source, "엔드포인트 수가 다시 문장에 박혔다"
    assert "contracts/openapi.json" in source
    assert "${endpointCount}" in source


def test_the_deck_says_the_endpoint_count_the_contract_says(builder):
    """덱 본문에 실제로 그 수가 찍혀 있는가 — 세기만 하고 안 쓰면 소용없다."""
    total = builder._endpoint_counts()[2]
    body = "\n".join(builder.deck_text(str(DECK)))
    assert re.search(rf"계약 전체는 {total}종", body), (
        f"덱이 계약 전체 {total}종을 말하지 않는다")


# --- 다시 낡을 자리 — 정본과 대조한다 ---------------------------------------

def test_the_deck_does_not_repeat_the_corrected_falsehoods(builder):
    """PR #76 과 이번에 고친 문구가 되살아나지 않았는지. **문자열 목록이지 만능이 아니다.**"""
    body = "\n".join(builder.deck_text(str(DECK)))
    dead = [
        "run.bat", "app.py", "CORS 허용", "MOCK_RESPONSE", "Python 3.13",
        "0–39", "40–69", "70–100",
        "policies.json의 요건 배열",
        "구조 시연용 예시 데이터",
        "KB 사업 연계", "KB국민은행", "KB 주택금융",
        "개인 참가", "2026년 8월 3일", "14장 참조", "본 기술설명서 14장",
    ]
    found = [d for d in dead if d in body]
    assert not found, f"고쳤던 문구가 덱에 되살아났다: {found}"


def test_the_risk_bands_match_the_constant_registry(builder):
    """위험 밴드 경계는 **상수 레지스트리가 정본**이다. 덱이 그 값을 말해야 한다."""
    registry = json.loads(
        (REPO_ROOT / "contracts" / "model_constants.json").read_text(encoding="utf-8"))
    values = {e["key"]: e["frozen_current_value"] for e in registry["entries"]}
    low_max = values["risk.band_low_max"]
    medium_max = values["risk.band_medium_max"]

    body = "\n".join(builder.deck_text(str(DECK)))
    assert f"0–{low_max}" in body, f"덱의 low 밴드가 상수(0–{low_max})와 다르다"
    assert f"{low_max + 1}–{medium_max}" in body
    assert f"{medium_max + 1}–100" in body


def test_the_mandatory_disclaimer_is_verbatim(builder):
    """필수 고지는 `common.DISCLAIMER` 와 **글자 단위로** 같아야 한다.

    ★ 소스를 정규식으로 파싱하지 않는다 — 처음에 그렇게 썼다가 값이 괄호로 감싸여
      있어서 못 찾았다. **표현 형태를 검사하면 표현이 바뀔 때 검사가 거짓말한다.**
      값이 필요하면 값을 import 한다.
    """
    from home_compass.common import DISCLAIMER

    body = "\n".join(builder.deck_text(str(DECK)))
    assert DISCLAIMER in body, (
        f"덱의 필수 고지가 코드의 DISCLAIMER 와 다르다.\n  코드: {DISCLAIMER}")
