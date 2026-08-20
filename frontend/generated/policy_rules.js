/* ============================================================
   생성물이다. 손으로 고치지 않는다 (SPEC D-11 · 1.2).

   재생성 : python scripts/gen_contracts.py
   검사   : python scripts/gen_contracts.py --check
   원본   : store 의 승인된 RuleVersion (SPEC D-11 · 2.3)
   모양   : contracts/README.md 결정 #34

   손으로 고치면 backend/tests/crosscheck/test_generated_frontend_diff.py 의
   바이트 비교가 깨진다. 되돌리려면 위 재생성 명령을 돌린다.

   이 파일이 없거나 로드에 실패하면 window.FIRSTHOME_POLICY_RULES 은 undefined 다.
   소비자는 그 자리에서 로컬 판정 경로를 끄고 화면에 명시한다 — 기본값으로 메우는
   침묵 폴백을 금지한다 (SPEC D-11 · 6.2 오프라인 동작 정의 #3).
   ============================================================ */
window.FIRSTHOME_POLICY_RULES = {
  "$activePredicate": "status = 'approved' AND (effective_from IS NULL OR effective_from <= now) AND (effective_to IS NULL OR now < effective_to) — SPEC 2.3. 이 배열은 승인된 규칙 **전부**이며, 소비자가 자기 시각으로 이 술어를 적용한다. 적용하지 않으면 종료된 규칙이 판정에 실린다.",
  "$generated": {
    "artifact": "web-policy-rules",
    "command": "python scripts/gen_contracts.py",
    "doNotEdit": true,
    "engineVersion": "3.0.0",
    "global": "FIRSTHOME_POLICY_RULES",
    "noSilentFallback": "이 파일이 없으면 window.FIRSTHOME_POLICY_RULES 은 undefined 다. 기본값·빈 값으로 대체하지 않는다. 판정 경로를 끄고 화면에 명시한다 (SPEC D-11).",
    "shapeDocumentedIn": "contracts/README.md 결정 #34",
    "source": "store 의 승인된 RuleVersion (SPEC 1.2 · D-11 · 2.3)"
  },
  "$noRuleFunctions": "요건은 데이터다. 이 파일은 판정 함수를 담지 않는다 — 해석기는 소비자가 쓰고, 그 해석은 backend/src/firsthome/engines/eligibility.py 와 같아야 한다 (SPEC D-11).",
  "criteriaFields": [
    "ageMax",
    "ageMin",
    "annualIncomeMaxKRW",
    "assetMaxKRW",
    "regionPrefixes",
    "requireHomeless",
    "requireNewlywed",
    "requireSME"
  ],
  "ruleVersions": [
    {
      "payload": {
        "category": "대출",
        "conditionalChecks": [],
        "criteria": {
          "ageMax": 34,
          "ageMin": 19,
          "annualIncomeMaxKRW": 50000000,
          "assetMaxKRW": 337000000,
          "regionPrefixes": [],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.",
        "id": "buttress_youth",
        "maxAmountKRW": 200000000,
        "name": "청년전용 버팀목전세자금대출",
        "notes": [
          "세대주(예비 세대주 포함) 요건 및 임차 전용면적·보증금 한도는 취급 은행에서 최종 확인이 필요합니다."
        ],
        "rateRangePct": [
          1.5,
          2.9
        ],
        "source": "주택도시기금",
        "summary": "무주택 청년의 전세보증금을 저리로 지원하는 주택도시기금 대출"
      },
      "policyId": "buttress_youth",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "주택도시기금",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:buttress_youth",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "대출",
        "conditionalChecks": [],
        "criteria": {
          "ageMax": 34,
          "ageMin": 19,
          "annualIncomeMaxKRW": 50000000,
          "assetMaxKRW": 337000000,
          "regionPrefixes": [],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.",
        "id": "youth_monthly_loan",
        "maxAmountKRW": 45000000,
        "name": "청년전용 보증부월세대출",
        "rateRangePct": [
          1.0,
          1.3
        ],
        "source": "주택도시기금",
        "summary": "보증금과 월세를 함께 지원하는 청년 전용 주택도시기금 대출"
      },
      "policyId": "youth_monthly_loan",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "주택도시기금",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:youth_monthly_loan",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "대출",
        "conditionalChecks": [],
        "criteria": {
          "ageMax": 200,
          "ageMin": 19,
          "annualIncomeMaxKRW": 75000000,
          "assetMaxKRW": 337000000,
          "regionPrefixes": [],
          "requireHomeless": true,
          "requireNewlywed": true,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.",
        "id": "newlywed_jeonse",
        "maxAmountKRW": 300000000,
        "name": "신혼부부 전용 전세자금대출",
        "rateRangePct": [
          1.5,
          2.7
        ],
        "source": "주택도시기금",
        "summary": "혼인 기간 요건을 충족하는 신혼부부 대상 전세자금 대출"
      },
      "policyId": "newlywed_jeonse",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "주택도시기금",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:newlywed_jeonse",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "지원금",
        "conditionalChecks": [
          "원가구(부모) 소득·자산 요건이 별도로 적용될 수 있습니다."
        ],
        "criteria": {
          "ageMax": 34,
          "ageMin": 19,
          "annualIncomeMaxKRW": 30000000,
          "assetMaxKRW": 122000000,
          "regionPrefixes": [],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 관할 지자체 공고 기준을 따릅니다.",
        "id": "youth_rent_support",
        "maxAmountKRW": 4800000,
        "name": "청년월세 한시 특별지원",
        "rateRangePct": [
          0.0,
          0.0
        ],
        "source": "국토교통부",
        "summary": "저소득 무주택 청년에게 월세 일부를 현금으로 지원하는 제도"
      },
      "policyId": "youth_rent_support",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "국토교통부",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:youth_rent_support",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "지원금",
        "conditionalChecks": [
          "지자체 예산 소진 시 조기 마감될 수 있으며, 모집 공고 기간에만 신청할 수 있습니다."
        ],
        "criteria": {
          "ageMax": 39,
          "ageMin": 19,
          "annualIncomeMaxKRW": 30000000,
          "assetMaxKRW": 122000000,
          "regionPrefixes": [
            "11"
          ],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 관할 지자체 공고 기준을 따릅니다.",
        "id": "seoul_youth_rent",
        "maxAmountKRW": 2400000,
        "name": "서울시 청년월세지원",
        "rateRangePct": [
          0.0,
          0.0
        ],
        "source": "서울특별시",
        "summary": "서울 거주 청년 1인가구에 월세를 한시적으로 지원"
      },
      "policyId": "seoul_youth_rent",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "서울특별시",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:seoul_youth_rent",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "이자지원",
        "conditionalChecks": [],
        "criteria": {
          "ageMax": 39,
          "ageMin": 19,
          "annualIncomeMaxKRW": 47000000,
          "assetMaxKRW": 337000000,
          "regionPrefixes": [
            "11"
          ],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 협약 금융기관 고시 기준을 따릅니다.",
        "id": "seoul_deposit_interest",
        "maxAmountKRW": 200000000,
        "name": "서울시 청년 임차보증금 이자지원",
        "rateRangePct": [
          0.0,
          2.0
        ],
        "source": "서울특별시",
        "summary": "서울 거주 청년의 임차보증금 대출 이자 일부를 서울시가 지원"
      },
      "policyId": "seoul_deposit_interest",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "서울특별시",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:seoul_deposit_interest",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "저축",
        "conditionalChecks": [],
        "criteria": {
          "ageMax": 34,
          "ageMin": 19,
          "annualIncomeMaxKRW": 50000000,
          "assetMaxKRW": 1000000000,
          "regionPrefixes": [],
          "requireHomeless": true,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.",
        "id": "housing_dream_savings",
        "maxAmountKRW": 50000000,
        "name": "청년 주택드림 청약통장",
        "rateRangePct": [
          2.0,
          4.5
        ],
        "source": "주택도시기금",
        "summary": "청약 기능과 우대금리를 결합한 청년 전용 주택청약 저축"
      },
      "policyId": "housing_dream_savings",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "주택도시기금",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:housing_dream_savings",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    },
    {
      "payload": {
        "category": "보증",
        "conditionalChecks": [
          "주택 유형·전세가율·선순위 채권 규모에 따라 보증 가입이 제한될 수 있습니다."
        ],
        "criteria": {
          "ageMax": 200,
          "ageMin": 0,
          "annualIncomeMaxKRW": 1000000000,
          "assetMaxKRW": 10000000000,
          "regionPrefixes": [],
          "requireHomeless": false,
          "requireNewlywed": false,
          "requireSME": false
        },
        "disclaimer": "프로토타입 시연용 예시 수치입니다. 실제 조건은 보증기관 고시 기준을 따릅니다.",
        "id": "hug_deposit_guarantee",
        "maxAmountKRW": 700000000,
        "name": "전세보증금반환보증",
        "rateRangePct": [
          0.1,
          0.2
        ],
        "source": "주택도시보증공사(HUG)",
        "summary": "임대인이 보증금을 돌려주지 못할 때 보증기관이 대신 지급하는 보증 상품"
      },
      "policyId": "hug_deposit_guarantee",
      "provenance": {
        "fetched_at": null,
        "observed_at": null,
        "source_kind": "statute",
        "source_name": "주택도시보증공사(HUG)",
        "source_ref": null,
        "verification": "unverified"
      },
      "ruleVersion": {
        "approved_by": null,
        "effective_from": null,
        "effective_to": null,
        "id": "seed:hug_deposit_guarantee",
        "origin": "seed",
        "status": "approved",
        "supersedes": null
      }
    }
  ]
};
