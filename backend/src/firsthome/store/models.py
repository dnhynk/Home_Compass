"""SPEC 2.1 `Provenance` + 2.2 엔티티 9종.

전부 frozen dataclass 다. 저장소가 돌려준 객체를 호출자가 고쳐도 저장소는 그대로여야 한다 —
특히 `AuditEvent` 는 반환값을 통한 수정 경로마저 없어야 append-only 가 성립한다 (SPEC 7.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------
# 허용 값. 계약·SPEC 에 적힌 것만 담는다.
# --------------------------------------------------------------------------

SOURCE_KINDS = ("statute", "statistic", "market", "normative")
VERIFICATIONS = ("verified", "unverified", "stale", "our_choice")

#: SPEC 2.2. `approved` 인 draft 가 존재한다는 것이 2.3 누수 방어의 핵심 이유다.
DRAFT_STATUSES = ("pending", "approved", "rejected", "extraction_failed")

#: 계약 결정 #5. status(판정 참여)와 origin(무엇이 승인했나)은 다른 축이다.
RULE_VERSION_ORIGINS = ("human_approval", "seed")

#: SPEC D-9. 시민은 익명이므로 계정이 없지만, 역할 자체는 3종이다 (6.1 권한 매트릭스).
ROLES = ("citizen", "counselor", "rule_manager")

DECISIONS = ("approved", "rejected")

#: SPEC 3.1 의 표가 다루는 `Region` 의 데이터 필드 8개. 이름은 `to_engine_dict()` 의 키와
#: **같다** — D-13 의 `targets`(JSON Pointer)가 이 이름으로 응답 위치를 가리켜야 하므로
#: 저장소 쪽 이름(snake_case)을 쓰면 계보와 응답이 서로 다른 이름을 갖게 된다.
REGION_FACT_FIELDS = (
    "jeonseMedianKRW",
    "monthlyDepositKRW",
    "monthlyRentKRW",
    "maintenanceFeeKRW",
    "jeonseRatioPct",
    "conversionRatePct",
    "marketRisk",
    "guaranteeAvailable",
)

#: SPEC 6.4 이상 신고의 대상 종류. 계약 결정 #38 — **자유 텍스트로 대상을 받지 않는다.**
REPORT_TARGET_KINDS = ("policy", "region")

#: 정책 쪽에서 신고할 수 있는 항목. **판정 응답의 `Policy` 스키마와 같은 이름**이며,
#: 상담원이 화면에서 보는 항목이 곧 이 목록이다 — 보지 못한 것은 신고할 수 없고,
#: 목록에 없는 이름은 저장소가 거부한다. 둘이 갈리지 않는지는 api 쪽 테스트가 붙든다.
#: 시세 쪽 목록은 `REGION_FACT_FIELDS` 를 그대로 쓴다 (아래) — 두 벌을 만들지 않는다.
POLICY_REPORT_FIELDS = (
    "status",
    "name",
    "category",
    "reasons",
    "maxAmountKRW",
    "rateRangePct",
    "source",
)

#: 신고의 상태. **초안의 상태어를 빌려 오지 않는다** — `approved` 인 신고는 뜻이 없다.
#: 신고는 승인의 대상이 아니라 제안이고, 승인되어도 아무것도 되지 않는다 (계약 결정 #38).
#:
#: ★ 6-A 는 **여는 경로만** 만든다. SPEC 6.4 는 신고를 받은 뒤 규칙관리자가 「수동으로
#:   입력하거나 재추출을 지시한다」고만 적었고, 닫는 동작을 어느 단계에도 배정하지
#:   않았다. `closed` 를 여기 두는 것은 대기 큐가 [쌓이는 곳]이라는 뜻을 담기 위해서이며,
#:   그 전이를 만드는 API 는 이 단계에 없다.
REPORT_STATUSES = ("open", "closed")

#: SPEC 2.4 — 등급은 가장 나쁜 것이 이긴다 (`C` > `B` > `A`).
#: `our_choice` 는 신선도 개념이 없어 **여기 없다.** 등급 산정 대상이 아니다.
_VERIFICATION_SEVERITY = {"verified": 0, "stale": 1, "unverified": 2}


def worst_verification(values: Iterable[str]) -> str | None:
    """여럿 중 가장 나쁜 `verification`. 등급 대상이 하나도 없으면 `None`.

    `Region` 의 레코드 단위 계보는 이 함수의 결과여야 한다 — 요약이 필드보다 좋으면
    그 레코드는 등급을 통과하려고 거짓말을 하는 것이다 (SPEC 2.4 · 3.1).
    """
    gradable = [v for v in values if v in _VERIFICATION_SEVERITY]
    if not gradable:
        return None
    return max(gradable, key=lambda v: _VERIFICATION_SEVERITY[v])


@dataclass(frozen=True)
class Provenance:
    """SPEC 2.1. 정본은 `contracts/provenance.schema.json` 이다.

    필드를 늘리거나 줄이지 않는다. 응답에 실릴 때 붙는 `targets`(D-13)는 응답 조립의
    관심사이지 저장 대상이 아니므로 여기 없다.
    """

    source_kind: str
    source_name: str | None
    source_ref: str | None
    observed_at: str | None
    fetched_at: str | None
    verification: str

    #: 계약 결정 #10. **원문을 확인했으나 그 원문이 기준시점을 밝히지 않은** 경우에만 `True`.
    #: `observed_at` 이 null 인 채로 `verified` 를 허용하는 유일한 통로다.
    #: 값을 못 찾은 경우에 쓰는 필드가 아니다 — 그건 `unverified` 다.
    #: 좁은 제약(분류·verification·필수 동반 필드)은 계약 스키마가 건다. 여기 다시 쓰지 않는다.
    observed_at_unstated: bool | None = None

    #: 계약의 `required` 에 없는 필드. **값이 없으면 키도 없어야 한다** — 기존 시드
    #: 레코드는 6키이며, 무조건 내보내면 계약과 바이트 동일성이 깨진다.
    OMITTED_WHEN_UNSET = ("observed_at_unstated",)

    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if not (f.name in self.OMITTED_WHEN_UNSET and getattr(self, f.name) is None)
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Provenance":
        return cls(**{f.name: data.get(f.name) for f in fields(cls)})


@dataclass(frozen=True)
class Region:
    """지역별 시세 (SPEC 2.2 · 3.1). 판정에 넘기는 필드는 8개 + 식별자 2개다."""

    code: str
    name: str
    jeonse_median_krw: int
    monthly_deposit_krw: int
    monthly_rent_krw: int
    maintenance_fee_krw: int
    jeonse_ratio_pct: float
    conversion_rate_pct: float
    market_risk: str
    guarantee_available: bool

    #: **레코드 단위 요약이다.** 필드별 계보의 최악값이며(SPEC 2.4) 지우지 않는다 —
    #: `to_engine_dict()` 의 `source` 가 이것을 보고, 골든이 그 위에 얹혀 있다.
    provenance: Provenance

    #: SPEC 2.1 · 3.1 — 계보는 **사실 단위**다. 키는 `REGION_FACT_FIELDS` 의 이름이다.
    #:
    #: 지역당 하나이던 시절에는 SPEC 10.2 의 3단계 완료 기준 둘을 **동시에** 만족시킬 수
    #: 없었다. 3필드(`maintenanceFeeKRW`·`marketRisk`·`guaranteeAvailable`)는 실거래가에
    #: 대응물이 없어 항상 `unverified` 이고, 최악값이 이기므로 `stale` 이 한 번도 보이지
    #: 않는다. 비어 있어도 된다 — 그때는 레코드 계보가 곧 필드 계보다.
    #:
    #: `hash=False` 는 `Region` 이 해시 가능한 상태를 유지하기 위한 것이다(매핑은 해시
    #: 불가). 동등성 비교에는 그대로 들어간다.
    field_provenance: Mapping[str, Provenance] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        # 돌려준 객체를 호출자가 고쳐도 저장소는 그대로여야 한다 (이 모듈 최상단).
        # 메모리 백엔드는 객체를 **그대로** 보관하므로 이 방어가 없으면 호출자가
        # 저장소 안의 계보를 직접 고칠 수 있다.
        if not isinstance(self.field_provenance, MappingProxyType):
            object.__setattr__(self, "field_provenance", MappingProxyType(dict(self.field_provenance)))

    def provenance_for(self, field_name: str) -> Provenance:
        """그 필드의 계보. 필드별 항목이 없으면 레코드 요약이 그 필드의 계보다."""
        return self.field_provenance.get(field_name) or self.provenance

    def to_engine_dict(self) -> dict[str, Any]:
        """엔진이 받는 형태. `data/regions.json` 의 한 항목과 같은 모양이다.

        이 함수가 파일과 어긋나면 이관만으로 판정 숫자가 움직인다 (SPEC 10.2 1-①).
        `source` 는 계보의 `source_name` 이 그대로 나온 것이다 — 값을 두 벌 들고 있지 않다.
        """
        return {
            "code": self.code,
            "name": self.name,
            "jeonseMedianKRW": self.jeonse_median_krw,
            "monthlyDepositKRW": self.monthly_deposit_krw,
            "monthlyRentKRW": self.monthly_rent_krw,
            "maintenanceFeeKRW": self.maintenance_fee_krw,
            "jeonseRatioPct": self.jeonse_ratio_pct,
            "conversionRatePct": self.conversion_rate_pct,
            "marketRisk": self.market_risk,
            "guaranteeAvailable": self.guarantee_available,
            "source": self.provenance.source_name,
        }


@dataclass(frozen=True)
class PolicySource:
    """공고문 원문 (SPEC 2.2). 텍스트 + 출처 + 취득시각.

    `text` 는 저장 시점에 NFC 정규화된다 (계약 결정 #7). `RuleSpanMapping` 의 오프셋은
    이 정규화된 문자열을 기준으로 한다.

    ★ **`Provenance` 를 갖지 않는다. 누락이 아니라 설계다** (코디네이터 결정 2026-08-14).
      `Provenance` 는 **판정에 쓰인 사실**을 서술한다 — `source_kind`(법정/통계/시장/규범) ·
      `verification` · `observed_at` 이 전부 「이 숫자가 어디서 왔고 얼마나 믿을 만한가」를
      묻는다. 그런데 `PolicySource` 는 사실이 아니라 **원자료**다. 공고문 자체는 참도 거짓도
      아니고 신선도 등급을 매길 대상도 아니다. 계보는 그 원문에서 **추출된 규칙**
      (`RuleVersion`)이 진다 — 거기서는 `source_kind` 가 `statute` 로 명확하다.
    """

    id: str
    text: str
    source_ref: str | None
    fetched_at: datetime

    #: 출처표시 문구 (계약 결정 #15). 공공누리·저작권법이 요구하는 **그 문장**이며 화면이
    #: 그대로 인용한다. `source_ref` 와 **합치지 않는다** — 참조는 이름 그대로 URL 이어야
    #: 기계가 쓸 수 있고, 거기에 기관·공고번호·이용근거를 말아 넣으면 화면이 URL 만 뽑아내지
    #: 못한다.
    #:
    #: 저장소는 이 값을 **요구하지 않는다.** 출처표시 의무는 원자료의 성질이 아니라 그것을
    #: 무엇으로 적재하는가에서 오므로, 강제는 적재 경로(`ingest`)가 진다. 여기서 강제하면
    #: `PolicySource` 를 쓰는 모든 경로(시드·픽스처)가 이용조건을 아는 척해야 한다.
    attribution: str | None = None


@dataclass(frozen=True)
class RuleDraft:
    """LLM 추출 결과 (SPEC 2.2 · 4.2.3).

    `payload` 는 0단계에서 **불투명 JSON** 이다 (계약 결정 #7). 대상 공고문이 특정되기
    전에 스키마를 만들면 2단계에서 반드시 바뀐다.
    """

    id: str
    policy_source_id: str
    policy_id: str
    status: str
    payload: dict[str, Any]
    created_at: datetime
    failure_reason: str | None = None


@dataclass(frozen=True)
class RuleSpanMapping:
    """규칙 필드 ↔ 원문 구간 (SPEC 2.2 · 4.2.1).

    `start` · `end` 는 **유니코드 코드포인트 인덱스**이고 구간은 `[start, end)` 반열린이다.
    `field_path` 는 `RuleDraft` 루트 기준 RFC 6901 JSON Pointer 다.
    """

    id: str
    draft_id: str
    field_path: str
    start: int
    end: int


@dataclass(frozen=True)
class RuleVersion:
    """승인된 규칙 (SPEC 2.2). 불변이며 `supersedes` 로 이력을 잇는다.

    `effective_from` NULL = 시작일 미상, `effective_to` NULL = 무기한 (계약 결정 #6).
    `origin` 은 무엇이 이 규칙을 승인했는가의 판별자다 (계약 결정 #5).
    """

    id: str
    policy_id: str
    payload: dict[str, Any]
    status: str
    origin: str
    effective_from: datetime | None
    effective_to: datetime | None
    supersedes: str | None
    approved_by: str | None
    provenance: Provenance
    created_at: datetime


@dataclass(frozen=True)
class ModelConstant:
    """모델 상수 + Provenance (SPEC 2.2 · 5.1).

    값의 정본은 여기다. `contracts/model_constants.json` 은 키·단위·분류만 고정한다.
    """

    key: str
    engine: str
    #: 외부화 전의 코드 심볼명. 인라인 리터럴이던 값은 이름이 없었으므로 `None` 이다.
    legacy_symbol: str | None
    spec_class: str
    value_type: str
    value: Any
    provenance: Provenance


@dataclass(frozen=True)
class User:
    """SPEC 2.2 · 6.3. `password_hash` 는 저장소에게 불투명한 문자열이다 —
    해싱 방식(Argon2id)은 인증 계층의 결정이며 4단계에서 붙는다."""

    id: str
    username: str
    role: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class ApprovalRecord:
    """누가·언제·무엇을·왜 (SPEC 2.2). 사유 없이 반려할 수 없다 (SPEC 10.2 5단계)."""

    id: str
    actor_user_id: str
    at: datetime
    target_kind: str
    target_id: str
    decision: str
    reason: str | None = None


@dataclass(frozen=True)
class AnomalyReport:
    """상담원 → 규칙관리자 이상 신고 (SPEC 6.4 · 계약 결정 #38).

    ★ **`RuleDraft` 와 별개 엔티티다.** 둘은 성격이 다르다 — 초안은 기계가 낸 것이라
      스키마 강제·span 실재성·부분 저장 금지(SPEC 4.2)가 걸리고, 신고는 사람이 낸 것이라
      그런 것이 없다. 한 엔티티로 합치면 둘 중 하나의 방어가 반드시 헐거워진다. 그리고
      **큐에서 별도 유형으로 보여야 한다**는 6.4 의 요구가 곧 「둘은 다른 것」이라는 진술이다.

    ★ **`target_field` 가 자유 텍스트가 아니라는 것이 이 엔티티의 유일한 방어다** (SPEC 7.1).
      사유는 자유 입력이라 고객 상황이 섞일 수 있고, 대상까지 자유 텍스트로 받으면 그 칸이
      두 번째 자유 입력이 된다. 대상은 정책·시세 **항목**으로 한정한다.

    `payload` 도 `policy_source_id` 도 없다. 사람이 낸 것이므로 인용할 원문이 없다.
    """

    id: str
    #: 신고자. **익명은 없다** (SPEC 6.4). 세션의 username 이 그대로 들어온다.
    reporter: str
    at: datetime
    #: `policy` | `region` (`REPORT_TARGET_KINDS`).
    target_kind: str
    #: 정책 id 또는 지역 코드. 대상이 **실재하는가**는 API 계층이 본다 — 저장소는 정책
    #: 목록도 지역 목록도 신고의 전제로 삼지 않는다(신고 대상이 사라진 뒤에도 기록은 남는다).
    target_id: str
    #: 어느 항목인가. `POLICY_REPORT_FIELDS` 또는 `REGION_FACT_FIELDS` 안의 이름이다.
    target_field: str
    #: 자유 입력. **파일 로그에 찍지 않는다** (SPEC 7.1 — 요청 본문을 찍지 않는다).
    reason: str
    status: str


@dataclass(frozen=True)
class AuditEvent:
    """append-only (SPEC 7.1). `actor · at · action · target · outcome · before/after`.

    시민의 판정 요청 **프로필은 담지 않는다.** 요청 메타만 남긴다 — 이 규칙은 구조가
    아니라 호출자의 책임이며, 저장소는 그것을 강제하지 못한다.
    """

    id: str
    actor: str
    at: datetime
    action: str
    target: str
    outcome: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
