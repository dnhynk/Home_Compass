/* ============================================================
   생성물이다. 손으로 고치지 않는다 (SPEC D-11 · 1.2).

   재생성 : python scripts/gen_contracts.py
   검사   : python scripts/gen_contracts.py --check
   원본   : contracts/openapi.json 의 x- 확장 (SPEC D-12 · 8.3 #3 · #4)
   모양   : contracts/README.md 결정 #34

   손으로 고치면 backend/tests/crosscheck/test_generated_frontend_diff.py 의
   바이트 비교가 깨진다. 되돌리려면 위 재생성 명령을 돌린다.

   이 파일이 없거나 로드에 실패하면 window.HOME_COMPASS_CONTRACT_CONSTANTS 은 undefined 다.
   소비자는 그 자리에서 로컬 판정 경로를 끄고 화면에 명시한다 — 기본값으로 메우는
   침묵 폴백을 금지한다 (SPEC D-11 · 6.2 오프라인 동작 정의 #3).
   ============================================================ */
window.HOME_COMPASS_CONTRACT_CONSTANTS = {
  "$generated": {
    "artifact": "web-contract-constants",
    "command": "python scripts/gen_contracts.py",
    "doNotEdit": true,
    "engineVersion": "3.0.0",
    "global": "HOME_COMPASS_CONTRACT_CONSTANTS",
    "noSilentFallback": "이 파일이 없으면 window.HOME_COMPASS_CONTRACT_CONSTANTS 은 undefined 다. 기본값·빈 값으로 대체하지 않는다. 판정 경로를 끄고 화면에 명시한다 (SPEC D-11).",
    "shapeDocumentedIn": "contracts/README.md 결정 #34",
    "source": "contracts/openapi.json 의 x- 확장 (SPEC 8.3 #3 · #4)",
    "sourcePointers": {
      "apiContractVersion": "/info/version",
      "boundaryConditions": "/x-boundary-conditions",
      "rounding": "/x-rounding",
      "units": "/x-units"
    }
  },
  "$timeoutLookup": "clientDispatch.byPath[path] 로 프로필 이름을 찾고, 없으면 clientDispatch.default 를 쓴다. 그 프로필의 clientTimeoutMs 가 값이다. 경로별 예산을 하나로 합치지 않는다 (SPEC 8.3 #6 · 8.3 정정).",
  "apiContractVersion": "2.0.0",
  "boundaryConditions": {
    "$comment": "SPEC 8.3. 타임아웃·재시도는 계약 파일의 x- 확장에만 존재하고 코드에 직접 쓰지 않는다(8.3 #3). 서버와 클라이언트가 같은 파일에서 읽는다(8.3 #4).",
    "$decidedBy": "코디네이터 (SPEC 8.2 #5), W-platform 실측 보고에 근거. 2026-08-13.",
    "$rule": "클라이언트 타임아웃 > 서버 응답 예산 + 마진 (8.3 #2). 역전되면 정상 응답이 폴백으로 처리된다.",
    "$structure": "경로별이다. 평면 구조를 쓰지 않는다 — 셋의 지연 성격이 완전히 다르므로 하나로 뭉치면 chat 기준으로 잡혀 analyze 가 75초를 기다리거나, analyze 기준으로 잡혀 chat 이 다시 잘린다. 후자가 예선 사고 그 자체다. 계약이 그 사고를 다시 가능하게 만드는 형태여서는 안 된다.",
    "clientDispatch": {
      "$comment": "frontend/app.js 의 timeoutFor(path) 와 같은 모양이다 — 특정 경로 둘을 먼저 가르고 나머지를 기본값으로 떨어뜨린다.",
      "byPath": {
        "/api/analyze": "analyze",
        "/api/chat": "chat"
      },
      "default": "read"
    },
    "profiles": {
      "analyze": {
        "$budgetComment": "1,000ms 는 실측 p99 5.1ms 의 약 200배다. 이 간극은 의도된 것이다 — 시연 노트북 사양과 실데이터 유입 후의 정책·지역 순회 증가를 흡수한다. 실측이 더 빨라져도 계약은 바뀌지 않고, 1,000ms 를 넘기면 그것은 회귀다.",
        "$retriesComment": "판정은 결정론적이다(원칙 1). 재시도는 같은 답을 같은 시간에 낼 뿐이므로 지연만 두 배가 된다.",
        "appliesTo": [
          "/api/analyze"
        ],
        "budgetIsAPromiseNotAMeasurement": true,
        "clientTimeoutMs": 5000,
        "measurement": {
          "$providerComment": "/api/analyze 는 원칙 1 에 따라 LLM 을 부르지 않으므로 프로바이더 모드가 이 분포에 영향을 주지 않는다.",
          "coldFirstRequestMs": 22.5,
          "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
          "maxMs": 11.5,
          "measured": true,
          "measuredAt": "2026-08-13",
          "p50Ms": 2.8,
          "p90Ms": 3.8,
          "p95Ms": 4.0,
          "p99Ms": 5.1,
          "providerMode": "offline",
          "report": "backend/tests/api/artifacts/analyze_latency.md",
          "samples": 800,
          "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. 순차 호출, 커넥션 재사용, 프로필 4종 x 200회.",
          "script": "scripts/measure_latency.py"
        },
        "onTimeout": {
          "display": "폴백했다는 사실을 화면에 명시한다. 침묵 폴백을 금지한다 (SPEC 6.2 오프라인 동작 정의 #3 · D-11).",
          "silentFallback": false
        },
        "retries": 0,
        "serverResponseBudgetMs": 1000
      },
      "chat": {
        "$budgetComment": "**서버 응답 예산 개념이 성립하지 않는다.** 지연을 정하는 것이 우리 코드가 아니라 외부 프로바이더이므로, 예산을 적으면 지킬 수 없는 약속이 된다.",
        "$retriesComment": "프로바이더 호출에는 이미 서버측 재시도가 있다. 클라이언트가 또 걸면 이중이 되어 최악 지연이 곱해진다.",
        "appliesTo": [
          "/api/chat"
        ],
        "clientTimeoutMs": 75000,
        "measurement": {
          "$followUp": "라이브 LLM 지연 측정은 실사 항목이다 (코디네이터가 목록에 올린다).",
          "$valueOrigin": "75,000 은 현행 frontend/app.js 값을 유지한 것이며 측정에서 유도되지 않았다. app.js 주석이 기록한 관측(단일 툴콜 2.7~4.5초, 4툴 턴 약 10초)은 예선 기록이지 우리 측정이 아니다.",
          "$whyNotMeasured": "라이브 LLM 왕복은 API 키와 호출 비용을 요구한다. 키 없이 도는 offline 템플릿 경로만 쟀고, 그 값은 이 타임아웃의 근거가 되지 못한다 — offline 은 프로바이더를 아예 부르지 않는다.",
          "measured": false,
          "offlineTemplatePath": {
            "$comment": "참고용. 이 값으로 타임아웃을 정하지 않는다.",
            "maxMs": 4.2,
            "measuredAt": "2026-08-13",
            "p50Ms": 3.1,
            "samples": 20,
            "script": "scripts/measure_latency.py"
          }
        },
        "onTimeout": {
          "display": "폴백했다는 사실을 화면에 명시한다. 침묵 폴백을 금지한다 (SPEC 6.2 오프라인 동작 정의 #3 · D-11).",
          "silentFallback": false
        },
        "retries": 0,
        "serverResponseBudgetMs": null
      },
      "read": {
        "$budgetComment": "현행 4,500ms 에서 낮춘다. D-8 이 로컬 단일 호스트를 못박았으므로 이 셋이 초 단위로 늘어나면 그것은 사고이고, 헐거운 타임아웃은 사고를 숨긴다.",
        "appliesTo": [
          "/api/health",
          "/api/regions",
          "/api/meta",
          "/api/auth/login",
          "/api/auth/logout",
          "/api/auth/session",
          "/api/admin/drafts",
          "/api/admin/drafts/{draft_id}",
          "/api/admin/drafts/{draft_id}/impact",
          "/api/admin/drafts/batch-approve",
          "/api/admin/drafts/{draft_id}/approve",
          "/api/admin/drafts/{draft_id}/reject",
          "/api/admin/audit",
          "/api/reports",
          "/api/admin/reports",
          "/api/admin/status"
        ],
        "budgetIsAPromiseNotAMeasurement": true,
        "clientTimeoutMs": 3000,
        "measurement": {
          "$aggregateComment": "위 세 값은 경로별 최악값이다. 평균이 아니다 — 타임아웃은 최악을 견뎌야 한다.",
          "$perPathStaleness": {
            "$comment": "이 행은 SPEC 8.1 추가 이전의 코드 경로를 잰 값이다. 그때 /api/health 는 저장소를 열지 않았고 지금은 연다.",
            "$whenToRemove": "read 프로필을 한 머신에서 다시 전수 측정해 perPath 세 행을 함께 갱신할 때 이 블록을 지운다.",
            "$whyNotPromoted": "이 실행의 세 GET 이 2026-08-13 대비 전부 4~6배 느리다 — 손대지 않은 /api/meta 까지 그렇다. 머신 상태 차이를 이 변경의 비용인 척 계약에 새겨 넣지 않는다. /api/health 행만 이 실행의 숫자로 갈아 끼우면 나머지 두 행과 다른 머신의 값이 한 표에 나란히 서고, 그 표는 경로 간 비교가 불가능해진다. 세 행을 다 갈아 끼우는 것은 기준 머신의 측정을 버리는 일이라 코디네이터 판단이다 (SPEC 8.2 #5).",
            "changedBy": "SPEC 8.1 — batch · freshness 추가. 요청마다 store_from_env() 로 저장소를 한 번 연다.",
            "path": "/api/health",
            "reprobe": {
              "$comment": "참고용. 위 perPath 를 대체하지 않는다.",
              "$verdict": "최악 11.9ms 로 serverResponseBudgetMs=500 의 약 2.4% 다. 예산을 고칠 이유가 없다.",
              "control": {
                "$comment": "★ 같은 실행 안의 대조군. 2026-08-13 값과의 차이는 이 변경이 아니라 머신 상태가 대부분이므로(손대지 않은 /api/meta 도 1.4 -> 2.2 로 움직였고 /api/analyze 는 2.8 -> 10.4 다), 비교는 **같은 실행 안에서** 해야 한다.",
                "$reading": "/api/meta 는 저장소를 열지 않고 나머지 둘은 연다. /api/health 가 /api/regions 와 같은 값이 됐다는 것이 이 변경의 비용이 곧 [저장소 열기 한 번] 이라는 뜻이다.",
                "/api/meta": {
                  "maxMs": 3.9,
                  "p50Ms": 2.2,
                  "p95Ms": 3.1
                },
                "/api/regions": {
                  "maxMs": 9.7,
                  "p50Ms": 6.3,
                  "p95Ms": 8.3
                }
              },
              "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
              "maxMs": 11.9,
              "measuredAt": "2026-08-15",
              "p50Ms": 6.3,
              "p95Ms": 8.8,
              "samples": 200,
              "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. uvicorn 실기동에 경로당 200회 순차 호출.",
              "script": "scripts/measure_latency.py"
            }
          },
          "environment": "Windows 11 / Python 3.13.7 / 개발 머신 (시연 노트북이 아니다)",
          "maxMs": 4.6,
          "measured": true,
          "measuredAt": "2026-08-13",
          "p50Ms": 1.4,
          "p95Ms": 2.0,
          "perPath": {
            "/api/health": {
              "maxMs": 1.9,
              "p50Ms": 0.9,
              "p95Ms": 1.4
            },
            "/api/meta": {
              "maxMs": 2.5,
              "p50Ms": 1.4,
              "p95Ms": 2.0
            },
            "/api/regions": {
              "maxMs": 4.6,
              "p50Ms": 1.0,
              "p95Ms": 1.5
            }
          },
          "providerMode": "offline",
          "report": "backend/tests/api/artifacts/analyze_latency.md",
          "samples": 600,
          "scope": "루프백 HTTP 왕복을 포함한 클라이언트 벽시계. 경로당 200회.",
          "script": "scripts/measure_latency.py",
          "unmeasuredPaths": {
            "$comment": "read.appliesTo 중 재현 가능한 측정 근거가 없는 경로. measured:true 가 프로필 전체를 덮는다고 읽히는 것을 막는다.",
            "$valueOrigin": "이 경로들은 read 프로필의 기존 값(clientTimeoutMs 3000 · serverResponseBudgetMs 500)을 물려받았다. 값이 이 경로들의 측정에서 유도되지 않았다.",
            "$whyNotMeasured": "재현 가능한 측정 스크립트가 없다. scripts/measure_latency.py 는 코디네이터 소유라 4단계 워커도 5단계 워커도 경로를 더할 수 없었다. 5단계가 더한 셋(/api/admin/drafts/{draft_id} · .../impact · .../batch-approve)은 앞의 넷보다 무거울 여지가 있다 — 특히 /impact 는 회귀 프로필 12건에 대해 판정을 **두 번씩** 돌린다. 그 사실을 재지 않고 적어 둔다. 6-A 가 더한 둘(/api/reports · /api/admin/reports)도 재지 않았다 — 신고 큐 조회는 신고 수만큼 늘어나는 조회이고, 신고 빈도가 얼마인지는 SPEC 6.4 가 [잠정]이라고 적어 둔 바로 그 미지수다.",
            "loginProbe": {
              "$comment": "참고용. **이 값으로 타임아웃을 정하지 않는다** (chat.measurement.offlineTemplatePath 와 같은 규약). /api/auth/login 만 Argon2id 해싱 때문에 예산에 닿을 여지가 있어 한 번 재 본 것이며, 재현 가능한 커밋된 스크립트가 없으므로 measurement 자리로 승격하지 않는다.",
              "$verdict": "최악 94.4ms 로 serverResponseBudgetMs=500 의 약 19% 다. 예산을 고칠 이유가 없다. 반대로 이 값이 500ms 를 넘겼다면 고칠 것은 Argon2id 파라미터가 아니라 예산이었을 것이다 — 해싱이 느린 것은 결함이 아니라 그 함수의 목적이다.",
              "environment": "Windows 11 / Python 3.13.7 / argon2-cffi 25.1.0 / 개발 머신 (시연 노트북이 아니다)",
              "maxMs": 94.4,
              "measuredAt": "2026-08-14",
              "p50Ms": 55.7,
              "p95Ms": 88.1,
              "samples": 60,
              "scope": "루프백 HTTP 왕복. uvicorn 실기동에 60회 순차 로그인."
            },
            "paths": [
              "/api/auth/login",
              "/api/auth/logout",
              "/api/auth/session",
              "/api/admin/drafts",
              "/api/admin/drafts/{draft_id}",
              "/api/admin/drafts/{draft_id}/impact",
              "/api/admin/drafts/batch-approve",
              "/api/admin/drafts/{draft_id}/approve",
              "/api/admin/drafts/{draft_id}/reject",
              "/api/admin/audit",
              "/api/reports",
              "/api/admin/reports",
              "/api/admin/status"
            ]
          }
        },
        "onTimeout": {
          "display": "폴백했다는 사실을 화면에 명시한다. 침묵 폴백을 금지한다 (SPEC 6.2 오프라인 동작 정의 #3 · D-11).",
          "silentFallback": false
        },
        "retries": 0,
        "serverResponseBudgetMs": 500
      }
    }
  },
  "rounding": {
    "$comment": "SPEC 8.2 #4. 응답의 수치와 화면 표시 문자열은 다른 규칙을 따른다. 그 구분이 없으면 예선의 80만/81만 사고가 재발한다.",
    "displayFormatting": {
      "$arbiter": "contracts/format_golden.json. 이 서술과 픽스처가 어긋나면 픽스처가 정본이다.",
      "$status": "확정 — SPEC 9.1.1 · 계약 결정 #16. 정본 픽스처는 contracts/format_golden.json 이며 파이썬과 JS 두 구현이 **같은 파일에 대해** 테스트된다. 정본을 고른 기준은 언어가 아니라 하나뿐이다 — **정보를 버리지 않는 쪽.**",
      "money": "만원 단위 **half-up** 반올림(은행가 반올림 아님 — 25,000원은 '3만원'이다). **부호를 보존한다**(-750,000 → '-75만원'). 1억 이상은 '<억>억 <만>만원', 1만 이상은 '<만>만원', 그 미만은 '<원>원'. 억 경계에서 만 자리가 올림되면 자리올림한다(199,999,000 → '2억원').",
      "pct": "**고정 소수 자릿수**. 무의미한 0 을 제거하지 않는다(pct(25.0, 1) → '25.0%'). 제거하면 정확한 25 와 반올림된 25 가 구분되지 않는데, F-1 이후 슈바베지수가 측정값이라 그 정밀도가 정보를 담는다."
    },
    "engineInternal": {
      "depositRoundingUnitKRW": "ModelConstant tco.deposit_rounding_unit_krw",
      "floorTo": "backend common.floor_to(value, unit) — unit 단위 내림, 0 하한. 기본 unit 은 10,000원(만원).",
      "monthlyRoundingUnitKRW": "ModelConstant tco.monthly_rounding_unit_krw"
    },
    "responseValues": "응답의 정수 금액은 엔진이 만든 값이다. 소비자가 다시 반올림하지 않는다."
  },
  "units": {
    "$comment": "SPEC 8.2 #4 · D-12. 필드명 접미사가 단위를 결정한다. 접미사가 없는 수치 필드는 아래에 전수 열거하며, 열거되지 않은 것이 생기면 교차 테스트가 실패한다.",
    "$keyFormat": "<components.schemas 이름>/<property 이름>",
    "enforcedBy": "backend/tests/crosscheck/test_openapi_contract.py",
    "fieldSuffix": {
      "KRW": {
        "jsonType": "integer",
        "note": "원 단위 정수. 응답에 실리는 금액은 엔진 계산값 그대로이며 표시용 반올림이 적용되지 않았다.",
        "unit": "원"
      },
      "Pct": {
        "jsonType": "number",
        "note": "60.0 은 60% 그 자체다. 100 으로 나누지 않는다 (model_constants.json 의 percent_level 과 같은 규약).",
        "unit": "퍼센트 포인트"
      }
    },
    "unsuffixedNumericFields": {
      "AffordabilityBreakdown/buffer": "원",
      "AffordabilityBreakdown/existingDebt": "원",
      "AffordabilityBreakdown/livingCost": "원",
      "AffordabilityBreakdown/netIncome": "원",
      "ChatResponse/attempts": "회 (템플릿으로 전환하기 전 제공자 호출 시도 횟수, 정상 응답이면 생략)",
      "ChatResponse/retried": "회 (성공 응답 전 재시도 횟수, 재시도하지 않으면 생략)",
      "DataGradeReason/provenanceIndex": "단위 없음 — `provenance` 배열의 0-기반 인덱스다. 사실에 걸리지 않는 사유(`freshness_not_evaluated`)는 `null` 이다.",
      "ImpactResponse/changedCount": "건 (판정이 달라진 프로필 수)",
      "ImpactResponse/profileCount": "건 (회귀 프로필 수)",
      "ProfileRequest/age": "세",
      "ProfileRequest/householdSize": "명",
      "Risk/score": "점 (0~100 척도)",
      "Scenario/fitScore": "점 (0~100 척도)",
      "ScenarioComponents/insurance": "원",
      "ScenarioComponents/interest": "원",
      "ScenarioComponents/maintenance": "원",
      "ScenarioComponents/opportunityCost": "원",
      "ScenarioComponents/rent": "원",
      "SourceView/length": "코드포인트 (SPEC 4.2.1 · UTF-16 코드유닛 아님)",
      "SpanView/end": "코드포인트 인덱스 (반열린 구간의 끝, 제외)",
      "SpanView/occurrences": "회 (이 인용이 원문에 나타나는 횟수)",
      "SpanView/start": "코드포인트 인덱스 (반열린 구간의 시작, 포함)",
      "StatusBatch/failed": "회",
      "StatusBatch/runs": "회 (market.run 감사 행 수 = 시세 수집 배치 실행 횟수)",
      "StatusBatch/succeeded": "회",
      "StatusExtraction/drafts": "건 (추출을 시도한 초안 수)",
      "StatusExtraction/failed": "건 (검증에서 거부된 초안 수)",
      "StatusFreshness/oldestAgeDays": "일 — 가장 오래된 `fetched_at` 으로부터 지난 날짜. **판정이 아니라 관측이다** — 신선도 임계가 미정이라 이 수가 `stale` 을 뜻하지 않는다 (계약 결정 #39). 수집 이력이 없으면 `null` 이며 0 이 아니다.",
      "StatusFreshness/regions": "개 (등재된 Region 수)",
      "StatusLatency/max": "단위 없음 — `StatusLatency/p50` 와 같다.",
      "StatusLatency/p50": "단위 없음 — 값의 단위는 같은 객체의 `unit` 필드가 싣는다 (채팅은 `ms`, 추출은 `s`). 표본이 0 이면 `null` 이며 0 이 아니다.",
      "StatusLatency/samples": "건 (지연이 기록된 호출 수. 호출 수와 다를 수 있다)",
      "StatusLlmChannel/calls": "회 (LLM 호출 수)",
      "StatusLlmChannel/failed": "회",
      "StatusLlmChannel/succeeded": "회",
      "StatusLog/records": "줄 (파일 로그에서 읽어낸 JSON 줄 수)",
      "StatusLog/unreadableLines": "줄 (JSON 으로 해석되지 않은 줄 수. 0 이 아니면 위 분모가 모자란다)",
      "StatusLog/writeFailures": "회 (파일에 쓰지 못한 횟수. 0 이 아니면 LLM 지표가 실제보다 적다)",
      "StatusQueue/longestWaitDays": "일 — 가장 오래 기다린 초안의 대기 일수. **초과 여부가 아니다** — SLA N 이 미정이라 이 화면은 초과를 판정하지 않는다 (SPEC 7.3). 대기 건수가 0 이면 `null` 이다.",
      "StatusQueue/pending": "건 (승인 대기 중인 초안 수)",
      "StatusReports/longestOpenDays": "일 — 가장 오래된 미종결 신고의 경과 일수. 없으면 `null`.",
      "StatusReports/open": "건 (닫히지 않은 신고 수 — **누적이다**, 밀린 일이 아니다)",
      "StatusReports/total": "건 (신고 전수)"
    }
  }
};
