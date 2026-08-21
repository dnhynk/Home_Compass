/* ============================================================
   Home_Compass — 포맷 함수 (SPEC 9.1.1 · 계약 결정 #16)

   9.1.1 은 "포맷 함수 1개"를 이렇게 정의했다.

     · **언어당 구현 1개** — 파이썬 1개, JS 1개.
     · **판정 기준은 구현이 아니라 출력이다.** `contracts/format_golden.json` 에
       입력 -> 기대 문자열을 두고 **양쪽 테스트가 같은 파일을 읽는다.**
     · 엔진·화면 어디서도 픽스처를 우회한 자체 포맷을 만들지 않는다.

   이 파일이 그 JS 변이다. 파이썬 변은 `backend/src/home_compass/common.py` 의
   `money()` · `pct()` 이고, 적합성은 두 테스트가 각각 붙든다 —
   `backend/tests/test_format_golden.py`(파이썬) ·
   `backend/tests/test_frontend_format_golden_js.py`(여기, node 로 실행).

   ── 왜 `toFixed` 를 쓰지 않는가 ─────────────────────────────────────────────
   픽스처의 `pct(2.5, 0) -> "2%"` 를 `(2.5).toFixed(0)` 은 `"3"` 으로 낸다.
   파이썬의 `f"{x:.0f}"` 는 **정확한 이진값에 대한 짝수 반올림**(round-half-even)이고
   ECMA-262 의 `toFixed` 는 동점에서 **큰 쪽**을 고르기 때문이다. 두 규칙은 동점에서만
   갈리지만, 갈리는 그 지점이 곧 계약 위반이다. 그래서 아래 `decimalString()` 은
   double 을 비트에서 분해해 BigInt 로 **정확한 십진 반올림**을 수행한다. 근사로
   흉내내지 않는 이유는 그 흉내가 어디서 틀리는지 아무도 모르게 되기 때문이다.

   같은 이유로 파이썬 `round(x, n)` 의 대응물도 여기서 나온다(`roundHalf`) —
   판정 응답에 실리는 `schwabeIndexPct` · `loanRatePct` · `valuePct` 가 그 함수의
   결과이므로, 로컬 판정 경로가 백엔드와 **같은 double** 을 내야 한다.

   빌드툴·CDN 없이 `<script src>` 로 읽힌다 (SPEC 6.2 오프라인 정의 #1).
   ============================================================ */
(function (global) {
  'use strict';

  /* ── double 의 정확한 값 ─────────────────────────────────────────────────
     IEEE754 binary64 를 (부호, 유효숫자, 지수) 로 분해한다.
     값 = (-1)^negative * mant * 2^e  —— 근사가 아니라 항등식이다. */
  function decompose(x) {
    var view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, x, false);
    var hi = view.getUint32(0, false);
    var lo = view.getUint32(4, false);
    var negative = (hi >>> 31) === 1;
    var biased = (hi >>> 20) & 0x7ff;
    var mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
    var e;
    if (biased === 0) {
      e = -1074;                       /* 비정규수(0 포함) */
    } else {
      mant |= (1n << 52n);             /* 묵시적 선행 1 */
      e = biased - 1075;
    }
    return { negative: negative, mant: mant, e: e };
  }

  /** |x| * 10^digits 를 **짝수 반올림**해 BigInt 로 돌려준다. */
  function scaledRoundHalfEven(mant, e, digits) {
    var numerator = mant * (10n ** BigInt(digits));
    if (e >= 0) return numerator << BigInt(e);   /* 정수 — 반올림할 것이 없다 */
    var denominator = 1n << BigInt(-e);
    var quotient = numerator / denominator;
    var twiceRest = (numerator % denominator) * 2n;
    if (twiceRest > denominator || (twiceRest === denominator && (quotient & 1n) === 1n)) {
      quotient += 1n;
    }
    return quotient;
  }

  /**
   * 파이썬 `format(float(x), '.{digits}f')` 와 **같은 문자열**.
   * 부호는 값이 음수이면 반올림 결과가 0이어도 남는다 (파이썬이 그렇다: -0.01 -> "-0.0").
   */
  function decimalString(x, digits) {
    var value = Number(x);
    if (!isFinite(value)) {
      /* 파이썬 `float(None)` 이 예외를 내는 자리다. 0 으로 메우지 않는다 —
         F-1 의 파손이 정확히 `pct(undefined)` 가 "0.0%" 로 렌더된 것이었다. */
      throw new TypeError('포맷할 수 없는 값입니다: ' + String(x));
    }
    var parts = decompose(value);
    var scaled = scaledRoundHalfEven(parts.mant, parts.e, digits).toString();
    if (digits > 0) {
      while (scaled.length <= digits) scaled = '0' + scaled;
      scaled = scaled.slice(0, scaled.length - digits) + '.' + scaled.slice(scaled.length - digits);
    }
    return (parts.negative ? '-' : '') + scaled;
  }

  /** 파이썬 `round(x, digits)` — 짝수 반올림 뒤 **가장 가까운 double** 로 되돌린다. */
  function roundHalf(x, digits) {
    return Number(decimalString(x, digits == null ? 0 : digits));
  }

  /* ── 정수 강제 ─────────────────────────────────────────────────────────── */

  /** 파이썬 `common._to_int_half_away_from_zero` — 부호를 유지한다. */
  function toIntHalfAwayFromZero(value, fallback) {
    var number = Number(value);
    if (!isFinite(number)) return fallback == null ? 0 : fallback;
    var magnitude = Math.floor(Math.abs(number) + 0.5);
    return number < 0 ? -magnitude : magnitude;
  }

  /** 파이썬 `common.safe_int` — **짝수 반올림** 뒤 음수를 0 으로 클램프한다. */
  function safeInt(value, fallback) {
    var number = Number(value);
    if (value == null || value === '' || !isFinite(number)) {
      return fallback == null ? 0 : fallback;
    }
    var rounded = roundHalf(number, 0);
    return rounded > 0 ? rounded : 0;
  }

  /** 파이썬 `(amount + unit // 2) // unit` — `amount` 는 음이 아닌 정수다. */
  function roundHalfUpUnit(amount, unit) {
    return Math.floor((amount + Math.floor(unit / 2)) / unit);
  }

  /** 파이썬 `f"{n:,}"` — 음이 아닌 정수의 천 단위 구분. */
  function group(n) {
    var text = String(n);
    var out = '';
    for (var i = 0; i < text.length; i++) {
      if (i > 0 && (text.length - i) % 3 === 0) out += ',';
      out += text.charAt(i);
    }
    return out;
  }

  /* ── 계약이 붙드는 두 함수 ─────────────────────────────────────────────── */

  /** 파이썬 `common.money` — 280000000 -> "2억 8,000만원", -750000 -> "-75만원". */
  function money(value) {
    var amount = toIntHalfAwayFromZero(value);
    var sign = amount < 0 ? '-' : '';
    amount = Math.abs(amount);
    if (amount >= 100000000) {
      var eok = Math.floor(amount / 100000000);
      var man = roundHalfUpUnit(amount - eok * 100000000, 10000);
      if (man >= 10000) { eok += 1; man = 0; }   /* 199,999,000 -> "2억원" */
      return man ? sign + eok + '억 ' + group(man) + '만원' : sign + eok + '억원';
    }
    if (amount >= 10000) return sign + group(roundHalfUpUnit(amount, 10000)) + '만원';
    return sign + group(amount) + '원';
  }

  /** 파이썬 `common.pct` — 자릿수를 고정한다. `:g` 처럼 후행 0 을 지우지 않는다. */
  function pct(value, digits) {
    return decimalString(value, digits == null ? 1 : digits) + '%';
  }

  /* ── 화면 전용 표기 ───────────────────────────────────────────────────────
     아래 둘은 백엔드에 대응물이 없는 **표시 형태**다. 새 반올림 규칙을 만들지
     않는다 — `money()` 와 같은 정수 강제·같은 자릿수 구분을 그대로 쓰고
     렌더링만 다르다. 규칙이 하나여야 9.1.1 이 성립한다. */

  /** 752000 -> "752,000원". 자릿수를 접지 않고 그대로 보인다. */
  function won(value) {
    var amount = toIntHalfAwayFromZero(value);
    return (amount < 0 ? '-' : '') + group(Math.abs(amount)) + '원';
  }

  /** `money()` 에서 '원' 만 뗀 표기. 큰 숫자 옆에 단위를 따로 붙이는 자리용. */
  function moneyNoUnit(value) {
    return money(value).replace(/원$/, '');
  }

  global.HomeCompassFormat = {
    money: money,
    moneyNoUnit: moneyNoUnit,
    won: won,
    pct: pct,
    decimalString: decimalString,
    roundHalf: roundHalf,
    safeInt: safeInt,
    toIntHalfAwayFromZero: toIntHalfAwayFromZero
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
