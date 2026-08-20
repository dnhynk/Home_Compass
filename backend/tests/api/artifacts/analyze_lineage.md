# `/api/analyze` 계보 · 등급 실기동 전문 (D-13)

`uvicorn firsthome.main:app --host 127.0.0.1 --port 8137 --workers 1` 로 실기동한 서버를
**익명으로** 한 번 친 결과다. SPEC 9.3 #3 의 첨부물이며, 손으로 옮겨 적지 않고 응답을 그대로 낸다.

생성 경로 — `scripts/seed_store.py` 로 시드한 저장소 (`model_constants` 82 · `regions` 10 · `rule_versions` 8).

요청 프로필

```json
{
  "age": 28,
  "annualIncomeKRW": 42000000,
  "monthlyNetIncomeKRW": 3000000,
  "liquidAssetsKRW": 40000000,
  "existingDebtMonthlyKRW": 300000,
  "householdSize": 1,
  "regionCode": "11440",
  "preferredType": "any"
}
```

최상단 키 — 계약 결정 #37 의 실측(`affordability, scenarios, policies, risk, summary, meta`)과 대조한다.

```
TOP KEYS: affordability, scenarios, policies, risk, summary, meta, provenance, dataGrade
has dataGrade? True | has provenance? True
```

## `dataGrade` 전문

```json
{
  "grade": "C",
  "reasons": [
    {
      "type": "unverified",
      "provenanceIndex": 0,
      "fact": "지역 시세 · conversionRatePct (서울 마포구)",
      "message": "지역 시세 · conversionRatePct (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 1,
      "fact": "지역 시세 · guaranteeAvailable (서울 마포구)",
      "message": "지역 시세 · guaranteeAvailable (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 2,
      "fact": "지역 시세 · jeonseMedianKRW (서울 마포구)",
      "message": "지역 시세 · jeonseMedianKRW (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 3,
      "fact": "지역 시세 · jeonseRatioPct (서울 마포구)",
      "message": "지역 시세 · jeonseRatioPct (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 4,
      "fact": "지역 시세 · maintenanceFeeKRW (서울 마포구)",
      "message": "지역 시세 · maintenanceFeeKRW (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 5,
      "fact": "지역 시세 · marketRisk (서울 마포구)",
      "message": "지역 시세 · marketRisk (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 6,
      "fact": "지역 시세 · monthlyDepositKRW (서울 마포구)",
      "message": "지역 시세 · monthlyDepositKRW (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 7,
      "fact": "지역 시세 · monthlyRentKRW (서울 마포구)",
      "message": "지역 시세 · monthlyRentKRW (서울 마포구) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 8,
      "fact": "정책 규칙 · 청년전용 버팀목전세자금대출 (seed:buttress_youth)",
      "message": "정책 규칙 · 청년전용 버팀목전세자금대출 (seed:buttress_youth) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 9,
      "fact": "정책 규칙 · 청년전용 보증부월세대출 (seed:youth_monthly_loan)",
      "message": "정책 규칙 · 청년전용 보증부월세대출 (seed:youth_monthly_loan) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 10,
      "fact": "정책 규칙 · 신혼부부 전용 전세자금대출 (seed:newlywed_jeonse)",
      "message": "정책 규칙 · 신혼부부 전용 전세자금대출 (seed:newlywed_jeonse) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 11,
      "fact": "정책 규칙 · 청년월세 한시 특별지원 (seed:youth_rent_support)",
      "message": "정책 규칙 · 청년월세 한시 특별지원 (seed:youth_rent_support) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 12,
      "fact": "정책 규칙 · 서울시 청년월세지원 (seed:seoul_youth_rent)",
      "message": "정책 규칙 · 서울시 청년월세지원 (seed:seoul_youth_rent) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 13,
      "fact": "정책 규칙 · 서울시 청년 임차보증금 이자지원 (seed:seoul_deposit_interest)",
      "message": "정책 규칙 · 서울시 청년 임차보증금 이자지원 (seed:seoul_deposit_interest) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 14,
      "fact": "정책 규칙 · 청년 주택드림 청약통장 (seed:housing_dream_savings)",
      "message": "정책 규칙 · 청년 주택드림 청약통장 (seed:housing_dream_savings) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 15,
      "fact": "정책 규칙 · 전세보증금반환보증 (seed:hug_deposit_guarantee)",
      "message": "정책 규칙 · 전세보증금반환보증 (seed:hug_deposit_guarantee) 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 21,
      "fact": "모델 상수 · affordability.living_cost_extra_per_person",
      "message": "모델 상수 · affordability.living_cost_extra_per_person 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 22,
      "fact": "모델 상수 · affordability.net_income_from_annual",
      "message": "모델 상수 · affordability.net_income_from_annual 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 65,
      "fact": "모델 상수 · risk.metro_sido_code_prefixes",
      "message": "모델 상수 · risk.metro_sido_code_prefixes 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "unverified",
      "provenanceIndex": 79,
      "fact": "모델 상수 · tco.jeonse_ltv",
      "message": "모델 상수 · tco.jeonse_ltv 의 출처를 확인하지 못했습니다."
    },
    {
      "type": "freshness_not_evaluated",
      "provenanceIndex": null,
      "fact": null,
      "message": "신선도 임계가 아직 정해지지 않아 stale 여부를 판정하지 않았습니다. 이 등급은 검증 상태만으로 산정된 것이며, 신선도가 확인되었다는 뜻이 아닙니다 (SPEC 2.4)."
    }
  ]
}
```

`our_choice` 는 계보에 **56 건** 실려 있고 등급 사유가 가리키는 것은 **0 건**이다 (Part 0-E #3).

`stale` 사유는 **0 건**이다 — 없어서가 아니라 **판정하지 않았기 때문**이며, 그 사실이 위 사유 목록의
`freshness_not_evaluated` 한 줄로 실린다 (SPEC 2.4 「신선도 임계는 미정이다」).

## `provenance` 전문 — 84 건

| # | factKind | verification | source_kind | targets | fact |
|---|---|---|---|---|---|
| 0 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · conversionRatePct (서울 마포구) |
| 1 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · guaranteeAvailable (서울 마포구) |
| 2 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · jeonseMedianKRW (서울 마포구) |
| 3 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · jeonseRatioPct (서울 마포구) |
| 4 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · maintenanceFeeKRW (서울 마포구) |
| 5 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · marketRisk (서울 마포구) |
| 6 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · monthlyDepositKRW (서울 마포구) |
| 7 | region_field | unverified | market | `/scenarios` `/risk` | 지역 시세 · monthlyRentKRW (서울 마포구) |
| 8 | rule_version | unverified | statute | `/policies/0` | 정책 규칙 · 청년전용 버팀목전세자금대출 (seed:buttress_youth) |
| 9 | rule_version | unverified | statute | `/policies/3` | 정책 규칙 · 청년전용 보증부월세대출 (seed:youth_monthly_loan) |
| 10 | rule_version | unverified | statute | `/policies/5` | 정책 규칙 · 신혼부부 전용 전세자금대출 (seed:newlywed_jeonse) |
| 11 | rule_version | unverified | statute | `/policies/6` | 정책 규칙 · 청년월세 한시 특별지원 (seed:youth_rent_support) |
| 12 | rule_version | unverified | statute | `/policies/7` | 정책 규칙 · 서울시 청년월세지원 (seed:seoul_youth_rent) |
| 13 | rule_version | unverified | statute | `/policies/1` | 정책 규칙 · 서울시 청년 임차보증금 이자지원 (seed:seoul_deposit_interest) |
| 14 | rule_version | unverified | statute | `/policies/2` | 정책 규칙 · 청년 주택드림 청약통장 (seed:housing_dream_savings) |
| 15 | rule_version | unverified | statute | `/policies/4` | 정책 규칙 · 전세보증금반환보증 (seed:hug_deposit_guarantee) |
| 16 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.buffer_ratio |
| 17 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.caution_cap_ratio |
| 18 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.caution_debt_ratio |
| 19 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.housing_cost_ratio_cap |
| 20 | model_constant | verified | statistic | `/affordability` | 모델 상수 · affordability.living_cost_by_household |
| 21 | model_constant | unverified | statistic | `/affordability` | 모델 상수 · affordability.living_cost_extra_per_person |
| 22 | model_constant | unverified | statute | `/affordability` | 모델 상수 · affordability.net_income_from_annual |
| 23 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.recommended_haircut |
| 24 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.safe_cap_ratio |
| 25 | model_constant | our_choice | normative | `/affordability` | 모델 상수 · affordability.safe_debt_ratio |
| 26 | model_constant | our_choice | normative | `/policies` | 모델 상수 · eligibility.age_cap_imminent_years |
| 27 | model_constant | our_choice | normative | `/policies` | 모델 상수 · eligibility.age_max_unlimited_sentinel |
| 28 | model_constant | our_choice | normative | `/policies` | 모델 상수 · eligibility.amount_unlimited_sentinel_krw |
| 29 | model_constant | our_choice | normative | `/policies` | 모델 상수 · eligibility.boundary_margin |
| 30 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · engines.jeonse_loan_priority |
| 31 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · engines.monthly_loan_priority |
| 32 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.band_low_max |
| 33 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.band_medium_max |
| 34 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.deposit_size_threshold_1 |
| 35 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.deposit_size_threshold_2 |
| 36 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.deposit_size_weight_2 |
| 37 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.deposit_size_weight_3 |
| 38 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.exposure_multiplier_low |
| 39 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.exposure_multiplier_minimal |
| 40 | model_constant | verified | statute | `/risk` | 모델 상수 · risk.guarantee_deposit_cap_metro_krw |
| 41 | model_constant | verified | statute | `/risk` | 모델 상수 · risk.guarantee_deposit_cap_other_krw |
| 42 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.guarantee_small_deposit_multiplier |
| 43 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.guarantee_unavailable_weight |
| 44 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_threshold_1 |
| 45 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_threshold_2 |
| 46 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_threshold_3 |
| 47 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_threshold_4 |
| 48 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_weight_1 |
| 49 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_weight_2 |
| 50 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_weight_3 |
| 51 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_weight_4 |
| 52 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.jeonse_ratio_weight_5 |
| 53 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_threshold_1 |
| 54 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_threshold_2 |
| 55 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_threshold_3 |
| 56 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_weight_2 |
| 57 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_weight_3 |
| 58 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.loan_share_weight_4 |
| 59 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.low_exposure_krw |
| 60 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.market_value_pct_high |
| 61 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.market_value_pct_low |
| 62 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.market_value_pct_medium |
| 63 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.market_weight_high |
| 64 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.market_weight_medium |
| 65 | model_constant | unverified | statute | `/risk` | 모델 상수 · risk.metro_sido_code_prefixes |
| 66 | model_constant | our_choice | normative | `/risk` | 모델 상수 · risk.minimal_exposure_krw |
| 67 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.deposit_rounding_unit_krw |
| 68 | model_constant | verified | market | `/scenarios` | 모델 상수 · tco.discount_rate_pct |
| 69 | model_constant | verified | market | `/scenarios` | 모델 상수 · tco.fallback_conversion_rate_pct |
| 70 | model_constant | verified | market | `/scenarios` | 모델 상수 · tco.fallback_jeonse_rate_pct |
| 71 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.fit_afford_overrun_slope |
| 72 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.fit_afford_weight |
| 73 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.fit_capital_weight |
| 74 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.fit_preference_match_score |
| 75 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.fit_preference_mismatch_score |
| 76 | model_constant | verified | statute | `/scenarios` | 모델 상수 · tco.guarantee_rate_table |
| 77 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.guarantee_rate_unknown_axis_rule |
| 78 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.horizon_years |
| 79 | model_constant | unverified | statute | `/scenarios` | 모델 상수 · tco.jeonse_ltv |
| 80 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.low_deposit_scenario_deposit_krw |
| 81 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.monthly_rounding_unit_krw |
| 82 | model_constant | verified | market | `/scenarios` | 모델 상수 · tco.opportunity_rate_pct |
| 83 | model_constant | our_choice | normative | `/scenarios` | 모델 상수 · tco.semi_jeonse_deposit_share |

항목 하나의 전문 (모양은 `contracts/provenance.schema.json` 과 같다 — 결정 #34 의 「같은 렌더러」):

```json
{
  "fact": "모델 상수 · affordability.buffer_ratio",
  "factKind": "model_constant",
  "provenance": {
    "source_kind": "normative",
    "source_name": null,
    "source_ref": null,
    "observed_at": null,
    "fetched_at": null,
    "verification": "our_choice"
  },
  "targets": [
    "/affordability"
  ]
}
```

## `targets` 가 실제 응답 위치를 가리키는가

```
사실   : 정책 규칙 · 청년전용 버팀목전세자금대출 (seed:buttress_youth)
포인터 : /policies/0
가리킨 곳 -> {"id": "buttress_youth", "name": "청년전용 버팀목전세자금대출", "status": "eligible"}
```

84 건의 `targets` 를 전부 RFC 6901 로 해석했고 **해석되지 않는 포인터는 0 건**이다.
같은 검사를 `backend/tests/api/test_analyze_lineage.py` 가 테스트로 고정한다.

## 계약 스키마 검증 (SPEC 9.1.2)

```
schema $ref : #/components/schemas/AnalyzeResponse
스키마 위반 : 없음 — 실기동 응답이 contracts/openapi.json 과 일치한다
```

2xx 만으로는 불합격이라는 것이 9.1.2 다. 부팅 스모크가 같은 검증을 CI 에서 돌린다.
