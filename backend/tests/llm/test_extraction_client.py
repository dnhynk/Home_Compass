"""추출용 프로바이더 호출 테스트 — SPEC 4.2 (프롬프트 쪽 강제) · 9.2.1.

**네트워크를 부르지 않는다.** 여기서 붙드는 것은 셋이다.

  1. 키가 없으면 `ExtractionUnavailable` 로 **정상 실패**한다 (SPEC 9.2.1)
  2. 프롬프트가 SPEC 4.2 의 강제를 실제로 담는다 — 추정 금지와 인용 규약은
     「스키마 양쪽에서」 걸어야 하고, 프롬프트가 그 한쪽이다
  3. 응답 해석은 관대하지 않다 — 모델이 낸 것을 주무르지 않는다

`agent.py`(런타임 채팅, A유형)와 **다른 파일**이다. SPEC Part 0-B 가 A 와 B 를 성격이
다른 경로로 갈랐고, 방어 방식도 정반대다. 한 파일에 섞으면 그 구분이 코드에서 사라진다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from home_compass.llm.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionCallFailed,
    ExtractionUnavailable,
    build_user_prompt,
    call_extraction,
    parse_envelope,
)

CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "rule_draft.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1. 키 없이 — 정상 실패 (SPEC 9.2.1)
# --------------------------------------------------------------------------

def test_without_any_key_the_call_raises_unavailable(monkeypatch, schema):
    """스택트레이스도 부분 결과도 아니고, **이름이 있는 실패**로 나온다."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(ExtractionUnavailable):
        call_extraction(policy_id="x", text="원문", schema=schema)


def test_importing_the_module_needs_no_key_and_no_sdk():
    """모듈 최상단에서 SDK 를 끌어오면 키 없는 환경에서 import 부터 깨진다.

    그러면 SPEC 9.2.1 의 「후반부는 전부 동작해야 한다」가 import 한 줄에 걸려 무너진다.
    """
    import ast

    import home_compass.llm.extraction as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names: list[str] = []
    for node in top_level:
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        else:
            names.extend(a.name for a in node.names)
    assert not [n for n in names if n.split(".")[0] in {"openai", "anthropic"}], names


def test_the_client_does_not_import_store_or_ingest():
    """SPEC 1.2 — `llm` 은 `store` · `ingest` 를 import 하지 않는다.

    계약 스키마를 llm 이 직접 읽으면 그 순간 의존이 생긴다. 그래서 스키마는 **인자로 받는다**.
    """
    import ast

    import home_compass.llm.extraction as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            hits.append(node.module or "")
        elif isinstance(node, ast.Import):
            hits.extend(a.name for a in node.names)
    assert not [h for h in hits if "store" in h or "ingest" in h], hits


# --------------------------------------------------------------------------
# 2. 프롬프트가 SPEC 4.2 의 강제를 담는가
# --------------------------------------------------------------------------

def test_the_system_prompt_forbids_guessing():
    """SPEC 4.2 — 「프롬프트와 스키마 **양쪽에서**」 강제한다. 이쪽이 프롬프트 쪽이다."""
    prompt = EXTRACTION_SYSTEM_PROMPT
    assert "추정" in prompt and "not_found" in prompt
    assert "null" in prompt


def test_the_system_prompt_states_the_quote_rule(schema):
    """인용은 원문에서 **글자 그대로** 복사해야 하고 기계가 대조한다는 사실을 알린다.

    모델에게 「검증된다」고 말하는 것 자체가 방어의 일부다. 요약을 인용으로 내는 실패가
    프롬프트 단계에서 크게 줄어든다 — 다만 그것은 완화이고, **판정은 검증기가 한다.**
    """
    prompt = EXTRACTION_SYSTEM_PROMPT
    assert "그대로" in prompt
    assert "요약" in prompt


def test_the_user_prompt_embeds_the_contract_schema_verbatim(schema):
    """스키마를 손으로 옮겨 적으면 계약이 바뀔 때 프롬프트만 옛날 것으로 남는다."""
    prompt = build_user_prompt(policy_id="buttress_youth", text="원문 텍스트", schema=schema)
    assert json.dumps(schema, ensure_ascii=False, indent=2) in prompt
    assert "buttress_youth" in prompt
    assert "원문 텍스트" in prompt


def test_the_user_prompt_explains_the_two_kinds_of_null(schema):
    """`null` 은 두 뜻을 갖는다 — 「원문에 없다」와 「원문이 제한 없음이라고 말했다」.

    이 구분을 프롬프트가 말해 주지 않으면 모델이 둘을 뭉개고, 뭉개진 초안은
    검증기를 통과한다(둘 다 스키마상 유효하므로). 기계가 못 잡는 것은 여기서 막는다.
    """
    prompt = build_user_prompt(policy_id="x", text="원문", schema=schema)
    assert "제한 없음" in prompt or "제한없음" in prompt
    assert "not_found" in prompt


def test_repair_notes_are_carried_into_the_prompt(schema):
    """재시도가 같은 프롬프트를 다시 보내면 같은 답이 온다 (SPEC 4.2.2)."""
    prompt = build_user_prompt(
        policy_id="x", text="원문", schema=schema,
        repair=["span_not_in_text: /criteria/ageMin 의 인용이 원문에 없다"],
    )
    assert "span_not_in_text" in prompt
    assert "/criteria/ageMin" in prompt


# --------------------------------------------------------------------------
# 3. 응답 해석 — 주무르지 않는다
# --------------------------------------------------------------------------

def test_a_plain_json_object_parses():
    assert parse_envelope('{"draft": {}, "spans": []}') == {"draft": {}, "spans": []}


def test_a_fenced_json_block_parses():
    """```json 울타리는 모델이 실제로 자주 붙인다. 봉투를 여는 것은 정규화가 아니다 —
    **원문 인용 문자열은 한 글자도 건드리지 않는다.**"""
    fenced = '```json\n{"draft": {}, "spans": []}\n```'
    assert parse_envelope(fenced) == {"draft": {}, "spans": []}


@pytest.mark.parametrize("text", ["", "   ", "설명만 있고 JSON 이 없다", "{깨진 JSON", "[1, 2]"])
def test_unparseable_responses_fail_loudly(text):
    """고쳐서 통과시키지 않는다. 여기서 관대해지면 검증기가 볼 것이 없어진다."""
    with pytest.raises(ExtractionCallFailed):
        parse_envelope(text)


def test_parsing_preserves_the_quote_bytes_exactly():
    """인용 안의 NBSP·전각 문자가 파싱 과정에서 바뀌면 span 검증이 통째로 거짓이 된다."""
    envelope = parse_envelope(
        json.dumps({"draft": {}, "spans": [{"field_path": "/x", "quote": "만 19세 ５천만원"}]},
                   ensure_ascii=False)
    )
    assert envelope["spans"][0]["quote"] == "만 19세 ５천만원"
