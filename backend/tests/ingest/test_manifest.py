"""수집 대장(매니페스트)이 실제 파일·정책 목록과 어긋나지 않는지 고정한다.

대장은 사람이 읽는 문서이면서 적재의 입력이다. 둘이 갈라지면 대장은 그 순간
"적어 둔 것"일 뿐 검증된 것이 아니게 된다. 여기 있는 테스트가 그 갈라짐을 막는다.
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata

import pytest

from home_compass.ingest import sources as manifest


def _policies_json() -> list[dict]:
    path = manifest.POLICIES_JSON
    return json.loads(path.read_text(encoding="utf-8"))["policies"]


def test_manifest_covers_every_current_policy_in_order():
    """대상은 **현행 정책 전수**다. 빠지면 수집이 덜 된 것이고, 늘면 대상 밖을 끌어온 것이다.

    건수를 문장에 박지 않는다. 10건이라고 적어 두었더니 폐지 2건(`sme_youth_deposit` ·
    `gyeonggi_youth_rent`, `diligence/FINDINGS-4.md`)이 빠질 때 **문서만 낡았다.**
    비교는 `policies.json` 과 하므로 숫자를 적을 이유가 없다.
    """
    assert [p["id"] for p in _policies_json()] == [s.policy_id for s in manifest.SOURCES]


def test_manifest_policy_names_match_policies_json():
    """대장의 정책명이 `policies.json` 과 다르면 다른 정책을 수집한 것으로 읽힌다."""
    by_id = {p["id"]: p["name"] for p in _policies_json()}
    assert {s.policy_id: s.policy_name for s in manifest.SOURCES} == by_id


def test_recorded_codepoint_count_matches_the_stored_file():
    """대장의 코드포인트 수는 실측치여야 한다. 파일이 바뀌면 이 테스트가 먼저 깨진다."""
    checked = 0
    for source in manifest.SOURCES:
        if source.text_path is None:
            continue
        text = source.read_text()
        assert len(text) == source.codepoints, source.policy_id
        checked += 1
    assert checked == manifest.RETAINED_COUNT


def test_stored_text_is_already_nfc():
    """저장 시 정규화가 **길이를 바꾸지 않는다**는 것을 파일 단계에서 확인한다.

    바뀐다면 대장의 코드포인트 수와 저장소의 코드포인트 수가 갈라지고,
    span 오프셋은 저장소 쪽을 기준으로 하므로 대장이 틀린 숫자를 들고 있게 된다.
    """
    for source in manifest.SOURCES:
        if source.text_path is None:
            continue
        text = source.read_text()
        assert unicodedata.is_normalized("NFC", text), source.policy_id
        assert len(unicodedata.normalize("NFC", text)) == source.codepoints


def test_the_manifest_currently_has_no_unidentified_source():
    """미특정이 **0건**이 된 사실 자체를 고정한다.

    미특정은 원래 2건이었고, 그 둘이 곧 `sme_youth_deposit` 과 `gyeonggi_youth_rent` 였다.
    실사(`diligence/FINDINGS-4.md`)가 「출처를 못 찾았다」가 아니라 **「제도가 없다」** 임을
    확인했고 사용자 결정으로 두 정책을 폐기했으므로, 미특정 항목도 함께 사라졌다.

    이 핀이 빨간불이면 새 정책이 원문 없이 대장에 들어온 것이다. 그때 할 일은 이 테스트를
    지우는 게 아니라 **아래 불변식이 그 새 항목에 대해 성립하는지 보는 것**이다.
    """
    assert [s.policy_id for s in manifest.SOURCES if not s.identified] == []


def test_unidentified_sources_carry_no_document():
    """[출처 미특정] 인데 원문 파일이 붙어 있으면 **다른 문서로 대체한 것**이다.

    현재 대상은 0건이라 공허하게 통과한다 — 그 사실은 위 핀이 따로 붙든다. 불변식 자체를
    지우지 않는 이유는, 미특정 항목이 다시 생겼을 때 이 검사가 없으면 조용히 대체되기 때문이다.
    """
    for source in (s for s in manifest.SOURCES if not s.identified):
        assert not source.secured, source.policy_id
        assert source.text_path is None, source.policy_id
        assert source.codepoints is None, source.policy_id
        assert source.url is None, source.policy_id


def test_every_secured_source_records_where_it_came_from():
    """URL·조회일·문서형식·문서종류가 비면 다음 사람이 같은 길로 다시 올 수 없다."""
    for source in manifest.SOURCES:
        if not source.secured:
            continue
        assert source.url, source.policy_id
        assert source.doc_title, source.policy_id
        assert source.authority, source.policy_id
        assert source.doc_format in ("html", "pdf"), source.policy_id
        assert source.doc_kind in manifest.DOC_KINDS, source.policy_id


def test_loadable_is_derived_from_the_licence_gate():
    """적재 가능 여부는 **별도 스위치가 아니라 이용조건에서 파생**된다.

    사람이 켜고 끄는 불리언이면 이용조건과 조용히 갈라진다.
    """
    for source in manifest.SOURCES:
        expected = source.licence in manifest.LICENCES_CLEARED and source.text_path is not None
        assert source.loadable is expected, source.policy_id


def test_the_cleared_licences_are_exactly_the_two_we_have_judged():
    """★ 게이트가 **조용히 넓어지는 것**을 막는다.

    계약 결정 #15 가 연 것은 `kogl_typed` 이고, 그 판단의 대상은 **제4유형**이었다.
    새 이용조건 갈래가 생겼을 때 이 목록에 슬쩍 얹히면 아무도 판단하지 않은 조건으로
    저작물이 적재된다 — 「확인하지 않은 채 저장·배포하지 않는다」가 그 지점에서 무너진다.
    """
    assert manifest.LICENCES_CLEARED == (
        manifest.LICENCE_FREE_USE,
        manifest.LICENCE_KOGL_TYPED,
    )
    assert manifest.LICENCE_CONSULTATION not in manifest.LICENCES_CLEARED
    assert manifest.LICENCE_UNCONFIRMED not in manifest.LICENCES_CLEARED

    typed = [s for s in manifest.SOURCES if s.licence == manifest.LICENCE_KOGL_TYPED]
    assert typed
    for source in typed:
        assert "제4유형" in (source.kogl_type or ""), source.policy_id


def test_sources_without_a_confirmed_licence_keep_no_text_in_the_repository():
    """이용조건이 확인되지 않은 원문은 **작업트리에도 두지 않는다.**

    git 에 커밋하는 것도 저장·배포다. 「확인하지 않은 채 저장·배포하지 않는다」가
    저장소 적재와 똑같이 걸린다. 크기(`codepoints`)는 원문이 아니라 관측 사실이므로 남는다.

    계약 결정 #15 이후 이 대상은 **⑤ 복지로 1건**이다 — 서울시 2건은 유형이 확인돼
    열렸고, 복지로는 여전히 유형을 정하는 문서를 찾지 못한 상태다.
    """
    blocked = [
        s
        for s in manifest.SOURCES
        if s.secured and s.licence not in manifest.LICENCES_CLEARED
    ]
    assert blocked, "차단 대상이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in blocked:
        assert source.text_file is None, source.policy_id
        assert source.codepoints is not None, source.policy_id  # 크기는 남는다
        assert source.url, source.policy_id  # URL 도 남는다
        assert not (manifest.text_dir() / f"{source.policy_id}.txt").exists(), source.policy_id


def test_the_text_directory_holds_exactly_the_permitted_files():
    """디렉터리에 **예상 밖의 파일이 생기는 것**을 막는다.

    다음 사람이 차단된 출처를 다시 받아 두면 그대로 커밋될 수 있다. 목록을 못박아 둔다.
    """
    expected = {s.text_file for s in manifest.SOURCES if s.text_file is not None}
    actual = {p.name for p in manifest.text_dir().glob("*.txt")}
    assert actual == expected


def test_git_does_not_rewrite_the_line_endings_of_stored_text():
    """`.gitattributes` 가 `data/policy_sources/**` 를 변환 대상에서 빼 두었는가.

    빼지 않으면 `* text=auto` 가 걸려 **윈도우 체크아웃과 리눅스 체크아웃의 코드포인트 수가
    달라지고** span 오프셋이 통째로 밀린다 (SPEC 4.2.1). 커밋본이 같아도 깨지므로
    파일 내용 검사로는 잡히지 않는다 — 속성 자체를 본다.
    """
    root = manifest.POLICIES_JSON.resolve().parents[4]
    targets = [s for s in manifest.SOURCES if s.text_path is not None]
    assert targets

    try:
        result = subprocess.run(
            ["git", "check-attr", "text", "--"] + [str(s.text_path) for s in targets],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - git 없는 환경
        pytest.skip(f"git 을 실행할 수 없다: {exc}")

    if result.returncode != 0:  # pragma: no cover - 저장소 밖에서 돌린 경우
        pytest.skip(f"git check-attr 실패: {result.stderr.strip()}")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == len(targets)
    for line in lines:
        assert line.endswith(": text: unset"), line


def test_licence_is_recorded_for_every_secured_source():
    """확보했는데 이용조건 칸이 비어 있으면 [확인하지 않은 채 저장]이 그대로 통과한다."""
    for source in manifest.SOURCES:
        if not source.secured:
            continue
        assert source.licence in manifest.LICENCES, source.policy_id
        assert source.kogl_type, source.policy_id


def test_seoul_notices_are_recorded_as_kogl_type_4():
    """★ **앞 판정 정정.** 서울시 2건은 [협의 필요] 가 아니라 **제4유형이 부착**돼 있다.

    앞 과업은 서울주거포털 게시글만 보고 「마크 없음 → 사전 협의 필요」로 단정했다.
    **유형이 표시되는 표면이 문서 페이지만이 아니다.** 유형은 `www.seoul.go.kr`
    고시·공고 상세(`nttNo=457234` · `458161`)에 부착돼 있다 — `lic_4.jpg` 이미지 ·
    `rel="license"` · `kogl.or.kr/info/licenseType4.do` 링크.

    서울시 정책의 사전 협의 조항은 「공공누리가 **부착되지 않은** 자료」에 걸리므로
    이 2건은 그 조항의 대상이 아니다. 실사 원문은
    `docs/engineering/collection/excerpts/공공누리-유형확인.md`.
    """
    seoul = [
        s
        for s in manifest.SOURCES
        if s.policy_id in ("seoul_youth_rent", "seoul_deposit_interest")
    ]
    assert len(seoul) == 2
    for source in seoul:
        assert source.licence == manifest.LICENCE_KOGL_TYPED, source.policy_id
        assert "제4유형" in (source.kogl_type or ""), source.policy_id


def test_kogl_typed_sources_name_the_type_number():
    """[유형 확인] 이라고 적었으면 **몇 유형인지**가 칸에 있어야 한다.

    유형번호 없이 「공공누리 마크가 있다」만 적으면 조건(출처표시 · 상업적 이용 ·
    변경 허용 여부)이 특정되지 않는다. 그건 확인이 아니라 미확인이다 —
    복지로 ⑤ 가 정확히 그 상태다(유형번호 없는 OPEN 마크).
    """
    typed = [s for s in manifest.SOURCES if s.licence == manifest.LICENCE_KOGL_TYPED]
    assert typed, "유형 확인이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in typed:
        assert re.search(r"제[0-4]유형", source.kogl_type or ""), source.policy_id


def test_unconfirmed_sources_record_that_the_check_failed():
    """[확인 실패] 와 [협의 필요] 는 다르다. 뭉치면 어느 문이 열 수 있는 문인지 사라진다.

    전자는 「유형을 정하는 문서를 찾지 못했다」이고 후자는 「기관이 협의를 요구한다」다.
    다음 사람이 어디부터 다시 봐야 하는지가 달라지므로 칸에 남긴다.
    """
    unconfirmed = [
        s
        for s in manifest.SOURCES
        if s.secured and s.licence == manifest.LICENCE_UNCONFIRMED
    ]
    assert unconfirmed, "미확인이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in unconfirmed:
        assert "확인 실패" in source.note, source.policy_id
