"""SPEC 3 흐름의 **fetch** — 국토교통부 실거래가 오픈API 두 개.

    아파트 전월세  RTMSDataSvcAptRent/getRTMSDataSvcAptRent
    아파트 매매    RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade

이용조건은 실사에서 원문확인됐다 — **이용허락범위 제한 없음 / 무료 / 자동승인**
(`docs/engineering/diligence/FINDINGS.md` D1). 저장·가공·재배포에 걸리는 제한이 없다.

**이 모듈이 지고 있는 것은 하나다 — 조용한 0건을 만들지 않는다.**
응답에는 봉투가 둘 있고 **루트 태그가 다르다.**

    <response><header><resultCode>…            정상 (0건도 정상이다)
    <OpenAPI_ServiceResponse><cmmMsgHeader>…   서비스 오류 (미등록 키 등, HTTP 403)

두 번째를 모르면 오류 응답이 「거래가 없었다」로 읽힌다. 2026-08-14 에 더미 키로 실제
호출해 관측한 봉투이며, 두 엔드포인트가 같은 형태를 돌려준다.

**응답 항목명은 2차출처까지만 확인됐다** (원문 명세가 hwp 기술문서다). 그래서 이름 매핑은
정규화 단계가 **후보 목록**으로 받고, 하나도 맞지 않으면 관측된 키를 들고 실패한다.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any, Callable, Mapping, Sequence
from xml.etree import ElementTree

import httpx

from ...config import clean_env_value, find_env_file, parse_env_text

#: 서비스 공통 키. 발급 형태가 서비스마다 갈릴 수 있어 전용 키를 **먼저** 본다.
API_KEY_ENV = "MOLIT_API_KEY"
SERVICE_KEY_ENV = {
    "rent": "MOLIT_RENT_API_KEY",
    "trade": "MOLIT_TRADE_API_KEY",
}

ENDPOINTS = {
    "rent": "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
    "trade": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
}

#: 계보에 실리는 출처. `source_ref` 는 **자료 제공 페이지**를 가리킨다 — 호출 URL 은
#: 키가 붙는 자리라 계보에 남길 것이 못 된다.
SOURCE_NAMES = {
    "rent": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)",
    "trade": "국토교통부 아파트 매매 실거래가 (공공데이터포털)",
}
SOURCE_REFS = {
    "rent": "https://www.data.go.kr/data/15126474/openapi.do",
    "trade": "https://www.data.go.kr/data/15126469/openapi.do",
}

#: 한 번에 받는 행 수. 포털 공통 상한이 100 이다. 모델 상수가 아니라 **호출 방식**이므로
#: `contracts/` 에 등재하지 않는다 (SPEC 5.1.2 — 판정에 들어가는 파라미터가 아니다).
PAGE_SIZE = 100

#: 페이지를 도는 상한. `totalCount` 를 믿되, 그것이 거짓이어도 무한히 돌지 않는다.
MAX_PAGES = 200

SUCCESS_CODES = ("00", "000")


class MarketSourceError(Exception):
    """수집 실패의 뿌리. 배치는 이것을 잡아 「이전 값 유지 + stale」로 간다."""


class MarketAuthError(MarketSourceError):
    """키가 없거나 등록되지 않았다. **키 없이 돌 때 배치가 타는 정상 경로다** (SPEC 9.2.1)."""


class MarketServiceError(MarketSourceError):
    """서비스가 오류를 돌려줬거나 응답이 XML 이 아니다."""


def normalise_service_key(value: str) -> str:
    """공공데이터포털이 주는 **두 형태** 중 무엇이 와도 같은 키로 만든다.

    포털은 인증키를 `Encoding` 과 `Decoding` 두 벌로 보여 준다. 우리는 키를
    `httpx.get(..., params=...)` 로 넘기고 httpx 가 값을 **다시 URL 인코딩**하므로,
    Encoding 쪽(`%2B` 등이 이미 박힌 것)을 그대로 쓰면 `%` 가 `%25` 로 이중 인코딩되어
    포털이 **[등록되지 않은 서비스키]** 로 거절한다.

    ★ 그 오류 메시지가 이 함수의 존재 이유다. 원인은 인코딩인데 메시지는 **키가 등록되지
      않았다고 말한다.** 실제로 그 함정에 걸렸고, 셋을 나란히 돌려서야 원인이 잡혔다 —
      Encoding+params 403 / Decoding+params 200 / Encoding을 URL에 직접 200.
      사용자에게 [Decoding 키를 쓰세요]라고 문서로 부탁하는 대신 코드가 흡수한다.

    안전한 이유: 포털 인증키는 base64 계열(`A-Za-z0-9+/=`)이라 **`%` 가 들어갈 수 없다.**
    그러므로 `%` 의 존재는 곧 URL 인코딩되었다는 뜻이고, 되돌리는 것이 모호하지 않다.
    `unquote_plus` 가 아니라 `unquote` 를 쓴다 — 키의 `+` 는 공백이 아니라 base64 문자다.
    """
    if "%" not in value:
        return value
    return urllib.parse.unquote(value)


def resolve_api_key(service: str | None = None) -> str | None:
    """서비스 전용 키 -> 공통 키 순. 없으면 `None` 이다 — **예외가 아니다.**

    키 부재는 정상 실패의 입구이므로(SPEC 9.2.1) 여기서 터지면 그 경로를 탈 수 없다.

    `.env` 를 직접 파싱하는 이유: `config.ENV_KEYS` 는 LLM 키만 담은 허용목록이라
    이 키를 `os.environ` 에 싣지 않는다. 그렇다고 파싱 규칙을 여기 다시 쓰면 따옴표·BOM·
    `export` 처리가 두 벌로 갈린다 (SPEC 9.1.1 이 기록한 실패 유형). **규칙은 `config` 의
    것을 그대로 쓰고 키만 우리가 꺼낸다.**
    """
    names = [SERVICE_KEY_ENV[service]] if service in SERVICE_KEY_ENV else []
    names.append(API_KEY_ENV)

    for name in names:
        value = clean_env_value(os.environ.get(name, ""))
        if value:
            return normalise_service_key(value)

    env_path = find_env_file()
    if env_path is None:
        return None
    try:
        parsed = parse_env_text(env_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return None
    for name in names:
        value = clean_env_value(parsed.get(name, ""))
        if value:
            return normalise_service_key(value)
    return None


def _root(xml_text: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        # 포털이 점검 페이지(HTML)를 돌려주는 일이 있다. 0건으로 뭉개지 않는다.
        raise MarketServiceError(
            f"응답을 XML 로 읽지 못했다: {exc} — 앞부분: {xml_text[:120]!r}"
        ) from exc


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text


#: 우리가 아는 봉투. 그 밖의 루트는 **정체를 모르는 응답**이다.
KNOWN_ROOTS = ("response", "OpenAPI_ServiceResponse")


def _raise_for_envelope(root: ElementTree.Element) -> None:
    # ★ 점검 페이지(HTML)는 XML 로도 잘 파싱된다. 루트를 검사하지 않으면 `<item>` 이
    #   없으므로 **0건**이 되고, 그 상태는 「그 달에 거래가 없었다」와 구분되지 않는다.
    #   실제로 이 테스트가 먼저 빨간불을 켜서 잡았다.
    if root.tag not in KNOWN_ROOTS:
        raise MarketServiceError(
            f"모르는 응답 봉투다: 루트 태그={root.tag!r} (아는 것: {list(KNOWN_ROOTS)}). "
            "0건으로 넘어가지 않는다"
        )

    if root.tag == "OpenAPI_ServiceResponse":
        err = _text(root.find(".//errMsg")) or "알 수 없는 서비스 오류"
        reason = _text(root.find(".//returnReasonCode"))
        message = f"{err} (returnReasonCode={reason})"
        if "SERVICE_KEY" in err.upper():
            raise MarketAuthError(message)
        raise MarketServiceError(message)

    code = _text(root.find("./header/resultCode")).strip()
    if code and code not in SUCCESS_CODES:
        msg = _text(root.find("./header/resultMsg")).strip()
        message = f"서비스가 오류를 돌려줬다: resultCode={code} resultMsg={msg}"
        if "KEY" in msg.upper():
            raise MarketAuthError(message)
        raise MarketServiceError(message)


def parse_items(xml_text: str) -> list[dict[str, str]]:
    """`<item>` 을 **가공하지 않은 문자열 dict** 로 돌려준다.

    단위 변환도 필드 매핑도 여기서 하지 않는다 — 그것은 다음 단계(정규화)의 일이고,
    섞으면 「응답이 이랬다」와 「우리가 이렇게 읽었다」를 나중에 구분할 수 없다.
    """
    root = _root(xml_text)
    _raise_for_envelope(root)
    return [
        {child.tag: "" if child.text is None else child.text for child in item}
        for item in root.iter("item")
    ]


def total_count(xml_text: str) -> int:
    root = _root(xml_text)
    _raise_for_envelope(root)
    raw = _text(root.find(".//totalCount")).strip()
    return int(raw) if raw.isdigit() else 0


class MolitClient:
    """두 엔드포인트를 같은 방식으로 부른다.

    `max_attempts` · `timeout_seconds` 는 **모델 상수에서 주입받는다.** 기본값을 두지
    않는 이유는 `analyze(now=...)` 와 같다 — 기본값이 곧 등재되지 않은 상수다.
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        timeout_seconds: float,
        api_key: Callable[[str], str | None] = resolve_api_key,
        transport: Callable[..., Any] = httpx.get,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(f"max_attempts 는 1 이상이어야 한다: {max_attempts}")
        self._max_attempts = max_attempts
        self._timeout = timeout_seconds
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep

    def fetch(self, service: str, region_code: str, ym: str) -> list[dict[str, str]]:
        """한 지역 · 한 계약월의 전 페이지. 실패는 `MarketSourceError` 로 나간다."""
        key = self._api_key(service)
        if not key:
            raise MarketAuthError(
                f"{service} 수집 키가 없다 — {SERVICE_KEY_ENV[service]} 또는 {API_KEY_ENV} "
                "를 환경변수나 .env 에 넣어라"
            )

        items: list[dict[str, str]] = []
        page = 1
        while page <= MAX_PAGES:
            body = self._request(service, key, region_code, ym, page)
            batch = parse_items(body)
            items.extend(batch)
            if len(batch) < PAGE_SIZE or len(items) >= total_count(body):
                break
            page += 1
        return items

    def _request(self, service: str, key: str, region_code: str, ym: str, page: int) -> str:
        params = {
            "serviceKey": key,
            "LAWD_CD": region_code,
            "DEAL_YMD": ym,
            "numOfRows": str(PAGE_SIZE),
            "pageNo": str(page),
        }
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._transport(
                    ENDPOINTS[service], params=params, timeout=self._timeout
                )
                # 인증 실패는 **본문**이 말해 준다 (HTTP 403 + 오류 봉투). 상태코드만 보고
                # 재시도하면 없는 키로 두 번 두드리게 된다.
                return response.text
            # 재시도는 **전송 실패에만** 건다. 서비스가 오류를 돌려준 것은 본문 파싱
            # 단계에서 드러나며, 그것은 다시 불러도 같은 답이 온다.
            except Exception as exc:  # 네트워크 계열
                last = exc
                if attempt < self._max_attempts:
                    self._sleep(0)
        raise MarketServiceError(
            f"{service} 호출이 {self._max_attempts}회 모두 실패했다 "
            f"({region_code}/{ym}): {last}"
        )


def fetcher(client: MolitClient) -> Callable[[str, str, str], Sequence[Mapping[str, str]]]:
    """파이프라인이 받는 모양 `(service, region_code, ym) -> 항목들` 로 감싼다."""
    return client.fetch
