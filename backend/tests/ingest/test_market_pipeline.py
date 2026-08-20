"""SPEC 3 · 3.1 · 10.2(3단계) — 시세 수집 파이프라인.

10.2 의 3단계 완료 기준 넷을 **이 파일이 직접 증명한다.** 넷 다 키 없이 검증된다.

    · 같은 날 재실행 멱등                        -> test_same_day_rerun_is_idempotent
    · 외부 실패 시 이전 값 유지 + stale 표시      -> test_failed_run_keeps_values_and_marks_stale
    · 대응물 없는 3필드가 unverified 로 드러난다  -> test_three_fields_stay_unverified_after_a_successful_run
    · 이상치가 자동 폐기되지 않는다               -> test_outlier_is_flagged_not_discarded

`fetch` 를 주입받는 이유가 여기 있다. 수집기가 자기 안에서 HTTP 를 부르면 이 넷 중
어느 것도 키 없이 증명할 수 없다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from market_fixtures import (
    FakeFetch,
    jeonse_items,
    monthly_items,
    raw_item,
    trade_items,
    trade_raw_item,
)

from firsthome.ingest.market import (
    CONSTANT_KEYS,
    NO_COUNTERPART_FIELDS,
    area_band,
    collect_market,
    conversion_rate_pct,
    jeonse_ratio_pct,
    normalize_deals,
    normalize_trades,
    paired_conversion_rate_pct,
    paired_jeonse_ratio_pct,
    window_months,
)
from firsthome.ingest.market.pipeline import (
    RENT_DERIVED_FIELDS,
    MarketFieldMappingError,
    detect_outliers,
)
from firsthome.store.models import REGION_FACT_FIELDS
from firsthome.store.seed import seed_regions

KST = timezone(timedelta(hours=9))

#: 배치를 돌린 시각. 고정값이다 — 결과가 "언제 돌렸는가"에 의존하면 아무것도 고정하지 못한다.
RUN_AT = datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)

#: 코디네이터가 `contracts/` 에 등재하기로 못박은 7개 키와 그 값 (전부 (d) `our_choice`).
#: 테스트는 값을 **주입**한다. 코드가 값을 알면 fail-closed 조회가 의미를 잃는다.
CONSTANTS = {
    # 통계마다 산포가 달라 배수를 나눴다 (사용자 결정 2026-08-14 · 실측 근거는
    # contracts/model_constants.json 의 해당 항목과 pipeline 의 OUTLIER_RATIO_KEYS 주석).
    "ingest.market_outlier_ratio_jeonse": 3.0,
    "ingest.market_outlier_ratio_monthly_deposit": 10.0,
    "ingest.market_outlier_ratio_monthly_rent": 10.0,
    "ingest.market_outlier_ratio_trade": 5.0,
    "ingest.market_outlier_share_threshold": 0.10,
    "ingest.market_min_sample_count": 10,
    # 셀(법정동+단지명+전용면적 구간)을 만드는 면적 구간 폭. 1.0 은 정수 제곱미터 반올림이다
    # (사용자 결정 2026-08-15 · SPEC 3.1 3차 정정 · 근거는 FINDINGS-6.md 의 민감도 실측).
    "ingest.market_pair_area_band_sqm": 1.0,
    "ingest.market_lookback_months": 3,
    "ingest.market_max_exclusive_area_sqm": 85,
    "ingest.market_max_attempts": 2,
    "ingest.market_request_timeout_seconds": 20,
    "ingest.market_batch_deadline_seconds": 600,
}

#: 시드 값과 **일부러 다르게** 잡는다. 같으면 "값이 갱신됐다"를 단언할 수 없다.
JEONSE_MANWON = 31_000        # 3.1억
DEPOSIT_MANWON = 3_000        # 3천만원
RENT_MANWON = 90              # 90만원
TRADE_MANWON = 45_000         # 4.5억


#: 표본을 흩어 놓을 단지 수. **최소 건수와 같아야 한다** — 파생 비율 2종이 셀 단위로
#: 짝지어지므로(SPEC 3.1 3차 정정) 한 단지에 몰아넣으면 셀이 하나가 되어 문턱에 걸리고,
#: 그러면 이 픽스처를 쓰는 모든 테스트가 「비율이 갱신되지 않는다」를 보게 된다.
#: 금액은 단지마다 전부 같으므로 지역 중앙값도 셀 단위 비도 값은 그대로다.
SAMPLE_APTS = tuple(f"테스트아파트{i:02d}" for i in range(12))


def sample_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for apt in SAMPLE_APTS:
        items += jeonse_items(1, manwon=JEONSE_MANWON, apt=apt)
        items += monthly_items(1, deposit_manwon=DEPOSIT_MANWON,
                               rent_manwon=RENT_MANWON, apt=apt)
    return items


def sample_trades() -> list[dict[str, str]]:
    return [trade_raw_item(TRADE_MANWON, apt=apt) for apt in SAMPLE_APTS]


def fetching(**over) -> FakeFetch:
    """전월세·매매 둘 다 정상인 기본 수집기."""
    kwargs = dict(default=sample_items(), trade_default=sample_trades())
    kwargs.update(over)
    return FakeFetch(**kwargs)


@pytest.fixture
def seeded(store):
    seed_regions(store)
    return store


def snapshot(store) -> list[tuple]:
    """저장소 상태를 비교 가능한 형태로 뽑는다. 계보까지 포함한다 — 값만 보면
    "계보가 조용히 바뀌었다"를 놓친다."""
    return [
        (
            r.code, r.jeonse_median_krw, r.monthly_deposit_krw, r.monthly_rent_krw,
            r.maintenance_fee_krw, r.jeonse_ratio_pct, r.conversion_rate_pct,
            r.market_risk, r.guarantee_available, r.provenance.to_dict(),
            tuple(sorted((k, tuple(sorted(p.to_dict().items())))
                         for k, p in r.field_provenance.items())),
        )
        for r in store.regions.list()
    ]


# --------------------------------------------------------------------------
# 수집 실패의 기대치 — **값과 계보를 나눠 본다**
# --------------------------------------------------------------------------
#
# ★ 예전에는 `snapshot(store) == before` 한 줄이 둘을 같이 붙들었고, 그때는 그것이
#   성립했다 — 시드가 8필드 전부 `unverified` 라 실패해도 계보가 움직일 곳이 없었기
#   때문이다. 계약 결정 #40 이 시드를 실수집으로 굳히면서 **실측 5필드가 `verified` 로
#   들어왔고**, 이제 수집이 실패하면 그 다섯이 `stale` 로 내려간다. 그것이 SPEC 9.2.1 이
#   요구하는 동작이므로 스냅샷 통째 비교는 더 이상 쓸 수 없다.
#
#   **그래서 값 비교를 같이 풀어 버리면 「이전 값 유지」가 무검증이 된다.** 나눠서
#   둘 다 명시로 단정한다 — 값은 하나도 바뀌지 않고, 계보는 `verified` 만 `stale` 로.


def values_only(store) -> list[tuple]:
    """계보를 뺀 **값만**. 「이전 값 유지」는 이쪽으로 단정한다."""
    return [(r.code, r.to_engine_dict()) for r in store.regions.list()]


def lineage(store) -> dict[str, dict[str, str]]:
    return {
        r.code: {n: r.provenance_for(n).verification for n in REGION_FACT_FIELDS}
        for r in store.regions.list()
    }


def stale_downgraded(before: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """`verified` 였던 것만 `stale` 로. 나머지는 그대로 (SPEC 9.2.1 · pipeline._mark_stale).

    출처가 없던 필드(`unverified`)를 `stale` 로 바꾸면 등급이 **좋아진다**(C -> B).
    실패를 이용해 데이터를 좋아 보이게 만드는 셈이므로 그렇게 되면 안 된다.
    """
    return {
        code: {n: ("stale" if v == "verified" else v) for n, v in names.items()}
        for code, names in before.items()
    }


# --------------------------------------------------------------------------
# 1. 정규화 — 단위 함정과 조용한 0건
# --------------------------------------------------------------------------


def test_deposit_is_manwon_with_commas():
    """`33,000` 은 33,000**만원** = 3.3억이다. 콤마를 지우고 만원을 곱하지 않으면
    3.3만원짜리 전세가 되고, 그 숫자는 판정을 통째로 거짓말로 만든다."""
    deals = normalize_deals([raw_item(33_000, 0)], region_code="11440", max_area_sqm=85)
    assert deals[0].deposit_krw == 330_000_000
    assert deals[0].monthly_rent_krw == 0


def test_monthly_rent_is_also_manwon():
    deals = normalize_deals([raw_item(2_000, 85)], region_code="11440", max_area_sqm=85)
    assert deals[0].deposit_krw == 20_000_000
    assert deals[0].monthly_rent_krw == 850_000


def test_jeonse_and_monthly_are_told_apart_by_the_rent_being_zero():
    deals = normalize_deals(
        [raw_item(28_000, 0), raw_item(2_000, 85)], region_code="11440", max_area_sqm=85
    )
    assert [d.is_jeonse for d in deals] == [True, False]


def test_area_above_the_limit_is_out_of_scope_not_an_outlier():
    """전용 85제곱미터 상한은 **집계 대상의 정의**다 (우리 선택). 이상치 폐기와 다르다 —
    범위 밖이라 애초에 세지 않는 것이고, 그 사실은 보고서의 건수 차이로 드러난다."""
    deals = normalize_deals(
        [raw_item(28_000, 0, area=59.9), raw_item(90_000, 0, area=134.5)],
        region_code="11440", max_area_sqm=85,
    )
    assert len(deals) == 1
    assert deals[0].exclusive_area_sqm == 59.9


def test_unknown_field_names_fail_loudly_with_the_observed_keys():
    """응답 항목명은 2차출처까지만 확인됐다. 실제 이름이 다르면 **조용한 0건**이 되는데,
    그 상태에서는 아무도 무엇이 잘못됐는지 모른다. 관측된 키를 들고 실패한다."""
    with pytest.raises(MarketFieldMappingError) as exc:
        normalize_deals([{"보증금액": "33000", "월세금액": "0"}], region_code="11440",
                        max_area_sqm=85)
    message = str(exc.value)
    assert "deposit" in message      # 우리가 기대한 이름
    assert "보증금액" in message      # 실제로 관측된 이름


def test_the_second_candidate_name_is_accepted():
    """전용면적은 `exclUseAr` 와 `excluUseAr` 두 표기가 돌아다닌다. 둘 다 받되
    **아무 이름이나** 받지는 않는다 (위 테스트가 그것을 고정한다)."""
    item = raw_item(28_000, 0)
    item["excluUseAr"] = item.pop("exclUseAr")
    deals = normalize_deals([item], region_code="11440", max_area_sqm=85)
    assert deals[0].exclusive_area_sqm == 59.9


def test_blank_values_are_skipped_not_guessed():
    """취소·정정 등으로 값이 빈 행이 온다. 0 으로 읽으면 중앙값이 내려가고,
    그 방향은 **관대한 쪽**이다 (HANDOFF 불변조건 7)."""
    item = raw_item(28_000, 0)
    item["deposit"] = "   "
    deals = normalize_deals([item], region_code="11440", max_area_sqm=85)
    assert deals == []


# --------------------------------------------------------------------------
# 2. 파생 계산 — 산식은 문서로 남긴다 (SPEC 3.1)
# --------------------------------------------------------------------------


def test_conversion_rate_follows_the_published_formula():
    """한국부동산원 통계산출항목 원문:
    전월세전환율(%) = [월세 * 12 / (전세가격 - 월세보증금)] * 100
    (https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?mi=9807&cntntsId=1189)

    문서의 예시 그대로 검산한다 — 전세 1억, 보증금 1천만원, 월세 90만원 -> 12%.

    ★ 산식 문자열은 원문확인됐지만 **그 페이지는 「오피스텔 가격동향조사」 것이다**
      (6차 실사 A4 · 본문이 다섯 번 오피스텔이라고 말한다). 우리는 아파트 실거래를
      모으므로 인용이 어긋나 있고, 아파트 쪽의 같은 성격 페이지는 **찾지 못했다.**
      URL 을 지어내지 않고 그 사실을 계보에 적는다
      (`test_the_conversion_lineage_admits_the_citation_is_the_officetel_page`).
    """
    assert conversion_rate_pct(100_000_000, 10_000_000, 900_000) == 12.0


def test_conversion_rate_is_none_when_the_denominator_is_not_positive():
    """월세 보증금이 전세가 이상이면 분모가 0 이하다. 그 자리에 아무 숫자나 넣는 대신
    비운다 — 빈 칸은 실패가 아니다."""
    assert conversion_rate_pct(100_000_000, 100_000_000, 900_000) is None
    assert conversion_rate_pct(100_000_000, 120_000_000, 900_000) is None


def test_jeonse_ratio_is_the_ratio_of_medians_not_the_median_of_ratios():
    """★ 둘은 다른 값이다.

        median(전세) / median(매매)      <- 중앙값의 비   (우리가 내는 값)
        median(전세_i / 매매_i)          <- 비의 중앙값   (같은 물건을 짝지어야 성립)

    실거래가는 전월세와 매매가 **같은 물건으로 짝지어지지 않는다.** 거래된 물건이
    서로 다르므로 비의 중앙값은 계산 자체가 불가능하다. 그래서 중앙값의 비를 쓰고,
    그 사실을 산식 문서와 계보에 적는다.
    """
    assert jeonse_ratio_pct(310_000_000, 450_000_000) == 68.89


def test_jeonse_ratio_is_none_without_a_trade_median():
    assert jeonse_ratio_pct(310_000_000, None) is None
    assert jeonse_ratio_pct(310_000_000, 0) is None


# --------------------------------------------------------------------------
# 2-1. 짝짓기 — 셀 = 법정동 + 단지명 + 전용면적 구간 (SPEC 3.1 3차 정정)
# --------------------------------------------------------------------------

BAND = CONSTANTS["ingest.market_pair_area_band_sqm"]


def _deals(*items: dict[str, str]):
    return normalize_deals(items, region_code="11440", max_area_sqm=85)


def _trades(*items: dict[str, str]):
    return normalize_trades(items, region_code="11440", max_area_sqm=85)


def test_the_area_band_is_a_rounding_to_the_registered_width():
    """구간 폭은 등재된 상수이며 코드에 기본값을 두지 않는다.

    한 단지 안의 같은 평형은 소수점만 다르고(59.82/59.99) 다른 평형은 멀다(59 vs 84).
    폭 1.0 이 앞쪽을 한 셀로 모으고 뒤쪽을 가른다.
    """
    assert area_band(59.82, 1.0) == area_band(59.99, 1.0) == 60.0
    assert area_band(59.4, 1.0) != area_band(84.9, 1.0)
    # 폭이 5 면 59.4 와 60.4 가 한 칸에 모인다 — 폭이 셀 정의를 바꾼다는 사실 자체.
    assert area_band(59.4, 5.0) == area_band(60.4, 5.0) == 60.0
    assert area_band(59.4, 1.0) != area_band(60.4, 1.0)


def test_a_cell_is_the_legal_dong_and_the_complex_and_the_band_together():
    """`aptNm` 만으로 묶으면 **같은 시군구의 동명 단지**가 한 셀이 된다 (6차 실사 B0).

    같은 이름의 단지를 다른 법정동에 두면 짝이 성립하지 않아야 한다 — 성립하면
    서로 다른 동네의 전세와 매매를 짝지은 것이다.
    """
    paired = paired_jeonse_ratio_pct(
        _deals(raw_item(21_000, 0, apt="같은이름")),
        _trades(trade_raw_item(40_000, apt="같은이름")),
        band_sqm=BAND,
    )
    assert paired.cells == 1 and paired.value_pct == 52.5

    other_dong = dict(trade_raw_item(40_000, apt="같은이름"), umdNm="다른동")
    assert paired_jeonse_ratio_pct(
        _deals(raw_item(21_000, 0, apt="같은이름")), _trades(other_dong), band_sqm=BAND,
    ).cells == 0

    assert paired_jeonse_ratio_pct(
        _deals(raw_item(21_000, 0, apt="같은이름", area=59.9)),
        _trades(trade_raw_item(40_000, apt="같은이름", area=84.9)),
        band_sqm=BAND,
    ).cells == 0, "평형이 다른데 짝이 됐다"


def test_the_cell_median_comes_first_so_a_crowded_cell_counts_once():
    """★ 셀 하나당 비 하나. 거래를 데카르트 곱으로 짝지으면 거래가 많은 셀이 중앙값을
    지배한다 — 그것이 셀 중앙값을 먼저 취하는 이유다 (FINDINGS-6.md B0)."""
    jeonse = [raw_item(21_000, 0, apt=f"작은단지{i}") for i in range(3)]
    trades = [trade_raw_item(40_000, apt=f"작은단지{i}") for i in range(3)]
    jeonse += [raw_item(60_000, 0, apt="큰단지") for _ in range(30)]
    trades += [trade_raw_item(80_000, apt="큰단지") for _ in range(30)]

    paired = paired_jeonse_ratio_pct(_deals(*jeonse), _trades(*trades), band_sqm=BAND)
    assert paired.cells == 4
    # 셀 넷의 비 [52.5, 52.5, 52.5, 75.0] 의 중앙값. 30건짜리 셀이 한 칸으로 세어진다.
    assert paired.value_pct == 52.5


def test_cells_without_a_ratio_are_counted_not_silently_dropped():
    """분모(전세 - 월세보증금)가 0 이하인 셀은 비를 만들 수 없다. **몇 개가 빠졌는지**를
    남긴다 — 모르면 그 중앙값이 무엇의 중앙값인지 말할 수 없다."""
    jeonse = [raw_item(21_000, 0, apt="정상"), raw_item(2_000, 0, apt="역전")]
    monthly = [raw_item(1_000, 60, apt="정상"), raw_item(3_000, 60, apt="역전")]

    paired = paired_conversion_rate_pct(
        _deals(*jeonse), _deals(*monthly), band_sqm=BAND,
    )
    assert paired.cells == 1 and paired.dropped_cells == 1
    assert paired.value_pct == 3.6


def test_paired_ratios_are_empty_rather_than_guessed_when_nothing_pairs():
    """짝이 하나도 없으면 값을 만들지 않는다. 빈 칸은 실패가 아니다."""
    paired = paired_jeonse_ratio_pct(
        _deals(raw_item(21_000, 0, apt="전세만")),
        _trades(trade_raw_item(40_000, apt="매매만")),
        band_sqm=BAND,
    )
    assert paired.value_pct is None and paired.cells == 0


def test_trade_amount_is_manwon_with_commas_under_a_different_field_name():
    """매매는 금액이 `dealAmount`, 전용면적이 `excluUseAr` 다 — 전월세와 이름이 다르다."""
    trades = normalize_trades([trade_raw_item(45_000)], region_code="11440", max_area_sqm=85)
    assert trades[0].amount_krw == 450_000_000


def test_trade_items_are_filtered_by_the_same_area_limit():
    """집계 조건이 전세와 매매에 **같아야** 한다. 한쪽만 다르면 비율이 조건 차이를 잰다."""
    trades = normalize_trades(
        [trade_raw_item(45_000, area=59.9), trade_raw_item(120_000, area=134.5)],
        region_code="11440", max_area_sqm=85,
    )
    assert len(trades) == 1


def test_unknown_trade_field_names_fail_loudly_too():
    with pytest.raises(MarketFieldMappingError) as exc:
        normalize_trades([{"거래금액": "45000"}], region_code="11440", max_area_sqm=85)
    assert "dealAmount" in str(exc.value)
    assert "거래금액" in str(exc.value)


# --------------------------------------------------------------------------
# 3. 이상치 — 폐기 금지 (SPEC 3)
# --------------------------------------------------------------------------


def test_detect_outliers_flags_both_tails():
    values = [100, 100, 100, 100, 100, 1_000, 10]
    flagged = detect_outliers(values, ratio=3.0)
    assert sorted(flagged) == [10, 1_000]


def test_detect_outliers_returns_nothing_on_a_tight_sample():
    assert detect_outliers([100, 110, 90, 105], ratio=3.0) == []


def test_outlier_is_flagged_not_discarded(seeded):
    """SPEC 10.2 3단계 — **이상치가 자동 폐기되지 않는다.**

    집계에서 빼는 것도 폐기다. 값은 그대로 들어가고 **건별로 기록**된다.

    ★ 기록과 판정은 다른 축이다. 여기서 고정하는 것은 **기록** 쪽이며, 비율이 문턱을
      넘든 안 넘든 성립해야 한다. 판정(`unverified` 표시)은 아래 두 테스트가 나눠 본다.
    """
    items = sample_items() + [raw_item(120_000, 0, apt="꼭대기집")]  # 12억 전세
    fetch = fetching(default=items)
    report = collect_market(seeded, fetch=fetch, constants=CONSTANTS, now=RUN_AT)

    assert report.committed is True
    outlier_regions = {o.region_code for o in report.outliers}
    assert outlier_regions == {r.code for r in seeded.regions.list()}

    # 폐기되지 않았다 — 표본 수가 이상치를 **포함한** 25 건이다.
    outcome = next(o for o in report.regions if o.code == "11440")
    assert outcome.deals_used == 25

    # 감사기록에 건별로 남는다 — 이상치가 몇 건이었는지 나중에 셀 수 있어야 한다.
    events = seeded.audit.list(action="market.outlier")
    assert len(events) == len(report.outliers)
    assert any(e.after["aptNm"] == "꼭대기집" for e in events if e.target == "11440")


def test_a_lone_outlier_does_not_mark_the_region(seeded):
    """이상치 1건(25건 중 4%)은 지역을 `unverified` 로 만들지 않는다.

    **왜 이 테스트가 생겼나.** 원래 규칙은 [이상치가 한 건이라도 있으면 unverified] 였다.
    실데이터로 돌렸더니 **10개 지역 중 9개가 걸렸다** — 배수를 통계별로 나눠 이상치를
    4420 -> 473 건으로 줄인 뒤에도 그대로였다. 큰 표본에서 극단값 한둘은 늘 있기 때문이다.

    늘 켜져 있는 표시는 검토 신호가 못 된다. SPEC 3 이 [검토 대상으로 올린다]고 한 것이
    무의미해진다. 그래서 판정을 **비율**로 옮겼다 (사용자 결정 2026-08-14).
    """
    items = sample_items() + [raw_item(120_000, 0, apt="꼭대기집")]
    report = collect_market(seeded, fetch=fetching(default=items),
                            constants=CONSTANTS, now=RUN_AT)
    assert report.committed is True

    # 기록은 남는다 (위 테스트) — 그러나 판정은 바뀌지 않는다.
    region = seeded.regions.get("11440")
    assert region.field_provenance["jeonseMedianKRW"].verification == "verified"
    assert all(o.exceeds_threshold is False for o in report.outliers)


def test_an_unusual_share_of_outliers_marks_the_region(seeded):
    """이상치 비율이 문턱을 넘으면 지역이 `unverified` 로 표시된다.

    문턱 아래에서 안 걸리는 것만 보면 [영원히 안 걸리는 검사]와 구별되지 않는다.
    넘는 쪽도 함께 고정해야 규칙이 살아 있다는 증거가 된다.
    """
    # 24건의 정상 표본에 12억 전세 6건 -> 전세 표본의 20% (문턱 10% 초과)
    items = sample_items() + [raw_item(120_000, 0, apt=f"꼭대기집{i}") for i in range(6)]
    report = collect_market(seeded, fetch=fetching(default=items),
                            constants=CONSTANTS, now=RUN_AT)
    assert report.committed is True

    region = seeded.regions.get("11440")
    assert region.field_provenance["jeonseMedianKRW"].verification == "unverified"
    assert any(o.exceeds_threshold for o in report.outliers)


# --------------------------------------------------------------------------
# 4. 성공 경로 — 무엇이 갱신되고 무엇이 갱신되지 않는가 (SPEC 3.1)
# --------------------------------------------------------------------------


def test_successful_run_updates_the_derivable_fields(seeded):
    before = seeded.regions.get("11440")
    report = collect_market(seeded, fetch=fetching(),
                            constants=CONSTANTS, now=RUN_AT)
    after = seeded.regions.get("11440")

    assert report.committed is True
    assert after.jeonse_median_krw == 310_000_000
    assert after.monthly_deposit_krw == 30_000_000
    assert after.monthly_rent_krw == 900_000
    # 900,000 * 12 / (310,000,000 - 30,000,000) * 100 = 3.857...
    assert after.conversion_rate_pct == 3.86
    assert before.jeonse_median_krw != after.jeonse_median_krw

    for name in RENT_DERIVED_FIELDS:
        provenance = after.field_provenance[name]
        assert provenance.source_kind == "market"
        assert provenance.verification == "verified"
        assert "국토교통부" in provenance.source_name


def test_three_fields_stay_unverified_after_a_successful_run(seeded):
    """SPEC 10.2 3단계 — **대응물 없는 3필드가 unverified 로 드러난다.**

    통계에서 유도하지도, 그럴듯한 값을 넣지도 않는다. 값은 시드 그대로이고
    계보도 시드 그대로다 — 국토부 이름이 이 셋에 붙으면 그 순간 예시값이
    실데이터인 척하게 된다 (SPEC 3.1 이 명시적으로 금지한다).
    """
    before = seeded.regions.get("11440")
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    after = seeded.regions.get("11440")

    assert after.maintenance_fee_krw == before.maintenance_fee_krw
    assert after.market_risk == before.market_risk
    assert after.guarantee_available == before.guarantee_available

    for name in NO_COUNTERPART_FIELDS:
        provenance = after.field_provenance[name]
        assert provenance.verification == "unverified"
        assert "국토교통부" not in (provenance.source_name or "")


def test_jeonse_ratio_is_derived_from_the_trade_endpoint(seeded):
    """사용자 결정으로 매매 API 가 수집 대상에 들어와 전세가율이 도출 가능해졌다.

    310,000,000 / 450,000,000 * 100 = 68.888... -> 68.89
    """
    before = seeded.regions.get("11440")
    collect_market(seeded, fetch=fetching(), constants=CONSTANTS, now=RUN_AT)
    after = seeded.regions.get("11440")

    # 시드값을 리터럴로 적지 않는다 — 굳히기(결정 #40)로 한 번 바뀌었고 또 바뀔 수 있다.
    # 여기서 재는 것은 「매매 엔드포인트가 이 값을 만들었다」이지 시드가 무엇이었나가 아니다.
    assert after.jeonse_ratio_pct != before.jeonse_ratio_pct
    assert after.jeonse_ratio_pct == 68.89
    provenance = after.field_provenance["jeonseRatioPct"]
    assert provenance.verification == "verified"
    # ★ 계보가 **무엇을 계산했는지**를 말한다. 2026-08-15 이전에는 「중앙값의 비」였고
    #   그 문구는 이제 거짓이다. 짝짓기 단위까지 적어야 [무엇을 짝지었나]가 드러난다.
    assert "비의 중앙값" in provenance.source_name
    assert "중앙값의 비" not in provenance.source_name
    assert "법정동+단지명+전용면적 구간" in provenance.source_name


#: ★ 「중앙값의 비」와 「비의 중앙값」이 **다른 값을 내는** 표본.
#:
#: 거래가 몰린 셀 하나(12건)와 거래가 한 건씩인 셀 열 개로 만든다. 지역 전체를 한 통에
#: 넣고 중앙값을 구하면 **몰린 셀이 중앙값을 가져간다** — 22건 중 12건이 그 셀이기
#: 때문이다. 셀마다 비를 구해 그 비들의 중앙값을 취하면 열 개의 셀이 하나로 세어져
#: 결과가 뒤집힌다. 6차 실사가 실데이터에서 잰 것이 이 구조다 (FINDINGS-6.md B3·B4).
PAIR_LIGHT_CELLS = 10
PAIR_HEAVY_DEALS = 12


def paired_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for i in range(PAIR_LIGHT_CELLS):                       # 전세 2.1억 / 보증 1천 / 월세 60
        apt = f"짝단지{i:02d}"
        items += jeonse_items(1, manwon=21_000, apt=apt)
        items += monthly_items(1, deposit_manwon=1_000, rent_manwon=60, apt=apt)
    items += jeonse_items(PAIR_HEAVY_DEALS, manwon=60_000, apt="짝대단지")
    items += monthly_items(PAIR_HEAVY_DEALS, deposit_manwon=5_000, rent_manwon=100,
                           apt="짝대단지")
    return items


def paired_trades() -> list[dict[str, str]]:
    return (
        [trade_raw_item(40_000, apt=f"짝단지{i:02d}") for i in range(PAIR_LIGHT_CELLS)]
        + [trade_raw_item(80_000, apt="짝대단지") for _ in range(PAIR_HEAVY_DEALS)]
    )


def test_derived_ratios_are_the_median_of_cell_ratios_not_the_ratio_of_medians(seeded):
    """★ 이 과업이 바꾸는 값 자체 (SPEC 3.1 3차 정정 · 계약 결정 #35).

    같은 표본에서 두 산식이 무엇을 내는지 나란히 적는다.

        중앙값의 비 (현행)   전세 median 6억 / 매매 median 8억            -> 75.00
        비의 중앙값 (새 값)  셀 10개가 52.5 · 셀 1개가 75 -> 중앙값        -> 52.50

        중앙값의 비 (현행)   100만*12 / (6억 - 5천만)                     ->  2.18
        비의 중앙값 (새 값)  셀 10개가 3.6 · 셀 1개가 2.18 -> 중앙값       ->  3.60

    현행이 몰린 셀 하나를 지역의 대표값으로 삼는다. 그것이 10개 지역 전부에서 전환율을
    낮추던 편향이며(FINDINGS-6.md B4), 낮은 전환율은 `tco` 의 월세를 싸게 만드는
    **관대한 방향**이다 (불변조건 7).
    """
    report = collect_market(
        seeded,
        fetch=fetching(default=paired_items(), trade_default=paired_trades()),
        constants=CONSTANTS, now=RUN_AT,
    )
    after = seeded.regions.get("11440")

    assert report.committed is True
    assert after.jeonse_ratio_pct == 52.5
    assert after.conversion_rate_pct == 3.6


def test_a_crowded_cell_does_not_dominate_the_median(seeded):
    """★ 거래를 데카르트 곱으로 짝지으면 안 되는 이유를 값으로 고정한다.

    셀 안에서 거래끼리 곱으로 짝지으면 몰린 셀이 12x12=144 쌍을 내고 나머지 열 개 셀은
    한 쌍씩만 낸다 — 중앙값은 다시 몰린 셀의 것(75.00 · 2.18)이 되어 현행과 같아진다.
    그래서 **셀 안에서 각 통계의 중앙값을 먼저 구하고 셀 하나당 비 하나**를 만든다.
    """
    collect_market(
        seeded,
        fetch=fetching(default=paired_items(), trade_default=paired_trades()),
        constants=CONSTANTS, now=RUN_AT,
    )
    after = seeded.regions.get("11440")

    assert after.jeonse_ratio_pct != 75.0, "몰린 셀이 중앙값을 가져갔다 (곱으로 짝지었다)"
    assert after.conversion_rate_pct != 2.18


def test_the_conversion_lineage_admits_the_citation_is_the_officetel_page(seeded):
    """★ 계보는 **우리가 무엇을 인용했는가**를 말하는 자리다 (6차 실사 A4).

    산식 페이지가 오피스텔 조사 것이고 아파트 대응 페이지를 찾지 못했다는 사실이
    거기 없으면, 계보는 아파트 산식을 원문확인한 것처럼 읽힌다.
    """
    collect_market(seeded, fetch=fetching(), constants=CONSTANTS, now=RUN_AT)
    source = seeded.regions.get("11440").field_provenance["conversionRatePct"].source_name

    assert "비의 중앙값" in source and "중앙값의 비" not in source
    assert "오피스텔" in source and "찾지 못했다" in source


def test_jeonse_ratio_is_not_updated_when_the_trade_sample_is_short(seeded):
    """매매 표본이 최소 건수에 못 미치면 **갱신하지 않는다** — 이전 값 유지 + 출처 미특정.
    모자란 표본으로 계산해 내놓지 않는다. 다만 전월세 통계는 정상이므로 **실행은 성공**이다
    (표본 부족을 실패로 다루면 전세가율 하나가 나머지 넷을 인질로 잡는다).

    ★ 문턱이 셀 수로 옮겨간 뒤에도 이 규율은 그대로다. 짝이 성립한 셀은 셀마다 매매가
      최소 한 건씩 있어야 하므로 **셀 수 <= 매매 표본 수**이고, 매매가 최소 건수에
      못 미치면 셀 수도 못 미친다. 새 규칙이 옛 규칙을 포함한다 (SPEC 3.1 3차 정정)."""
    before = seeded.regions.get("11440")
    report = collect_market(
        seeded, fetch=fetching(trade_per_region={"11440": trade_items(3, manwon=TRADE_MANWON)}),
        constants=CONSTANTS, now=RUN_AT,
    )
    after = seeded.regions.get("11440")

    assert report.committed is True
    assert after.jeonse_ratio_pct == before.jeonse_ratio_pct
    # ★ 갱신하지 않은 필드는 **이전 계보를 그대로** 들고 간다 (pipeline._existing_field_provenance).
    #   굳힌 시드에서는 그것이 `verified` 다 — 실수집 시각의 계보가 그 값의 사실이기
    #   때문이며, 낡음은 `stale` 이 따로 말한다. 계보가 헐거워진 것이 아니라
    #   **값과 계보가 함께 유지된 것**이다.
    assert (after.field_provenance["jeonseRatioPct"]
            == before.field_provenance["jeonseRatioPct"])
    assert after.jeonse_median_krw == 310_000_000        # 나머지는 갱신됐다
    outcome = next(o for o in report.regions if o.code == "11440")
    assert outcome.trade_sample == 3


def test_derived_ratios_are_not_updated_when_too_few_cells_pair(seeded):
    """★ 짝이 성립한 **셀 수**에 표본 최소 건수를 그대로 건다 (SPEC 3.1 3차 정정).

    새 문턱 상수를 만들지 않는다 — 준거 없는 문턱이 하나 늘면 감도분석에서 다른 (d) 와
    같은 무게를 갖는다. 미달이면 두 비율을 **갱신하지 않고** 이전 값과 계보를 그대로 둔다.
    전월세 통계는 정상이므로 **실행은 성공**이다.

    표본 24건이 단지 하나에 다 들어 있는 경우다. 건수는 넉넉한데 **셀이 하나**다 —
    그 하나로 지역을 대표하면 그것이 6차 실사가 잰 편향 그 자체가 된다.
    """
    one_complex = jeonse_items(12, manwon=JEONSE_MANWON) + monthly_items(
        12, deposit_manwon=DEPOSIT_MANWON, rent_manwon=RENT_MANWON
    )
    before = seeded.regions.get("11440")
    report = collect_market(
        seeded,
        fetch=fetching(default=one_complex, trade_default=trade_items(12, manwon=TRADE_MANWON)),
        constants=CONSTANTS, now=RUN_AT,
    )
    after = seeded.regions.get("11440")

    assert report.committed is True
    assert after.jeonse_median_krw == 310_000_000                  # 나머지는 갱신됐다
    assert after.jeonse_ratio_pct == before.jeonse_ratio_pct       # 이전 값 유지
    assert after.conversion_rate_pct == before.conversion_rate_pct
    # 값을 유지했으면 계보도 유지한다 — 위 테스트와 같은 이유다.
    for name in ("jeonseRatioPct", "conversionRatePct"):
        assert after.field_provenance[name] == before.field_provenance[name], name

    outcome = next(o for o in report.regions if o.code == "11440")
    assert outcome.jeonse_sample == 12 and outcome.trade_sample == 12
    assert outcome.ratio_cells == 1 and outcome.conversion_cells == 1

    # 갱신하지 않았다는 사실이 감사기록에 남는다 — 「왜 이 필드만 예시값인가」의 답이다.
    event = next(e for e in seeded.audit.list(action="market.ingest") if e.target == "11440")
    assert {"jeonseRatioPct", "conversionRatePct"} <= set(event.after["untouched"])


def test_the_matched_cell_count_is_reported_per_region(seeded):
    """표본이 몇 건인지와 짝이 몇 셀인지는 **다른 사실**이다. 셀 수를 보고서에 남기지
    않으면 문턱에 걸린 지역이 왜 걸렸는지 실기동에서 말할 수 없다."""
    report = collect_market(seeded, fetch=fetching(), constants=CONSTANTS, now=RUN_AT)
    outcome = next(o for o in report.regions if o.code == "11440")

    assert outcome.ratio_cells == len(SAMPLE_APTS)
    assert outcome.conversion_cells == len(SAMPLE_APTS)
    assert outcome.conversion_cells_dropped == 0


def test_a_failing_trade_fetch_blocks_the_whole_run(seeded):
    """표본 부족과 **수집 실패**는 다르다. 후자는 외부 장애이므로 전건 규칙이 걸린다."""
    before_values, before_lineage = values_only(seeded), lineage(seeded)
    report = collect_market(seeded, fetch=fetching(trade_fail_for={"11440"}),
                            constants=CONSTANTS, now=RUN_AT)

    assert report.committed is False
    assert values_only(seeded) == before_values          # 이전 값 유지
    assert lineage(seeded) == stale_downgraded(before_lineage)   # + stale
    assert any("11440" in reason and "매매" in reason for reason in report.failures)


def test_record_summary_is_the_worst_of_the_fields(seeded):
    """SPEC 2.4 — 수집이 성공해도 3필드가 unverified 라 레코드 요약은 unverified 다.
    이것이 지역 단위 계보 하나로는 `stale` 을 볼 수 없었던 이유다."""
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    assert seeded.regions.get("11440").provenance.verification == "unverified"


def test_observed_at_is_the_deal_date_and_fetched_at_is_the_run(seeded):
    """계약 결정 #12 — 관측 기준시점과 취득 시각을 섞지 않는다.
    `Z` 표기를 쓰지 않고 KST 는 `+09:00` 이다 (결정 #4)."""
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    provenance = seeded.regions.get("11440").field_provenance["jeonseMedianKRW"]

    assert provenance.observed_at == "2026-06-15T00:00:00+09:00"
    assert provenance.fetched_at == "2026-08-14T09:00:00+09:00"
    assert not provenance.observed_at.endswith("Z")


def test_window_is_the_lookback_months_ending_with_the_run_month():
    assert window_months(RUN_AT, 3) == ("202606", "202607", "202608")
    assert window_months(datetime(2026, 2, 3, tzinfo=KST), 3) == ("202512", "202601", "202602")


# --------------------------------------------------------------------------
# 5. 멱등성 (SPEC 10.2 3단계)
# --------------------------------------------------------------------------


def test_same_day_rerun_is_idempotent(seeded):
    """**같은 날 재실행 멱등.** 같은 입력·같은 시각이면 저장소 상태가 바이트로 같다."""
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    first = snapshot(seeded)

    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    assert snapshot(seeded) == first


def test_rerun_later_the_same_day_changes_only_when_we_fetched(seeded):
    """시각이 다르면 `fetched_at` 은 **정직하게** 달라진다. 판정에 쓰이는 값과
    관측 기준시점은 그대로다 — 그 둘까지 흔들리면 멱등이 아니다."""
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    before = seeded.regions.get("11440")

    later = RUN_AT.replace(hour=18)
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=later)
    after = seeded.regions.get("11440")

    assert after.to_engine_dict() == before.to_engine_dict()
    assert after.field_provenance["jeonseMedianKRW"].observed_at == \
        before.field_provenance["jeonseMedianKRW"].observed_at
    assert after.field_provenance["jeonseMedianKRW"].fetched_at == \
        "2026-08-14T18:00:00+09:00"


# --------------------------------------------------------------------------
# 6. 실패 — 이전 값 유지 + stale, 그리고 부분 갱신 없음
# --------------------------------------------------------------------------


def test_failed_run_keeps_values_and_marks_stale(seeded):
    """SPEC 10.2 3단계 — **외부 실패 시 이전 값 유지 + `stale` 표시.**

    수집에 성공한 적이 있는 필드만 `stale` 이 된다. 출처가 없던 필드를 `stale` 로
    바꾸면 등급이 **좋아진다**(C -> B). 그것은 실패를 이용해 데이터를 좋아 보이게
    만드는 것이다.
    """
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    good = seeded.regions.get("11440")
    assert good.field_provenance["jeonseMedianKRW"].verification == "verified"

    later = RUN_AT + timedelta(days=1)
    report = collect_market(
        seeded, fetch=fetching(fail_for={"11440"}),
        constants=CONSTANTS, now=later,
    )
    after = seeded.regions.get("11440")

    assert report.committed is False
    assert after.to_engine_dict() == good.to_engine_dict()          # 값은 그대로
    assert after.field_provenance["jeonseMedianKRW"].verification == "stale"
    assert after.field_provenance["jeonseMedianKRW"].observed_at == \
        good.field_provenance["jeonseMedianKRW"].observed_at         # 계보의 나머지도 그대로
    assert after.field_provenance["marketRisk"].verification == "unverified"   # 좋아지지 않는다


def test_one_region_failing_updates_nothing_anywhere(seeded):
    """부분 갱신을 만들지 않는다. 지역 일부만 새 값이 된 저장소는 그 상태가
    무엇을 뜻하는지 아무도 모른다."""
    before_values, before_lineage = values_only(seeded), lineage(seeded)
    report = collect_market(
        seeded, fetch=fetching(fail_for={"12330"}),
        constants=CONSTANTS, now=RUN_AT,
    )

    assert report.committed is False
    assert values_only(seeded) == before_values          # 부분 갱신이 없다
    assert lineage(seeded) == stale_downgraded(before_lineage)
    assert any("12330" in reason for reason in report.failures)


def test_sample_shortage_blocks_the_run_rather_than_updating_some_regions(seeded):
    """표본이 모자란 지역이 하나라도 있으면 커밋하지 않는다. 그 지역만 건너뛰면
    다시 부분 갱신이다."""
    thin = {"12330": jeonse_items(3, manwon=JEONSE_MANWON)}
    seeded_value = seeded.regions.get("11440").jeonse_median_krw
    report = collect_market(
        seeded, fetch=fetching(per_region=thin),
        constants=CONSTANTS, now=RUN_AT,
    )

    assert report.committed is False
    assert any("표본" in reason and "12330" in reason for reason in report.failures)
    assert seeded.regions.get("11440").jeonse_median_krw == seeded_value   # 시드 그대로


def test_failure_is_recorded_in_the_audit_log(seeded):
    collect_market(seeded, fetch=fetching(fail_for={"11440"}),
                   constants=CONSTANTS, now=RUN_AT)
    events = seeded.audit.list(action="market.run_failed")
    assert len(events) == 1
    assert events[0].outcome == "failed"
    assert "11440" in str(events[0].after)


def test_a_second_failed_run_does_not_pile_up_new_states(seeded):
    """실패가 반복돼도 저장소는 한 번 `stale` 로 내려간 뒤 더 나빠지지 않는다."""
    collect_market(seeded, fetch=fetching(),
                   constants=CONSTANTS, now=RUN_AT)
    fail_at = RUN_AT + timedelta(days=1)
    collect_market(seeded, fetch=fetching(fail_for={"11440"}), constants=CONSTANTS,
                   now=fail_at)
    once = snapshot(seeded)
    collect_market(seeded, fetch=fetching(fail_for={"11440"}), constants=CONSTANTS,
                   now=fail_at)
    assert snapshot(seeded) == once


# --------------------------------------------------------------------------
# 7. 상수 fail-closed (SPEC 5.1.1 · 코디네이터 승인)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", CONSTANT_KEYS)
def test_batch_refuses_to_run_when_a_constant_is_missing(seeded, missing):
    """등재 전까지 배치가 **정직하게 거부**한다. 기본값을 두면 그 기본값이 곧
    등재되지 않은 모델 상수다."""
    partial = {k: v for k, v in CONSTANTS.items() if k != missing}
    with pytest.raises(KeyError) as exc:
        collect_market(seeded, fetch=fetching(),
                       constants=partial, now=RUN_AT)
    assert missing in str(exc.value)


def test_constant_keys_match_the_registered_names():
    """코디네이터가 `contracts/` 에 등재하기로 못박은 이름 그대로여야 한다.
    (레지스트리 키 문법이 `<engine>.<symbol>` 이라 점은 하나다.)"""
    assert set(CONSTANT_KEYS) == set(CONSTANTS)
    assert all(key.count(".") == 1 and key.startswith("ingest.market_") for key in CONSTANT_KEYS)


# --------------------------------------------------------------------------
# 8. 감사기록 · 보고서
# --------------------------------------------------------------------------


def test_successful_run_records_one_audit_event_per_region(seeded):
    seeded_value = seeded.regions.get("11440").jeonse_median_krw
    report = collect_market(seeded, fetch=fetching(),
                            constants=CONSTANTS, now=RUN_AT)
    events = seeded.audit.list(action="market.ingest")

    assert len(events) == len(report.regions) == 10
    assert {e.actor for e in events} == {"system:ingest"}
    sample = next(e for e in events if e.target == "11440")
    assert sample.before["jeonseMedianKRW"] == seeded_value
    assert sample.after["jeonseMedianKRW"] == 310_000_000
    # 무엇을 안 건드렸는지도 남는다 — 나중에 "왜 이 필드만 예시값인가"의 답이 여기 있다.
    assert set(sample.after["untouched"]) >= set(NO_COUNTERPART_FIELDS)


def test_report_counts_what_was_read_and_what_was_used(seeded):
    items = sample_items() + [raw_item(28_000, 0, area=134.5)]      # 범위 밖 1건
    report = collect_market(seeded, fetch=fetching(default=items),
                            constants=CONSTANTS, now=RUN_AT)
    outcome = next(o for o in report.regions if o.code == "11440")

    assert outcome.deals_read == 25
    assert outcome.deals_used == 24
    assert outcome.jeonse_sample == 12
    assert outcome.monthly_sample == 12
    assert outcome.trade_sample == 12


def test_window_is_fetched_for_every_region_and_both_services(seeded):
    fetch = fetching()
    collect_market(seeded, fetch=fetch, constants=CONSTANTS, now=RUN_AT)

    assert len(fetch.calls) == 10 * 3 * 2
    assert {ym for _, _, ym in fetch.calls} == {"202606", "202607", "202608"}
    assert {service for service, _, _ in fetch.calls} == {"rent", "trade"}


# --- 계약해제된 매매 (cdealType) ---------------------------------------------

def _trade_item(amount: str = "70,000", cdeal: str | None = None) -> dict[str, str]:
    item = {
        "dealAmount": amount, "excluUseAr": "59.5",
        "dealYear": "2026", "dealMonth": "6", "dealDay": "25",
        "aptNm": "테스트", "umdNm": "테스트동",
    }
    if cdeal is not None:
        item["cdealType"] = cdeal
    return item


def test_cancelled_trades_are_not_counted():
    """계약해제된 거래는 **성사되지 않은 거래**다. 가격 중앙값에 섞으면 실거래가가 아니다.

    이것은 이상치 판단이 아니라 **집계 대상의 정의**이므로 SPEC 3절의 [자동 폐기 금지]에
    걸리지 않는다 — 애초에 우리가 세려는 모집단이 아니다.
    실측: 마포구 3개월 206건 중 8건(3.9%)이 해제 건이었다 (2026-08-14).
    """
    from firsthome.ingest.market.pipeline import normalize_trades

    items = [_trade_item(cdeal="O"), _trade_item(cdeal=" "), _trade_item()]
    trades = normalize_trades(items, region_code="11440", max_area_sqm=85)
    assert len(trades) == 2, "해제 건이 걸러지지 않았거나 정상 건까지 걸렀다"


def test_missing_cancellation_field_does_not_drop_everything():
    """이름이 없으면 **거르지 않는다.**

    있는데 무시하는 것과 없어서 못 거르는 것은 다르다. 없다고 실패시키면 이 필드를
    주지 않는 응답에서 전건이 죽고, 그 상태는 조용한 0건과 구분되지 않는다.
    """
    from firsthome.ingest.market.pipeline import normalize_trades

    trades = normalize_trades([_trade_item()], region_code="11440", max_area_sqm=85)
    assert len(trades) == 1
