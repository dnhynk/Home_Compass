"""교차 테스트 — 발표 자료가 생성기와 어긋나지 않는다 (코디네이터 소유, SPEC 9.4).

## 왜 이 파일이 생겼나

**PR #76 이 `build_ppt.py` 22곳을 고치고 `.pptx` 를 다시 뽑지 않았다.** 그래서 심사위원이
받는 파일에는 옛 거짓이 그대로 남아 있었다 — 위험 밴드 `0–39/40–69/70–100`(실제
`0–34/35–64/65–100`) · `Python 3.13`(실제 `>=3.11`) · `run.bat`(없다) · `app.py`(`main.py`) ·
`CORS 허용`(없다) · `MOCK_RESPONSE 폴백`(삭제됨) · 존재하지 않는 rationale 8줄.

**아무도 못 잡은 이유는 검사가 없었기 때문이다.** `frontend/generated/` 는 바이트 비교가
같은 사고를 막고 있었고 `docs/competition/` 에는 그것이 없었다. 이 파일이 그 빈자리다.

## 왜 바이트가 아니라 본문인가 — **재 봤다**

같은 코드로 두 번 뽑아 sha 를 비교하면 **다르다.** `.pptx` 는 zip 이고 항목마다 시각이
박힌다. 그러나 **본문 텍스트는 결정적이다** — 두 번 뽑아 544문장이 완전히 일치했다.
그래서 목적(생성물이 생성기와 같은가)은 같고 수단만 다르다.

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
DECK = DECK_DIR / "기술설명서_KB첫집나침반.pptx"


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


# --- 있어야 할 것들 ---------------------------------------------------------

def test_the_builder_and_the_deck_both_exist():
    """둘 중 하나가 사라지면 아래 검사가 **조용히 0건을 통과시킨다.**"""
    assert BUILDER.is_file(), f"생성기가 없다: {BUILDER}"
    assert DECK.is_file(), f"생성물이 없다: {DECK}"


# --- 핵심 — 커밋된 덱이 지금 코드와 같은가 ----------------------------------

def test_the_committed_deck_matches_a_fresh_build(builder, tmp_path):
    """★ 이 저장소가 `frontend/generated/` 에 거는 것과 **같은 강제**다.

    생성기만 고치고 덱을 안 뽑으면 여기서 빨간불이 난다. PR #76 이 그렇게 샜다.
    """
    committed = builder.deck_text(str(DECK))
    assert committed, "커밋된 덱에서 본문을 한 줄도 못 읽었다"

    backup = tmp_path / "committed.pptx"
    backup.write_bytes(DECK.read_bytes())
    try:
        builder.build()
        fresh = builder.deck_text(str(DECK))
    finally:
        DECK.write_bytes(backup.read_bytes())   # 검사는 저장소를 바꾸지 않는다

    if committed != fresh:
        only_committed = [t for t in committed if t not in set(fresh)][:12]
        only_fresh = [t for t in fresh if t not in set(committed)][:12]
        pytest.fail(
            "커밋된 발표 자료가 build_ppt.py 와 다르다. "
            "`python docs/competition/build_ppt.py` 로 다시 뽑아 함께 커밋한다.\n"
            f"  커밋본에만: {only_committed}\n"
            f"  재생성에만: {only_fresh}"
        )


def test_a_planted_drift_is_caught(builder, tmp_path):
    """★ 규칙이 표에만 남지 않게 한다 — 어긋남을 먹여 걸리는 것을 본다.

    실제 파일이 일치하는 것과 **대조가 작동하는 것**은 다른 사실이다.
    """
    fresh = builder.deck_text(str(DECK))
    drifted = [t for t in fresh]
    drifted[0] = drifted[0] + " (심어 넣은 어긋남)"
    assert drifted != fresh


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

    source = BUILDER.read_text(encoding="utf-8")
    assert "계약 전체는 15종" not in source, "엔드포인트 수가 다시 문장에 박혔다"
    assert "_endpoint_counts()" in source


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
    from firsthome.common import DISCLAIMER

    body = "\n".join(builder.deck_text(str(DECK)))
    assert DISCLAIMER in body, (
        f"덱의 필수 고지가 코드의 DISCLAIMER 와 다르다.\n  코드: {DISCLAIMER}")
