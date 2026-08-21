"""1-③ 뒷부분 — F-3 보증료율표 · F-4 가입요건 상한 · F-5 없는 하한의 폐기.

세 결함은 **값이 틀린 것이 아니라 모델이 틀린 것**이었다 (FINDINGS.md A3-1·A3-2·A3-3·4절).

  F-3  `tco.guarantee_rate_pct` = 0.15 는 단일값이 아니다. 실제 공시는 보증금액 4구간 x
       주택유형 2종 x 부채비율 3구간 = **24칸 요율표**이고, 0.15 는 그 표의 **어느 칸과도
       일치하지 않는다.**
  F-4  `risk.guarantee_limit_krw` = 7억은 「보증한도」가 아니다. 7억은 **가입 가능한
       전세보증금의 상한**(수도권 7억 / 그 외 5억)이고, 보증한도는
       「주택가격 x 90% - 선순위채권」이라는 물건별 산식이다. 이름과 의미가 어긋나 있었고
       상수 하나가 서로 다른 둘을 겸하고 있었다.
  F-5  `tco.guarantee_min_deposit_krw` = 3천만은 **대응하는 제도가 없다.** HUG 가 거는
       문턱은 상한이지 하한이 아니다.

★ 이 파일의 제일 중요한 테스트는 `test_the_registry_table_is_the_excerpt_verbatim` 이다.
  24개 요율은 **우리가 만든 값이 아니라 원문에서 읽은 값**이어야 하고, 그것을 사람의
  주장이 아니라 기계 검사로 붙든다 — 실사 발췌 문서의 표를 파싱해 레지스트리와 대조한다.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from home_compass.engines import (  # noqa: E402
    analyze,
    guarantee_deposit_cap_for,
    required_constant_keys,
)
from home_compass.engines.risk import scan_deposit_risk  # noqa: E402
from home_compass.engines.tco import evaluate_scenario, guarantee_rate_pct_for  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed, load_registry  # noqa: E402

CONSTANTS = frozen_seed()

# SPEC 2.3 컷오버 — 지역·정책도 주입받는다 (`decision_inputs.py`).
REGIONS = store_regions()
POLICIES = store_policies(FROZEN_NOW)

EXCERPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs" / "engineering" / "diligence" / "excerpts" / "A3-hug-보증료율표.md"
)

#: 폐기된 단일 요율. 어느 칸과도 일치하지 않는다는 사실을 테스트가 직접 쓴다.
DROPPED_FLAT_RATE_PCT = 0.15

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


def _table() -> list[dict]:
    return CONSTANTS["tco.guarantee_rate_table"]


def _scenario(**overrides) -> dict:
    kwargs = {
        "scenario_id": "unit",
        "label": "단위 테스트 시나리오",
        "scenario_type": "jeonse",
        "deposit_krw": 200_000_000,
        "monthly_rent_krw": 0,
        "maintenance_fee_krw": 0,
        "loan_amount_krw": 0,
        "loan_rate_pct": 0.0,
        "liquid_assets_krw": 1_000_000_000,
        "affordable_max_krw": 2_000_000,
        "affordable_recommended_krw": 1_700_000,
        "monthly_net_income_krw": 3_000_000,
        "guarantee_deposit_cap_krw": 700_000_000,
    }
    kwargs.update(overrides)
    return evaluate_scenario(
        kwargs.pop("scenario_id"),
        kwargs.pop("label"),
        kwargs.pop("scenario_type"),
        constants=CONSTANTS,
        **kwargs,
    )


# ==========================================================================
# F-3 — 24칸 요율표
# ==========================================================================

def _parse_excerpt_table() -> list[dict]:
    """실사 발췌의 마크다운 표를 그대로 읽는다. **여기서 값을 만들지 않는다.**"""
    deposit_bounds = {
        "1억원 이하": 100_000_000,
        "1억원 초과 ~ 2억원 이하": 200_000_000,
        "2억원 초과 ~ 5억원 이하": 500_000_000,
        "5억원 초과": None,
    }
    housing_types = {"아파트": "apartment", "기타": "other"}
    debt_ratios = {"70% 이하": 70, "80% 이하": 80, "80% 초과": None}

    rows = []
    for line in EXCERPT_PATH.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] not in deposit_bounds:
            continue
        rate = re.fullmatch(r"연 (\d+\.\d+)%", cells[3])
        assert rate, f"요율 칸의 형식이 바뀌었다: {cells[3]!r}"
        rows.append(
            {
                "depositMaxKRW": deposit_bounds[cells[0]],
                "housingType": housing_types[cells[1]],
                "debtRatioMaxPct": debt_ratios[cells[2]],
                "ratePct": float(rate.group(1)),
            }
        )
    return rows


def test_the_excerpt_actually_holds_24_cells():
    """파서가 표를 못 읽어 0행을 돌려주면 아래 대조가 공허해진다. 먼저 그것부터 막는다."""
    assert len(_parse_excerpt_table()) == 24


def test_the_registry_table_is_the_excerpt_verbatim():
    """★ 레지스트리의 24개 요율이 **원문 발췌와 한 칸도 다르지 않다.**

    이 과업의 가장 큰 위험은 없는 값을 지어내는 것이었다. 「원문 그대로 옮겼다」는
    주장을 사람이 아니라 검사가 붙들게 한다 — 발췌 문서의 표를 파싱해 대조한다.
    """
    def key(row):
        return (row["depositMaxKRW"] or 0, row["housingType"], row["debtRatioMaxPct"] or 0)

    assert sorted(_table(), key=key) == sorted(_parse_excerpt_table(), key=key)


def test_the_dropped_flat_rate_matches_no_cell_in_the_table():
    """0.15 가 표의 어느 칸과도 일치하지 않는다 — 그것이 F-3 의 실사 소견이다."""
    assert DROPPED_FLAT_RATE_PCT not in {row["ratePct"] for row in _table()}


@pytest.mark.parametrize(
    "deposit, expected",
    [
        (0, 0.172),               # 하한 — 보증금 0 도 첫 구간에 든다
        (30_000_000, 0.172),      # 폐기된 하한 3천만 언저리
        (100_000_000, 0.172),     # 1억원 **이하** 경계 포함
        (100_000_001, 0.184),     # 경계 바로 위
        (200_000_000, 0.184),
        (200_000_001, 0.197),
        (500_000_000, 0.197),
        (500_000_001, 0.211),     # 개방 구간
        (5_000_000_000, 0.211),
    ],
)
def test_the_bracket_boundaries_follow_the_published_table(deposit, expected):
    """「이하」/「초과」가 원문 그대로인가. 경계 한 칸이 어긋나면 요율이 통째로 밀린다."""
    assert guarantee_rate_pct_for(deposit, constants=CONSTANTS) == expected


def test_the_lookup_returns_the_bracket_maximum_because_two_axes_are_missing():
    """★ 없는 축을 기본값으로 메우지 않는다 — 그 구간의 **최고요율**을 쓴다.

    주택유형·부채비율은 입력에 없다. 「아파트·부채비율 70% 이하」를 전형으로 가정하면
    요율이 0.097~0.113 이 되어 **폐기된 0.15 보다도 낮아지고**, 보증료가 더 과소계상된다.
    첫 집 지불능력 도구에서 그것이 관대한 방향이다 (계약 결정 #11).
    """
    for bound in (100_000_000, 200_000_000, 500_000_000, None):
        cells = [r["ratePct"] for r in _table() if r["depositMaxKRW"] == bound]
        probe = (bound or 500_000_000) if bound else 600_000_000
        looked_up = guarantee_rate_pct_for(probe, constants=CONSTANTS)
        assert looked_up == max(cells)
        assert looked_up != min(cells), "최저요율(아파트·70% 이하)을 고르면 관대한 방향이다"


def test_every_bracket_charges_more_than_the_dropped_flat_rate():
    """★ 방향 (계약 결정 #11) — 네 구간 모두 0.15 보다 높다. 보증료가 커지는 쪽이다."""
    for deposit in (50_000_000, 150_000_000, 300_000_000, 800_000_000):
        assert guarantee_rate_pct_for(deposit, constants=CONSTANTS) > DROPPED_FLAT_RATE_PCT


def test_an_unknown_lookup_rule_is_refused_rather_than_defaulted():
    """SPEC 5.1.1 fail-closed. 모르는 규칙에 폴백을 두면 그 폴백이 요율을 정한다."""
    constants = dict(CONSTANTS)
    constants["tco.guarantee_rate_unknown_axis_rule"] = "apartment_typical"
    with pytest.raises(ValueError):
        guarantee_rate_pct_for(200_000_000, constants=constants)


def test_the_rate_lookup_rule_is_registered_as_our_choice_not_as_a_published_value():
    """표는 (a) 공시값이고, 칸을 고르는 규칙은 (d) 우리 선택이다. 둘을 섞지 않는다."""
    entries = {e["key"]: e for e in load_registry()["entries"]}
    assert entries["tco.guarantee_rate_table"]["spec_class"] == "a"
    assert entries["tco.guarantee_rate_unknown_axis_rule"]["spec_class"] == "d"


# ==========================================================================
# F-4 — 7억은 「보증한도」가 아니라 「가입 가능한 전세보증금 상한」이다
# ==========================================================================

@pytest.mark.parametrize(
    "code, name, metro",
    [
        ("11440", "서울 마포구", True),
        ("41117", "경기 수원시 영통구", True),
        ("26350", "부산 해운대구", False),
        ("27260", "대구 수성구", False),
        ("12330", "광주 광산구", False),
        ("30200", "대전 유성구", False),
    ],
)
def test_the_deposit_cap_splits_metro_from_the_rest(code, name, metro):
    """원문 가입요건 ② — 수도권 7억 / 그 외 5억.

    이전 구현은 전 지역에 7억을 썼다. 비수도권에 7억을 쓰면 상한을 과대하게 잡아
    「보증금/상한」 비율이 낮게 나오고 위험 가중치가 덜 붙는다 — 관대한 방향이다.
    """
    cap = guarantee_deposit_cap_for({"code": code, "name": name}, constants=CONSTANTS)
    assert cap == (700_000_000 if metro else 500_000_000)


def test_the_risk_factor_is_named_after_what_it_actually_measures():
    """A3-3 이 지적한 「명명이 틀렸다」가 응답 필드에도 그대로 있었다."""
    result = analyze(BASE_PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    names = [f["name"] for f in result["risk"]["factors"]]
    assert "보증금 규모 (가입 가능 상한 대비)" in names
    assert not [n for n in names if "보증 한도" in n], (
        "7억을 「보증 한도」라고 부르는 이름이 남아 있다 — 보증한도는 물건별 산식이다"
    )


def test_the_deposit_share_is_measured_against_the_regional_cap():
    """비수도권은 분모가 5억이다. 같은 보증금이라도 비율이 커진다 — 엄격한 방향."""
    deposit = 150_000_000
    metro = scan_deposit_risk(
        deposit_krw=deposit,
        jeonse_ratio_pct=70.0,
        guarantee_deposit_cap_krw=700_000_000,
        constants=CONSTANTS,
    )
    other = scan_deposit_risk(
        deposit_krw=deposit,
        jeonse_ratio_pct=70.0,
        guarantee_deposit_cap_krw=500_000_000,
        constants=CONSTANTS,
    )

    def share(result):
        return next(
            f["valuePct"] for f in result["factors"] if f["name"].startswith("보증금 규모")
        )

    assert share(metro) == pytest.approx(deposit / 700_000_000 * 100, abs=0.05)
    assert share(other) == pytest.approx(deposit / 500_000_000 * 100, abs=0.05)
    assert share(other) > share(metro)


def test_the_guarantee_limit_formula_is_not_faked():
    """보증한도(주택가격 x 90% - 선순위채권)는 **계산하지 않는다.**

    주택가격도 선순위채권도 입력에 없다. 없는 입력으로 산식을 흉내 내면 그 순간
    (d) 규범적 선택이 되고, 그것을 공시값인 척 두면 Part 0-C 위반이다.
    그래서 레지스트리에 그런 키가 없다는 것을 여기서 붙든다.
    """
    keys = {e["key"] for e in load_registry()["entries"]}
    assert "risk.guarantee_limit_krw" not in keys, "폐기 대상 키가 남아 있다"
    assert not [k for k in keys if "collateral" in k or "prior_lien" in k], (
        "선순위채권이 입력에 없는데 그것을 쓰는 상수가 생겼다"
    )


# ==========================================================================
# F-5 — 3천만 하한은 대응 제도가 없다. 문턱은 상한이다
# ==========================================================================

def test_the_unsourced_lower_bound_is_gone_from_every_key_source():
    """폐기는 코드에서만 하는 것이 아니다 — 레지스트리·조회 목록 양쪽에서 사라져야 한다."""
    for dropped in (
        "tco.guarantee_min_deposit_krw",
        "tco.guarantee_rate_pct",
        "risk.guarantee_limit_krw",
    ):
        assert dropped not in required_constant_keys(), dropped
        assert dropped not in {e["key"] for e in load_registry()["entries"]}, dropped


@pytest.mark.parametrize("deposit", [5_000_000, 10_000_000, 29_999_999])
def test_a_small_deposit_now_pays_a_guarantee_fee(deposit):
    """★ 3천만 미만이라는 이유로 보증료를 빼지 않는다 — 그 하한에 1차 출처가 없다.

    방향 (계약 결정 #11): 보증료가 새로 붙어 총비용이 오른다. 엄격한 쪽이다.
    """
    assert _scenario(deposit_krw=deposit)["components"]["insurance"] > 0


def test_a_deposit_over_the_cap_is_not_insurable_and_both_engines_agree():
    """★ 상한을 넘으면 가입 자체가 안 된다. TCO 와 리스크가 같은 사실을 읽어야 한다.

    TCO 만 고치면 보증료도 안 내고 위험 가중치도 안 붙어 **두 번 관대해진다.**
    """
    cap = 500_000_000
    over = _scenario(deposit_krw=cap + 1, guarantee_deposit_cap_krw=cap)
    within = _scenario(deposit_krw=cap, guarantee_deposit_cap_krw=cap)

    assert within["components"]["insurance"] > 0
    assert over["components"]["insurance"] == 0

    risk_over = scan_deposit_risk(
        deposit_krw=cap + 1,
        jeonse_ratio_pct=70.0,
        guarantee_available=True,
        guarantee_deposit_cap_krw=cap,
        constants=CONSTANTS,
    )
    risk_within = scan_deposit_risk(
        deposit_krw=cap,
        jeonse_ratio_pct=70.0,
        guarantee_available=True,
        guarantee_deposit_cap_krw=cap,
        constants=CONSTANTS,
    )
    guarantee_factor = next(
        f for f in risk_over["factors"] if f["name"] == "보증보험 가입 가능성"
    )
    assert guarantee_factor["valuePct"] == 0.0
    assert guarantee_factor["impact"] == "high"
    assert risk_over["score"] > risk_within["score"], (
        "가입 불가인데 위험 점수가 오르지 않으면 TCO 의 보증료 제외만 남아 관대해진다"
    )


def test_a_zero_deposit_pays_nothing():
    """보증금이 없으면 보증할 것도 없다. 상한 조건이 0 을 통과시키면 안 된다."""
    assert _scenario(deposit_krw=0)["components"]["insurance"] == 0


def test_the_engines_refuse_to_run_without_the_cap():
    """SPEC 5.1.1 fail-closed — 상한에 기본값을 두면 그 기본값이 가입 가능 여부를 정한다."""
    with pytest.raises(TypeError):
        evaluate_scenario(
            "no_cap", "상한 없이", "jeonse",
            100_000_000, 0, 0, 0, 0.0, 0, 1_000_000, 800_000,
            constants=CONSTANTS,
        )
    with pytest.raises(TypeError):
        scan_deposit_risk(deposit_krw=100_000_000, jeonse_ratio_pct=70.0, constants=CONSTANTS)
