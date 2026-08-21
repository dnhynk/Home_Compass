"""SPEC 4.4 · D-3 원칙 3 — 검토 화면이 서는 근거 (소유자: `api`).

4.4 는 네 항목을 「표시하라」고 적었지만 목적은 표시가 아니라 **거수기 방지**다. 그래서
이 파일이 재는 것은 「필드가 응답에 있는가」가 아니라 **「이 응답만 보고 승인·반려를 가를
수 있는가」** 다. 셋으로 나뉜다.

    1. 근거 대조가 **맞는 구간**을 가리키는가 (4.4 #1)
    2. 승인 시 판정이 어떻게 바뀌는가를 **실제 사례로** 내는가 (4.4 #2)
    3. 무엇이 어떻게 바뀌는가를 **거짓 없이** 그리는가 (4.4 #3 · PR #58 의 병합 규칙)

## ★ 오프셋은 서버가 자른다 (코디네이터 결정 2026-08-14)

과업 원안은 [JS 가 `Array.from(text)` 로 코드포인트 배열을 만들어 자르고 그것을 테스트로
고정하라] 였다. **이 저장소에는 JS 실행 하네스가 없다** — 결정 #31 이 CI 를 파이썬 전용으로
못박았고, `test_format_golden.py` 는 자기 머리에 「JS 변은 6단계 web 이 맡는다」고 적어
두었다. 그대로 하면 [고정하라]와 [node 를 들이지 마라]가 양립하지 않는다.

그래서 상세 API 가 원문을 **세그먼트 배열**로 내려보내고 화면은 순서대로 렌더만 한다.
파이썬 `str` 인덱스가 곧 SPEC 4.2.1 의 코드포인트이므로 **단위 변환이 아예 없어진다.**
`extraction_verify.locate_quote` 가 이미 같은 이유로 파이썬에서 자른다.

그 결과 이 파일이 **BMP 밖 문자로 경계를 고정한다.** UTF-16 코드유닛으로 자르면 여기서
빨간불이 난다 — 그것이 이 절이 있는 이유다.

격리: 케이스마다 자기 `tmp_path` 저장소를 만들어 `HOME_COMPASS_STORE_URL` 을 그쪽으로 돌린다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import CSRF_HEADER_NAME, ensure_seed_accounts
from home_compass.main import app
from home_compass.store import (
    STORE_URL_ENV,
    PolicySource,
    RuleDraft,
    RuleSpanMapping,
    create_store,
)
from home_compass.store.seed import seed_all

REPO_ROOT = Path(__file__).resolve().parents[3]
REGRESSION_PROFILES = REPO_ROOT / "contracts" / "regression_profiles.json"

T0 = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)

COUNSELOR_PW = os.environ["HOME_COMPASS_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"]

# --------------------------------------------------------------------------
# 원문 — **BMP 밖 문자를 일부러 넣는다**
# --------------------------------------------------------------------------
#
# `😀`(U+1F600) 과 `𝕏`(U+1D54F) 는 UTF-16 에서 **2 코드유닛**이다. 한글은 1 코드유닛이라
# 한글만으로는 이 결함이 드러나지 않는다 — 그래서 둘을 섞고, 하이라이트할 구간을
# **두 문자 뒤쪽에** 둔다. 코드유닛으로 세면 그 지점부터 오프셋이 어긋난다.
SOURCE_TEXT = (
    "제1조(목적) 이 지침은 청년 주거 지원을 정한다. 😀 "
    "제2조(대상) 신청 연령은 만 19세 이상 34세 이하로 한다. 𝕏 "
    "제3조(소득) 부부합산 연소득은 5,000만원 이하여야 한다. "
    "제4조(한도) 대출 한도는 2억원으로 한다. "
    "제5조(금리) 금리는 연 1.5%에서 2.9% 범위로 한다. "
    "제6조(확인) 기금 소진 시 조기 마감될 수 있다."
)

QUOTES = {
    "/criteria/ageMin": "만 19세 이상",
    "/criteria/ageMax": "34세 이하",
    "/criteria/annualIncomeMaxKRW": "연소득은 5,000만원 이하",
    "/criteria/requireHomeless": "청년 주거 지원",
    "/criteria/requireNewlywed": "부부합산",
    "/criteria/requireSME": "이 지침은",
    "/criteria/regionPrefixes": "제2조(대상)",
    "/maxAmountKRW": "대출 한도는 2억원",
    "/rateRangePct": "연 1.5%에서 2.9%",
    "/conditionalChecks/0": "기금 소진 시 조기 마감될 수 있다",
}

#: `/criteria/assetMaxKRW` 는 **일부러 빠져 있다.** `not_found` 이므로 span 이 없는 것이
#: 정상이며(SPEC 4.2.2), 화면이 그것을 「누락」으로 그리면 안 된다.
DRAFT_PAYLOAD = {
    "policy_id": "buttress_youth",
    "criteria": {
        "ageMin": 19,
        "ageMax": 34,
        "annualIncomeMaxKRW": 50_000_000,
        "assetMaxKRW": None,
        "requireHomeless": True,
        "requireNewlywed": False,
        "requireSME": False,
        "regionPrefixes": None,
    },
    "maxAmountKRW": 200_000_000,
    "rateRangePct": [1.5, 2.9],
    "conditionalChecks": ["기금 소진 시 조기 마감될 수 있다"],
    "not_found": ["/criteria/assetMaxKRW"],
}


def detail_path(draft_id: str) -> str:
    return f"/api/admin/drafts/{draft_id}"


def impact_path(draft_id: str) -> str:
    return f"/api/admin/drafts/{draft_id}/impact"


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'review.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
        store.policy_sources.add(
            PolicySource(
                id="src-review",
                text=SOURCE_TEXT,
                source_ref="https://nhuf.molit.go.kr/",
                fetched_at=T0,
                attribution="주택도시기금, 「청년전용 버팀목전세자금 운용지침」, 공고 제2026-1호, 공공누리 제4유형",
            )
        )
    monkeypatch.setenv(STORE_URL_ENV, url)
    return url


@pytest.fixture
def clock(monkeypatch):
    holder = {"now": T0}
    monkeypatch.setattr(main_module, "request_now", lambda: holder["now"])
    return holder


@pytest.fixture
def client(store_url, clock) -> TestClient:
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def add_draft(store_url: str, draft_id: str, payload: dict, *,
              quotes: dict[str, str] | None = None,
              policy_id: str | None = None,
              status: str = "pending") -> str:
    """초안 + 근거 구간. 오프셋은 **파이썬이 원문에서 찾아** 넣는다.

    `str.index` 의 단위가 코드포인트이므로 SPEC 4.2.1 과 같다 —
    `extraction_verify.locate_quote` 가 하는 것과 같은 계산이며, 테스트가 손으로 센
    숫자를 적으면 그 숫자 자체가 검증 대상이 되어 버린다.
    """
    with create_store(store_url) as store:
        store.rule_drafts.add(
            RuleDraft(
                id=draft_id,
                policy_source_id="src-review",
                policy_id=policy_id or payload["policy_id"],
                status=status,
                payload=payload,
                created_at=T0,
            )
        )
        for index, (field_path, quote) in enumerate(sorted((quotes or QUOTES).items())):
            start = SOURCE_TEXT.index(quote)
            store.rule_drafts.add_span(
                RuleSpanMapping(
                    id=f"{draft_id}:span:{index}",
                    draft_id=draft_id,
                    field_path=field_path,
                    start=start,
                    end=start + len(quote),
                )
            )
    return draft_id


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def as_rule_manager(client: TestClient) -> str:
    return login(client, "rulemanager", RULE_MANAGER_PW)


def as_counselor(client: TestClient) -> str:
    return login(client, "counselor", COUNSELOR_PW)


def detail(client: TestClient, draft_id: str = "d-review") -> dict:
    response = client.get(detail_path(draft_id))
    assert response.status_code == 200, response.text
    return response.json()


def field_by_path(body: dict, path: str) -> dict:
    match = [f for f in body["fields"] if f["path"] == path]
    assert len(match) == 1, f"{path} 가 fields 에 정확히 하나 있어야 한다: {[f['path'] for f in body['fields']]}"
    return match[0]


# ==========================================================================
# 1. 권한 — 새 엔드포인트도 같은 게이트 뒤에 있다 (SPEC 6.1)
# ==========================================================================

class TestTheReviewEndpointsAreBehindTheRuleManagerRole:
    @pytest.mark.parametrize("path", ["detail", "impact"])
    def test_anonymous_is_refused(self, client, store_url, path):
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        url = detail_path("d-review") if path == "detail" else impact_path("d-review")
        response = client.get(url)
        assert response.status_code == 401, response.text

    @pytest.mark.parametrize("path", ["detail", "impact"])
    def test_a_counselor_session_is_refused(self, client, store_url, path):
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_counselor(client)
        url = detail_path("d-review") if path == "detail" else impact_path("d-review")
        response = client.get(url)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    def test_an_unknown_draft_is_404_for_a_rule_manager(self, client, store_url):
        as_rule_manager(client)
        assert client.get(detail_path("nope")).status_code == 404
        assert client.get(impact_path("nope")).status_code == 404


# ==========================================================================
# 2. 4.4 #1 — 근거 원문 구간의 대조 표시
# ==========================================================================

class TestTheEvidenceHighlightPointsAtTheRightStretch:
    def test_the_segments_reassemble_into_the_source_text_byte_for_byte(self, client, store_url):
        """★ 한 글자라도 새거나 빠지면 화면이 **원문이 아닌 것**을 보여 준다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)
        assert "".join(s["text"] for s in body["source"]["segments"]) == SOURCE_TEXT

    def test_every_highlighted_segment_is_exactly_its_quote(self, client, store_url):
        """세그먼트를 `fieldPath` 별로 이어 붙이면 그 필드의 인용과 **정확히** 같아야 한다.

        여기가 이 파일의 심장이다. UTF-16 코드유닛으로 잘랐다면 `😀`·`𝕏` 뒤의 인용이
        한두 글자씩 밀려 이 단언이 깨진다.
        """
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        segments = detail(client)["source"]["segments"]

        for field_path, quote in QUOTES.items():
            joined = "".join(s["text"] for s in segments if field_path in s["fieldPaths"])
            assert joined == quote, f"{field_path}: 하이라이트가 인용과 다르다"

    def test_the_offsets_are_codepoints_not_utf16_code_units(self, client, store_url):
        """단위를 **직접** 확인한다 — 두 셈이 실제로 다른 숫자를 내는 원문이다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)

        # 전제: 이 원문에서 두 셈이 실제로 갈린다. 안 갈리면 위 테스트는 아무것도 안 잡는다.
        utf16_units = len(SOURCE_TEXT.encode("utf-16-le")) // 2
        assert utf16_units != len(SOURCE_TEXT), "BMP 밖 문자가 없다 — 이 파일이 재려던 것이 사라졌다"

        assert body["source"]["length"] == len(SOURCE_TEXT)
        spans = {s["fieldPath"]: s for s in body["spans"]}
        for field_path, quote in QUOTES.items():
            span = spans[field_path]
            assert SOURCE_TEXT[span["start"]:span["end"]] == quote
            assert span["quote"] == quote

    def test_overlapping_spans_split_into_their_own_segment(self, client, store_url):
        """겹치는 구간은 **쪼개고** `fieldPaths` 에 둘을 함께 싣는다.

        지금 데이터에 겹침이 없어도 고정한다 — 없어서 안 잡히는 것과 처리해서 안 나는
        것은 다르다 (코디네이터 지시 2026-08-14).
        """
        overlapping = {
            "/criteria/ageMin": "만 19세 이상 34세",   # 뒤쪽이 겹친다
            "/criteria/ageMax": "34세 이하",
        }
        add_draft(store_url, "d-overlap", DRAFT_PAYLOAD, quotes=overlapping)
        as_rule_manager(client)
        segments = detail(client, "d-overlap")["source"]["segments"]

        assert "".join(s["text"] for s in segments) == SOURCE_TEXT
        both = [s for s in segments if len(s["fieldPaths"]) == 2]
        assert len(both) == 1
        assert both[0]["fieldPaths"] == ["/criteria/ageMax", "/criteria/ageMin"]
        assert both[0]["text"] == "34세"
        # 그리고 각 필드의 하이라이트는 여전히 자기 인용 전체다.
        for field_path, quote in overlapping.items():
            joined = "".join(s["text"] for s in segments if field_path in s["fieldPaths"])
            assert joined == quote

    def test_a_span_contained_in_another_span_is_handled_too(self, client, store_url):
        nested = {
            "/criteria/ageMin": "신청 연령은 만 19세 이상 34세 이하로 한다",
            "/criteria/ageMax": "34세 이하",
        }
        add_draft(store_url, "d-nested", DRAFT_PAYLOAD, quotes=nested)
        as_rule_manager(client)
        segments = detail(client, "d-nested")["source"]["segments"]

        assert "".join(s["text"] for s in segments) == SOURCE_TEXT
        for field_path, quote in nested.items():
            joined = "".join(s["text"] for s in segments if field_path in s["fieldPaths"])
            assert joined == quote

    def test_a_quote_that_appears_twice_is_reported_as_ambiguous(self, client, store_url):
        """인용이 원문에 두 번 나오면 **어느 조항인지 확정되지 않았다.**

        `extraction_verify` 가 이 수를 세면서 [5단계 대조 표시가 정할 문제]로 남겨 둔
        것이다. 실패시키지 않고 **수를 보인다** — 검토자가 그 사실을 알고 봐야 한다.
        """
        add_draft(store_url, "d-ambig", DRAFT_PAYLOAD, quotes={"/criteria/ageMin": "제"})
        as_rule_manager(client)
        span = detail(client, "d-ambig")["spans"][0]
        assert span["occurrences"] == SOURCE_TEXT.count("제")
        assert span["occurrences"] > 1
        assert span["ambiguous"] is True

    def test_a_not_found_field_has_no_span_and_is_not_drawn_as_missing(self, client, store_url):
        """`not_found` 는 span 이 없어야 정상이다 (SPEC 4.2.2). 「누락」이 아니다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)

        assert "/criteria/assetMaxKRW" not in {s["fieldPath"] for s in body["spans"]}
        field = field_by_path(body, "/criteria/assetMaxKRW")
        assert field["draftSaid"] == "not_found"
        assert field["evidence"] is None
        assert field["evidenceExpected"] is False

    def test_the_source_attribution_reaches_the_review_screen(self, client, store_url):
        """계약 결정 #17 — 출처표시가 **화면까지 전달**되어야 한다. 문서에만 남으면 안 된다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        source = detail(client)["source"]
        assert "공공누리" in source["attribution"]
        assert source["sourceRef"] == "https://nhuf.molit.go.kr/"


# ==========================================================================
# 3. 4.4 #3 — 변경 전/후 diff (PR #58 의 병합 규칙을 화면이 거짓 없이 그린다)
# ==========================================================================

class TestTheDiffTellsTheTruthAboutTheMergeRules:
    def test_the_merged_payload_is_what_approval_would_write(self, client, store_url):
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)
        assert body["merged"]["id"] == "buttress_youth"
        assert body["merged"]["maxAmountKRW"] == 200_000_000
        # 표시 전용 필드는 이전 버전에서 물려받는다.
        assert body["merged"]["name"] == body["current"]["payload"]["name"]

    def test_asking_for_the_diff_writes_nothing(self, client, store_url):
        """★ 승인은 아직 일어나지 않았다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        with create_store(store_url) as store:
            before = (
                sorted(v.id for v in store.rule_versions.list()),
                len(store.approvals.list()),
                store.rule_drafts.get("d-review").status,
            )
        detail(client)
        with create_store(store_url) as store:
            after = (
                sorted(v.id for v in store.rule_versions.list()),
                len(store.approvals.list()),
                store.rule_drafts.get("d-review").status,
            )
        assert after == before

    # --- D1 ---------------------------------------------------------------
    def test_display_only_fields_are_marked_as_beyond_what_a_draft_can_say(self, client, store_url):
        """D1 — `name` · `summary` 등을 「안 바뀜」으로 그리면 **거짓말**이다.

        초안이 애초에 말할 수 없는 필드이며, 그 둘은 검토자에게 전혀 다른 사실이다.
        """
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)

        name = field_by_path(body, "/name")
        assert name["origin"] == "inherited"
        assert name["draftSaid"] == "not_applicable"
        assert name["mergeMode"] == "inherit_only"
        assert "말할 수" in name["note"]

        # 초안이 덮을 수 있는 넷은 반대쪽이다.
        assert field_by_path(body, "/maxAmountKRW")["origin"] == "draft"

    def test_the_four_overridable_fields_are_exactly_the_contract_required_set(self, client, store_url):
        """목록의 근거는 `contracts/rule_draft.schema.json` 의 `required` 다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)

        top_level = {
            f["path"] for f in body["fields"]
            if f["origin"] == "draft" and not f["path"].startswith("/criteria/")
        }
        assert top_level == {"/maxAmountKRW", "/rateRangePct", "/conditionalChecks"}
        assert any(f["path"].startswith("/criteria/") for f in body["fields"])

    # --- D2 ---------------------------------------------------------------
    def test_criteria_is_key_merge_and_the_other_two_are_whole_replacement(self, client, store_url):
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = detail(client)

        assert field_by_path(body, "/criteria/ageMin")["mergeMode"] == "key_merge"
        assert field_by_path(body, "/rateRangePct")["mergeMode"] == "replace"
        assert field_by_path(body, "/conditionalChecks")["mergeMode"] == "replace"

    def test_an_empty_conditional_checks_list_is_shown_as_wiping_the_previous_ones(self, client, store_url):
        """D2 — 초안이 `conditionalChecks: []` 를 실으면 이전 확인 항목이 **전부 사라진다.**

        `criteria` 와 의미가 다르므로 화면이 같은 방식으로 그리면 안 된다.
        """
        # 시드 8건 중 `conditionalChecks` 가 비어 있지 않은 정책을 고른다 — 비어 있는
        # 정책으로는 [전부 사라진다]가 애초에 일어나지 않아 이 테스트가 아무것도 안 잡는다.
        payload = json.loads(json.dumps(DRAFT_PAYLOAD))
        payload["policy_id"] = "seoul_youth_rent"
        payload["conditionalChecks"] = []
        quotes = {k: v for k, v in QUOTES.items() if k != "/conditionalChecks/0"}
        add_draft(store_url, "d-wipe", payload, quotes=quotes)
        as_rule_manager(client)
        body = detail(client, "d-wipe")

        previous = body["current"]["payload"].get("conditionalChecks") or []
        assert previous, "시드 규칙에 확인 항목이 없으면 이 테스트는 아무것도 잡지 않는다"

        field = field_by_path(body, "/conditionalChecks")
        assert field["changed"] is True
        assert field["after"] == []
        assert field["wipesPrevious"] is True
        assert str(len(previous)) in field["note"]

    # --- D3 ---------------------------------------------------------------
    def test_not_found_and_an_explicit_null_are_different_on_screen(self, client, store_url):
        """D3 — 하나는 [모름], 하나는 [없음] 이다. 구분해 보이지 않으면 검토자가 가를 수 없다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)

        explicit = json.loads(json.dumps(DRAFT_PAYLOAD))
        explicit["maxAmountKRW"] = None
        explicit["not_found"] = ["/criteria/assetMaxKRW"]
        quotes = {k: v for k, v in QUOTES.items() if k != "/maxAmountKRW"}
        add_draft(store_url, "d-null", explicit, quotes=quotes)

        as_rule_manager(client)
        unknown = field_by_path(detail(client), "/criteria/assetMaxKRW")
        absent = field_by_path(detail(client, "d-null"), "/maxAmountKRW")

        assert unknown["draftSaid"] == "not_found"
        assert unknown["changed"] is False          # 이전 값이 유지된다
        assert "모름" in unknown["note"]

        assert absent["draftSaid"] == "explicit_null"
        assert absent["after"] is None
        assert absent["afterPresent"] is True       # `null` 이 실제로 들어간다
        assert "없음" in absent["note"]

        assert unknown["note"] != absent["note"]

    # --- D4 ---------------------------------------------------------------
    def test_a_criteria_key_the_draft_never_mentioned_is_marked_silent(self, client, store_url):
        """D4 — 「이 조건이 폐지됐다」를 표현할 방법이 **지금 없다.**

        없는 기능을 있는 것처럼 그리지 않는다. 화면에 그 한계가 보여야 한다.
        """
        partial = json.loads(json.dumps(DRAFT_PAYLOAD))
        del partial["criteria"]["requireSME"]
        quotes = {k: v for k, v in QUOTES.items() if k != "/criteria/requireSME"}
        add_draft(store_url, "d-silent", partial, quotes=quotes)
        as_rule_manager(client)
        body = detail(client, "d-silent")

        field = field_by_path(body, "/criteria/requireSME")
        assert field["draftSaid"] == "silent"
        assert field["changed"] is False
        assert "폐지" in field["note"]
        # 그리고 그 한계는 화면 전체에도 한 번 걸린다.
        assert any("폐지" in line for line in body["limitations"])

    def test_the_limitation_is_stated_even_when_no_key_is_silent(self, client, store_url):
        """한계는 데이터에 우연히 걸릴 때만 나타나는 것이 아니다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        assert detail(client)["limitations"]

    # --- 유형 (SPEC 4.3) ---------------------------------------------------
    def test_a_policy_with_no_active_version_is_type_one(self, client, store_url):
        add_draft(store_url, "d-new", DRAFT_PAYLOAD, policy_id="brand_new_policy")
        as_rule_manager(client)
        body = detail(client, "d-new")
        assert body["current"] is None
        assert body["changeType"] == "new"

    def test_a_policy_with_an_active_version_is_type_two(self, client, store_url):
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        assert detail(client)["changeType"] == "requirement_change"


# ==========================================================================
# 4. 4.4 #2 — 승인 시 판정이 어떻게 바뀌는가 (회귀 사례)
# ==========================================================================

class TestTheImpactIsShownWithRealCases:
    def test_the_population_is_the_contract_profile_set(self, client, store_url):
        """SPEC 9.2.2 · 7.1 — 실사용 프로필을 쓰지 않는다. 모집단은 계약 파일이다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        contract = json.loads(REGRESSION_PROFILES.read_text(encoding="utf-8"))

        body = client.get(impact_path("d-review")).json()
        assert body["profileSetVersion"] == contract["setVersion"]
        assert [p["id"] for p in body["profiles"]] == [p["id"] for p in contract["profiles"]]

    def test_every_profile_carries_the_axis_it_probes(self, client, store_url):
        """[무엇을 재는 프로필인가]가 없으면 12줄의 표는 판단 근거가 못 된다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        contract = json.loads(REGRESSION_PROFILES.read_text(encoding="utf-8"))
        body = client.get(impact_path("d-review")).json()
        for entry in body["profiles"]:
            assert entry["axis"] == contract["axes"][entry["id"]]

    def test_computing_the_impact_touches_nothing_in_the_store(self, client, store_url):
        """★ 승인은 아직 일어나지 않았다. 저장소가 한 바이트도 움직이면 안 된다."""
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)

        def snapshot():
            with create_store(store_url) as store:
                return (
                    sorted((v.id, v.status, str(v.effective_to)) for v in store.rule_versions.list()),
                    sorted(r.id for r in store.approvals.list()),
                    sorted((d.id, d.status) for d in store.rule_drafts.list()),
                    len(store.audit.list()),
                )

        before = snapshot()
        assert client.get(impact_path("d-review")).status_code == 200
        assert snapshot() == before

    def test_a_draft_that_moves_the_verdict_reports_which_profiles_moved(self, client, store_url):
        """승인 **전/후** 판정을 각각 계산해 달라진 프로필과 무엇이 달라졌는지를 낸다."""
        widened = json.loads(json.dumps(DRAFT_PAYLOAD))
        widened["criteria"]["ageMax"] = 44          # 34 -> 44: 연령 상한 초과 프로필이 뒤집힌다
        add_draft(store_url, "d-wide", widened)
        as_rule_manager(client)

        body = client.get(impact_path("d-wide")).json()
        changed = {p["id"] for p in body["profiles"] if p["changed"]}
        assert "age_over_max" in changed, "연령 상한을 10살 늘렸는데 아무 프로필도 안 움직였다"
        assert body["changedCount"] == len(changed)

        entry = next(p for p in body["profiles"] if p["id"] == "age_over_max")
        assert entry["policyBefore"]["status"] == "ineligible"
        assert entry["policyAfter"]["status"] in ("eligible", "conditional")
        assert any(c["path"].startswith("/policies/") for c in entry["changes"])

    def test_a_draft_that_changes_nothing_says_so(self, client, store_url):
        """시드와 같은 값이면 달라지는 프로필이 0이어야 한다 — 그것도 판단 근거다."""
        as_rule_manager(client)
        with create_store(store_url) as store:
            current = next(
                v for v in store.rule_versions.active(T0) if v.policy_id == "buttress_youth"
            )
        same = json.loads(json.dumps(DRAFT_PAYLOAD))
        same["criteria"] = dict(current.payload["criteria"])
        same["criteria"].pop("assetMaxKRW", None)
        same["criteria"]["assetMaxKRW"] = None
        same["maxAmountKRW"] = current.payload["maxAmountKRW"]
        same["rateRangePct"] = list(current.payload["rateRangePct"])
        same["conditionalChecks"] = list(current.payload.get("conditionalChecks") or [])
        quotes = {k: v for k, v in QUOTES.items() if k != "/conditionalChecks/0"}
        add_draft(store_url, "d-same", same, quotes=quotes)

        body = client.get(impact_path("d-same")).json()
        assert body["changedCount"] == 0
        assert all(not p["changed"] for p in body["profiles"])

    def test_a_profile_whose_verdict_cannot_be_computed_is_reported_not_hidden(self, client, store_url):
        """`unknown_region` 은 `analyze` 가 `ValueError` 를 던지는 축이다 (SPEC 9.2.2).

        그 한 건 때문에 나머지 11건의 영향 사례가 사라지면 화면이 판단 근거를 잃는다.
        숨기지도 않는다 — 못 쟀다는 사실을 적는다.
        """
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = client.get(impact_path("d-review")).json()

        entry = next(p for p in body["profiles"] if p["id"] == "unknown_region")
        assert entry["errorBefore"] is not None
        assert entry["errorAfter"] == entry["errorBefore"]
        assert entry["changed"] is False
        assert len(body["profiles"]) == len(
            json.loads(REGRESSION_PROFILES.read_text(encoding="utf-8"))["profiles"]
        )

    def test_the_impact_is_computed_against_the_merged_payload_not_the_raw_draft(self, client, store_url):
        """병합 규칙을 지나지 않은 초안으로 재면 화면과 승인 결과가 어긋난다.

        `not_found` 필드는 이전 값이 유지되므로, 그 유지가 [영향 없음]으로 나와야 한다.
        """
        add_draft(store_url, "d-review", DRAFT_PAYLOAD)
        as_rule_manager(client)
        body = client.get(impact_path("d-review")).json()
        assert body["mergedPayload"] == detail(client)["merged"]


# ==========================================================================
# 5. 승인 없이는 판정이 바뀌지 않는다 (SPEC 10.2 5단계 · 원칙 2)
# ==========================================================================

class TestNoVerdictMovesWithoutApproval:
    def test_reading_the_whole_review_screen_leaves_analyze_byte_identical(self, client, store_url):
        add_draft(store_url, "d-wide", DRAFT_PAYLOAD)
        as_rule_manager(client)
        profile = json.loads(REGRESSION_PROFILES.read_text(encoding="utf-8"))["profiles"][0]["profile"]

        before = client.post("/api/analyze", json=profile).json()
        client.get("/api/admin/drafts")
        detail(client, "d-wide")
        client.get(impact_path("d-wide"))
        after = client.post("/api/analyze", json=profile).json()
        assert after == before
