"""추출 검증 테스트가 공유하는 픽스처 — **키 없이 도는 후반부의 입력**이다 (SPEC 9.2.1).

원문 픽스처는 일부러 작지만, **정규화 유혹을 두 군데 심어 두었다.**

  - `만\\u00a019세` — NBSP. NFC 는 U+00A0 을 건드리지 않는다 (NFKC 만 건드린다)
  - `５천만원` — 전각 숫자. 역시 NFC 는 유지하고 NFKC 만 반각으로 접는다

SPEC 4.2.1 은 「검증 시점에 추가 정규화(공백 접기 · 전각/반각 변환)를 하지 않는다」고
못 박았다. 검증기가 저 둘을 흡수하기 시작하면 무엇이든 통과하며, 그 순간 4.2 의
「핵심 방어」가 사라진다. 두 줄은 그 유혹을 실제로 걸어 보기 위해 있다.
"""

from __future__ import annotations

import copy
import unicodedata

#: 원문 픽스처. `PolicySource` 에 들어가면 저장소가 NFC 정규화하므로, 여기서도
#: **이미 NFC 인 문자열**이어야 저장 왕복 후 오프셋이 흔들리지 않는다 (아래에서 검증한다).
FIXTURE_POLICY_ID = "fixture_policy"
FIXTURE_SOURCE_ID = "src-fixture_policy"

FIXTURE_TEXT = (
    "제3조(지원대상) 신청일 현재 만 19세 이상 만 34세 이하인 무주택 청년으로서\n"
    "연소득 5,000만원 이하인 자를 대상으로 한다.\n"
    "제4조(지원한도) 대출한도는 최대 2억원으로 하며, 대출금리는 연 1.5%에서 2.9%로 한다.\n"
    "제5조(적용지역) 적용 지역은 전국으로 한다.\n"
    "제6조(유의사항) 예산 소진 시 조기 마감될 수 있다.\n"
    "부칙 이 줄은 만 19세 라는 NBSP 표기를 일부러 담고 있다.\n"
    "별표 ５천만원 이라는 전각 표기도 함께 둔다.\n"
)

assert unicodedata.is_normalized("NFC", FIXTURE_TEXT), "픽스처가 NFC 가 아니다"


def valid_draft() -> dict:
    """계약(`contracts/rule_draft.schema.json`)을 통과하는 초안.

    `assetMaxKRW` · `requireNewlywed` · `requireSME` 는 원문이 말하지 않는다 →
    `null` + `not_found`. **이것은 실패가 아니다** (SPEC 4.2.2).

    `regionPrefixes` 는 `null` 이지만 `not_found` 가 **아니다** — 원문이 「전국」이라고
    말했기 때문이다. 두 종류의 `null` 을 가르는 것이 `not_found` 이며, 후자는 근거
    구간을 가져야 한다.
    """
    return {
        "policy_id": FIXTURE_POLICY_ID,
        "criteria": {
            "ageMin": 19,
            "ageMax": 34,
            "annualIncomeMaxKRW": 50000000,
            "assetMaxKRW": None,
            "requireHomeless": True,
            "requireNewlywed": None,
            "requireSME": None,
            "regionPrefixes": None,
        },
        "maxAmountKRW": 200000000,
        "rateRangePct": [1.5, 2.9],
        "conditionalChecks": ["예산 소진 시 조기 마감될 수 있다"],
        "not_found": [
            "/criteria/assetMaxKRW",
            "/criteria/requireNewlywed",
            "/criteria/requireSME",
        ],
    }


def valid_spans() -> list[dict]:
    """근거 매핑. **인용은 원문에서 글자 그대로 복사한 것**이어야 한다.

    오프셋은 담지 않는다 — 담지 않으면 검증기가 원문에서 직접 찾고, 담으면 검증기가
    그 값을 그대로 검사한다. 두 경로 모두 테스트가 붙든다.
    """
    return [
        {"field_path": "/criteria/ageMin", "quote": "만 19세 이상"},
        {"field_path": "/criteria/ageMax", "quote": "만 34세 이하"},
        {"field_path": "/criteria/annualIncomeMaxKRW", "quote": "연소득 5,000만원 이하"},
        {"field_path": "/criteria/requireHomeless", "quote": "무주택 청년"},
        {"field_path": "/criteria/regionPrefixes", "quote": "적용 지역은 전국으로 한다"},
        {"field_path": "/maxAmountKRW", "quote": "대출한도는 최대 2억원"},
        {"field_path": "/rateRangePct", "quote": "연 1.5%에서 2.9%로 한다"},
        {"field_path": "/conditionalChecks/0", "quote": "예산 소진 시 조기 마감될 수 있다"},
    ]


def valid_envelope() -> dict:
    """LLM 이 내야 하는 응답 봉투. 매번 새 사본을 준다 — 테스트가 서로를 오염시키지 않는다."""
    return {"draft": valid_draft(), "spans": valid_spans()}


def envelope_with(**changes: object) -> dict:
    envelope = valid_envelope()
    envelope.update(copy.deepcopy(changes))
    return envelope


def span_for(envelope: dict, field_path: str) -> dict:
    return next(s for s in envelope["spans"] if s["field_path"] == field_path)


def drop_span(envelope: dict, field_path: str) -> dict:
    envelope["spans"] = [s for s in envelope["spans"] if s["field_path"] != field_path]
    return envelope
