"""계약 생성기 자체의 성질 (소유자: `api`, SPEC 9.4).

`tests/crosscheck/` 는 **결과물**을 본다 — 커밋본과 재생성본이 같은가, 계약이 SPEC 이
요구한 것을 담고 있는가. 여기서는 **생성기**를 본다. 결정적인가, 앱 상태를 오염시키지
않는가, 버전 규칙(SPEC 8.4)을 지키는가.
"""

from __future__ import annotations

import json

from firsthome.common import ENGINE_VERSION
from firsthome.main import (
    API_CONTRACT_VERSION,
    app,
    build_openapi_document,
    render_openapi_document,
    write_openapi_document,
)


def test_rendering_is_stable_within_a_process():
    assert render_openapi_document() == render_openapi_document()


def test_rendering_obeys_the_declared_serialization_rules():
    rendered = render_openapi_document()
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert "\r" not in rendered
    # 키 정렬이 실제로 걸렸는가 — 안 걸리면 dict 삽입 순서가 그대로 실린다.
    document = json.loads(rendered)
    assert list(document) == sorted(document)
    # 한국어가 유니코드 이스케이프로 부풀지 않고 그대로 실렸는가 (ensure_ascii=False).
    assert app.description in rendered and app.description.isascii() is False


def test_building_the_document_does_not_poison_the_live_app():
    """`app.openapi()` 는 결과를 캐시에 붙인다. 생성기가 그 객체를 만지면 `/openapi.json`
    응답까지 함께 바뀐다 — 계약 파일을 만들었더니 서버 응답이 달라지는 종류의 사고다."""
    before = app.openapi_schema
    document = build_openapi_document()
    document["info"]["title"] = "오염"
    assert app.openapi_schema is before
    assert app.openapi()["info"]["title"] == app.title


def test_the_contract_version_is_decoupled_from_the_engine_version():
    """SPEC 8.4 — 둘은 다른 규칙을 따른다.

    `ENGINE_VERSION` 은 "판정 출력이 달라지면" 올라가고(1-② 의 값 교체 포함),
    `info.version` 은 "8.2 절차로만" 바뀐다. 묶어 두면 값 교체가 계약 버전을 절차 없이
    올린다. 지금은 값이 같지만 **출처가 다르다** — 그 사실을 여기서 붙든다.
    """
    document = build_openapi_document()
    assert document["info"]["version"] == API_CONTRACT_VERSION
    assert document["info"]["x-engine-version"] == ENGINE_VERSION


def test_writing_is_a_no_op_when_nothing_changed(tmp_path):
    """내용이 같으면 파일을 건드리지 않는다. mtime 만 흔들면 무엇이 바뀌었는지가 흐려진다."""
    target = tmp_path / "openapi.json"
    assert write_openapi_document(target) is True
    first = target.stat().st_mtime_ns
    assert write_openapi_document(target) is False
    assert target.stat().st_mtime_ns == first


def test_the_written_file_has_no_bom_and_lf_endings(tmp_path):
    target = tmp_path / "openapi.json"
    write_openapi_document(target)
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert json.loads(raw.decode("utf-8"))["openapi"].startswith("3.1.")
