"""SPEC 6.4 C — 이상 신고가 **두 화면**에 실제로 서는가 (소유자: `api`).

6.4 는 화면 둘을 함께 요구한다. 하나만 있으면 경로가 끊긴다 —

    1. **판정 화면(상담원 모드)** — 정책·시세 **항목별로** 「이상 신고」. 익명에는 없다
    2. **규칙 관리 화면** — 큐에 **별도 유형**으로 쌓이고 추출 draft 와 눈으로 구분된다

## 판정 화면은 **실행해서** 본다 (계약 결정 #36 · SPEC 9.1.1)

「판정 기준은 구현이 아니라 출력이다」. 파일을 파싱해 `if (session)` 같은 문자열이
있는지 세는 검사는 *구현*을 보는 것이고, 그것을 만족이라고 부르면 검사한 척이 된다.
그래서 `frontend/app.js` 를 node 로 올려 **함수를 실제로 불러** 출력을 본다.

`admin/app.js` 는 하네스가 없다(js_runner 는 `frontend/` 만 올린다). 그쪽은 기존
`test_admin_screen.py` 와 같은 방식 — 마크업과 소스에 대한 정적 단언 — 을 쓴다.

## 개인정보 (SPEC 7.1)

대상은 구조로 닫았다(`test_report_api.py`). 화면 쪽에서 고정하는 것은 둘이다 —
**대상을 자유 텍스트로 묻지 않는 것**(입력칸이 아니라 목록이다)과 **경고 문구가 실제로
화면에 있는 것**. 문구는 규율이지 구조가 아니며, 그 한계는 PR 에 적힌다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from js_runner import run_js

from home_compass.store.models import POLICY_REPORT_FIELDS, REGION_FACT_FIELDS

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_DIR = REPO_ROOT / "admin"
FRONTEND_DIR = REPO_ROOT / "frontend"

ADMIN_JS = (ADMIN_DIR / "app.js").read_text(encoding="utf-8")
ADMIN_HTML = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
FRONTEND_HTML = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

#: 판정 응답의 `Policy` 한 건과 같은 모양. 화면이 그리는 것이 이것이므로 신고 가능한
#: 항목도 여기서 나온다 — 목록을 테스트에 손으로 적으면 그것이 네 번째 사본이 된다.
POLICY = {
    "id": "buttress_youth", "name": "청년전용 버팀목전세자금", "category": "전세자금",
    "status": "eligible", "reasons": ["연령 요건 충족"], "maxAmountKRW": 200_000_000,
    "rateRangePct": [1.5, 2.9], "source": "주택도시기금", "disclaimer": "예시 수치",
}

REGION = {
    "code": "11440", "name": "서울 마포구", "jeonseMedianKRW": 280_000_000,
    "monthlyDepositKRW": 20_000_000, "monthlyRentKRW": 850_000,
    "maintenanceFeeKRW": 90_000, "jeonseRatioPct": 71.2, "conversionRatePct": 5.5,
    "marketRisk": "low", "guaranteeAvailable": True, "source": "프로토타입 예시",
}


def call(body: str, *, authenticated: bool) -> object:
    """`app.js` 를 올린 뒤 세션 상태를 세워 놓고 `body` 를 실행한다."""
    session = json.dumps(
        {"authenticated": authenticated, "username": "counselor",
         "role": "counselor" if authenticated else None, "csrfToken": "t"}
    )
    return run_js(
        f"var C = globalThis.HomeCompass;\n"
        f"C.STATE.session = {session};\n"
        f"{body}",
        include_screen=True,
    )


# ==========================================================================
# 1. 판정 화면 — 익명에는 없다 (SPEC 6.4)
# ==========================================================================

class TestTheReportControlOnlyExistsForSignedInStaff:
    def test_an_anonymous_screen_draws_nothing(self):
        """★ 「익명에는 없다」 — 빈 문자열이어야 한다. 숨긴 버튼이 아니라 없는 버튼이다."""
        assert call("return C.reportButtonHTML('policy', 'p1', '제도');",
                    authenticated=False) == ""

    def test_a_counselor_screen_draws_the_button(self):
        html = call("return C.reportButtonHTML('policy', 'buttress_youth', '청년전용');",
                    authenticated=True)
        assert "이상 신고" in html
        assert 'data-report-kind="policy"' in html
        assert 'data-report-id="buttress_youth"' in html

    def test_can_report_follows_the_session_not_the_role(self):
        """역할로 분기하지 않는다 — 상담원도 규칙관리자도 신고할 수 있다 (SPEC 6.1 6.4)."""
        assert call("return C.canReport();", authenticated=True) is True
        assert call("return C.canReport();", authenticated=False) is False

    def test_the_policy_list_carries_the_button_only_when_signed_in(self):
        """카드 렌더 전체를 통과시켜 본다 — 함수 하나가 맞아도 배선이 틀리면 소용없다."""
        body = (
            "var doc = { policyList: '' };\n"
            "globalThis.document = { querySelector: function () {\n"
            "  return { set innerHTML(v) { doc.policyList = v; },\n"
            "           get innerHTML() { return doc.policyList; } }; } };\n"
            "C.STATE.policyFilter = 'all';\n"
            f"C.renderPolicies([{json.dumps(POLICY)}]);\n"
            "return doc.policyList;"
        )
        assert "data-report-kind" in call(body, authenticated=True)
        assert "data-report-kind" not in call(body, authenticated=False)


# ==========================================================================
# 2. ★ 대상은 목록이지 자유 텍스트가 아니다 (SPEC 7.1 · 계약 결정 #38)
# ==========================================================================

class TestTheTargetIsChosenNotTyped:
    def test_the_policy_items_come_from_the_response_object(self):
        """★ 화면이 목록을 **들고 있지 않다.** 방금 그린 응답에서 만든다.

        손으로 적으면 백엔드 허용 목록에 이어 사본이 하나 더 생기고, 스키마가 바뀔 때
        화면에는 있는데 신고는 400 이 되는 상태가 조용히 만들어진다.
        """
        fields = call(f"return C.reportableFields('policy', {json.dumps(POLICY)});",
                      authenticated=True)
        assert set(fields) == set(POLICY_REPORT_FIELDS)

    def test_the_market_items_come_from_the_region_object(self):
        fields = call(f"return C.reportableFields('region', {json.dumps(REGION)});",
                      authenticated=True)
        assert set(fields) == set(REGION_FACT_FIELDS)

    def test_the_dialog_asks_for_the_item_with_a_select_not_an_input(self):
        """자유 입력 칸이 **사유 하나뿐**이어야 한다. 대상 칸이 텍스트면 그것이 두 번째다."""
        assert re.search(r'<select[^>]*id="reportField"', FRONTEND_HTML)
        assert not re.search(r'<input[^>]*id="reportField"', FRONTEND_HTML)

    def test_the_dialog_has_exactly_one_free_text_field(self):
        panel = re.search(r'<div class="report-modal".*?</div>', FRONTEND_HTML, re.S)
        assert panel is not None, "신고 대화상자가 없다"
        assert len(re.findall(r"<textarea", panel.group(0))) == 1
        assert not re.findall(r'<input[^>]*type="text"', panel.group(0))


# ==========================================================================
# 3. ★ 개인정보 문구 (SPEC 7.1 — 화면에 **명시**한다)
# ==========================================================================

class TestThePrivacyNoticeIsOnTheScreen:
    def test_the_notice_names_customer_personal_data(self):
        notice = call("return C.REPORT_PRIVACY_NOTICE;", authenticated=True)
        assert "개인정보" in notice

    def test_the_notice_is_wired_into_the_dialog(self):
        """상수만 있고 화면에 붙지 않으면 아무도 읽지 않는다."""
        source = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
        assert "reportPrivacy" in source and "REPORT_PRIVACY_NOTICE" in source
        assert 'id="reportPrivacy"' in FRONTEND_HTML

    def test_the_notice_admits_the_record_cannot_be_undone(self):
        """★ 이 문구는 구조가 아니라 규율이다. 그러면 최소한 **사실**을 말해야 한다 —
        감사기록은 append-only 이고 지우는 경로가 없다 (SPEC 7.1)."""
        notice = call("return C.REPORT_PRIVACY_NOTICE;", authenticated=True)
        assert "감사기록" in notice and "지울 수 없" in notice


# ==========================================================================
# 4. 규칙 관리 화면 — 별도 유형 (SPEC 6.4 · 10.2 6-A)
# ==========================================================================

class TestTheAdminQueueKeepsTheTwoTypesApart:
    def test_the_queue_has_a_separate_list_for_reports(self):
        assert 'id="reportList"' in ADMIN_HTML
        assert 'id="queueList"' in ADMIN_HTML

    def test_the_screen_reads_the_report_queue_endpoint(self):
        assert "/api/admin/reports" in ADMIN_JS

    def test_report_items_carry_a_type_chip_the_draft_items_do_not(self):
        """눈으로 구분된다 — 항목마다 「현장 신고」 칩이 앞에 선다. 색만으로 나르지 않는다."""
        block = re.search(r"function renderReports\(\).*?\n  \}", ADMIN_JS, re.S)
        assert block is not None, "renderReports 가 없다"
        assert "현장 신고" in block.group(0)

        draft_block = re.search(r"function renderQueue\(\).*?\n  \}", ADMIN_JS, re.S)
        assert draft_block is not None
        assert "현장 신고" not in draft_block.group(0), "초안 목록이 신고를 그린다"

    def test_the_draft_detail_shows_the_attached_reports(self):
        """SPEC 6.4 — 「검토자는 기계가 이렇게 추출했고, 현장에서는 이런 문제가 보고됐다를 함께 본다」."""
        assert "renderDraftReports" in ADMIN_JS
        assert 'id="draftReports"' in ADMIN_HTML
        assert re.search(r"renderDraftReports\(detail\.reports\)", ADMIN_JS)

    def test_the_merge_rule_is_not_re_implemented_on_the_screen(self):
        """★ 병합은 서버가 계산한다. 화면이 정책 id 로 직접 조인하면 규칙이 두 벌이 된다."""
        assert "mergedDraftIds" in ADMIN_JS
        block = re.search(r"function renderReports\(\).*?\n  \}", ADMIN_JS, re.S)
        assert "policyId" not in block.group(0), "화면이 정책 id 로 직접 병합을 계산한다"

    def test_the_screen_says_what_happens_to_a_report_with_no_draft(self):
        """「신고만 있고 draft 가 없으면 신고 단독 항목으로 큐에 남는다」 (SPEC 6.4)."""
        assert "재추출" in ADMIN_JS


# ==========================================================================
# 5. ★ 없는 기능을 그리지 않는다 (코디네이터 조건 ①)
# ==========================================================================
#
# SPEC 6.4 는 신고를 받은 뒤 규칙관리자가 「수동으로 입력하거나 재추출을 지시한다」고만
# 적었다. **닫는 동작을 어느 단계에도 배정하지 않았다.** 그래서 신고는 이 큐에 계속
# 쌓인다. 그 사실을 화면이 [처리 완료] 버튼으로 덮으면, 누른 사람은 무언가 일어났다고
# 믿지만 실제로는 아무 일도 일어나지 않는다.

class TestNoScreenPretendsToCloseAReport:
    @pytest.mark.parametrize("name", ["app.js", "index.html"])
    def test_there_is_no_resolve_button(self, name):
        # 파일 내용을 파라미터로 넘기지 않는다 — pytest 가 그것을 테스트 id 로 만들고
        # `PYTEST_CURRENT_TEST` 환경변수 길이 상한(32767)에 걸려 테스트가 아니라
        # 하네스가 죽는다. 이름만 넘기고 내용은 여기서 읽는다.
        source = (ADMIN_DIR / name).read_text(encoding="utf-8")
        for token in ("처리 완료", "신고 닫기", "reportClose", "resolveReport"):
            assert token not in source, f"admin/{name} 에 없는 기능이 그려져 있다: {token}"

    def test_no_screen_calls_a_status_changing_report_endpoint(self):
        assert not re.search(r"/api/(admin/)?reports/[^']*'", ADMIN_JS)

    def test_the_counselor_screen_says_the_rule_does_not_change(self):
        """★ 「접수됐습니다」로 끝내면 상담원은 고쳐진 것으로 읽는다.
        신고는 제안이지 변경이 아니라는 것이 화면에 남아야 한다 (SPEC 6.4 SoD)."""
        source = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
        block = re.search(r"function submitReport\(e\).*?\n  \}", source, re.S)
        assert block is not None, "submitReport 가 없다"
        assert "규칙은 바뀌지 않습니다" in block.group(0)
