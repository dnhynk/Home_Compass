"""SPEC 10.2 7단계 ③ — **상태 화면이 실제로 지표를 그리는가** (소유자: `api`).

## 왜 소스를 문자열로 훑는 것으로 끝내지 않는가

`test_status_metrics.py` 의 파수병은 `admin/app.js` 에 `|| 0` 이 없다는 것까지는 말하지만
**화면에 무엇이 나타나는지는 말하지 못한다.** SPEC 9.1.1 이 「판정 기준은 구현이 아니라
출력이다」라고 못박았고, 그 규율을 JS 에 대해 지키는 방법을 이 저장소는 이미 정해 두었다 —
**`node` 로 실제 실행한다** (계약 결정 #36). 새 의존성도, 번들러도, 브라우저도 없다.

여기서는 `admin/app.js` 를 최소 DOM 위에 올리고 `fetch` 를 가짜 응답으로 바꾼 뒤
`DOMContentLoaded` 를 발사한다. 그리고 **`#metricGrid` 에 실제로 찍힌 글자**를 읽는다.

## 이 파일이 붙드는 것

  · `null` 이 내려오면 화면에 **숫자가 아니라 말**이 나온다 (0% · 0건이 아니다)
  · 관측된 값이 있으면 그 값이 그대로 나온다 — 위 규율이 화면을 벙어리로 만들지 않았다
  · 배지가 **두 수를 따로** 그린다 (승인 대기 · 신고). 합계는 어디에도 없다
  · 초과 판정 자리가 화면에 없고, **판정하지 않았다는 문장**이 그 자리에 있다

`node` 가 없으면 **skip 하지 않고 실패한다** — skip 은 검사가 돌지 않은 상태를 초록으로
칠하는 것이고, 이 저장소가 D-11 에서 금지한 침묵 폴백과 같다 (계약 결정 #36).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from js_runner import node_executable

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_JS = REPO_ROOT / "admin" / "app.js"

# --------------------------------------------------------------------------
# 최소 DOM + 동기 Promise
# --------------------------------------------------------------------------
#
# ★ **Promise 를 동기로 만든다.** 실제 Promise 는 마이크로태스크로 풀리므로 node 프로세스가
#   끝나기 전에 화면이 그려졌는지 확인할 자리가 없다. `app.js` 는 `then`/`catch` 만 쓰므로
#   그 둘을 즉시 호출하는 thenable 로 바꾸면 부팅 전체가 한 줄기로 끝난다. 이것이
#   [비동기를 테스트하려고 sleep 을 넣는] 것보다 결정적이다.

_HARNESS = r"""
function textNode(value) {
  return { nodeType: 3, get textContent() { return this._v; },
           set textContent(v) { this._v = String(v); }, _v: String(value) };
}

function makeElement(tag) {
  return {
    tagName: tag, className: '', hidden: false, title: '', type: '', value: '',
    disabled: false, checked: false, href: '', rel: '',
    children: [],
    style: {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    appendChild: function (child) { this.children.push(child); return child; },
    removeChild: function (child) {
      var index = this.children.indexOf(child);
      if (index >= 0) { this.children.splice(index, 1); }
      return child;
    },
    get firstChild() { return this.children.length ? this.children[0] : null; },
    set textContent(value) { this.children = [textNode(value)]; },
    get textContent() {
      return this.children.map(function (c) { return c.textContent; }).join('');
    },
    addEventListener: function () {},
    setAttribute: function () {},
    getElementsByTagName: function () { return []; },
    scrollIntoView: function () {}
  };
}

var REGISTRY = {};
var LISTENERS = [];

var document = {
  getElementById: function (id) {
    if (!REGISTRY[id]) { REGISTRY[id] = makeElement('div'); }
    return REGISTRY[id];
  },
  createElement: makeElement,
  createTextNode: textNode,
  addEventListener: function (name, handler) { LISTENERS.push([name, handler]); }
};

function resolved(value) {
  return {
    then: function (onOk) {
      if (!onOk) { return resolved(value); }
      var next;
      try { next = onOk(value); } catch (err) { return rejected(err); }
      return (next && typeof next.then === 'function') ? next : resolved(next);
    },
    catch: function () { return resolved(value); }
  };
}

function rejected(error) {
  function handle(handler) {
    if (!handler) { return rejected(error); }
    var next;
    try { next = handler(error); } catch (err) { return rejected(err); }
    return (next && typeof next.then === 'function') ? next : resolved(next);
  }
  return {
    then: function (onOk, onErr) { return handle(onErr); },
    catch: function (onErr) { return handle(onErr); }
  };
}

var CALLED = [];

function fetch(path, options) {
  CALLED.push(path);
  var payload = RESPONSES[path];
  if (payload === undefined) {
    return resolved({ ok: false, status: 404,
                      json: function () { return resolved({ error: { code: 'not_found',
                                                                     message: path } }); } });
  }
  return resolved({ ok: true, status: 200,
                    json: function () { return resolved(payload); } });
}
"""

_BOOT = r"""
LISTENERS.forEach(function (entry) {
  if (entry[0] === 'DOMContentLoaded') { entry[1](); }
});

return {
  called: CALLED,
  metrics: document.getElementById('metricGrid').textContent,
  cards: document.getElementById('metricGrid').children.map(function (card) {
    return card.children.map(function (line) { return line.textContent; });
  }),
  summary: document.getElementById('statusSummary').textContent,
  foot: document.getElementById('statusFoot').textContent,
  badge: document.getElementById('queueBadge').textContent,
  badgeTitle: document.getElementById('queueBadge').title,
  panelHidden: document.getElementById('statusPanel').hidden,
  badgeHidden: document.getElementById('queueBadge').hidden
};
"""


_NODE_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
let input = '';
process.stdin.on('data', c => (input += c));
process.stdin.on('end', () => {
  const spec = JSON.parse(input);
  const context = {};
  context.window = context;
  context.globalThis = context;
  context.console = console;
  context.JSON = JSON;
  vm.createContext(context);
  vm.runInContext(spec.harness, context, { filename: 'harness.js' });
  vm.runInContext('var RESPONSES = ' + JSON.stringify(spec.responses) + ';', context);
  vm.runInContext(fs.readFileSync(spec.appJs, 'utf8'), context, { filename: spec.appJs });
  const fn = vm.runInContext('(function () {\n' + spec.boot + '\n})', context);
  let out;
  try { out = { ok: true, value: fn() }; }
  catch (err) { out = { ok: false, error: String(err && err.stack ? err.stack : err) }; }
  process.stdout.write(JSON.stringify(out));
});
"""

#: 상태 말고 나머지 화면은 정상인 서버. 이 표에서 `/api/admin/status` 만 빼면
#: [화면 전체가 죽은 것] 과 [지표만 못 읽은 것] 이 구분된다.
BASE_RESPONSES = {
    "/api/health": {"status": "ok", "llm": "offline"},
    "/api/auth/session": {"authenticated": True, "username": "rulemanager",
                          "role": "rule_manager", "csrfToken": "t"},
    "/api/admin/drafts": {"drafts": []},
    "/api/admin/reports": {"reports": []},
}


def run_screen(responses: dict) -> dict:
    """`admin/app.js` 를 최소 DOM 위에서 실제로 실행하고 화면에 찍힌 글자를 돌려준다."""
    completed = subprocess.run(
        [node_executable(), "-e", _NODE_SCRIPT],
        input=json.dumps({"harness": _HARNESS, "boot": _BOOT,
                          "responses": responses, "appJs": str(ADMIN_JS)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"node 실행 실패 (exit {completed.returncode}):\n{completed.stderr}")
    result = json.loads(completed.stdout)
    if not result["ok"]:
        raise RuntimeError("화면 JS 가 터졌다:\n" + result["error"])
    return result["value"]


def render(status: dict) -> dict:
    return run_screen({**BASE_RESPONSES, "/api/admin/status": status})


# --------------------------------------------------------------------------
# 응답 픽스처
# --------------------------------------------------------------------------

EMPTY_STATUS = {
    "generatedAt": "2026-08-15T09:00:00+00:00",
    "batch": {"runs": 0, "succeeded": 0, "failed": 0, "successRatePct": None,
              "lastRunAt": None, "lastOutcome": None,
              "denominator": "market.run 감사기록 1행 = 시세 수집 배치 1회."},
    "freshness": {"regions": 10, "oldestFetchedAt": None, "newestFetchedAt": None,
                  "oldestAgeDays": None, "verification": {"unverified": 80},
                  "thresholdEvaluated": False,
                  "note": "신선도 임계가 미정이라 판정하지 않는다 (계약 결정 #39)."},
    "llm": {
        "chat": {"calls": 0, "succeeded": 0, "failed": 0, "successRatePct": None,
                 "latency": {"samples": 0, "p50": None, "max": None, "unit": "ms"},
                 "source": "파일 로그(llm.chat)"},
        "extraction": {"calls": 0, "succeeded": 0, "failed": 0, "successRatePct": None,
                       "latency": {"samples": 0, "p50": None, "max": None, "unit": "s"},
                       "source": "AuditEvent(rule_draft.extract)"},
    },
    "extraction": {"drafts": 0, "failed": 0, "failureRatePct": None, "codes": {},
                   "passLine": None, "note": "합격선을 두지 않는다 (계약 결정 #33)."},
    "queue": {"pending": 0, "oldestPendingAt": None, "longestWaitDays": None,
              "overdue": None, "overdueNote": "SLA N값이 미정이라 판정하지 않는다 (SPEC 7.3)."},
    "reports": {"open": 0, "total": 0, "oldestOpenAt": None, "longestOpenDays": None,
                "note": "닫는 경로가 없어 누적된다."},
    "log": {"path": "C:/var/observability.jsonl", "exists": False, "records": 0,
            "unreadableLines": 0, "writeFailures": 0},
}


def observed_status() -> dict:
    """관측이 **있는** 저장소. 같은 화면이 값을 실제로 그리는지 본다."""
    status = json.loads(json.dumps(EMPTY_STATUS))
    status["batch"].update({"runs": 3, "succeeded": 2, "failed": 1, "successRatePct": 66.7,
                            "lastRunAt": "2026-08-15T03:30:00+09:00", "lastOutcome": "success"})
    status["freshness"].update({"oldestFetchedAt": "2026-08-06T09:00:00+09:00",
                                "newestFetchedAt": "2026-08-15T03:30:00+09:00",
                                "oldestAgeDays": 9.0,
                                "verification": {"unverified": 30, "verified": 50}})
    status["llm"]["chat"].update({"calls": 4, "succeeded": 3, "failed": 1,
                                  "successRatePct": 75.0,
                                  "latency": {"samples": 4, "p50": 3.1, "max": 8.4,
                                              "unit": "ms"}})
    status["llm"]["extraction"].update({"calls": 7, "succeeded": 5, "failed": 2,
                                        "successRatePct": 71.4,
                                        "latency": {"samples": 7, "p50": 1.2, "max": 4.9,
                                                    "unit": "s"}})
    status["extraction"].update({"drafts": 7, "failed": 2, "failureRatePct": 28.6,
                                 "codes": {"schema_invalid": 2}})
    status["queue"].update({"pending": 2, "oldestPendingAt": "2026-08-03T09:00:00+00:00",
                            "longestWaitDays": 12.0})
    status["reports"].update({"open": 5, "total": 5,
                              "oldestOpenAt": "2026-07-26T09:00:00+00:00",
                              "longestOpenDays": 20.0})
    status["log"].update({"exists": True, "records": 128})
    return status


@pytest.fixture(scope="module")
def empty_screen() -> dict:
    return render(EMPTY_STATUS)


@pytest.fixture(scope="module")
def observed_screen() -> dict:
    return render(observed_status())


# ==========================================================================
# 1. 화면이 실제로 떴는가
# ==========================================================================

class TestTheScreenActuallyBoots:
    def test_it_asked_the_status_endpoint(self, empty_screen):
        assert "/api/admin/status" in empty_screen["called"]

    def test_the_panel_and_the_badge_became_visible(self, empty_screen):
        assert empty_screen["panelHidden"] is False
        assert empty_screen["badgeHidden"] is False

    def test_all_seven_two_metrics_are_on_the_screen(self, observed_screen):
        """SPEC 7.2 가 이름으로 요구한 다섯 + 7.3 의 대기 큐 + 신고 + 로그."""
        text = observed_screen["metrics"]
        for label in ("배치 성공률", "데이터 신선도", "LLM 호출", "추출 스키마 실패율",
                      "승인 대기", "현장 신고", "파일 로그"):
            assert label in text, f"7.2 지표가 화면에 없다: {label}"
        assert len(observed_screen["cards"]) == 8


# ==========================================================================
# 2. ★ `null` 은 화면에서 숫자가 되지 않는다
# ==========================================================================

class TestNothingObservedIsNotDrawnAsZero:
    def test_the_empty_screen_says_so_in_words(self, empty_screen):
        text = empty_screen["metrics"]
        assert "아직 안 돎" in text, "배치 이력이 없는데 화면이 그 사실을 말하지 않는다"
        assert "호출 없음" in text
        assert "추출 이력 없음" in text
        assert "취득 이력 없음" in text

    def test_the_empty_screen_never_prints_a_fabricated_percentage(self, empty_screen):
        """★ 이것이 이 파일의 이유다 — 0% 는 **관측된 값일 때만** 화면에 있어야 한다."""
        assert "0%" not in empty_screen["metrics"], empty_screen["metrics"]
        assert "0.0%" not in empty_screen["metrics"]

    def test_the_empty_screen_states_the_facts_that_really_are_zero(self, empty_screen):
        """0 이 **관측된 사실**인 자리는 0 으로 나와야 한다 — 아니면 반대 방향의 거짓말이다."""
        assert "0회 실행" in empty_screen["metrics"]
        assert "대기 중인 초안이 없습니다" in empty_screen["metrics"]

    def test_the_observed_screen_really_prints_the_numbers(self, observed_screen):
        """규율이 화면을 벙어리로 만들지 않았다는 것을 같은 하네스로 확인한다."""
        text = observed_screen["metrics"]
        assert "66.7" in text                       # 배치 성공률
        assert "28.6" in text                       # 추출 스키마 실패율
        assert "75" in text and "71.4" in text       # LLM 성공률 둘
        assert "지연 p50 3.1ms" in text
        assert "지연 p50 1.2s" in text
        assert "9" in text                           # 신선도 경과일


# ==========================================================================
# 3. ★ 판정하지 않은 것을 판정한 것처럼 그리지 않는다
# ==========================================================================

class TestTheScreenSaysWhatItDidNotJudge:
    def test_the_queue_card_carries_the_overdue_note(self, observed_screen):
        text = observed_screen["metrics"]
        assert "SLA N값이 미정" in text
        assert "판정하지 않는다" in text

    def test_the_freshness_card_says_the_threshold_is_undecided(self, observed_screen):
        assert "신선도 임계가 미정" in observed_screen["metrics"]

    def test_the_extraction_card_says_there_is_no_pass_line(self, observed_screen):
        assert "합격선을 두지 않는다" in observed_screen["metrics"]

    def test_the_foot_names_all_three_undecided_thresholds(self, observed_screen):
        foot = observed_screen["foot"]
        assert "#33" in foot and "#39" in foot and "7.3" in foot
        assert "판정하지 않습니다" in foot


# ==========================================================================
# 4. ★★ 승인 대기와 신고를 한 수로 뭉치지 않는다
# ==========================================================================

class TestTheBadgeKeepsTheTwoQueuesApart:
    def test_the_badge_shows_two_numbers_not_their_sum(self, observed_screen):
        badge = observed_screen["badge"]
        assert "대기 2건" in badge
        assert "신고 5건" in badge
        assert "7건" not in badge, f"두 큐를 더했다: {badge}"

    def test_the_badge_says_the_report_count_accumulates(self, observed_screen):
        assert "누적" in observed_screen["badge"]
        assert "누적" in observed_screen["badgeTitle"]

    def test_the_badge_shows_the_longest_wait_but_no_overdue_count(self, observed_screen):
        badge = observed_screen["badge"]
        assert "최장 12일" in badge
        assert "초과" not in badge, f"존재할 수 없는 판정이 배지에 있다: {badge}"

    def test_with_nothing_pending_the_longest_wait_is_a_dash_not_zero(self, empty_screen):
        assert "최장 —" in empty_screen["badge"], empty_screen["badge"]


class TestANegativeAgeIsNamedNotClamped:
    """★ 실기동에서 실제로 나왔다 — 고정 시각으로 심은 초안이 벽시계보다 앞서 있었다.

    그때 화면은 「최장 대기 -0.56일」을 그렸다. 두 가지가 다 나쁘다 —
    읽는 사람이 뜻을 모르고, 0 으로 깎으면 시계 문제가 화면에서 사라진다.
    그래서 **무슨 일이 일어났는지를 적는다.**
    """

    @pytest.fixture(scope="class")
    def skewed(self) -> dict:
        status = observed_status()
        status["queue"]["longestWaitDays"] = -0.56
        status["freshness"]["oldestAgeDays"] = -0.02
        status["reports"]["longestOpenDays"] = -1.5
        return render(status)

    def test_no_negative_day_count_is_printed(self, skewed):
        assert "-0.56" not in skewed["metrics"]
        assert "-0.02" not in skewed["metrics"]
        assert "-1.5" not in skewed["metrics"]
        assert "-0.56" not in skewed["badge"]

    def test_the_screen_names_the_clock_problem_instead(self, skewed):
        assert skewed["metrics"].count("기록 시각이 미래") == 3
        assert "기록 시각이 미래" in skewed["badge"]

    def test_it_is_not_clamped_to_zero(self, skewed):
        """0 으로 깎으면 [막 들어온 건] 과 [시계가 어긋난 건] 이 같은 그림이 된다."""
        assert "최장 대기 0일" not in skewed["metrics"]
        assert "0일 전" not in skewed["metrics"]


# ==========================================================================
# 5. 파일 로그가 새면 화면이 그것을 말한다
# ==========================================================================

class TestTheScreenAdmitsWhenItsOwnNumbersAreShort:
    def test_a_clean_log_says_the_request_body_is_not_written(self, observed_screen):
        assert "요청 본문을 적지 않습니다" in observed_screen["metrics"]

    def test_a_leaking_log_says_the_denominator_is_short(self):
        status = observed_status()
        status["log"].update({"unreadableLines": 3, "writeFailures": 2})
        screen = render(status)
        assert "기록이 새고 있습니다" in screen["metrics"]
        assert "분모가 실제 호출 수보다 작습니다" in screen["metrics"]


# ==========================================================================
# 6. 실패 경로 — 지표를 못 읽으면 **빈 화면**이 아니라 그 사실을 적는다
# ==========================================================================

def test_a_failed_status_request_is_not_drawn_as_an_empty_screen():
    """★ 비어 있는 지표 화면은 [문제 없음] 으로 읽힌다 (SPEC 6.2 침묵 폴백 금지)."""
    screen = run_screen(dict(BASE_RESPONSES))       # `/api/admin/status` 만 없다
    assert screen["metrics"] == "", "지표를 못 읽었는데 카드가 그려졌다"
    assert "지표를 불러오지 못했습니다" in screen["summary"]
    assert "0 이라는 뜻이 아닙니다" in screen["foot"]
