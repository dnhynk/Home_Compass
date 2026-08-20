"""A1 — LLM agent layer (자연어 인터페이스).

Design rule for the whole product: **the LLM never computes a number.** It only
decides which deterministic engine to call and turns that engine's output into
Korean prose, quoting the `rationale` strings the engines already produced.
That is the hallucination barrier.

Three providers, resolved in priority order by `engines.config`:

  1. "openai"    — OPENAI_API_KEY present. OpenAI function calling.
  2. "anthropic" — ANTHROPIC_API_KEY present. Claude tool use.
  3. "offline"   — no key at all. Deterministic Korean template over the same
                   engine output. This path must never be removed: a judge has
                   to be able to run the prototype with no credentials.

The four tools are declared **once** in `tool_specs()` and mechanically converted
to each SDK's format, so the two providers can never drift apart.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from ..engines import analyze, find_region
from ..common import DISCLAIMER, money, safe_int
from ..config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OFFLINE,
    PROVIDER_OPENAI,
    anthropic_model,
    openai_model,
    resolve_provider,
)

MAX_TOOL_ITERATIONS = 4
ANTHROPIC_MAX_TOKENS = 8192

# Per-HTTP-request timeout for a live provider, and how many times one whole
# chat turn is retried before degrading. Measured round-trip for a 1-tool turn
# is ~3-4s; a 4-tool turn can reach ~10s, so the timeout is set well above the
# observed tail rather than at the median.
LLM_TIMEOUT_SECONDS = 30.0
LLM_MAX_ATTEMPTS = 2  # 1 initial call + 1 retry

SYSTEM_PROMPT = """당신은 'Home_Compass'의 청년 주거 금융 상담 에이전트입니다.

절대 규칙:
1. 금액, 비율, 점수 등 모든 숫자는 반드시 제공된 도구(tool)를 호출해서 얻으십시오.
   당신이 직접 계산하거나 추정한 숫자를 답변에 쓰면 안 됩니다.
2. 도구가 돌려준 rationale(근거) 문장을 인용해 왜 그런 결론인지 설명하십시오.
3. 실제 금융상품의 금리·한도를 지어내지 마십시오. 도구가 준 값만 사용하고,
   그 값이 프로토타입 예시임을 답변 말미에 한 번 밝히십시오.
4. 모르면 모른다고 답하십시오.

답변은 한국어로, 3~6문장 정도로 간결하게 작성하고 핵심 숫자를 먼저 제시하십시오."""


# --------------------------------------------------------------------------
# Single source of truth for the tool surface.
# --------------------------------------------------------------------------

def tool_specs(regions: Sequence[dict]) -> list:
    """Build the tool surface for one request, against the regions in play.

    **모듈 최상단 상수가 아니다** (SPEC 2.3). 예전에는 `REGION_CODES` ·
    `REGION_CHOICES` 를 import 시점에 한 번 만들었고, 그러면 배치가 지역을 갱신해도
    채팅은 프로세스가 죽을 때까지 낡은 목록으로 말한다 — `load_regions` 의
    `lru_cache` 와 **같은 결함**이며 같이 걷어냈다.

    Constrain regionCode to codes that actually exist. Without this a model will
    happily invent one ("MA" for 마포) and the tool call is wasted — observed in
    live testing against OpenAI.
    """
    region_codes = [region["code"] for region in regions]
    region_choices = ", ".join(f"{r['code']}={r['name']}" for r in regions)
    return [
        {
            "name": "assess_affordability",
            "description": (
                "E1 주거지불능력 엔진. 사용자의 소득·부채·가구원수로 감당 가능한 월 주거비 "
                "상한과 권장액, 안전/주의/위험 밴드를 계산한다. "
                "'얼마짜리 집에 살 수 있나', '월세 얼마까지 괜찮나' 류 질문에 반드시 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "monthlyNetIncomeKRW": {
                        "type": "integer",
                        "description": "월 실수령액을 다른 값으로 가정해 볼 때만 지정(원 단위).",
                    },
                    "householdSize": {
                        "type": "integer",
                        "description": "가구원 수를 다른 값으로 가정해 볼 때만 지정.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "check_eligibility",
            "description": (
                "E2 정책·상품 적격성 룰엔진. 청년 주거 지원 제도별로 "
                "eligible/conditional/ineligible 판정과 판정 사유 배열을 돌려준다. "
                "'무슨 지원을 받을 수 있나', '버팀목 대출 되나' 류 질문에 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "regionCode": {
                        "type": "string",
                        "enum": region_codes,
                        "description": (
                            "다른 지역 기준으로 확인할 때만 지정. 반드시 다음 코드 중 하나여야 "
                            f"하며 임의로 지어내지 말 것: {region_choices}"
                        ),
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "compare_tco",
            "description": (
                "E3 전월세 총비용 비교 엔진. 전세/반전세/월세 시나리오별 5년 총비용(TCO), "
                "현재가치(NPV), 월 환산비용, 적합도 점수를 돌려준다. "
                "'전세가 나은가 월세가 나은가' 류 질문에 반드시 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preferredType": {
                        "type": "string",
                        "enum": ["jeonse", "monthly", "any"],
                        "description": "선호 유형. 지정하지 않으면 사용자 프로필 값을 사용.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "scan_risk",
            "description": (
                "E4 전세보증금 리스크 스캐너. 전세가율·보증보험 가입 가능성·대출 비중 등을 "
                "종합해 0~100 위험 점수와 위험 요인 목록을 돌려준다. "
                "'전세 사기 위험 없나', '보증금 떼일 위험' 류 질문에 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "depositKRW": {
                        "type": "integer",
                        "description": "특정 보증금 금액으로 확인할 때만 지정(원 단위).",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    ]

#: 도구 이름은 지역에 의존하지 않는다 — 그래서 여기만 모듈 상수로 남는다.
#: 빈 지역 목록으로 부르는 것은 이름만 뽑는다는 뜻이며, 지역이 실린 칸은 보지 않는다.
TOOL_NAMES = tuple(spec["name"] for spec in tool_specs(()))


def to_openai_tools(regions: Sequence[dict]) -> list:
    """Render the tool surface in OpenAI chat-completions function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in tool_specs(regions)
    ]


def to_anthropic_tools(regions: Sequence[dict]) -> list:
    """Render the tool surface in Anthropic Messages API tool format."""
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for spec in tool_specs(regions)
    ]


def get_llm_mode() -> str:
    """Return the active provider: 'openai' | 'anthropic' | 'offline'.

    A key that is set but whose SDK is not importable degrades to the next
    provider rather than failing at request time.
    """
    provider = resolve_provider()
    if provider == PROVIDER_OPENAI:
        try:
            import openai  # noqa: F401
        except Exception:
            provider = PROVIDER_ANTHROPIC if _has_anthropic_key() else PROVIDER_OFFLINE
    if provider == PROVIDER_ANTHROPIC:
        try:
            import anthropic  # noqa: F401
        except Exception:
            return PROVIDER_OFFLINE
    return provider


def _has_anthropic_key() -> bool:
    import os

    from ..config import clean_env_value

    return bool(clean_env_value(os.environ.get("ANTHROPIC_API_KEY", "")))


# --------------------------------------------------------------------------
# Tool execution — every tool is backed by a deterministic engine.
# --------------------------------------------------------------------------

def _merge(profile: dict, overrides: dict) -> dict:
    merged = dict(profile or {})
    for key, value in (overrides or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def execute_tool(
    name: str,
    args: dict,
    profile: dict,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> tuple[dict, str]:
    """Run one engine tool. Returns (payload, one-line Korean summary).

    A model can still hand us an override the engines reject (a hallucinated
    region code, for instance). Rather than burning the tool call on an error,
    we drop the bad overrides once and answer from the user's real profile —
    a wasted turn is worse than a slightly narrower answer.
    """
    merged = _merge(profile, args)
    note = ""
    try:
        result = analyze(
            merged, constants=constants, regions=regions, policies=policies, now=now
        )
    except ValueError as exc:
        try:
            result = analyze(
                profile or {},
                constants=constants,
                regions=regions,
                policies=policies,
                now=now,
            )
        except ValueError:
            return {"error": str(exc)}, f"입력 오류: {exc}"
        note = f" (요청한 값이 유효하지 않아 사용자 프로필 기준으로 계산했습니다: {exc})"

    if name == "assess_affordability":
        payload = dict(result["affordability"])
        summary = (
            f"감당 가능 월 주거비 상한 {money(payload['maxMonthlyHousingCostKRW'])}, "
            f"권장 {money(payload['recommendedMonthlyHousingCostKRW'])}, "
            f"밴드 {payload['band']}"
        )
    elif name == "check_eligibility":
        payload = {"policies": result["policies"]}
        counts: dict[str, int] = {}
        for policy in result["policies"]:
            counts[policy["status"]] = counts.get(policy["status"], 0) + 1
        summary = (
            f"적격 {counts.get('eligible', 0)}건 / 조건부 {counts.get('conditional', 0)}건 / "
            f"부적격 {counts.get('ineligible', 0)}건"
        )
    elif name == "compare_tco":
        payload = {"scenarios": result["scenarios"]}
        best = result["scenarios"][0]
        summary = (
            f"적합도 1위 '{best['label']}' (5년 총비용 {money(best['tco5yKRW'])}, "
            f"월 환산 {money(best['monthlyEquivalentCostKRW'])})"
        )
    elif name == "scan_risk":
        payload = dict(result["risk"])
        summary = f"보증금 위험 점수 {payload['score']}점 ({payload['band']})"
    else:
        return {"error": f"알 수 없는 도구입니다: {name}"}, f"알 수 없는 도구: {name}"

    if note:
        payload["_note"] = note.strip()
    return payload, summary + note


# --------------------------------------------------------------------------
# Offline template mode (no API key required)
# --------------------------------------------------------------------------

INTENT_KEYWORDS = {
    "compare_tco": ("전세", "월세", "반전세", "비교", "총비용", "tco", "어느 쪽", "뭐가 나아"),
    "scan_risk": ("위험", "리스크", "사기", "떼", "보증", "안전", "깡통"),
    "check_eligibility": ("지원", "정책", "대출", "제도", "버팀목", "자격", "받을 수", "청약"),
    "assess_affordability": ("얼마", "감당", "여력", "예산", "주거비", "소득", "생활비"),
}


# Tie-break order when two intents match the same number of keywords.
INTENT_PRIORITY = ("compare_tco", "scan_risk", "check_eligibility", "assess_affordability")


def detect_intent(message: str) -> str:
    """Route a question to one engine by keyword overlap.

    Scored rather than first-match: "월세 얼마까지 감당 가능해?" contains the
    word 월세 but is an affordability question, and only counting every hit
    ("얼마", "감당") gets that right.
    """
    text = (message or "").lower()
    scores = {
        name: sum(1 for keyword in keywords if keyword in text)
        for name, keywords in INTENT_KEYWORDS.items()
    }
    best = max(scores.values(), default=0)
    if best == 0:
        return "assess_affordability"
    return next(name for name in INTENT_PRIORITY if scores.get(name, 0) == best)


def _offline_reply(message: str, result: dict, intent: str) -> str:
    affordability = result["affordability"]
    scenarios = result["scenarios"]
    policies = result["policies"]
    risk = result["risk"]
    region = result["meta"]["region"]["name"]

    lines = [f"[오프라인 모드] '{message.strip()[:60]}' 질문에 결정론적 엔진 결과로 답변드립니다.", ""]

    if intent == "compare_tco":
        best = scenarios[0]
        cheapest = min(scenarios, key=lambda s: s["tco5yKRW"])
        lines.append(
            f"{region} 기준 적합도 1위는 '{best['label']}'입니다. "
            f"5년 총비용 {money(best['tco5yKRW'])}, 월 환산 "
            f"{money(best['monthlyEquivalentCostKRW'])}, 판정은 {best['verdict']}입니다."
        )
        # Only worth a sentence when the two actually differ — otherwise it
        # reads as the same scenario repeated twice.
        if cheapest["id"] != best["id"]:
            lines.append(
                f"5년 총비용만 보면 '{cheapest['label']}'이 "
                f"{money(cheapest['tco5yKRW'])}으로 가장 저렴합니다."
            )
        else:
            lines.append("이 대안은 적합도와 5년 총비용 양쪽에서 모두 1위입니다.")
        if best["verdict"] != "affordable":
            lines.append(
                f"다만 권장 주거비 {money(result['affordability']['recommendedMonthlyHousingCostKRW'])}"
                f"를 기준으로 보면 여유 있는 선택은 아닙니다(판정: {best['verdict']})."
            )
        lines.extend(f"· {r}" for r in best["rationale"][:3])
    elif intent == "scan_risk":
        lines.append(
            f"{region} 기준 보증금 위험 점수는 {risk['score']}점({risk['band']})입니다."
        )
        for factor in risk["factors"][:3]:
            lines.append(f"· {factor['name']} {factor['valuePct']}% ({factor['impact']}) — {factor['note']}")
    elif intent == "check_eligibility":
        eligible = [p for p in policies if p["status"] == "eligible"]
        conditional = [p for p in policies if p["status"] == "conditional"]
        lines.append(
            f"검토한 {len(policies)}개 제도 중 적격 {len(eligible)}건, 조건부 {len(conditional)}건입니다."
        )
        for policy in (eligible + conditional)[:3]:
            lines.append(
                f"· [{policy['status']}] {policy['name']} (한도 {money(policy['maxAmountKRW'])}, "
                f"출처 {policy['source']}) — {policy['reasons'][0]}"
            )
    else:
        # 슈바베지수는 더 이상 affordability 에 없다 (F-1, SPEC 5.2.1) — 시나리오별
        # 측정값이므로 최상위 단일값을 인용할 수 없다. 밴드와 금액만 인용한다.
        lines.append(
            f"감당 가능한 월 주거비 상한은 {money(affordability['maxMonthlyHousingCostKRW'])}, "
            f"권장액은 {money(affordability['recommendedMonthlyHousingCostKRW'])}이며 "
            f"밴드는 {affordability['band']}입니다."
        )
        lines.extend(f"· {r}" for r in affordability["rationale"][:3])

    lines.append("")
    lines.append(
        "※ LLM API 키가 설정되지 않아 템플릿 모드로 응답했습니다. "
        "숫자는 모두 실제 엔진이 계산한 값입니다."
    )
    lines.append(f"※ {DISCLAIMER}")
    return "\n".join(lines)


def _offline_chat(
    message: str,
    profile: dict,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> dict:
    intent = detect_intent(message)
    try:
        result = analyze(
            profile or {}, constants=constants, regions=regions, policies=policies, now=now
        )
    except ValueError as exc:
        return {
            "reply": (
                f"입력을 확인해 주세요: {exc}\n"
                "지역을 다시 선택한 뒤 질문해 주시면 바로 계산해 드리겠습니다."
            ),
            "toolCalls": [],
            "mode": "offline",
            "provider": PROVIDER_OFFLINE,
        }

    _, summary = execute_tool(
        intent,
        {},
        profile or {},
        constants=constants,
        regions=regions,
        policies=policies,
        now=now,
    )
    return {
        "reply": _offline_reply(message, result, intent),
        "toolCalls": [{"tool": intent, "args": {}, "resultSummary": summary}],
        "mode": "offline",
        "provider": PROVIDER_OFFLINE,
    }


# --------------------------------------------------------------------------
# Shared prompt scaffolding
# --------------------------------------------------------------------------

def _profile_brief(profile: dict, *, regions: Sequence[dict]) -> str:
    region = find_region(str(profile.get("regionCode") or ""), regions=regions) or {}
    return (
        "[사용자 프로필]\n"
        f"- 나이: {safe_int(profile.get('age'))}세\n"
        f"- 연소득: {money(profile.get('annualIncomeKRW'))}\n"
        f"- 월 실수령액: {money(profile.get('monthlyNetIncomeKRW'))}\n"
        f"- 유동자산: {money(profile.get('liquidAssetsKRW'))}\n"
        f"- 월 부채상환: {money(profile.get('existingDebtMonthlyKRW'))}\n"
        f"- 가구원수: {safe_int(profile.get('householdSize'), 1)}명\n"
        f"- 희망 지역: {region.get('name', profile.get('regionCode', '미지정'))}\n"
        f"- 무주택: {bool(profile.get('isHomeless'))}, 신혼: {bool(profile.get('isNewlywed'))}, "
        f"중소기업 재직: {bool(profile.get('isSMEEmployee'))}\n"
        f"- 선호 유형: {profile.get('preferredType', 'any')}"
    )


def _user_turn(message: str, profile: dict, *, regions: Sequence[dict]) -> str:
    return f"{_profile_brief(profile, regions=regions)}\n\n[질문]\n{message}"


def _prior_turns(history: list) -> list:
    turns = []
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": str(content)})
    return turns


def _iteration_cap_reply(tool_calls: list) -> str:
    return "도구 호출이 너무 많아 요약으로 답변드립니다.\n" + "\n".join(
        f"· {c['tool']}: {c['resultSummary']}" for c in tool_calls
    )


# --------------------------------------------------------------------------
# Provider 1 — OpenAI function calling
# --------------------------------------------------------------------------

def _openai_chat(
    message: str,
    profile: dict,
    history: list,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> dict:
    from openai import OpenAI

    client = OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
    model = openai_model()
    tools = to_openai_tools(regions)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_prior_turns(history))
    messages.append({"role": "user", "content": _user_turn(message, profile, regions=regions)})

    tool_calls: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice="auto"
        )
        choice = response.choices[0].message
        requested = choice.tool_calls or []

        if not requested:
            text = (choice.content or "").strip()
            if not text:
                raise RuntimeError("빈 응답을 받았습니다.")
            return {
                "reply": text,
                "toolCalls": tool_calls,
                "mode": "live",
                "provider": PROVIDER_OPENAI,
                "model": model,
            }

        messages.append(
            {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in requested
                ],
            }
        )

        for call in requested:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            payload, summary = execute_tool(
                call.function.name,
                args,
                profile or {},
                constants=constants,
                regions=regions,
                policies=policies,
                now=now,
            )
            tool_calls.append(
                {"tool": call.function.name, "args": args, "resultSummary": summary}
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )

    return {
        "reply": _iteration_cap_reply(tool_calls),
        "toolCalls": tool_calls,
        "mode": "live",
        "provider": PROVIDER_OPENAI,
        "model": model,
    }


# --------------------------------------------------------------------------
# Provider 2 — Anthropic tool use
# --------------------------------------------------------------------------

def _anthropic_chat(
    message: str,
    profile: dict,
    history: list,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> dict:
    import anthropic

    client = anthropic.Anthropic(timeout=LLM_TIMEOUT_SECONDS, max_retries=0)
    model = anthropic_model()
    tools = to_anthropic_tools(regions)

    messages = _prior_turns(history)
    messages.append({"role": "user", "content": _user_turn(message, profile, regions=regions)})

    tool_calls: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"effort": "medium"},
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "refusal":
            return {
                "reply": "요청을 처리할 수 없습니다. 다른 방식으로 질문해 주세요.",
                "toolCalls": tool_calls,
                "mode": "live",
                "provider": PROVIDER_ANTHROPIC,
                "model": model,
            }

        blocks = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not blocks:
            text = "\n".join(
                b.text for b in response.content if getattr(b, "type", "") == "text"
            ).strip()
            if not text:
                raise RuntimeError("빈 응답을 받았습니다.")
            return {
                "reply": text,
                "toolCalls": tool_calls,
                "mode": "live",
                "provider": PROVIDER_ANTHROPIC,
                "model": model,
            }

        messages.append({"role": "assistant", "content": response.content})

        results = []
        for block in blocks:
            args = dict(block.input or {})
            payload, summary = execute_tool(
                block.name,
                args,
                profile or {},
                constants=constants,
                regions=regions,
                policies=policies,
                now=now,
            )
            tool_calls.append({"tool": block.name, "args": args, "resultSummary": summary})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": results})

    return {
        "reply": _iteration_cap_reply(tool_calls),
        "toolCalls": tool_calls,
        "mode": "live",
        "provider": PROVIDER_ANTHROPIC,
        "model": model,
    }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

_PROVIDER_HANDLERS = {
    PROVIDER_OPENAI: _openai_chat,
    PROVIDER_ANTHROPIC: _anthropic_chat,
}


def chat(
    message: str,
    profile: dict | None = None,
    history: list | None = None,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> dict:
    """Answer one natural-language question. Never raises.

    지역·정책·시각은 `constants` 와 **같은 방식 하나**로 주입받아 그대로 엔진까지
    내려간다 (SPEC 5.1.1). 이 계층은 그 값을 만들지도, 캐시하지도 않는다 — 판정 숫자의
    출처가 호출자 하나로 남아야 채팅과 대시보드가 같은 숫자를 말한다. `now` 도 같은
    이유로 여기서 읽지 않는다: 한 턴이 도구를 여러 번 부르는데 매번 시계를 읽으면 한
    응답 안에서 판정 기준 시각이 갈린다 (SPEC 5.3).

    Returns {"reply", "toolCalls", "mode", "provider", ...}. `mode` stays
    "live"|"offline" for API-contract compatibility; `provider` names which of
    openai/anthropic/offline actually served the request.

    Any failure in a live provider (missing SDK, network, API error, empty
    response) degrades to the offline template instead of surfacing an
    exception — the demo must never show a stack trace.
    """
    profile = profile or {}
    message = (message or "").strip()
    provider = get_llm_mode()

    if not message:
        return {
            "reply": "궁금한 점을 입력해 주세요. 예: '전세랑 월세 중 뭐가 나아?'",
            "toolCalls": [],
            "mode": "offline" if provider == PROVIDER_OFFLINE else "live",
            "provider": provider,
        }

    handler = _PROVIDER_HANDLERS.get(provider)
    if handler is None:
        return _offline_chat(
            message, profile, constants=constants, regions=regions, policies=policies, now=now
        )

    # One retry: the observed failures on a live provider are transient
    # (timeout / 429 / 5xx), and a second attempt costs ~3s against a demo
    # that would otherwise visibly drop to template mode mid-presentation.
    last_exc: Exception | None = None
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            result = handler(
                message,
                profile,
                history or [],
                constants=constants,
                regions=regions,
                policies=policies,
                now=now,
            )
            if attempt:
                result["retried"] = attempt
            return result
        except Exception as exc:  # noqa: BLE001 — graceful degradation is required
            last_exc = exc

    # Still failing after the retry. Degrade — but never silently: the reason
    # is surfaced both in the reply text and as a machine-readable field so the
    # UI can say *why* it is showing template output instead of just flipping
    # a badge the operator has to guess about.
    reason = f"{type(last_exc).__name__}: {last_exc}".strip()[:300]
    fallback = _offline_chat(
        message, profile, constants=constants, regions=regions, policies=policies, now=now
    )
    fallback["reply"] = (
        f"[{provider} 호출이 {LLM_MAX_ATTEMPTS}회 모두 실패해 결정론적 엔진 결과로 답변드립니다. "
        f"사유: {reason}]\n\n" + fallback["reply"]
    )
    fallback["degradedFrom"] = provider
    fallback["degradedReason"] = reason
    fallback["attempts"] = LLM_MAX_ATTEMPTS
    return fallback
