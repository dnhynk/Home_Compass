"""E2 — Policy & product eligibility rule engine (정책·상품 적격성 룰엔진).

Each policy in `data/policies.json` carries a machine-readable `criteria`
block. This module walks those criteria one by one and records a Korean
sentence for every check, so a user always sees *why* they were judged
eligible, conditional or ineligible — never a bare verdict.

Verdict logic:
  * any hard criterion fails                -> "ineligible"
  * all hard criteria pass, but an external
    document / budget / boundary caveat
    applies                                 -> "conditional"
  * otherwise                               -> "eligible"
"""

from __future__ import annotations

from collections.abc import Mapping

from ..common import money, pct, ratio, safe_int

STATUSES = ("eligible", "conditional", "ineligible")


def _criteria(policy: dict) -> dict:
    return policy.get("criteria") or {}


def evaluate_policy(
    profile: dict,
    policy: dict,
    region_name: str = "",
    *,
    constants: Mapping[str, object],
) -> dict:
    """Evaluate one policy against one profile. Pure and deterministic."""
    # A value within this distance of a cap is flagged as a boundary case.
    boundary_margin = constants["eligibility.boundary_margin"]
    age_cap_imminent_years = constants["eligibility.age_cap_imminent_years"]
    # Seed policies express "no cap" as an out-of-range number rather than null.
    # Registered so the judgement branch they drive is visible; slated for
    # removal in stage 2, where the rule schema expresses it as nullable.
    age_max_unlimited = constants["eligibility.age_max_unlimited_sentinel"]
    amount_unlimited = constants["eligibility.amount_unlimited_sentinel_krw"]

    crit = _criteria(policy)
    reasons: list[str] = []
    failures: list[str] = []
    caveats: list[str] = list(policy.get("conditionalChecks") or [])

    age = safe_int(profile.get("age"))
    annual_income = safe_int(profile.get("annualIncomeKRW"))
    assets = safe_int(profile.get("liquidAssetsKRW"))
    region_code = str(profile.get("regionCode") or "")
    is_homeless = bool(profile.get("isHomeless"))
    is_newlywed = bool(profile.get("isNewlywed"))
    is_sme = bool(profile.get("isSMEEmployee"))

    # --- Age ---------------------------------------------------------------
    age_min = crit.get("ageMin")
    age_max = crit.get("ageMax")
    if age_min is not None and age_max is not None and age_max < age_max_unlimited:
        label = f"만 {age_min}~{age_max}세"
        if age_min <= age <= age_max:
            reasons.append(f"{label} 요건 충족 ({age}세)")
            if age_max - age <= age_cap_imminent_years:
                caveats.append(
                    f"연령 상한({age_max}세)에 임박했습니다. 신청 시점 기준으로 재확인이 필요합니다."
                )
        else:
            msg = f"{label} 요건 미충족 ({age}세)"
            reasons.append(msg)
            failures.append(msg)

    # --- Income ------------------------------------------------------------
    income_cap = crit.get("annualIncomeMaxKRW")
    if income_cap is not None and income_cap < amount_unlimited:
        if annual_income <= income_cap:
            reasons.append(f"연소득 {money(income_cap)} 이하 충족 ({money(annual_income)})")
            if ratio(annual_income, income_cap) >= 1 - boundary_margin:
                caveats.append(
                    f"연소득이 기준선({money(income_cap)})의 {pct(ratio(annual_income, income_cap) * 100)} "
                    "수준으로 경계값에 가깝습니다. 소득 산정 방식에 따라 결과가 달라질 수 있습니다."
                )
        else:
            msg = f"연소득 {money(income_cap)} 이하 요건 미충족 ({money(annual_income)})"
            reasons.append(msg)
            failures.append(msg)

    # --- Assets ------------------------------------------------------------
    asset_cap = crit.get("assetMaxKRW")
    if asset_cap is not None and asset_cap < amount_unlimited:
        if assets <= asset_cap:
            reasons.append(f"순자산 {money(asset_cap)} 이하 충족 ({money(assets)})")
        else:
            msg = f"순자산 {money(asset_cap)} 이하 요건 미충족 ({money(assets)})"
            reasons.append(msg)
            failures.append(msg)

    # --- Boolean flags -----------------------------------------------------
    if crit.get("requireHomeless"):
        if is_homeless:
            reasons.append("무주택 요건 충족")
        else:
            msg = "무주택 요건 미충족 (주택 보유)"
            reasons.append(msg)
            failures.append(msg)

    if crit.get("requireNewlywed"):
        if is_newlywed:
            reasons.append("신혼부부(혼인 요건) 충족")
        else:
            msg = "신혼부부 전용 상품으로 혼인 요건 미충족"
            reasons.append(msg)
            failures.append(msg)

    if crit.get("requireSME"):
        if is_sme:
            reasons.append("중소·중견기업 재직 요건 충족")
        else:
            msg = "중소·중견기업 재직 요건 미충족"
            reasons.append(msg)
            failures.append(msg)

    # --- Region scope ------------------------------------------------------
    prefixes = crit.get("regionPrefixes") or []
    if prefixes:
        where = region_name or region_code or "선택 지역"
        if any(region_code.startswith(p) for p in prefixes):
            reasons.append(f"거주 지역 요건 충족 ({where})")
        else:
            msg = f"해당 지자체 거주자 전용 제도로 지역 요건 미충족 ({where})"
            reasons.append(msg)
            failures.append(msg)

    if not reasons:
        reasons.append("별도 자격 제한이 없는 제도입니다.")

    if failures:
        status = "ineligible"
    elif caveats:
        status = "conditional"
    else:
        status = "eligible"

    if status == "conditional":
        reasons.extend(caveats)

    # `notes` are informational only — they never change the verdict.
    reasons.extend(policy.get("notes") or [])

    return {
        "id": policy.get("id", ""),
        "name": policy.get("name", ""),
        "category": policy.get("category", ""),
        "status": status,
        "reasons": reasons,
        "maxAmountKRW": safe_int(policy.get("maxAmountKRW")),
        "rateRangePct": list(policy.get("rateRangePct") or [0.0, 0.0]),
        "source": policy.get("source", ""),
        "disclaimer": policy.get("disclaimer", ""),
    }


def evaluate_policies(
    profile: dict,
    policies: list,
    region_name: str = "",
    *,
    constants: Mapping[str, object],
) -> dict:
    """Evaluate every policy and return the contract-shaped list + rationale.

    Result: {"policies": [...], "rationale": [...]}
    Sorted eligible -> conditional -> ineligible so the UI can render top-down.
    """
    evaluated = [
        evaluate_policy(profile, p, region_name, constants=constants)
        for p in (policies or [])
    ]
    order = {"eligible": 0, "conditional": 1, "ineligible": 2}
    evaluated.sort(key=lambda p: (order.get(p["status"], 3), -p["maxAmountKRW"]))

    counts = {s: sum(1 for p in evaluated if p["status"] == s) for s in STATUSES}
    rationale = [
        f"총 {len(evaluated)}개 제도를 검토해 적격 {counts['eligible']}건, "
        f"조건부 {counts['conditional']}건, 부적격 {counts['ineligible']}건으로 판정했습니다."
    ]

    top = [p for p in evaluated if p["status"] == "eligible"][:2]
    for policy in top:
        rationale.append(
            f"[{policy['name']}] 적격 — " + " / ".join(policy["reasons"][:2])
        )

    conditional = [p for p in evaluated if p["status"] == "conditional"][:2]
    for policy in conditional:
        rationale.append(
            f"[{policy['name']}] 조건부 — 추가 확인이 필요합니다: {policy['reasons'][-1]}"
        )

    if counts["eligible"] == 0 and counts["conditional"] == 0:
        rationale.append(
            "현재 프로필로 즉시 적용 가능한 제도가 없습니다. "
            "소득·자산·연령 요건을 다시 확인하거나 지역을 변경해 보세요."
        )

    rationale.append(
        "정책 조건은 공개된 일반 요건을 단순화한 예시이며, 실제 심사 기준은 "
        "각 기관 공고를 따릅니다."
    )

    return {"policies": evaluated, "rationale": rationale}
