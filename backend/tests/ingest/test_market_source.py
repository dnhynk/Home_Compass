"""SPEC 3 흐름의 **fetch** — 외부 응답을 어떻게 읽고 어떻게 실패하는가.

이 파일이 지키는 것은 하나다. **조용한 0건을 만들지 않는다.**
항목명이 우리 기대와 다르면 「거래가 없었다」로 보이는데, 그 상태에서는 아무도
무엇이 잘못됐는지 알 수 없다. 응답 항목명은 2차출처까지만 확인됐으므로 이 방어가
가정이 아니라 실제로 필요한 것이다.
"""

from __future__ import annotations

import pytest
from market_fixtures import auth_error_xml, item_xml, response_xml

from home_compass.ingest.market.source import (
    API_KEY_ENV,
    MarketAuthError,
    MarketServiceError,
    parse_items,
    resolve_api_key,
    total_count,
)


# --------------------------------------------------------------------------
# 1. 정상 응답
# --------------------------------------------------------------------------


def test_items_are_read_as_plain_dicts():
    xml = response_xml([item_xml(deposit="33,000", monthly_rent="0")])
    items = parse_items(xml)

    assert len(items) == 1
    # **가공하지 않는다.** 단위 변환과 필드 매핑은 다음 단계(정규화)의 일이다.
    assert items[0]["deposit"] == "33,000"
    assert items[0]["monthlyRent"] == "0"
    assert items[0]["exclUseAr"] == "75.62"


def test_empty_items_is_not_an_error():
    """거래가 없는 달은 흔하다. 0건 자체는 실패가 아니다 —
    실패로 다루면 배치가 계절을 오류로 신고한다."""
    assert parse_items(response_xml([], total=0)) == []


def test_total_count_is_read_for_paging():
    xml = response_xml([item_xml()], total=137)
    assert total_count(xml) == 137


def test_whitespace_only_values_survive_as_given():
    """`contractType` 처럼 공백 하나만 든 칸이 실제로 온다. 여기서 지우지 않는다 —
    빈 값과 공백 값의 차이를 정규화 단계가 볼 수 있어야 한다."""
    items = parse_items(response_xml([item_xml() + ""]))
    assert isinstance(items[0]["aptNm"], str)


# --------------------------------------------------------------------------
# 2. 실패 — 두 가지 봉투가 있고 루트 태그가 다르다
# --------------------------------------------------------------------------


def test_unregistered_key_envelope_is_an_auth_error():
    """미등록 키로 실제 호출해 관측한 봉투다 (HTTP 403).

    정상 봉투(`response`)와 루트 태그가 달라, 이것을 모르면 「항목 0건」으로 읽힌다.
    """
    with pytest.raises(MarketAuthError) as exc:
        parse_items(auth_error_xml())
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in str(exc.value)


def test_service_error_code_in_the_normal_envelope_is_an_error():
    with pytest.raises(MarketServiceError) as exc:
        parse_items(response_xml([], code="22", msg="LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS"))
    assert "22" in str(exc.value)


def test_html_or_garbage_is_a_service_error_not_zero_items():
    """포털이 점검 페이지(HTML)를 돌려주는 일이 있다. XML 파싱 실패를 0건으로 뭉개지 않는다."""
    with pytest.raises(MarketServiceError):
        parse_items("<html><body>서비스 점검 중</body></html>")


def test_completely_unparsable_text_is_a_service_error():
    with pytest.raises(MarketServiceError):
        parse_items("not xml at all <<<")


# --------------------------------------------------------------------------
# 3. 키 조회 — .env 는 편의 수단일 뿐 유일 경로가 아니다 (부록 A)
# --------------------------------------------------------------------------


def test_api_key_comes_from_the_environment_first(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "  key-from-env  ")
    assert resolve_api_key() == "key-from-env"


def test_missing_api_key_is_none_not_an_exception(monkeypatch, tmp_path):
    """키 부재는 **정상 실패**의 입구다 (SPEC 9.2.1). 여기서 터지면 그 경로를 못 탄다."""
    monkeypatch.setenv(API_KEY_ENV, "")
    monkeypatch.setattr("home_compass.ingest.market.source.find_env_file", lambda: None)
    assert resolve_api_key() is None


def test_api_key_falls_back_to_a_dotenv_file(monkeypatch, tmp_path):
    """`config.ENV_KEYS` 는 LLM 키만 허용목록에 두고 있어 이 키를 os.environ 에 싣지 않는다.
    그래서 **파싱 규칙은 config 의 것을 그대로 쓰고** 키만 우리가 꺼낸다 — 규칙을 두 벌로
    만들면 그 순간 따옴표·BOM 처리가 갈린다 (SPEC 9.1.1 이 기록한 실패 유형)."""
    env_file = tmp_path / ".env"
    env_file.write_text(f'{API_KEY_ENV}="<key-from-file>"\n', encoding="utf-8")
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr("home_compass.ingest.market.source.find_env_file", lambda: env_file)

    assert resolve_api_key() == "key-from-file"


# --- 인증키의 두 형태 (공공데이터포털) --------------------------------------

def test_encoding_form_key_is_normalised_to_the_decoding_form():
    """포털의 `Encoding` 키를 그대로 쓰면 이중 인코딩으로 인증이 **거절된다.**

    우리는 키를 `httpx.get(..., params=...)` 로 넘기고 httpx 가 값을 다시 URL 인코딩하므로,
    `%2B` 가 `%252B` 가 되어 포털이 [등록되지 않은 서비스키]로 돌려준다.

    ★ 이 테스트가 있는 이유는 **오류 메시지가 원인을 가리키지 않기 때문**이다.
      실제로 걸렸고, 2026-08-14 에 같은 키로 셋을 나란히 호출해서야 원인이 잡혔다 —
      Encoding+params 403 / Decoding+params 200 / Encoding 을 URL 에 직접 200.
    """
    from home_compass.ingest.market.source import normalise_service_key

    decoding = "abcDEF123+/xyz=="
    encoding = "abcDEF123%2B%2Fxyz%3D%3D"
    assert normalise_service_key(encoding) == decoding


def test_decoding_form_key_passes_through_untouched():
    """이미 Decoding 형태면 건드리지 않는다. `+` 는 공백이 아니라 base64 문자다."""
    from home_compass.ingest.market.source import normalise_service_key

    key = "abcDEF123+/xyz=="
    assert normalise_service_key(key) == key


def test_resolve_api_key_returns_the_normalised_key(monkeypatch):
    """환경변수로 들어온 Encoding 키가 **조회 시점에** 정규화되는가."""
    from home_compass.ingest.market import source

    monkeypatch.setenv(source.SERVICE_KEY_ENV["rent"], "aa%2Bbb%3D")
    assert source.resolve_api_key("rent") == "aa+bb="
