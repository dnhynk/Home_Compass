/* ============================================================
   생성물이다. 손으로 고치지 않는다 (SPEC D-11 · 1.2).

   재생성 : python scripts/gen_contracts.py
   검사   : python scripts/gen_contracts.py --check
   원본   : store 의 ModelConstant (SPEC D-11 · 5.1.4)
   모양   : contracts/README.md 결정 #34

   손으로 고치면 backend/tests/crosscheck/test_generated_frontend_diff.py 의
   바이트 비교가 깨진다. 되돌리려면 위 재생성 명령을 돌린다.

   이 파일이 없거나 로드에 실패하면 window.HOME_COMPASS_MODEL_CONSTANTS 은 undefined 다.
   소비자는 그 자리에서 로컬 판정 경로를 끄고 화면에 명시한다 — 기본값으로 메우는
   침묵 폴백을 금지한다 (SPEC D-11 · 6.2 오프라인 동작 정의 #3).
   ============================================================ */
window.HOME_COMPASS_MODEL_CONSTANTS = {
  "$generated": {
    "artifact": "web-model-constants",
    "command": "python scripts/gen_contracts.py",
    "doNotEdit": true,
    "engineVersion": "3.0.0",
    "global": "HOME_COMPASS_MODEL_CONSTANTS",
    "noSilentFallback": "이 파일이 없으면 window.HOME_COMPASS_MODEL_CONSTANTS 은 undefined 다. 기본값·빈 값으로 대체하지 않는다. 판정 경로를 끄고 화면에 명시한다 (SPEC D-11).",
    "registryVersion": "4.1.0",
    "shapeDocumentedIn": "contracts/README.md 결정 #34",
    "source": "store 의 ModelConstant (SPEC 1.2 · D-11)"
  },
  "$objectKeys": "krw_by_household 의 키는 JSON 에 정수가 없어 문자열이다 (\"1\" · \"2\" …). 가구원수로 조회할 때 String(n) 으로 맞춘다.",
  "$valueTypes": "값의 해석은 contracts/model_constants.json 의 valueTypeVocabulary 를 따른다. percent_rate 는 /100 을 거치고 percent_level 은 거치지 않는다 — 섞으면 예선의 80만/81만 부류 단위 사고가 난다.",
  "entries": {
    "affordability.buffer_ratio": {
      "engine": "affordability",
      "key": "affordability.buffer_ratio",
      "legacy_symbol": "BUFFER_RATIO",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.1,
      "value_type": "ratio"
    },
    "affordability.caution_cap_ratio": {
      "engine": "affordability",
      "key": "affordability.caution_cap_ratio",
      "legacy_symbol": "CAUTION_CAP_RATIO",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.12,
      "value_type": "ratio"
    },
    "affordability.caution_debt_ratio": {
      "engine": "affordability",
      "key": "affordability.caution_debt_ratio",
      "legacy_symbol": "CAUTION_DEBT_RATIO",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.35,
      "value_type": "ratio"
    },
    "affordability.housing_cost_ratio_cap": {
      "engine": "affordability",
      "key": "affordability.housing_cost_ratio_cap",
      "legacy_symbol": "HOUSING_COST_RATIO_CAP",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "국토교통부 2024년도 주거실태조사 — 수도권 임차가구 RIR 중위수 18.4%",
        "source_ref": "https://www.molit.go.kr/USR/NEWS/m_71/dtl.jsp?lcmspage=1&id=95091415",
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.3,
      "value_type": "ratio"
    },
    "affordability.living_cost_by_household": {
      "engine": "affordability",
      "key": "affordability.living_cost_by_household",
      "legacy_symbol": "LIVING_COST_BY_HOUSEHOLD",
      "provenance": {
        "fetched_at": "2026-08-14T00:00:00+09:00",
        "observed_at": "2025-12-31T00:00:00+09:00",
        "source_kind": "statistic",
        "source_name": "국가데이터처 가계동향조사 — 가구원수별 가구당 월평균 가계수지 (2025년 연간, 전국 1인이상 전체가구). 소비지출에서 실제주거비 + 기타주거관련서비스를 뺀 값",
        "source_ref": "KOSIS 101 / DT_1L9U105",
        "verification": "verified"
      },
      "spec_class": "b",
      "value": {
        "1": 1530773,
        "2": 2553845,
        "3": 3690871,
        "4": 4578150
      },
      "value_type": "krw_by_household"
    },
    "affordability.living_cost_extra_per_person": {
      "engine": "affordability",
      "key": "affordability.living_cost_extra_per_person",
      "legacy_symbol": "LIVING_COST_EXTRA_PER_PERSON",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statistic",
        "source_name": null,
        "source_ref": null,
        "verification": "unverified"
      },
      "spec_class": "b",
      "value": 500000,
      "value_type": "krw"
    },
    "affordability.net_income_from_annual": {
      "engine": "affordability",
      "key": "affordability.net_income_from_annual",
      "legacy_symbol": "NET_INCOME_FROM_ANNUAL",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": null,
        "source_ref": null,
        "verification": "unverified"
      },
      "spec_class": "a",
      "value": 0.85,
      "value_type": "ratio"
    },
    "affordability.recommended_haircut": {
      "engine": "affordability",
      "key": "affordability.recommended_haircut",
      "legacy_symbol": "RECOMMENDED_HAIRCUT",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.85,
      "value_type": "ratio"
    },
    "affordability.safe_cap_ratio": {
      "engine": "affordability",
      "key": "affordability.safe_cap_ratio",
      "legacy_symbol": "SAFE_CAP_RATIO",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.25,
      "value_type": "ratio"
    },
    "affordability.safe_debt_ratio": {
      "engine": "affordability",
      "key": "affordability.safe_debt_ratio",
      "legacy_symbol": "SAFE_DEBT_RATIO",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.2,
      "value_type": "ratio"
    },
    "auth.session_absolute_timeout_seconds": {
      "engine": "auth",
      "key": "auth.session_absolute_timeout_seconds",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "OWASP ASVS 4.0, V3.3.2 (세션 관리 — 주기적 재인증)",
        "source_ref": "https://github.com/OWASP/ASVS/blob/master/4.0/en/0x12-V3-Session-management.md",
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 28800,
      "value_type": "seconds"
    },
    "auth.session_idle_timeout_seconds": {
      "engine": "auth",
      "key": "auth.session_idle_timeout_seconds",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "OWASP ASVS 4.0, V3.3.2 (세션 관리 — 주기적 재인증)",
        "source_ref": "https://github.com/OWASP/ASVS/blob/master/4.0/en/0x12-V3-Session-management.md",
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1800,
      "value_type": "seconds"
    },
    "eligibility.age_cap_imminent_years": {
      "engine": "eligibility",
      "key": "eligibility.age_cap_imminent_years",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1,
      "value_type": "years"
    },
    "eligibility.age_max_unlimited_sentinel": {
      "engine": "eligibility",
      "key": "eligibility.age_max_unlimited_sentinel",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 200,
      "value_type": "years"
    },
    "eligibility.amount_unlimited_sentinel_krw": {
      "engine": "eligibility",
      "key": "eligibility.amount_unlimited_sentinel_krw",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1000000000,
      "value_type": "krw"
    },
    "eligibility.boundary_margin": {
      "engine": "eligibility",
      "key": "eligibility.boundary_margin",
      "legacy_symbol": "BOUNDARY_MARGIN",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.05,
      "value_type": "ratio"
    },
    "engines.jeonse_loan_priority": {
      "engine": "engines",
      "key": "engines.jeonse_loan_priority",
      "legacy_symbol": "JEONSE_LOAN_PRIORITY",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": [
        "buttress_youth",
        "newlywed_jeonse"
      ],
      "value_type": "policy_id_order"
    },
    "engines.monthly_loan_priority": {
      "engine": "engines",
      "key": "engines.monthly_loan_priority",
      "legacy_symbol": "MONTHLY_LOAN_PRIORITY",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": [
        "youth_monthly_loan"
      ],
      "value_type": "policy_id_order"
    },
    "extraction.max_attempts": {
      "engine": "extraction",
      "key": "extraction.max_attempts",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 2,
      "value_type": "attempts"
    },
    "ingest.market_batch_deadline_seconds": {
      "engine": "ingest",
      "key": "ingest.market_batch_deadline_seconds",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 600,
      "value_type": "seconds"
    },
    "ingest.market_lookback_months": {
      "engine": "ingest",
      "key": "ingest.market_lookback_months",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "감정평가에 관한 규칙 (국토교통부령 제1253호) 제2조제12호의2 — [적정한 실거래가] 의 거래시점 상한",
        "source_ref": "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&MST=254883&type=XML",
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 3,
      "value_type": "months"
    },
    "ingest.market_max_attempts": {
      "engine": "ingest",
      "key": "ingest.market_max_attempts",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 2,
      "value_type": "attempts"
    },
    "ingest.market_max_exclusive_area_sqm": {
      "engine": "ingest",
      "key": "ingest.market_max_exclusive_area_sqm",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 85,
      "value_type": "sqm"
    },
    "ingest.market_min_sample_count": {
      "engine": "ingest",
      "key": "ingest.market_min_sample_count",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10,
      "value_type": "count"
    },
    "ingest.market_outlier_ratio_jeonse": {
      "engine": "ingest",
      "key": "ingest.market_outlier_ratio_jeonse",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 3.0,
      "value_type": "multiple"
    },
    "ingest.market_outlier_ratio_monthly_deposit": {
      "engine": "ingest",
      "key": "ingest.market_outlier_ratio_monthly_deposit",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10.0,
      "value_type": "multiple"
    },
    "ingest.market_outlier_ratio_monthly_rent": {
      "engine": "ingest",
      "key": "ingest.market_outlier_ratio_monthly_rent",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10.0,
      "value_type": "multiple"
    },
    "ingest.market_outlier_ratio_trade": {
      "engine": "ingest",
      "key": "ingest.market_outlier_ratio_trade",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 5.0,
      "value_type": "multiple"
    },
    "ingest.market_outlier_share_threshold": {
      "engine": "ingest",
      "key": "ingest.market_outlier_share_threshold",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.1,
      "value_type": "ratio"
    },
    "ingest.market_pair_area_band_sqm": {
      "engine": "ingest",
      "key": "ingest.market_pair_area_band_sqm",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "한국부동산원 공동주택 실거래가격지수 — 동일 주택 가정 (국가통계 승인 제116072호)",
        "source_ref": "https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?mi=10337&cntntsId=1193&statId=S231520283",
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1.0,
      "value_type": "sqm"
    },
    "ingest.market_request_timeout_seconds": {
      "engine": "ingest",
      "key": "ingest.market_request_timeout_seconds",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 20,
      "value_type": "seconds"
    },
    "risk.band_low_max": {
      "engine": "risk",
      "key": "risk.band_low_max",
      "legacy_symbol": "BAND_LOW_MAX",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 34,
      "value_type": "score_points"
    },
    "risk.band_medium_max": {
      "engine": "risk",
      "key": "risk.band_medium_max",
      "legacy_symbol": "BAND_MEDIUM_MAX",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 64,
      "value_type": "score_points"
    },
    "risk.deposit_size_threshold_1": {
      "engine": "risk",
      "key": "risk.deposit_size_threshold_1",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 50,
      "value_type": "percent_level"
    },
    "risk.deposit_size_threshold_2": {
      "engine": "risk",
      "key": "risk.deposit_size_threshold_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 90,
      "value_type": "percent_level"
    },
    "risk.deposit_size_weight_2": {
      "engine": "risk",
      "key": "risk.deposit_size_weight_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 6,
      "value_type": "score_points"
    },
    "risk.deposit_size_weight_3": {
      "engine": "risk",
      "key": "risk.deposit_size_weight_3",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 12,
      "value_type": "score_points"
    },
    "risk.exposure_multiplier_low": {
      "engine": "risk",
      "key": "risk.exposure_multiplier_low",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.5,
      "value_type": "ratio"
    },
    "risk.exposure_multiplier_minimal": {
      "engine": "risk",
      "key": "risk.exposure_multiplier_minimal",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.2,
      "value_type": "ratio"
    },
    "risk.guarantee_deposit_cap_metro_krw": {
      "engine": "risk",
      "key": "risk.guarantee_deposit_cap_metro_krw",
      "legacy_symbol": "GUARANTEE_LIMIT_KRW",
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": null,
        "observed_at_unstated": true,
        "source_kind": "statute",
        "source_name": "주택도시보증공사(HUG) 「전세보증금반환보증 > 상품개요」 가입요건 ② — 전세보증금(월세가 있는 경우 전월세전환율 적용)이 수도권 7억 이하일 것",
        "source_ref": "https://www.khug.or.kr/hug/web/ig/dr/igdr000001.jsp",
        "verification": "verified"
      },
      "spec_class": "a",
      "value": 700000000,
      "value_type": "krw"
    },
    "risk.guarantee_deposit_cap_other_krw": {
      "engine": "risk",
      "key": "risk.guarantee_deposit_cap_other_krw",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": null,
        "observed_at_unstated": true,
        "source_kind": "statute",
        "source_name": "주택도시보증공사(HUG) 「전세보증금반환보증 > 상품개요」 가입요건 ② — 그 외 지역 5억원 이하일 것",
        "source_ref": "https://www.khug.or.kr/hug/web/ig/dr/igdr000001.jsp",
        "verification": "verified"
      },
      "spec_class": "a",
      "value": 500000000,
      "value_type": "krw"
    },
    "risk.guarantee_small_deposit_multiplier": {
      "engine": "risk",
      "key": "risk.guarantee_small_deposit_multiplier",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.3,
      "value_type": "ratio"
    },
    "risk.guarantee_unavailable_weight": {
      "engine": "risk",
      "key": "risk.guarantee_unavailable_weight",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 28,
      "value_type": "score_points"
    },
    "risk.jeonse_ratio_threshold_1": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_threshold_1",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 60,
      "value_type": "percent_level"
    },
    "risk.jeonse_ratio_threshold_2": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_threshold_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 70,
      "value_type": "percent_level"
    },
    "risk.jeonse_ratio_threshold_3": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_threshold_3",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 80,
      "value_type": "percent_level"
    },
    "risk.jeonse_ratio_threshold_4": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_threshold_4",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 90,
      "value_type": "percent_level"
    },
    "risk.jeonse_ratio_weight_1": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_weight_1",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 4,
      "value_type": "score_points"
    },
    "risk.jeonse_ratio_weight_2": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_weight_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10,
      "value_type": "score_points"
    },
    "risk.jeonse_ratio_weight_3": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_weight_3",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 18,
      "value_type": "score_points"
    },
    "risk.jeonse_ratio_weight_4": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_weight_4",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 30,
      "value_type": "score_points"
    },
    "risk.jeonse_ratio_weight_5": {
      "engine": "risk",
      "key": "risk.jeonse_ratio_weight_5",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 42,
      "value_type": "score_points"
    },
    "risk.loan_share_threshold_1": {
      "engine": "risk",
      "key": "risk.loan_share_threshold_1",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 20,
      "value_type": "percent_level"
    },
    "risk.loan_share_threshold_2": {
      "engine": "risk",
      "key": "risk.loan_share_threshold_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 50,
      "value_type": "percent_level"
    },
    "risk.loan_share_threshold_3": {
      "engine": "risk",
      "key": "risk.loan_share_threshold_3",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 70,
      "value_type": "percent_level"
    },
    "risk.loan_share_weight_2": {
      "engine": "risk",
      "key": "risk.loan_share_weight_2",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 6,
      "value_type": "score_points"
    },
    "risk.loan_share_weight_3": {
      "engine": "risk",
      "key": "risk.loan_share_weight_3",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10,
      "value_type": "score_points"
    },
    "risk.loan_share_weight_4": {
      "engine": "risk",
      "key": "risk.loan_share_weight_4",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 14,
      "value_type": "score_points"
    },
    "risk.low_exposure_krw": {
      "engine": "risk",
      "key": "risk.low_exposure_krw",
      "legacy_symbol": "LOW_EXPOSURE_KRW",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 50000000,
      "value_type": "krw"
    },
    "risk.market_value_pct_high": {
      "engine": "risk",
      "key": "risk.market_value_pct_high",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 85.0,
      "value_type": "percent_level"
    },
    "risk.market_value_pct_low": {
      "engine": "risk",
      "key": "risk.market_value_pct_low",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 30.0,
      "value_type": "percent_level"
    },
    "risk.market_value_pct_medium": {
      "engine": "risk",
      "key": "risk.market_value_pct_medium",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 60.0,
      "value_type": "percent_level"
    },
    "risk.market_weight_high": {
      "engine": "risk",
      "key": "risk.market_weight_high",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 14,
      "value_type": "score_points"
    },
    "risk.market_weight_medium": {
      "engine": "risk",
      "key": "risk.market_weight_medium",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 6,
      "value_type": "score_points"
    },
    "risk.metro_sido_code_prefixes": {
      "engine": "risk",
      "key": "risk.metro_sido_code_prefixes",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": null,
        "source_ref": null,
        "verification": "unverified"
      },
      "spec_class": "a",
      "value": [
        "11",
        "28",
        "41"
      ],
      "value_type": "sido_code_prefixes"
    },
    "risk.minimal_exposure_krw": {
      "engine": "risk",
      "key": "risk.minimal_exposure_krw",
      "legacy_symbol": "MINIMAL_EXPOSURE_KRW",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 10000000,
      "value_type": "krw"
    },
    "tco.deposit_rounding_unit_krw": {
      "engine": "tco",
      "key": "tco.deposit_rounding_unit_krw",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1000000,
      "value_type": "krw"
    },
    "tco.discount_rate_pct": {
      "engine": "tco",
      "key": "tco.discount_rate_pct",
      "legacy_symbol": "DISCOUNT_RATE_PCT",
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": "2026-08-13T16:00:00+09:00",
        "source_kind": "market",
        "source_name": "금융투자협회 채권정보센터 최종호가수익률 — 국고채권(5년) 오후(16시) 고시 연 4.016%",
        "source_ref": "https://www.kofiabond.or.kr/ → /html/MAIN.html → 「최종호가수익률」 탭",
        "verification": "verified"
      },
      "spec_class": "c",
      "value": 4.016,
      "value_type": "percent_rate"
    },
    "tco.fallback_conversion_rate_pct": {
      "engine": "tco",
      "key": "tco.fallback_conversion_rate_pct",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": "2026-05-31T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "한국부동산원 「전국주택가격동향조사」 지역별 전월세전환율 — 서울 · 주택유형 종합, 2026년 5월 연 5.6%",
        "source_ref": "KOSIS orgId=408 · tblId=DT_30404_N0010 (https://kosis.kr/statHtml/statHtml.do?orgId=408&tblId=DT_30404_N0010)",
        "verification": "verified"
      },
      "spec_class": "c",
      "value": 5.6,
      "value_type": "percent_rate"
    },
    "tco.fallback_jeonse_rate_pct": {
      "engine": "tco",
      "key": "tco.fallback_jeonse_rate_pct",
      "legacy_symbol": "FALLBACK_JEONSE_RATE_PCT",
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": "2026-06-30T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "한국은행 「2026년 6월 금융기관 가중평균금리」 — 예금은행 담보별 가계대출 금리(신규취급액 기준) 전세자금대출 연 4.11%, 잠정치(p)",
        "source_ref": "https://www.bok.or.kr/portal/bbs/B0000501/view.do?nttId=11063198&menuNo=201264",
        "verification": "verified"
      },
      "spec_class": "c",
      "value": 4.11,
      "value_type": "percent_rate"
    },
    "tco.fit_afford_overrun_slope": {
      "engine": "tco",
      "key": "tco.fit_afford_overrun_slope",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 120.0,
      "value_type": "score_points"
    },
    "tco.fit_afford_weight": {
      "engine": "tco",
      "key": "tco.fit_afford_weight",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 60.0,
      "value_type": "score_points"
    },
    "tco.fit_capital_weight": {
      "engine": "tco",
      "key": "tco.fit_capital_weight",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 25.0,
      "value_type": "score_points"
    },
    "tco.fit_preference_match_score": {
      "engine": "tco",
      "key": "tco.fit_preference_match_score",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 15.0,
      "value_type": "score_points"
    },
    "tco.fit_preference_mismatch_score": {
      "engine": "tco",
      "key": "tco.fit_preference_mismatch_score",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 7.0,
      "value_type": "score_points"
    },
    "tco.guarantee_rate_table": {
      "engine": "tco",
      "key": "tco.guarantee_rate_table",
      "legacy_symbol": "GUARANTEE_RATE_PCT",
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": null,
        "observed_at_unstated": true,
        "source_kind": "statute",
        "source_name": "주택도시보증공사(HUG) 「전세보증금반환보증 > 상품개요」 보증료율표 — 보증금액 4구간 x 주택유형 2종(아파트/기타) x 부채비율 3구간(70%/80%/초과) 24칸, 연 0.097~0.211%",
        "source_ref": "https://www.khug.or.kr/hug/web/ig/dr/igdr000001.jsp",
        "verification": "verified"
      },
      "spec_class": "a",
      "value": [
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 100000000,
          "housingType": "apartment",
          "ratePct": 0.097
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 100000000,
          "housingType": "apartment",
          "ratePct": 0.117
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 100000000,
          "housingType": "apartment",
          "ratePct": 0.137
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 100000000,
          "housingType": "other",
          "ratePct": 0.111
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 100000000,
          "housingType": "other",
          "ratePct": 0.142
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 100000000,
          "housingType": "other",
          "ratePct": 0.172
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 200000000,
          "housingType": "apartment",
          "ratePct": 0.102
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 200000000,
          "housingType": "apartment",
          "ratePct": 0.124
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 200000000,
          "housingType": "apartment",
          "ratePct": 0.146
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 200000000,
          "housingType": "other",
          "ratePct": 0.117
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 200000000,
          "housingType": "other",
          "ratePct": 0.151
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 200000000,
          "housingType": "other",
          "ratePct": 0.184
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 500000000,
          "housingType": "apartment",
          "ratePct": 0.107
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 500000000,
          "housingType": "apartment",
          "ratePct": 0.131
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 500000000,
          "housingType": "apartment",
          "ratePct": 0.154
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": 500000000,
          "housingType": "other",
          "ratePct": 0.124
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": 500000000,
          "housingType": "other",
          "ratePct": 0.161
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": 500000000,
          "housingType": "other",
          "ratePct": 0.197
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": null,
          "housingType": "apartment",
          "ratePct": 0.113
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": null,
          "housingType": "apartment",
          "ratePct": 0.138
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": null,
          "housingType": "apartment",
          "ratePct": 0.164
        },
        {
          "debtRatioMaxPct": 70,
          "depositMaxKRW": null,
          "housingType": "other",
          "ratePct": 0.132
        },
        {
          "debtRatioMaxPct": 80,
          "depositMaxKRW": null,
          "housingType": "other",
          "ratePct": 0.172
        },
        {
          "debtRatioMaxPct": null,
          "depositMaxKRW": null,
          "housingType": "other",
          "ratePct": 0.211
        }
      ],
      "value_type": "guarantee_rate_table"
    },
    "tco.guarantee_rate_unknown_axis_rule": {
      "engine": "tco",
      "key": "tco.guarantee_rate_unknown_axis_rule",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": "요율표 조회 축 2종(주택유형·부채비율)이 입력에 없을 때의 처리 — 우리 선택",
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": "bracket_max",
      "value_type": "lookup_rule"
    },
    "tco.horizon_years": {
      "engine": "tco",
      "key": "tco.horizon_years",
      "legacy_symbol": "HORIZON_YEARS",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 5,
      "value_type": "years"
    },
    "tco.jeonse_ltv": {
      "engine": "tco",
      "key": "tco.jeonse_ltv",
      "legacy_symbol": "JEONSE_LTV",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": null,
        "source_ref": null,
        "verification": "unverified"
      },
      "spec_class": "a",
      "value": 0.8,
      "value_type": "ratio"
    },
    "tco.low_deposit_scenario_deposit_krw": {
      "engine": "tco",
      "key": "tco.low_deposit_scenario_deposit_krw",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 5000000,
      "value_type": "krw"
    },
    "tco.monthly_rounding_unit_krw": {
      "engine": "tco",
      "key": "tco.monthly_rounding_unit_krw",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 1000,
      "value_type": "krw"
    },
    "tco.opportunity_rate_pct": {
      "engine": "tco",
      "key": "tco.opportunity_rate_pct",
      "legacy_symbol": "OPPORTUNITY_RATE_PCT",
      "provenance": {
        "fetched_at": "2026-08-13T00:00:00+09:00",
        "observed_at": "2026-06-30T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "한국은행 「2026년 6월 금융기관 가중평균금리」 — 예금은행 수신금리(신규취급액 기준) 정기예금(1년) 연 3.26%, 잠정치(p)",
        "source_ref": "https://www.bok.or.kr/portal/bbs/B0000501/view.do?nttId=11063198&menuNo=201264",
        "verification": "verified"
      },
      "spec_class": "c",
      "value": 3.26,
      "value_type": "percent_rate"
    },
    "tco.semi_jeonse_deposit_share": {
      "engine": "tco",
      "key": "tco.semi_jeonse_deposit_share",
      "legacy_symbol": null,
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "normative",
        "source_name": null,
        "source_ref": null,
        "verification": "our_choice"
      },
      "spec_class": "d",
      "value": 0.5,
      "value_type": "ratio"
    }
  }
};
