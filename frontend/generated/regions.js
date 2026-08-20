/* ============================================================
   생성물이다. 손으로 고치지 않는다 (SPEC D-11 · 1.2).

   재생성 : python scripts/gen_contracts.py
   검사   : python scripts/gen_contracts.py --check
   원본   : store 의 Region (SPEC D-11 · D-5 · 6.2 오프라인 정의 #2)
   모양   : contracts/README.md 결정 #34

   손으로 고치면 backend/tests/crosscheck/test_generated_frontend_diff.py 의
   바이트 비교가 깨진다. 되돌리려면 위 재생성 명령을 돌린다.

   이 파일이 없거나 로드에 실패하면 window.FIRSTHOME_REGIONS 은 undefined 다.
   소비자는 그 자리에서 로컬 판정 경로를 끄고 화면에 명시한다 — 기본값으로 메우는
   침묵 폴백을 금지한다 (SPEC D-11 · 6.2 오프라인 동작 정의 #3).
   ============================================================ */
window.FIRSTHOME_REGIONS = {
  "$factFields": [
    "conversionRatePct",
    "guaranteeAvailable",
    "jeonseMedianKRW",
    "jeonseRatioPct",
    "maintenanceFeeKRW",
    "marketRisk",
    "monthlyDepositKRW",
    "monthlyRentKRW"
  ],
  "$generated": {
    "artifact": "web-regions",
    "command": "python scripts/gen_contracts.py",
    "doNotEdit": true,
    "engineVersion": "3.0.0",
    "global": "FIRSTHOME_REGIONS",
    "noSilentFallback": "이 파일이 없으면 window.FIRSTHOME_REGIONS 은 undefined 다. 기본값·빈 값으로 대체하지 않는다. 판정 경로를 끄고 화면에 명시한다 (SPEC D-11).",
    "shapeDocumentedIn": "contracts/README.md 결정 #34",
    "source": "store 의 Region (SPEC 1.2 · D-11 · D-5)"
  },
  "$provenanceLayers": "payload.source 는 provenance.source_name 이 한 줄로 접힌 화면 문구다. 기계 판독의 정본은 provenance(레코드 요약)와 fieldProvenance(사실 단위)이며, 요약은 필드별 계보의 최악값이다 (SPEC 2.4 — 가장 나쁜 것이 이긴다).",
  "$readFieldProvenanceNotTheRecordSummary": "필드별 계보는 **서로 다를 수 있다.** 레코드 요약(provenance)은 그 최악값이므로 (SPEC 2.4 — 가장 나쁜 것이 이긴다) 요약으로 접으면 더 나은 계보를 가진 필드가 과소 진술된다. 소비자는 fieldProvenance 를 필드 단위로 읽고, 값이 같아 보인다고 레코드 요약으로 접지 않는다. ★ 이 문장은 시점을 적지 않는다 — 앞 판이 「지금은 8필드가 전부 같다」고 적었다가 8단계 1부(결정 #40)가 시드를 실수집으로 굳히면서 조용히 거짓이 됐다. 지금 어떤지는 이 파일의 fieldProvenance 가 말한다.",
  "regions": [
    {
      "code": "11440",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-10T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "서울 마포구",
      "payload": {
        "code": "11440",
        "conversionRatePct": 4.82,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 650000000,
        "jeonseRatioPct": 43.27,
        "maintenanceFeeKRW": 90000,
        "marketRisk": "low",
        "monthlyDepositKRW": 100000000,
        "monthlyRentKRW": 950000,
        "name": "서울 마포구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "11620",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-12T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "서울 관악구",
      "payload": {
        "code": "11620",
        "conversionRatePct": 4.62,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 500000000,
        "jeonseRatioPct": 55.7,
        "maintenanceFeeKRW": 70000,
        "marketRisk": "medium",
        "monthlyDepositKRW": 80000000,
        "monthlyRentKRW": 680000,
        "name": "서울 관악구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "11200",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-06T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "서울 성동구",
      "payload": {
        "code": "11200",
        "conversionRatePct": 4.74,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 729000000,
        "jeonseRatioPct": 39.73,
        "maintenanceFeeKRW": 100000,
        "marketRisk": "low",
        "monthlyDepositKRW": 100000000,
        "monthlyRentKRW": 1100000,
        "name": "서울 성동구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "11350",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-12T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "서울 노원구",
      "payload": {
        "code": "11350",
        "conversionRatePct": 4.94,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 300000000,
        "jeonseRatioPct": 54.12,
        "maintenanceFeeKRW": 70000,
        "marketRisk": "medium",
        "monthlyDepositKRW": 37045000,
        "monthlyRentKRW": 700000,
        "name": "서울 노원구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "41117",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-13T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "경기 수원시 영통구",
      "payload": {
        "code": "41117",
        "conversionRatePct": 5.0,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 330000000,
        "jeonseRatioPct": 61.33,
        "maintenanceFeeKRW": 80000,
        "marketRisk": "medium",
        "monthlyDepositKRW": 50000000,
        "monthlyRentKRW": 800000,
        "name": "경기 수원시 영통구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "41281",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "경기 고양시 덕양구",
      "payload": {
        "code": "41281",
        "conversionRatePct": 5.0,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 330000000,
        "jeonseRatioPct": 71.1,
        "maintenanceFeeKRW": 70000,
        "marketRisk": "medium",
        "monthlyDepositKRW": 50000000,
        "monthlyRentKRW": 500000,
        "name": "경기 고양시 덕양구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "26350",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "부산 해운대구",
      "payload": {
        "code": "26350",
        "conversionRatePct": 5.08,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 254775000,
        "jeonseRatioPct": 60.02,
        "maintenanceFeeKRW": 70000,
        "marketRisk": "low",
        "monthlyDepositKRW": 30000000,
        "monthlyRentKRW": 800000,
        "name": "부산 해운대구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "30200",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "대전 유성구",
      "payload": {
        "code": "30200",
        "conversionRatePct": 5.23,
        "guaranteeAvailable": true,
        "jeonseMedianKRW": 250000000,
        "jeonseRatioPct": 73.3,
        "maintenanceFeeKRW": 60000,
        "marketRisk": "medium",
        "monthlyDepositKRW": 47210000,
        "monthlyRentKRW": 220000,
        "name": "대전 유성구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "27260",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-13T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "대구 수성구",
      "payload": {
        "code": "27260",
        "conversionRatePct": 5.14,
        "guaranteeAvailable": false,
        "jeonseMedianKRW": 300000000,
        "jeonseRatioPct": 59.26,
        "maintenanceFeeKRW": 65000,
        "marketRisk": "high",
        "monthlyDepositKRW": 20000000,
        "monthlyRentKRW": 750000,
        "name": "대구 수성구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    },
    {
      "code": "12330",
      "fieldProvenance": {
        "conversionRatePct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털) — 한국부동산원 전월세전환율 산식 적용 · 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). 인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 아파트 대응 페이지는 찾지 못했다",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "guaranteeAvailable": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "jeonseMedianKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "jeonseRatioPct": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)",
          "source_ref": "https://www.data.go.kr/data/15126469/openapi.do",
          "verification": "verified"
        },
        "maintenanceFeeKRW": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "marketRisk": {
          "fetched_at": null,
          "observed_at": null,
          "source_kind": "market",
          "source_name": "프로토타입 예시 데이터",
          "source_ref": null,
          "verification": "unverified"
        },
        "monthlyDepositKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        },
        "monthlyRentKRW": {
          "fetched_at": "2026-08-15T19:49:32.142041+09:00",
          "observed_at": "2026-08-14T00:00:00+09:00",
          "source_kind": "market",
          "source_name": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
          "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
          "verification": "verified"
        }
      },
      "name": "광주 광산구",
      "payload": {
        "code": "12330",
        "conversionRatePct": 5.71,
        "guaranteeAvailable": false,
        "jeonseMedianKRW": 163650000,
        "jeonseRatioPct": 78.16,
        "maintenanceFeeKRW": 55000,
        "marketRisk": "high",
        "monthlyDepositKRW": 20000000,
        "monthlyRentKRW": 450000,
        "name": "광주 광산구",
        "source": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"
      },
      "provenance": {
        "fetched_at": "2026-08-15T19:49:32.142041+09:00",
        "observed_at": "2026-08-14T00:00:00+09:00",
        "source_kind": "market",
        "source_name": "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)",
        "source_ref": "https://www.data.go.kr/data/15126474/openapi.do",
        "verification": "unverified"
      }
    }
  ]
};
