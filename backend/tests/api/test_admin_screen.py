"""SPEC 6.2 · 4.4 — 규칙 관리 화면이 실제로 서는가 (소유자: `api`).

두 가지를 고정한다.

    1. **동일 오리진 정적 서빙.** `admin` 은 `api` 와 같은 오리진의 `/admin` 에 선다.
       별도 포트를 만들면 쿠키 세션(6.3)이 오리진을 넘어야 하고, 그 순간 CORS 와 CSRF 를
       새로 설계하게 된다. 6.2 가 「동일 오리진」이라고 적은 이유가 그것이다.

    2. ★ **화면이 원문 오프셋 산술을 하지 않는다** (파수병).

## 파수병이 무엇을 막는가 — 그리고 무엇을 막지 않는가

SPEC 4.2.1 은 span 오프셋을 **유니코드 코드포인트**로 못박았고, JS 문자열 인덱스는
**UTF-16 코드유닛**이다. 화면이 직접 자르면 BMP 밖 문자에서 조용히 어긋나고, 검토자는
엉뚱한 조항을 근거로 보고 승인한다. 그래서 자르기는 서버가 하고(`source.segments`)
이 파수병이 그 규율이 되살아나 무너지는 것을 막는다.

**범위를 좁혔다.** `.slice(` 를 통째로 금지하면 배열 조작까지 막힌다 — 막으려는 것은
문자열 오프셋 산술이지 배열이 아니다 (코디네이터 지시 2026-08-14). 그래서 둘로 나눈다.

    (a) **문자열에만 뜻이 있는 연산**은 무조건 금지한다.
        `substring` · `substr` · `charAt` · `charCodeAt` · `codePointAt` ·
        `String.fromCharCode` · `String.fromCodePoint` · `normalize` ·
        `split('')`(코드유닛 배열) — 배열에는 이런 메서드가 없거나 뜻이 다르다.

    (b) **`slice` 는 인자에 span 오프셋이 실릴 때만** 금지한다.
        `arr.slice(0, 5)` 같은 배열 조작은 통과하고, `text.slice(span.start, span.end)`
        처럼 `start`/`end` 를 태우는 호출만 걸린다. 그것이 정확히 [span 으로 자르기] 다.

## 파수병이 실제로 잡는지 확인한다 (프로브)

이 프로젝트에서 [규칙이 표에만 남고 아무것도 안 잡는] 일이 반복됐다. 그래서 같은 검사
함수에 **위반을 일부러 먹여** 걸리는 것을 본다 — 실제 파일이 깨끗한 것과 검사기가
작동하는 것은 **다른 사실**이며, 둘 다 확인해야 이 파일이 의미를 갖는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from firsthome import main as main_module
from firsthome.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_DIR = REPO_ROOT / "admin"
APP_JS = ADMIN_DIR / "app.js"


# ==========================================================================
# 1. 동일 오리진 정적 서빙 (SPEC 6.2)
# ==========================================================================

@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


class TestTheAdminScreenIsServedFromTheSameOrigin:
    def test_the_admin_directory_is_wired_to_the_app(self):
        assert main_module.ADMIN_DIR == ADMIN_DIR
        assert ADMIN_DIR.is_dir()

    def test_admin_serves_its_index(self, client):
        response = client.get("/admin/", follow_redirects=True)
        assert response.status_code == 200, response.text
        assert "규칙 검토·승인" in response.text

    def test_the_bare_path_reaches_the_index_too(self, client):
        response = client.get("/admin", follow_redirects=True)
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("asset", ["styles.css", "app.js"])
    def test_the_static_assets_are_served(self, client, asset):
        response = client.get(f"/admin/{asset}")
        assert response.status_code == 200, response.text
        assert response.content

    def test_the_admin_mount_comes_before_the_frontend_mount(self):
        """순서가 곧 동작이다 — `/` 를 먼저 마운트하면 그것이 `/admin` 을 먹는다."""
        names = [getattr(route, "name", "") for route in app.routes]
        assert "admin" in names and "frontend" in names
        assert names.index("admin") < names.index("frontend")

    def test_the_frontend_is_still_served_at_the_root(self, client):
        """`web` 을 밀어내지 않았다 — 6단계 소유이며 한 글자도 건드리지 않았다."""
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200, response.text
        assert "Home_Compass" in response.text

    def test_the_api_still_wins_over_the_static_mounts(self, client):
        assert client.get("/api/health").status_code == 200

    def test_the_screen_does_not_load_anything_from_the_network(self, client):
        """오프라인 기동 (D-8 · SPEC 6.2) — CDN · 원격 폰트 · 외부 스크립트 금지.

        ★ 문자열 `http://` 만 세지 않는다. 파비콘의 `data:` URI 안에 SVG **네임스페이스**
          (`xmlns='http://www.w3.org/2000/svg'`)가 들어 있는데 그것은 네트워크 요청이
          아니다. 그것까지 잡으면 이 검사는 [고치는 방법이 파비콘을 지우는 것]이 되고,
          그러면 검사가 무엇을 지키는지가 흐려진다. **자원을 가리키는 속성**만 본다.
        """
        html = client.get("/admin/", follow_redirects=True).text
        remote = re.findall(r"(?:src|href)\s*=\s*[\"'](//|https?://)", html)
        assert not remote, f"외부 자원을 참조한다: {remote}"
        for token in ("@import", "unpkg", "jsdelivr", "googleapis", "cdnjs"):
            assert token not in html, f"외부 자원을 참조한다: {token}"

    def test_the_stylesheet_and_script_do_not_reach_out_either(self, client):
        for asset in ("styles.css", "app.js"):
            body = client.get(f"/admin/{asset}").text
            remote = re.findall(r"(?:url\(|import\s+|from\s+)[\"']?(?://|https?://)", body)
            assert not remote, f"{asset} 가 외부 자원을 참조한다: {remote}"


# ==========================================================================
# 2. 파수병 — 화면이 원문 오프셋 산술을 하지 않는다
# ==========================================================================

#: (a) 문자열에만 뜻이 있는 연산. 배열에는 없거나 뜻이 다르므로 **무조건** 금지한다.
_STRING_ONLY_OPERATIONS = (
    r"\.substring\s*\(",
    r"\.substr\s*\(",
    r"\.charAt\s*\(",
    r"\.charCodeAt\s*\(",
    r"\.codePointAt\s*\(",
    r"String\s*\.\s*fromCharCode",
    r"String\s*\.\s*fromCodePoint",
    r"\.normalize\s*\(",
    r"\.split\s*\(\s*(''|\"\")\s*\)",
)

#: (b) `slice` 는 **span 오프셋을 태울 때만** 금지한다. 배열 조작은 통과한다.
#:     `text.slice(span.start, span.end)` · `cps.slice(start, end)` 가 여기 걸린다.
_SLICE_BY_OFFSET = r"\.slice\s*\([^)]*\b(start|end)\b[^)]*\)"

FORBIDDEN_PATTERNS = _STRING_ONLY_OPERATIONS + (_SLICE_BY_OFFSET,)


def offset_arithmetic_violations(source: str) -> list[str]:
    """이 소스에 남아 있는 [원문 오프셋 산술] 의 흔적. 없으면 빈 목록.

    **검사 대상은 소스 전체다.** 주석 안이라도 걸린다 — 주석에 적힌 코드는 다음 사람이
    복사해 살려 내는 자리이며, 여기서 예외를 두면 파수병이 [주석으로 옮기면 통과하는]
    검사가 된다. 이 파일과 `admin/app.js` 의 설명문은 그래서 금지 토큰을 **코드 형태로
    적지 않는다** (`substring(` 이 아니라 `substring` 처럼 괄호 없이 적는다).
    """
    found = []
    for pattern in FORBIDDEN_PATTERNS:
        for match in re.finditer(pattern, source):
            line = source.count("\n", 0, match.start()) + 1
            found.append(f"{line}행: {match.group(0)}")
    return sorted(found)


class TestTheScreenNeverDoesOffsetArithmeticOnTheSourceText:
    def test_the_real_file_is_clean(self):
        violations = offset_arithmetic_violations(APP_JS.read_text(encoding="utf-8"))
        assert not violations, (
            "admin/app.js 가 원문 오프셋 산술을 한다 (SPEC 4.2.1). 자르기는 서버가 하고 "
            f"화면은 `source.segments` 를 순서대로 그리기만 해야 한다: {violations}"
        )

    def test_the_screen_actually_consumes_the_server_side_segments(self):
        """깨끗한 것만으로는 부족하다 — **세그먼트를 실제로 쓰고 있어야** 규율이 성립한다."""
        source = APP_JS.read_text(encoding="utf-8")
        assert "segments" in source and "fieldPaths" in source

    # --- 프로브: 검사기가 실제로 잡는가 --------------------------------
    @pytest.mark.parametrize("probe", [
        "var q = text.substring(span.start, span.end);",
        "var q = text.substr(span.start, 5);",
        "var c = text.charAt(3);",
        "var c = text.charCodeAt(3);",
        "var c = text.codePointAt(3);",
        "var s = String.fromCharCode(0x1F600);",
        "var s = String.fromCodePoint(0x1F600);",
        "var n = text.normalize('NFC');",
        "var units = text.split('');",
        'var units = text.split("");',
        "var q = text.slice(span.start, span.end);",
        "var q = cps.slice(start, end).join('');",
    ])
    def test_a_planted_violation_is_caught(self, probe):
        """★ 규칙이 표에만 남지 않게 한다 — 위반을 먹여 걸리는 것을 본다."""
        assert offset_arithmetic_violations(probe), f"파수병이 놓쳤다: {probe}"

    def test_a_planted_violation_is_caught_inside_the_real_file_too(self):
        """파일을 읽는 경로까지 확인한다. 검사 함수만 맞고 배선이 틀리면 소용없다."""
        contaminated = APP_JS.read_text(encoding="utf-8") + "\nvar q = text.substring(a, b);\n"
        assert offset_arithmetic_violations(contaminated)

    @pytest.mark.parametrize("allowed", [
        "var head = items.slice(0, 5);",
        "var copy = list.slice();",
        "var rest = rows.slice(1);",
        "var parts = iso.split('T');",
        "var joined = paths.join(' ');",
    ])
    def test_ordinary_array_work_is_not_blocked(self, allowed):
        """범위를 좁힌 것이 실제로 좁혀졌는가 — 배열 조작까지 막으면 규칙이 과녁을 벗어난다."""
        assert not offset_arithmetic_violations(allowed), f"배열 조작을 잘못 막았다: {allowed}"


# ==========================================================================
# 3. 반려 사유 — 화면도 막는다 (SPEC 10.2 5단계)
# ==========================================================================
#
# 서버가 400 을, 저장소의 CHECK 제약이 그 뒤를 받친다. 화면은 **세 번째 겹**이며
# 앞의 둘을 대신하지 않는다. 여기서 고정하는 것은 [빈 사유로는 버튼이 눌리지 않는다] 다.

class TestTheRejectButtonIsBlockedUntilAReasonIsTyped:
    def test_the_markup_starts_with_the_reject_button_disabled(self):
        html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
        button = re.search(r"<button[^>]*id=\"btnReject\"[^>]*>", html)
        assert button is not None, "반려 버튼이 없다"
        assert "disabled" in button.group(0), "반려 버튼이 처음부터 눌리는 상태다"

    def test_the_reason_field_is_marked_required(self):
        html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
        field = re.search(r"<input[^>]*id=\"rejectReason\"[^>]*>", html)
        assert field is not None and "required" in field.group(0)

    def test_the_script_re_enables_it_only_from_the_typed_reason(self):
        """빈 문자열·공백만으로는 열리지 않아야 한다 — `trim()` 이 그 자리에 있다.

        ★ **`disabled` 를 세우는 자리가 옮겨졌다** (2026-08-16). 반려를 막을 수 있는 것이
          사유 유무와 **초안 상태** 둘이 됐고(아래 4번), 두 자리에서 쓰면 나중에 갈린다.
          그래서 사유를 읽는 곳과 버튼을 닫는 곳을 나눠서 본다 — 성질은 그대로다.
        """
        source = APP_JS.read_text(encoding="utf-8")
        reads = re.search(r"function syncRejectButton\(\)\s*\{.*?\n  \}", source, re.S)
        assert reads is not None, "syncRejectButton 이 없다"
        assert "trim()" in reads.group(0), "사유를 공백까지 다듬어 읽지 않는다"
        closes = re.search(r"function syncDecisionButtons\(\)\s*\{.*?\n  \}", source, re.S)
        assert closes is not None, "syncDecisionButtons 가 없다"
        assert "disabled" in closes.group(0)
        assert "trim()" in closes.group(0), "버튼을 닫는 자리가 사유를 보지 않는다"


# ==========================================================================
# 4. 추출 실패 초안 — 사유를 그리고, 결정 버튼을 닫는다
# ==========================================================================
#
# 재리허설이 브라우저로 관측한 결함 둘이다 (PR #99).
#
#   ① 서버는 `failureReason` 을 큐(`DraftRef`)와 상세 양쪽에 싣는데 화면이 안 그렸다.
#      규칙관리자는 `extraction_failed` 라는 **상태 문자열만** 보고, 재추출을 지시할지
#      수동 입력할지 정할 근거가 없었다.
#   ② 실패 초안의 검토 화면이 **결정 버튼을 열어 뒀다.** 누르면 서버가 409 로 거절한다.
#      「눌리는데 거절되는 버튼」은 무엇이 가능한지 화면이 거짓말하는 것이다.
#
# ★ 서버의 규칙은 `extraction_failed` 가 아니라 **`pending` 이 아니면 전부**다
#   (`_pending_draft_or_error`). 승인·반려 **둘 다** 그 규칙을 지나므로 화면도 둘 다 닫는다.
#   실패 상태 하나만 특수 분기로 막으면 이미 승인된 초안에서 같은 거짓말이 남는다.

class TestAFailedDraftShowsItsReasonAndCannotBeDecided:

    # --- ① 사유를 그린다 -----------------------------------------------
    def test_the_queue_draws_the_failure_reason(self):
        source = APP_JS.read_text(encoding="utf-8")
        block = re.search(r"function renderQueue\(\)\s*\{.*?\n  \}", source, re.S)
        assert block is not None, "renderQueue 가 없다"
        assert "failureReason" in block.group(0), (
            "큐가 실패 사유를 그리지 않는다 — 상태 문자열만 보이면 다음 행동을 정할 수 없다")

    def test_the_review_pane_draws_the_failure_reason(self):
        source = APP_JS.read_text(encoding="utf-8")
        block = re.search(r"function renderFailure\(\w+\)\s*\{.*?\n  \}", source, re.S)
        assert block is not None, "renderFailure 가 없다"
        assert "failureReason" in block.group(0)

    def test_the_markup_has_a_failure_box_that_starts_hidden(self):
        """실패가 아닐 때 보이면 안 된다 — 초안 대부분은 `pending` 이다."""
        html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
        box = re.search(r"<[a-z]+[^>]*id=\"failureBox\"[^>]*>", html)
        assert box is not None, "failureBox 가 없다"
        assert "hidden" in box.group(0), "실패 상자가 처음부터 보이는 상태다"

    # --- ② 결정 버튼을 닫는다 -------------------------------------------
    def test_the_screen_uses_the_same_rule_as_the_server(self):
        """★ `extraction_failed` 특수 분기가 아니라 **`pending` 이 아니면 닫는다**.

        서버의 `_pending_draft_or_error` 가 그 규칙이고 승인·반려가 둘 다 그것을 지난다.
        """
        source = APP_JS.read_text(encoding="utf-8")
        block = re.search(r"function decisionBlock\(\w+\)\s*\{.*?\n  \}", source, re.S)
        assert block is not None, "decisionBlock 이 없다"
        assert "'pending'" in block.group(0), (
            "결정 차단이 pending 을 기준으로 하지 않는다 — 상태 하나만 막으면 "
            "이미 승인된 초안에서 같은 거짓말이 남는다")

    @pytest.mark.parametrize("button", ["btnApprove", "btnReject"])
    def test_both_decision_buttons_are_closed_by_the_block(self, button):
        """반려도 409 를 받는다 — 서버는 승인·반려를 같은 관문에 태운다."""
        source = APP_JS.read_text(encoding="utf-8")
        block = re.search(r"function syncDecisionButtons\(\)\s*\{.*?\n  \}", source, re.S)
        assert block is not None, "syncDecisionButtons 가 없다"
        assert button in block.group(0), f"{button} 이 차단을 따르지 않는다"

    def test_the_screen_still_shows_the_raw_code(self):
        """옮긴 말만 남기면 개발자가 재현할 수 없다 — 원래 코드도 함께 보인다."""
        source = APP_JS.read_text(encoding="utf-8")
        block = re.search(r"function renderFailure\(\w+\)\s*\{.*?\n  \}", source, re.S)
        assert block is not None
        assert re.search(r"\.code\b", block.group(0)), "사유의 원래 코드를 화면에 싣지 않는다"


# --- ③ 손으로 쓴 사본이 조용히 낡지 않는다 ---------------------------------
#
# 사유 코드를 사람 말로 옮기기로 했다 (규칙관리자는 간헐 업무자다 — SPEC 7.3).
# 그 표는 `admin/app.js` 안의 **손으로 쓴 사본**이고, 이 저장소가 반복해서 당한 것이
# 정확히 그 부류다(낡은 산출물 · 없는 필드에 0.0% · 시점을 박은 주석). 그래서 서버의
# 어휘와 **정확히** 같은지 고정한다.
#
# ★ 검사 함수를 밖으로 뺀 이유는 **프로브 때문**이다. 실제 파일이 깨끗한 것과 검사기가
#   작동하는 것은 다른 사실이고, 이 파일의 파수병 1번이 이미 그렇게 하고 있다.

def label_table_drift(source: str, server_codes: set[str]) -> dict[str, list[str]]:
    """화면의 사유 어휘와 서버 어휘의 어긋남. 없으면 두 목록이 다 비어 있다."""
    block = re.search(r"var REJECTION_LABEL = \{(.*?)\n  \};", source, re.S)
    if block is None:
        return {"missing": sorted(server_codes), "unknown": ["REJECTION_LABEL 이 없다"]}
    keys = set(re.findall(r"^\s+([a-z_]+):", block.group(1), re.M))
    return {"missing": sorted(server_codes - keys), "unknown": sorted(keys - server_codes)}


class TestTheFailureVocabularyOnScreenMatchesTheServer:
    @staticmethod
    def _server_codes() -> set[str]:
        from firsthome.ingest.extraction_verify import ALL_CODES

        return set(ALL_CODES)

    def test_the_real_file_matches(self):
        drift = label_table_drift(APP_JS.read_text(encoding="utf-8"), self._server_codes())
        assert drift == {"missing": [], "unknown": []}, (
            f"화면의 사유 어휘가 서버와 어긋난다: {drift}")

    def test_a_missing_code_is_caught(self):
        source = APP_JS.read_text(encoding="utf-8")
        drift = label_table_drift(source, self._server_codes() | {"code_added_later"})
        assert drift["missing"] == ["code_added_later"], (
            f"서버가 코드를 늘렸는데 놓쳤다: {drift}")

    def test_a_stale_code_is_caught(self):
        source = APP_JS.read_text(encoding="utf-8")
        drift = label_table_drift(source, self._server_codes() - {"span_not_in_text"})
        assert drift["unknown"] == ["span_not_in_text"], (
            f"서버가 코드를 지웠는데 화면에 남은 것을 못 잡았다: {drift}")

    def test_a_table_that_vanished_is_caught(self):
        drift = label_table_drift("var nothing = 1;\n", self._server_codes())
        assert drift["unknown"], "표가 통째로 사라진 것을 못 잡았다"
