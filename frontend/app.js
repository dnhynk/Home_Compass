/* ============================================================
   Home_Compass · frontend controller
   Vanilla JS. No framework, no bundler, no external request.
   Charts are hand-built inline SVG.

   ── 손으로 쓴 판정값이 이 파일에 없다 (SPEC D-11) ──────────────────────────
   상수 · 정책 규칙 · 지역 시세 · 타임아웃은 전부 `frontend/generated/*.js`
   에서 온다 (계약 결정 #34). 로컬 판정 경로는 `local_engine.js` 가 지고,
   포맷은 `format.js` 가 진다. 이 파일은 **화면과 API 계층**만 맡는다.

   생성물이 없으면 로컬 판정 경로는 **동작하지 않고 화면에 그렇게 적는다.**
   기본값·빈 값으로 메우지 않는다 (SPEC 6.2 오프라인 정의 #3).
   ============================================================ */
(function () {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     0. CONFIG
     ══════════════════════════════════════════════════════════ */
  var API_BASE = (typeof location !== 'undefined' && location.protocol !== 'file:' && location.origin && location.origin !== 'null')
    ? location.origin
    : 'http://127.0.0.1:8000';

  var FMT = window.HomeCompassFormat;
  var LOCAL = window.HomeCompassLocalEngine;

  /* 타임아웃은 계약에서 유도한다. 프론트가 숫자를 다시 쓰지 않는다 (SPEC 8.3 #3 · #4).
     경로별 예산을 하나로 합치지 않는다 — 합치면 chat 기준으로 잡혀 analyze 가 75초를
     기다리거나, analyze 기준으로 잡혀 chat 이 다시 잘린다. 후자가 예선 사고다. */
  function timeoutFor(path) {
    var contract = window.HOME_COMPASS_CONTRACT_CONSTANTS;
    if (!contract) {
      throw new Error('생성물 HOME_COMPASS_CONTRACT_CONSTANTS 이 없어 타임아웃을 정할 수 없습니다.');
    }
    var bc = contract.boundaryConditions;
    return bc.profiles[bc.clientDispatch.byPath[path] || bc.clientDispatch.default].clientTimeoutMs;
  }

  /* categorical series — validated (adjacent CVD ΔE 9.2, normal-vision 27.6,
     light surface #ffffff). Order is the CVD-safety mechanism: do not shuffle. */
  var SERIES = {
    s1: '#2A78D6',  /* 대출이자   */
    s2: '#EB6834',  /* 월세       */
    s3: '#1BAF7A',  /* 관리비     */
    s4: '#4A3AA7',  /* 기회비용   */
    s5: '#E87BA4',  /* 보증보험료 */
    neutral: '#DCD7CC'
  };
  var STATUS = { good: '#0CA30C', caution: '#EC835A', critical: '#D03B3B' };

  var BAND_META = {
    safe:    { label: '안전',   cls: 'chip-good',     color: STATUS.good,     icon: 'check' },
    caution: { label: '주의',   cls: 'chip-caution',  color: STATUS.caution,  icon: 'alert' },
    risk:    { label: '위험',   cls: 'chip-critical', color: STATUS.critical, icon: 'alert' }
  };
  var RISK_BAND_META = {
    low:    { label: '위험 낮음', cls: 'chip-good',     color: STATUS.good,     icon: 'check' },
    medium: { label: '주의 필요', cls: 'chip-caution',  color: STATUS.caution,  icon: 'alert' },
    high:   { label: '위험 높음', cls: 'chip-critical', color: STATUS.critical, icon: 'alert' }
  };
  var VERDICT_META = {
    affordable:   { label: '감당 가능', cls: 'chip-good',     icon: 'check' },
    stretch:      { label: '다소 부담', cls: 'chip-caution',  icon: 'alert' },
    unaffordable: { label: '무리',      cls: 'chip-critical', icon: 'alert' }
  };
  var POLICY_META = {
    eligible:    { label: '적격',   cls: 'chip-good',    icon: 'check' },
    conditional: { label: '조건부', cls: 'chip-caution', icon: 'alert' },
    ineligible:  { label: '부적격', cls: 'chip-neutral', icon: 'minus' }
  };

  var STATE = {
    regions: [],
    connection: 'checking',   /* checking | live | offline | local | disabled */
    llmMode: 'offline',
    lastResult: null,
    lastProfile: null,
    lastSource: null,         /* 'backend' | 'local' — 어느 경로가 이 숫자를 냈는가 */
    session: { authenticated: false, username: null, role: null, csrfToken: null },
    policyFilter: 'all',
    chatHistory: [],
    chatBusy: false,
    /* 열려 있는 이상 신고 대화상자의 대상 (SPEC 6.4). 닫히면 `null`. */
    report: null
  };

  /** 로컬 판정 경로가 성립하는가. 성립하지 않으면 무엇이 없는지까지 돌려준다. */
  function localStatus() {
    if (!LOCAL) {
      return { ready: false, missing: [{ file: 'local_engine.js', label: '로컬 판정 경로' }] };
    }
    return LOCAL.status();
  }

  /* ══════════════════════════════════════════════════════════
     1. UTILITIES
     ══════════════════════════════════════════════════════════ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function num(v, fallback) { var n = Number(v); return isFinite(n) ? n : (fallback || 0); }

  /* 포맷 함수는 **여기에 없다.** `frontend/format.js` 가 JS 변의 유일한 구현이고,
     `contracts/format_golden.json` 이 파이썬 변과 같은 파일로 그것을 붙든다
     (SPEC 9.1.1 — 「엔진·화면 어디서도 픽스처를 우회한 자체 포맷을 만들지 않는다」).
     아래 셋은 이름만 잇는 얇은 별칭이다.

     ★ 값이 없으면 **던진다.** 예전 `pct()` 는 `num(v, 0)` 으로 메워서
       `affordability.schwabeIndexPct` 가 사라진 응답을 "0.0%" 로 그렸다 —
       F-1 파손 ①②④ 가 정확히 그것이다 (PR #24 §6). 지어낸 0 보다 멈추는 편이 낫다. */
  function fmtKR(v, withUnit) { return withUnit === false ? FMT.moneyNoUnit(v) : FMT.money(v); }
  function fmtWon(v) { return FMT.won(v); }
  function fmtAxis(v) { return FMT.moneyNoUnit(v); }
  function pct(v, digits) { return FMT.pct(v, digits); }

  /** 값이 없을 수 있는 자리 — `null` 은 0 이 아니라 「잴 수 없음」이다 (SPEC 5.2.1). */
  function pctOrDash(v, digits) { return v == null ? '—' : FMT.pct(v, digits); }

  function iconSVG(kind) {
    if (kind === 'check') {
      return '<svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">' +
        '<path d="M2.6 7.4 5.6 10.4 11.4 3.9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
    if (kind === 'alert') {
      return '<svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">' +
        '<path d="M7 2.4 13 12H1Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
        '<path d="M7 6v2.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
        '<circle cx="7" cy="10.2" r=".85" fill="currentColor"/></svg>';
    }
    return '<svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">' +
      '<path d="M3 7h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  }
  /* 백엔드 서술문에 열거형 토큰이 그대로 섞여 나올 때가 있어 표시 단계에서 한글 라벨로 바꾼다.
     숫자는 손대지 않는다. (근본 수정은 백엔드 문구 쪽) */
  var ENUM_LABELS = {
    affordable: '감당 가능', unaffordable: '무리', stretch: '다소 부담',
    eligible: '적격', conditional: '조건부', ineligible: '부적격'
  };
  function humanizeEnums(s) {
    return String(s == null ? '' : s).replace(
      /\b(unaffordable|affordable|stretch|ineligible|conditional|eligible)\b/g,
      function (m) { return ENUM_LABELS[m] || m; });
  }

  function chipHTML(meta, size) {
    return '<span class="chip ' + meta.cls + (size ? ' ' + size : '') + '">' +
      iconSVG(meta.icon) + esc(meta.label) + '</span>';
  }

  /* ==========================================================
     2. 로컬 판정 경로 어댑터 (SPEC D-11 · 6.2 오프라인 정의)

     판정 사본은 이 파일에 **없다.** `frontend/local_engine.js` 가 백엔드 네 엔진의
     충실한 이식이고, 상수·정책 규칙·지역 시세는 `frontend/generated/*.js` 에서 온다.

     예전에는 여기에 `MOCK_REGIONS` 9건 · `POLICY_CATALOG` 9건 · 인라인 상수
     (`0.40` · `0.10` · `0.30` · `0.85` · `0.25` · `0.20`) · `MOCK_RESPONSE` 가 있었고,
     그것들이 백엔드와 **별개로** 자랐다. 지역은 코드가 2건만 겹쳤고 그중 둘은
     2026-07-01 통합으로 폐지된 코드였다(PR #59). 손으로 쓴 데이터가 조용히 낡는다는
     D-11 의 논거 그 자체이므로 전부 걷어냈다.

     * **정적 폴백을 두지 않는다.** 예전 `MOCK_RESPONSE` 는 로컬 엔진까지 실패해도
       화면이 뜨게 하는 장치였는데, 그것이 곧 「출처 없는 숫자를 판정인 척 보여 주는」
       경로였다 (게다가 사라진 `affordability.schwabeIndexPct: 25.0` 을 아직 들고 있었다).
       생성물이 없으면 숫자를 내지 않고 **화면에 그렇게 적는다.**
     ========================================================== */

  /** 로컬 경로의 지역 목록 — 생성물의 `payload` 가 곧 엔진 입력이다. */
  function localRegions() {
    return LOCAL.regions().map(function (record) { return record.payload; });
  }

  /** 로컬 판정. 시각을 주입한다 (SPEC 5.3) — 이 경로에도 같은 규율을 건다. */
  function localAnalyze(profile) {
    return LOCAL.analyze(profile, { now: Date.now() });
  }

  function findRegion(code) {
    var pool = STATE.regions;
    for (var i = 0; i < pool.length; i++) if (pool[i].code === code) return pool[i];
    return null;
  }

  /* ══════════════════════════════════════════════════════════
     3. INLINE SVG CHARTS
     ══════════════════════════════════════════════════════════ */
  function tipAttr(title, rows) {
    var html = '<b>' + esc(title) + '</b>';
    (rows || []).forEach(function (r) {
      html += '<br><span class="tip-key">' + esc(r[0]) + '</span> <b>' + esc(r[1]) + '</b>';
    });
    return ' data-tip="' + esc(html) + '"';
  }

  /* `polar()` · `arcPath()` 는 반원 게이지 전용이었고 게이지를 걷어내면서 함께 지웠다.
     쓰지 않는 헬퍼를 남겨 두면 다음 사람이 그것을 근거로 게이지를 되살린다. */

  /**
   * 시나리오별 슈바베지수 — **상한 없는 측정값**을 그린다 (SPEC 5.2.1 F-1).
   *
   * ── 왜 반원 게이지를 버렸는가 ─────────────────────────────────────────────
   * 예전 `gaugeSVG` 는 `DOMAIN = 45` 에 `clamp` 였고 구간이 「안전 25 / 주의 30 /
   * 위험 45+」였다. 그 눈금은 **권장액의 소득 비중**(상한 규칙이 0.25 근처에 붙여 두던
   * 값)에 맞춰 잡힌 것이다. F-1 이후 이 지표는 시나리오별 **실측 주거비/소득**이고
   * 실측에서 109.5% 가 나온다 — 45 이상이 전부 같은 위치로 포화해 **서로 다른 부담을
   * 구분하지 못한다**(PR #24 §6 ③). 게다가 값이 하나가 아니라 시나리오마다 다르므로
   * 하나를 골라 게이지에 얹는 것은 임의 선택이다(5.2.1 이 최상위 단일값을 금지한 이유).
   *
   * ── 무엇으로 바꿨고 왜 그 방식인가 ────────────────────────────────────────
   * 1. **시나리오마다 한 줄.** 값이 여러 개이므로 표시도 여러 개다. 비교가 목적인
   *    화면에서 하나만 보여 주면 나머지는 없는 것이 된다.
   * 2. **척도는 데이터에서 나온다.** 도메인은 `max(100, 실측 최대값을 10 단위로 올림)`.
   *    상한을 상수로 박지 않으므로 109.5% 도 잘리지 않는다. 100% 를 항상 포함하는 이유는
   *    그것이 규범이 아니라 **사실**이기 때문이다 — 주거비가 소득과 같아지는 지점.
   * 3. **기준선은 응답에서 유도한다.** 권장액/소득 · 상한/소득 두 선을 그리되, 값은
   *    `affordability` 에서 계산한다. 화면이 30 이나 25 를 다시 쓰지 않는다(SPEC 5.1.2).
   *    그리고 그 둘은 측정값이 아니라 **규칙값**이라고 라벨에 적는다.
   * 4. **`null` 은 0 이 아니다.** 소득이 0이면 주거비/소득은 정의되지 않으므로
   *    막대를 그리지 않고 「잴 수 없음」이라고 쓴다. 0.0% 로 메우면 「주거비가 소득의
   *    0%」라는 거짓말이 된다 (계약이 이 필드를 nullable 로 바꾼 이유).
   * 5. 색은 백엔드가 이미 내린 `verdict` 를 따른다. 화면이 구간을 새로 정하지 않는다.
   */
  function schwabeChartHTML(scenarios, affordability) {
    var breakdown = affordability.breakdown || {};
    var netIncome = num(breakdown.netIncome);
    var measured = scenarios
      .map(function (s) { return s.schwabeIndexPct; })
      .filter(function (v) { return v != null; });

    if (!measured.length) {
      return '<p class="schwabe-empty">월 실수령액이 0이라 <b>주거비 ÷ 소득</b>을 잴 수 없습니다. ' +
        '0%로 대신 표시하지 않습니다 — 「주거비가 없다」와 「소득이 없어 잴 수 없다」는 다른 사실입니다.</p>';
    }

    var dataMax = Math.max.apply(null, measured);
    var domain = Math.max(100, Math.ceil(dataMax / 10) * 10);
    var toPct = function (v) { return (v / domain) * 100; };

    var refs = [];
    if (netIncome > 0) {
      refs.push({
        at: num(affordability.recommendedMonthlyHousingCostKRW) / netIncome * 100,
        label: '권장액', kind: 'rec'
      });
      refs.push({
        at: num(affordability.maxMonthlyHousingCostKRW) / netIncome * 100,
        label: '상한', kind: 'max'
      });
    }

    var rows = scenarios.map(function (s) {
      var v = s.schwabeIndexPct;
      var meta = VERDICT_META[s.verdict] || VERDICT_META.stretch;
      var color = s.verdict === 'affordable' ? STATUS.good
        : s.verdict === 'stretch' ? STATUS.caution : STATUS.critical;
      var bar = v == null
        ? '<span class="schwabe-na">잴 수 없음</span>'
        : '<svg class="viz" width="100%" height="18" style="height:18px" role="img" aria-label="' +
          esc(s.label + ' 슈바베지수 ' + pct(v)) + '">' +
          '<rect x="0" y="4" width="100%" height="10" rx="5" fill="' + SERIES.neutral + '" fill-opacity=".55"></rect>' +
          '<rect x="0" y="4" width="' + toPct(v).toFixed(3) + '%" height="10" rx="5" fill="' + color + '"' +
          tipAttr(s.label, [['슈바베지수', pct(v)], ['월 환산 주거비', fmtKR(s.monthlyEquivalentCostKRW)],
                            ['월 실수령액', fmtKR(netIncome)], ['판정', meta.label]]) + '></rect>' +
          '</svg>';
      return '<li class="schwabe-row">' +
        '<span class="schwabe-name">' + esc(s.label) + '</span>' +
        '<span class="schwabe-bar">' + bar + '</span>' +
        '<span class="schwabe-val">' + esc(pctOrDash(v)) + '</span></li>';
    }).join('');

    var marks = refs.filter(function (r) { return r.at > 0 && r.at <= domain; }).map(function (r) {
      return '<span class="schwabe-mark schwabe-mark-' + r.kind + '" style="left:' + toPct(r.at).toFixed(3) + '%">' +
        '<i></i><b>' + esc(r.label) + ' ' + esc(pct(r.at)) + '</b></span>';
    }).join('');

    return '<ul class="schwabe-rows">' + rows + '</ul>' +
      '<div class="schwabe-axis"><span style="left:0%">0%</span>' + marks +
      '<span class="schwabe-axis-end" style="left:100%">' + esc(pct(domain, 0)) + '</span></div>' +
      '<p class="schwabe-note">기준선 둘(권장액·상한)은 <b>측정값이 아니라 규칙값</b>입니다. ' +
      '막대는 각 시나리오의 <b>실제 월 환산 주거비 ÷ 월 실수령액</b>이며 상한이 없습니다.</p>';
  }

  /**
   * 가로 스택 막대. 퍼센트 좌표로 그려 컨테이너 폭이 변해도 라운드 코너가
   * 찌그러지지 않는다. 세그먼트 사이에는 표면색 간격을 둔다.
   * opts.max 를 주면 그 값을 100% 기준으로 삼아 여러 막대를 서로 비교할 수 있다.
   */
  function stackedBarSVG(segments, opts) {
    opts = opts || {};
    var H = opts.height || 40;
    var R = Math.min(5, H / 2);
    var GAP = H > 16 ? 0.9 : 0.6;   /* percent */
    var total = segments.reduce(function (a, b) { return a + Math.max(0, b.value); }, 0) || 1;
    var base = opts.max && opts.max > 0 ? opts.max : total;
    var live = segments.filter(function (s) { return s.value > 0; });

    var s = '<svg class="viz" width="100%" height="' + H + '" style="height:' + H + 'px" ' +
      'role="img" aria-label="' + esc(opts.aria || '구성비 막대') + '">';
    var x = 0;
    live.forEach(function (seg, i) {
      var raw = (seg.value / base) * 100;
      var w = Math.max(0.7, raw - (i < live.length - 1 ? GAP : 0));
      s += '<rect class="seg" x="' + x.toFixed(3) + '%" y="0" width="' + w.toFixed(3) + '%" height="' + H +
        '" rx="' + R + '" fill="' + seg.color + '"' +
        tipAttr(seg.label, [['금액', fmtWon(seg.value)], ['비중', pct(seg.value / total * 100)]]) + '></rect>';
      x += raw;
    });
    s += '</svg>';
    return s;
  }

  function legendHTML(segments, total) {
    return segments.filter(function (s) { return s.value > 0; }).map(function (s) {
      return '<li><span class="legend-swatch" style="background:' + s.color + '"></span>' +
        esc(s.label) + ' <span class="legend-val">' + fmtKR(s.value) +
        (total ? ' · ' + pct(s.value / total * 100, 0) : '') + '</span></li>';
    }).join('');
  }

  /**
   * 시나리오별 5년 총비용 비교. 라벨·눈금은 실제 HTML 텍스트로 두고 막대만 SVG 로
   * 그려서, 폭이 좁아져도 글자가 함께 줄어드는 viewBox 스케일 문제를 피한다.
   * 모든 막대는 최대값을 공통 기준으로 삼아 길이 비교가 성립한다.
   */
  function tcoChartHTML(scenarios, keys) {
    var maxV = Math.max.apply(null, scenarios.map(function (s) { return s.tco5yKRW; })) || 1;
    var rows = scenarios.map(function (sc) {
      var segs = keys.map(function (k) {
        return { label: k.label, value: sc.components[k.key] || 0, color: k.color };
      });
      return '<li class="tco-row">' +
        '<div class="tco-row-top">' +
          '<span class="tco-row-name">' + esc(sc.label) + '</span>' +
          '<span class="tco-row-val">' + esc(fmtKR(sc.tco5yKRW)) + '</span>' +
        '</div>' +
        '<div class="tco-row-bar">' +
          stackedBarSVG(segs, { height: 24, max: maxV, aria: sc.label + ' 5년 총비용 구성' }) +
        '</div></li>';
    }).join('');

    /* Ticks carry their own position so they sit on the 25% gridlines under the
       bars rather than being distributed by space-between. */
    var ticks = '';
    for (var i = 0; i <= 4; i++) {
      ticks += '<span style="left:' + (i * 25) + '%">' + esc(fmtAxis(maxV / 4 * i)) + '</span>';
    }
    return '<ul class="tco-rows">' + rows + '</ul><div class="tco-axis">' + ticks + '</div>';
  }

  /** 리스크 미터 — 3구간 트랙 + 마커 */
  function riskMeterSVG(score, band) {
    var W = 320, H = 62, TRACK_Y = 22, TH = 14;
    var zones = [
      { from: 0, to: 33, color: STATUS.good, label: '낮음' },
      { from: 33, to: 60, color: STATUS.caution, label: '주의' },
      { from: 60, to: 100, color: STATUS.critical, label: '높음' }
    ];
    var s = '<svg class="viz" viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
      'aria-label="보증금 리스크 점수 ' + score + '점, ' + RISK_BAND_META[band].label + '">';
    zones.forEach(function (z) {
      var x = (z.from / 100) * W, w = ((z.to - z.from) / 100) * W - 3;
      s += '<rect x="' + x.toFixed(1) + '" y="' + TRACK_Y + '" width="' + w.toFixed(1) + '" height="' + TH +
        '" rx="4" fill="' + z.color + '" fill-opacity=".2"' +
        tipAttr('위험 ' + z.label, [['구간', z.from + ' ~ ' + z.to + '점']]) + '></rect>';
      s += '<text class="tick" x="' + (x + w / 2).toFixed(1) + '" y="' + (TRACK_Y + TH + 15) +
        '" text-anchor="middle">' + esc(z.label) + '</text>';
    });
    var mx = clamp((score / 100) * W, 8, W - 8);
    s += '<rect x="' + (mx - 2.5).toFixed(1) + '" y="' + (TRACK_Y - 6) + '" width="5" height="' + (TH + 12) +
      '" rx="2.5" fill="#fff"/>';
    s += '<rect x="' + (mx - 1.5).toFixed(1) + '" y="' + (TRACK_Y - 4) + '" width="3" height="' + (TH + 8) +
      '" rx="1.5" fill="' + RISK_BAND_META[band].color + '"/>';
    s += '<text class="bar-value" x="' + mx.toFixed(1) + '" y="' + (TRACK_Y - 10) + '" text-anchor="middle">' +
      score + '</text>';
    s += '</svg>';
    return s;
  }

  /** 적합도 도넛 링 */
  function fitRingSVG(score, color) {
    var S = 40, c = S / 2, r = 15.5, sw = 4.2;
    var circ = 2 * Math.PI * r;
    var on = circ * clamp(score, 0, 100) / 100;
    /* fit-ring, not viz: .viz is fluid (width:100%) and stretched this glyph. */
    return '<svg class="fit-ring" width="' + S + '" height="' + S + '" viewBox="0 0 ' + S + ' ' + S +
      '" role="img" aria-label="적합도 ' + score + '점">' +
      '<circle cx="' + c + '" cy="' + c + '" r="' + r + '" fill="none" stroke="#EDEAE2" stroke-width="' + sw + '"/>' +
      '<circle cx="' + c + '" cy="' + c + '" r="' + r + '" fill="none" stroke="' + color +
      '" stroke-width="' + sw + '" stroke-linecap="round" stroke-dasharray="' + on.toFixed(2) + ' ' + circ.toFixed(2) +
      '" transform="rotate(-90 ' + c + ' ' + c + ')"/></svg>';
  }

  /* tooltip layer */
  function bindTips(root) {
    $$('[data-tip]', root).forEach(function (node) {
      node.addEventListener('mouseenter', showTip);
      node.addEventListener('mousemove', moveTip);
      node.addEventListener('mouseleave', hideTip);
    });
  }
  function showTip(e) {
    var tip = $('#vizTip');
    if (!tip) return;
    tip.innerHTML = e.currentTarget.getAttribute('data-tip');
    tip.hidden = false;
    moveTip(e);
  }
  function moveTip(e) {
    var tip = $('#vizTip');
    if (!tip || tip.hidden) return;
    tip.style.left = clamp(e.clientX, 90, (window.innerWidth || 1200) - 90) + 'px';
    tip.style.top = Math.max(60, e.clientY - 14) + 'px';
  }
  function hideTip() { var tip = $('#vizTip'); if (tip) tip.hidden = true; }

  /* ══════════════════════════════════════════════════════════
     4. RENDERING
     ══════════════════════════════════════════════════════════ */
  var ALLOC_KEYS = [
    { key: 'housing', label: '주거비(권장)', color: SERIES.s1 },
    { key: 'living', label: '생활비', color: SERIES.s2 },
    { key: 'debt', label: '기존 부채 상환', color: SERIES.s3 },
    { key: 'buffer', label: '비상 버퍼', color: SERIES.s4 },
    { key: 'rest', label: '잔여 여유자금', color: SERIES.neutral }
  ];
  var TCO_KEYS = [
    { key: 'interest', label: '대출이자', color: SERIES.s1 },
    { key: 'rent', label: '월세', color: SERIES.s2 },
    { key: 'maintenance', label: '관리비', color: SERIES.s3 },
    { key: 'opportunityCost', label: '보증금 기회비용', color: SERIES.s4 },
    { key: 'insurance', label: '보증료', color: SERIES.s5 }
  ];

  function renderAffordability(a, profile, scenarios) {
    var meta = BAND_META[a.band] || BAND_META.caution;
    $('#bandChip').outerHTML = '<span class="chip chip-lg ' + meta.cls + '" id="bandChip">' +
      iconSVG(meta.icon) + '지불능력 ' + esc(meta.label) + '</span>';

    $('#recAmount').innerHTML = esc(fmtKR(a.recommendedMonthlyHousingCostKRW, false)) + '<span class="cur">원 / 월</span>';
    $('#maxAmount').textContent = fmtKR(a.maxMonthlyHousingCostKRW);
    /* F-1 (SPEC 5.2.1) — 여기에 있던 `<dt>슈바베지수</dt>` 는 사라졌다. 그 자리 값은
       `affordability.schwabeIndexPct` 였는데 그것은 측정값이 아니라 상한 규칙의
       되풀이였고 계약에서 제거됐다. 대신 **권장액이 소득에서 차지하는 비중**을 응답의
       두 필드로 재현해 보이되, 이름에 「규칙값」을 박아 측정값과 구분한다. */
    var netIncome = num((a.breakdown || {}).netIncome);
    $('#recShare').textContent = netIncome > 0
      ? pct(num(a.recommendedMonthlyHousingCostKRW) / netIncome * 100)
      : '—';
    $('#netIncomeStat').textContent = fmtKR(a.breakdown.netIncome);
    $('#assetStat').textContent = fmtKR(profile.liquidAssetsKRW);

    $('#schwabeSlot').innerHTML = schwabeChartHTML(scenarios || [], a);

    var b = a.breakdown;
    var rest = Math.max(0, b.netIncome - a.recommendedMonthlyHousingCostKRW - b.livingCost - b.existingDebt - b.buffer);
    var vals = {
      housing: a.recommendedMonthlyHousingCostKRW,
      living: b.livingCost, debt: b.existingDebt, buffer: b.buffer, rest: rest
    };
    var segs = ALLOC_KEYS.map(function (k) { return { label: k.label, value: vals[k.key], color: k.color }; });
    $('#allocSlot').innerHTML = stackedBarSVG(segs, { height: 40, aria: '월 소득 배분' });
    $('#allocLegend').innerHTML = legendHTML(segs, b.netIncome);
    $('#allocTotal').textContent = '월 실수령 ' + fmtKR(b.netIncome) + ' 기준';

    $('#affordRationale').innerHTML = (a.rationale || []).map(function (t) {
      return '<li>' + esc(t) + '</li>';
    }).join('');
  }

  function renderScenarios(list) {
    if (!list || !list.length) { $('#cardScenarios').hidden = true; return; }
    $('#cardScenarios').hidden = false;

    $('#tcoChartSlot').innerHTML = tcoChartHTML(list, TCO_KEYS);
    $('#tcoLegend').innerHTML = TCO_KEYS.filter(function (k) {
      return list.some(function (s) { return (s.components[k.key] || 0) > 0; });
    }).map(function (k) {
      return '<li><span class="legend-swatch" style="background:' + k.color + '"></span>' + esc(k.label) + '</li>';
    }).join('');

    var best = list.reduce(function (a, b) { return b.fitScore > a.fitScore ? b : a; }, list[0]);

    $('#scenarioGrid').innerHTML = list.map(function (s) {
      var v = VERDICT_META[s.verdict] || VERDICT_META.stretch;
      var ringColor = s.verdict === 'affordable' ? STATUS.good : s.verdict === 'stretch' ? STATUS.caution : STATUS.critical;
      var segs = TCO_KEYS.map(function (k) { return { label: k.label, value: s.components[k.key] || 0, color: k.color }; });
      var terms = [];
      terms.push('보증금 ' + fmtKR(s.depositKRW));
      if (s.monthlyRentKRW > 0) terms.push('월세 ' + fmtKR(s.monthlyRentKRW));
      if (s.loanAmountKRW > 0) terms.push('대출 ' + fmtKR(s.loanAmountKRW) + ' @ ' + pct(s.loanRatePct, 2));

      return '<article class="scenario' + (s.id === best.id ? ' is-best' : '') + '">' +
        (s.id === best.id ? '<span class="sc-flag">추천</span>' : '') +
        '<div class="sc-top"><div><p class="sc-name">' + esc(s.label) + '</p>' +
          '<p class="sc-type">' + (s.type === 'jeonse' ? '전세' : '월세 · 반전세') + '</p></div>' +
          chipHTML(v, 'chip-sm') + '</div>' +
        '<div class="sc-cost-row"><p class="sc-cost">' + esc(fmtKR(s.monthlyEquivalentCostKRW, false)) +
          '<small>원 / 월 환산</small></p></div>' +
        '<div class="sc-terms">' + terms.map(function (t) { return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' +
        '<div><div class="sc-bar-label"><span>5년 총비용 구성</span>' +
          '<span class="sc-tco">' + esc(fmtKR(s.tco5yKRW)) + '</span></div>' +
          stackedBarSVG(segs, { height: 10, aria: s.label + ' 총비용 구성' }) + '</div>' +
        '<ul class="sc-rationale">' + (s.rationale || []).slice(0, 3).map(function (t) {
          return '<li>' + esc(t) + '</li>';
        }).join('') + '</ul>' +
        '<div class="sc-foot"><span class="fit-label">현재가치(NPV) ' + esc(fmtKR(s.npv5yKRW)) + '</span>' +
          '<span class="fit">' + fitRingSVG(s.fitScore, ringColor) +
          '<span><span class="fit-num">' + s.fitScore + '</span>' +
          '<span class="fit-label"> / 100 적합도</span></span></span></div>' +
        '</article>';
    }).join('');
  }

  function renderPolicies(list) {
    var filtered = STATE.policyFilter === 'all'
      ? list : list.filter(function (p) { return p.status === STATE.policyFilter; });

    if (!filtered.length) {
      $('#policyList').innerHTML = '<li class="policy" style="grid-template-columns:1fr"><p class="policy-src">' +
        '해당 상태의 제도가 없습니다.</p></li>';
      return;
    }
    $('#policyList').innerHTML = filtered.map(function (p) {
      var meta = POLICY_META[p.status] || POLICY_META.conditional;
      var side = '';
      if (p.maxAmountKRW) side += '<span class="policy-num"><small>최대 한도</small>' + esc(fmtKR(p.maxAmountKRW)) + '</span>';
      if (p.rateRangePct && p.rateRangePct.length === 2) {
        side += '<span class="policy-num"><small>금리(예시)</small>' +
          esc(num(p.rateRangePct[0]).toFixed(2)) + '~' + esc(num(p.rateRangePct[1]).toFixed(2)) + '%</span>';
      }
      return '<li class="policy" data-status="' + esc(p.status) + '">' +
        '<div class="policy-main">' +
          '<div class="policy-top">' + chipHTML(meta, 'chip-sm') +
            '<span class="policy-name">' + esc(p.name) + '</span>' +
            '<span class="policy-cat">' + esc(p.category) + '</span></div>' +
          /* SPEC 6.1 「왜 그렇게 판정했는지」 — 충족과 미충족이 **같은 체크 표식**으로
             늘어서면 어느 줄이 이 제도를 떨어뜨렸는지 화면에서 알 수 없다. 가르는
             기준은 응답의 `failures` 다. 사유 문자열의 "미충족" 을 매칭하지 않는다 —
             SPEC 5.3 이 문자열을 계약으로 보지 않으므로 문구를 다듬는 순간 조용히
             깨진다. `failures` 는 `reasons` 의 부분집합이고 원문 그대로 실린다.
             필드가 없는 응답(구 계약)에서는 빈 목록이 되어 현행 표시로 되돌아간다. */
          '<ul class="policy-reasons">' + (p.reasons || []).map(function (r) {
            if ((p.failures || []).indexOf(r) < 0) return '<li>' + esc(r) + '</li>';
            /* 낭독 순서에서도 분류가 문장보다 앞선다 — 표식이 시각적으로 주는 것과 같다. */
            return '<li data-met="false"><span class="sr-only">미충족 사유 — </span>' +
              esc(r) + '</li>';
          }).join('') + '</ul>' +
          '<p class="policy-src"><b>출처</b> ' + esc(p.source || '—') +
            (p.disclaimer ? ' · ' + esc(p.disclaimer) : '') + '</p>' +
          /* SPEC 6.4 — 제도 **항목별**로 신고한다. 어느 항목인지는 대화상자가 목록으로
             묻는다. 익명이면 이 자리가 빈 문자열이다. */
          reportButtonHTML('policy', p.id, p.name) +
        '</div>' +
        '<div class="policy-side">' + side + '</div></li>';
    }).join('');
  }

  /* ── 이상 신고 (SPEC 6.4 · 7.1) ───────────────────────────────────────────
     「상담원은 데이터 오류의 **최전선 탐지자**다. 고객 앞에서 *그 제도 지난달에
      없어졌는데요* 를 듣는 사람은 상담원이지 규칙관리자가 아니다.」

     ★ **익명에는 없다.** 세션이 없으면 이 함수들이 빈 문자열을 낸다. 그러나 그것은
       편의이지 권한이 아니다 — API 가 익명 요청을 401 로 막는다 (SPEC 6.1).
     ★ **대상은 자유 텍스트가 아니다** (SPEC 7.1). 항목 목록을 이 파일에 적어 두지
       않고 **방금 그린 응답 객체에서 만든다.** 손으로 적으면 백엔드의 허용 목록에
       이어 세 번째 사본이 되고, 스키마가 바뀔 때 조용히 어긋난다.
     ★ 신고는 **제안이지 변경이 아니다.** 이 화면에는 규칙을 바꾸는 경로가 없다. */

  var REPORT_PRIVACY_NOTICE =
    '고객 개인정보를 적지 마세요. 이름·연락처·생년월일·계좌 같은 개인정보는 ' +
    '신고 사유에 쓰지 않습니다. 신고는 제도·시세 데이터의 오류를 알리는 것이며, ' +
    '이 칸의 내용은 감사기록에 그대로 남아 지울 수 없습니다.';

  /* 신고 대상이 **아닌** 키. 나머지는 전부 신고할 수 있는 항목이다.
     · policy — `id` 는 대상 그 자체이고, `disclaimer` 는 엔진이 붙이는 고정 문구다.
       `failures` 는 `reasons` 의 부분집합이고 문자열이 같다 — 두 항목이 같은 사실을
       가리키면 감사기록의 「어느 항목인가」가 두 곳을 가리키게 된다. 사유의 오류는
       `reasons` 로 신고한다. (저장소의 `POLICY_REPORT_FIELDS` 도 이 셋을 뺀 값이다.)
     · region — `code`·`name` 은 지역 식별자이고 `source` 는 계보 표시다 */
  var REPORT_SKIP_FIELDS = {
    policy: ['id', 'disclaimer', 'failures'],
    region: ['code', 'name', 'source']
  };

  /* 화면 이름. **목록이 아니라 라벨이다** — 여기 없는 키는 키 그대로 보인다.
     허용 목록을 여기서 다시 정의하지 않는다는 뜻이다. */
  var REPORT_FIELD_LABEL = {
    status: '판정 결과', name: '제도 이름', category: '분류', reasons: '판정 사유',
    maxAmountKRW: '최대 한도', rateRangePct: '금리 범위', source: '출처',
    jeonseMedianKRW: '전세 중위가', monthlyDepositKRW: '월세 보증금',
    monthlyRentKRW: '월세', maintenanceFeeKRW: '관리비',
    jeonseRatioPct: '전세가율', conversionRatePct: '전월세 전환율',
    marketRisk: '시장 리스크', guaranteeAvailable: '보증 가입 가능'
  };

  function canReport() {
    return !!(STATE.session && STATE.session.authenticated);
  }

  function reportableFields(kind, item) {
    var skip = REPORT_SKIP_FIELDS[kind] || [];
    return Object.keys(item || {}).filter(function (key) { return skip.indexOf(key) < 0; });
  }

  function reportButtonHTML(kind, id, label) {
    if (!canReport()) return '';
    return '<button type="button" class="btn btn-ghost btn-xs report-btn" ' +
      'data-report-kind="' + esc(kind) + '" data-report-id="' + esc(id) + '">' +
      '이상 신고<span class="sr-only"> — ' + esc(label) + '</span></button>';
  }

  function reportTargetItem(kind, id) {
    if (kind === 'policy') {
      return ((STATE.lastResult && STATE.lastResult.policies) || []).filter(function (p) {
        return p.id === id;
      })[0] || null;
    }
    return findRegion(id) || null;
  }

  function openReportDialog(kind, id) {
    var item = reportTargetItem(kind, id);
    if (!item) { toast('신고 대상을 화면에서 찾지 못했습니다.'); return; }

    STATE.report = { kind: kind, id: id };
    $('#reportTarget').textContent = (kind === 'policy' ? '제도 · ' : '시세 · ') +
      (item.name || id) + ' (' + id + ')';
    $('#reportField').innerHTML = reportableFields(kind, item).map(function (key) {
      return '<option value="' + esc(key) + '">' +
        esc(REPORT_FIELD_LABEL[key] || key) + '</option>';
    }).join('');
    $('#reportReason').value = '';
    $('#reportReason').removeAttribute('aria-invalid');
    $('#reportNote').textContent = '';
    /* 대화상자를 연 버튼을 기억해 둔다. 닫을 때 그 자리로 초점을 돌려주지 않으면
       키보드 사용자는 문서 맨 앞으로 튕긴다. */
    STATE.reportOpener = document.activeElement;
    $('#reportModal').hidden = false;
    $('#reportReason').focus();
  }

  function closeReportDialog() {
    var opener = STATE.reportOpener;
    $('#reportModal').hidden = true;
    STATE.report = null;
    STATE.reportOpener = null;
    if (opener && document.contains(opener) && opener.focus) opener.focus();
  }

  /* aria-modal="true" 를 선언한 대화상자는 그 계약대로 동작해야 한다. 측정:
     Escape 가 닫지 않았고, 탭이 두 번 만에 대화상자를 빠져나가 뒤쪽 페이지를
     돌아다녔다(오버레이 뒤 요소가 계속 조작 가능했다). 둘 다 여기서 막는다. */
  function reportModalKeydown(e) {
    if ($('#reportModal').hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); closeReportDialog(); return; }
    if (e.key !== 'Tab') return;
    var stops = $$('#reportModal button, #reportModal select, #reportModal textarea, #reportModal input')
      .filter(function (el) { return !el.disabled && el.offsetParent !== null; });
    if (!stops.length) return;
    var first = stops[0];
    var last = stops[stops.length - 1];
    var here = document.activeElement;
    if (e.shiftKey && (here === first || !$('#reportModal').contains(here))) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && (here === last || !$('#reportModal').contains(here))) {
      e.preventDefault(); first.focus();
    }
  }

  function submitReport(e) {
    e.preventDefault();
    if (!STATE.report) return;
    var reason = $('#reportReason').value.trim();
    if (!reason) {
      /* 오류 문구가 어느 칸의 것인지 묶고, 초점을 그 칸으로 보낸다.
         전에는 문구만 뜨고 초점이 제출 버튼에 남았다. */
      $('#reportNote').textContent = '사유를 적어야 신고할 수 있습니다.';
      $('#reportReason').setAttribute('aria-invalid', 'true');
      $('#reportReason').focus();
      return;
    }
    $('#reportReason').removeAttribute('aria-invalid');

    apiFetch('/api/reports', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': (STATE.session && STATE.session.csrfToken) || ''
      },
      body: JSON.stringify({
        targetKind: STATE.report.kind,
        targetId: STATE.report.id,
        targetField: $('#reportField').value,
        reason: reason
      })
    }).then(function (filed) {
      closeReportDialog();
      /* 신고가 **무엇이 되는지** 그대로 적는다. 「접수됐습니다」로 끝내면 상담원은
         이것이 고쳐진 것으로 읽는다 — 신고는 제안이지 변경이 아니다. */
      toast('신고를 올렸습니다. 규칙관리자의 대기 큐에 쌓였고, <b>규칙은 바뀌지 않습니다</b>' +
        (filed && filed.mergedDraftIds && filed.mergedDraftIds.length
          ? ' · 같은 제도의 검토 대기 초안 ' + filed.mergedDraftIds.length + '건과 함께 보입니다.'
          : '.'));
    }).catch(function (err) {
      /* 침묵 폴백 금지 (SPEC 6.2 #3). 실패를 삼키면 상담원은 올렸다고 믿는다. */
      $('#reportNote').textContent = '신고하지 못했습니다: ' + ((err && err.message) || '알 수 없는 오류');
    });
  }

  function renderRegionReport() {
    var slot = $('#regionReport');
    if (!slot) return;
    var region = findRegion($('#regionCode').value);
    slot.innerHTML = region
      ? reportButtonHTML('region', region.code, region.name + ' 시세')
      : '';
  }

  function renderRisk(risk) {
    var meta = RISK_BAND_META[risk.band] || RISK_BAND_META.medium;
    $('#riskChip').outerHTML = '<span class="chip chip-lg ' + meta.cls + '" id="riskChip">' +
      iconSVG(meta.icon) + esc(meta.label) + '</span>';
    $('#riskMeterSlot').innerHTML = riskMeterSVG(risk.score, risk.band);
    $('#riskScore').textContent = risk.score;
    $('#riskScope').textContent = risk.evaluatedScenario
      ? '평가 대상 — ' + risk.evaluatedScenario
      : '적합도 1위 시나리오를 기준으로 평가했습니다.';

    var impactMeta = { low: POLICY_META.eligible, medium: POLICY_META.conditional, high: { label: '높음', cls: 'chip-critical', icon: 'alert' } };
    var impactLabel = { low: '영향 낮음', medium: '영향 보통', high: '영향 높음' };

    $('#riskFactors').innerHTML = (risk.factors || []).map(function (f) {
      var m = impactMeta[f.impact] || impactMeta.medium;
      return '<li class="factor">' +
        '<div><span class="factor-name">' + esc(f.name) + '</span> ' +
          '<span class="chip chip-sm ' + m.cls + '">' + iconSVG(m.icon) + esc(impactLabel[f.impact] || '영향 보통') + '</span></div>' +
        '<span class="factor-val">' + (f.valuePct != null ? esc(pct(f.valuePct)) : '—') + '</span>' +
        '<p class="factor-note">' + esc(f.note || '') + '</p></li>';
    }).join('');
  }

  /* ── dataGrade (SPEC 2.4 · 10.2 6단계) ────────────────────────────────────
     ★ 원인 유형별로 **구분해서** 그린다. `stale`(신선도) · `unverified`(검증) ·
       `pending_review`(승인 적체)는 대응 주체가 다르다 — 앞의 둘은 배치, 뒤의 하나는
       규칙관리자다. 한 글자로 뭉치면 그 구분이 사라진다.
     ★ 응답에 `dataGrade` 가 **없으면 화면에 그렇게 적는다.** 프론트가 계보를 지어내
       등급을 만들지 않는다 — 백엔드 숫자에 프론트 생성물의 계보를 붙이는 것이
       D-11 이 없애려는 두 번째 판정 경로다 (코디네이터 결정 2026-08-15 (1)).
     ★ `pending_review` 는 5단계 승인 대기 큐에서 오므로 지금은 나올 수 없다.
       유형을 **다룰 수 있게만** 두고 없는 것을 있는 척 그리지 않는다. */
  var GRADE_META = {
    A: { cls: 'chip-good', label: '등급 A', note: '판정에 쓰인 사실이 전부 검증됐고 신선도 기준 이내입니다.' },
    B: { cls: 'chip-caution', label: '등급 B', note: '일부 사실이 낡았거나 검토 대기 중인 변경이 있습니다.' },
    C: { cls: 'chip-critical', label: '등급 C', note: '출처를 확인하지 못한 사실이 판정에 포함됐습니다.' }
  };
  /* 색에는 아이콘과 라벨이 항상 동반한다 (styles.css 머리말의 규약). 그래서 유형 구분을
     칩으로 낸다 — 색만 나르는 표식(카드 옆 색 띠 따위)을 쓰지 않는다. */
  var GRADE_REASON_META = {
    unverified: { label: '검증 안 됨', cls: 'chip-critical', icon: 'alert',
                  owner: '수집 배치', why: '출처를 확인하지 못한 사실입니다.' },
    stale: { label: '신선도 초과', cls: 'chip-caution', icon: 'alert',
             owner: '수집 배치', why: '관측 시점이 신선도 기준을 넘었습니다.' },
    pending_review: { label: '승인 적체', cls: 'chip-caution', icon: 'alert',
                      owner: '규칙관리자', why: '이 정책에 검토 대기 중인 변경이 있습니다.' },
    /* ★ 대응 주체가 **배치도 규칙관리자도 아니다.** SPEC 2.4 가 사유를 원인 유형별로
       나눈 이유가 대응 주체가 다르기 때문이고, 이것은 임계를 정하는 사람이 푼다.
       「미상」으로 적으면 그 구분이 처음부터 없었던 것이 된다. */
    freshness_not_evaluated: { label: '신선도 미판정', cls: 'chip-neutral', icon: 'minus',
                               owner: '코디네이터 (신선도 임계 확정)',
                               why: '이 판정은 신선도를 검사하지 않았습니다.' }
  };

  /* `dataGrade` 는 있는데 `grade` 가 `null` 인 상태. **「계보 없음」과 다른 사실이다** —
     하나는 서버가 계보를 안 실은 것이고, 하나는 계보는 있는데 등급의 조건 하나(신선도)가
     확정되지 않은 것이다. 뭉치면 화면이 [서버가 뭔가 빠뜨렸다]로 읽는다. */
  var UNGRADED_META = {
    cls: 'chip-neutral', label: '등급 산정 불가',
    note: '등급의 조건 하나가 확정되지 않아 등급을 매기지 못했습니다. ' +
          '「문제 없음」이 아닙니다 — 아래 사유가 무엇이 확정되지 않았는지를 말합니다.'
  };

  function renderDataGrade(res) {
    var card = $('#cardGrade');
    var grade = res.dataGrade;
    if (!grade) {
      card.hidden = false;
      $('#gradeChip').outerHTML = '<span class="chip chip-lg chip-neutral" id="gradeChip">' +
        iconSVG('minus') + '등급 없음</span>';
      $('#gradeBody').innerHTML =
        '<p class="grade-absent"><b>이 응답에는 계보가 실려 있지 않습니다.</b> ' +
        '데이터 등급(SPEC 2.4)과 계보 목록(D-13)은 판정을 만든 쪽이 함께 실어야 하는 값입니다. ' +
        '화면이 대신 만들어 붙이지 않습니다 — 다른 데이터로 계산한 등급은 이 숫자의 등급이 아니기 때문입니다.</p>';
      return;
    }

    var meta = grade.grade ? (GRADE_META[grade.grade] || GRADE_META.C) : UNGRADED_META;
    card.hidden = false;
    $('#gradeChip').outerHTML = '<span class="chip chip-lg ' + meta.cls + '" id="gradeChip">' +
      iconSVG(grade.grade === 'A' ? 'check' : (grade.grade ? 'alert' : 'minus')) +
      esc(meta.label) + '</span>';

    var provenance = res.provenance || [];
    var reasons = grade.reasons || [];
    var buckets = {};
    reasons.forEach(function (r) {
      var type = r.type || 'unclassified';
      (buckets[type] = buckets[type] || []).push(r);
    });

    var order = ['unverified', 'stale', 'pending_review', 'freshness_not_evaluated'];
    Object.keys(buckets).forEach(function (t) { if (order.indexOf(t) === -1) order.push(t); });

    var groups = order.filter(function (t) { return buckets[t] && buckets[t].length; }).map(function (type) {
      var m = GRADE_REASON_META[type] ||
        { label: '분류되지 않은 사유', cls: 'chip-neutral', icon: 'minus',
          owner: '미상', why: '응답이 원인 유형을 담지 않았습니다.' };
      var items = buckets[type].map(function (r) {
        var item = (r.provenanceIndex != null && provenance[r.provenanceIndex]) || null;
        /* 사실에 걸리지 않는 사유는 가리킬 항목도 출처도 없다 (`freshness_not_evaluated`).
           「사실 이름 없음 / 출처 미기재」로 그리면 **없는 것을 누락으로** 보이게 한다 —
           그것은 설계이지 빠뜨린 것이 아니다. 그런 사유는 자기 문장을 낸다. */
        if (!item && !r.fact) {
          return '<li class="grade-reason-note">' + esc(r.message || '') + '</li>';
        }
        var targets = (item && item.targets) || [];
        var fact = r.fact || (item && item.fact) || '(사실 이름 없음)';
        var prov = item && (item.provenance || item);
        var origin = prov && prov.source_name ? prov.source_name : '출처 미기재';
        return '<li><span class="grade-fact">' + esc(fact) + '</span>' +
          '<span class="grade-origin">' + esc(origin) + '</span>' +
          (targets.length
            ? '<span class="grade-targets">' + targets.map(function (t) {
                return '<code>' + esc(t) + '</code>';
              }).join(' ') + '</span>'
            : '') + '</li>';
      }).join('');
      return '<section class="grade-group" data-type="' + esc(type) + '">' +
        '<h3>' + chipHTML(m, 'chip-sm') +
        '<span class="grade-count">' + buckets[type].length + '건</span>' +
        '<span class="grade-owner">대응 주체 — ' + esc(m.owner) + '</span></h3>' +
        '<p class="grade-why">' + esc(m.why) + '</p>' +
        '<ul class="grade-facts">' + items + '</ul></section>';
    }).join('');

    $('#gradeBody').innerHTML = '<p class="grade-note">' + esc(meta.note) + '</p>' +
      (groups || '<p class="grade-note">등급을 낮춘 사유가 없습니다.</p>') +
      '<p class="grade-foot">오른쪽 <code>/…</code> 는 그 계보가 걸린 응답 위치(JSON Pointer)입니다. ' +
      '규범적 선택(<code>our_choice</code>)은 신선도 개념이 없어 등급 산정에서 빠지고 계보 목록에만 남습니다.</p>';
  }

  /* ── 상담원 확장 (SPEC 6.1 · D-9) — **필드 유무로** 갈린다 ────────────────
     역할로 분기하지 않는다. 익명 응답에는 `internal` 키가 아예 없고(4단계가 그것을
     권한 테스트로 고정했다), 인증된 요청에만 채워진다. 화면이 버튼을 숨기는 것은
     권한이 아니다 — 권한은 API 가 이미 막고 있다 (SPEC 6.1 SoD). */
  function renderInternal(res) {
    var card = $('#cardInternal');
    var internal = res.internal;
    if (!internal) { card.hidden = true; $('#internalBody').innerHTML = ''; return; }
    card.hidden = false;

    var versions = (internal.ruleVersions || []).map(function (v) {
      return '<tr><td>' + esc(v.policyId) + '</td><td><code>' + esc(v.ruleVersionId) + '</code></td>' +
        '<td>' + esc(v.origin) + '</td>' +
        '<td>' + esc(v.effectiveFrom || '시행일 미상') + ' → ' + esc(v.effectiveTo || '무기한') + '</td></tr>';
    }).join('');

    var fresh = internal.dataFreshness || {};
    var freshness = '<dl class="internal-freshness">' +
      '<div><dt>지역 코드</dt><dd>' + esc(fresh.regionCode || '—') + '</dd></div>' +
      '<div><dt>검증 상태</dt><dd>' + esc(fresh.verification || '—') + '</dd></div>' +
      '<div><dt>관측 시점</dt><dd>' + esc(fresh.observedAt || '없음') + '</dd></div>' +
      '<div><dt>취득 시각</dt><dd>' + esc(fresh.fetchedAt || '없음') + '</dd></div></dl>';

    var thresholds = (internal.ineligiblePolicies || []).map(function (p) {
      var pairs = Object.keys(p.criteria || {}).sort().map(function (k) {
        return '<span class="crit"><b>' + esc(k) + '</b> ' + esc(JSON.stringify(p.criteria[k])) + '</span>';
      }).join('');
      return '<li><span class="internal-pid">' + esc(p.policyId) + '</span>' +
        '<span class="chip chip-sm ' + ((POLICY_META[p.status] || POLICY_META.conditional).cls) + '">' +
        esc((POLICY_META[p.status] || POLICY_META.conditional).label) + '</span>' +
        '<div class="internal-crit">' + (pairs || '<span class="crit">요건 없음</span>') + '</div></li>';
    }).join('');

    $('#internalBody').innerHTML =
      '<h3>판정에 참여한 승인 규칙</h3>' +
      '<div class="table-scroll"><table class="internal-table"><thead><tr>' +
      '<th>정책</th><th>규칙 버전</th><th>승인 출처</th><th>유효기간</th></tr></thead><tbody>' +
      (versions || '<tr><td colspan="4">없음</td></tr>') + '</tbody></table></div>' +
      '<h3>이 판정에 쓰인 시세의 신선도</h3>' + freshness +
      '<h3>부적격·조건부 정책의 문턱</h3>' +
      '<ul class="internal-thresholds">' + (thresholds || '<li>해당 없음</li>') + '</ul>';
  }

  function sourceLabel() {
    if (STATE.lastSource === 'local') return '브라우저 로컬 판정 경로(백엔드 미연결)';
    return '백엔드 엔진 응답';
  }

  function renderSummary(res) {
    $('#summaryText').textContent = humanizeEnums(res.summary || '');
    var m = res.meta || {};
    var when = m.generatedAt ? new Date(m.generatedAt) : null;
    var stamp = when && !isNaN(when.getTime()) ? when.toLocaleString('ko-KR') : '—';
    $('#summaryMeta').textContent = '엔진 v' + (m.engineVersion || '—') + ' · 생성 ' + stamp +
      ' · ' + sourceLabel() + (m.disclaimer ? ' · ' + m.disclaimer : '');
  }

  function renderAll(res, profile) {
    STATE.lastResult = res;
    STATE.lastProfile = profile;

    renderAffordability(res.affordability, profile, res.scenarios || []);
    renderScenarios(res.scenarios || []);
    renderPolicies(res.policies || []);
    renderRisk(res.risk || { score: 0, band: 'low', factors: [] });
    renderDataGrade(res);
    renderInternal(res);
    renderSummary(res);

    $('#onboarding').hidden = true;
    $('#skeleton').hidden = true;
    var dash = $('#dashboard');
    dash.hidden = false;
    $$('#dashboard > .card', document).forEach(function (card, i) {
      card.classList.remove('reveal');
      void card.offsetWidth;
      card.style.animationDelay = (i * 55) + 'ms';
      card.classList.add('reveal');
    });
    bindTips(dash);
  }

  /* ══════════════════════════════════════════════════════════
     5. API LAYER (with graceful fallback)
     ══════════════════════════════════════════════════════════ */
  function apiFetch(path, options) {
    if (typeof fetch !== 'function') {
      return Promise.reject(new Error('fetch unavailable — offline fallback'));
    }
    /* Once the health probe has proven there is no backend, later calls
       short-circuit instead of re-dialling a dead origin. Without this, every
       action in the offline demo stalled for the full GET budget and the
       browser logged another network failure the app had already handled. */
    if (STATE.connection === 'local' && path !== '/api/health') {
      return Promise.reject(new Error('backend offline — using the local path'));
    }
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutFor(path));
    /* 같은 오리진에서 서빙되므로 세션 쿠키가 함께 간다 (SPEC 6.2 · 6.3).
       `file://` 로 열면 교차 오리진이라 쿠키가 실리지 않고, 그때는 로그인이 성립하지 않는다. */
    var opts = Object.assign({
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin'
    }, options || {});
    if (ctrl) opts.signal = ctrl.signal;

    return fetch(API_BASE + path, opts).then(function (r) {
      clearTimeout(timer);
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          var msg = (body && body.error && body.error.message) || ('HTTP ' + r.status);
          throw new Error(msg);
        });
      }
      return r.json();
    }, function (err) { clearTimeout(timer); throw err; });
  }

  function setConnection(state, text) {
    STATE.connection = state;
    var badge = $('#connBadge');
    if (!badge) return;
    badge.setAttribute('data-state', state);
    $('#connText').textContent = text;
    /* 좁은 폭에서 배지는 점만 남는다. 문구는 `#connText` 를 시각적으로만 숨겨
       (styles.css 의 ≤810px 규칙) **내용으로** 살려 둔다.
       ★ 여기 있던 `aria-label` 은 지웠다 — ARIA 는 role 없는 <span>(generic)에
         이름을 붙이는 것을 금지하고, 실제로 axe 가 serious 로 잡았다. 그 상태에서
         ≤620px 는 텍스트가 display:none 이라 상태가 **색 점 하나로만** 전달됐다. */
    badge.setAttribute('title', text);
  }

  /**
   * 로컬 판정 경로의 가용 여부를 **화면에 적는다** (SPEC 6.2 오프라인 정의 #3 · D-11).
   * 생성물이 없으면 그 경로를 끄고 무엇이 없는지까지 말한다. 조용히 기본값으로 돌지 않는다.
   */
  function renderLocalPathBanner() {
    var banner = $('#localBanner');
    if (!banner) return;
    var st = localStatus();
    if (st.ready && STATE.connection !== 'local') { banner.hidden = true; return; }
    banner.hidden = false;
    if (!st.ready) {
      banner.setAttribute('data-kind', 'disabled');
      banner.innerHTML = '<b>로컬 판정 경로가 꺼져 있습니다.</b> 생성물이 없어 이 브라우저에서는 ' +
        '판정 숫자를 만들 수 없습니다 — 기본값으로 대신 계산하지 않습니다(SPEC D-11). 없는 것: ' +
        st.missing.map(function (m) {
          return '<code>' + esc(m.file) + '</code>(' + esc(m.label) + ')';
        }).join(' · ') +
        '. <span class="banner-fix">복구: <code>python scripts/gen_contracts.py</code></span>';
      return;
    }
    banner.setAttribute('data-kind', 'local');
    banner.innerHTML = '<b>백엔드에 연결하지 못해 이 화면의 숫자는 브라우저 안에서 계산됐습니다.</b> ' +
      '상수·정책 규칙·지역 시세는 <code>frontend/generated/</code> 생성물에서 왔고, ' +
      '백엔드 엔진과 같은 값을 내는지는 <code>test_frontend_local_engine_equivalence.py</code> 가 붙들고 있습니다. ' +
      '다만 <b>시세는 이 커밋이 아는 예시값</b>이며 수집 배치가 넣은 실데이터가 아닙니다.';
  }

  function checkHealth() {
    return apiFetch('/api/health').then(function (h) {
      /* /api/health returns llm ∈ "openai" | "anthropic" | "offline" (BRIEF §5).
         Matching against "live" never held, so a working OpenAI backend still
         reported "템플릿 응답". Anything other than "offline" is a live provider. */
      var provider = h && h.llm ? String(h.llm) : 'offline';
      STATE.llmMode = provider !== 'offline' ? 'live' : 'offline';
      if (STATE.llmMode === 'live') setConnection('live', '백엔드 연결 · AI 라이브');
      else setConnection('offline', '백엔드 연결 · 템플릿 응답');
      setChatModeChip(STATE.llmMode);
      renderLocalPathBanner();
      return true;
    }).catch(function () {
      var st = localStatus();
      if (st.ready) setConnection('local', '백엔드 미연결 · 로컬 판정 경로');
      else setConnection('disabled', '백엔드 미연결 · 로컬 판정 불가');
      setChatModeChip('offline');
      renderLocalPathBanner();
      return false;
    });
  }

  /** 세션 조회. 익명은 401 이 아니라 `authenticated:false` 인 200 이다. */
  function loadSession() {
    return apiFetch('/api/auth/session').then(function (s) {
      STATE.session = s || { authenticated: false, username: null, role: null, csrfToken: null };
      return STATE.session;
    }).catch(function () {
      STATE.session = { authenticated: false, username: null, role: null, csrfToken: null };
      return STATE.session;
    }).then(function (s) { renderSessionBar(); renderRegionReport(); return s; });
  }

  function loadRegions() {
    return apiFetch('/api/regions').then(function (d) {
      var list = (d && d.regions) || [];
      if (!list.length) throw new Error('empty');
      STATE.regions = list;
      return list;
    }).catch(function () {
      /* 손으로 쓴 지역 목록은 없다. 생성물이 있으면 그것을, 없으면 **빈 목록**이다 —
         선택지를 지어내면 그 지역의 시세로 판정하게 되고 그것이 값 날조다. */
      var st = localStatus();
      STATE.regions = st.ready ? localRegions() : [];
      return STATE.regions;
    }).then(function (list) {
      var sel = $('#regionCode');
      if (!list.length) {
        sel.innerHTML = '<option value="">지역 데이터 없음</option>';
        sel.disabled = true;
        $('#heroRegionCount').textContent = '0개';
        $('#regionHelp').textContent =
          '지역 시세를 얻을 수 없습니다. 백엔드가 꺼져 있고 생성물도 없습니다 — 임의 값으로 대신하지 않습니다.';
        return list;
      }
      sel.disabled = false;
      sel.innerHTML = list.map(function (r) {
        return '<option value="' + esc(r.code) + '">' + esc(r.name) + '</option>';
      }).join('');
      sel.value = list[0].code;
      $('#heroRegionCount').textContent = list.length + '개';
      updateRegionHelp();
      return list;
    });
  }

  function updateRegionHelp() {
    var r = findRegion($('#regionCode').value);
    if (!r) return;
    // ★ 예전에는 '예시 시세' 였다. 계약 결정 #40 이 시드를 실수집으로 굳히면서 **이 줄에
    //   실리는 네 값이 전부 국토교통부 아파트 실거래가에서 나온 것**이 됐고, 그때부터
    //   '예시' 는 거짓이다. 검증 상태(verified / stale / unverified)는 이 줄이 말하지
    //   않는다 — STEP 06 의 등급 사유가 항목별로 말한다. 여기서는 **출처만** 적는다.
    $('#regionHelp').innerHTML = '국토교통부 실거래가 기준 — 전세 중위 <strong>' + esc(fmtKR(r.jeonseMedianKRW)) +
      '</strong> · 월세 <strong>' + esc(fmtKR(r.monthlyDepositKRW)) + ' / ' + esc(fmtKR(r.monthlyRentKRW)) +
      '</strong> · 전세가율 ' + esc(pct(r.jeonseRatioPct));
    renderRegionReport();
  }

  /* 라디오 그룹은 **하나의 탭 정지**다. 선택된 버튼만 탭으로 들어오고, 그 안에서는
     화살표키로 옮긴다. 선택과 탭 정지를 한 곳에서 같이 바꿔야 둘이 어긋나지 않는다. */
  function syncPreferredTypeTabStops() {
    $$('#preferredType button').forEach(function (b) {
      b.setAttribute('tabindex', b.getAttribute('aria-checked') === 'true' ? '0' : '-1');
    });
  }

  function selectPreferredType(btn) {
    $$('#preferredType button').forEach(function (b) { b.setAttribute('aria-checked', 'false'); });
    btn.setAttribute('aria-checked', 'true');
    syncPreferredTypeTabStops();
  }

  function readProfile() {
    var seg = $('#preferredType [aria-checked="true"]');
    return {
      age: num($('#age').value, 28),
      annualIncomeKRW: num($('#annualIncome').value) * 10000,
      monthlyNetIncomeKRW: num($('#monthlyNetIncome').value) * 10000,
      liquidAssetsKRW: num($('#liquidAssets').value) * 10000,
      existingDebtMonthlyKRW: num($('#existingDebt').value) * 10000,
      householdSize: num($('#householdSize').value, 1),
      regionCode: $('#regionCode').value,
      isHomeless: $('#isHomeless').checked,
      isNewlywed: $('#isNewlywed').checked,
      isSMEEmployee: $('#isSMEEmployee').checked,
      preferredType: seg ? seg.getAttribute('data-value') : 'any'
    };
  }

  /* ── 폼 오류 표기 ────────────────────────────────────────────────────────
     오류가 토스트뿐이었다. 토스트는 사라지고, 어느 칸이 문제인지 접근성 트리에
     남지 않는다 (측정: aria-invalid 없음 · aria-describedby 없음 · 칸 옆 문구 없음).
     칸 옆에 적고, 그 문구를 칸에 묶고, aria-invalid 를 세운다. 토스트는 그대로
     둔다 — 스크롤이 결과 쪽에 가 있을 때 알림 역할이 남아 있다. */
  function setFieldError(id, message) {
    var input = document.getElementById(id);
    if (!input) return;
    var errId = id + 'Error';
    var node = document.getElementById(errId);
    if (!node) {
      node = document.createElement('p');
      node.className = 'field-error';
      node.id = errId;
      node.setAttribute('role', 'alert');
      (input.closest('.field') || input.parentNode).appendChild(node);
    }
    node.textContent = message;
    node.hidden = false;
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', errId);
  }

  function clearFieldError(id) {
    var input = document.getElementById(id);
    var node = document.getElementById(id + 'Error');
    if (node) { node.hidden = true; node.textContent = ''; }
    if (input) { input.removeAttribute('aria-invalid'); input.removeAttribute('aria-describedby'); }
  }

  function analyze(e) {
    if (e) e.preventDefault();
    var profile = readProfile();
    clearFieldError('monthlyNetIncome');
    clearFieldError('regionCode');
    if (profile.monthlyNetIncomeKRW <= 0) {
      setFieldError('monthlyNetIncome', '월 실수령액을 0보다 크게 입력해 주세요.');
      toast('월 실수령액을 <b>0보다 크게</b> 입력해 주세요.');
      $('#monthlyNetIncome').focus();
      return;
    }
    if (!profile.regionCode) {
      setFieldError('regionCode', '지역 시세를 얻을 수 없어 판정할 수 없습니다. 백엔드를 켜거나 생성물을 재생성하세요.');
      toast('지역 시세를 얻을 수 없어 판정할 수 없습니다. 백엔드를 켜거나 생성물을 재생성하세요.');
      $('#regionCode').focus();
      return;
    }
    var btn = $('#btnAnalyze');
    btn.classList.add('is-busy');
    btn.disabled = true;
    $('#onboarding').hidden = true;
    $('#dashboard').hidden = true;
    $('#skeleton').hidden = false;

    var started = Date.now();
    var finish = function (res) {
      var wait = Math.max(0, 420 - (Date.now() - started));
      setTimeout(function () {
        try { if (res) renderAll(res, profile); }
        catch (err) {
          $('#skeleton').hidden = true;
          $('#onboarding').hidden = false;
          toast('결과를 그리는 중 오류가 발생했습니다: ' + esc(err.message));
        }
        btn.classList.remove('is-busy');
        btn.disabled = false;
      }, wait);
    };

    apiFetch('/api/analyze', { method: 'POST', body: JSON.stringify(profile) })
      .then(function (res) {
        if (!res || !res.affordability) throw new Error('malformed');
        if (STATE.connection === 'local' || STATE.connection === 'disabled') {
          setConnection('offline', '백엔드 연결 · 템플릿 응답');
        }
        STATE.lastSource = 'backend';
        renderLocalPathBanner();
        finish(res);
      })
      .catch(function (err) {
        /* ★ 침묵 폴백 금지 (SPEC 6.2 오프라인 정의 #3 · D-11).
           백엔드 응답이 없어 로컬로 내려간 경우도, 로컬조차 불가능한 경우도
           **화면에 명시한다.** 예전에는 여기서 정적 `MOCK_RESPONSE` 로 조용히
           떨어졌고 그 숫자에는 출처가 없었다. */
        var why = (err && err.name === 'AbortError') ? '응답 시간 초과'
          : ((err && err.message) || '네트워크 오류');
        var st = localStatus();
        if (!st.ready) {
          setConnection('disabled', '백엔드 미연결 · 로컬 판정 불가');
          setChatModeChip('offline');
          renderLocalPathBanner();
          $('#skeleton').hidden = true;
          $('#onboarding').hidden = false;
          toast('백엔드에 연결하지 못했고(' + esc(why) + ') <b>생성물이 없어 로컬 판정도 할 수 없습니다.</b> ' +
                '기본값으로 대신 계산하지 않습니다.');
          finish(null);
          return;
        }
        setConnection('local', '백엔드 미연결 · 로컬 판정 경로');
        setChatModeChip('offline');
        renderLocalPathBanner();
        toast('백엔드에 연결하지 못해(' + esc(why) + ') <b>브라우저 로컬 판정 경로</b>로 계산했습니다. ' +
              '상수·규칙·시세는 생성물에서 왔습니다.');
        var local;
        try {
          local = localAnalyze(profile);
        } catch (localErr) {
          setConnection('disabled', '백엔드 미연결 · 로컬 판정 불가');
          renderLocalPathBanner();
          $('#skeleton').hidden = true;
          $('#onboarding').hidden = false;
          toast('로컬 판정도 실패했습니다: ' + esc(localErr.message));
          finish(null);
          return;
        }
        STATE.lastSource = 'local';
        finish(local);
      });
  }

  /* ══════════════════════════════════════════════════════════
     6. CHAT
     ══════════════════════════════════════════════════════════ */
  function setChatModeChip(mode) {
    var chip = $('#chatModeChip');
    if (!chip) return;
    if (mode === 'live') { chip.className = 'chip chip-sm chip-good'; chip.textContent = 'LLM 라이브 모드'; }
    else { chip.className = 'chip chip-sm chip-neutral'; chip.textContent = '결정론적 템플릿 모드'; }
  }

  function pushMsg(role, text, tools) {
    var log = $('#chatLog');
    var li = document.createElement('li');
    li.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-bot');
    var toolHTML = '';
    if (tools && tools.length) {
      toolHTML = '<div class="msg-tools">' + tools.map(function (t) {
        return '<span class="tool-chip" title="' + esc(t.resultSummary || '') + '">' + esc(t.tool) + '()</span>';
      }).join('') + '</div>';
    }
    li.innerHTML = '<span class="msg-avatar">' + (role === 'user' ? 'ME' : 'AI') + '</span>' +
      '<div><div class="msg-bubble">' + esc(role === 'user' ? text : humanizeEnums(text)) + '</div>' +
      toolHTML + '</div>';
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
    return li;
  }

  function pushTyping() {
    var log = $('#chatLog');
    var li = document.createElement('li');
    li.className = 'msg msg-bot';
    li.id = 'typingRow';
    li.innerHTML = '<span class="msg-avatar">AI</span><div class="msg-bubble">' +
      '<span class="typing"><i></i><i></i><i></i></span></div>';
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
    return li;
  }

  /** 백엔드 미연결 시의 결정론적 템플릿 응답 — 숫자는 마지막 엔진 결과에서만 인용한다. */
  function localChatReply(message) {
    var res = STATE.lastResult;
    var q = String(message || '');
    if (!res) {
      return {
        reply: '먼저 왼쪽에서 프로필을 입력하고 「주거비 진단 시작」을 눌러주세요. ' +
          '진단 결과가 있어야 계산된 숫자를 근거로 답변할 수 있습니다. 지어낸 수치로는 답하지 않습니다.',
        toolCalls: [], mode: 'offline'
      };
    }
    var a = res.affordability, ss = res.scenarios || [], risk = res.risk || {};
    var best = ss[0], reply, tools = [];

    if (/전세|월세|비교|나아|뭐가|어느/.test(q) && ss.length > 1) {
      var j = ss.filter(function (s) { return s.type === 'jeonse'; })[0];
      var m = ss.filter(function (s) { return s.type === 'monthly'; })[0];
      tools = [{ tool: 'compare_tco', args: { years: 5 }, resultSummary: ss.length + '개 시나리오 비교' }];
      if (j && m) {
        var diff = m.tco5yKRW - j.tco5yKRW;
        reply = '5년 총비용 기준으로 비교하면\n' +
          '· 전세(' + j.label + '): ' + fmtKR(j.tco5yKRW) + ' (월 환산 ' + fmtKR(j.monthlyEquivalentCostKRW) + ')\n' +
          '· 월세(' + m.label + '): ' + fmtKR(m.tco5yKRW) + ' (월 환산 ' + fmtKR(m.monthlyEquivalentCostKRW) + ')\n\n' +
          (diff > 0 ? '전세가 ' + fmtKR(Math.abs(diff)) + ' 저렴합니다. ' : '월세가 ' + fmtKR(Math.abs(diff)) + ' 저렴합니다. ') +
          '단, 전세는 보증금이 묶이는 기회비용과 미반환 위험(현재 리스크 ' + (risk.score || 0) + '점)을 함께 봐야 합니다. ' +
          '현재 적합도 1위는 「' + best.label + '」(' + best.fitScore + '점)입니다.';
      } else {
        reply = '현재 조건에서는 「' + best.label + '」의 5년 총비용이 ' + fmtKR(best.tco5yKRW) +
          '으로 가장 유리합니다. 월 환산비용은 ' + fmtKR(best.monthlyEquivalentCostKRW) + '입니다.';
      }
    } else if (/얼마|상한|감당|가능한|주거비|월세.*까지/.test(q)) {
      /* F-1 (PR #24 §6 ④) — 여기서 `a.schwabeIndexPct` 를 인용하고 있었다. 그 필드는
         계약에서 제거됐고 `pct(undefined)` 가 "0.0%" 로 렌더됐다. 슈바베지수는 이제
         **시나리오별 측정값**이므로 하나를 고르지 않고 비교 대상 전체를 인용한다. */
      tools = [{ tool: 'calc_affordability', args: {}, resultSummary: '상한 ' + fmtKR(a.maxMonthlyHousingCostKRW) }];
      var shares = ss.map(function (s) {
        return '· ' + s.label + ': ' + pctOrDash(s.schwabeIndexPct);
      }).join('\n');
      reply = '월 주거비 상한은 ' + fmtKR(a.maxMonthlyHousingCostKRW) + ', 권장액은 ' +
        fmtKR(a.recommendedMonthlyHousingCostKRW) + '입니다(지불능력 판정 ' +
        BAND_META[a.band].label + ').\n\n' + (a.rationale || []).slice(0, 2).join('\n') +
        (shares ? '\n\n시나리오별 슈바베지수(실제 월 주거비 ÷ 월 실수령액)는\n' + shares : '') +
        '\n\n여기서 말하는 주거비는 월세뿐 아니라 관리비와 대출이자를 모두 합친 금액입니다.';
    } else if (/대출|정책|제도|지원|받을 수|자격|신청/.test(q)) {
      var ok = (res.policies || []).filter(function (x) { return x.status === 'eligible'; });
      var cond = (res.policies || []).filter(function (x) { return x.status === 'conditional'; });
      tools = [{ tool: 'check_eligibility', args: {}, resultSummary: '적격 ' + ok.length + '건 / 조건부 ' + cond.length + '건' }];
      reply = '입력하신 조건으로 적격 판정된 제도는 ' + ok.length + '건입니다.\n' +
        ok.slice(0, 4).map(function (x) {
          return '· ' + x.name + (x.maxAmountKRW ? ' — 최대 ' + fmtKR(x.maxAmountKRW) : '') +
            (x.rateRangePct ? ' / 금리 예시 ' + x.rateRangePct[0] + '~' + x.rateRangePct[1] + '%' : '');
        }).join('\n') +
        (cond.length ? '\n\n추가 확인이 필요한 조건부 제도가 ' + cond.length + '건 있습니다: ' +
          cond.slice(0, 3).map(function (x) { return x.name; }).join(', ') : '') +
        '\n\n각 판정의 사유는 위 「제도 매칭」 카드에서 항목별로 확인하실 수 있습니다. 표시된 금리·한도는 시연용 예시 수치입니다.';
    } else if (/위험|사기|리스크|보증|안전|떼이/.test(q)) {
      tools = [{ tool: 'scan_deposit_risk', args: {}, resultSummary: '위험점수 ' + (risk.score || 0) }];
      reply = '보증금 리스크 점수는 ' + (risk.score || 0) + '점 / 100 (' +
        (RISK_BAND_META[risk.band] || RISK_BAND_META.medium).label + ')입니다.\n\n' +
        (risk.factors || []).slice(0, 3).map(function (f) {
          return '· ' + f.name + ' ' + (f.valuePct != null ? pct(f.valuePct) : '') + ' — ' + f.note;
        }).join('\n') +
        '\n\n가장 확실한 대응은 전세보증금 반환보증 가입입니다. 계약 전 등기부등본의 선순위 채권과 임대인 체납 여부를 반드시 확인하세요.';
    } else {
      tools = [{ tool: 'summarize_analysis', args: {}, resultSummary: '엔진 결과 요약' }];
      reply = res.summary + '\n\n더 구체적으로는 “전세랑 월세 중 뭐가 나아?”, “내가 받을 수 있는 대출 알려줘”, ' +
        '“전세 사기 위험은 어때?” 처럼 물어보시면 계산된 숫자로 답변드립니다.';
    }
    return { reply: reply, toolCalls: tools, mode: 'offline' };
  }

  function sendChat(text) {
    if (!text || STATE.chatBusy) return;
    STATE.chatBusy = true;
    $('#btnSend').disabled = true;
    pushMsg('user', text);
    STATE.chatHistory.push({ role: 'user', content: text });
    var typing = pushTyping();

    var payload = {
      message: text,
      profile: STATE.lastProfile || readProfile(),
      history: STATE.chatHistory.slice(-8)
    };

    var finish = function (data) {
      if (typing && typing.parentNode) typing.parentNode.removeChild(typing);
      pushMsg('bot', data.reply, data.toolCalls);
      STATE.chatHistory.push({ role: 'assistant', content: data.reply });
      setChatModeChip(data.mode === 'live' ? 'live' : 'offline');
      STATE.chatBusy = false;
      $('#btnSend').disabled = false;
    };

    apiFetch('/api/chat', { method: 'POST', body: JSON.stringify(payload) })
      .then(function (d) {
        if (!d || typeof d.reply !== 'string') throw new Error('malformed');
        finish(d);
      })
      .catch(function (err) {
        /* Never swap in the built-in engine silently — an operator who sees the
           chip flip mid-demo needs to know whether the backend died or the
           request merely timed out. */
        var why = (err && err.name === 'AbortError')
          ? '응답 시간 초과'
          : ((err && err.message) || '네트워크 오류');
        setTimeout(function () {
          var local = localChatReply(text);
          local.reply = '[서버 응답을 받지 못해(' + why + ') 브라우저 내장 엔진으로 답변드립니다.]\n\n' + local.reply;
          finish(local);
        }, 380);
      });
  }

  /* ══════════════════════════════════════════════════════════
     7. MISC UI
     ══════════════════════════════════════════════════════════ */
  var toastTimer = null;
  function toast(html) {
    var t = $('#toast');
    if (!t) return;
    t.innerHTML = html;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 5200);
  }

  function syncMoneyEcho() {
    $$('.money-echo').forEach(function (node) {
      var input = document.getElementById(node.getAttribute('data-echo-for'));
      if (!input) return;
      var v = num(input.value) * 10000;
      node.textContent = v > 0 ? '= ' + fmtKR(v) : '';
    });
  }

  var SAMPLE = {
    age: 28, annualIncome: 4200, monthlyNetIncome: 300,
    liquidAssets: 4000, existingDebt: 30, householdSize: '1',
    isHomeless: true, isSMEEmployee: true, isNewlywed: false, preferredType: 'any'
  };
  function fillSample() {
    ['age', 'annualIncome', 'monthlyNetIncome', 'liquidAssets', 'existingDebt'].forEach(function (id) {
      document.getElementById(id).value = SAMPLE[id];
    });
    $('#householdSize').value = SAMPLE.householdSize;
    $('#isHomeless').checked = SAMPLE.isHomeless;
    $('#isSMEEmployee').checked = SAMPLE.isSMEEmployee;
    $('#isNewlywed').checked = SAMPLE.isNewlywed;
    $$('#preferredType button').forEach(function (b) {
      b.setAttribute('aria-checked', String(b.getAttribute('data-value') === SAMPLE.preferredType));
    });
    syncPreferredTypeTabStops();
    if (STATE.regions.length) $('#regionCode').value = STATE.regions[0].code;
    syncMoneyEcho();
    updateRegionHelp();
    toast('예시 프로필을 채웠습니다. <b>주거비 진단 시작</b>을 눌러보세요.');
  }

  /* ── 세션 (SPEC 6.1 · 6.3 · D-9) ──────────────────────────────────────────
     로그인은 **같은 화면**에서 켠다. 판정 화면을 역할별로 포크하지 않는다.
     로그인이 하는 일은 응답에 `internal` 이 실리게 하는 것뿐이고, 그 판단은
     API 가 한다 — 화면은 필드 유무만 본다. */
  var ROLE_LABEL = { counselor: '상담원', rule_manager: '규칙관리자' };

  function renderSessionBar() {
    var bar = $('#sessionBar');
    if (!bar) return;
    var s = STATE.session || {};
    if (s.authenticated) {
      bar.innerHTML = '<span class="session-who">' + esc(s.username) +
        ' <span class="session-role">' + esc(ROLE_LABEL[s.role] || s.role || '') + '</span></span>' +
        '<button type="button" class="btn btn-ghost btn-xs" id="btnLogout">로그아웃</button>';
      $('#btnLogout').addEventListener('click', doLogout);
    } else {
      bar.innerHTML = '<form class="session-form" id="loginForm">' +
        '<label class="sr-only" for="loginUser">아이디</label>' +
        '<input type="text" id="loginUser" placeholder="상담원 아이디" autocomplete="username">' +
        '<label class="sr-only" for="loginPass">비밀번호</label>' +
        '<input type="password" id="loginPass" placeholder="비밀번호" autocomplete="current-password">' +
        '<button type="submit" class="btn btn-ghost btn-xs">직원 로그인</button></form>';
      $('#loginForm').addEventListener('submit', doLogin);
    }
  }

  function doLogin(e) {
    e.preventDefault();
    var username = $('#loginUser').value.trim();
    var password = $('#loginPass').value;
    if (!username || !password) { toast('아이디와 비밀번호를 입력해 주세요.'); return; }
    apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: username, password: password })
    }).then(function (s) {
      STATE.session = s;
      renderSessionBar();
      /* 신고 버튼은 세션이 켜지는 순간 나타나야 한다 — 다시 진단할 때까지 기다리면
         상담원은 [이 화면에는 없다]로 읽는다. */
      renderRegionReport();
      if (STATE.lastResult) renderPolicies(STATE.lastResult.policies || []);
      toast('로그인했습니다. 다시 진단하면 <b>내부 정보</b>가 함께 실립니다.');
    }).catch(function (err) {
      toast('로그인하지 못했습니다: ' + esc((err && err.message) || '알 수 없는 오류'));
    });
  }

  function doLogout() {
    /* 상태변경 요청이므로 CSRF 토큰을 함께 보낸다 (SPEC 6.3). */
    apiFetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': STATE.session.csrfToken || '' }
    }).then(function () {
      STATE.session = { authenticated: false, username: null, role: null, csrfToken: null };
      renderSessionBar();
      closeReportDialog();
      renderRegionReport();
      if (STATE.lastResult) {
        delete STATE.lastResult.internal;
        renderInternal(STATE.lastResult);
        renderPolicies(STATE.lastResult.policies || []);
      }
      toast('로그아웃했습니다.');
    }).catch(function (err) {
      toast('로그아웃하지 못했습니다: ' + esc((err && err.message) || '알 수 없는 오류'));
    });
  }

  /**
   * 요약본 출력 (SPEC 6.1 「요약본 출력」 — 상담원 이상).
   * 버튼을 숨기는 것이 권한이 아니다. 이 출력에 담기는 것은 **응답이 실어 준 필드**이며,
   * 익명 응답에는 `internal` 이 아예 없어 담을 내용 자체가 없다.
   */
  function printSummary() {
    if (!STATE.lastResult) { toast('먼저 진단을 실행해 주세요.'); return; }
    if (!STATE.lastResult.internal) {
      toast('이 응답에는 내부 정보가 실려 있지 않습니다. 요약본은 직원 로그인 상태에서만 만들어집니다.');
      return;
    }
    window.print();
  }

  function wire() {
    $('#profileForm').addEventListener('submit', analyze);
    $('#btnSample').addEventListener('click', fillSample);
    $('#btnPrint').addEventListener('click', printSummary);
    $('#regionCode').addEventListener('change', updateRegionHelp);
    $$('.money-echo').forEach(function (node) {
      var input = document.getElementById(node.getAttribute('data-echo-for'));
      if (input) input.addEventListener('input', syncMoneyEcho);
    });

    /* role="radiogroup" 을 붙였으면 그 계약을 지켜야 한다. 측정: 화살표키가 아무
       것도 하지 않았고(핸들러 자체가 없었다) 세 버튼이 모두 탭 정지였다 —
       스크린리더 사용자는 라디오 그룹이라고 안내받은 뒤 라디오처럼 조작할 수 없었다.
       로빙 탭인덱스 + 화살표 이동/선택으로 맞춘다 (WAI-ARIA APG radio group). */
    $$('#preferredType button').forEach(function (btn, idx, all) {
      btn.addEventListener('click', function () { selectPreferredType(btn); });
      btn.addEventListener('keydown', function (e) {
        var step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1
          : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
        if (!step) return;
        e.preventDefault();
        var next = all[(idx + step + all.length) % all.length];
        selectPreferredType(next);
        next.focus();
      });
    });
    syncPreferredTypeTabStops();

    /* 이상 신고 (SPEC 6.4) — 위임으로 받는다. 정책 카드는 매 판정마다 다시 그려지므로
       버튼에 직접 걸면 렌더할 때마다 다시 걸어야 하고, 한 번 빠지면 그 자리만 조용히
       죽는다. 대상은 버튼이 들고 있는 값이지 사용자가 타이핑한 문자열이 아니다. */
    document.addEventListener('click', function (event) {
      var btn = event.target && event.target.closest ? event.target.closest('[data-report-kind]') : null;
      if (!btn) return;
      openReportDialog(btn.getAttribute('data-report-kind'), btn.getAttribute('data-report-id'));
    });
    $('#reportForm').addEventListener('submit', submitReport);
    $('#reportCancel').addEventListener('click', closeReportDialog);
    document.addEventListener('keydown', reportModalKeydown);
    $('#reportPrivacy').textContent = REPORT_PRIVACY_NOTICE;

    /* 선택 상태가 `is-on` 클래스뿐이었다 — 화면에는 보이지만 접근성 트리에는 없다.
       aria-pressed 로 같은 사실을 노출한다. 값은 클래스와 한 곳에서 함께 바꾼다. */
    $$('#policyFilter .pill').forEach(function (btn) {
      btn.addEventListener('click', function () {
        $$('#policyFilter .pill').forEach(function (b) {
          b.classList.remove('is-on');
          b.setAttribute('aria-pressed', 'false');
        });
        btn.classList.add('is-on');
        btn.setAttribute('aria-pressed', 'true');
        STATE.policyFilter = btn.getAttribute('data-filter');
        if (STATE.lastResult) renderPolicies(STATE.lastResult.policies || []);
      });
    });

    $('#chatForm').addEventListener('submit', function (e) {
      e.preventDefault();
      var input = $('#chatText');
      var v = input.value.trim();
      if (!v) return;
      input.value = '';
      sendChat(v);
    });
    $$('#chatSuggest .pill').forEach(function (btn) {
      btn.addEventListener('click', function () { sendChat(btn.textContent.trim()); });
    });

    window.addEventListener('scroll', hideTip, { passive: true });
  }

  function init() {
    wire();
    renderSessionBar();
    renderLocalPathBanner();
    syncMoneyEcho();
    pushMsg('bot',
      '안녕하세요. Home_Compass입니다.\n' +
      '왼쪽에 상황을 입력하고 진단을 실행하면, 계산된 숫자를 근거로 답변해 드립니다. ' +
      '저는 값을 만들어내지 않고 4개 판정 엔진이 계산한 결과만 인용합니다.',
      [{ tool: 'ready', args: {}, resultSummary: '엔진 대기' }]);
    checkHealth();
    loadSession();
    loadRegions();
  }

  /* ══════════════════════════════════════════════════════════
     8. BOOT / TEST HOOK
     ══════════════════════════════════════════════════════════ */
  /* 판정 엔진은 여기서 나가지 않는다 — `window.HomeCompassLocalEngine` 이 정본이다.
     예전 이 목록은 `engineAffordability` · `POLICY_CATALOG` · `MOCK_REGIONS` 를
     내보내고 있었고, 그 존재 자체가 두 번째 판정 경로의 표면이었다. */
  var TESTABLE = {
    fmtKR: fmtKR, fmtWon: fmtWon, pct: pct, pctOrDash: pctOrDash, esc: esc,
    localChatReply: localChatReply,
    schwabeChartHTML: schwabeChartHTML, stackedBarSVG: stackedBarSVG,
    tcoChartHTML: tcoChartHTML, riskMeterSVG: riskMeterSVG, fitRingSVG: fitRingSVG,
    renderDataGrade: renderDataGrade, renderInternal: renderInternal,
    renderPolicies: renderPolicies,
    canReport: canReport, reportableFields: reportableFields,
    reportButtonHTML: reportButtonHTML, REPORT_PRIVACY_NOTICE: REPORT_PRIVACY_NOTICE,
    localStatus: localStatus, timeoutFor: timeoutFor,
    STATE: STATE, TCO_KEYS: TCO_KEYS, ALLOC_KEYS: ALLOC_KEYS
  };
  if (typeof globalThis !== 'undefined') globalThis.HomeCompass = TESTABLE;

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
  }
})();
