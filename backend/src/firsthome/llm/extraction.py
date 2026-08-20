"""추출용 프로바이더 호출 — SPEC 4.1 #2 · 4.2. **Part 0-B 의 B유형이다.**

`agent.py`(런타임 채팅)와 **성격이 반대인 경로**이므로 파일을 나눈다.

| | `agent.py` (A) | 이 파일 (B) |
|---|---|---|
| 트리거 | 사용자 입력 | 배치 |
| 출력 | 답변(문장) | **데이터(판정 규칙)** |
| 실패 시 | 오프라인 템플릿으로 **강등** | **정상 실패**. 조용히 대신 답하지 않는다 |
| 방어 | 숫자 생성 권한 박탈 | 스키마 강제 + span 검증 + 사람 게이트 |

**강등이 없다는 것이 가장 큰 차이다.** 채팅은 답을 못 하면 템플릿으로라도 답해야 하지만,
추출은 답을 못 하면 **아무것도 만들지 않아야** 한다 (SPEC 4.2 부분 저장 금지). 그래서
여기서는 예외를 삼키지 않고 이름 있는 실패로 올린다 — 판단은 파이프라인이 한다.

## 이 파일이 하지 않는 것

  - **검증하지 않는다.** 스키마·span 검증은 `ingest.extraction_verify` 가 한다.
    검증을 호출자 쪽에 두는 이유는 SPEC 9.2.1 이다 — 후반부는 키 없이 돌아야 하므로
    LLM 호출과 같은 모듈에 있으면 안 된다.
  - **계약 파일을 읽지 않는다.** 스키마는 **인자로 받는다.** 여기서 읽으면
    `llm -> store` 의존이 생기고 SPEC 1.2 를 위반한다.
  - **재시도하지 않는다.** 횟수는 `ModelConstant` 이고 그 조회는 `ingest` 의 일이다.

## SDK 는 함수 안에서 import 한다

모듈 최상단에서 `openai` 를 끌어오면 SDK 가 없는 환경에서 **import 부터** 깨진다.
그러면 SPEC 9.2.1 의 「후반부는 전부 동작해야 한다」가 import 한 줄에 걸려 무너진다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..config import PROVIDER_OPENAI, openai_model, resolve_provider

#: 응답에서 JSON 만 꺼낼 때 쓰는 울타리. 모델이 ```json 을 붙이는 것은 흔한 일이며,
#: 울타리를 벗기는 것은 **봉투를 여는 것**이지 내용을 주무르는 것이 아니다.
#: ★ 인용 문자열은 이 과정에서 한 글자도 바뀌지 않는다 (SPEC 4.2.1).
_FENCE = re.compile(r"\A\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*\Z", re.DOTALL)


EXTRACTION_SYSTEM_PROMPT = """당신은 한국의 주거 지원 제도 문서에서 **기계 판정 규칙**을 추출한다.

당신이 내는 것은 사람에게 읽히는 답변이 아니라 **데이터**다. 이 데이터는 사람 검토자의
승인을 거쳐 모든 사용자의 자격 판정에 쓰인다. 하나가 틀리면 그 제도를 매칭받는 사용자
전원의 판정이 틀린다.

■ 절대 규칙 1 — 추정 금지

원문에 없는 값을 채우지 마라. 그럴듯한 값을 채워 넣는 것이 이 작업의 가장 흔한 실패다.
원문이 말하지 않는 필드는 값을 null 로 두고 not_found 배열에 그 필드의 JSON Pointer 를
적어라. **모르는 것을 모른다고 적는 것은 감점이 아니다.** 지어낸 값이 감점이다.

■ 절대 규칙 2 — 근거는 원문에서 글자 그대로 복사한다

값을 낸 필드마다 그 근거가 된 원문 구간을 인용으로 함께 내라. 인용은 원문의 **연속된
한 구간을 글자 그대로 복사**한 것이어야 한다.

  금지 — 요약 · 다른 말로 바꾸기 · 여러 곳을 이어 붙이기
  금지 — 공백 개수 바꾸기 · 줄바꿈 지우기 · 전각을 반각으로 바꾸기 · 앞뒤 공백 붙이기

**기계가 원문과 한 글자 단위로 대조한다.** 인용이 원문에 그대로 없으면 그 인용 하나 때문에
추출 결과 **전체가 폐기**된다. 확신이 없으면 인용을 짧게 잡아라 — 짧고 정확한 인용이
길고 어긋난 인용보다 언제나 낫다.

■ 출력

JSON 객체 하나만 출력한다. 설명·머리말·꼬리말을 붙이지 않는다."""


@dataclass(frozen=True)
class ExtractionCall:
    """호출 1회의 결과와 **실측치**.

    지연·토큰을 여기 담는 이유는 SPEC 8.3 이 「추출 1건당 지연/비용」을 2단계에서 실측하라고
    남겼기 때문이다. 호출한 곳에서만 알 수 있는 값이므로 반환값에 실어 보낸다.
    """

    envelope: dict[str, Any]
    model: str
    latency_s: float
    usage: dict[str, int] = field(default_factory=dict)


class ExtractionError(Exception):
    """추출 호출의 실패. 파이프라인이 이것을 `extraction_failed` 로 옮긴다."""


class ExtractionUnavailable(ExtractionError):
    """프로바이더 자체가 없다 — 키 부재 · SDK 부재.

    **재시도 대상이 아니다** (SPEC 9.2.1 「정상 실패」). 키가 없는 것은 일시적 장애가 아니고,
    같은 실패를 N 번 반복하면 로그만 시끄러워진다.
    """


class ExtractionCallFailed(ExtractionError):
    """호출은 했으나 쓸 수 있는 응답을 못 받았다 — 네트워크 · API 오류 · 해석 불가.

    이쪽은 재시도 대상이다 (SPEC 4.2.2).
    """


# --------------------------------------------------------------------------
# 프롬프트
# --------------------------------------------------------------------------

def build_user_prompt(
    *,
    policy_id: str,
    text: str,
    schema: Mapping[str, Any],
    repair: Sequence[str] = (),
) -> str:
    """한 건의 추출 프롬프트.

    ★ 스키마를 **계약 파일 그대로** 싣는다. 손으로 옮겨 적으면 계약이 바뀔 때 프롬프트만
      옛날 것으로 남고, 그때부터 모델은 없는 필드를 채우려 한다.
    """
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    prompt = f"""[대상 정책]
policy_id = {policy_id}
draft 의 policy_id 에는 이 값을 그대로 적어라. 원문에서 찾는 값이 아니다.

[출력 형식]
{{
  "draft": {{ ... 아래 JSON Schema 를 만족하는 객체 ... }},
  "spans": [ {{ "field_path": "<RFC 6901 JSON Pointer>", "quote": "<원문에서 그대로 복사한 인용>" }} ]
}}

- 최상단 키는 draft 와 spans **둘뿐**이다. 다른 키를 넣지 마라.
- span 에 오프셋(start · end)을 **넣지 마라.** 기계가 원문에서 직접 찾는다.
  당신이 글자 수를 세려고 하면 거의 반드시 틀린다.

[draft 의 JSON Schema — 2020-12, additionalProperties: false]
{schema_json}

[null 의 두 가지 뜻 — 이것을 틀리는 것이 가장 흔하다]

null 은 두 경우에 쓰이고, not_found 가 그 둘을 가른다.

  (가) 원문이 그 요건을 **언급하지 않았다**
       -> 값 null + not_found 에 그 필드의 JSON Pointer 를 적는다 + span 을 내지 않는다
  (나) 원문이 「제한 없음」 · 「전국」 · 「상한 없음」이라고 **명시했다**
       -> 값 null + not_found 에 적지 않는다 + **그렇게 적힌 구간의 span 을 낸다**

(가)를 (나)로 적으면 「언급이 없다」가 「제한이 없다」로 바뀌어 자격이 없는 사람이
자격 있다고 판정된다. 반대로 (나)를 (가)로 적으면 원문에 있는 사실을 버리는 것이다.

[span 규칙]
- not_found 에 적지 않은 필드는 **전부** span 이 하나씩 있어야 한다 (값이 null 이어도).
- not_found 에 적은 필드는 span 이 **없어야** 한다.
- conditionalChecks 는 항목마다 span 을 낸다 — field_path 는 /conditionalChecks/0,
  /conditionalChecks/1 … 이다. 항목이 없으면 빈 배열로 두고 span 도 내지 않는다.
- 한 필드에 span 은 하나다.

[값 표기]
- 금액은 **원 단위 정수**다. 「2억원」 -> 200000000, 「5천만원」 -> 50000000.
- rateRangePct 는 퍼센트 포인트 [하한, 상한] 이다. 「연 1.5%~2.9%」 -> [1.5, 2.9].
  단일 금리면 [x, x] 로 적는다.
- 연령은 만 나이 정수다. 「상한 없음」에 200 같은 큰 수를 넣지 마라 — null 이다.
- regionPrefixes 는 **법정동코드 접두사 숫자 문자열**이다. 원문에 그 코드가 숫자로
  적혀 있지 않으면 지역명에서 코드를 유추하지 마라 — not_found 다.
  원문이 「전국」이라고 적었다면 그것은 위 (나) 이므로 null + span 이다.
- requireHomeless · requireNewlywed · requireSME 는 원문이 그 요건을 말할 때만
  true/false 다. 말하지 않으면 false 가 아니라 not_found 다.

[원문 — 이 텍스트가 대조 기준이다. 여기 없는 문자열은 인용이 될 수 없다]
{text}"""

    if repair:
        listed = "\n".join(f"  - {reason}" for reason in repair)
        prompt += f"""

[직전 시도가 거부된 사유 — 같은 실수를 반복하지 마라]
{listed}

거부는 필드 단위가 아니라 **전체**다. 위 사유를 고친 완전한 JSON 을 처음부터 다시 내라.
인용이 원문에 없다고 나온 필드는, 원문에서 그 문자열을 다시 찾아 **그대로** 복사하라.
찾을 수 없으면 그 필드는 not_found 다 — 비슷한 구간을 인용으로 쓰지 마라."""

    return prompt


# --------------------------------------------------------------------------
# 응답 해석
# --------------------------------------------------------------------------

def parse_envelope(raw: str) -> dict[str, Any]:
    """모델 응답에서 봉투 객체를 꺼낸다.

    관대하지 않다. 울타리(```json)만 벗기고, 그 밖의 어떤 보정도 하지 않는다 —
    앞뒤 산문에서 JSON 을 긁어내는 식의 구조는 모델이 형식을 어겨도 통과시키고,
    그러면 「스키마로 강제한다」는 SPEC 4.2 의 절반이 사라진다.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ExtractionCallFailed("응답이 비어 있다")

    body = raw
    fenced = _FENCE.match(raw)
    if fenced is not None:
        body = fenced.group("body")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExtractionCallFailed(f"응답이 JSON 이 아니다: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ExtractionCallFailed(f"응답 최상단이 객체가 아니다: {type(parsed).__name__}")
    return parsed


# --------------------------------------------------------------------------
# 호출
# --------------------------------------------------------------------------

def extraction_provider() -> str:
    """지금 추출에 쓸 수 있는 프로바이더. `offline` 이면 추출은 불가능하다.

    ★ 채팅과 달리 `offline` 은 **폴백이 아니라 부재**다. 결정론적 템플릿으로 규칙을
      만들어 낼 수는 없다 — 만들어 낸다면 그것이 바로 SPEC 이 금지한 값 날조다.
    """
    return resolve_provider()


def call_extraction(
    *,
    policy_id: str,
    text: str,
    schema: Mapping[str, Any],
    repair: Sequence[str] = (),
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> ExtractionCall:
    """제도 문서 원문 하나를 봉투 하나로 바꾼다. **검증은 하지 않는다.**

    `timeout_seconds` 는 기본값이 `None` 이고, 그때는 SDK 기본값을 쓴다.
    ★ 여기에 숫자를 박지 않은 이유가 있다 — SPEC 8.3 #1 은 타임아웃을 **측정에서
      유도**하라고 하고, 8.3.2 는 「추출 1건당 지연 상한」을 **2단계 실측 대상**으로
      남겼다. 즉 이 과업이 그 측정을 만드는 쪽이며, 측정 전에 상한을 정하면
      「감으로 정한 임계가 검증했다는 착각을 만든다」(SPEC 4.2.2)에 그대로 걸린다.
      운영자가 배치를 돌릴 때 넣는 값은 그 실행의 선택이고 제품 상수가 아니다.
    """
    provider = extraction_provider()
    if provider != PROVIDER_OPENAI:
        # Anthropic 경로를 여기서 만들지 않는다. 추출은 프로바이더마다 응답 형식 강제
        # 방법이 다르고, 두 경로를 동시에 열면 어느 쪽으로 나온 결과인지가 초안에 남지
        # 않는 채 실패율이 섞인다. 필요해지면 그때 별도 함수로 추가한다.
        raise ExtractionUnavailable(
            f"추출은 OPENAI_API_KEY 를 요구한다 (현재 프로바이더: {provider})"
        )

    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - SDK 부재 환경
        raise ExtractionUnavailable(f"openai SDK 를 불러올 수 없다: {exc}") from exc

    resolved_model = model or openai_model()
    client = (
        OpenAI(max_retries=0)
        if timeout_seconds is None
        else OpenAI(timeout=timeout_seconds, max_retries=0)
    )
    # 재시도는 파이프라인이 센다 (SPEC 4.2.2 의 「정해진 횟수」). SDK 가 몰래 한 번 더
    # 부르면 그 횟수가 두 곳에서 곱해지고, 실측한 지연·비용이 실제와 어긋난다.

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(
            policy_id=policy_id, text=text, schema=schema, repair=repair)},
    ]

    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 — 프로바이더 예외 종류를 여기서 열거하지 않는다
        raise ExtractionCallFailed(f"{type(exc).__name__}: {exc}") from exc
    latency = time.perf_counter() - started

    content = response.choices[0].message.content if response.choices else None
    envelope = parse_envelope(content or "")

    usage = getattr(response, "usage", None)
    return ExtractionCall(
        envelope=envelope,
        model=getattr(response, "model", resolved_model),
        latency_s=latency,
        usage={
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        },
    )
