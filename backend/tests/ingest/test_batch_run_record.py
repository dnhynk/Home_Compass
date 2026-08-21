"""SPEC 7.1 「배치 실행 결과」 · 7.2 배치 성공률 — **실행 단위 기록**.

7단계 착수 시점의 관측이 이 파일의 이유다. 실기동(`python -m home_compass.ingest.market
--demo`)이 배치를 3회 돌리는데(최초 · 멱등 재실행 · 일부러 실패) 감사기록을
`(action, at)` 으로 묶으면 이렇게 나왔다 —

    market.ingest      2026-08-14T18:30:59.488178+00:00   20건
    market.outlier     2026-08-14T18:30:59.488178+00:00    4건
    market.run_failed  2026-08-15T18:30:59.488178+00:00    1건

성공한 **2회가 한 그룹**이다. 멱등 재실행이 같은 `now` 를 쓰기 때문이며, 이는 결함이
아니라 SPEC 3 이 요구하는 멱등 그 자체다. 그러나 그 결과로 저장소에 **실행의 경계가
없고**, 7.2 의 배치 성공률은 분모를 셀 수 없다.

그래서 `collect_market` 이 실행마다 `market.run` 한 행을 닫는다. 이 파일이 고정하는
것은 셋이다 —

  (a) 성공한 실행도 실패한 실행도 **각각 한 행**을 남긴다
  (b) 같은 시각으로 두 번 돌려도 **두 행**이다 — 실행을 세는 것이 시각이 아니다
  (c) 감사 행이 느는 것은 **멱등 위반이 아니다.** SPEC 3 의 멱등은 `Region` 값에
      걸리는 것이고, append-only 원장이 실행마다 느는 것은 정상 동작이다.
      (c) 를 여기 적어 두는 이유는 다음 사람이 [행 수가 늘었으니 멱등이 깨졌다]로
      읽고 이 기록을 되돌리는 것을 막기 위해서다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from market_fixtures import FakeFetch, jeonse_items, monthly_items, trade_raw_item

from home_compass.ingest.market.pipeline import (
    ACTION_INGEST,
    ACTION_RUN,
    INGEST_ACTOR,
    collect_market,
)
from home_compass.store.seed import seed_regions

KST = timezone(timedelta(hours=9))
RUN_AT = datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)

CONSTANTS = {
    "ingest.market_outlier_ratio_jeonse": 3.0,
    "ingest.market_outlier_ratio_monthly_deposit": 10.0,
    "ingest.market_outlier_ratio_monthly_rent": 10.0,
    "ingest.market_outlier_ratio_trade": 5.0,
    "ingest.market_outlier_share_threshold": 0.10,
    "ingest.market_min_sample_count": 10,
    "ingest.market_pair_area_band_sqm": 1.0,
    "ingest.market_lookback_months": 3,
    "ingest.market_max_exclusive_area_sqm": 85,
    "ingest.market_max_attempts": 2,
    "ingest.market_request_timeout_seconds": 20,
    "ingest.market_batch_deadline_seconds": 600,
}

APTS = tuple(f"기록테스트아파트{i:02d}" for i in range(12))


def _items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for apt in APTS:
        items += jeonse_items(1, manwon=31_000, apt=apt)
        items += monthly_items(1, deposit_manwon=3_000, rent_manwon=90, apt=apt)
    return items


def _fetching(**over) -> FakeFetch:
    kwargs = dict(default=_items(),
                  trade_default=[trade_raw_item(45_000, apt=apt) for apt in APTS])
    kwargs.update(over)
    return FakeFetch(**kwargs)


@pytest.fixture
def seeded(store):
    seed_regions(store)
    return store


def _runs(store):
    return store.audit.list(action=ACTION_RUN)


# --------------------------------------------------------------------------
# (a) 실행 하나 = 행 하나
# --------------------------------------------------------------------------


def test_a_successful_run_closes_with_one_record(seeded):
    report = collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    assert report.committed is True

    runs = _runs(seeded)
    assert len(runs) == 1
    event = runs[0]
    assert event.actor == INGEST_ACTOR
    # 어휘는 기존 기록과 같다. 새 단어를 만들면 감사 조회가 배치마다 다른 말을 읽는다.
    assert event.outcome == "success"
    assert event.after["committed"] is True
    assert event.after["regions"] == 10
    assert event.after["regionsUpdated"] == 10
    assert event.after["failures"] == []


def test_a_failed_run_closes_with_one_record_too(seeded):
    """실패도 실행이다. 실패한 실행이 기록을 안 남기면 성공률의 분모가 성공 수와 같아진다."""
    report = collect_market(seeded, fetch=_fetching(fail_for={"11440"}),
                            constants=CONSTANTS, now=RUN_AT)
    assert report.committed is False

    runs = _runs(seeded)
    assert len(runs) == 1
    assert runs[0].outcome == "failed"
    assert runs[0].after["committed"] is False
    assert runs[0].after["failures"], "실패 사유가 실행 기록에 없다"
    # 실패한 실행은 아무 지역도 갱신하지 않는다 — 0 이 여기서는 관측된 사실이다.
    assert runs[0].after["regionsUpdated"] == 0


def test_the_run_record_comes_after_the_per_region_records(seeded):
    """읽는 순서가 곧 [실행이 이 행으로 닫혔다] 다. 먼저 적으면 그 뜻이 사라진다."""
    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    actions = [e.action for e in seeded.audit.list()]
    assert actions[-1] == ACTION_RUN
    assert ACTION_INGEST in actions


# --------------------------------------------------------------------------
# (b) 실행을 세는 것은 시각이 아니다 — 7단계가 관측한 결함 그 자체
# --------------------------------------------------------------------------


def test_two_runs_at_the_same_instant_are_two_records(seeded):
    """★ **이 테스트가 이 파일의 이유다.**

    같은 `now` 로 두 번 돌리면 지역별 행은 시각이 같아 한 그룹으로 뭉친다. 실행 기록은
    그러면 안 된다 — 뭉치면 배치 성공률의 분모가 실행 수가 아니라 **서로 다른 시각의
    수**가 되고, 멱등 재실행이 잦을수록 그 값은 실제와 멀어진다.
    """
    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)

    runs = _runs(seeded)
    assert len(runs) == 2, "같은 시각의 두 실행이 한 행으로 뭉쳤다"
    assert {e.at for e in runs} == {RUN_AT}, "두 실행의 시각은 같아야 한다 (멱등)"
    # 시각이 아니라 **식별자**가 둘을 가른다.
    assert len({e.target for e in runs}) == 2
    assert len({e.id for e in runs}) == 2
    assert all(e.after["runId"] == e.target for e in runs)


def test_a_mixed_history_counts_the_way_the_status_screen_counts(seeded):
    """성공 2 · 실패 1 이면 성공률은 66.7% 다. 화면이 세는 것과 같은 것을 여기서 센다."""
    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    collect_market(seeded, fetch=_fetching(fail_for={"11440"}),
                   constants=CONSTANTS, now=RUN_AT + timedelta(days=1))

    runs = _runs(seeded)
    assert [e.outcome for e in runs] == ["success", "success", "failed"]
    assert round(sum(1 for e in runs if e.outcome == "success") * 100 / len(runs), 1) == 66.7


# --------------------------------------------------------------------------
# (c) 멱등의 대상은 `Region` 이지 감사 행이 아니다
# --------------------------------------------------------------------------


def test_the_idempotency_contract_is_on_region_values_not_on_audit_rows(seeded):
    """SPEC 3 「같은 날 재실행해도 결과가 동일해야 한다」의 **대상이 무엇인가**.

    `Region` 값과 계보는 바이트로 같아야 한다. 감사 행은 **늘어야 한다** — append-only
    원장에서 두 번 일어난 일이 한 행으로 보이면 그것이 오히려 기록의 결함이다.
    """
    def region_snapshot():
        return [
            (r.code, r.to_engine_dict(),
             tuple(sorted((n, p.verification, p.fetched_at)
                          for n, p in r.field_provenance.items())))
            for r in seeded.regions.list()
        ]

    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)
    values_after_first = region_snapshot()
    rows_after_first = len(seeded.audit.list())

    collect_market(seeded, fetch=_fetching(), constants=CONSTANTS, now=RUN_AT)

    assert region_snapshot() == values_after_first, "멱등이 깨졌다 (Region 값)"
    assert len(seeded.audit.list()) > rows_after_first, (
        "재실행이 감사 행을 하나도 남기지 않았다 — 두 번 일어난 일이 기록에서 사라졌다"
    )


# ==========================================================================
# 추출 경로의 LLM 지연 — SPEC 7.2 「LLM 호출 성공률과 **지연**」
# ==========================================================================
#
# `ExtractionOutcome.latency_s` 는 예전부터 있었으나 **프로세스 안에만** 있었다. 추출
# 배치는 별도 프로세스이므로 그것이 끝나면 그 수는 사라지고, 상태 화면이 읽을 수 있는
# 곳(저장소)에는 아무것도 남지 않았다. 그래서 감사기록의 `after` 에 함께 싣는다.
#
# **내용은 싣지 않는다** (SPEC 7.1 — 프로바이더로 나가는 내용은 로컬에 남기지 않는다).
# 남는 것은 얼마나 걸렸는가 하나뿐이며, 아래 마지막 테스트가 그 경계를 지킨다.

from home_compass.ingest.extraction import (  # noqa: E402
    EXTRACTION_ACTION,
    MAX_ATTEMPTS_KEY,
    extract_one,
)
from home_compass.store.models import PolicySource  # noqa: E402

from extraction_fixtures import (  # noqa: E402
    FIXTURE_POLICY_ID,
    FIXTURE_SOURCE_ID,
    FIXTURE_TEXT,
    span_for,
    valid_envelope,
)

EXTRACT_NOW = datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)


@pytest.fixture
def extract_source(store) -> PolicySource:
    return store.policy_sources.add(
        PolicySource(
            id=FIXTURE_SOURCE_ID,
            text=FIXTURE_TEXT,
            source_ref="https://example.invalid/fixture",
            fetched_at=EXTRACT_NOW,
            attribution="테스트 픽스처 「가상 제도 문서」 (픽스처) · 해당 없음",
        )
    )


def _calling(envelope, latency_s: float):
    from home_compass.llm.extraction import ExtractionCall

    def call(**_kwargs):
        return ExtractionCall(envelope=envelope, model="fake-model",
                              latency_s=latency_s, usage={"total_tokens": 1})

    return call


@pytest.mark.parametrize("mangle, expected_outcome", [
    (False, "pending"),
    (True, "extraction_failed"),
])
def test_the_extraction_record_carries_the_llm_latency(store, extract_source,
                                                       mangle, expected_outcome):
    """성공한 추출도 거부된 추출도 지연을 남긴다.

    실패 쪽을 빼면 성공률과 지연의 **모집단이 갈라진다** — 느려서 실패한 호출이 지연
    분포에서 빠지면 그 분포는 [빠른 호출만 모은 것] 이 되고 실제보다 좋아 보인다.
    """
    envelope = valid_envelope()
    if mangle:
        span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"   # 원문에 없다

    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants={MAX_ATTEMPTS_KEY: 1}, now=EXTRACT_NOW,
        call=_calling(envelope, 1.234),
    )

    events = store.audit.list(action=EXTRACTION_ACTION)
    assert [e.outcome for e in events] == [expected_outcome]
    assert events[0].after["latency_s"] == 1.234


def test_the_extraction_record_still_carries_no_content(store, extract_source):
    """★ 지연을 실으면서 **내용이 딸려 들어가지 않았는지**를 같이 붙든다.

    원문 조각·인용·규칙 값이 감사기록에 새면 SPEC 7.1 의 개인정보 경계가 아니라
    「프로바이더로 나가는 내용은 로컬에 남기지 않는다」가 먼저 깨진다.
    """
    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants={MAX_ATTEMPTS_KEY: 1}, now=EXTRACT_NOW,
        call=_calling(valid_envelope(), 0.5),
    )
    after = store.audit.list(action=EXTRACTION_ACTION)[0].after
    serialised = str(after)
    # 원문에서 넉넉히 긴 조각을 떼어 그것이 기록에 없음을 본다. 짧은 조각은 우연히
    # 겹칠 수 있으므로 길이를 준다.
    excerpt = FIXTURE_TEXT.strip().splitlines()[0]
    assert len(excerpt) >= 8, "픽스처 첫 줄이 너무 짧아 이 검사가 무의미하다"
    assert excerpt not in serialised, f"원문 조각이 감사기록에 실렸다: {excerpt}"
    assert set(after) == {
        "policy_id", "policy_source_id", "spans", "not_found",
        "attempts", "latency_s", "attempt_codes", "ambiguous_spans",
    }, f"추출 기록의 필드가 늘었다 — 무엇이 늘었는지 확인하라: {sorted(after)}"
