"""E4 — Deposit risk scanner (전세보증금 리스크 스캐너).

Scores the chance that a tenant does not get their deposit back, on a 0~100
scale where higher is worse. Five weighted factors are evaluated independently
and summed, and each one is returned with its own value, impact level and a
plain-Korean note so the score is never a black box.

The weights are prototype heuristics, not a lender's model. They are **injected**
rather than declared here (SPEC 5.1.1): 5.1.2 names "리스크 점수 가중치" as a
forbidden literal precisely because a weight silently edited in code is a
judgement changed with no registry entry and no provenance behind it.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..common import money, pct, ratio, safe_int

IMPACTS = ("low", "medium", "high")
BANDS = ("low", "medium", "high")


def _jeonse_ratio_factor(
    jeonse_ratio_pct: float, *, constants: Mapping[str, object]
) -> tuple[float, str, str]:
    threshold_1 = constants["risk.jeonse_ratio_threshold_1"]
    threshold_2 = constants["risk.jeonse_ratio_threshold_2"]
    threshold_3 = constants["risk.jeonse_ratio_threshold_3"]
    threshold_4 = constants["risk.jeonse_ratio_threshold_4"]
    r = float(jeonse_ratio_pct or 0)
    if r <= 0:
        return 0, "low", "전세가율 정보가 없어 위험 가중치를 적용하지 않았습니다."
    if r < threshold_1:
        return (
            constants["risk.jeonse_ratio_weight_1"],
            "low",
            "매매가 대비 전세가율이 낮아 보증금 회수 여력이 충분한 편입니다.",
        )
    if r < threshold_2:
        return (
            constants["risk.jeonse_ratio_weight_2"],
            "low",
            "전세가율이 안정 구간이지만 시세 하락에는 주의가 필요합니다.",
        )
    # The note quotes the band's own lower bound, so the sentence cannot drift
    # away from the threshold that produced it.
    if r < threshold_3:
        return (
            constants["risk.jeonse_ratio_weight_3"],
            "medium",
            f"전세가율이 {threshold_2}%를 넘어 시세가 하락하면 보증금 일부가 위험해질 수 있습니다.",
        )
    if r < threshold_4:
        return (
            constants["risk.jeonse_ratio_weight_4"],
            "high",
            f"전세가율이 {threshold_3}%를 넘는 고위험 구간입니다. 선순위 채권 확인이 필수입니다.",
        )
    return (
        constants["risk.jeonse_ratio_weight_5"],
        "high",
        f"전세가율이 {threshold_4}% 이상으로 이른바 깡통전세 위험이 매우 큽니다.",
    )


def _loan_share_factor(
    loan_share_pct: float, *, constants: Mapping[str, object]
) -> tuple[float, str, str]:
    threshold_3 = constants["risk.loan_share_threshold_3"]
    s = float(loan_share_pct or 0)
    if s < constants["risk.loan_share_threshold_1"]:
        return 0, "low", "보증금 대부분을 자기자본으로 조달해 대출 상환 부담이 낮습니다."
    if s < constants["risk.loan_share_threshold_2"]:
        return (
            constants["risk.loan_share_weight_2"],
            "medium",
            "보증금의 일부를 대출로 조달합니다. 금리 변동에 유의하세요.",
        )
    if s < threshold_3:
        return (
            constants["risk.loan_share_weight_3"],
            "medium",
            "보증금의 절반 이상이 대출입니다. 보증금 미반환 시 상환 부담이 큽니다.",
        )
    return (
        constants["risk.loan_share_weight_4"],
        "high",
        f"보증금의 {threshold_3}% 이상이 대출로, 보증금 사고 시 부채만 남을 위험이 있습니다.",
    )


def _deposit_size_factor(
    deposit_krw: int, guarantee_deposit_cap_krw: int, *, constants: Mapping[str, object]
) -> tuple[float, str, str, float]:
    """보증금이 **가입 가능한 전세보증금 상한**의 몇 %인가 (F-4).

    이전에는 분모가 `risk.guarantee_limit_krw`(7억) 였고 이름도 「보증 한도」였다.
    **둘 다 틀렸다** (FINDINGS.md A3-2 · A3-3). 7억은 보증한도가 아니라 가입요건
    상한이고(수도권 7억 / 그 외 5억), 진짜 보증한도는 「주택가격 x 90% - 선순위채권」
    이라는 **물건별 산식**이라 상수가 될 수 없다. 주택가격도 선순위채권도 입력에
    없으므로 그 산식은 이 도구가 계산하지 않는다 — 이름을 맞추고, 계산하지 않는 것을
    계산하는 척하지 않는다.
    """
    deposit = safe_int(deposit_krw)
    share = ratio(deposit, safe_int(guarantee_deposit_cap_krw)) * 100
    if share < constants["risk.deposit_size_threshold_1"]:
        return 0, "low", "보증금 규모가 가입 가능 상한 대비 여유가 있어 보증 가입이 수월합니다.", share
    if share < constants["risk.deposit_size_threshold_2"]:
        return (
            constants["risk.deposit_size_weight_2"],
            "medium",
            "보증금이 가입 가능 상한의 절반을 넘어 물건별 보증한도(주택가격 x 90% - 선순위채권)를 "
            "미리 확인해야 합니다.",
            share,
        )
    return (
        constants["risk.deposit_size_weight_3"],
        "high",
        "보증금이 가입 가능 상한에 근접해 보증 가입이 거절될 수 있습니다.",
        share,
    )


def _market_factor(
    market_risk: str, *, constants: Mapping[str, object]
) -> tuple[float, str, str, float]:
    key = (market_risk or "medium").lower()
    table = {
        "low": (
            0,
            "low",
            "해당 지역 임대차 시장은 수요가 안정적인 편입니다.",
            constants["risk.market_value_pct_low"],
        ),
        "medium": (
            constants["risk.market_weight_medium"],
            "medium",
            "해당 지역은 거래량·시세 변동을 주기적으로 확인할 필요가 있습니다.",
            constants["risk.market_value_pct_medium"],
        ),
        "high": (
            constants["risk.market_weight_high"],
            "high",
            "해당 지역은 시세 하락·거래 위축 위험이 상대적으로 큽니다.",
            constants["risk.market_value_pct_high"],
        ),
    }
    return table.get(key, table["medium"])


def _exposure_multiplier(deposit_krw: int, *, constants: Mapping[str, object]) -> float:
    """Small deposits carry proportionally less downside, so damp their weight."""
    deposit = safe_int(deposit_krw)
    if deposit >= constants["risk.low_exposure_krw"]:
        return 1.0
    if deposit >= constants["risk.minimal_exposure_krw"]:
        return constants["risk.exposure_multiplier_low"]
    return constants["risk.exposure_multiplier_minimal"]


def scan_deposit_risk(
    deposit_krw: int,
    jeonse_ratio_pct: float,
    loan_amount_krw: int = 0,
    guarantee_available: bool = True,
    market_risk: str = "medium",
    region_name: str = "",
    *,
    guarantee_deposit_cap_krw: int,
    constants: Mapping[str, object],
) -> dict:
    """Score deposit-return risk for one contract. Pure and deterministic.

    `guarantee_deposit_cap_krw` is HUG's published ceiling on the deposit that
    can be guaranteed at all (수도권 7억 / 그 외 5억, F-4). Keyword-only with **no
    default** — a default would quietly decide whether this deposit counts as
    guaranteeable (SPEC 5.1.1 fail-closed).
    """
    band_low_max = constants["risk.band_low_max"]
    band_medium_max = constants["risk.band_medium_max"]
    minimal_exposure_krw = constants["risk.minimal_exposure_krw"]

    deposit = safe_int(deposit_krw)
    loan = min(safe_int(loan_amount_krw), deposit)
    loan_share = ratio(loan, deposit) * 100
    exposure = _exposure_multiplier(deposit, constants=constants)

    factors = []
    score = 0.0

    weight, impact, note = _jeonse_ratio_factor(jeonse_ratio_pct, constants=constants)
    weight = weight * exposure
    score += weight
    factors.append(
        {
            "name": "전세가율",
            "valuePct": round(float(jeonse_ratio_pct or 0), 1),
            "impact": impact if exposure >= 1.0 else "low",
            "note": note,
        }
    )

    # 지역 조건뿐 아니라 **보증금 상한**도 가입 가능 여부를 가른다 (F-4 · F-5).
    # TCO 가 상한 초과 시 보증료를 빼면서 여기서는 「가입 가능」이라고 말하면 두
    # 엔진이 어긋나고, 어긋난 쪽은 하필 관대한 쪽이다 (보증료도 안 내고 위험 가중치도
    # 안 붙는다). 같은 사실을 두 엔진이 같게 읽도록 여기서 좁힌다.
    over_cap = deposit > safe_int(guarantee_deposit_cap_krw)
    if guarantee_available and not over_cap:
        g_weight, g_impact = 0, "low"
        g_note = "전세보증금반환보증 가입이 가능한 지역·물건 조건입니다. 가입을 강력히 권장합니다."
    elif over_cap:
        g_weight = constants["risk.guarantee_unavailable_weight"]
        g_impact = "high"
        g_note = (
            f"보증금이 가입 가능한 전세보증금 상한 {money(guarantee_deposit_cap_krw)}을 "
            "넘어 반환보증에 가입할 수 없습니다. 보증금 미반환 시 회수 수단이 제한됩니다."
        )
    else:
        g_weight = constants["risk.guarantee_unavailable_weight"]
        g_impact = "high"
        g_note = "보증보험 가입이 어려운 조건입니다. 보증금 미반환 시 회수 수단이 제한됩니다."
    score += g_weight * (
        1.0
        if deposit >= minimal_exposure_krw
        else constants["risk.guarantee_small_deposit_multiplier"]
    )
    factors.append(
        {
            "name": "보증보험 가입 가능성",
            "valuePct": 100.0 if (guarantee_available and not over_cap) else 0.0,
            "impact": g_impact,
            "note": g_note,
        }
    )

    l_weight, l_impact, l_note = _loan_share_factor(loan_share, constants=constants)
    score += l_weight * exposure
    factors.append(
        {
            "name": "보증금 내 대출 비중",
            "valuePct": round(loan_share, 1),
            "impact": l_impact if exposure >= 1.0 else "low",
            "note": l_note,
        }
    )

    d_weight, d_impact, d_note, d_share = _deposit_size_factor(
        deposit, guarantee_deposit_cap_krw, constants=constants
    )
    score += d_weight
    factors.append(
        {
            "name": "보증금 규모 (가입 가능 상한 대비)",
            "valuePct": round(d_share, 1),
            "impact": d_impact,
            "note": d_note,
        }
    )

    m_weight, m_impact, m_note, m_value = _market_factor(market_risk, constants=constants)
    score += m_weight
    factors.append(
        {
            "name": "지역 임대차 시장 여건",
            "valuePct": m_value,
            "impact": m_impact,
            "note": m_note,
        }
    )

    total = int(max(0, min(100, round(score))))
    if total <= band_low_max:
        band = "low"
    elif total <= band_medium_max:
        band = "medium"
    else:
        band = "high"

    where = region_name or "선택 지역"
    rationale = [
        f"{where} 기준 보증금 {money(deposit)}에 대한 위험 점수는 100점 만점에 "
        f"{total}점({band})입니다."
    ]
    if deposit <= 0:
        rationale.append("보증금이 없어 보증금 미반환 위험은 사실상 없습니다.")
    else:
        if exposure < 1.0:
            rationale.append(
                f"보증금이 {money(deposit)}으로 소액이어서 전세가율·대출비중 가중치를 "
                f"{pct(exposure * 100, 0)} 수준으로 완화 적용했습니다."
            )
        top = sorted(factors, key=lambda f: IMPACTS.index(f["impact"]), reverse=True)[0]
        rationale.append(f"가장 큰 위험 요인은 '{top['name']}'입니다: {top['note']}")

    band_message = {
        "low": "계약 전 등기부등본 확인과 확정일자·전입신고만 지키면 관리 가능한 수준입니다.",
        "medium": "선순위 채권과 임대인 세금 체납 여부를 반드시 확인하고 보증보험에 가입하세요.",
        "high": "현재 조건으로는 계약을 재검토하거나 보증금을 낮춘 대안을 우선 검토하세요.",
    }[band]
    rationale.append(band_message)
    rationale.append(
        "위험 점수는 공개된 일반 지표를 단순화한 프로토타입 산식이며, 실제 계약 심사 결과와 "
        "다를 수 있습니다."
    )

    return {"score": total, "band": band, "factors": factors, "rationale": rationale}
