"""포맷 골든 픽스처에 대한 **파이썬 구현 적합성** (SPEC 9.1.1 · 계약 결정 #16).

9.1.1 이 정한 판정 방식은 하나다 — **판정 기준은 구현이 아니라 출력이다.**
`contracts/format_golden.json` 에 입력 → 기대 문자열을 두고 **양쪽 구현이 같은 파일을
읽어** 검증한다. 한쪽만 바꾸면 그쪽 테스트가 깨진다.

이 파일은 그 양쪽 중 **파이썬 변**이다. JS 변은 D-11(6단계 `web`)이 같은 파일을 읽어
붙든다. 픽스처 자체의 완결성(음수·0·억 경계·반올림 캐리·소수 자릿수가 들어 있는가)은
`crosscheck/test_format_golden_fixture.py` 가 따로 본다 — 셋의 역할이 다르다.

  픽스처 완결성   crosscheck (코디네이터)  계약이 무엇을 요구하는가
  파이썬 적합성   여기 (engines)           우리 구현이 그것을 내는가
  JS 적합성       6단계 web                저쪽 구현이 그것을 내는가

계약 결정 #16 이 고치라고 지시한 세 결함이 여기서 잡힌다 —
은행가 반올림 · 음수 클램프 · `:g` 의 자릿수 소실.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from home_compass.common import money, pct, safe_int  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "format_golden.json"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))

MONEY_CASES = [(c["in"], c["out"], c["why"]) for c in GOLDEN["money"]["cases"]]
PCT_CASES = [(c["in"], c["digits"], c["out"], c["why"]) for c in GOLDEN["pct"]["cases"]]


@pytest.mark.parametrize("value, expected, why", MONEY_CASES, ids=[str(c[0]) for c in MONEY_CASES])
def test_money_matches_the_golden_fixture(value, expected, why):
    assert money(value) == expected, f"money({value}) — {why}"


@pytest.mark.parametrize(
    "value, digits, expected, why", PCT_CASES,
    ids=[f"{c[0]}@{c[1]}" for c in PCT_CASES],
)
def test_pct_matches_the_golden_fixture(value, digits, expected, why):
    assert pct(value, digits) == expected, f"pct({value}, {digits}) — {why}"


# --- 픽스처가 통째로 빠지는 사고를 막는다 -----------------------------------

def test_the_fixture_is_actually_being_read():
    """케이스가 0건이면 위 두 테스트는 아무것도 검증하지 않고 초록이 된다."""
    assert len(MONEY_CASES) >= 15
    assert len(PCT_CASES) >= 10


# --- 결정 #16 이 명시적으로 남기라고 한 것 -----------------------------------

def test_safe_int_still_clamps_negatives():
    """★ `safe_int` 는 **바꾸지 않는다** (계약 결정 #16).

    입력 강제에서 음수를 0으로 보는 것은 타당하다 — 소득·자산·부채가 음수로 들어오면
    0으로 읽는 것이 맞다. 결함은 강제 자체가 아니라 **표시 함수가 그것을 쓴 것**이었다.
    이 구분이 사라지면 다음 사람이 `safe_int` 를 고쳐 판정 입력까지 음수를 태운다.
    """
    assert safe_int(-750_000) == 0
    assert safe_int(-1) == 0
    assert safe_int("쓰레기") == 0
    assert safe_int(None, 3) == 3


def test_money_does_not_route_through_safe_int():
    """표시 함수가 음수를 0으로 뭉개지 않는다 — 위 테스트와 짝이다."""
    assert money(-750_000) == "-75만원"
    assert safe_int(-750_000) == 0


def test_money_rounds_half_away_from_zero_not_to_even():
    """은행가 반올림이 되돌아오면 여기서 잡힌다. 25,000원에서 1만원이 갈린다."""
    assert money(25_000) == "3만원"
    assert money(35_000) == "4만원"
    assert money(-25_000) == "-3만원"


def test_pct_keeps_the_requested_precision():
    """`:g` 는 25% 와 25.0% 를 구분 불가능하게 만든다. F-1 이후 그 구분이 의미를 갖는다."""
    assert pct(25.0, 1) == "25.0%"
    assert pct(100.0, 1) == "100.0%"
    assert pct(120.7, 1) == "120.7%"
