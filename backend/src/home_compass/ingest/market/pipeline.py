"""SPEC 3 흐름의 **정규화 -> 이상치 검사 -> upsert + Provenance.**

SPEC 3.1 의 표가 이 모듈의 작업 지시서다. 여덟 필드 중 **넷만** 실거래가로 도출된다.

    jeonseMedianKRW · monthlyDepositKRW · monthlyRentKRW   전월세 실거래가 집계
    conversionRatePct                                      파생 (한국부동산원 산식)
    jeonseRatioPct                                         파생 (매매 실거래가 필요 · 사용자 결정으로 추가)
    maintenanceFeeKRW · marketRisk · guaranteeAvailable    **대응물 없음 — 비워 둔다**

마지막 줄이 이 과업에서 가장 틀리기 쉬운 자리다. 통계에서 유도하지 않고, 그럴듯한 값을
넣지 않고, **건드리지 않는다.** 그 사실이 필드별 계보에 `unverified` 로 그대로 드러난다.

파생 비율 **2종은 「비의 중앙값」**이다 (SPEC 3.1 3차 정정 2026-08-15 · 계약 결정 #35).
셀(법정동 + 단지명 + 전용면적 구간) 안에서 각 통계의 중앙값을 먼저 구하고, 셀 단위 비를
만든 뒤, 그 비들의 중앙값을 취한다. 지역 전체를 한 통에 넣은 「중앙값의 비」는 세 통계가
**서로 다른 표본**에서 나와 모집단이 어긋나 있었다.

산식과 그 준거는 `docs/engineering/market/DERIVATION.md` 에 있다.

**시각 두 개를 섞지 않는다** (계약 결정 #12).
    `observed_at`  관측 기준시점 — 집계에 들어간 **가장 늦은 계약일** (KST 00:00)
    `fetched_at`   우리가 취득한 시각 — 배치를 돌린 순간
둘 다 RFC 3339 오프셋 표기이며 KST 는 `+09:00` 이다. `Z` 를 쓰지 않는다 (결정 #4).
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...store.interfaces import Store
from ...store.models import (
    REGION_FACT_FIELDS,
    AuditEvent,
    Provenance,
    Region,
    worst_verification,
)
from .source import SOURCE_NAMES, SOURCE_REFS, MarketSourceError

KST = timezone(timedelta(hours=9))

# --------------------------------------------------------------------------
# 모델 상수 — 전부 (d) 규범적 선택이며 `contracts/` 에 `our_choice` 로 등재돼 있다.
# 코드는 **조회만** 한다. 기본값을 두면 그 기본값이 곧 등재되지 않은 모델 상수다.
# --------------------------------------------------------------------------

#: 이상치 판정의 편차 배수 — **통계마다 다르다.**
#:
#: 하나로 두었더니 10개 지역 중 9개가 걸렸다 (2026-08-14 실측). 데이터가 이상해서가 아니라
#: **월세 보증금이 원래 100배 넘게 퍼져 있기 때문**이다 — 보증금 500만/월세 50만과
#: 보증금 2억/월세 30만이 둘 다 정상적인 월세 계약이다. 중앙값 ±3배 띠는 그 변수에
#: 애초에 맞지 않는 모델이었다. 늘 켜져 있는 표시는 정보가 아니라 배경이 된다.
#:
#: 배수별 **최악 지역**의 이상치 비율 (9개 지역 · 3개월 · 2026-08-14 실측):
#:
#:     통계          3x     5x     8x    10x
#:     전세         4.5%   0.7%   0.5%   0.3%
#:     월세보증금   54.5%  40.1%  13.9%   5.5%    <- 8x->10x 에서 무릎
#:     월세         34.1%  17.9%  12.5%   4.3%
#:     매매         12.4%   3.9%   1.3%   1.1%
#: 지역을 `unverified` 로 표시하는 **비율** 문턱.
#:
#: 처음에는 [이상치가 한 건이라도 있으면 그 지역을 unverified] 였다. 배수를 통계별로
#: 나눠 이상치가 4420 -> 473 건으로 줄어든 뒤에도 **9/10 지역이 여전히 걸렸다** — 큰 표본에서
#: 극단값 한둘은 늘 있기 때문이다. 늘 켜져 있는 표시는 검토 신호가 못 된다.
#:
#: 배수를 나눈 뒤 지역별 최대 비율은 **0.6% ~ 5.5%** 였다 (9개 지역 · 3개월 · 2026-08-14 실측).
#: 그 대역이 [정상]이므로 문턱을 그 위에 둔다. 아래에서 걸리는 것은 이상이 아니라 산포다.
OUTLIER_SHARE_KEY = "ingest.market_outlier_share_threshold"

OUTLIER_RATIO_KEYS = {
    "jeonseDepositKRW": "ingest.market_outlier_ratio_jeonse",
    "monthlyDepositKRW": "ingest.market_outlier_ratio_monthly_deposit",
    "monthlyRentKRW": "ingest.market_outlier_ratio_monthly_rent",
    "tradeAmountKRW": "ingest.market_outlier_ratio_trade",
}
MIN_SAMPLE_KEY = "ingest.market_min_sample_count"
LOOKBACK_KEY = "ingest.market_lookback_months"
MAX_AREA_KEY = "ingest.market_max_exclusive_area_sqm"
#: 셀을 만드는 전용면적 구간의 폭. 셀 = 법정동 + 단지명 + **전용면적 구간** 이다.
#:
#: 1.0 은 정수 제곱미터 반올림이며 **공표 준거가 없다 — 우리 선택이다.** 6차 실사가
#: 1제곱미터와 5제곱미터를 비교해 값의 최대 이동이 0.12%p(전환율) · 0.46%p(전세가율)
#: 임을 실측했다 (FINDINGS-6.md B5). 어느 값을 골라도 결과가 같으므로 재현 가능한
#: 쪽을 골랐고, **고른다는 사실 자체가 우리 선택**이다.
PAIR_AREA_BAND_KEY = "ingest.market_pair_area_band_sqm"
MAX_ATTEMPTS_KEY = "ingest.market_max_attempts"
TIMEOUT_KEY = "ingest.market_request_timeout_seconds"
DEADLINE_KEY = "ingest.market_batch_deadline_seconds"

CONSTANT_KEYS = (
    *OUTLIER_RATIO_KEYS.values(),
    OUTLIER_SHARE_KEY,
    MIN_SAMPLE_KEY,
    LOOKBACK_KEY,
    PAIR_AREA_BAND_KEY,
    MAX_AREA_KEY,
    MAX_ATTEMPTS_KEY,
    TIMEOUT_KEY,
    DEADLINE_KEY,
)

# --------------------------------------------------------------------------
# 필드 분류 (SPEC 3.1)
# --------------------------------------------------------------------------

#: 전월세 실거래가로 도출되는 필드.
RENT_DERIVED_FIELDS = (
    "jeonseMedianKRW",
    "monthlyDepositKRW",
    "monthlyRentKRW",
    "conversionRatePct",
)

#: 매매 실거래가가 있어야 도출되는 필드.
TRADE_DERIVED_FIELDS = ("jeonseRatioPct",)

#: **실거래가 원자료에 대응물이 없는 셋** (SPEC 3.1). 배치가 건드리지 않는다.
NO_COUNTERPART_FIELDS = ("maintenanceFeeKRW", "marketRisk", "guaranteeAvailable")

INGEST_ACTOR = "system:ingest"
ACTION_INGEST = "market.ingest"
ACTION_OUTLIER = "market.outlier"
ACTION_FAILED = "market.run_failed"
#: 실행 **한 번**을 닫는 기록 (SPEC 7.1 「배치 실행 결과」 · 7.2 배치 성공률).
ACTION_RUN = "market.run"

#: 전월세전환율의 산식 준거. 자료는 국토부, 산식은 한국부동산원이다 — 둘을 뭉치면
#: 「우리가 무엇을 인용했는가」가 사라진다.
#:
#: ★ **이 페이지는 「오피스텔 가격동향조사」의 산출항목이다** (6차 실사 A4, 원문확인:
#:   본문이 다섯 번 「오피스텔」이라고 말한다). 산식 문자열 자체는 우리 구현과 일치하지만
#:   우리는 **아파트** 실거래를 모으므로 **인용이 어긋나 있다.** 실사가 주택(아파트) 쪽의
#:   같은 성격 페이지를 **찾지 못했다** (A4-5, 접근실패). 없는 URL 을 지어내지 않으므로
#:   가리키는 것을 그대로 두고, 그것이 무엇인지와 대응 페이지 미확인을 여기와 계보에 적는다.
CONVERSION_FORMULA_REF = "https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?mi=9807&cntntsId=1189"

#: ★ 파생 비율 2종의 이름이 **무엇을 계산했는가**를 말한다. 2026-08-15 이전에는 둘 다
#:   「중앙값의 비」였고, 그 문구는 이제 거짓이다 (SPEC 3.1 3차 정정 · 결정 #35).
#:   셀 정의를 이름에 적는 이유: 「비의 중앙값」만으로는 **무엇을 짝지었는지**가 안 보인다.
FIELD_SOURCE_NAMES = {
    "jeonseMedianKRW": SOURCE_NAMES["rent"],
    "monthlyDepositKRW": SOURCE_NAMES["rent"],
    "monthlyRentKRW": SOURCE_NAMES["rent"],
    "conversionRatePct": (
        f"{SOURCE_NAMES['rent']} — 한국부동산원 전월세전환율 산식 적용 · "
        "비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출). "
        "인용한 산식 페이지는 오피스텔 가격동향조사의 산출항목이며 "
        "아파트 대응 페이지는 찾지 못했다"
    ),
    "jeonseRatioPct": (
        "국토교통부 아파트 전월세·매매 실거래가 — 전세/매매의 "
        "비의 중앙값 (셀 = 법정동+단지명+전용면적 구간, 우리 산출)"
    ),
}

#: 레코드 단위 요약의 이름. 화면의 `source` 가 이것을 그대로 보인다.
#: 필드마다 출처가 다르다는 사실이 한 줄 안에 드러나야 한다.
RECORD_SOURCE_NAME = "국토교통부 실거래가 (일부 필드는 출처 미특정 — 필드별 계보 참조)"


class MarketFieldMappingError(MarketSourceError):
    """응답 항목명이 우리가 아는 이름과 하나도 맞지 않는다.

    이것을 예외로 내는 것이 이 파이프라인의 핵심 방어다. 걸러 내면 **조용한 0건**이
    되고, 그 상태는 「그 달에 거래가 없었다」와 구분되지 않는다.
    """


# --------------------------------------------------------------------------
# 정규화 — 단위 함정이 여기 있다
# --------------------------------------------------------------------------

#: 응답 항목명 후보. 원문 명세가 hwp 라 2차출처까지만 확인됐고, 전용면적은
#: `exclUseAr`(전월세)·`excluUseAr`(매매) 두 표기가 돌아다닌다. 후보로 받되
#: **아무 이름이나** 받지는 않는다.
_RENT_NAMES = {
    "deposit": ("deposit",),
    "monthly_rent": ("monthlyRent",),
    "area": ("exclUseAr", "excluUseAr"),
    "year": ("dealYear",),
    "month": ("dealMonth",),
    "day": ("dealDay",),
    "apt": ("aptNm",),
    "umd": ("umdNm",),
}
_RENT_REQUIRED = ("deposit", "monthly_rent", "area", "year", "month")

_TRADE_NAMES = {
    "amount": ("dealAmount",),
    "area": ("excluUseAr", "exclUseAr"),
    "year": ("dealYear",),
    "month": ("dealMonth",),
    "day": ("dealDay",),
    "apt": ("aptNm",),
    "umd": ("umdNm",),
}
_TRADE_REQUIRED = ("amount", "area", "year", "month")

#: 계약해제 표시. 값이 `O` 면 **해제된 거래**다.
#: 필수가 아니다 — 이름이 없으면 거르지 않고 그대로 둔다. 있는데 무시하는 것과
#: 없어서 못 거르는 것은 다르며, 없다고 실패시키면 이 필드를 안 주는 응답에서 전건이 죽는다.
_TRADE_CANCELLED_NAMES = ("cdealType",)
_CANCELLED_MARK = "O"

#: 실거래가의 금액 단위. 응답은 **만원**이고 콤마가 섞인 문자열이다.
MANWON = 10_000


@dataclass(frozen=True)
class Deal:
    """전월세 거래 한 건. 금액은 **원 단위로 정규화된 뒤**의 값이다."""

    region_code: str
    deposit_krw: int
    monthly_rent_krw: int
    exclusive_area_sqm: float
    deal_date: date
    apt_name: str
    umd_name: str

    @property
    def is_jeonse(self) -> bool:
        """월세가 0 이면 전세다. 이 한 줄이 두 통계를 가른다."""
        return self.monthly_rent_krw == 0


@dataclass(frozen=True)
class Trade:
    """매매 거래 한 건."""

    region_code: str
    amount_krw: int
    exclusive_area_sqm: float
    deal_date: date
    apt_name: str
    umd_name: str


def _pick(item: Mapping[str, str], candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in item:
            return item[name]
    return None


def _require_names(item: Mapping[str, str], names: Mapping[str, tuple[str, ...]],
                   required: tuple[str, ...], kind: str) -> None:
    missing = [names[key][0] for key in required if _pick(item, names[key]) is None]
    if missing:
        raise MarketFieldMappingError(
            f"{kind} 응답 항목명이 기대와 다르다. 기대한 이름(없는 것): {missing} / "
            f"실제로 관측된 키: {sorted(item)}. "
            "이름 매핑을 고치기 전에는 조용히 0건으로 넘어가지 않는다"
        )


def _int_manwon(raw: str | None) -> int | None:
    """`33,000` -> 330,000,000. 빈 칸은 `None` 이다 — 0 으로 읽으면 중앙값이 내려가고
    그 방향은 **관대한 쪽**이다 (HANDOFF 불변조건 7)."""
    text = (raw or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(text) * MANWON
    except ValueError:
        return None


def _float(raw: str | None) -> float | None:
    text = (raw or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _deal_date(item: Mapping[str, str], names: Mapping[str, tuple[str, ...]]) -> date | None:
    year = _float(_pick(item, names["year"]))
    month = _float(_pick(item, names["month"]))
    day = _float(_pick(item, names["day"])) or 1
    if year is None or month is None:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def normalize_deals(
    items: Iterable[Mapping[str, str]], *, region_code: str, max_area_sqm: float
) -> list[Deal]:
    """전월세 응답 항목 -> `Deal`. 범위 밖·읽을 수 없는 행은 **세지 않는다.**

    범위 밖(전용면적 상한 초과)은 이상치 폐기와 다르다. 상한은 **집계 대상의 정의**이고
    (우리 선택이다) 그 사실은 보고서의 `deals_read` 와 `deals_used` 차이로 드러난다.
    """
    deals: list[Deal] = []
    for item in items:
        _require_names(item, _RENT_NAMES, _RENT_REQUIRED, "전월세")
        deposit = _int_manwon(_pick(item, _RENT_NAMES["deposit"]))
        rent = _int_manwon(_pick(item, _RENT_NAMES["monthly_rent"]))
        area = _float(_pick(item, _RENT_NAMES["area"]))
        when = _deal_date(item, _RENT_NAMES)
        if deposit is None or area is None or when is None:
            continue
        if area > max_area_sqm:
            continue
        deals.append(
            Deal(
                region_code=region_code,
                deposit_krw=deposit,
                # 월세 칸이 비어 있으면 전세로 읽는다 — 응답이 실제로 그렇게 온다.
                monthly_rent_krw=rent or 0,
                exclusive_area_sqm=area,
                deal_date=when,
                apt_name=_pick(item, _RENT_NAMES["apt"]) or "",
                umd_name=_pick(item, _RENT_NAMES["umd"]) or "",
            )
        )
    return deals


def normalize_trades(
    items: Iterable[Mapping[str, str]], *, region_code: str, max_area_sqm: float
) -> list[Trade]:
    """매매 응답 항목 -> `Trade`. **전월세와 같은 조건**으로 거른다.

    한쪽만 조건이 다르면 전세가율이 시장이 아니라 조건 차이를 재게 된다.
    """
    trades: list[Trade] = []
    for item in items:
        _require_names(item, _TRADE_NAMES, _TRADE_REQUIRED, "매매")
        # ★ 계약해제된 거래는 **성사되지 않은 거래**다. 가격 중앙값에 섞으면 [실거래가]가
        #   아니게 된다. 이것은 이상치 판단이 아니라 **집계 대상의 정의**이므로 폐기 금지
        #   규칙(SPEC 3절)에 걸리지 않는다 — 애초에 우리가 세려는 모집단이 아니다.
        #   마포구 3개월 표본 206건 중 8건(3.9%)이 해제 건이었다 (2026-08-14 실측).
        if (_pick(item, _TRADE_CANCELLED_NAMES) or "").strip() == _CANCELLED_MARK:
            continue
        amount = _int_manwon(_pick(item, _TRADE_NAMES["amount"]))
        area = _float(_pick(item, _TRADE_NAMES["area"]))
        when = _deal_date(item, _TRADE_NAMES)
        if amount is None or area is None or when is None:
            continue
        if area > max_area_sqm:
            continue
        trades.append(
            Trade(
                region_code=region_code,
                amount_krw=amount,
                exclusive_area_sqm=area,
                deal_date=when,
                apt_name=_pick(item, _TRADE_NAMES["apt"]) or "",
                umd_name=_pick(item, _TRADE_NAMES["umd"]) or "",
            )
        )
    return trades


# --------------------------------------------------------------------------
# 집계 · 파생 계산 (산식은 DERIVATION.md)
# --------------------------------------------------------------------------


def median_krw(values: Sequence[int]) -> int | None:
    """짝수 표본에서는 가운데 두 값의 평균이며 원 단위로 반올림한다."""
    if not values:
        return None
    return round(statistics.median(values))


def conversion_rate_pct(
    jeonse_krw: int | None, monthly_deposit_krw: int | None, monthly_rent_krw: int | None
) -> float | None:
    """전월세전환율(%) = 월세 x 12 / (전세가격 - 월세보증금) x 100.

    한국부동산원 통계산출항목의 산식을 **원문 그대로** 옮긴 것이다 —
    https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?mi=9807&cntntsId=1189
    (「전월세전환율은 조사월까지 신고된 실거래 기반 산출」)

    분모가 0 이하이면 비운다. 그 자리에 아무 숫자나 넣지 않는다.
    """
    if jeonse_krw is None or monthly_deposit_krw is None or monthly_rent_krw is None:
        return None
    denominator = jeonse_krw - monthly_deposit_krw
    if denominator <= 0:
        return None
    return round(monthly_rent_krw * 12 / denominator * 100, 2)


def jeonse_ratio_pct(jeonse_krw: int | None, trade_krw: int | None) -> float | None:
    """전세가율(%) = 전세 / 매매 x 100. **한 셀의 비 하나**를 만든다.

    ★ 2026-08-15 이전에는 이 함수에 지역 전체의 중앙값 둘을 넣어 「중앙값의 비」를 냈고,
    그 근거는 「실거래가는 전월세와 매매의 거래 물건이 달라 짝지을 수 없다」였다.
    **그 근거가 뒤집혔다.** 6차 실사가 한국부동산원 전국주택가격동향조사의 원문을 확인한
    결과, 그 조사는 단지(PSU) -> 개별 호(SSU)로 뽑은 **같은 표본주택에 대해 매매·전세·
    월세를 모두 산정**한다 — 짝짓는 절차가 따로 있는 것이 아니라 **표본 설계 자체가 짝을
    만든다.** 우리는 같은 호를 볼 수 없지만 **같은 법정동·같은 단지·같은 평형**까지는 갈 수
    있고, 그 셀이 우리가 갈 수 있는 가장 가까운 자리다 (SPEC 3.1 3차 정정 · 결정 #35).

    그러므로 지역 값은 이 함수를 셀마다 부른 뒤 **비의 중앙값**을 취해 만든다
    (`paired_jeonse_ratio_pct`). 한국부동산원이 실제로 어느 쪽을 쓰는지는 **원문에서
    확정하지 못했으므로**(FINDINGS-6.md E-1) **그쪽 공표값인 척하지 않는다.**
    """
    if not jeonse_krw or not trade_krw:
        return None
    return round(jeonse_krw / trade_krw * 100, 2)


# --------------------------------------------------------------------------
# 짝짓기 — 셀 = 법정동 + 단지명 + 전용면적 구간 (SPEC 3.1 3차 정정)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedRatio:
    """셀 단위 비의 중앙값과, 그 중앙값을 만든 셀 수."""

    value_pct: float | None
    #: 비가 성립한 셀 수. **최소 건수 문턱이 여기에 걸린다** — 새 상수를 만들지 않고
    #: `ingest.market_min_sample_count` 를 그대로 건다 (SPEC 3.1 3차 정정).
    cells: int
    #: 짝은 성립했는데 비를 만들 수 없던 셀 (전환율의 분모 <= 0). **버리지 않고 센다** —
    #: 몇 개가 빠졌는지 모르면 중앙값이 무엇의 중앙값인지 말할 수 없다.
    dropped_cells: int = 0


def area_band(area_sqm: float, band_sqm: float) -> float:
    """전용면적을 `band_sqm` 폭으로 **반올림**한 구간 라벨.

    한 단지 안의 같은 평형은 59.82/59.92/59.99 처럼 소수점만 다르고, 다른 평형은
    59 와 84 처럼 멀다. 그래서 정수 제곱미터 반올림(폭 1.0)이면 앞쪽은 한 셀로 모이고
    뒤쪽은 갈린다. 폭은 등재된 상수이며 여기에 기본값을 두지 않는다.
    """
    # 부동소수 잔차가 셀 키를 가르지 않게 자른다 (59.99/1.0 이 60.00000000000001 이 되는 부류).
    return round(round(area_sqm / band_sqm) * band_sqm, 6)


def _cell_key(umd_name: str, apt_name: str, area_sqm: float,
              band_sqm: float) -> tuple[str, str, float]:
    """`aptNm` 만으로는 부족하다 — 같은 시군구에 **같은 이름의 단지가 여럿** 있다.
    응답이 주는 `umdNm`(법정동)을 앞에 붙인다 (6차 실사 B0)."""
    return (umd_name.strip(), apt_name.strip(), area_band(area_sqm, band_sqm))


def _cells(rows: Iterable[Deal | Trade], band_sqm: float) -> dict[tuple[str, str, float], list]:
    grouped: dict[tuple[str, str, float], list] = {}
    for row in rows:
        key = _cell_key(row.umd_name, row.apt_name, row.exclusive_area_sqm, band_sqm)
        grouped.setdefault(key, []).append(row)
    return grouped


def _median_of_cell_ratios(ratios: Sequence[float], dropped: int) -> PairedRatio:
    if not ratios:
        return PairedRatio(None, 0, dropped)
    return PairedRatio(round(statistics.median(ratios), 2), len(ratios), dropped)


def paired_jeonse_ratio_pct(
    jeonse: Sequence[Deal], trades: Sequence[Trade], *, band_sqm: float
) -> PairedRatio:
    """전세가율 = **셀 단위 비의 중앙값** (SPEC 3.1 3차 정정).

    ★ 셀 안에서 각 통계의 중앙값을 먼저 구하고 **셀 하나당 비 하나**를 만든다.
      거래를 데카르트 곱으로 짝지으면 거래가 많은 셀이 중앙값을 지배하기 때문이다.
      (전세 12건 x 매매 12건인 셀 하나가 144쌍을 내는 동안 1건짜리 셀 열 개는 열 쌍을
      낸다 — 그러면 지역 값이 그 한 단지의 값이 된다.)

    집계 조건은 여기서 **하나도 새로 걸지 않는다.** 면적 상한·수집 창·주택유형·계약해제는
    `normalize_deals`/`normalize_trades` 가 이미 걸었고, 이 함수는 그 결과를 묶기만 한다.
    조건이 전세와 매매 사이에서 어긋나면 이 비가 시장이 아니라 **조건 차이**를 재게 된다.
    """
    jeonse_cells = _cells(jeonse, band_sqm)
    trade_cells = _cells(trades, band_sqm)
    ratios: list[float] = []
    dropped = 0
    for key in jeonse_cells.keys() & trade_cells.keys():
        value = jeonse_ratio_pct(
            median_krw([d.deposit_krw for d in jeonse_cells[key]]),
            median_krw([t.amount_krw for t in trade_cells[key]]),
        )
        if value is None:
            dropped += 1
            continue
        ratios.append(value)
    return _median_of_cell_ratios(ratios, dropped)


def paired_conversion_rate_pct(
    jeonse: Sequence[Deal], monthly: Sequence[Deal], *, band_sqm: float
) -> PairedRatio:
    """전월세전환율 = **셀 단위 비의 중앙값**. 짝짓기 규약은 위와 같다.

    분모(전세 - 월세보증금)가 0 이하인 셀은 비를 만들 수 없다. 그 셀은 **버리지 않고**
    `dropped_cells` 로 센다 — 중앙값에서 몇 개가 빠졌는지가 값의 성격이다.
    """
    jeonse_cells = _cells(jeonse, band_sqm)
    monthly_cells = _cells(monthly, band_sqm)
    ratios: list[float] = []
    dropped = 0
    for key in jeonse_cells.keys() & monthly_cells.keys():
        value = conversion_rate_pct(
            median_krw([d.deposit_krw for d in jeonse_cells[key]]),
            median_krw([d.deposit_krw for d in monthly_cells[key]]),
            median_krw([d.monthly_rent_krw for d in monthly_cells[key]]),
        )
        if value is None:
            dropped += 1
            continue
        ratios.append(value)
    return _median_of_cell_ratios(ratios, dropped)


def detect_outliers(values: Sequence[float], *, ratio: float) -> list[float]:
    """중앙값 대비 편차가 임계를 넘는 값들. **폐기하지 않는다 — 표시할 뿐이다.**

    임계 초과 시 자동 폐기 금지(SPEC 3)는 「집계에서 제외」로도 우회되면 안 된다.
    빼는 것도 폐기다. 그래서 이 함수는 값을 돌려줄 뿐 아무것도 지우지 않는다.
    """
    if not values:
        return []
    median = statistics.median(values)
    if median <= 0:
        return []
    return [v for v in values if v > median * ratio or v < median / ratio]


def window_months(now: datetime, lookback_months: int) -> tuple[str, ...]:
    """`DEAL_YMD` 로 쓸 `YYYYMM` 목록. **실행 월을 포함해** 최근 N 개월이다.

    실행 월은 신고 지연 때문에 거의 비어 있다. 그래도 빼지 않는다 — 빼는 것 역시
    등재되지 않은 규범적 선택이고, 비어 있다는 사실은 표본 수로 드러나는 편이 낫다.
    """
    months: list[str] = []
    year, month = now.year, now.month
    for _ in range(lookback_months):
        months.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return tuple(reversed(months))


# --------------------------------------------------------------------------
# 보고서
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Outlier:
    region_code: str
    statistic: str
    value_krw: float
    median_krw: float
    apt_name: str
    deal_ym: str
    #: 이 통계에서 이상치가 차지한 비율. 기록에 남겨야 [왜 걸렸나/왜 안 걸렸나]를 말할 수 있다.
    share: float = 0.0
    #: 비율 문턱을 넘었는가. **넘지 않아도 기록은 남는다** (SPEC 3 자동 폐기 금지).
    exceeds_threshold: bool = False


@dataclass(frozen=True)
class RegionOutcome:
    code: str
    name: str
    deals_read: int
    deals_used: int
    jeonse_sample: int
    monthly_sample: int
    trades_read: int
    trade_sample: int
    values: dict[str, Any] | None
    error: str | None
    #: 짝이 성립한 셀 수 — **파생 비율 2종의 모집단**이며 최소 건수 문턱이 여기에 걸린다.
    #: 표본이 몇 건인지와 짝이 몇 셀인지는 다른 사실이라 따로 센다 (FINDINGS-6.md B2).
    ratio_cells: int = 0
    conversion_cells: int = 0
    #: 짝은 성립했는데 분모가 0 이하라 비를 만들 수 없던 셀. 버리지 않고 센다.
    conversion_cells_dropped: int = 0


@dataclass(frozen=True)
class MarketRunReport:
    committed: bool
    window: tuple[str, ...]
    regions: tuple[RegionOutcome, ...]
    failures: tuple[str, ...]
    outliers: tuple[Outlier, ...]
    stale_marked: tuple[str, ...]

    @property
    def outlier_regions(self) -> tuple[str, ...]:
        return tuple(sorted({o.region_code for o in self.outliers}))


# --------------------------------------------------------------------------
# 배치
# --------------------------------------------------------------------------


def _rfc3339_kst(when: date) -> str:
    """계약일 -> `2026-06-15T00:00:00+09:00`. `Z` 를 쓰지 않는다 (계약 결정 #4)."""
    return datetime(when.year, when.month, when.day, tzinfo=KST).isoformat()


def _statistic_outliers(deals: Sequence[Deal], trades: Sequence[Trade], *, region_code: str,
                        ratios: Mapping[str, float], share_threshold: float) -> list[Outlier]:
    found: list[Outlier] = []
    jeonse = [d for d in deals if d.is_jeonse]
    monthly = [d for d in deals if not d.is_jeonse]
    samples: list[tuple[str, list[tuple[float, str, date]]]] = [
        ("jeonseDepositKRW", [(d.deposit_krw, d.apt_name, d.deal_date) for d in jeonse]),
        ("monthlyDepositKRW", [(d.deposit_krw, d.apt_name, d.deal_date) for d in monthly]),
        ("monthlyRentKRW", [(d.monthly_rent_krw, d.apt_name, d.deal_date) for d in monthly]),
        ("tradeAmountKRW", [(t.amount_krw, t.apt_name, t.deal_date) for t in trades]),
    ]
    for name, rows in samples:
        values = [value for value, _, _ in rows]
        flagged = set(detect_outliers(values, ratio=ratios[name]))
        if not flagged:
            continue
        # ★ 값은 **언제나** 감사기록에 남는다 (SPEC 3 [자동 폐기 금지]). 비율 문턱은
        #   [이 지역을 unverified 로 볼 것인가]에만 걸린다 — 기록과 판정을 분리한다.
        #
        # ★ **거래 건수로 센다.** `flagged` 는 값의 집합이라 같은 금액이 여러 건이면 하나로
        #   접힌다 — 실거래가에는 같은 금액이 흔하다(같은 단지·같은 평형). 집합 크기로 세면
        #   비율이 실제보다 **작게** 나오고, 그 방향은 [이상을 덜 표시하는] 쪽이다.
        share = sum(1 for value in values if value in flagged) / len(values)
        exceeds = share > share_threshold
        median = statistics.median(values)
        for value, apt, when in rows:
            if value in flagged:
                found.append(
                    Outlier(
                        region_code=region_code,
                        statistic=name,
                        value_krw=value,
                        median_krw=median,
                        apt_name=apt,
                        deal_ym=f"{when.year:04d}-{when.month:02d}",
                        share=share,
                        exceeds_threshold=exceeds,
                    )
                )
    return found


def _provenance(field_name: str, *, observed_at: str, fetched_at: str,
                verification: str) -> Provenance:
    service = "trade" if field_name in TRADE_DERIVED_FIELDS else "rent"
    return Provenance(
        source_kind="market",
        source_name=FIELD_SOURCE_NAMES[field_name],
        source_ref=SOURCE_REFS[service],
        observed_at=observed_at,
        fetched_at=fetched_at,
        verification=verification,
    )


def _summary(region: Region, field_provenance: Mapping[str, Provenance],
             *, fetched_at: str, observed_at: str | None) -> Provenance:
    """레코드 단위 요약. **최악값이 이긴다** (SPEC 2.4)."""
    worst = worst_verification(p.verification for p in field_provenance.values())
    return Provenance(
        source_kind="market",
        source_name=RECORD_SOURCE_NAME,
        source_ref=SOURCE_REFS["rent"],
        observed_at=observed_at,
        fetched_at=fetched_at,
        verification=worst or region.provenance.verification,
    )


def _existing_field_provenance(region: Region) -> dict[str, Provenance]:
    """건드리지 않는 필드는 **있던 계보를 그대로** 들고 간다.

    여기서 국토부 이름을 붙이면 그 순간 예시값이 실데이터인 척하게 된다 (SPEC 3.1).
    """
    return {name: region.provenance_for(name) for name in REGION_FACT_FIELDS}


def _collect_raw(
    fetch: Callable[[str, str, str], Sequence[Mapping[str, str]]],
    service: str,
    region_code: str,
    window: Sequence[str],
) -> tuple[list[Mapping[str, str]], str | None]:
    """한 서비스의 수집 창 전체. 실패는 **어느 서비스였는지와 함께** 돌려준다.

    수집 실패는 배치의 정상 경로다 (SPEC 9.2.1) — 예외로 배치를 죽이지 않고,
    「이전 값 유지 + stale」로 가는 입력이 된다.
    """
    items: list[Mapping[str, str]] = []
    for ym in window:
        try:
            items.extend(fetch(service, region_code, ym))
        except Exception as exc:
            return items, f"{type(exc).__name__}: {exc}"
    return items, None


def _require_constants(constants: Mapping[str, Any]) -> dict[str, Any]:
    """fail-closed 조회. 등재 전에는 `KeyError` 로 배치가 **정직하게 거부**한다."""
    return {key: constants[key] for key in CONSTANT_KEYS}


def collect_market(
    store: Store,
    *,
    fetch: Callable[[str, str, str], Sequence[Mapping[str, str]]],
    constants: Mapping[str, Any],
    now: datetime,
    region_codes: Sequence[str] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> MarketRunReport:
    """시세 수집 배치 한 번.

    **전건 성공일 때만 커밋한다.** 지역 하나가 실패했다고 나머지 아홉만 새 값이 되면,
    그 저장소가 무엇을 뜻하는지 아무도 말할 수 없다. 실패하면 값은 하나도 바꾸지 않고
    이전에 수집에 성공했던 필드만 `stale` 로 내린다 (SPEC 3 · 10.2 3단계).

    `fetch` 를 주입받는 이유: 수집기가 자기 안에서 HTTP 를 부르면 완료 기준 넷 중
    어느 것도 키 없이 증명할 수 없다.
    """
    settings = _require_constants(constants)
    ratios = {name: float(settings[key]) for name, key in OUTLIER_RATIO_KEYS.items()}
    share_threshold = float(settings[OUTLIER_SHARE_KEY])
    min_sample = int(settings[MIN_SAMPLE_KEY])
    max_area = float(settings[MAX_AREA_KEY])
    band_sqm = float(settings[PAIR_AREA_BAND_KEY])
    window = window_months(now, int(settings[LOOKBACK_KEY]))
    deadline_seconds = float(settings[DEADLINE_KEY])

    started = monotonic()
    fetched_at = now.astimezone(KST).isoformat()

    regions = [
        region for region in store.regions.list()
        if region_codes is None or region.code in set(region_codes)
    ]

    outcomes: list[RegionOutcome] = []
    failures: list[str] = []
    outliers: list[Outlier] = []
    planned: list[tuple[Region, dict[str, Any], dict[str, Provenance]]] = []

    for region in regions:
        # 실행 시간 상한. **판정 시각이 아니라 경과 시간**이라 단조 시계를 쓴다 —
        # 여기서 벽시계를 읽으면 주입받은 `now` 와 두 개의 답이 생긴다.
        if monotonic() - started > deadline_seconds:
            failures.append(f"{region.code}: 배치 실행 시간 상한({deadline_seconds:.0f}s) 초과")
            outcomes.append(RegionOutcome(region.code, region.name, 0, 0, 0, 0, 0, 0, None,
                                          "deadline"))
            continue

        raw_rent, rent_error = _collect_raw(fetch, "rent", region.code, window)
        raw_trade, trade_error = (([], None) if rent_error
                                  else _collect_raw(fetch, "trade", region.code, window))
        # 어느 서비스가 실패했는지를 **추측하지 않는다.** 사유 문구가 틀리면 다음 사람이
        # 엉뚱한 엔드포인트를 들여다본다 (실기동에서 실제로 이 실수를 잡았다).
        if rent_error or trade_error:
            kind, error = ("전월세", rent_error) if rent_error else ("매매", trade_error)
            failures.append(f"{region.code}: {kind} 수집 실패 — {error}")
            outcomes.append(RegionOutcome(region.code, region.name, len(raw_rent), 0, 0, 0,
                                          len(raw_trade), 0, None, error))
            continue

        deals = normalize_deals(raw_rent, region_code=region.code, max_area_sqm=max_area)
        trades = normalize_trades(raw_trade, region_code=region.code, max_area_sqm=max_area)
        jeonse = [d for d in deals if d.is_jeonse]
        monthly = [d for d in deals if not d.is_jeonse]

        region_outliers = _statistic_outliers(deals, trades, region_code=region.code,
                                              ratios=ratios, share_threshold=share_threshold)
        outliers.extend(region_outliers)

        if len(jeonse) < min_sample or len(monthly) < min_sample:
            failures.append(
                f"{region.code}: 표본 부족 — 전세 {len(jeonse)}건 · 월세 {len(monthly)}건 "
                f"(최소 {min_sample}건)"
            )
            outcomes.append(RegionOutcome(region.code, region.name, len(raw_rent), len(deals),
                                          len(jeonse), len(monthly), len(raw_trade),
                                          len(trades), None, "sample_shortage"))
            continue

        jeonse_median = median_krw([d.deposit_krw for d in jeonse])
        deposit_median = median_krw([d.deposit_krw for d in monthly])
        rent_median = median_krw([d.monthly_rent_krw for d in monthly])

        # 파생 비율 2종은 **셀 단위 비의 중앙값**이다 (SPEC 3.1 3차 정정 · 결정 #35).
        # 지역 전체의 중앙값 셋은 여기에 쓰이지 않는다 — 서로 다른 표본의 중앙값이었다.
        conversion = paired_conversion_rate_pct(jeonse, monthly, band_sqm=band_sqm)
        ratio = paired_jeonse_ratio_pct(jeonse, trades, band_sqm=band_sqm)

        values: dict[str, Any] = {
            "jeonseMedianKRW": jeonse_median,
            "monthlyDepositKRW": deposit_median,
            "monthlyRentKRW": rent_median,
        }
        # 짝이 성립한 셀이 최소 건수에 못 미치면 **갱신하지 않는다** — 이전 값 유지 +
        # 출처 미특정. 모자란 표본으로 계산해 내놓지 않는다. 문턱은 **새로 만들지 않고**
        # 표본 최소 건수를 셀 수에 그대로 건다 (준거 없는 문턱이 하나 늘면 감도분석에서
        # 다른 (d) 와 같은 무게를 갖는다). 다만 이것은 외부 실패가 아니므로 실행 자체를
        # 막지는 않는다 — 막으면 비율 하나가 나머지 셋을 인질로 잡는다.
        if conversion.cells >= min_sample:
            values["conversionRatePct"] = conversion.value_pct
        if ratio.cells >= min_sample:
            values["jeonseRatioPct"] = ratio.value_pct

        if any(v is None for v in values.values()):
            missing = sorted(k for k, v in values.items() if v is None)
            failures.append(f"{region.code}: 도출 실패 — {missing}")
            outcomes.append(RegionOutcome(region.code, region.name, len(raw_rent), len(deals),
                                          len(jeonse), len(monthly), len(raw_trade),
                                          len(trades), None, "derivation_failed"))
            continue

        # 기록은 전건, 판정은 **문턱을 넘은 통계가 있을 때만** (SPEC 3).
        exceeded = any(o.exceeds_threshold for o in region_outliers)
        verification = "unverified" if exceeded else "verified"
        observed_rent = _rfc3339_kst(max(d.deal_date for d in deals))
        observed_trade = _rfc3339_kst(max(t.deal_date for t in trades)) if trades else None

        field_provenance = _existing_field_provenance(region)
        for name in values:
            observed = observed_trade if name in TRADE_DERIVED_FIELDS else observed_rent
            field_provenance[name] = _provenance(
                name, observed_at=observed, fetched_at=fetched_at, verification=verification
            )

        planned.append((region, values, field_provenance))
        outcomes.append(RegionOutcome(region.code, region.name, len(raw_rent), len(deals),
                                      len(jeonse), len(monthly), len(raw_trade), len(trades),
                                      values, None, ratio.cells, conversion.cells,
                                      conversion.dropped_cells))

    if failures:
        stale = _mark_stale(store, now=now, failures=failures)
        _record_run(store, now=now, window=window, outcomes=outcomes, failures=failures,
                    outliers=outliers, stale_marked=stale, committed=False)
        return MarketRunReport(False, window, tuple(outcomes), tuple(failures),
                               tuple(outliers), tuple(stale))

    _commit(store, planned, now=now, fetched_at=fetched_at, outliers=outliers)
    _record_run(store, now=now, window=window, outcomes=outcomes, failures=(),
                outliers=outliers, stale_marked=(), committed=True)
    return MarketRunReport(True, window, tuple(outcomes), (), tuple(outliers), ())


_VALUE_TO_ATTR = {
    "jeonseMedianKRW": "jeonse_median_krw",
    "monthlyDepositKRW": "monthly_deposit_krw",
    "monthlyRentKRW": "monthly_rent_krw",
    "conversionRatePct": "conversion_rate_pct",
    "jeonseRatioPct": "jeonse_ratio_pct",
}


def _record_run(
    store: Store,
    *,
    now: datetime,
    window: tuple[str, ...],
    outcomes: Sequence[RegionOutcome],
    failures: Sequence[str],
    outliers: Sequence[Outlier],
    stale_marked: Sequence[str],
    committed: bool,
) -> None:
    """실행 **한 번**을 닫는다. SPEC 7.1 의 필수 기록 「배치 실행 결과」가 이 행이다.

    ★ **지역별 행만으로는 실행의 경계를 되찾을 수 없다.** 멱등 재실행은 같은 `now` 를
      쓰므로 `(action, at)` 으로 묶으면 서로 다른 두 실행이 한 그룹이 된다 — 7단계
      실기동에서 성공 2회가 1개 그룹으로 뭉치는 것을 실제로 관측했다. 그러면 7.2 의
      배치 성공률은 **분모를 셀 수 없다.** 그래서 실행에 시각이 아니라 **자기 식별자**를
      붙이고, 이 행 하나가 곧 실행 한 번이다.

    ★ 판정하지 않는다. 여기서 하는 일은 이미 결정된 결과(`committed`)와 이미 센 수를
      옮겨 적는 것뿐이며, 집계·산식·이상치·짝짓기는 위에서 끝나 있다.
    """
    seq = len(store.audit.list()) + 1
    run_id = f"market-run-{seq:06d}"
    store.audit.append(
        AuditEvent(
            id=f"audit-{seq:06d}-{ACTION_RUN}",
            actor=INGEST_ACTOR,
            at=now,
            action=ACTION_RUN,
            target=run_id,
            # 어휘는 기존 기록과 같다 — `success` 는 시드·인증이, `failed` 는
            # `market.run_failed` 가 이미 쓴다. 새 어휘를 만들지 않는다.
            outcome="success" if committed else "failed",
            before=None,
            after={
                "runId": run_id,
                "committed": committed,
                "window": list(window),
                "regions": len(outcomes),
                "regionsUpdated": sum(1 for o in outcomes if o.values is not None) if committed else 0,
                "failures": list(failures),
                "outliers": len(outliers),
                "staleMarked": list(stale_marked),
            },
        )
    )


def _commit(store: Store, planned: Sequence[tuple[Region, dict[str, Any], dict[str, Provenance]]],
            *, now: datetime, fetched_at: str, outliers: Sequence[Outlier]) -> None:
    seq = len(store.audit.list())
    for index, (region, values, field_provenance) in enumerate(planned):
        before = region.to_engine_dict()
        observed = max(
            (p.observed_at for p in field_provenance.values() if p.observed_at), default=None
        )
        updated = replace(
            region,
            **{_VALUE_TO_ATTR[k]: v for k, v in values.items()},
            field_provenance=field_provenance,
            provenance=_summary(region, field_provenance, fetched_at=fetched_at,
                                observed_at=observed),
        )
        store.regions.upsert(updated)

        untouched = [name for name in REGION_FACT_FIELDS if name not in values]
        after = updated.to_engine_dict()
        after["untouched"] = untouched
        after["verification"] = {n: p.verification for n, p in field_provenance.items()}
        store.audit.append(
            AuditEvent(
                id=f"audit-{seq + index + 1:06d}-{ACTION_INGEST}-{region.code}",
                actor=INGEST_ACTOR,
                at=now,
                action=ACTION_INGEST,
                target=region.code,
                outcome="updated",
                before=before,
                after=after,
            )
        )

    seq = len(store.audit.list())
    for index, outlier in enumerate(outliers):
        store.audit.append(
            AuditEvent(
                id=f"audit-{seq + index + 1:06d}-{ACTION_OUTLIER}-{outlier.region_code}-{index}",
                actor=INGEST_ACTOR,
                at=now,
                action=ACTION_OUTLIER,
                target=outlier.region_code,
                # ★ 폐기가 아니라 표시다. 값은 집계에 그대로 들어가 있다.
                outcome="flagged",
                before=None,
                after={
                    "statistic": outlier.statistic,
                    "valueKRW": outlier.value_krw,
                    "medianKRW": outlier.median_krw,
                    "aptNm": outlier.apt_name,
                    "dealYm": outlier.deal_ym,
                    "discarded": False,
                },
            )
        )


def _mark_stale(store: Store, *, now: datetime, failures: Sequence[str]) -> list[str]:
    """값은 그대로 두고 **수집에 성공했던 필드만** `stale` 로 내린다.

    출처가 없던 필드(`unverified`)를 `stale` 로 바꾸면 등급이 **좋아진다**(C -> B).
    실패를 이용해 데이터를 좋아 보이게 만드는 셈이므로 그렇게 하지 않는다.
    """
    marked: list[str] = []
    for region in store.regions.list():
        # 필드별 계보가 없던 레코드는 레코드 요약에서 채워진다 (`_existing_field_provenance`).
        # 뜻이 같은 상태를 명시적으로 적는 것뿐이라 값도 등급도 움직이지 않는다.
        downgraded = {
            name: replace(p, verification="stale") if p.verification == "verified" else p
            for name, p in _existing_field_provenance(region).items()
        }
        worst = worst_verification(p.verification for p in downgraded.values())
        summary = replace(region.provenance, verification=worst or region.provenance.verification)
        # 바뀐 것이 없으면 쓰지 않는다. 실패가 반복돼도 저장소는 한 번 내려간 뒤
        # 더 나빠지지 않는다 (반복 실패의 멱등).
        if downgraded == dict(region.field_provenance) and summary == region.provenance:
            continue
        store.regions.upsert(
            replace(region, field_provenance=downgraded, provenance=summary)
        )
        marked.append(region.code)

    seq = len(store.audit.list())
    store.audit.append(
        AuditEvent(
            id=f"audit-{seq + 1:06d}-{ACTION_FAILED}",
            actor=INGEST_ACTOR,
            at=now,
            action=ACTION_FAILED,
            target="market",
            outcome="failed",
            before=None,
            after={"failures": list(failures), "staleMarked": marked},
        )
    )
    return marked
