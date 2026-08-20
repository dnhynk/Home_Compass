# 감도분석 표 (SPEC 5.1.3) — 생성물

손으로 쓰지 않는다. `python backend/tests/sensitivity.py` 로 재생성한다.

**합격선은 '뒤집히지 않는다'가 아니라 '어디서 뒤집히는지 드러낸다'이다.**
이 표는 통과/실패를 판정하지 않는다. 어떤 가정이 결론을 지고 있는지를 보이기 위한 것이다.

- 교란폭: ±5% (작은 폭) · ±20% (큰 폭). **이 선택 자체가 (d) 규범적 선택이며 준거가 없다.**
  다른 폭을 고르면 아래 숫자가 달라진다. 이 표를 근거로 '안정적이다'라고 주장하지 않는다.
- 대상 상수: 레지스트리의 `spec_class == "d"` 전수 (71개).
- 사례 모집단: 11건 — baseline, zero_income, very_high_income, age_boundary_min, age_boundary_max, age_over_max, non_metro, non_metro_no_guarantee, metro_gyeonggi, max_jeonse_region, household_four.
  **골격용 임시 세트다.** 개수·설계 책임자는 SPEC 9.2.2 실사 미정이며 커버리지를 주장하지 않는다.
  예외를 던지는 축(없는 지역)은 상수와 무관하게 항상 거부되므로 모집단에서 제외했다.
- `판정 뒤집힘` = 밴드·verdict·정책 status·시나리오 순위 중 하나라도 달라진 사례 비율.
  `숫자 이동` = 판정은 같아도 어떤 숫자든 움직인 사례 비율. 둘을 나눈 이유는
  "조금 움직였다"와 "결론이 바뀌었다"가 다른 사실이기 때문이다.
- **`[정의역 밖]`** = 교란값이 그 상수가 가질 수 없는 값이 됐다는 뜻이다.
  **클램프하지 않는다.** 잘라 놓고 「+20% 교란」이라 적으면 표가 스스로 거짓말한다.
  「이 상수는 그 방향으로 그만큼 교란할 여지가 없다」는 것 자체가 드러낼 사실이다.
  정의역은 `sensitivity.py` 의 `DOMAINS` 에 상수별 근거와 함께 적혀 있다.
  ※ `recommended <= max` 같은 **불변식 검사는 프로덕션 경로에만** 건다. 이 하네스는
  일부러 비현실적 값을 넣어 보는 곳이라 여기서 불변식이 깨지는 것은 결함이 아니다.

| (d) 상수 | 교란폭 | 판정 뒤집힘 | 숫자 이동 | 비고 |
|---|---|---|---|---|
| `affordability.housing_cost_ratio_cap` | -5% (작은 폭) | 0% | 82% |  |
| `affordability.housing_cost_ratio_cap` | +5% (작은 폭) | 0% | 9% |  |
| `affordability.housing_cost_ratio_cap` | -20% (큰 폭) | 82% | 82% |  |
| `affordability.housing_cost_ratio_cap` | +20% (큰 폭) | 0% | 9% |  |
| `affordability.recommended_haircut` | -5% (작은 폭) | 9% | 82% |  |
| `affordability.recommended_haircut` | +5% (작은 폭) | 9% | 82% |  |
| `affordability.recommended_haircut` | -20% (큰 폭) | 18% | 82% |  |
| `affordability.recommended_haircut` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 1.02 이 정의역 (0, 1] — 상한에 곱하는 안전마진. 1 초과면 권장액이 상한을 넘어 SPEC 5.3 의 `recommended <= max` 가 깨진다. |
| `affordability.buffer_ratio` | -5% (작은 폭) | 0% | 91% |  |
| `affordability.buffer_ratio` | +5% (작은 폭) | 0% | 91% |  |
| `affordability.buffer_ratio` | -20% (큰 폭) | 9% | 91% |  |
| `affordability.buffer_ratio` | +20% (큰 폭) | 9% | 91% |  |
| `affordability.safe_cap_ratio` | -5% (작은 폭) | 0% | 0% |  |
| `affordability.safe_cap_ratio` | +5% (작은 폭) | 0% | 0% |  |
| `affordability.safe_cap_ratio` | -20% (큰 폭) | 0% | 0% |  |
| `affordability.safe_cap_ratio` | +20% (큰 폭) | 73% | 73% |  |
| `affordability.caution_cap_ratio` | -5% (작은 폭) | 0% | 0% |  |
| `affordability.caution_cap_ratio` | +5% (작은 폭) | 0% | 0% |  |
| `affordability.caution_cap_ratio` | -20% (큰 폭) | 0% | 0% |  |
| `affordability.caution_cap_ratio` | +20% (큰 폭) | 0% | 0% |  |
| `affordability.safe_debt_ratio` | -5% (작은 폭) | 0% | 0% |  |
| `affordability.safe_debt_ratio` | +5% (작은 폭) | 0% | 0% |  |
| `affordability.safe_debt_ratio` | -20% (큰 폭) | 0% | 0% |  |
| `affordability.safe_debt_ratio` | +20% (큰 폭) | 0% | 0% |  |
| `affordability.caution_debt_ratio` | -5% (작은 폭) | 0% | 0% |  |
| `affordability.caution_debt_ratio` | +5% (작은 폭) | 0% | 0% |  |
| `affordability.caution_debt_ratio` | -20% (큰 폭) | 0% | 0% |  |
| `affordability.caution_debt_ratio` | +20% (큰 폭) | 0% | 0% |  |
| `tco.horizon_years` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `tco.horizon_years` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `tco.horizon_years` | -20% (큰 폭) | 0% | 100% |  |
| `tco.horizon_years` | +20% (큰 폭) | 0% | 100% |  |
| `tco.guarantee_rate_unknown_axis_rule` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `tco.guarantee_rate_unknown_axis_rule` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `tco.guarantee_rate_unknown_axis_rule` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `tco.guarantee_rate_unknown_axis_rule` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.band_low_max` | -5% (작은 폭) | 0% | 0% |  |
| `risk.band_low_max` | +5% (작은 폭) | 0% | 0% |  |
| `risk.band_low_max` | -20% (큰 폭) | 9% | 9% |  |
| `risk.band_low_max` | +20% (큰 폭) | 0% | 0% |  |
| `risk.band_medium_max` | -5% (작은 폭) | 0% | 0% |  |
| `risk.band_medium_max` | +5% (작은 폭) | 0% | 0% |  |
| `risk.band_medium_max` | -20% (큰 폭) | 0% | 0% |  |
| `risk.band_medium_max` | +20% (큰 폭) | 9% | 9% |  |
| `risk.low_exposure_krw` | -5% (작은 폭) | 0% | 0% |  |
| `risk.low_exposure_krw` | +5% (작은 폭) | 0% | 9% |  |
| `risk.low_exposure_krw` | -20% (큰 폭) | 0% | 0% |  |
| `risk.low_exposure_krw` | +20% (큰 폭) | 0% | 9% |  |
| `risk.minimal_exposure_krw` | -5% (작은 폭) | 0% | 0% |  |
| `risk.minimal_exposure_krw` | +5% (작은 폭) | 0% | 0% |  |
| `risk.minimal_exposure_krw` | -20% (큰 폭) | 0% | 0% |  |
| `risk.minimal_exposure_krw` | +20% (큰 폭) | 0% | 0% |  |
| `engines.jeonse_loan_priority` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.jeonse_loan_priority` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.jeonse_loan_priority` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.jeonse_loan_priority` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.monthly_loan_priority` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.monthly_loan_priority` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.monthly_loan_priority` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `engines.monthly_loan_priority` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `eligibility.boundary_margin` | -5% (작은 폭) | 0% | 0% |  |
| `eligibility.boundary_margin` | +5% (작은 폭) | 0% | 0% |  |
| `eligibility.boundary_margin` | -20% (큰 폭) | 0% | 0% |  |
| `eligibility.boundary_margin` | +20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_1` | -5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_1` | +5% (작은 폭) | 0% | 18% |  |
| `risk.jeonse_ratio_threshold_1` | -20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_1` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 72 이 정의역 (0, 70) — 전세가율 구간 경계(%). 이웃 경계를 넘으면 그 사이 구간이 도달 불가능해진다. |
| `risk.jeonse_ratio_threshold_2` | -5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_2` | +5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_2` | -20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 56 이 정의역 (60, 80) — 전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다. |
| `risk.jeonse_ratio_threshold_2` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 84 이 정의역 (60, 80) — 전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다. |
| `risk.jeonse_ratio_threshold_3` | -5% (작은 폭) | 0% | 9% |  |
| `risk.jeonse_ratio_threshold_3` | +5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_3` | -20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 64 이 정의역 (70, 90) — 전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다. |
| `risk.jeonse_ratio_threshold_3` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 96 이 정의역 (70, 90) — 전세가율 구간 경계(%). 이웃 경계 사이에 있어야 그 구간이 도달 가능하다. |
| `risk.jeonse_ratio_threshold_4` | -5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_4` | +5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_threshold_4` | -20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 72 이 정의역 (80, ∞) — 최상위 경계(%). 전세가율은 100 을 넘을 수 있으므로(깡통전세) 위쪽 경계는 두지 않는다. |
| `risk.jeonse_ratio_threshold_4` | +20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_1` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.jeonse_ratio_weight_1` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.jeonse_ratio_weight_1` | -20% (큰 폭) | 0% | 18% |  |
| `risk.jeonse_ratio_weight_1` | +20% (큰 폭) | 0% | 18% |  |
| `risk.jeonse_ratio_weight_2` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.jeonse_ratio_weight_2` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.jeonse_ratio_weight_2` | -20% (큰 폭) | 0% | 18% |  |
| `risk.jeonse_ratio_weight_2` | +20% (큰 폭) | 0% | 18% |  |
| `risk.jeonse_ratio_weight_3` | -5% (작은 폭) | 0% | 9% |  |
| `risk.jeonse_ratio_weight_3` | +5% (작은 폭) | 0% | 9% |  |
| `risk.jeonse_ratio_weight_3` | -20% (큰 폭) | 0% | 9% |  |
| `risk.jeonse_ratio_weight_3` | +20% (큰 폭) | 0% | 9% |  |
| `risk.jeonse_ratio_weight_4` | -5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_4` | +5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_4` | -20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_4` | +20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_5` | -5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_5` | +5% (작은 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_5` | -20% (큰 폭) | 0% | 0% |  |
| `risk.jeonse_ratio_weight_5` | +20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_1` | -5% (작은 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_1` | +5% (작은 폭) | 0% | 9% |  |
| `risk.loan_share_threshold_1` | -20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_1` | +20% (큰 폭) | 0% | 9% |  |
| `risk.loan_share_threshold_2` | -5% (작은 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_2` | +5% (작은 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_2` | -20% (큰 폭) | 0% | 9% |  |
| `risk.loan_share_threshold_2` | +20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_3` | -5% (작은 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_3` | +5% (작은 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_3` | -20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_threshold_3` | +20% (큰 폭) | 0% | 18% |  |
| `risk.loan_share_weight_2` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.loan_share_weight_2` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.loan_share_weight_2` | -20% (큰 폭) | 0% | 18% |  |
| `risk.loan_share_weight_2` | +20% (큰 폭) | 0% | 18% |  |
| `risk.loan_share_weight_3` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.loan_share_weight_3` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.loan_share_weight_3` | -20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_weight_3` | +20% (큰 폭) | 0% | 0% |  |
| `risk.loan_share_weight_4` | -5% (작은 폭) | 0% | 18% |  |
| `risk.loan_share_weight_4` | +5% (작은 폭) | 0% | 18% |  |
| `risk.loan_share_weight_4` | -20% (큰 폭) | 0% | 18% |  |
| `risk.loan_share_weight_4` | +20% (큰 폭) | 0% | 18% |  |
| `risk.deposit_size_threshold_1` | -5% (작은 폭) | 0% | 0% |  |
| `risk.deposit_size_threshold_1` | +5% (작은 폭) | 0% | 9% |  |
| `risk.deposit_size_threshold_1` | -20% (큰 폭) | 0% | 0% |  |
| `risk.deposit_size_threshold_1` | +20% (큰 폭) | 0% | 9% |  |
| `risk.deposit_size_threshold_2` | -5% (작은 폭) | 0% | 0% |  |
| `risk.deposit_size_threshold_2` | +5% (작은 폭) | 0% | 0% |  |
| `risk.deposit_size_threshold_2` | -20% (큰 폭) | 0% | 0% |  |
| `risk.deposit_size_threshold_2` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 108 이 정의역 (50, 100] — 상한 대비 100% 를 넘으면 그 구간은 이미 가입 불가 영역이라 문턱으로서 의미가 없다. |
| `risk.deposit_size_weight_2` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.deposit_size_weight_2` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.deposit_size_weight_2` | -20% (큰 폭) | 0% | 9% |  |
| `risk.deposit_size_weight_2` | +20% (큰 폭) | 0% | 9% |  |
| `risk.deposit_size_weight_3` | -5% (작은 폭) | 0% | 0% |  |
| `risk.deposit_size_weight_3` | +5% (작은 폭) | 0% | 0% |  |
| `risk.deposit_size_weight_3` | -20% (큰 폭) | 0% | 0% |  |
| `risk.deposit_size_weight_3` | +20% (큰 폭) | 0% | 0% |  |
| `risk.market_weight_medium` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.market_weight_medium` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `risk.market_weight_medium` | -20% (큰 폭) | 0% | 9% |  |
| `risk.market_weight_medium` | +20% (큰 폭) | 0% | 9% |  |
| `risk.market_weight_high` | -5% (작은 폭) | 0% | 9% |  |
| `risk.market_weight_high` | +5% (작은 폭) | 0% | 9% |  |
| `risk.market_weight_high` | -20% (큰 폭) | 0% | 9% |  |
| `risk.market_weight_high` | +20% (큰 폭) | 0% | 9% |  |
| `risk.market_value_pct_low` | -5% (작은 폭) | 0% | 82% |  |
| `risk.market_value_pct_low` | +5% (작은 폭) | 0% | 82% |  |
| `risk.market_value_pct_low` | -20% (큰 폭) | 0% | 82% |  |
| `risk.market_value_pct_low` | +20% (큰 폭) | 0% | 82% |  |
| `risk.market_value_pct_medium` | -5% (작은 폭) | 0% | 9% |  |
| `risk.market_value_pct_medium` | +5% (작은 폭) | 0% | 9% |  |
| `risk.market_value_pct_medium` | -20% (큰 폭) | 0% | 9% |  |
| `risk.market_value_pct_medium` | +20% (큰 폭) | 0% | 9% |  |
| `risk.market_value_pct_high` | -5% (작은 폭) | 0% | 9% |  |
| `risk.market_value_pct_high` | +5% (작은 폭) | 0% | 9% |  |
| `risk.market_value_pct_high` | -20% (큰 폭) | 0% | 9% |  |
| `risk.market_value_pct_high` | +20% (큰 폭) | **[정의역 밖]** | **[정의역 밖]** | 교란값 102 이 정의역 [60, 100] — 응답에 그대로 실리는 표시값(%). 100 을 넘으면 백분율이 아니게 된다. |
| `risk.guarantee_unavailable_weight` | -5% (작은 폭) | 0% | 9% |  |
| `risk.guarantee_unavailable_weight` | +5% (작은 폭) | 0% | 9% |  |
| `risk.guarantee_unavailable_weight` | -20% (큰 폭) | 0% | 9% |  |
| `risk.guarantee_unavailable_weight` | +20% (큰 폭) | 0% | 9% |  |
| `risk.guarantee_small_deposit_multiplier` | -5% (작은 폭) | 0% | 0% |  |
| `risk.guarantee_small_deposit_multiplier` | +5% (작은 폭) | 0% | 0% |  |
| `risk.guarantee_small_deposit_multiplier` | -20% (큰 폭) | 0% | 0% |  |
| `risk.guarantee_small_deposit_multiplier` | +20% (큰 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_low` | -5% (작은 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_low` | +5% (작은 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_low` | -20% (큰 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_low` | +20% (큰 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_minimal` | -5% (작은 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_minimal` | +5% (작은 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_minimal` | -20% (큰 폭) | 0% | 0% |  |
| `risk.exposure_multiplier_minimal` | +20% (큰 폭) | 0% | 0% |  |
| `tco.fit_afford_weight` | -5% (작은 폭) | 0% | 36% |  |
| `tco.fit_afford_weight` | +5% (작은 폭) | 0% | 18% |  |
| `tco.fit_afford_weight` | -20% (큰 폭) | 9% | 36% |  |
| `tco.fit_afford_weight` | +20% (큰 폭) | 0% | 18% |  |
| `tco.fit_afford_overrun_slope` | -5% (작은 폭) | 0% | 18% |  |
| `tco.fit_afford_overrun_slope` | +5% (작은 폭) | 0% | 18% |  |
| `tco.fit_afford_overrun_slope` | -20% (큰 폭) | 9% | 18% |  |
| `tco.fit_afford_overrun_slope` | +20% (큰 폭) | 9% | 18% |  |
| `tco.fit_capital_weight` | -5% (작은 폭) | 9% | 91% |  |
| `tco.fit_capital_weight` | +5% (작은 폭) | 0% | 73% |  |
| `tco.fit_capital_weight` | -20% (큰 폭) | 0% | 91% |  |
| `tco.fit_capital_weight` | +20% (큰 폭) | 9% | 73% |  |
| `tco.fit_preference_match_score` | -5% (작은 폭) | 0% | 100% |  |
| `tco.fit_preference_match_score` | +5% (작은 폭) | 0% | 82% |  |
| `tco.fit_preference_match_score` | -20% (큰 폭) | 0% | 100% |  |
| `tco.fit_preference_match_score` | +20% (큰 폭) | 0% | 82% |  |
| `tco.fit_preference_mismatch_score` | -5% (작은 폭) | 0% | 0% |  |
| `tco.fit_preference_mismatch_score` | +5% (작은 폭) | 0% | 0% |  |
| `tco.fit_preference_mismatch_score` | -20% (큰 폭) | 0% | 0% |  |
| `tco.fit_preference_mismatch_score` | +20% (큰 폭) | 0% | 0% |  |
| `tco.semi_jeonse_deposit_share` | -5% (작은 폭) | 9% | 100% |  |
| `tco.semi_jeonse_deposit_share` | +5% (작은 폭) | 0% | 100% |  |
| `tco.semi_jeonse_deposit_share` | -20% (큰 폭) | 9% | 100% |  |
| `tco.semi_jeonse_deposit_share` | +20% (큰 폭) | 0% | 100% |  |
| `tco.low_deposit_scenario_deposit_krw` | -5% (작은 폭) | 0% | 100% |  |
| `tco.low_deposit_scenario_deposit_krw` | +5% (작은 폭) | 0% | 100% |  |
| `tco.low_deposit_scenario_deposit_krw` | -20% (큰 폭) | 0% | 100% |  |
| `tco.low_deposit_scenario_deposit_krw` | +20% (큰 폭) | 0% | 100% |  |
| `tco.deposit_rounding_unit_krw` | -5% (작은 폭) | 0% | 100% |  |
| `tco.deposit_rounding_unit_krw` | +5% (작은 폭) | 0% | 100% |  |
| `tco.deposit_rounding_unit_krw` | -20% (큰 폭) | 0% | 100% |  |
| `tco.deposit_rounding_unit_krw` | +20% (큰 폭) | 0% | 100% |  |
| `tco.monthly_rounding_unit_krw` | -5% (작은 폭) | 0% | 100% |  |
| `tco.monthly_rounding_unit_krw` | +5% (작은 폭) | 0% | 100% |  |
| `tco.monthly_rounding_unit_krw` | -20% (큰 폭) | 0% | 100% |  |
| `tco.monthly_rounding_unit_krw` | +20% (큰 폭) | 0% | 100% |  |
| `eligibility.age_cap_imminent_years` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `eligibility.age_cap_imminent_years` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `eligibility.age_cap_imminent_years` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `eligibility.age_cap_imminent_years` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `eligibility.age_max_unlimited_sentinel` | -5% (작은 폭) | 0% | 0% |  |
| `eligibility.age_max_unlimited_sentinel` | +5% (작은 폭) | 0% | 0% |  |
| `eligibility.age_max_unlimited_sentinel` | -20% (큰 폭) | 0% | 0% |  |
| `eligibility.age_max_unlimited_sentinel` | +20% (큰 폭) | 0% | 0% |  |
| `eligibility.amount_unlimited_sentinel_krw` | -5% (작은 폭) | 0% | 0% |  |
| `eligibility.amount_unlimited_sentinel_krw` | +5% (작은 폭) | 0% | 0% |  |
| `eligibility.amount_unlimited_sentinel_krw` | -20% (큰 폭) | 0% | 0% |  |
| `eligibility.amount_unlimited_sentinel_krw` | +20% (큰 폭) | 0% | 0% |  |
| `extraction.max_attempts` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `extraction.max_attempts` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `extraction.max_attempts` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `extraction.max_attempts` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_outlier_ratio_jeonse` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_jeonse` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_jeonse` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_jeonse` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_deposit` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_deposit` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_deposit` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_deposit` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_rent` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_rent` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_rent` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_monthly_rent` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_trade` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_trade` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_trade` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_ratio_trade` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_share_threshold` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_share_threshold` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_outlier_share_threshold` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_outlier_share_threshold` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_min_sample_count` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_min_sample_count` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_min_sample_count` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_min_sample_count` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_pair_area_band_sqm` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_pair_area_band_sqm` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_pair_area_band_sqm` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_pair_area_band_sqm` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_lookback_months` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_lookback_months` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_lookback_months` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_lookback_months` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_max_exclusive_area_sqm` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_max_exclusive_area_sqm` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_max_exclusive_area_sqm` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_max_exclusive_area_sqm` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_max_attempts` | -5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_max_attempts` | +5% (작은 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_max_attempts` | -20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_max_attempts` | +20% (큰 폭) | — | — | 교란 불가 — 비수치이거나 폭이 값을 움직이지 못함 |
| `ingest.market_request_timeout_seconds` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_request_timeout_seconds` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_request_timeout_seconds` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_request_timeout_seconds` | +20% (큰 폭) | 0% | 0% |  |
| `ingest.market_batch_deadline_seconds` | -5% (작은 폭) | 0% | 0% |  |
| `ingest.market_batch_deadline_seconds` | +5% (작은 폭) | 0% | 0% |  |
| `ingest.market_batch_deadline_seconds` | -20% (큰 폭) | 0% | 0% |  |
| `ingest.market_batch_deadline_seconds` | +20% (큰 폭) | 0% | 0% |  |
| `auth.session_idle_timeout_seconds` | -5% (작은 폭) | 0% | 0% |  |
| `auth.session_idle_timeout_seconds` | +5% (작은 폭) | 0% | 0% |  |
| `auth.session_idle_timeout_seconds` | -20% (큰 폭) | 0% | 0% |  |
| `auth.session_idle_timeout_seconds` | +20% (큰 폭) | 0% | 0% |  |
| `auth.session_absolute_timeout_seconds` | -5% (작은 폭) | 0% | 0% |  |
| `auth.session_absolute_timeout_seconds` | +5% (작은 폭) | 0% | 0% |  |
| `auth.session_absolute_timeout_seconds` | -20% (큰 폭) | 0% | 0% |  |
| `auth.session_absolute_timeout_seconds` | +20% (큰 폭) | 0% | 0% |  |

## 정의 선택 민감도 — **위 (d) 표와 별개의 산출물이다**

이 절은 (d) 상수 × 교란폭 표가 **아니다.** 대상은 `affordability.living_cost_by_household`
하나이고, 축은 교란폭이 아니라 **「무엇을 뺄지」의 정의 선택지**다.

**일반 규칙 — (b)(c) 라도 도출에 우리 선택이 끼면 그 선택은 노출 대상이다.**
값이 공표값이라는 것이 도출까지 공표됐다는 뜻은 아니다. 이 상수의 값은 가계동향조사
공표값의 뺄셈이라 `(b) verified` 이지만, 소비지출에서 **무엇을 뺄지는 우리가 골랐다.**
그래서 (d) 표에는 넣지 않고(SPEC 5.1.3 은 (d) × 교란폭이다) 여기에 따로 세운다.

- 기준선은 채택안이다. 「판정 뒤집힘」·「숫자 이동」은 채택안 대비 비율이다.
- 사례 모집단: 11건. 위 표와 같은 세트이며 커버리지를 주장하지 않는다.
- 세 안의 숫자는 전부 `FINDINGS-3.md` 7.3 의 공표값이다 (KOSIS `101/DT_1L9U105`,
  2025년 연간 · 전국 1인이상 · 전체가구). **같은 공표값에서 빼는 항목만 다르다.**

| 정의 | 1인 | 2인 | 3인 | 4인 | 판정 뒤집힘 | 숫자 이동 |
|---|---|---|---|---|---|---|
| 주거·수도·광열 전액 차감 | 1,432,902 | 2,379,282 | 3,482,512 | 4,343,910 | 9% | 100% |
| 실제주거비 + 기타주거관련서비스  ★ 채택 | 1,530,773 | 2,553,845 | 3,690,871 | 4,578,150 | 기준선 | 기준선 |
| 실제주거비만 차감 | 1,579,825 | 2,619,991 | 3,781,869 | 4,684,129 | 9% | 100% |

각 안을 기각·채택한 근거:

- **주거·수도·광열 전액 차감** — 기각. 연료비·상하수도까지 빼면 그 지출이 생활비에도 주거비에도 없는 상태가 된다 — 가구는 실제로 내는데 모델 어디에도 없어 잔여여력이 과대계상된다.
- **실제주거비 + 기타주거관련서비스  ★ 채택** — 모델이 주거비로 세는 항목만 뺀다 (tco.py 의 rent · maintenance). 계약 결정 #11.
- **실제주거비만 차감** — 기각. 공동주택관리비를 생활비에 남기면 region.maintenanceFeeKRW 와 이중계상된다.
