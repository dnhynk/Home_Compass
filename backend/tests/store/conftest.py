"""store 테스트 공통 픽스처.

핵심은 `store` 픽스처가 **두 백엔드로 파라미터화**되어 있다는 것이다.
같은 계약 테스트가 SQLite 와 메모리 백엔드에서 모두 돌아야 통과한다 — 이것이
부록 A 의 "교체 가능" 주장을 코드로 붙들어 두는 장치다.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from home_compass.store import create_store, register_backend  # noqa: E402
from home_compass.store.models import (  # noqa: E402
    AnomalyReport,
    ApprovalRecord,
    AuditEvent,
    ModelConstant,
    PolicySource,
    Provenance,
    Region,
    RuleDraft,
    RuleVersion,
    User,
)
from memory_backend import MemoryStore  # noqa: E402

KST = timezone(timedelta(hours=9))

# 고정 시각. 테스트가 "오늘"에 따라 결과를 바꾸면 그 테스트는 아무것도 고정하지 못한다.
T0 = datetime(2026, 8, 13, 9, 0, 0, tzinfo=KST)

register_backend("memory", MemoryStore.open)


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite://{tmp_path / 'store.db'}"
    else:
        url = f"memory://{request.node.name}"
    with create_store(url) as opened:
        yield opened


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f"sqlite://{tmp_path / 'store.db'}"


# --------------------------------------------------------------------------
# 엔티티 팩토리 — 테스트마다 필드를 다시 적지 않도록.
# --------------------------------------------------------------------------

OUR_CHOICE = Provenance(
    source_kind="normative",
    source_name=None,
    source_ref=None,
    observed_at=None,
    fetched_at=None,
    verification="our_choice",
)

UNVERIFIED_MARKET = Provenance(
    source_kind="market",
    source_name="프로토타입 예시 데이터",
    source_ref=None,
    observed_at=None,
    fetched_at=None,
    verification="unverified",
)


def make_region(code: str = "11440", **over) -> Region:
    fields = dict(
        code=code,
        name="서울 마포구",
        jeonse_median_krw=280_000_000,
        monthly_deposit_krw=20_000_000,
        monthly_rent_krw=850_000,
        maintenance_fee_krw=90_000,
        jeonse_ratio_pct=71.2,
        conversion_rate_pct=5.5,
        market_risk="low",
        guarantee_available=True,
        provenance=UNVERIFIED_MARKET,
    )
    fields.update(over)
    return Region(**fields)


def make_policy_source(source_id: str = "src-1", text: str = "만 19세 이상 34세 이하", **over) -> PolicySource:
    fields = dict(id=source_id, text=text, source_ref="https://example.invalid/notice/1", fetched_at=T0)
    fields.update(over)
    return PolicySource(**fields)


def make_draft(draft_id: str = "draft-1", **over) -> RuleDraft:
    fields = dict(
        id=draft_id,
        policy_source_id="src-1",
        policy_id="buttress_youth",
        status="pending",
        payload={"criteria": {"ageMin": 19, "ageMax": 34}},
        created_at=T0,
        failure_reason=None,
    )
    fields.update(over)
    return RuleDraft(**fields)


def make_rule_version(version_id: str = "rv-1", **over) -> RuleVersion:
    """기본값은 시드 유래 규칙 — origin='seed' 이면 approved_by 는 NULL 이다."""
    fields = dict(
        id=version_id,
        policy_id="buttress_youth",
        payload={"id": "buttress_youth", "maxAmountKRW": 200_000_000},
        status="approved",
        origin="seed",
        effective_from=T0,
        effective_to=None,
        supersedes=None,
        approved_by=None,
        provenance=UNVERIFIED_MARKET,
        created_at=T0,
    )
    fields.update(over)
    return RuleVersion(**fields)


def make_constant(key: str = "affordability.buffer_ratio", **over) -> ModelConstant:
    fields = dict(
        key=key,
        engine="affordability",
        legacy_symbol="BUFFER_RATIO",
        spec_class="d",
        value_type="ratio",
        value=0.10,
        provenance=OUR_CHOICE,
    )
    fields.update(over)
    return ModelConstant(**fields)


def make_user(user_id: str = "u-1", **over) -> User:
    fields = dict(
        id=user_id,
        username="rule_admin_1",
        role="rule_manager",
        password_hash="$argon2id$placeholder",
        created_at=T0,
    )
    fields.update(over)
    return User(**fields)


def make_approval(record_id: str = "ap-1", **over) -> ApprovalRecord:
    fields = dict(
        id=record_id,
        actor_user_id="u-1",
        at=T0,
        target_kind="rule_draft",
        target_id="draft-1",
        decision="approved",
        reason=None,
    )
    fields.update(over)
    return ApprovalRecord(**fields)


def make_report(report_id: str = "rep-1", **over) -> AnomalyReport:
    """SPEC 6.4 이상 신고. 기본값은 상담원이 정책 하나를 겨눈 신고다.

    초안 팩토리와 나란히 두되 **필드를 빌려 오지 않는다** — 원문 id 도 payload 도 없다.
    사람이 낸 것이라 인용할 원문이 없기 때문이며, 그 비대칭이 계약 결정 #38 이다.
    """
    fields = dict(
        id=report_id,
        reporter="counselor",
        at=T0,
        target_kind="policy",
        target_id="buttress_youth",
        target_field="status",
        reason="고객이 이 제도가 지난달에 없어졌다고 한다",
        status="open",
    )
    fields.update(over)
    return AnomalyReport(**fields)


def make_audit_event(event_id: str = "ae-1", **over) -> AuditEvent:
    fields = dict(
        id=event_id,
        actor="u-1",
        at=T0,
        action="rule.approve",
        target="draft-1",
        outcome="success",
        before=None,
        after={"status": "approved"},
    )
    fields.update(over)
    return AuditEvent(**fields)
