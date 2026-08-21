"""추출 검증 테스트 — SPEC 9.2 #10 · 10.2 2단계. **키 없이 전부 돈다.**

이 파일이 붙드는 것은 SPEC 4.2 가 「핵심 방어」라고 부른 것 하나다:

    LLM 이 낸 인용이 원문에 실재하는지 **기계가** 확인한다. 실재하지 않으면 추출 실패다.

그래서 여기 있는 테스트는 대부분 **음성 케이스**다. 검증기가 통과시켜서는 안 되는 것을
통과시키면 4.2 의 방어는 프롬프트 한 줄로만 남는다. 특히 SPEC 4.2.1 이 금지한
**검증 시점 정규화**(공백 접기 · 전각/반각 변환 · 줄바꿈 제거)를 세 개의 테스트가 직접
찔러 본다 — 검증기가 문자열을 주무르기 시작하면 무엇이든 통과시킬 수 있기 때문이다.

`llm` 을 import 하지 않는다. 그것이 Part 0-B 주장(「LLM 호출은 파이프라인의 한 단계일
뿐이다」)의 기계적 증명이며, 마지막 테스트가 그 사실 자체를 검사한다.
"""

from __future__ import annotations

import pytest

from home_compass.ingest.extraction_verify import (
    EVIDENCE_POINTERS,
    count_occurrences,
    ExtractionRejected,
    RejectionCode,
    locate_quote,
    rule_draft_schema,
    verify,
)

from extraction_fixtures import (  # noqa: E402 — pytest 가 이 디렉터리를 sys.path 에 넣는다
    FIXTURE_POLICY_ID,
    FIXTURE_TEXT,
    drop_span,
    envelope_with,
    span_for,
    valid_draft,
    valid_envelope,
    valid_spans,
)


def run(envelope: dict, *, policy_id: str = FIXTURE_POLICY_ID, text: str = FIXTURE_TEXT):
    return verify(envelope, policy_id=policy_id, text=text)


def codes(excinfo) -> set[str]:
    return set(excinfo.value.codes)


def expect_rejected(envelope: dict, code: str, **kwargs):
    with pytest.raises(ExtractionRejected) as caught:
        run(envelope, **kwargs)
    assert code in codes(caught), (
        f"{code} 로 거부되어야 하는데 사유가 {sorted(codes(caught))} 였다")
    return caught.value


# --------------------------------------------------------------------------
# 1. 통과해야 하는 것
# --------------------------------------------------------------------------

def test_a_well_formed_extraction_passes():
    result = run(valid_envelope())
    assert result.draft == valid_draft()
    assert len(result.spans) == len(valid_spans())


def test_every_verified_span_resolves_to_its_own_quote():
    """SPEC 4.2.1 의 검증 규약 그 자체 — `text[start:end] == 인용`.

    산출물이 이 불변식을 만족하지 않으면 저장해도 근거 대조 화면(4.4 #1)이 거짓말을 한다.
    """
    for span in run(valid_envelope()).spans:
        assert FIXTURE_TEXT[span.start : span.end] == span.quote
        assert span.end > span.start  # 반열린 구간이며 빈 구간은 없다


def test_not_found_is_not_a_failure():
    """SPEC 4.2.2 — `null` + `not_found` 는 **정직한 보고**이지 실패가 아니다."""
    envelope = valid_envelope()
    assert envelope["draft"]["not_found"], "픽스처가 not_found 를 담고 있어야 이 테스트가 의미 있다"
    result = run(envelope)
    assert result.draft["criteria"]["assetMaxKRW"] is None
    # not_found 필드에는 span 이 **없어야** 정상이다.
    assert not [s for s in result.spans if s.field_path.startswith("/criteria/assetMaxKRW")]


def test_null_that_the_document_actually_states_is_not_not_found():
    """`null` 은 두 뜻을 갖는다 — 「원문에 없다」와 「원문이 제한 없음이라고 **말했다**」.

    후자는 `not_found` 가 아니며 **근거 구간을 가져야 한다.** 둘을 뭉개면 「전국 대상」과
    「지역 요건을 못 찾았다」가 같은 초안으로 저장된다.
    """
    result = run(valid_envelope())
    assert result.draft["criteria"]["regionPrefixes"] is None
    assert "/criteria/regionPrefixes" not in result.draft["not_found"]
    assert any(s.field_path == "/criteria/regionPrefixes" for s in result.spans)


def test_offsets_supplied_by_the_caller_are_verified_not_trusted():
    """호출자가 오프셋을 실어 보내면 검증기가 **그 값을** 검사한다.

    누가 정수를 계산했는지와 무관하게 4.2.1 의 등식이 성립해야 한다는 뜻이다.
    """
    envelope = valid_envelope()
    quote = span_for(envelope, "/maxAmountKRW")["quote"]
    start = FIXTURE_TEXT.index(quote)
    span_for(envelope, "/maxAmountKRW").update({"start": start, "end": start + len(quote)})
    result = run(envelope)
    hit = next(s for s in result.spans if s.field_path == "/maxAmountKRW")
    assert (hit.start, hit.end) == (start, start + len(quote))


# --------------------------------------------------------------------------
# 2. ★ span 위조 — SPEC 10.2 2단계 완료 기준의 첫 줄
# --------------------------------------------------------------------------

def test_a_quote_that_is_not_in_the_source_is_rejected():
    """원문에 없는 인용을 **일부러 심어** 확인한다 (SPEC 10.2 2단계).

    이것이 통과하면 LLM 은 근거를 지어내고도 규칙을 저장할 수 있다 — 그 순간
    「사람 게이트」는 지어낸 근거를 대조 표시하는 화면이 된다.
    """
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"  # 원문에 없다
    expect_rejected(envelope, RejectionCode.SPAN_NOT_IN_TEXT)


def test_forged_offsets_are_rejected_even_when_the_quote_is_real():
    """인용은 진짜인데 오프셋이 딴 데를 가리키는 경우.

    인용 실재성만 보고 오프셋을 믿으면 검토 화면이 엉뚱한 구간을 하이라이트한다.
    """
    envelope = valid_envelope()
    span = span_for(envelope, "/criteria/ageMax")
    span.update({"start": 0, "end": len(span["quote"])})
    expect_rejected(envelope, RejectionCode.SPAN_OFFSET_MISMATCH)


def test_offsets_outside_the_source_are_rejected():
    envelope = valid_envelope()
    span = span_for(envelope, "/criteria/ageMax")
    span.update({"start": len(FIXTURE_TEXT) - 1, "end": len(FIXTURE_TEXT) + 500})
    expect_rejected(envelope, RejectionCode.SPAN_OFFSET_MISMATCH)


def test_an_empty_quote_is_rejected():
    """빈 인용은 어떤 원문에서도 「찾을 수」 있다. 근거가 아니다."""
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = ""
    expect_rejected(envelope, RejectionCode.SPAN_EMPTY_QUOTE)


# --------------------------------------------------------------------------
# 3. ★★ 검증 시점 정규화 금지 — SPEC 4.2.1
# --------------------------------------------------------------------------
#
# 아래 셋은 「거의 맞는」 인용이다. 사람 눈에는 같아 보이고, 검증기가 조금만 관대해지면
# 전부 통과한다. 통과하면 안 된다 — 원문 쪽 표기 흔들림은 **저장 시 정규화**로만 흡수한다.

def test_whitespace_folding_is_not_performed():
    """원문의 NBSP 를 보통 공백으로 바꾼 인용. NFC 는 U+00A0 을 접지 않는다."""
    assert "만 19세" in FIXTURE_TEXT, "픽스처에 NBSP 가 남아 있어야 한다"
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 19세 라는 NBSP"  # 보통 공백
    expect_rejected(envelope, RejectionCode.SPAN_NOT_IN_TEXT)


def test_fullwidth_to_halfwidth_conversion_is_not_performed():
    """전각 `５천만원` 을 반각으로 적은 인용. NFC 는 전각을 접지 않는다 (NFKC 만 접는다)."""
    assert "５천만원" in FIXTURE_TEXT
    envelope = valid_envelope()
    span_for(envelope, "/criteria/annualIncomeMaxKRW")["quote"] = "5천만원 이라는 전각"
    expect_rejected(envelope, RejectionCode.SPAN_NOT_IN_TEXT)


def test_newline_removal_is_not_performed():
    """줄바꿈을 공백으로 바꿔 두 줄을 이어 붙인 인용."""
    envelope = valid_envelope()
    span_for(envelope, "/criteria/annualIncomeMaxKRW")["quote"] = (
        "무주택 청년으로서 연소득 5,000만원 이하"  # 원문은 사이에 개행이 있다
    )
    expect_rejected(envelope, RejectionCode.SPAN_NOT_IN_TEXT)


def test_trimming_is_not_performed():
    """앞뒤 공백을 붙인 인용. `strip()` 한 줄이면 통과하고, 그 한 줄이 방어를 지운다."""
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "  만 19세 이상  "
    expect_rejected(envelope, RejectionCode.SPAN_NOT_IN_TEXT)


def test_the_live_nbsp_incident_stays_rejected():
    """★ 실제로 일어난 일이다 (2026-08-14 실측, `housing_dream_savings`).

    모델이 낸 인용은 원문과 **한 글자**만 달랐다 — 원문의 NBSP(U+00A0)를 보통
    공백(U+0020)으로 바꿔 적었다. 오타(`여부는` -> `여보는`)는 원문 그대로 옮겼는데
    공백만 조용히 정규화한 것이다. 검증기가 공백을 접었다면 **그대로 통과했을 것이고**,
    아무도 눈치채지 못했을 것이다.

    이 테스트는 그 사건을 픽스처가 아니라 **실제 적재 원문**으로 붙든다. 누가 검증기에
    `.replace(chr(0xa0), ' ')` 한 줄을 넣으면 여기가 빨간불이 된다.
    """
    from home_compass.ingest.sources import SOURCES

    source = next(s for s in SOURCES if s.policy_id == "housing_dream_savings")
    text = source.read_text()

    truth = "주택 소유 여보는"
    assert truth in text, "실측 대상 원문이 바뀌었다 — 이 사건의 근거가 사라졌다"

    folded = truth.replace(" ", " ")  # 모델이 낸 형태
    assert folded not in text
    assert locate_quote(text, folded) is None
    assert locate_quote(text, truth) is not None


def test_locate_quote_does_not_normalise_either():
    """검증기의 하위 함수도 같은 규율을 진다 — 위쪽만 엄격하면 아래로 우회된다."""
    assert locate_quote(FIXTURE_TEXT, "만 19세 이상") is not None
    assert locate_quote(FIXTURE_TEXT, "만  19세 이상") is None
    assert locate_quote(FIXTURE_TEXT, "５천만원") is not None
    assert locate_quote(FIXTURE_TEXT, "5천만원") is None


# --------------------------------------------------------------------------
# 3-b. 인용이 원문에 여러 번 나타나는 경우 (코디네이터 지시 2026-08-14)
# --------------------------------------------------------------------------

def test_a_quote_that_appears_twice_is_accepted_but_counted():
    """★ 실패시키지 않는다. **세어서 낸다.**

    짧은 인용은 어느 문서에서든 반복되므로 여기서 실패시키면 검증이 아니라 **우연**을
    재게 된다. 그러나 조용히 첫 번째를 집는 것도 금지다 — 5단계 검토 화면(SPEC 4.4 #1)이
    이 오프셋으로 원문을 대조 표시하므로, 어느 조항인지가 확정되지 않았다는 사실이
    어딘가에 남아야 한다.
    """
    assert FIXTURE_TEXT.count("만 19세") == 1, "픽스처의 NBSP 판은 다른 문자열이다"
    envelope = valid_envelope()
    span_for(envelope, "/criteria/requireHomeless")["quote"] = "제"  # 조문마다 나온다

    span = next(
        s for s in run(envelope).spans if s.field_path == "/criteria/requireHomeless"
    )
    assert span.occurrences == FIXTURE_TEXT.count("제") > 1
    assert span.ambiguous
    # **첫 등장**을 고른다. 결정적이어야 실행마다 다른 조항이 하이라이트되지 않는다.
    assert span.start == FIXTURE_TEXT.index("제")


def test_a_unique_quote_is_not_flagged_as_ambiguous():
    for span in run(valid_envelope()).spans:
        assert span.occurrences == FIXTURE_TEXT.count(span.quote)
        assert not span.ambiguous, span.field_path


def test_span_offsets_are_deterministic_across_runs():
    """같은 입력이 같은 오프셋을 낸다. 흔들리면 골든 스냅샷도 검토 화면도 못 믿는다."""
    first = [(s.field_path, s.start, s.end) for s in run(valid_envelope()).spans]
    second = [(s.field_path, s.start, s.end) for s in run(valid_envelope()).spans]
    assert first == second


def test_count_occurrences_does_not_normalise():
    assert count_occurrences(FIXTURE_TEXT, "만 19세 이상") == 1
    assert count_occurrences(FIXTURE_TEXT, "５천만원") == 1
    assert count_occurrences(FIXTURE_TEXT, "5천만원") == 0
    assert count_occurrences(FIXTURE_TEXT, "") == 0


# --------------------------------------------------------------------------
# 4. 근거 매핑의 전수성 — 「각 필드마다」 (SPEC 4.1 #3)
# --------------------------------------------------------------------------

def test_a_field_without_evidence_is_rejected():
    """근거 없는 필드가 하나라도 있으면 초안 전체가 실패다 (SPEC 4.2.2 실패 단위)."""
    expect_rejected(drop_span(valid_envelope(), "/maxAmountKRW"), RejectionCode.SPAN_MISSING)


def test_every_extracted_field_needs_evidence():
    """전수로 확인한다 — 하나씩 빼면서 전부 거부되는지 본다."""
    for pointer in [s["field_path"] for s in valid_spans()]:
        expect_rejected(drop_span(valid_envelope(), pointer), RejectionCode.SPAN_MISSING)


def test_each_conditional_check_item_needs_its_own_evidence():
    envelope = valid_envelope()
    envelope["draft"]["conditionalChecks"].append("추가 조건은 근거가 없다")
    expect_rejected(envelope, RejectionCode.SPAN_MISSING)


def test_a_span_on_a_not_found_field_is_rejected():
    """SPEC 4.2.2 — `not_found` 에 적힌 필드는 span 이 **없어야** 정상이다.

    있다는 것은 「못 찾았다」와 「근거가 있다」를 동시에 주장하는 것이다.
    """
    envelope = valid_envelope()
    envelope["spans"].append(
        {"field_path": "/criteria/assetMaxKRW", "quote": "연소득 5,000만원 이하"}
    )
    expect_rejected(envelope, RejectionCode.SPAN_FOR_NOT_FOUND_FIELD)


def test_a_span_on_a_field_that_is_not_extracted_is_rejected():
    """`policy_id` 는 우리가 넣은 식별자이지 원문에서 추출한 값이 아니다."""
    envelope = valid_envelope()
    envelope["spans"].append({"field_path": "/policy_id", "quote": "제3조(지원대상)"})
    expect_rejected(envelope, RejectionCode.SPAN_UNEXPECTED_FIELD)


def test_duplicate_spans_for_one_field_are_rejected():
    """한 필드에 근거가 둘이면 검토 화면이 어느 것을 보여야 하는지 정해지지 않는다."""
    envelope = valid_envelope()
    envelope["spans"].append(
        {"field_path": "/criteria/ageMin", "quote": "신청일 현재 만 19세"}
    )
    expect_rejected(envelope, RejectionCode.SPAN_DUPLICATE)


def test_evidence_pointer_set_matches_the_contract_fields():
    """근거를 요구하는 필드 집합이 계약과 어긋나면 전수성 주장이 조용히 좁아진다."""
    schema = rule_draft_schema()
    contract_leaves = {f"/criteria/{name}" for name in schema["properties"]["criteria"]["properties"]}
    contract_leaves |= {"/maxAmountKRW", "/rateRangePct"}
    assert set(EVIDENCE_POINTERS) == contract_leaves


# --------------------------------------------------------------------------
# 5. 스키마 강제 — 추정 금지가 스키마 쪽에서도 걸린다 (SPEC 4.2)
# --------------------------------------------------------------------------

def test_schema_violation_is_rejected():
    envelope = valid_envelope()
    envelope["draft"]["criteria"]["ageMin"] = "열아홉"
    expect_rejected(envelope, RejectionCode.SCHEMA_VIOLATION)


def test_an_invented_field_is_rejected():
    """`additionalProperties: false` 가 계약 쪽에 걸려 있다. 그것이 실제로 작동하는지 본다."""
    envelope = valid_envelope()
    envelope["draft"]["criteria"]["requireVeteran"] = True
    expect_rejected(envelope, RejectionCode.SCHEMA_VIOLATION)


def test_a_sentinel_value_is_rejected():
    """파수병 금지 (계약 결정 #18). 「상한 없음」은 `null` 이지 200 이 아니다."""
    envelope = valid_envelope()
    envelope["draft"]["criteria"]["ageMax"] = 200
    expect_rejected(envelope, RejectionCode.SCHEMA_VIOLATION)


def test_a_not_found_field_that_still_carries_a_value_is_rejected():
    """★ 추정 금지의 핵심 음성 케이스.

    「못 찾았다」고 적어 놓고 그럴듯한 값을 채워 넣는 것 — 이 단계의 지배적 실패 양상이다.
    스키마는 두 필드의 **관계**를 볼 수 없으므로 여기서 잡는다.
    """
    envelope = valid_envelope()
    envelope["draft"]["criteria"]["assetMaxKRW"] = 300000000  # not_found 에 적혀 있는데 값이 있다
    expect_rejected(envelope, RejectionCode.NOT_FOUND_VALUE_PRESENT)


def test_a_not_found_pointer_that_names_no_real_field_is_rejected():
    """계약의 `pattern` 은 `/criteria/아무거나` 를 통과시킨다. 실재 여부는 여기서 본다."""
    envelope = valid_envelope()
    envelope["draft"]["not_found"].append("/criteria/nonsense")
    expect_rejected(envelope, RejectionCode.NOT_FOUND_UNKNOWN_POINTER)


def test_policy_id_mismatch_is_rejected():
    """다른 정책의 규칙이 이 원문에서 나왔다고 주장하는 초안."""
    envelope = valid_envelope()
    envelope["draft"]["policy_id"] = "some_other_policy"
    expect_rejected(envelope, RejectionCode.POLICY_ID_MISMATCH)


@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"draft": valid_draft()},
        {"spans": valid_spans()},
        {"draft": valid_draft(), "spans": valid_spans(), "extra": 1},
        {"draft": valid_draft(), "spans": "not a list"},
        {"draft": "not an object", "spans": valid_spans()},
    ],
    ids=["empty", "no-spans", "no-draft", "extra-key", "spans-not-list", "draft-not-object"],
)
def test_malformed_envelopes_are_rejected(envelope):
    expect_rejected(envelope, RejectionCode.ENVELOPE_INVALID)


def test_a_span_entry_without_a_quote_is_rejected():
    envelope = valid_envelope()
    envelope["spans"].append({"field_path": "/criteria/ageMin"})
    expect_rejected(envelope, RejectionCode.ENVELOPE_INVALID)


# --------------------------------------------------------------------------
# 6. 실패 단위는 draft 전체다 (SPEC 4.2.2)
# --------------------------------------------------------------------------

def test_one_bad_span_fails_the_whole_draft():
    """span 하나가 틀렸을 뿐인데 나머지 일곱은 멀쩡하다. 그래도 전체가 실패다.

    필드 단위 부분 저장은 「부분 저장 금지」와 직접 충돌한다.
    """
    envelope = valid_envelope()
    span_for(envelope, "/rateRangePct")["quote"] = "연 0.1%에서 0.2%로 한다"
    with pytest.raises(ExtractionRejected):
        run(envelope)


def test_all_reasons_are_reported_not_just_the_first():
    """실패를 숨기지 않는다 — 사유 분포를 세려면 사유가 전부 남아야 한다 (SPEC 7.2)."""
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"
    drop_span(envelope, "/maxAmountKRW")
    with pytest.raises(ExtractionRejected) as caught:
        run(envelope)
    assert {RejectionCode.SPAN_NOT_IN_TEXT, RejectionCode.SPAN_MISSING} <= codes(caught)


# --------------------------------------------------------------------------
# 7. ★ 후반부는 LLM 을 모른다 — Part 0-B 주장의 기계적 증명
# --------------------------------------------------------------------------

def test_the_verifier_module_does_not_import_the_llm_layer():
    """SPEC 9.2.1 마지막 줄: 추출의 **후반부는 키 없이 전부 동작해야 한다.**

    「돌더라」가 아니라 **구조적으로 LLM 을 모른다**는 것을 import 그래프로 고정한다.
    한 줄이라도 llm 을 끌어오면 이 모듈은 키 없는 환경에서 import 조차 못 할 수 있고,
    그러면 9.2.1 의 마지막 줄이 우연에 기대게 된다.
    """
    import ast
    from pathlib import Path

    import home_compass.ingest.extraction_verify as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    assert not [name for name in imported if "llm" in name], imported
