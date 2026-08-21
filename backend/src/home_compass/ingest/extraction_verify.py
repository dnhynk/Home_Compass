"""추출 결과의 기계 검증 — SPEC 4.1 #3·#4 · 4.2 · 4.2.1 · 4.2.2.

**이 모듈은 LLM 을 모른다.** import 그래프에 `llm` 이 한 줄도 없고, 그것을
`backend/tests/ingest/test_extraction_verify.py` 가 검사한다. 그래야 SPEC 9.2.1 의
마지막 줄 — 「정책 추출의 **후반부**는 키 없이 전부 동작해야 한다」 — 이 우연이 아니라
구조가 된다. Part 0-B 가 「LLM 호출은 결정적 파이프라인의 한 단계일 뿐」이라고 주장했고,
그 주장이 코드로 증명되는 자리가 여기다.

## 무엇을 검증하는가

    1. 스키마      `contracts/rule_draft.schema.json` (JSON Schema 2020-12)
    2. 정체성      draft 의 `policy_id` 가 우리가 요청한 정책과 같은가
    3. 추정 금지    `not_found` 에 적힌 필드가 실제로 비어 있는가 (SPEC 4.2)
    4. 근거 전수    `not_found` 가 아닌 모든 필드에 근거 구간이 하나씩 있는가
    5. 인용 실재    인용 문자열이 저장된 원문에 **글자 그대로** 있는가 (SPEC 4.2.1)

## ★ 검증 시점에 정규화하지 않는다 (SPEC 4.2.1)

공백 접기 · 전각/반각 변환 · 줄바꿈 제거 · `strip()` — 전부 하지 않는다. 정규화는
`PolicySource` 저장 시 NFC 로 **한 번만** 한다 (계약 결정 #7). 검증기가 문자열을 주무르기
시작하면 무엇이든 통과시킬 수 있고, 그 순간 4.2 의 「핵심 방어」가 사라진다. 원문 쪽 표기
흔들림은 저장 시 정규화로만 흡수한다.

## 오프셋은 누가 계산하는가

SPEC 4.2.1 은 span 이 **무엇인지**(코드포인트 · 반열린 · JSON Pointer)와 **어떻게
검증되는지**(`text[start:end] == 인용`)를 고정했다. 정수를 누가 계산하는지는 고정하지
않았고, 4.2 가 요구한 방어는 「그 구간이 원문에 **문자열로 실재**하는지」다.

그래서 이 모듈은 둘 다 받는다.

    오프셋이 없으면  원문에서 그 인용을 **정확히** 찾아 오프셋을 만든다.
                    못 찾으면 `span_not_in_text` — 지어낸 근거가 여기서 죽는다.
    오프셋이 있으면  **그 값을 그대로 검사한다.** `text[start:end] != 인용` 이면
                    `span_offset_mismatch`. 호출자가 준 정수를 믿지 않는다.

전자를 택한 이유는 언어모델이 글자를 세지 못한다는 것이고, 후자를 남긴 이유는 검증이
오프셋 출처와 무관하게 성립해야 한다는 것이다. 두 경로 모두 테스트가 붙든다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

# 계약 디렉터리의 위치는 `store` 가 이미 정했다 (환경변수 `HOME_COMPASS_CONTRACTS_DIR`).
# 두 번 정의하면 한쪽만 갈아끼울 때 조용히 갈라진다. `ingest -> store` 는 허용된 방향이다.
from ..store.provenance import contracts_dir

RULE_DRAFT_SCHEMA_FILE = "rule_draft.schema.json"

#: 근거 구간을 **요구하는** 필드. `not_found` 에 적힌 것은 여기서 빠진다.
#:
#: ★ 계약에서 자동 생성하지 않고 손으로 적는다. 자동 생성하면 계약에 필드가 늘 때
#:   근거 요구가 조용히 따라 늘거나 줄고, 그 변화를 아무도 검토하지 않는다.
#:   어긋남은 `test_evidence_pointer_set_matches_the_contract_fields` 가 빨간불로 알린다.
#:
#: `policy_id` 는 **없다.** 우리가 넣은 식별자이지 원문에서 추출한 값이 아니다 —
#: 원문에 없는 것이 정상이므로 근거를 요구하면 전 건이 실패한다.
EVIDENCE_POINTERS: tuple[str, ...] = (
    "/criteria/ageMin",
    "/criteria/ageMax",
    "/criteria/annualIncomeMaxKRW",
    "/criteria/assetMaxKRW",
    "/criteria/requireHomeless",
    "/criteria/requireNewlywed",
    "/criteria/requireSME",
    "/criteria/regionPrefixes",
    "/maxAmountKRW",
    "/rateRangePct",
)

#: 봉투에서 허용하는 키. 그 밖의 키는 `envelope_invalid` 다 — 모델이 발명한 필드를
#: 조용히 무시하면 무엇을 근거로 통과시켰는지가 흐려진다.
_ENVELOPE_KEYS = frozenset({"draft", "spans"})
_SPAN_KEYS = frozenset({"field_path", "quote", "start", "end"})
_SPAN_REQUIRED_KEYS = frozenset({"field_path", "quote"})


class RejectionCode:
    """거부 사유의 어휘. **문자열이 곧 지표 이름이다** (SPEC 7.2 추출 스키마 실패율).

    사유를 뭉개면 「무엇이 어떻게 틀렸는가」를 셀 수 없고, 셀 수 없으면 8.3 의 실측이
    「몇 건 실패」에서 멈춘다.
    """

    ENVELOPE_INVALID = "envelope_invalid"
    SCHEMA_VIOLATION = "schema_violation"
    POLICY_ID_MISMATCH = "policy_id_mismatch"
    NOT_FOUND_UNKNOWN_POINTER = "not_found_unknown_pointer"
    NOT_FOUND_VALUE_PRESENT = "not_found_value_present"
    SPAN_MISSING = "span_missing"
    SPAN_DUPLICATE = "span_duplicate"
    SPAN_UNEXPECTED_FIELD = "span_unexpected_field"
    SPAN_FOR_NOT_FOUND_FIELD = "span_for_not_found_field"
    SPAN_EMPTY_QUOTE = "span_empty_quote"
    SPAN_NOT_IN_TEXT = "span_not_in_text"
    SPAN_OFFSET_MISMATCH = "span_offset_mismatch"

    #: 검증 이전 단계의 실패. 사유 분포를 한 목록에서 읽으려면 어휘가 하나여야 한다.
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_CALL_FAILED = "llm_call_failed"
    #: 검증은 통과했는데 저장소가 거부한 경우. 일어나면 안 되지만, 일어났을 때
    #: `pending` 으로 남는 것보다 실패로 남는 것이 옳다.
    SPAN_STORE_REJECTED = "span_store_rejected"


ALL_CODES: tuple[str, ...] = tuple(
    value
    for name, value in vars(RejectionCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


@dataclass(frozen=True)
class Rejection:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class ExtractionRejected(Exception):
    """검증 실패. **사유를 전부 들고 있다** — 첫 번째만 알리면 분포를 셀 수 없다."""

    def __init__(self, rejections: Iterable[Rejection]) -> None:
        self.rejections: tuple[Rejection, ...] = tuple(rejections)
        super().__init__(" / ".join(str(r) for r in self.rejections))

    @property
    def codes(self) -> tuple[str, ...]:
        """중복을 접은 사유 코드. 등장 순서를 유지한다."""
        return tuple(dict.fromkeys(r.code for r in self.rejections))


@dataclass(frozen=True)
class VerifiedSpan:
    """검증을 통과한 근거 구간. `quote` 는 저장되지 않는다 — `RuleSpanMapping` 은
    오프셋만 담고, 인용은 `text[start:end]` 로 언제든 되살아난다 (SPEC 4.2.1)."""

    field_path: str
    start: int
    end: int
    quote: str

    #: ★ 이 인용이 원문에 **몇 번** 나타나는가 (코디네이터 지시 2026-08-14).
    #:
    #: 2 이상이면 「이 문자열이 원문에 있다」는 것만 확인된 것이고 **어느 조항에서 나온
    #: 근거인지는 확정되지 않았다.** 5단계 검토 화면(SPEC 4.4 #1)이 이 오프셋으로 원문을
    #: 대조 표시하므로, 엉뚱한 조항이 하이라이트되면 검토자는 그것을 보고 승인한다 —
    #: 원칙 3(사람 게이트는 실질이어야 한다)이 거기서 무너진다.
    #:
    #: **그렇다고 실패시키지 않는다.** 짧은 인용은 어느 문서에서든 반복되므로, 실패시키면
    #: 검증이 아니라 우연을 재게 된다. 대신 (a) 결정적으로 첫 등장을 고르고
    #: (b) **이 수를 보고에 남긴다.** 금지된 것은 조용히 첫 번째를 집는 것이다.
    #:
    #: `RuleSpanMapping` 에는 넣지 않는다 — 그것은 계약·`store` 변경이고, 대조 표시가
    #: 실제로 지어지는 5단계에 정할 문제다.
    occurrences: int = 1

    @property
    def ambiguous(self) -> bool:
        return self.occurrences > 1


@dataclass(frozen=True)
class VerifiedExtraction:
    draft: dict[str, Any]
    spans: tuple[VerifiedSpan, ...]


# --------------------------------------------------------------------------
# 계약
# --------------------------------------------------------------------------

def rule_draft_schema() -> dict[str, Any]:
    """계약 원본을 그대로 읽는다. **캐시하지 않는다** — `store/provenance.py` 와 같은 이유로,
    계약을 고치고 재기동해야 반영되는 구조를 만들지 않는다. 추출은 배치이고 스키마는 작다.
    """
    path = contracts_dir() / RULE_DRAFT_SCHEMA_FILE
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 인용 찾기 — ★ 주무르지 않는다
# --------------------------------------------------------------------------

def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """`quote` 가 `text` 에 **정확히** 있으면 `[start, end)` 를, 없으면 `None`.

    파이썬 `str` 의 인덱스는 유니코드 코드포인트이므로 SPEC 4.2.1 의 단위와 같다
    (바이트도 UTF-16 코드유닛도 아니다).

    ★ 여기에 `strip()` · `replace(' ', '')` · `unicodedata.normalize(...)` 를 넣지 마라.
      한 줄이면 성공률이 오르고 방어가 사라진다. 여러 번 등장하면 **첫 번째**를 쓴다 —
      어느 것이든 실재하는 근거이고, 첫 번째를 고르는 것이 결정적이다.
    """
    if not quote:
        return None
    index = text.find(quote)
    if index < 0:
        return None
    return index, index + len(quote)


def count_occurrences(text: str, quote: str) -> int:
    """인용이 원문에 몇 번 나타나는가. **겹치지 않는** 등장을 센다 (`str.count` 규약).

    「어느 조항에서 나온 근거인가」가 확정되었는지를 재는 값이다. 겹치는 등장까지 세면
    `가가가` 안의 `가가` 같은 경우가 2 로 세어지는데, 조항을 가리키는 관점에서 그것은
    한 자리다. 세는 방식을 바꾸면 보고 숫자의 뜻이 바뀌므로 여기 적어 둔다.
    """
    return text.count(quote) if quote else 0


# --------------------------------------------------------------------------
# RFC 6901
# --------------------------------------------------------------------------

_MISSING = object()


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON Pointer 를 푼다. 없으면 `_MISSING` 을 돌려준다 (`None` 과 구분).

    `None` 을 부재로 쓰면 「필드가 없다」와 「필드가 null 이다」가 같아지는데,
    이 모듈에서 그 둘은 정반대의 의미다.
    """
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return _MISSING
    current = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                return _MISSING
            current = current[int(token)]
        else:
            return _MISSING
    return current


def _is_empty(value: Any) -> bool:
    """`not_found` 에 적힌 필드가 가질 수 있는 값.

    `None` 이 정상형이지만 `conditionalChecks` 는 계약이 nullable 로 두지 않았으므로
    (`type: array`) 빈 배열이 그 자리의 「비어 있음」이다. 계약을 고치지 않고 둘을 모두
    받는다 — 계약은 코디네이터 소유다.
    """
    return value is None or value == []


# --------------------------------------------------------------------------
# 검증
# --------------------------------------------------------------------------

def _envelope_rejections(envelope: Any) -> list[Rejection]:
    if not isinstance(envelope, Mapping):
        return [Rejection(RejectionCode.ENVELOPE_INVALID, f"봉투가 객체가 아니다: {type(envelope).__name__}")]

    found = set(envelope)
    if found != _ENVELOPE_KEYS:
        return [Rejection(
            RejectionCode.ENVELOPE_INVALID,
            f"봉투 키가 {sorted(_ENVELOPE_KEYS)} 여야 한다 (받은 것: {sorted(found)})",
        )]
    if not isinstance(envelope["draft"], Mapping):
        return [Rejection(RejectionCode.ENVELOPE_INVALID, "draft 가 객체가 아니다")]
    if not isinstance(envelope["spans"], list):
        return [Rejection(RejectionCode.ENVELOPE_INVALID, "spans 가 배열이 아니다")]

    rejections: list[Rejection] = []
    for index, entry in enumerate(envelope["spans"]):
        where = f"spans[{index}]"
        if not isinstance(entry, Mapping):
            rejections.append(Rejection(RejectionCode.ENVELOPE_INVALID, f"{where} 가 객체가 아니다"))
            continue
        keys = set(entry)
        if not _SPAN_REQUIRED_KEYS <= keys:
            rejections.append(Rejection(
                RejectionCode.ENVELOPE_INVALID,
                f"{where} 에 {sorted(_SPAN_REQUIRED_KEYS - keys)} 가 없다",
            ))
            continue
        if keys - _SPAN_KEYS:
            rejections.append(Rejection(
                RejectionCode.ENVELOPE_INVALID, f"{where} 에 모르는 키가 있다: {sorted(keys - _SPAN_KEYS)}"))
            continue
        if not isinstance(entry["field_path"], str) or not isinstance(entry["quote"], str):
            rejections.append(Rejection(
                RejectionCode.ENVELOPE_INVALID, f"{where} 의 field_path·quote 는 문자열이어야 한다"))
            continue
        for key in ("start", "end"):
            value = entry.get(key)
            if key in entry and (isinstance(value, bool) or not isinstance(value, int)):
                rejections.append(Rejection(
                    RejectionCode.ENVELOPE_INVALID, f"{where} 의 {key} 는 정수여야 한다: {value!r}"))
    return rejections


def _where(error: Any) -> str:
    """스키마 오류가 난 **위치**를 JSON Pointer 로 적는다.

    메시지만 남기면 `None is not of type 'integer'` 가 어느 필드인지 알 수 없고,
    사유 분포를 봐도 무엇을 고쳐야 하는지가 나오지 않는다.
    """
    path = list(error.absolute_path)
    return "/" + "/".join(str(part) for part in path) if path else "(루트)"


def _canonical_order(required: set[str], item_count: int) -> list[str]:
    """span 을 항상 같은 순서로 낸다 — 저장되는 span id 가 실행마다 흔들리지 않게 한다."""
    ordered = [p for p in EVIDENCE_POINTERS if p in required]
    ordered += [
        f"/conditionalChecks/{i}"
        for i in range(item_count)
        if f"/conditionalChecks/{i}" in required
    ]
    return ordered


def verify(envelope: Any, *, policy_id: str, text: str) -> VerifiedExtraction:
    """봉투 하나를 검증한다. 통과하면 `VerifiedExtraction`, 아니면 `ExtractionRejected`.

    `text` 는 **`PolicySource` 에 저장된 NFC 정규화 텍스트**여야 한다 (SPEC 4.2.1).
    원본 파일을 다시 파싱한 문자열을 넣으면 오프셋 기준이 달라진다.

    실패 사유는 **모아서** 낸다. 첫 번째에서 멈추면 재시도 프롬프트가 한 번에 하나씩만
    고치고, 실패 분포도 첫 사유로만 집계된다.
    """
    fatal = _envelope_rejections(envelope)
    if fatal:
        raise ExtractionRejected(fatal)

    draft = dict(envelope["draft"])
    spans: Sequence[Mapping[str, Any]] = envelope["spans"]

    # --- 1. 스키마. 여기서 실패하면 아래 검사는 의미가 없다 (필드가 있다고 가정할 수 없다).
    errors = sorted(Draft202012Validator(rule_draft_schema()).iter_errors(draft), key=str)
    if errors:
        raise ExtractionRejected([
            Rejection(RejectionCode.SCHEMA_VIOLATION, f"{_where(e)}: {e.message}")
            for e in errors
        ])

    rejections: list[Rejection] = []

    # --- 2. 정체성
    if draft["policy_id"] != policy_id:
        rejections.append(Rejection(
            RejectionCode.POLICY_ID_MISMATCH,
            f"요청한 정책은 {policy_id!r} 인데 초안은 {draft['policy_id']!r} 를 주장한다",
        ))

    # --- 3. 추정 금지 — not_found 에 적힌 필드는 비어 있어야 한다 (SPEC 4.2)
    not_found = list(draft["not_found"])
    for pointer in not_found:
        value = resolve_pointer(draft, pointer)
        if value is _MISSING:
            rejections.append(Rejection(
                RejectionCode.NOT_FOUND_UNKNOWN_POINTER,
                f"{pointer} 는 이 초안에 없는 위치다",
            ))
        elif not _is_empty(value):
            rejections.append(Rejection(
                RejectionCode.NOT_FOUND_VALUE_PRESENT,
                f"{pointer} 를 못 찾았다고 적어 놓고 값이 있다: {value!r}",
            ))

    # --- 4. 근거를 요구하는 집합
    not_found_set = set(not_found)
    required = {p for p in EVIDENCE_POINTERS if p not in not_found_set}
    items = draft["conditionalChecks"]
    required |= {f"/conditionalChecks/{i}" for i in range(len(items))}

    # --- 5. 인용 실재성 + 오프셋
    verified: dict[str, VerifiedSpan] = {}
    for entry in spans:
        field_path = entry["field_path"]
        if field_path in verified:
            rejections.append(Rejection(
                RejectionCode.SPAN_DUPLICATE, f"{field_path} 에 근거가 둘 이상 붙었다"))
            continue

        # not_found 검사가 먼저다 — not_found 필드는 required 에도 없으므로 순서를 바꾸면
        # 「못 찾았다면서 근거를 냈다」가 「모르는 필드」로 잘못 보고된다.
        if _covered_by(field_path, not_found_set):
            rejections.append(Rejection(
                RejectionCode.SPAN_FOR_NOT_FOUND_FIELD,
                f"{field_path} 는 not_found 인데 근거 구간이 붙었다 (SPEC 4.2.2)",
            ))
            verified[field_path] = _PLACEHOLDER
            continue
        if field_path not in required:
            rejections.append(Rejection(
                RejectionCode.SPAN_UNEXPECTED_FIELD,
                f"{field_path} 는 근거를 요구하는 필드가 아니다",
            ))
            verified[field_path] = _PLACEHOLDER
            continue

        quote = entry["quote"]
        if not quote:
            rejections.append(Rejection(
                RejectionCode.SPAN_EMPTY_QUOTE, f"{field_path} 의 인용이 비어 있다"))
            verified[field_path] = _PLACEHOLDER
            continue

        if "start" in entry or "end" in entry:
            span = _verified_from_offsets(entry, field_path, quote, text, rejections)
        else:
            span = _verified_from_search(field_path, quote, text, rejections)
        verified[field_path] = span if span is not None else _PLACEHOLDER

    # --- 6. 근거 전수 — 「각 필드마다」 (SPEC 4.1 #3)
    for pointer in _canonical_order(required, len(items)):
        if pointer not in verified:
            rejections.append(Rejection(
                RejectionCode.SPAN_MISSING, f"{pointer} 에 근거 구간이 없다"))

    if rejections:
        raise ExtractionRejected(rejections)

    ordered = _canonical_order(required, len(items))
    return VerifiedExtraction(
        draft=draft,
        spans=tuple(verified[pointer] for pointer in ordered),
    )


#: 사유를 이미 기록한 자리를 채우는 표식. 실패 경로에서만 쓰이고 밖으로 나가지 않는다 —
#: `rejections` 가 비어 있지 않으면 `verify` 는 반드시 예외를 던지기 때문이다.
_PLACEHOLDER = VerifiedSpan(field_path="", start=0, end=0, quote="")


def _covered_by(field_path: str, pointers: set[str]) -> bool:
    """`field_path` 가 `pointers` 중 하나이거나 그 하위인가.

    `/conditionalChecks` 가 not_found 인데 `/conditionalChecks/0` 에 근거를 붙이는 것도
    같은 모순이므로 하위까지 본다.
    """
    return any(field_path == p or field_path.startswith(p + "/") for p in pointers)


def _verified_from_offsets(
    entry: Mapping[str, Any],
    field_path: str,
    quote: str,
    text: str,
    rejections: list[Rejection],
) -> VerifiedSpan | None:
    """호출자가 준 오프셋을 **검사한다.** 믿지 않는다 (SPEC 4.2.1 의 검증 규약)."""
    if "start" not in entry or "end" not in entry:
        rejections.append(Rejection(
            RejectionCode.SPAN_OFFSET_MISMATCH,
            f"{field_path}: start 와 end 는 함께 와야 한다",
        ))
        return None

    start, end = entry["start"], entry["end"]
    if start < 0 or end <= start or end > len(text):
        rejections.append(Rejection(
            RejectionCode.SPAN_OFFSET_MISMATCH,
            f"{field_path}: 구간 [{start}, {end}) 가 원문 밖이다 (원문 {len(text)} 코드포인트)",
        ))
        return None
    # ★ SPEC 4.2.1 의 등식. 양쪽 어디에도 정규화를 끼우지 않는다.
    if text[start:end] != quote:
        rejections.append(Rejection(
            RejectionCode.SPAN_OFFSET_MISMATCH,
            f"{field_path}: text[{start}:{end}] 가 인용과 다르다 "
            f"(원문 {text[start:end]!r} / 인용 {quote!r})",
        ))
        return None
    return VerifiedSpan(
        field_path=field_path, start=start, end=end, quote=quote,
        occurrences=count_occurrences(text, quote),
    )


def _verified_from_search(
    field_path: str, quote: str, text: str, rejections: list[Rejection]
) -> VerifiedSpan | None:
    """오프셋 없이 온 인용 — 원문에서 정확히 찾는다. 못 찾으면 그것이 위조의 증거다."""
    located = locate_quote(text, quote)
    if located is None:
        rejections.append(Rejection(
            RejectionCode.SPAN_NOT_IN_TEXT,
            f"{field_path}: 인용이 원문에 없다 {quote!r}",
        ))
        return None
    start, end = located
    # 스스로를 한 번 더 본다. `find` 의 결과라 항상 참이지만, 이 등식이 SPEC 4.2.1 의
    # 검증 규약 자체이므로 코드에 남겨 둔다 — 아래 저장 경로가 이 값을 그대로 쓴다.
    assert text[start:end] == quote
    return VerifiedSpan(
        field_path=field_path, start=start, end=end, quote=quote,
        occurrences=count_occurrences(text, quote),
    )
