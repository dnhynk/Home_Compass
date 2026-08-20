"""시세 수집 테스트용 응답 픽스처.

**응답 항목명은 2차출처까지만 확인됐다** (원문 명세가 hwp 기술문서다). 그래서 이 픽스처가
"진짜 응답과 같다"고 주장하지 않는다 — 주장하는 것은 **파이프라인이 이 형태를 어떻게 다루는가**
뿐이다. 이름이 실제와 다르면 파서가 조용히 0건을 내는 대신 관측된 키를 찍고 실패한다
(`test_market_normalize.py` 의 필드 매핑 검사).

단위 함정 둘을 일부러 그대로 재현한다.
  · `deposit` · `monthlyRent` 는 **만원 단위**이고 **콤마가 섞인 문자열**이다
  · 전세는 `monthlyRent` 가 `0` 이다 (0 이 아니면 월세 거래다)
"""

from __future__ import annotations

#: 정상 응답 봉투. 오류 봉투와 **루트 태그가 다르다** — 실제로 관측한 차이다.
_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>{code}</resultCode><resultMsg>{msg}</resultMsg></header>
  <body>
    <items>
{items}
    </items>
    <numOfRows>{rows}</numOfRows>
    <pageNo>{page}</pageNo>
    <totalCount>{total}</totalCount>
  </body>
</response>"""

#: 미등록 키로 실제 호출해서 받은 봉투 (2026-08-14 관측, HTTP 403).
_AUTH_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenAPI_ServiceResponse>
<cmmMsgHeader>
  <errMsg>{err}</errMsg>
  <returnAuthMsg>{auth}</returnAuthMsg>
  <returnReasonCode>{reason}</returnReasonCode>
</cmmMsgHeader>
</OpenAPI_ServiceResponse>"""


def item_xml(
    *,
    deposit: str = "33,000",
    monthly_rent: str = "0",
    area: str = "75.62",
    year: str = "2026",
    month: str = "6",
    day: str = "15",
    apt: str = "테스트아파트",
    umd: str = "테스트동",
    field_names: dict[str, str] | None = None,
) -> str:
    names = {
        "deposit": "deposit",
        "monthlyRent": "monthlyRent",
        "exclUseAr": "exclUseAr",
        "dealYear": "dealYear",
        "dealMonth": "dealMonth",
        "dealDay": "dealDay",
        "aptNm": "aptNm",
        "umdNm": "umdNm",
    }
    names.update(field_names or {})
    values = {
        "deposit": deposit,
        "monthlyRent": monthly_rent,
        "exclUseAr": area,
        "dealYear": year,
        "dealMonth": month,
        "dealDay": day,
        "aptNm": apt,
        "umdNm": umd,
    }
    body = "".join(f"<{names[k]}>{v}</{names[k]}>" for k, v in values.items())
    return f"      <item>{body}</item>"


def response_xml(items: list[str], *, code: str = "00", msg: str = "OK",
                 rows: int = 100, page: int = 1, total: int | None = None) -> str:
    return _RESPONSE.format(
        code=code, msg=msg, items="\n".join(items), rows=rows, page=page,
        total=len(items) if total is None else total,
    )


def auth_error_xml(err: str = "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                   auth: str = "등록되지 않은 인증키", reason: str = "30") -> str:
    return _AUTH_ERROR.format(err=err, auth=auth, reason=reason)


# --------------------------------------------------------------------------
# 정규화 뒤의 원시 항목 (dict) 을 바로 만들어 주는 헬퍼 — 집계 테스트용
# --------------------------------------------------------------------------


def raw_item(deposit_manwon: int, monthly_manwon: int = 0, *, area: float = 59.9,
             year: int = 2026, month: int = 6, day: int = 15,
             apt: str = "테스트아파트") -> dict[str, str]:
    return {
        "deposit": f"{deposit_manwon:,}",
        "monthlyRent": str(monthly_manwon),
        "exclUseAr": str(area),
        "dealYear": str(year),
        "dealMonth": str(month),
        "dealDay": str(day),
        "aptNm": apt,
        "umdNm": "테스트동",
    }


def jeonse_items(count: int, *, manwon: int = 28_000, **over) -> list[dict[str, str]]:
    """전세 거래 `count` 건. 값이 전부 같으면 중앙값이 명백해 단언이 읽기 쉽다."""
    return [raw_item(manwon, 0, **over) for _ in range(count)]


def monthly_items(count: int, *, deposit_manwon: int = 2_000, rent_manwon: int = 85,
                  **over) -> list[dict[str, str]]:
    return [raw_item(deposit_manwon, rent_manwon, **over) for _ in range(count)]


def trade_raw_item(manwon: int, *, area: float = 59.9, year: int = 2026, month: int = 6,
                   day: int = 15, apt: str = "테스트아파트") -> dict[str, str]:
    """매매 응답 항목. **전월세와 이름이 다르다** —
    금액은 `dealAmount`, 전용면적은 `excluUseAr`(전월세는 `exclUseAr`) 다.
    이 차이를 픽스처가 그대로 재현해야 매핑이 실제로 검사된다."""
    return {
        "dealAmount": f"{manwon:,}",
        "excluUseAr": str(area),
        "dealYear": str(year),
        "dealMonth": str(month),
        "dealDay": str(day),
        "aptNm": apt,
        "umdNm": "테스트동",
    }


def trade_items(count: int, *, manwon: int = 45_000, **over) -> list[dict[str, str]]:
    return [trade_raw_item(manwon, **over) for _ in range(count)]


class FakeFetch:
    """`(service, region_code, ym) -> 원시 항목 목록`.

    수집 창의 **첫 달에만** 항목을 싣는다. 창이 3개월이면 같은 목록이 세 번 들어와
    표본이 3배로 부풀고, 그러면 테스트가 표본 최소 건수를 정확히 겨눌 수 없다.
    호출 이력(`calls`)을 남겨 **몇 번 불렀는지**도 본다.
    """

    def __init__(self, per_region: dict[str, list[dict[str, str]]] | None = None,
                 *, default: list[dict[str, str]] | None = None,
                 trade_per_region: dict[str, list[dict[str, str]]] | None = None,
                 trade_default: list[dict[str, str]] | None = None,
                 fail_for: set[str] | None = None,
                 trade_fail_for: set[str] | None = None,
                 error: Exception | None = None) -> None:
        self.per_region = per_region or {}
        self.default = default
        self.trade_per_region = trade_per_region or {}
        self.trade_default = trade_default
        self.fail_for = fail_for or set()
        self.trade_fail_for = trade_fail_for or set()
        self.error = error
        self.calls: list[tuple[str, str, str]] = []
        self._served: set[tuple[str, str]] = set()

    def __call__(self, service: str, region_code: str, ym: str) -> list[dict[str, str]]:
        self.calls.append((service, region_code, ym))
        failing = self.trade_fail_for if service == "trade" else self.fail_for
        if region_code in failing:
            raise self.error or RuntimeError(f"수집 실패: {service}/{region_code}")
        if (service, region_code) in self._served:
            return []
        self._served.add((service, region_code))
        if service == "trade":
            if region_code in self.trade_per_region:
                return list(self.trade_per_region[region_code])
            return list(self.trade_default if self.trade_default is not None else trade_items(12))
        if region_code in self.per_region:
            return list(self.per_region[region_code])
        return list(self.default or [])
