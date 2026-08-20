"""감도분석 골격 (SPEC 5.1.3).

**합격선은 "뒤집히지 않는다" 가 아니다. "어디서 뒤집히는지 드러낸다" 이다.**
목적은 통과가 아니라 노출이다 — Part 0-C 가 인용한 SR 11-7 의 "모든 기저 가정을
문서화·정당화한다" 와 같은 취지다. 그래서 이 모듈은 임계도 합격선도 두지 않고 표만 만든다.

산출물: **(d) 상수 × 교란폭 × 판정이 달라진 사례 비율**.

── 교란폭의 선택 자체가 (d) 다 ──────────────────────────────────────────
±5% 와 ±20% 를 쓴다. **준거는 없다. 우리 선택이다.**
왜 둘인가는 SPEC 5.1.3 이 "최소 두 개(작은 폭·큰 폭)" 로 정했기 때문이고,
왜 하필 5 와 20 인가에는 답이 없다. 다른 폭을 고르면 아래 표의 숫자가 달라진다.
그 사실을 감추지 않기 위해 폭을 표 머리에 적고, 표를 근거로 "안정적이다" 라고
주장하지 않는다. 이 선택은 값이 확정되는 1-② 에서 재검토 대상이다.

── 대상 사례 모집단 ────────────────────────────────────────────────────
`contracts/regression_profiles.json` (setVersion 1.0.0). **계약이므로 코디네이터만 바꾸고,
바꾸면 이 표와 골든을 함께 재생성한다** (SPEC 9.2.2 · 8.2).

SPEC 9.2.2 가 명시한 넷(0소득·초고소득·연령 경계·없는 지역)에 더해, 실측으로 분기가
열리는 것을 확인한 다섯을 넣었다 — 비수도권 상한(F-4) · 보증불가+고위험 · 수도권 비서울
접두 · 전세 규모 상단 · 4인 가구 생활비. 각 항목이 무엇을 여는지는 그 파일의 `axes` 에
실측치와 함께 적혀 있다.

**그래도 이 표로 커버리지를 주장하지 않는다.** 덮이지 않는 것은 같은 파일의
`$uncovered` 에 적혀 있다 (특히 `tco.fallback_conversion_rate_pct` 는 프로필로 덮을 수 없다).

사람이 돌릴 때:  python backend/tests/sensitivity.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------
# 단독 실행 — 세션 저장소를 **conftest 와 같은 방식으로** 시드한다
# --------------------------------------------------------------------------
#
# 아래 `REGIONS` · `POLICIES` 는 저장소에서 읽는다 (`decision_inputs.py`). pytest 밖에서는
# 그 저장소를 시드하는 `conftest.py` 가 돌지 않으므로 `FIRSTHOME_STORE_URL` 이 없는 채로
# 기본 경로(`backend/var/firsthome.db`)가 열리고, 지역 0건 · 정책 0건이 된다. 그러면 모든
# 프로필이 [없는 지역]으로 거부되어 사례가 0건이 되고 비율 계산이 0 으로 나눈다 —
# `test_sensitivity` 의 오류 메시지가 **재생성 방법으로 안내하는 명령**이 그렇게 죽었다.
#
# 시드 절차를 여기 베끼지 않고 `conftest` 를 그대로 import 하는 이유는 편의가 아니다.
# 커밋된 산출물은 `test_sensitivity.test_committed_artifact_matches_a_fresh_run` 이
# **pytest 안에서** 재생성한 것과 비교된다. 재생성 경로가 다른 저장소를 읽으면 두 표가
# 어긋나고, 최악은 빈 저장소로 재생성해 산출물이 통째로 비는 것이다. 같은 모듈을 부르면
# 그 어긋남이 원천적으로 불가능하다.
#
# `conftest` 는 `FIRSTHOME_STORE_URL` 을 **덮어쓴다.** 그것이 맞다 — 재생성은 시드된
# 저장소 안에서만 성립하고, 다른 저장소로 만든 표는 위 테스트가 곧바로 거부한다.
if __name__ == "__main__":
    import conftest  # noqa: F401  (import 자체가 임시 저장소 시드다)

from firsthome.engines import analyze as _analyze  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed, load_registry  # noqa: E402
from snapshot_util import dumps, load_profiles, split_snapshot  # noqa: E402


def analyze(profile: dict, *, constants):
    """감도분석의 축은 **상수 하나**다. 지역·정책·시각은 고정한다.

    SPEC 2.3 컷오버로 엔진이 지역·정책도 주입받게 됐지만, 그 둘을 여기서 흔들면 표의
    한 칸이 무엇 때문에 움직였는지 말할 수 없게 된다 (SPEC 5.1.3 의 목적은 통과가
    아니라 노출이다). 매 호출 저장소를 다시 읽지 않는 것도 같은 이유다 — 표 한 장이
    수천 번 판정하는데 그 사이에 입력이 바뀌면 표가 자기 자신과 어긋난다.

    클럭(SPEC 5.3)도 같은 이유로 고정한다. 여기서 시계를 읽으면 `_number_signature` 가
    매 호출 달라져 **모든 행이 「숫자 이동 100%」** 가 된다 — 상수가 아니라 시각이 움직인
    것인데 표는 그것을 상수 탓으로 적게 된다.
    """
    return _analyze(
        profile, constants=constants, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW
    )


REGIONS = store_regions()
POLICIES = store_policies(FROZEN_NOW)

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "sensitivity.md"

# 교란폭. 이 선택 자체가 (d) — 모듈 docstring 참조.
PERTURBATIONS = (("작은 폭", 0.05), ("큰 폭", 0.20))

# ==========================================================================
# 정의역 — 교란값이 상수가 **가질 수 없는 값**이 되는 지점
#
# 왜 필요한가. `affordability.recommended_haircut` 은 0.85 이고 +20% 는 1.02 다.
# 1.02 는 안전마진이 가질 수 없는 값이다 — 상한의 102%를 권장한다는 뜻이 되고
# `recommended <= max` (SPEC 5.3)가 깨진다. 그런데 **클램프도 답이 아니다.**
# 1.0 으로 잘라 놓고 표에 「+20% 교란」이라고 적으면 실제로는 +17.6% 를 교란한
# 것이므로 표가 스스로 거짓말한다. 그래서 자르지도 채우지도 않고 `[정의역 밖]`
# 이라고 적는다. **「이 상수는 위로 20% 교란할 여지가 없다」는 것 자체가 정보다**
# — SPEC 5.1.3 의 목적은 통과가 아니라 노출이다.
#
# ── 불변식 검사와의 구분 (중요) ─────────────────────────────────────────
# `recommended <= max` 같은 불변식은 **프로덕션 경로에만** 건다
# (`test_schwabe_and_recommendation.py::test_recommended_never_exceeds_max`).
# 이 하네스는 일부러 비현실적인 값을 넣어 보는 곳이므로 여기서 불변식이 깨지는
# 것은 결함이 아니라 **하네스가 하는 일 그 자체**다. 그래서 여기에는 불변식
# assert 를 걸지 않고, 대신 그 값이 정의역 밖이라는 사실을 표에 드러낸다.
#
# ── 표기 ────────────────────────────────────────────────────────────────
# (low, low_inclusive, high, high_inclusive, 근거)
#   · `None` = 그 방향으로 경계가 없다
#   · 문자열 = **다른 상수 키**. 순서가 의미를 지는 구간 경계·가중치 계열은
#     이웃과의 순서가 곧 정의역이다. 80% 문턱이 90% 문턱을 넘으면 그 구간은
#     도달 불가능해지는데, 그것은 「값이 좀 움직였다」가 아니라 밴드 하나가
#     사라지는 일이다.
# ==========================================================================

DOMAINS: dict[str, tuple] = {
    # --- affordability -----------------------------------------------------
    "affordability.housing_cost_ratio_cap":
        (0, False, 1, True, "소득 대비 주거비 상한 비중. 0 이면 상한이 0 이라 판정이 성립하지 않고, 1 초과는 소득 전액을 넘는 주거비를 허용한다는 뜻이다."),
    "affordability.recommended_haircut":
        (0, False, 1, True, "상한에 곱하는 안전마진. 1 초과면 권장액이 상한을 넘어 SPEC 5.3 의 `recommended <= max` 가 깨진다."),
    "affordability.buffer_ratio":
        (0, True, 1, False, "소득에서 떼는 비상자금 비중. 1 이상이면 잔여여력이 항상 음수가 된다. 0 은 「버퍼를 두지 않는다」로 성립한다."),
    "affordability.safe_cap_ratio":
        ("affordability.caution_cap_ratio", True, 1, True, "상한/소득 비율과 비교되는 safe 문턱. 상한은 소득을 넘지 못하므로 1 초과는 도달 불가능하고, caution 문턱 아래로 내려오면 밴드 순서가 뒤집힌다."),
    "affordability.caution_cap_ratio":
        (0, False, "affordability.safe_cap_ratio", True, "같은 축의 완화 문턱. safe 문턱을 넘어서면 caution 이 safe 보다 엄격해져 밴드 순서가 뒤집힌다."),
    "affordability.safe_debt_ratio":
        (0, False, "affordability.caution_debt_ratio", True, "부채상환/소득 safe 문턱. caution 문턱을 넘으면 caution 구간이 사라진다."),
    "affordability.caution_debt_ratio":
        ("affordability.safe_debt_ratio", True, 1, True, "부채상환/소득 caution 문턱. 1 초과는 소득 전액을 넘는 상환을 주의 구간으로 보겠다는 뜻이다."),
    # --- eligibility -------------------------------------------------------
    "eligibility.boundary_margin":
        (0, True, 1, False, "경계 근접 판정 폭. 1 이상이면 모든 값이 경계 근처가 되어 판정이 무의미해진다."),
    "eligibility.age_cap_imminent_years":
        (0, True, None, False, "연령 상한 임박 경고 폭(년). 음수는 이미 지난 나이를 임박으로 부르는 것이다."),
    "eligibility.age_max_unlimited_sentinel":
        (120, False, None, False, "「연령 제한 없음」 센티널. `ProfileRequest.age` 의 상한이 120 이므로 그 이하로 내려오면 센티널이 실제 나이와 충돌한다."),
    "eligibility.amount_unlimited_sentinel_krw":
        (0, False, None, False, "「한도 없음」 센티널(원). 실제 어떤 상품 한도보다도 커야 의미가 있다."),

    # --- engines (비수치) ---------------------------------------------------
    "engines.jeonse_loan_priority":
        (None, False, None, False, "정책 ID 순서열. 수치가 아니므로 곱셈 교란의 정의역이 없다 — 교란 가능한 축은 순서 자체이며 이 표의 축이 아니다."),
    "engines.monthly_loan_priority":
        (None, False, None, False, "정책 ID 순서열. 위와 같이 수치가 아니므로 곱셈 교란의 정의역이 없다."),

    # --- risk: 밴드 경계 ----------------------------------------------------
    "risk.band_low_max":
        (0, True, "risk.band_medium_max", False, "0~100 점수 척도의 low/medium 경계. medium 경계를 넘으면 medium 밴드가 사라진다."),
    "risk.band_medium_max":
        ("risk.band_low_max", False, 100, True, "medium/high 경계. 100 을 넘으면 점수가 클램프되어 high 밴드가 도달 불가능해진다."),

    # --- risk: 노출 규모 ----------------------------------------------------
    "risk.low_exposure_krw":
        ("risk.minimal_exposure_krw", False, None, False, "소액 완화가 끝나는 보증금(원). minimal 문턱 아래로 내려오면 두 문턱의 순서가 뒤집힌다."),
    "risk.minimal_exposure_krw":
        (0, False, "risk.low_exposure_krw", False, "최소 노출 문턱(원). 0 이하면 보증금 0 도 완화 대상이 된다."),
    "risk.exposure_multiplier_low":
        ("risk.exposure_multiplier_minimal", True, 1, True, "완화 계수. 1 초과면 완화가 아니라 가중이 되고, minimal 계수보다 작으면 소액일수록 위험이 커진다."),
    "risk.exposure_multiplier_minimal":
        (0, False, "risk.exposure_multiplier_low", True, "최소 노출 구간의 완화 계수. 0 이면 위험 요인이 통째로 사라진다."),

    # --- risk: 전세가율 -----------------------------------------------------
    "risk.jeonse_ratio_threshold_1":
        (0, False, "risk.jeonse_ratio_threshold_2", False, "전세가율 구간 경계(%). 이웃 경계를 넘으면 그 사이 구간이 도달 불가능해진다."),
    "risk.jeonse_ratio_threshold_2":
        ("risk.jeonse_ratio_threshold_1", False, "risk.jeonse_ratio_threshold_3", False, "전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다."),
    "risk.jeonse_ratio_threshold_3":
        ("risk.jeonse_ratio_threshold_2", False, "risk.jeonse_ratio_threshold_4", False, "전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다."),
    "risk.jeonse_ratio_threshold_4":
        ("risk.jeonse_ratio_threshold_3", False, None, False, "최상위 경계(%). 전세가율은 100 을 넘을 수 있으므로(깡통전세) 위쪽 경계는 두지 않는다."),
    "risk.jeonse_ratio_weight_1":
        (0, True, "risk.jeonse_ratio_weight_2", True, "구간 가중치(점). 전세가율이 높을수록 위험이 크다는 단조성이 깨지면 요인 자체가 뒤집힌다."),
    "risk.jeonse_ratio_weight_2":
        ("risk.jeonse_ratio_weight_1", True, "risk.jeonse_ratio_weight_3", True, "구간 가중치(점). 이웃 구간 사이여야 「전세가율이 높을수록 위험하다」가 유지된다."),
    "risk.jeonse_ratio_weight_3":
        ("risk.jeonse_ratio_weight_2", True, "risk.jeonse_ratio_weight_4", True, "구간 가중치(점). 이웃 구간 사이여야 「전세가율이 높을수록 위험하다」가 유지된다."),
    "risk.jeonse_ratio_weight_4":
        ("risk.jeonse_ratio_weight_3", True, "risk.jeonse_ratio_weight_5", True, "구간 가중치(점). 이웃 구간 사이여야 「전세가율이 높을수록 위험하다」가 유지된다."),
    "risk.jeonse_ratio_weight_5":
        ("risk.jeonse_ratio_weight_4", True, 100, True, "최고 구간 가중치(점). 단일 요인이 100 점을 넘으면 다른 요인이 점수에 영향을 못 준다."),

    # --- risk: 대출 비중 ----------------------------------------------------
    "risk.loan_share_threshold_1":
        (0, True, "risk.loan_share_threshold_2", False, "보증금 내 대출비중 구간 경계(%). 이웃을 넘으면 구간이 사라진다."),
    "risk.loan_share_threshold_2":
        ("risk.loan_share_threshold_1", False, "risk.loan_share_threshold_3", False, "대출비중 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다."),
    "risk.loan_share_threshold_3":
        ("risk.loan_share_threshold_2", False, 100, True, "최상위 경계(%). 대출비중은 보증금을 넘을 수 없으므로 100 이 상한이다."),
    "risk.loan_share_weight_2":
        (0, True, "risk.loan_share_weight_3", True, "구간 가중치(점). 대출비중이 클수록 위험이 크다는 단조성이 정의역이다."),
    "risk.loan_share_weight_3":
        ("risk.loan_share_weight_2", True, "risk.loan_share_weight_4", True, "구간 가중치(점). 이웃 구간 사이여야 「대출비중이 클수록 위험하다」가 유지된다."),
    "risk.loan_share_weight_4":
        ("risk.loan_share_weight_3", True, 100, True, "위와 같고, 단일 요인이 100 점을 넘을 수 없다."),

    # --- risk: 보증금 규모 --------------------------------------------------
    "risk.deposit_size_threshold_1":
        (0, False, "risk.deposit_size_threshold_2", False, "가입 가능 상한 대비 보증금 비율 경계(%). 이웃을 넘으면 구간이 사라진다."),
    "risk.deposit_size_threshold_2":
        ("risk.deposit_size_threshold_1", False, 100, True, "상한 대비 100% 를 넘으면 그 구간은 이미 가입 불가 영역이라 문턱으로서 의미가 없다."),
    "risk.deposit_size_weight_2":
        (0, True, "risk.deposit_size_weight_3", True, "구간 가중치(점). 상한에 가까울수록 위험이 크다는 단조성이 정의역이다."),
    "risk.deposit_size_weight_3":
        ("risk.deposit_size_weight_2", True, 100, True, "위와 같고, 단일 요인이 100 점을 넘을 수 없다."),

    # --- risk: 시장 · 보증 --------------------------------------------------
    "risk.market_weight_medium":
        (0, True, "risk.market_weight_high", True, "시장 위험 가중치(점). high 를 넘으면 medium 이 high 보다 위험해진다."),
    "risk.market_weight_high":
        ("risk.market_weight_medium", True, 100, True, "위와 같고, 단일 요인이 100 점을 넘을 수 없다."),
    "risk.market_value_pct_low":
        (0, True, "risk.market_value_pct_medium", True, "응답에 그대로 실리는 표시값(%). 0~100 밖이면 백분율이 아니고, 순서가 뒤집히면 low 가 medium 보다 나쁘게 보인다."),
    "risk.market_value_pct_medium":
        ("risk.market_value_pct_low", True, "risk.market_value_pct_high", True, "응답에 그대로 실리는 표시값(%). 순서가 뒤집히면 medium 이 high 보다 나쁘게 보인다."),
    "risk.market_value_pct_high":
        ("risk.market_value_pct_medium", True, 100, True, "응답에 그대로 실리는 표시값(%). 100 을 넘으면 백분율이 아니게 된다."),
    "risk.guarantee_unavailable_weight":
        (0, True, 100, True, "보증 미가입 가중치(점). 단일 요인이 100 점을 넘으면 다른 요인이 점수에 영향을 못 준다."),
    "risk.guarantee_small_deposit_multiplier":
        (0, True, 1, True, "소액 보증금의 완화 계수. 1 초과면 완화가 아니라 가중이 된다."),

    # --- tco ---------------------------------------------------------------
    "tco.horizon_years":
        (0, False, None, False, "비교 기간(년). 0 이하면 총비용이 0 이 되어 네 시나리오가 구분되지 않는다."),
    "tco.fit_afford_weight":
        (0, True, 100, True, "적합도 배점(점). 100 을 넘으면 단일 축이 fitScore 전부를 차지한다."),
    "tco.fit_afford_overrun_slope":
        (0, True, None, False, "초과분 1배당 깎는 점수. 음수면 예산을 넘길수록 적합도가 올라간다."),
    "tco.fit_capital_weight":
        (0, True, 100, True, "적합도 배점(점). 100 을 넘으면 자기자본 축 하나가 fitScore 전부를 차지한다."),
    "tco.fit_preference_match_score":
        ("tco.fit_preference_mismatch_score", True, 100, True, "선호 일치 가점. 불일치 점수보다 낮아지면 선호를 어길수록 유리해진다."),
    "tco.fit_preference_mismatch_score":
        (0, True, "tco.fit_preference_match_score", True, "선호 불일치 점수. 일치 가점을 넘으면 선호를 어길수록 유리해진다."),
    "tco.semi_jeonse_deposit_share":
        (0, False, 1, False, "반전세의 보증금 비중. 1 이면 전세와, 0 이면 순월세와 같아져 시나리오가 중복된다."),
    "tco.low_deposit_scenario_deposit_krw":
        (0, True, None, False, "저보증금 시나리오의 보증금(원). 음수 보증금은 없다."),
    "tco.deposit_rounding_unit_krw":
        (1, True, None, False, "반올림 단위(원). `floor_to` 의 제수이므로 1 미만이면 단위가 성립하지 않는다."),
    "tco.monthly_rounding_unit_krw":
        (1, True, None, False, "월 환산액의 반올림 단위(원). `floor_to` 의 제수이므로 1 미만이면 단위가 성립하지 않는다."),
    "tco.guarantee_rate_unknown_axis_rule":
        (None, False, None, False,
         "요율표에서 칸을 고르는 규칙의 이름. 열거형이라 곱셈 교란의 정의역이 없다 — 교란 가능한 "
         "축은 규칙 자체이며(`bracket_max` 대 「아파트·70% 이하 가정」) 그것은 폭이 아니라 "
         "선택지다. 생활비 정의 3안처럼 별도 절에 세울 후보다."),

    # --- extraction (비엔진 · 판정 경로 밖) ---------------------------------
    # 이 절은 판정에 영향이 없다. 그래도 표에 싣는 이유는 SPEC Part 0-E #4 가 (d) 운영
    # 임계를 ModelConstant 로 등재해 감도분석 대상에 포함시키라고 했기 때문이다.
    #
    # ★ 실제로 표에는 [교란 불가]가 찍힌다. [판정 변화 0]이 아니다. 값 2 에 ±5%·±20% 를
    #   곱해도 정수 한 칸을 못 넘어 `_perturb` 가 None 을 돌려주기 때문이다. 그 분기가
    #   0% 로 보고하기를 거부하는 이유가 여기 그대로 적용된다 — 교란이 성립하지 않은 것과
    #   교란했는데 안 바뀐 것은 다른 사실이고, 둘을 같은 칸에 적으면 표가 거짓말을 한다.
    #   이 상수가 판정 경로 밖이라는 사실은 표가 아니라 계약의 engineConsumers 가 말한다.
    "extraction.max_attempts":
        (1, True, None, False,
         "추출 1건의 시도 횟수 상한(최초 호출 포함). 1 미만이면 한 번도 시도하지 않는다는 "
         "뜻이라 파이프라인이 성립하지 않는다. 정수이며 `_perturb` 가 정수성을 지킨다."),

    # --- ingest.market (비엔진 · 판정 경로 밖) -------------------------------
    # 위 extraction 절과 같은 이유로 표에 실린다 (Part 0-E #4). 배치가 저장소에 넣은
    # **값**은 판정을 바꾸지만, 이 상수들은 [무엇을 어떻게 모을 것인가]를 정할 뿐
    # 이미 저장된 값에는 작용하지 않는다. 그래서 판정 변화가 0 으로 나온다.
    # 통계마다 산포가 달라 배수를 나눴다 (사용자 결정 2026-08-14). 정의역은 넷 다 같다 —
    # 1 이하면 중앙값 자신이 이상치가 되어 규칙이 성립하지 않는다.
    "ingest.market_outlier_ratio_jeonse":
        (1, True, None, False, "전세 보증금의 중앙값 대비 배수. 1 이하면 규칙이 성립하지 않는다."),
    "ingest.market_outlier_ratio_monthly_deposit":
        (1, True, None, False, "월세 보증금의 중앙값 대비 배수. 1 이하면 규칙이 성립하지 않는다."),
    "ingest.market_outlier_ratio_monthly_rent":
        (1, True, None, False, "월세의 중앙값 대비 배수. 1 이하면 규칙이 성립하지 않는다."),
    "ingest.market_outlier_ratio_trade":
        (1, True, None, False, "매매 거래금액의 중앙값 대비 배수. 1 이하면 규칙이 성립하지 않는다."),
    "ingest.market_outlier_share_threshold":
        (0, False, 1, True,
         "지역을 unverified 로 볼 이상치 비율 문턱. 0 이하면 항상 걸리고 1 초과는 도달 불가능하다."),
    "ingest.market_min_sample_count":
        (1, True, None, False,
         "표본 최소 건수. 1 미만이면 표본이 0건이어도 통계로 취급하겠다는 뜻이다. "
         "짝이 성립한 셀 수에도 같은 문턱이 걸린다 (SPEC 3.1 3차 정정)."),
    # 파생 비율 2종을 [비의 중앙값] 으로 내면서 들어온 셀 정의의 자유도다 (결정 #35).
    # 자유도를 하나 만들지만 **그 자유도가 결과를 지배하지 않는다는 것을 실측했다** —
    # 1제곱미터와 5제곱미터에서 값의 최대 이동이 0.12%p(전환율) · 0.46%p(전세가율)였다
    # (FINDINGS-6.md B5). 그래도 표에는 다른 (d) 와 같은 자격으로 실린다.
    "ingest.market_pair_area_band_sqm":
        (0, False, "ingest.market_max_exclusive_area_sqm", False,
         "셀을 만드는 전용면적 구간의 폭(제곱미터). 0 이하면 폭이 없어 구간이 성립하지 "
         "않고(반올림에서 0 으로 나눈다), 전용면적 상한 이상이면 모든 거래가 한 구간에 "
         "들어가 셀에서 면적 축이 사라진다 — 법정동+단지명만으로 짝지은 것이 되어 "
         "같은 단지의 59제곱미터와 84제곱미터가 한 셀이 된다."),
    "ingest.market_lookback_months":
        (1, True, None, False,
         "집계 대상 개월 수. 1 미만이면 집계할 기간이 없다."),
    "ingest.market_max_exclusive_area_sqm":
        (0, False, None, False,
         "전용면적 상한(제곱미터). 0 이하면 어떤 거래도 통과하지 못한다."),
    "ingest.market_max_attempts":
        (1, True, None, False,
         "수집 1회의 시도 횟수 상한(최초 호출 포함). 1 미만이면 한 번도 시도하지 않는다."),
    "ingest.market_request_timeout_seconds":
        (0, False, None, False,
         "호출 1건의 대기 상한(초). 0 이하면 즉시 포기라 호출이 성립하지 않는다."),
    "ingest.market_batch_deadline_seconds":
        (0, False, None, False,
         "배치 전체의 실행 상한(초). 0 이하면 배치가 시작하자마자 끝난다."),

    # --- auth (비엔진 · 판정 경로 밖) ---------------------------------------
    # 세션 수명은 [누가 화면을 얼마나 오래 열어 둘 수 있는가]를 정할 뿐 판정 숫자에
    # 작용하지 않는다. 그래서 판정 변화가 0 으로 나온다.
    "auth.session_idle_timeout_seconds":
        (0, False, "auth.session_absolute_timeout_seconds", True,
         "유휴 만료(초). 0 이하면 즉시 만료라 로그인이 성립하지 않고, 절대 만료를 넘으면 "
         "유휴 만료가 도달 불가능해져 두 종류를 둔 의미가 사라진다."),
    "auth.session_absolute_timeout_seconds":
        ("auth.session_idle_timeout_seconds", True, None, False,
         "절대 만료(초). 유휴 만료보다 짧으면 유휴 쪽이 죽은 값이 된다."),
}


def _bound(spec, baseline: dict):
    """경계값 해석. 문자열이면 다른 상수 키를 가리킨다."""
    if spec is None:
        return None
    if isinstance(spec, str):
        return baseline[spec]
    return spec


def in_domain(key: str, value, baseline: dict) -> bool:
    low, low_inc, high, high_inc, _ = DOMAINS[key]
    lo, hi = _bound(low, baseline), _bound(high, baseline)
    if lo is not None and (value < lo if low_inc else value <= lo):
        return False
    if hi is not None and (value > hi if high_inc else value >= hi):
        return False
    return True


def describe_domain(key: str, baseline: dict) -> str:
    low, low_inc, high, high_inc, reason = DOMAINS[key]
    lo, hi = _bound(low, baseline), _bound(high, baseline)
    left = "(-∞" if lo is None else f"{'[' if low_inc else '('}{lo:g}"
    right = "∞)" if hi is None else f"{hi:g}{']' if high_inc else ')'}"
    return f"{left}, {right} — {reason}"

# ==========================================================================
# 정의 선택 민감도 — (d) 표와 별개의 산출물
#
# **일반 규칙: (b)(c) 라도 도출에 우리 선택이 끼면 그 선택은 노출 대상이다.**
# 값이 공표값이라는 것이 도출까지 공표됐다는 뜻은 아니다.
#
# `affordability.living_cost_by_household` 가 정확히 그 경우다. 값은 가계동향조사
# 공표값의 뺄셈이라 (b) verified 이지만, **무엇을 뺄지**는 우리가 골랐다. 그래서 이
# 상수는 (d) 표에 들어가지 않고(5.1.3 은 (d) × 교란폭이다) 여기에 따로 선다.
#
# 아래 숫자는 전부 FINDINGS-3.md 7.3 의 공표값이다 (KOSIS 101/DT_1L9U105,
# 2025년 연간 · 전국 1인이상 · 전체가구, 원 단위). 우리가 만든 값은 하나도 없고,
# 세 정의는 같은 공표값에서 무엇을 빼느냐만 다르다.
PUBLISHED_2025 = {
    #        소비지출,   04.주거·수도·광열,  실제주거비,  기타주거관련서비스
    1: (1_757_319, 324_417, 177_494, 49_052),
    2: (2_710_796, 331_514, 90_805, 66_146),
    3: (3_884_655, 402_143, 102_786, 90_998),
    4: (4_786_967, 443_057, 102_838, 105_979),
}

LIVING_COST_DEFINITIONS = (
    (
        "주거·수도·광열 전액 차감",
        "기각. 연료비·상하수도까지 빼면 그 지출이 생활비에도 주거비에도 없는 상태가 된다 "
        "— 가구는 실제로 내는데 모델 어디에도 없어 잔여여력이 과대계상된다.",
        lambda spend, total, rent, svc: spend - total,
    ),
    (
        "실제주거비 + 기타주거관련서비스  ★ 채택",
        "모델이 주거비로 세는 항목만 뺀다 (tco.py 의 rent · maintenance). 계약 결정 #11.",
        lambda spend, total, rent, svc: spend - rent - svc,
    ),
    (
        "실제주거비만 차감",
        "기각. 공동주택관리비를 생활비에 남기면 region.maintenanceFeeKRW 와 이중계상된다.",
        lambda spend, total, rent, svc: spend - rent,
    ),
)


def normative_keys() -> list[str]:
    """레지스트리에서 (d) 규범적 선택만 고른다. 감도분석의 대상은 (d) 다 (SPEC 5.1.3)."""
    return [e["key"] for e in load_registry()["entries"] if e["spec_class"] == "d"]


def _decision_signature(result: dict) -> str:
    """판정 = 범주형 결론. 숫자가 조금 움직이는 것과 결론이 뒤집히는 것은 다르다."""
    return dumps(
        {
            "affordability.band": result["affordability"]["band"],
            "scenarios.ranking": [s["id"] for s in result["scenarios"]],
            "scenarios.verdict": {s["id"]: s["verdict"] for s in result["scenarios"]},
            "policies.status": {p["id"]: p["status"] for p in result["policies"]},
            "risk.band": result["risk"]["band"],
        }
    )


def _number_signature(result: dict) -> str:
    numeric, _ = split_snapshot(result)
    return dumps(numeric)


def _perturb(value, factor: float):
    """수치만 교란한다. 비수치 상수는 None 을 돌려 표에 '교란 불가' 로 적는다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    moved = value * (1 + factor)
    if isinstance(value, int):
        moved = int(round(moved))
        if moved == value:
            return None  # 교란폭이 정수 한 칸을 못 넘었다. 0% 로 보고하면 거짓말이 된다.
    return moved


def _cases():
    """예외를 던지는 축(없는 지역)은 상수와 무관하게 항상 거부되므로 모집단에서 뺀다."""
    constants = frozen_seed()
    usable, refused = [], []
    for case in load_profiles():
        try:
            analyze(case["profile"], constants=constants)
        except ValueError as exc:
            refused.append(f"{case['id']}: {exc}")
            continue
        usable.append(case)
    if not usable:
        # **0 으로 나누지 않는다.** 사례가 0건이면 비율의 분모가 0 이고, 예전에는 여기가
        # `ZeroDivisionError` 로 죽어 원인을 하나도 말해 주지 않았다. 무엇이 없어서 못
        # 도는지를 세 숫자로 말한다 — 프로필은 있는데 지역·정책이 0건이면 저장소가
        # 시드되지 않은 것이다.
        raise RuntimeError(
            "감도분석 사례가 0건이다 — 표를 만들 수 없다.\n"
            f"  프로필 {len(load_profiles())}건 · 저장소 지역 {len(REGIONS)}건 · "
            f"활성 정책 {len(POLICIES)}건\n"
            "  전부 거부됨:\n    " + "\n    ".join(refused) + "\n"
            "  지역이 0건이면 저장소가 시드되지 않은 것이다. 이 모듈은 pytest 의 "
            "`conftest.py` 가 시드한 세션 저장소를 읽으며, 단독 실행일 때는 "
            "`__main__` 에서 같은 conftest 를 import 해 임시 저장소를 시드한다. "
            "이 모듈을 다른 진입점에서 import 했다면 그 경로에는 시드가 없다."
        )
    return usable


def build_table() -> dict:
    """(d) 상수 × 교란폭 × 판정이 달라진 사례 비율."""
    baseline_constants = frozen_seed()
    cases = _cases()
    baseline = {
        case["id"]: (
            _decision_signature(analyze(case["profile"], constants=baseline_constants)),
            _number_signature(analyze(case["profile"], constants=baseline_constants)),
        )
        for case in cases
    }

    rows = []
    for key in normative_keys():
        for width_label, width in PERTURBATIONS:
            for direction, sign in (("-", -1.0), ("+", 1.0)):
                moved = _perturb(baseline_constants[key], sign * width)
                if moved is None:
                    rows.append(
                        {
                            "constant": key,
                            "width": f"{direction}{int(width * 100)}% ({width_label})",
                            "decision_flipped": None,
                            "numbers_moved": None,
                            "out_of_domain": False,
                            "note": "교란 불가 — 비수치이거나 폭이 값을 움직이지 못함",
                        }
                    )
                    continue
                # 정의역 밖이면 **숫자를 만들지 않는다.** 클램프하면 표가 적은 교란폭과
                # 실제 교란폭이 갈리고, 그 순간 표가 스스로 거짓말한다. 모듈 상단 주석 참조.
                if not in_domain(key, moved, baseline_constants):
                    rows.append(
                        {
                            "constant": key,
                            "width": f"{direction}{int(width * 100)}% ({width_label})",
                            "decision_flipped": None,
                            "numbers_moved": None,
                            "out_of_domain": True,
                            "note": (
                                f"교란값 {moved:g} 이 정의역 "
                                f"{describe_domain(key, baseline_constants)}"
                            ),
                        }
                    )
                    continue
                constants = dict(baseline_constants)
                constants[key] = moved
                flipped = moved_numbers = 0
                for case in cases:
                    result = analyze(case["profile"], constants=constants)
                    base_decision, base_numbers = baseline[case["id"]]
                    if _decision_signature(result) != base_decision:
                        flipped += 1
                    if _number_signature(result) != base_numbers:
                        moved_numbers += 1
                rows.append(
                    {
                        "constant": key,
                        "width": f"{direction}{int(width * 100)}% ({width_label})",
                        "decision_flipped": flipped / len(cases),
                        "numbers_moved": moved_numbers / len(cases),
                        "out_of_domain": False,
                        "note": "",
                    }
                )
    return {"caseCount": len(cases), "caseIds": [c["id"] for c in cases], "rows": rows}


def build_definition_table() -> dict:
    """생활비 「무엇을 뺄지」 정의 3안 × 판정이 달라진 사례 비율.

    (d) 표와 달리 교란폭이 없다 — 폭이 아니라 **정의 선택지 자체**가 축이다.
    임의의 ±% 가 아니라 실제로 고를 수 있었던 세 가지다.
    """
    baseline_constants = frozen_seed()
    cases = _cases()
    adopted = baseline_constants["affordability.living_cost_by_household"]
    baseline = {
        case["id"]: (
            _decision_signature(analyze(case["profile"], constants=baseline_constants)),
            _number_signature(analyze(case["profile"], constants=baseline_constants)),
        )
        for case in cases
    }

    rows = []
    for label, note, rule in LIVING_COST_DEFINITIONS:
        values = {size: rule(*parts) for size, parts in PUBLISHED_2025.items()}
        constants = dict(baseline_constants)
        constants["affordability.living_cost_by_household"] = values
        flipped = moved = 0
        for case in cases:
            result = analyze(case["profile"], constants=constants)
            base_decision, base_numbers = baseline[case["id"]]
            if _decision_signature(result) != base_decision:
                flipped += 1
            if _number_signature(result) != base_numbers:
                moved += 1
        rows.append(
            {
                "label": label,
                "note": note,
                "values": values,
                "is_adopted": values == adopted,
                "decision_flipped": flipped / len(cases),
                "numbers_moved": moved / len(cases),
            }
        )
    return {"caseCount": len(cases), "rows": rows}


def render_definition_section(table: dict) -> list[str]:
    lines = [
        "## 정의 선택 민감도 — **위 (d) 표와 별개의 산출물이다**",
        "",
        "이 절은 (d) 상수 × 교란폭 표가 **아니다.** 대상은 `affordability.living_cost_by_household`",
        "하나이고, 축은 교란폭이 아니라 **「무엇을 뺄지」의 정의 선택지**다.",
        "",
        "**일반 규칙 — (b)(c) 라도 도출에 우리 선택이 끼면 그 선택은 노출 대상이다.**",
        "값이 공표값이라는 것이 도출까지 공표됐다는 뜻은 아니다. 이 상수의 값은 가계동향조사",
        "공표값의 뺄셈이라 `(b) verified` 이지만, 소비지출에서 **무엇을 뺄지는 우리가 골랐다.**",
        "그래서 (d) 표에는 넣지 않고(SPEC 5.1.3 은 (d) × 교란폭이다) 여기에 따로 세운다.",
        "",
        "- 기준선은 채택안이다. 「판정 뒤집힘」·「숫자 이동」은 채택안 대비 비율이다.",
        f"- 사례 모집단: {table['caseCount']}건. 위 표와 같은 세트이며 커버리지를 주장하지 않는다.",
        "- 세 안의 숫자는 전부 `FINDINGS-3.md` 7.3 의 공표값이다 (KOSIS `101/DT_1L9U105`,",
        "  2025년 연간 · 전국 1인이상 · 전체가구). **같은 공표값에서 빼는 항목만 다르다.**",
        "",
        "| 정의 | 1인 | 2인 | 3인 | 4인 | 판정 뒤집힘 | 숫자 이동 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in table["rows"]:
        cells = " | ".join(f"{row['values'][s]:,}" for s in (1, 2, 3, 4))
        flipped = "기준선" if row["is_adopted"] else f"{row['decision_flipped'] * 100:.0f}%"
        moved = "기준선" if row["is_adopted"] else f"{row['numbers_moved'] * 100:.0f}%"
        lines.append(f"| {row['label']} | {cells} | {flipped} | {moved} |")
    lines.append("")
    lines.append("각 안을 기각·채택한 근거:")
    lines.append("")
    for row in table["rows"]:
        lines.append(f"- **{row['label']}** — {row['note']}")
    lines.append("")
    return lines


def render(table: dict) -> str:
    widths = " · ".join(f"±{int(w * 100)}% ({label})" for label, w in PERTURBATIONS)
    lines = [
        "# 감도분석 표 (SPEC 5.1.3) — 생성물",
        "",
        "손으로 쓰지 않는다. `python backend/tests/sensitivity.py` 로 재생성한다.",
        "",
        "**합격선은 '뒤집히지 않는다'가 아니라 '어디서 뒤집히는지 드러낸다'이다.**",
        "이 표는 통과/실패를 판정하지 않는다. 어떤 가정이 결론을 지고 있는지를 보이기 위한 것이다.",
        "",
        f"- 교란폭: {widths}. **이 선택 자체가 (d) 규범적 선택이며 준거가 없다.**",
        "  다른 폭을 고르면 아래 숫자가 달라진다. 이 표를 근거로 '안정적이다'라고 주장하지 않는다.",
        f"- 대상 상수: 레지스트리의 `spec_class == \"d\"` 전수 ({len(normative_keys())}개).",
        f"- 사례 모집단: {table['caseCount']}건 — {', '.join(table['caseIds'])}.",
        "  **골격용 임시 세트다.** 개수·설계 책임자는 SPEC 9.2.2 실사 미정이며 커버리지를 주장하지 않는다.",
        "  예외를 던지는 축(없는 지역)은 상수와 무관하게 항상 거부되므로 모집단에서 제외했다.",
        "- `판정 뒤집힘` = 밴드·verdict·정책 status·시나리오 순위 중 하나라도 달라진 사례 비율.",
        "  `숫자 이동` = 판정은 같아도 어떤 숫자든 움직인 사례 비율. 둘을 나눈 이유는",
        "  \"조금 움직였다\"와 \"결론이 바뀌었다\"가 다른 사실이기 때문이다.",
        "- **`[정의역 밖]`** = 교란값이 그 상수가 가질 수 없는 값이 됐다는 뜻이다.",
        "  **클램프하지 않는다.** 잘라 놓고 「+20% 교란」이라 적으면 표가 스스로 거짓말한다.",
        "  「이 상수는 그 방향으로 그만큼 교란할 여지가 없다」는 것 자체가 드러낼 사실이다.",
        "  정의역은 `sensitivity.py` 의 `DOMAINS` 에 상수별 근거와 함께 적혀 있다.",
        "  ※ `recommended <= max` 같은 **불변식 검사는 프로덕션 경로에만** 건다. 이 하네스는",
        "  일부러 비현실적 값을 넣어 보는 곳이라 여기서 불변식이 깨지는 것은 결함이 아니다.",
        "",
        "| (d) 상수 | 교란폭 | 판정 뒤집힘 | 숫자 이동 | 비고 |",
        "|---|---|---|---|---|",
    ]
    for row in table["rows"]:
        if row["out_of_domain"]:
            flipped = moved = "**[정의역 밖]**"
        else:
            flipped = "—" if row["decision_flipped"] is None else f"{row['decision_flipped'] * 100:.0f}%"
            moved = "—" if row["numbers_moved"] is None else f"{row['numbers_moved'] * 100:.0f}%"
        lines.append(
            f"| `{row['constant']}` | {row['width']} | {flipped} | {moved} | {row['note']} |"
        )
    lines.append("")
    lines.extend(render_definition_section(build_definition_table()))
    return "\n".join(lines)


def main() -> None:
    table = build_table()
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(render(table), encoding="utf-8")
    print(json.dumps({"rows": len(table["rows"]), "cases": table["caseCount"]}, ensure_ascii=False))
    print(f"wrote {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()
