/* ============================================================
   Home_Compass — 규칙 검토·승인 화면 (admin)

   바닐라 JS. 빌드 도구 · 번들러 · 프레임워크 없음 (계약 결정 #31).

   ★★ 이 파일은 **원문 오프셋 산술을 하지 않는다.**

   SPEC 4.2.1 이 span 오프셋 단위를 **유니코드 코드포인트**로 못박았는데, JS 문자열
   인덱스는 **UTF-16 코드유닛**이다. 한글은 둘이 같지만 이모지·희귀 한자 같은 BMP 밖
   문자에서 갈린다. 그 자리에서 어긋나면 검토자는 **엉뚱한 조항을 근거로 보고 승인한다** —
   있는 것보다 나쁜 화면이 된다.

   그래서 자르는 일을 서버가 한다. 상세 API 가 원문을 `source.segments` 로 이미 끊어
   보내고, 이 파일은 **받은 조각을 순서대로 그리기만 한다.** 파이썬 `str` 인덱스가 곧
   코드포인트이므로 단위 변환이 아예 없어지고, 그 정확성이 `backend/tests/api/
   test_admin_review.py` 에서 BMP 밖 문자로 고정된다 (이 저장소에는 JS 실행 하네스가
   없다 — 결정 #31 이 CI 를 파이썬 전용으로 못박았다).

   ★ 이 규율은 `backend/tests/api/test_admin_screen.py` 의 파수병이 지킨다.
     문자열 오프셋 연산(`substring` · `charAt` · `codePointAt` …)과
     [span 오프셋으로 자르기](`slice(...start...)`)를 이 파일에서 금지한다.
     배열 조작은 막지 않는다 — 막으려는 것은 문자열 오프셋 산술이지 배열이 아니다.
   ============================================================ */

(function () {
  'use strict';

  var CSRF_HEADER = 'X-CSRF-Token';

  //: 한 프로필에 대해 표에 펼치는 변경 항목 수. 넘치면 **몇 건을 접었는지 화면에 적는다** —
  //  조용히 자르면 [이게 전부다] 로 읽힌다.
  var MAX_VISIBLE_CHANGES = 6;

  var state = {
    csrf: null,
    role: null,
    username: null,
    drafts: [],
    reports: [],
    selectedIds: [],
    currentId: null,
    detail: null,
    activeField: null
  };

  // ------------------------------------------------------------------
  // DOM 손잡이
  // ------------------------------------------------------------------
  function $(id) { return document.getElementById(id); }

  function clear(node) {
    while (node.firstChild) { node.removeChild(node.firstChild); }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  // ------------------------------------------------------------------
  // HTTP — **침묵 폴백 금지** (SPEC 6.2 오프라인 동작 정의 #3)
  // ------------------------------------------------------------------
  //
  // 실패를 삼키면 화면은 [아무 일도 없었다] 처럼 보이고, 검토자는 자기가 누른 승인이
  // 실제로 반영됐는지 알 수 없게 된다. 모든 실패는 오류 봉투(SPEC 8.1)의 문구를 그대로
  // 화면에 올린다.

  function request(method, path, body) {
    var options = {
      method: method,
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    if (state.csrf && method !== 'GET') {
      options.headers[CSRF_HEADER] = state.csrf;
    }
    return fetch(path, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (response.ok) { return payload; }
        var envelope = payload && payload.error ? payload.error : {};
        var error = new Error(envelope.message || ('요청이 실패했습니다 (HTTP ' + response.status + ').'));
        error.code = envelope.code || ('http_' + response.status);
        error.status = response.status;
        throw error;
      });
    });
  }

  // ------------------------------------------------------------------
  // 표시 헬퍼
  // ------------------------------------------------------------------

  function show(value, present) {
    if (present === false) { return '(없는 필드)'; }
    if (value === null) { return 'null'; }
    if (value === undefined) { return '(없는 필드)'; }
    if (typeof value === 'object') { return JSON.stringify(value); }
    return String(value);
  }

  var SAID_LABEL = {
    value: '값을 실었다',
    explicit_null: '「없음」(null)을 명시',
    not_found: '「모름」(not_found)',
    silent: '말하지 않았다',
    not_applicable: '말할 수 없는 필드'
  };

  var SAID_CHIP = {
    value: '',
    explicit_null: 'is-warn',
    not_found: 'is-new',
    silent: 'is-warn',
    not_applicable: ''
  };

  function shortTime(iso) {
    if (!iso) { return '—'; }
    var pieces = String(iso).split('T');
    if (pieces.length < 2) { return String(iso); }
    return pieces[0] + ' ' + pieces[1].split('.')[0].split('+')[0];
  }

  // ------------------------------------------------------------------
  // 세션
  // ------------------------------------------------------------------

  function refreshSession() {
    return request('GET', '/api/auth/session').then(function (session) {
      state.csrf = session.csrfToken;
      state.role = session.role;
      state.username = session.username;
      renderIdentity();
      return session;
    });
  }

  function renderIdentity() {
    var badge = $('whoBadge');
    var logout = $('btnLogout');
    if (state.role) {
      clear(badge);
      badge.appendChild(el('span', null, state.username + ' · '));
      badge.appendChild(el('strong', null, state.role));
      badge.hidden = false;
      logout.hidden = false;
    } else {
      badge.hidden = true;
      logout.hidden = true;
    }
    var isManager = state.role === 'rule_manager';
    $('gate').hidden = isManager;
    $('desk').hidden = !isManager;
    if (!isManager) {
      // 지표도 대기 큐와 같은 게이트 뒤에 있다. 화면이 숨기는 것은 편의일 뿐이고
      // 검사는 API 가 한다 (SPEC 6.1) — `status.read` 는 rule_manager 뿐이다.
      $('statusPanel').hidden = true;
      $('queueBadge').hidden = true;
    }
    if (!isManager && state.role) {
      // ★ 화면이 버튼을 숨기는 것으로 권한을 지키지 않는다 (SPEC 6.1). 상담원이 여기
      //   도달하면 사실대로 적는다 — API 가 이미 거부하고 있다는 것까지.
      note('로그인은 됐지만 역할이 ' + state.role + ' 입니다. 규칙 승인·반려는 '
        + 'rule_manager 만 할 수 있고, 그 검사는 화면이 아니라 API 가 합니다 (SPEC 6.1).');
    }
  }

  function note(message) {
    $('loginNote').textContent = message || '';
  }

  // ------------------------------------------------------------------
  // 추출 실패의 사유 — 큐와 검토창이 함께 쓴다
  // ------------------------------------------------------------------
  //
  // ★ 서버는 `failureReason` 을 큐(`DraftRef`)와 상세 양쪽에 싣는데 **화면이 안 그렸다.**
  //   규칙관리자는 `extraction_failed` 라는 상태 문자열만 보고, 재추출을 지시할지 수동으로
  //   입력할지 정할 근거가 없었다. 같은 화면의 신고 항목은 이미 「짝이 되는 추출 초안이
  //   없습니다 — 수동 입력하거나 재추출을 지시해야 합니다」까지 적고 있었다.
  //   **한쪽만 친절한 화면이었다.**
  //
  // ★ 코드를 사람 말로 옮기되 **원래 코드도 함께 보인다.** 규칙관리자는 간헐 업무자이고
  //   (SPEC 7.3) `span_not_in_text` 는 개발자 어휘다. 그러나 옮긴 말만 남기면 개발자가
  //   재현할 수 없다. 이 표는 서버 어휘의 **손으로 쓴 사본**이고 — 이 저장소가 반복해서
  //   당한 부류다 — 그래서 `test_admin_screen.py` 가 서버의 `ALL_CODES` 와 정확히 같은지
  //   매번 대조한다.
  var REJECTION_LABEL = {
    envelope_invalid: '모델 응답의 봉투가 규격과 다릅니다',
    schema_violation: '추출 결과가 규칙 스키마를 어겼습니다',
    policy_id_mismatch: '다른 제도의 결과가 돌아왔습니다',
    not_found_unknown_pointer: '없다고 보고한 자리가 이 초안에 없는 항목입니다',
    not_found_value_present: '없다고 보고해 놓고 값이 실려 있습니다',
    span_missing: '값을 실었는데 근거 구간이 없습니다',
    span_duplicate: '한 항목에 근거 구간이 둘 이상 붙었습니다',
    span_unexpected_field: '근거를 요구하지 않는 항목에 근거가 붙었습니다',
    span_for_not_found_field: '없다고 보고한 항목에 근거가 붙었습니다',
    span_empty_quote: '근거 인용이 비어 있습니다',
    span_not_in_text: '근거 인용을 원문에서 찾지 못했습니다',
    span_offset_mismatch: '근거 구간의 위치가 인용과 어긋납니다',
    llm_unavailable: '추출 모델을 호출할 수 없었습니다',
    llm_call_failed: '추출 모델 호출이 실패했습니다',
    span_store_rejected: '검증은 통과했으나 저장소가 근거 구간을 거부했습니다'
  };

  //: 사유 문자열의 형태는 `코드: 자세히` 이고, 여럿이면 ` / ` 로 이어진다
  //  (`ingest/extraction.py` 의 join · `extraction_verify.Rejection` 의 문자열화).
  //
  // ★ **` / ` 로 그냥 쪼개지 않는다.** 자세히에는 원문 인용이 실리고 그 안에 ` / ` 가
  //   들어 있을 수 있다. 그래서 **알려진 코드가 뒤따르는 자리에서만** 끊는다.
  // ★ 어긋난 자리(JSON 포인터)는 **자세히가 `/` 로 시작할 때만** 뽑는다. 서버가 포인터를
  //   앞세우지 않는 사유도 있다(`policy_id_mismatch` · `envelope_invalid`).
  //   **없는 것을 지어내지 않는다** — 빈 칸은 실패가 아니다.
  function parseFailureReason(text) {
    if (!text) { return []; }
    var codes = Object.keys(REJECTION_LABEL);
    var boundary = new RegExp(' / (?=(?:' + codes.join('|') + '): )');
    return text.split(boundary).map(function (chunk) {
      var head = /^([a-z_]+): ([\s\S]*)$/.exec(chunk);
      if (!head || !REJECTION_LABEL[head[1]]) {
        return { code: null, pointer: null, detail: chunk };
      }
      var pointer = /^(\/[^\s:]*)/.exec(head[2]);
      return { code: head[1], pointer: pointer ? pointer[1] : null, detail: head[2] };
    });
  }

  function rejectionLabel(item) {
    if (!item.code) { return '분류되지 않은 사유'; }
    return REJECTION_LABEL[item.code] || item.code;
  }

  //: 큐 한 줄에 들어갈 요약. 자세히(자유 텍스트)는 넣지 않는다 — 검토창이 그것을 진다.
  function failureSummary(text) {
    var items = parseFailureReason(text);
    if (items.length === 0) { return '실패 사유가 기록되지 않았습니다.'; }
    return items.map(function (item) {
      return rejectionLabel(item) + (item.pointer ? ' · ' + item.pointer : '');
    }).join(' / ');
  }

  // ------------------------------------------------------------------
  // 대기 큐
  // ------------------------------------------------------------------

  function loadQueue() {
    return request('GET', '/api/admin/drafts').then(function (payload) {
      state.drafts = payload.drafts;
      renderQueue();
    });
  }

  function renderQueue() {
    var list = $('queueList');
    clear(list);

    var pending = state.drafts.filter(function (d) { return d.status === 'pending'; });
    var summary = state.drafts.length + '건 중 대기 ' + pending.length + '건';
    $('queueSummary').textContent = summary;

    if (state.drafts.length === 0) {
      list.appendChild(el('li', 'queue-empty', '초안이 없습니다. 추출 배치를 먼저 돌리세요.'));
      renderBatchButton();
      return;
    }

    state.drafts.forEach(function (draft) {
      var item = el('li', 'queue-item');
      if (draft.id === state.currentId) { item.className = 'queue-item active'; }

      var box = document.createElement('input');
      box.type = 'checkbox';
      box.disabled = draft.status !== 'pending';
      box.checked = state.selectedIds.indexOf(draft.id) >= 0;
      box.setAttribute('aria-label', draft.id + ' 일괄 승인 대상으로 선택');
      box.addEventListener('change', function () {
        toggleSelected(draft.id, box.checked);
      });

      var open = el('button', 'queue-open');
      open.type = 'button';
      open.appendChild(el('span', 'queue-policy', draft.policyId));
      open.appendChild(el('span', 'queue-id', draft.id));
      var meta = el('span', 'queue-meta',
        draft.status + ' · ' + shortTime(draft.createdAt));
      open.appendChild(meta);
      // 실패 초안은 **큐에서부터** 사유를 보인다. 열어 봐야 아는 것으로 두면 대기 큐가
      // [무엇이 밀려 있는가] 는 말해도 [무엇을 해야 하는가] 는 말하지 않는다.
      if (draft.status === 'extraction_failed') {
        open.appendChild(el('span', 'queue-failure', failureSummary(draft.failureReason)));
      }
      open.addEventListener('click', function () { openDraft(draft.id); });

      item.appendChild(box);
      item.appendChild(open);
      list.appendChild(item);
    });
    renderBatchButton();
  }

  // ------------------------------------------------------------------
  // 현장 신고 큐 — **별도 유형** (SPEC 6.4 · 10.2 6-A)
  // ------------------------------------------------------------------
  //
  // ★ 초안 큐와 **다른 목록**이다. 같은 목록에 섞으면 [무엇이 이것을 말했는가] 가
  //   사라진다 — 초안에는 원문 근거·span·병합 규칙이 걸리고, 신고에는 아무것도 없다.
  //
  // ★ 병합은 SPEC 6.4 가 **잠정**이라고 적은 규칙이다. 실제 운영에서 신고 빈도와
  //   draft 빈도의 비율을 본 뒤 재검토한다. 여기서는 서버가 계산한 `mergedDraftIds`
  //   를 그대로 그린다 — 화면이 정책 id 로 직접 조인하면 그 규칙이 두 벌이 된다.

  var REPORT_FIELD_LABEL = {
    status: '판정 결과', name: '제도 이름', category: '분류', reasons: '판정 사유',
    maxAmountKRW: '최대 한도', rateRangePct: '금리 범위', source: '출처',
    jeonseMedianKRW: '전세 중위가', monthlyDepositKRW: '월세 보증금',
    monthlyRentKRW: '월세', maintenanceFeeKRW: '관리비',
    jeonseRatioPct: '전세가율', conversionRatePct: '전월세 전환율',
    marketRisk: '시장 리스크', guaranteeAvailable: '보증 가입 가능'
  };

  function reportItemLabel(report) {
    return (report.targetKind === 'policy' ? '제도' : '시세') + ' · ' + report.targetId +
      ' · ' + (REPORT_FIELD_LABEL[report.targetField] || report.targetField);
  }

  function loadReports() {
    return request('GET', '/api/admin/reports').then(function (payload) {
      state.reports = payload.reports;
      renderReports();
    });
  }

  function renderReports() {
    var list = $('reportList');
    clear(list);

    var merged = state.reports.filter(function (r) { return r.mergedDraftIds.length > 0; });
    $('reportSummary').textContent = state.reports.length === 0
      ? '올라온 신고가 없습니다.'
      : state.reports.length + '건 · 이 중 ' + merged.length + '건은 같은 제도의 초안과 함께 검토합니다';

    if (state.reports.length === 0) {
      list.appendChild(el('li', 'queue-empty',
        '현장에서 올라온 신고가 없습니다. 상담원이 판정 화면에서 올립니다.'));
      return;
    }

    state.reports.forEach(function (report) {
      var item = el('li', 'queue-item report-item');
      // 유형 표식. 초안 항목에는 없는 칩이며, 이것이 [별도 유형] 의 눈에 보이는 형태다.
      item.appendChild(el('span', 'chip chip-sm report-chip', '현장 신고'));

      var box = el('div', 'report-body');
      box.appendChild(el('span', 'queue-policy', reportItemLabel(report)));
      box.appendChild(el('span', 'report-reason', report.reason));
      box.appendChild(el('span', 'queue-meta',
        report.reporter + ' · ' + shortTime(report.at) + ' · ' + report.status));

      if (report.mergedDraftIds.length > 0) {
        // 병합 — 신고는 초안의 **컨텍스트**다. 초안을 열면 그 안에서 다시 보인다.
        report.mergedDraftIds.forEach(function (draftId) {
          var open = el('button', 'queue-open report-merged');
          open.type = 'button';
          open.appendChild(el('span', 'queue-id', '초안 ' + draftId + ' 와 함께 검토'));
          open.addEventListener('click', function () { openDraft(draftId); });
          box.appendChild(open);
        });
      } else {
        // 「신고만 있고 draft 가 없으면 신고 단독 항목으로 큐에 남는다」 (SPEC 6.4).
        box.appendChild(el('span', 'report-alone',
          '짝이 되는 추출 초안이 없습니다 — 수동 입력하거나 재추출을 지시해야 합니다.'));
      }

      item.appendChild(box);
      list.appendChild(item);
    });
  }

  function renderDraftReports(reports) {
    var card = $('draftReports');
    var list = $('draftReportList');
    clear(list);
    if (!reports || reports.length === 0) { card.hidden = true; return; }
    card.hidden = false;
    $('draftReportChip').textContent = reports.length + '건';
    reports.forEach(function (report) {
      var row = el('li', 'report-context-item');
      row.appendChild(el('span', 'queue-policy', reportItemLabel(report)));
      row.appendChild(el('span', 'report-reason', report.reason));
      row.appendChild(el('span', 'queue-meta', report.reporter + ' · ' + shortTime(report.at)));
      list.appendChild(row);
    });
  }

  // ------------------------------------------------------------------
  // 상태 화면 — SPEC 7.2 관측 지표 · 7.3 대기 큐
  // ------------------------------------------------------------------
  //
  // ★★ **이 블록의 규율은 하나다 — 없는 값을 0 으로 그리지 않는다.**
  //
  //   서버가 관측하지 못한 값을 `null` 로 내려보낸다. 여기서 그것을 0 이나 0% 로 바꾸면
  //   화면은 [실패율 0%] · [기한을 넘긴 건이 없다] 를 말하게 되고, 그 둘은 **아직 한 번도
  //   안 돌았다** 와 **판정하지 않았다** 를 덮는다. 관측 화면이 낼 수 있는 가장 나쁜
  //   거짓말이다. 그래서 카드 렌더러는 `null` 을 받으면 숫자를 만들지 않고 사유를 적는다.
  //
  // ★ **판정하지 않는다.** 이 화면에는 통과/불통과 배지가 없다. 세 지표의 임계가 전부
  //   미정이기 때문이며(추출 성공률 문턱 없음 · 신선도 임계 미정 · SLA N 미정), 그것에 색을
  //   입히면 없는 판정선이 있는 것처럼 읽힌다. 각 카드의 마지막 줄이 그 사실을 적는다.
  //
  // ★ **승인 대기와 신고를 더하지 않는다.** 초안은 승인·반려로 큐를 떠나지만 신고는
  //   떠나는 경로가 SPEC 의 어느 단계에도 없다. 더하면 그 합은 밀린 일이 아니라
  //   누적 카운터가 되고, 늘 커지기만 하는 수는 정보가 아니다.

  //: 관측이 없을 때 쓰는 말. **0 이 아니다.**
  var NO_OBSERVATION = '관측 없음';

  function metricNumber(value, unit) {
    if (value === null || value === undefined) { return null; }
    return String(value) + (unit || '');
  }

  //: 일수 표기. **음수를 0 으로 깎지 않는다.**
  //
  //  음수는 [기록의 시각이 지금보다 뒤다] 라는 **관측**이다. 0 으로 만들면 시계 문제가
  //  화면에서 사라지고, 그것은 이 화면이 하지 않기로 한 바로 그 일이다(없는 값을 0 으로
  //  채우기). 그렇다고 「-0.56일 대기」로 그리면 읽는 사람이 뜻을 모른다. 그래서 숫자를
  //  버리지 않고 **무슨 일이 일어났는지를 적는다.**
  //
  //  실기동에서 실제로 나왔다 — 고정 시각으로 심은 초안이 벽시계보다 앞서 있었다.
  var FUTURE_TIMESTAMP = '기록 시각이 미래 (시계 확인 필요)';

  function dayText(value, suffix) {
    if (value === null || value === undefined) { return null; }
    return value < 0 ? FUTURE_TIMESTAMP : String(value) + suffix;
  }

  function metricCard(spec) {
    var card = el('article', 'metric' + (spec.leaking ? ' is-leaking' : ''));
    card.appendChild(el('p', 'metric-label', spec.label));

    var value = el('p', 'metric-value');
    if (spec.value === null || spec.value === undefined) {
      value.className = 'metric-value is-none';
      value.textContent = spec.missing || NO_OBSERVATION;
    } else {
      value.appendChild(document.createTextNode(String(spec.value)));
      if (spec.unit) { value.appendChild(el('span', 'metric-unit', spec.unit)); }
    }
    card.appendChild(value);

    (spec.subs || []).forEach(function (line) {
      if (line) { card.appendChild(el('p', 'metric-sub', line)); }
    });
    if (spec.note) { card.appendChild(el('p', 'metric-note', spec.note)); }
    return card;
  }

  function verificationLine(counts) {
    var names = Object.keys(counts || {});
    if (names.length === 0) { return '계보가 비어 있습니다.'; }
    return names.map(function (name) { return name + ' ' + counts[name]; }).join(' · ');
  }

  function latencyLine(latency) {
    if (!latency || latency.samples === 0) {
      return '지연 표본 없음 — 기록된 호출이 없습니다.';
    }
    return '지연 p50 ' + latency.p50 + latency.unit +
      ' · 최대 ' + latency.max + latency.unit +
      ' (표본 ' + latency.samples + '건)';
  }

  function llmCard(label, channel) {
    return metricCard({
      label: label,
      value: metricNumber(channel.successRatePct, '%'),
      missing: channel.calls === 0 ? '호출 없음' : NO_OBSERVATION,
      subs: [
        channel.calls + '회 호출 · 성공 ' + channel.succeeded + ' · 실패 ' + channel.failed,
        latencyLine(channel.latency)
      ],
      note: '출처 ' + channel.source
    });
  }

  function codesLine(codes) {
    var names = Object.keys(codes || {});
    if (names.length === 0) { return '거부 사유 기록이 없습니다.'; }
    return names.map(function (name) { return name + ' ' + codes[name]; }).join(' · ');
  }

  function renderStatus(status) {
    var grid = $('metricGrid');
    clear(grid);

    var batch = status.batch;
    grid.appendChild(metricCard({
      label: '배치 성공률 (시세 수집)',
      value: metricNumber(batch.successRatePct, '%'),
      missing: '아직 안 돎',
      subs: [
        batch.runs + '회 실행 · 성공 ' + batch.succeeded + ' · 실패 ' + batch.failed,
        batch.lastRunAt
          ? '마지막 실행 ' + shortTime(batch.lastRunAt) + ' · ' + batch.lastOutcome
          : '실행 기록이 없습니다 — 성공률이 낮은 것이 아니라 한 번도 돌지 않았습니다.'
      ],
      note: '분모 — ' + batch.denominator
    }));

    var fresh = status.freshness;
    grid.appendChild(metricCard({
      label: '데이터 신선도 (가장 오래된 취득)',
      value: dayText(fresh.oldestAgeDays, '일 전'),
      missing: '취득 이력 없음',
      subs: [
        '지역 ' + fresh.regions + '개 · 계보 ' + verificationLine(fresh.verification),
        fresh.oldestFetchedAt
          ? '가장 오래된 fetched_at ' + shortTime(fresh.oldestFetchedAt)
          : '수집 배치가 아직 값을 넣지 않았습니다.'
      ],
      note: fresh.note
    }));

    grid.appendChild(llmCard('LLM 호출 — 상담 채팅', status.llm.chat));
    grid.appendChild(llmCard('LLM 호출 — 규칙 추출', status.llm.extraction));

    var extraction = status.extraction;
    grid.appendChild(metricCard({
      label: '추출 스키마 실패율',
      value: metricNumber(extraction.failureRatePct, '%'),
      missing: '추출 이력 없음',
      subs: [
        extraction.drafts + '건 중 ' + extraction.failed + '건이 검증에서 거부됐습니다.',
        codesLine(extraction.codes)
      ],
      note: extraction.note
    }));

    var queue = status.queue;
    grid.appendChild(metricCard({
      label: '승인 대기 (초안)',
      value: queue.pending,
      unit: '건',
      subs: [
        queue.longestWaitDays === null
          ? '대기 중인 초안이 없습니다.'
          : '최장 대기 ' + dayText(queue.longestWaitDays, '일')
            + ' (' + shortTime(queue.oldestPendingAt) + ' 생성)'
      ],
      note: queue.overdueNote
    }));

    var reports = status.reports;
    grid.appendChild(metricCard({
      label: '현장 신고 (누적)',
      value: reports.open,
      unit: '건',
      subs: [
        '전수 ' + reports.total + '건 중 열려 있는 것 ' + reports.open + '건',
        reports.longestOpenDays === null
          ? '올라온 신고가 없습니다.'
          : '가장 오래된 것이 ' + dayText(reports.longestOpenDays, '일') + ' 됐습니다.'
      ],
      note: reports.note
    }));

    // 파일 로그 자체의 상태. **지표가 아니라 지표를 믿을 수 있는가에 대한 답이다** —
    // 못 쓴 줄과 깨진 줄이 있으면 위 LLM 채팅 카드의 분모가 실제보다 작다.
    var log = status.log;
    var leaking = log.unreadableLines > 0 || log.writeFailures > 0;
    grid.appendChild(metricCard({
      label: '파일 로그 (SPEC 7.2)',
      value: log.records,
      unit: '줄',
      leaking: leaking,
      subs: [
        log.exists ? '파일 ' + log.path : '아직 파일이 만들어지지 않았습니다: ' + log.path,
        leaking
          ? '해석 실패 ' + log.unreadableLines + '줄 · 쓰기 실패 ' + log.writeFailures + '회'
          : '해석 실패 0줄 · 쓰기 실패 0회'
      ],
      note: leaking
        ? '기록이 새고 있습니다. 위 「LLM 호출 — 상담 채팅」의 분모가 실제 호출 수보다 작습니다.'
        : '요청 본문을 적지 않습니다 (SPEC 7.1). 오류 경로도 예외 타입 이름만 남깁니다.'
    }));

    $('statusSummary').textContent = '기준 시각 ' + shortTime(status.generatedAt) +
      ' · 출처는 저장소의 감사기록과 파일 로그뿐입니다 (외부 APM 없음).';
    $('statusFoot').textContent =
      '이 화면은 판정하지 않습니다 — 추출 합격선(계약 결정 #33) · 신선도 임계(결정 #39) · ' +
      '대기 큐 SLA N(SPEC 7.3) 이 전부 미정이므로 통과/불통과를 말할 근거가 없습니다. ' +
      '관측된 수와 그 수가 무엇을 세었는지만 싣습니다.';

    renderQueueBadge(status);
  }

  //: SPEC 7.3 장치 1 — 상시 배지. **세 수를 따로 센다** (더하지 않는다).
  function renderQueueBadge(status) {
    var badge = $('queueBadge');
    clear(badge);
    badge.appendChild(document.createTextNode('대기 '));
    badge.appendChild(el('strong', null, status.queue.pending + '건'));
    badge.appendChild(document.createTextNode(' · 최장 '));
    badge.appendChild(el('strong', null,
      dayText(status.queue.longestWaitDays, '일') || '—'));
    badge.appendChild(el('span', 'sep', ' | '));
    badge.appendChild(document.createTextNode('신고 '));
    badge.appendChild(el('strong', null, status.reports.open + '건'));
    badge.appendChild(document.createTextNode(' (누적)'));
    badge.title = '승인 대기와 신고를 더하지 않습니다 — 신고는 큐를 떠나는 경로가 없어 '
      + '누적됩니다. 기한을 넘긴 건이 몇 건인지는 N값이 미정이라 표시하지 않습니다 (SPEC 7.3).';
    badge.hidden = false;
  }

  function loadStatus() {
    return request('GET', '/api/admin/status').then(function (payload) {
      $('statusPanel').hidden = false;
      renderStatus(payload);
    }).catch(function (error) {
      // 침묵 폴백 금지 (SPEC 6.2 #3). 지표를 못 읽었으면 **빈 화면 대신 그 사실**을 적는다 —
      // 비어 있는 지표 화면은 [문제 없음] 으로 읽힌다.
      $('statusPanel').hidden = false;
      clear($('metricGrid'));
      $('statusSummary').textContent = '지표를 불러오지 못했습니다 — [' + error.code + '] ' + error.message;
      $('statusFoot').textContent = '이 화면의 숫자가 없는 것은 지표가 0 이라는 뜻이 아닙니다.';
    });
  }

  function toggleSelected(draftId, checked) {
    var index = state.selectedIds.indexOf(draftId);
    if (checked && index < 0) { state.selectedIds.push(draftId); }
    if (!checked && index >= 0) { state.selectedIds.splice(index, 1); }
    renderBatchButton();
  }

  function renderBatchButton() {
    $('batchCount').textContent = String(state.selectedIds.length);
    $('btnBatch').disabled = state.selectedIds.length === 0;
  }

  // ------------------------------------------------------------------
  // 검토 — SPEC 4.4 의 네 항목
  // ------------------------------------------------------------------

  function openDraft(draftId) {
    // 결정 직후 같은 초안을 다시 열 때는 결과 문구를 지우지 않는다. 지우면 방금 누른
    // 승인·반려의 확인이 화면에서 사라지고, 검토자는 [반영됐는가]를 알 수 없게 된다.
    if (draftId !== state.currentId) { result('', ''); }
    state.currentId = draftId;
    state.activeField = null;
    renderQueue();

    return request('GET', '/api/admin/drafts/' + encodeURIComponent(draftId))
      .then(function (detail) {
        state.detail = detail;
        renderDetail(detail);
        $('reviewEmpty').hidden = true;
        $('review').hidden = false;
        // 영향 사례는 무거우므로(회귀 프로필 × 판정 2회) 상세 렌더가 끝난 뒤 이어 붙인다.
        return request('GET', '/api/admin/drafts/' + encodeURIComponent(draftId) + '/impact');
      })
      .then(renderImpact)
      .catch(function (error) { result(error.message, 'err'); });
  }

  function renderDetail(detail) {
    var draft = detail.draft;
    $('reviewTitle').textContent = draft.policyId;
    $('reviewEyebrow').textContent = '검토 대상';

    var chip = $('changeTypeChip');
    var isNew = detail.changeType === 'new';
    chip.className = 'chip chip-lg ' + (isNew ? 'is-new' : 'is-change');
    chip.textContent = isNew
      ? '① 신규 제도 신설 — 전체 검토'
      : '② 요건 변경 — 변경 필드 + 영향 사례';

    var meta = $('reviewMeta');
    clear(meta);
    addMeta(meta, '초안 ID', draft.id);
    addMeta(meta, '초안 상태', draft.status);
    addMeta(meta, '생성', shortTime(draft.createdAt));
    addMeta(meta, '현행 규칙 버전', detail.current ? detail.current.ruleVersionId : '없음 (첫 승인)');
    addMeta(meta, '원문', draft.policySourceId);
    if (detail.source) {
      addMeta(meta, '원문 길이', detail.source.length + ' 코드포인트');
    }

    // 계약 결정 #17 — 출처표시가 **화면까지** 전달되어야 한다.
    var attribution = $('attribution');
    clear(attribution);
    if (detail.source && detail.source.attribution) {
      attribution.appendChild(el('strong', null, '출처표시 · '));
      attribution.appendChild(document.createTextNode(detail.source.attribution));
      if (detail.source.sourceRef) {
        attribution.appendChild(document.createTextNode(' · '));
        var link = el('a', null, detail.source.sourceRef);
        link.href = detail.source.sourceRef;
        link.rel = 'noreferrer noopener';
        attribution.appendChild(link);
      }
      attribution.hidden = false;
    } else {
      attribution.textContent = '출처표시가 원문에 없습니다. 적재 경로(ingest)가 이용조건을 기록하지 않았다는 뜻입니다.';
      attribution.hidden = false;
    }

    renderFailure(detail);
    renderFields(detail);
    renderDraftReports(detail.reports);
    renderSource(detail);
    renderLimits(detail.limitations);
    resetDecision();
  }

  // --- 추출 실패 — 사유와 어긋난 자리 ---------------------------------
  function renderFailure(detail) {
    var box = $('failureBox');
    var list = $('failureList');
    clear(list);
    if (detail.draft.status !== 'extraction_failed') { box.hidden = true; return; }
    box.hidden = false;

    var items = parseFailureReason(detail.draft.failureReason);
    if (items.length === 0) {
      list.appendChild(el('li', 'failure-item',
        '실패로 기록됐는데 사유가 비어 있습니다. 추출 배치의 기록을 확인해야 합니다.'));
      return;
    }

    items.forEach(function (item) {
      var row = el('li', 'failure-item');
      row.appendChild(el('span', 'failure-label', rejectionLabel(item)));
      // ★ 옮긴 말과 **원래 코드를 함께** 보인다 — 번역만 남기면 개발자가 재현할 수 없다.
      if (item.code) { row.appendChild(el('code', 'failure-code', item.code)); }
      if (item.pointer) { row.appendChild(el('code', 'failure-pointer', item.pointer)); }
      // ★ 자세히는 **자유 텍스트**이고 원문 조각이 실릴 수 있다 (계약 결정 #41 과 같은 부류).
      //   `el()` 은 `textContent` 만 쓰므로 평문으로 들어가고, 긴 인용은 CSS 가 접는다.
      //   **자르지는 않는다** — 조용히 자르면 [이게 전부다] 로 읽힌다.
      row.appendChild(el('p', 'failure-detail', item.detail));
      list.appendChild(row);
    });
  }

  function addMeta(parent, label, value) {
    var wrap = document.createElement('div');
    wrap.appendChild(el('dt', null, label));
    wrap.appendChild(el('dd', null, value));
    parent.appendChild(wrap);
  }

  // --- 4.4 ① · ③ ----------------------------------------------------
  function renderFields(detail) {
    var body = $('fieldBody');
    clear(body);

    detail.fields.forEach(function (field) {
      var row = document.createElement('tr');
      var classes = [];
      if (field.origin === 'inherited') { classes.push('is-inherited'); }
      if (field.changed) { classes.push('is-changed'); }
      if (field.evidence) { classes.push('selectable'); }
      row.className = classes.join(' ');

      var name = document.createElement('td');
      name.appendChild(el('span', 'f-label', field.label));
      name.appendChild(el('code', 'f-path', field.path));
      row.appendChild(name);

      var before = document.createElement('td');
      before.appendChild(el('span', 'f-val was', show(field.before, field.beforePresent)));
      row.appendChild(before);

      var after = document.createElement('td');
      after.appendChild(el('span', 'f-val', show(field.after, field.afterPresent)));
      if (field.wipesPrevious) {
        after.appendChild(el('span', 'f-note', '통째 교체 — 이전 항목이 전부 사라집니다.'));
      }
      row.appendChild(after);

      var said = document.createElement('td');
      var badge = el('span', 'chip ' + (SAID_CHIP[field.draftSaid] || ''),
        SAID_LABEL[field.draftSaid] || field.draftSaid);
      said.appendChild(badge);
      if (field.note) { said.appendChild(el('span', 'f-note', field.note)); }
      row.appendChild(said);

      var evidence = document.createElement('td');
      if (field.evidence) {
        evidence.appendChild(el('span', 'f-quote', field.evidence.quote));
        if (field.evidence.ambiguous) {
          evidence.appendChild(el('span', 'f-note',
            '⚠ 이 인용은 원문에 ' + field.evidence.occurrences + '번 나옵니다 — '
            + '어느 조항에서 나온 근거인지 확정되지 않았습니다. 첫 등장을 표시합니다.'));
        }
        row.addEventListener('click', function () { focusField(field.path, row); });
      } else if (field.evidenceExpected) {
        evidence.appendChild(el('span', 'f-nospan', '⚠ 근거 구간이 없습니다 — 값을 실었는데 근거가 붙지 않았습니다.'));
      } else if (field.draftSaid === 'not_found') {
        evidence.appendChild(el('span', 'f-nospan', '근거 없음이 정상입니다 (원문에 없다고 보고).'));
      } else {
        evidence.appendChild(el('span', 'f-nospan', '—'));
      }
      row.appendChild(evidence);

      // conditionalChecks 는 근거가 **항목마다** 붙는다.
      if (field.evidenceItems) {
        field.evidenceItems.forEach(function (item, index) {
          if (!item) { return; }
          var sub = el('span', 'f-note', '[' + index + '] ' + item.quote);
          evidence.appendChild(sub);
        });
      }

      body.appendChild(row);
    });
  }

  function focusField(path, row) {
    state.activeField = path;
    var rows = $('fieldBody').children;
    for (var i = 0; i < rows.length; i += 1) {
      rows[i].classList.remove('active');
    }
    row.classList.add('active');
    highlightActive();
  }

  // --- 4.4 ① — 원문 대조 --------------------------------------------
  //
  // ★ **여기가 이 파일에서 오프셋을 다루지 않는 이유가 보이는 자리다.** `segments` 는
  //   서버가 이미 코드포인트 기준으로 끊어 놓은 조각들이고, 이 함수는 순서대로 이어
  //   붙이기만 한다. 이어 붙인 결과가 원문과 같다는 것은 파이썬 테스트가 붙든다.

  function renderSource(detail) {
    var view = $('sourceView');
    clear(view);
    if (!detail.source) {
      view.appendChild(el('p', 'f-nospan', '원문을 찾을 수 없습니다. 대조 표시를 만들 수 없습니다.'));
      $('sourceChip').textContent = '원문 없음';
      return;
    }

    var marked = 0;
    detail.source.segments.forEach(function (segment) {
      if (segment.fieldPaths.length === 0) {
        view.appendChild(document.createTextNode(segment.text));
        return;
      }
      marked += 1;
      var mark = el('mark', segment.fieldPaths.length > 1 ? 'multi' : null, segment.text);
      // 필드 목록은 **배열 그대로** 들고 있는다. 문자열로 말아 넣고 다시 파싱하면
      // 이 파일에 문자열 조작이 되살아난다.
      mark.fieldPaths = segment.fieldPaths;
      mark.title = segment.fieldPaths.join(' · ');
      view.appendChild(mark);
    });

    $('sourceChip').textContent = detail.spans.length + '개 근거 · ' + marked + '개 구간';
    highlightActive();
  }

  function highlightActive() {
    var marks = $('sourceView').getElementsByTagName('mark');
    var first = null;
    for (var i = 0; i < marks.length; i += 1) {
      var paths = marks[i].fieldPaths || [];
      var on = state.activeField !== null && paths.indexOf(state.activeField) >= 0;
      marks[i].classList.toggle('active', on);
      if (on && first === null) { first = marks[i]; }
    }
    if (first) { first.scrollIntoView({ block: 'center' }); }
  }

  function renderLimits(limitations) {
    var list = $('limitList');
    clear(list);
    (limitations || []).forEach(function (line) {
      list.appendChild(el('li', null, line));
    });
  }

  // --- 4.4 ② — 승인 영향 --------------------------------------------
  function renderImpact(impact) {
    var body = $('impactBody');
    clear(body);

    var chip = $('impactChip');
    chip.className = 'chip ' + (impact.changedCount > 0 ? 'is-change' : 'is-good');
    chip.textContent = impact.profileCount + '건 중 ' + impact.changedCount + '건의 판정이 달라집니다';

    impact.profiles.forEach(function (entry) {
      var row = document.createElement('tr');
      if (entry.changed) { row.className = 'is-changed'; }

      var who = document.createElement('td');
      who.appendChild(el('strong', null, entry.id));
      who.appendChild(el('span', 'impact-axis', entry.axis));
      row.appendChild(who);

      var verdict = document.createElement('td');
      if (entry.errorBefore || entry.errorAfter) {
        verdict.appendChild(el('span', 'f-nospan', '판정 불가 — ' + (entry.errorAfter || entry.errorBefore)));
      } else {
        var was = entry.policyBefore ? entry.policyBefore.status : '없음';
        var now = entry.policyAfter ? entry.policyAfter.status : '없음';
        verdict.appendChild(el('span', 'f-val was', was));
        verdict.appendChild(el('span', 'impact-arrow', '→'));
        verdict.appendChild(el('strong', 'f-val', now));
      }
      row.appendChild(verdict);

      var diff = document.createElement('td');
      if (!entry.changed) {
        diff.appendChild(el('span', 'f-nospan', '달라지는 것 없음'));
      } else {
        var list = el('ul', 'impact-diff');
        entry.changes.forEach(function (change, index) {
          if (index >= MAX_VISIBLE_CHANGES) { return; }
          list.appendChild(el('li', null,
            change.path + ': ' + show(change.before, true) + ' → ' + show(change.after, true)));
        });
        diff.appendChild(list);
        if (entry.changes.length > MAX_VISIBLE_CHANGES) {
          diff.appendChild(el('span', 'impact-more',
            '외 ' + (entry.changes.length - MAX_VISIBLE_CHANGES) + '건 더 (접어서 보여 주고 있습니다)'));
        }
      }
      row.appendChild(diff);
      body.appendChild(row);
    });
  }

  // ------------------------------------------------------------------
  // 결정 — 승인 · 반려 · 일괄 승인
  // ------------------------------------------------------------------

  function resetDecision() {
    $('approveReason').value = '';
    $('rejectReason').value = '';
    syncRejectButton();
  }

  //: SPEC 10.2 5단계 — **사유 없이 반려할 수 없다.** 서버가 400 을 돌려주고 저장소의
  //  CHECK 제약이 그 뒤를 받치며, 이 함수는 **세 번째 겹**이다. 앞의 둘을 대신하는 것이
  //  아니라 검토자에게 무엇이 빠졌는지 먼저 말해 주는 자리다.
  //
  // ★ 버튼을 실제로 닫는 것은 `syncDecisionButtons` 한 곳이다. 반려를 막을 수 있는 것이
  //   **사유 유무와 초안 상태 둘**이 됐고, 두 자리에서 쓰면 나중에 갈린다.
  function syncRejectButton() {
    var reason = $('rejectReason').value.trim();
    $('reasonHint').textContent = reason.length === 0
      ? '사유를 입력해야 반려할 수 있습니다.'
      : '';
    syncDecisionButtons();
  }

  //: 결정이 막히는 이유. `null` 이면 결정할 수 있다.
  //
  // ★ **서버와 같은 규칙을 쓴다.** `_pending_draft_or_error` 는 `pending` 이 아닌 초안을
  //   전부 409 로 거절하고 **승인·반려가 둘 다** 그 관문을 지난다. 그래서 화면도
  //   `extraction_failed` 하나를 특수 분기로 막지 않는다 — 그러면 이미 처리된 초안에서
  //   같은 거짓말이 그대로 남는다.
  //
  // ★ **화면은 거들 뿐이다** (SPEC D-9). 서버의 409 를 대신하지 않으며 여기서 없애지도
  //   않는다. 막는 것은 [눌리는데 거절되는 버튼] 이라는 거짓말이지 상태 강제가 아니다.
  function decisionBlock(draft) {
    if (!draft) { return '초안을 먼저 여세요.'; }
    if (draft.status === 'pending') { return null; }
    if (draft.status === 'extraction_failed') {
      return '추출에 실패한 초안이라 승인·반려할 수 없습니다. '
        + '아래 사유를 보고 재추출을 지시하거나 수동으로 입력해야 합니다.';
    }
    return '이미 처리된 초안입니다 (현재 상태: ' + draft.status + '). '
      + '승인은 한 번만 일어납니다.';
  }

  function syncDecisionButtons() {
    var blocked = decisionBlock(state.detail ? state.detail.draft : null);
    var reason = $('rejectReason').value.trim();
    $('btnApprove').disabled = blocked !== null;
    $('btnReject').disabled = blocked !== null || reason.length === 0;
    var notice = $('decideBlocked');
    notice.textContent = blocked || '';
    notice.hidden = blocked === null;
  }

  function result(message, kind) {
    var node = $('decideResult');
    node.className = 'decide-result ' + (kind || '');
    node.textContent = message;
  }

  function decide(kind) {
    if (!state.currentId) { return; }
    var path = '/api/admin/drafts/' + encodeURIComponent(state.currentId) + '/' + kind;
    var reason = kind === 'approve' ? $('approveReason').value : $('rejectReason').value;
    var body = {};
    if (reason.trim().length > 0) { body.reason = reason.trim(); }

    request('POST', path, body).then(function (payload) {
      var message = (kind === 'approve' ? '승인했습니다' : '반려했습니다')
        + ' · 승인기록 ' + payload.approvalRecordId
        + (payload.ruleVersionId ? ' · 규칙버전 ' + payload.ruleVersionId : '');
      state.selectedIds = [];
      // 승인·반려는 초안을 `pending` 에서 빼므로 병합 상태가 달라진다 (SPEC 6.4, 잠정).
      // 신고 큐를 다시 읽지 않으면 화면이 이미 끝난 초안과 묶인 신고를 계속 보인다.
      return loadQueue()
        .then(loadReports)
        .then(function () { return openDraft(state.currentId); })
        .then(function () { result(message, 'ok'); });
    }).catch(function (error) {
      result('[' + error.code + '] ' + error.message, 'err');
    });
  }

  function batchApprove() {
    if (state.selectedIds.length === 0) { return; }
    var reason = $('approveReason').value.trim();
    var body = { draftIds: state.selectedIds };
    if (reason.length > 0) { body.reason = reason; }

    request('POST', '/api/admin/drafts/batch-approve', body).then(function (payload) {
      var message = '일괄 승인 ' + payload.results.length + '건 — 승인기록이 건별로 남았습니다: '
        + payload.results.map(function (r) { return r.approvalRecordId; }).join(', ');
      state.selectedIds = [];
      // 승인·반려는 대기 건수와 최장 대기일을 바꾼다. 지표를 다시 읽지 않으면
      // 화면 위쪽이 방금 처리한 초안을 계속 대기 중으로 보인다.
      return loadQueue().then(loadReports).then(loadStatus)
        .then(function () { result(message, 'ok'); });
    }).catch(function (error) {
      // 원자성 — 하나라도 실패하면 **아무것도 반영되지 않는다.** 그 사실을 적는다.
      result('[' + error.code + '] ' + error.message + ' · 아무것도 반영되지 않았습니다.', 'err');
      return loadQueue();
    });
  }

  // ------------------------------------------------------------------
  // 배선
  // ------------------------------------------------------------------

  function connect() {
    return request('GET', '/api/health').then(function (payload) {
      $('connDot').className = 'conn-dot ok';
      $('connText').textContent = '연결됨 · LLM ' + payload.llm;
    }).catch(function () {
      $('connDot').className = 'conn-dot bad';
      $('connText').textContent = '백엔드에 연결하지 못했습니다';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('loginForm').addEventListener('submit', function (event) {
      event.preventDefault();
      note('');
      request('POST', '/api/auth/login', {
        username: $('username').value,
        password: $('password').value
      }).then(function () {
        return refreshSession();
      }).then(function () {
        if (state.role === 'rule_manager') { return loadQueue().then(loadReports).then(loadStatus); }
        return null;
      }).catch(function (error) { note(error.message); });
    });

    $('btnLogout').addEventListener('click', function () {
      request('POST', '/api/auth/logout', {}).catch(function () { return null; }).then(function () {
        state.csrf = null;
        state.role = null;
        state.username = null;
        state.currentId = null;
        state.selectedIds = [];
        $('review').hidden = true;
        $('reviewEmpty').hidden = false;
        renderIdentity();
      });
    });

    $('rejectReason').addEventListener('input', syncRejectButton);
    $('btnApprove').addEventListener('click', function () { decide('approve'); });
    $('btnReject').addEventListener('click', function () { decide('reject'); });
    $('btnBatch').addEventListener('click', batchApprove);

    connect();
    refreshSession().then(function () {
      if (state.role === 'rule_manager') { return loadQueue().then(loadReports).then(loadStatus); }
      return null;
    }).catch(function () { return null; });
  });
}());
