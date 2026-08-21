"""백엔드가 공유하는 불변식.

여기 있는 것들은 **저장 매체와 무관한 보장**이다. SQLite 는 이 위에 트리거·CHECK 로
두 번째 겹을 더 얹지만(SPEC 7.1), 이 층만으로도 다른 백엔드에서 같은 보장이 유지되어야 한다.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

from .errors import ProvenanceError, SpanOutOfRangeError, StoreError
from .models import (
    DECISIONS,
    DRAFT_STATUSES,
    POLICY_REPORT_FIELDS,
    REGION_FACT_FIELDS,
    REPORT_STATUSES,
    REPORT_TARGET_KINDS,
    ROLES,
    RULE_VERSION_ORIGINS,
    AnomalyReport,
    Provenance,
    Region,
    worst_verification,
)
from .provenance import validate_provenance_dict


def require_aware(value: datetime, field: str) -> datetime:
    """오프셋 없는 시각을 거부한다.

    naive datetime 은 조용히 로컬시각으로 해석되어 활성 규칙 창(SPEC 2.3)과 감사기록
    순서를 어긋나게 만든다. 어긋난 뒤에는 어느 쪽이 맞는지 알 방법이 없다.
    """
    if not isinstance(value, datetime):
        raise StoreError(f"{field} 는 datetime 이어야 한다: {value!r}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise StoreError(f"{field} 에 오프셋이 없다 (SPEC 2.1): {value!r}")
    return value


def normalize_text(text: str) -> str:
    """계약 결정 #7 — NFC 정규화는 **저장 시 한 번만** 한다.

    검증 시점에 다시 주무르면 SPEC 4.2.1 의 '핵심 방어' 가 사라진다.
    """
    return unicodedata.normalize("NFC", text)


def validate_provenance(provenance: Provenance) -> None:
    if not isinstance(provenance, Provenance):
        raise ProvenanceError(f"Provenance 가 아니다: {provenance!r}")
    validate_provenance_dict(provenance.to_dict())


def validate_region(region: Region) -> None:
    """`Region` 이 저장되기 전에 지나야 하는 문. 백엔드가 무엇이든 같은 문이다.

    필드별 계보(SPEC 2.1 · 3.1)에 두 가지를 건다.

      1. **이름이 표에 있는가.** 오타 하나로 계보가 조용히 사라지는 경로를 만들지 않는다.
      2. **레코드 요약이 최악값인가** (SPEC 2.4). 이 검사가 없으면 3필드를 `unverified`
         로 적어 두고도 요약만 `verified` 로 올려 등급을 통과시킬 수 있다. 그것이
         SPEC 3.1 이 금지한 "예시값을 실데이터인 척" 두는 경로 그 자체다.
    """
    validate_provenance(region.provenance)
    if not region.field_provenance:
        return

    unknown = sorted(set(region.field_provenance) - set(REGION_FACT_FIELDS))
    if unknown:
        raise StoreError(
            f"Region 의 계보가 알 수 없는 필드를 가리킨다: {unknown} "
            f"(허용: {list(REGION_FACT_FIELDS)})"
        )
    for provenance in region.field_provenance.values():
        validate_provenance(provenance)

    worst = worst_verification(p.verification for p in region.field_provenance.values())
    if worst is not None and region.provenance.verification != worst:
        raise StoreError(
            "Region 의 레코드 계보가 필드별 최악값과 다르다 (SPEC 2.4 — 가장 나쁜 등급이 "
            f"이긴다): 요약={region.provenance.verification!r} / 최악={worst!r}"
        )


def validate_json_pointer(field_path: str) -> None:
    """RFC 6901. 빈 문자열은 루트를 가리키는 유효한 포인터다."""
    if not isinstance(field_path, str):
        raise StoreError(f"field_path 는 문자열이어야 한다: {field_path!r}")
    if field_path == "":
        return
    if not field_path.startswith("/"):
        raise StoreError(f"field_path 가 RFC 6901 JSON Pointer 가 아니다: {field_path!r}")
    for token in field_path.split("/")[1:]:
        index = 0
        while (index := token.find("~", index)) != -1:
            if token[index + 1 : index + 2] not in ("0", "1"):
                raise StoreError(f"RFC 6901 이스케이프가 잘못됐다: {field_path!r}")
            index += 2


def validate_span(text: str, start: int, end: int, field_path: str) -> None:
    """구간은 `[start, end)` 반열린이고 단위는 유니코드 코드포인트다 (계약 결정 #7)."""
    validate_json_pointer(field_path)
    if not isinstance(start, int) or not isinstance(end, int):
        raise SpanOutOfRangeError(f"구간은 정수여야 한다: ({start!r}, {end!r})")
    if start < 0 or end <= start or end > len(text):
        raise SpanOutOfRangeError(
            f"구간이 원문 밖이다: [{start}, {end}) — 원문 길이 {len(text)} 코드포인트"
        )


def validate_draft_status(status: str) -> None:
    if status not in DRAFT_STATUSES:
        raise StoreError(f"알 수 없는 RuleDraft 상태: {status!r} (허용: {DRAFT_STATUSES})")


def validate_role(role: str) -> None:
    if role not in ROLES:
        raise StoreError(f"알 수 없는 역할: {role!r} (허용: {ROLES})")


def validate_approval(decision: str, reason: str | None) -> None:
    """SPEC 10.2 5단계 — 사유 없이 반려할 수 없다."""
    if decision not in DECISIONS:
        raise StoreError(f"알 수 없는 결정: {decision!r} (허용: {DECISIONS})")
    if decision == "rejected" and not (reason or "").strip():
        raise StoreError("반려에는 사유가 있어야 한다 (SPEC 10.2 5단계)")


#: 신고 대상 종류별로 **열 수 있는 항목 목록**. 시세 쪽은 저장소가 이미 아는 사실 필드
#: 8종을 그대로 쓴다 — 목록을 두 벌 만들면 하나가 늘 때 다른 하나가 조용히 낡는다.
_REPORT_FIELDS_BY_KIND = {
    "policy": POLICY_REPORT_FIELDS,
    "region": REGION_FACT_FIELDS,
}


def validate_report(report: AnomalyReport) -> None:
    """SPEC 6.4 이상 신고가 저장되기 전에 지나는 문. 백엔드가 무엇이든 같은 문이다.

    ★ **대상 한정이 이 함수의 핵심이다** (SPEC 7.1 의 표 · 계약 결정 #38). 사유는 자유
      입력이라 고객 상황이 섞일 수 있고, 대상까지 자유 텍스트로 받으면 자유 입력 칸이
      둘이 된다. 그래서 종류와 항목 이름을 **닫힌 목록**에 건다. 화면 문구는 규율이지만
      이 문은 구조이며, 저장소를 바꿔도 남는다.

    대상이 **실재하는지**는 여기서 보지 않는다. 그것은 정책·지역 목록을 아는 API 계층의
    일이고, 저장소가 그것을 전제로 삼으면 대상이 사라진 뒤 신고 기록을 되읽지 못하게 된다.
    """
    if not isinstance(report, AnomalyReport):
        raise StoreError(f"AnomalyReport 가 아니다: {report!r}")

    require_aware(report.at, "at")

    # SPEC 6.4 — 신고자·사유는 신고의 최소 내용이다. 익명 신고는 감사추적을 끊는다.
    if not (report.reporter or "").strip():
        raise StoreError("신고에는 신고자가 있어야 한다 — 익명은 없다 (SPEC 6.4)")
    if not (report.reason or "").strip():
        raise StoreError("신고에는 사유가 있어야 한다 (SPEC 6.4)")

    if report.target_kind not in REPORT_TARGET_KINDS:
        raise StoreError(
            f"알 수 없는 신고 대상 종류: {report.target_kind!r} (허용: {REPORT_TARGET_KINDS})"
        )
    if not (report.target_id or "").strip():
        raise StoreError("신고 대상 식별자가 비어 있다 (SPEC 7.1 — 대상은 항목으로 한정한다)")

    allowed = _REPORT_FIELDS_BY_KIND[report.target_kind]
    if report.target_field not in allowed:
        raise StoreError(
            f"신고 대상 항목이 목록에 없다: {report.target_field!r} "
            f"(허용: {list(allowed)}). 대상은 정책·시세 **항목**으로 한정한다 — "
            "자유 텍스트로 받지 않는다 (SPEC 7.1)"
        )

    if report.status not in REPORT_STATUSES:
        raise StoreError(f"알 수 없는 신고 상태: {report.status!r} (허용: {REPORT_STATUSES})")


def validate_rule_version_origin(
    *, origin: str, approved_by: str | None, has_approval_record: bool
) -> None:
    """계약 결정 #5 의 불변식 표를 그대로 옮긴 것.

    | origin           | approved_by | ApprovalRecord |
    |------------------|-------------|----------------|
    | human_approval   | NOT NULL    | 존재해야 한다   |
    | seed             | NULL        | 없다            |
    """
    if origin not in RULE_VERSION_ORIGINS:
        raise StoreError(f"알 수 없는 origin: {origin!r} (허용: {RULE_VERSION_ORIGINS})")

    if origin == "human_approval":
        if not approved_by:
            raise StoreError("origin='human_approval' 이면 approved_by 가 있어야 한다 (계약 #5)")
        if not has_approval_record:
            raise StoreError(
                "origin='human_approval' 인데 대응하는 ApprovalRecord 가 없다 (계약 #5). "
                "승인자 이름만 적고 승인 기록이 없으면 그것은 승인이 아니다"
            )
    else:
        if approved_by is not None:
            raise StoreError("origin='seed' 는 승인자를 갖지 않는다 — 감사기록 날조다 (계약 #5)")
        if has_approval_record:
            raise StoreError("origin='seed' 에는 ApprovalRecord 가 없어야 한다 (계약 #5)")
