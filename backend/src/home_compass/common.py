"""Shared helpers for the four deterministic engines.

Everything here is a pure function: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import math as _math

#: SPEC 8.4 — 판정 출력이 달라지면 올린다. 상수 값 변경(1-②)도 포함된다.
#: 1.0.0 -> 1.1.0: 1-② 가 시장금리 4종(기회비용률·할인율·전세대출·전월세전환율)을
#: 원문확인 관측값으로 교체해 같은 입력이 다른 숫자를 낸다. 계약 스키마는 바뀌지
#: 않으므로 major 가 아니라 minor 다.
#: 1.1.0 -> 2.0.0: 1-③ 이 **응답 스키마를 바꾼다** — `affordability.schwabeIndexPct` 가
#: 제거되고 `scenarios[].schwabeIndexPct` 가 생긴다 (F-1, SPEC 5.2.1 · 8.1 의 확정 예외).
#: 8.4 는 "계약 스키마가 바뀌면 major, 값만 바뀌면 minor" 이므로 major 다. 값도 함께
#: 움직인다 (F-2 권장액 단일 규칙 · 계약 결정 #16 의 표시 포맷) 지만 판정 근거는 스키마다.
#: 2.0.0 -> 3.0.0: 1-③ 뒷부분. **스키마가 또 바뀐다** — `scenarios[].schwabeIndexPct` 가
#: nullable 이 된다 (소득 0 이면 주거비/소득은 정의되지 않는다). `float` 을 전제한
#: 소비자가 깨지므로 major 다. 값도 함께 움직인다 (F-3 보증료율 24칸 요율표 ·
#: F-4 가입요건 상한의 수도권/그 외 분리 · F-5 보증금 하한 폐기).
ENGINE_VERSION = "3.0.0"

DISCLAIMER = (
    "프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다."
)


def floor_to(value: float, unit: int = 10_000) -> int:
    """Round `value` down to the nearest `unit`, clamped at 0."""
    if value <= 0:
        return 0
    return int(value // unit) * unit


def safe_int(value, default: int = 0) -> int:
    """Coerce anything numeric-ish to a non-negative int."""
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return result if result > 0 else 0


def _to_int_half_away_from_zero(value, default: int = 0) -> int:
    """Coerce to int, breaking .5 away from zero. **Keeps the sign.**

    `safe_int` is the input-coercion rule and clamps negatives to 0, which is
    right for income/assets/debt. Display is a different job: a household whose
    residual capacity is -750,000 learns nothing from "0원". Contract decision
    #16 fixes the display path and leaves `safe_int` alone.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    magnitude = int(_math.floor(abs(number) + 0.5))
    return -magnitude if number < 0 else magnitude


def _round_half_up(amount: int, unit: int) -> int:
    """`amount / unit` rounded half-up. `amount` is non-negative."""
    return (amount + unit // 2) // unit


def money(value) -> str:
    """Format a KRW amount as a compact Korean string ('2,800만원').

    Rounds to the nearest 만원 rather than truncating. This must stay
    byte-for-byte consistent with `fmtKR()` in `frontend/app.js`: the dashboard
    card and the `summary` sentence beside it quote the same number, and a
    floor-vs-round split rendered 808,000원 as "81만원" in the card and
    "80만원" in the summary.

    The rule is no longer a comment — `contracts/format_golden.json` holds the
    input -> expected-string pairs and both implementations are tested against
    that one file (SPEC 9.1.1). Two things it pins that the old code got wrong
    (contract decision #16):

      · **half-up, not banker's.** `round(2.5)` is 2 in Python, so 25,000원
        rendered as "2만원" — a 만원 decided by a language default nobody chose.
      · **the sign survives.** -750,000 is "-75만원", not "0원".
    """
    amount = _to_int_half_away_from_zero(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 100_000_000:
        eok, rest = divmod(amount, 100_000_000)
        man = _round_half_up(rest, 10_000)
        if man >= 10_000:  # carry, e.g. 199,999,000 -> "2억원" not "1억 10,000만원"
            eok += 1
            man = 0
        return f"{sign}{eok}억 {man:,}만원" if man else f"{sign}{eok}억원"
    if amount >= 10_000:
        return f"{sign}{_round_half_up(amount, 10_000):,}만원"
    return f"{sign}{amount:,}원"


def pct(value: float, digits: int = 1) -> str:
    """Format a percentage at a **fixed** number of decimals.

    `:g` used to drop trailing zeros, so "25%" and "25.0%" became the same
    string and a reader could not tell an exact 25 from a rounded one. That
    matters now: after F-1 (SPEC 5.2.1) the Schwabe index is a measurement
    rather than a constant, so its precision carries information.
    `contracts/format_golden.json` is the arbiter (contract decision #16).
    """
    return f"{float(value):.{digits}f}%"


def ratio(numerator: float, denominator: float) -> float:
    """Division that returns 0.0 instead of raising on a zero denominator."""
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)
