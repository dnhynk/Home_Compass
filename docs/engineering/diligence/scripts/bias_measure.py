"""6차 실사 — 파생 비율 2종의 **모집단 불일치 편향**을 실측한다.

    python docs/engineering/diligence/scripts/bias_measure.py --cache var/molit_cache

이 스크립트는 **읽기 전용 조사 도구**다. 제품 코드를 import 해서 쓰되 고치지 않고,
저장소(SQLite)에도 쓰지 않는다. 산출물은 표준출력과 `--json` 파일뿐이다.

무엇을 재는가
-------------
현행 파이프라인은 두 파생 비율을 **중앙값의 비**로 낸다.

    전세가율   = median(전세 보증금) / median(매매 금액) x 100
    전월세전환율 = median(월세) x 12 / (median(전세 보증금) - median(월세 보증금)) x 100

세 중앙값이 **서로 다른 표본**에서 나온다 — 전세 계약 / 월세 계약 / 매매 계약은
같은 물건이 아니다. 전세 쪽에 크고 비싼 매물이 쏠리면 분모가 부풀어 전환율이 낮게 나온다.

그래서 같은 조건을 **짝지어서** 다시 계산하고 두 값을 나란히 놓는다.

    B1 (현행)  지역 전체 표본의 중앙값의 비
    B2 (짝지음) 같은 **법정동 + 단지명 + 전용면적 구간**(=셀) 안에서 비를 구하고,
               그 비들의 중앙값

집계 조건은 현행 파이프라인과 **동일하게** 건다 — 아파트 · 85m^2 이하 · 최근 3개월 ·
같은 시군구. 조건을 바꾸면 편향이 아니라 조건 차이를 재게 된다. 그래서 정규화·중앙값·
산식은 전부 `home_compass.ingest.market` 의 함수를 그대로 부른다.

짝짓기 규약 (이 스크립트의 유일한 새 선택)
------------------------------------------
셀 키 = `(umdNm, aptNm, 면적구간)`.

* `aptNm` 만으로는 부족하다 — 같은 시군구 안에 같은 이름의 단지가 여럿 있다.
  응답이 주는 `umdNm`(법정동)을 앞에 붙인다.
* 면적구간은 **정수 m^2 반올림**이 기본이다. 한 단지 안의 같은 평형은 59.82/59.92/59.99
  처럼 소수점만 다르고, 다른 평형은 59 vs 84 처럼 멀다.
  `--band 5` 로 5m^2 폭 구간(경계 고정)으로 바꿔 민감도를 볼 수 있다.
* 셀 안에서 각 통계의 중앙값을 먼저 구하고 **셀 하나당 비 하나**를 만든다.
  거래를 데카르트 곱으로 짝지으면 거래가 많은 셀이 중앙값을 지배한다.
* 짝이 성립하지 않은 셀(한쪽만 있는 셀)은 **버리지 않고 센다.** 그 수가 결과다.

`observed_at`/`fetched_at` 같은 계보는 여기서 만들지 않는다 — 이 스크립트의 출력은
제품 데이터가 아니라 실사 근거다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from home_compass.ingest.market.pipeline import (  # noqa: E402
    LOOKBACK_KEY,
    MAX_AREA_KEY,
    MAX_ATTEMPTS_KEY,
    MIN_SAMPLE_KEY,
    TIMEOUT_KEY,
    Deal,
    Trade,
    conversion_rate_pct,
    jeonse_ratio_pct,
    median_krw,
    normalize_deals,
    normalize_trades,
    window_months,
)
from home_compass.ingest.market.source import MolitClient  # noqa: E402

KST = timezone(timedelta(hours=9))

REGIONS_JSON = REPO_ROOT / "backend" / "src" / "home_compass" / "data" / "regions.json"
CONSTANTS_JSON = REPO_ROOT / "contracts" / "model_constants.json"

#: 한국부동산원 공표값 — **주택유형 = 아파트 · 시군구 단위**. 6차 실사가 KOSIS 그리드에서
#: 직접 읽었다 (`excerpts/R8-부동산원-산출방법과-시군구-공표값.md` 에 도달 경로와 원문).
#:
#:     전월세전환율   orgId=408 tblId=DT_30404_N0010 「지역별 전월세전환율」   2026.05
#:     전세가율       orgId=408 tblId=DT_30404_N0006_R1 「유형별 매매가격 대비 전세가격 비율」 2026.06
#:
#: 2차 실사(FINDINGS-2.md R3)는 권역 단위까지만 읽었다. **시군구까지 내려간다** —
#: 그래서 우리 지역 10건 전부와 1:1 로 맞춰 볼 수 있다. 시점이 다른 것은 그대로 적는다:
#: 두 공표값의 최신 시점이 각각 2026.05 · 2026.06 이고, 우리 표본은 2026.06~08 계약이다.
REB_PUBLISHED_APT = {
    # code: (라벨, 전월세전환율 2026.05, 전세가율 2026.06)
    "11440": ("서울 마포", 4.8, 49.2),
    "11620": ("서울 관악", 4.7, 58.3),
    "11200": ("서울 성동", 5.0, 44.5),
    "11350": ("서울 노원", 4.8, 54.8),
    "41117": ("경기 수원 영통", 4.9, 63.1),
    "41281": ("경기 고양 덕양", 5.0, 71.9),
    "26350": ("부산 해운대", 5.1, 57.1),
    "30200": ("대전 유성", 5.0, 71.1),
    "27260": ("대구 수성", 5.1, 61.3),
    "12330": ("광주 광산", 6.0, 77.8),
}


# --------------------------------------------------------------------------
# 입력 — 전부 저장소 밖의 파일에서 읽는다 (SQLite 를 열지 않는다)
# --------------------------------------------------------------------------


def load_regions() -> list[tuple[str, str]]:
    data = json.loads(REGIONS_JSON.read_text(encoding="utf-8"))
    return [(r["code"], r["name"]) for r in data["regions"]]


def load_constants() -> dict[str, Any]:
    """`contracts/model_constants.json` 의 동결값. 파이프라인이 저장소에서 읽는 것과
    같은 값이며(시드가 이 파일에서 나온다), 여기서 기본값을 만들지 않는다."""
    data = json.loads(CONSTANTS_JSON.read_text(encoding="utf-8"))
    return {e["key"]: e.get("frozen_current_value") for e in data["entries"]}


# --------------------------------------------------------------------------
# 수집 — 캐시를 쓴다. 같은 표를 다시 만들 때 API 를 또 두드리지 않기 위해서다
# --------------------------------------------------------------------------


def fetch_all(
    client: MolitClient | None,
    *,
    regions: Sequence[tuple[str, str]],
    window: Sequence[str],
    cache_dir: Path | None,
) -> tuple[dict[tuple[str, str], list[dict[str, str]]], dict[str, int]]:
    """`(service, region_code) -> 원시 항목들`. 호출 통계도 함께 돌려준다."""
    raw: dict[tuple[str, str], list[dict[str, str]]] = {}
    stats = {"api_calls": 0, "cache_hits": 0, "items": 0}
    for service in ("rent", "trade"):
        for code, _name in regions:
            items: list[dict[str, str]] = []
            for ym in window:
                cached = None
                path = None
                if cache_dir is not None:
                    path = cache_dir / f"{service}-{code}-{ym}.json"
                    if path.is_file():
                        cached = json.loads(path.read_text(encoding="utf-8"))
                if cached is not None:
                    stats["cache_hits"] += 1
                    items.extend(cached)
                    continue
                if client is None:
                    raise SystemExit(
                        f"캐시에 {service}/{code}/{ym} 가 없고 API 키도 없다. "
                        "값을 지어내지 않으므로 여기서 멈춘다"
                    )
                batch = client.fetch(service, code, ym)
                stats["api_calls"] += 1
                if path is not None:
                    path.write_text(
                        json.dumps(batch, ensure_ascii=False), encoding="utf-8"
                    )
                items.extend(batch)
            stats["items"] += len(items)
            raw[(service, code)] = items
    return raw, stats


# --------------------------------------------------------------------------
# 짝짓기
# --------------------------------------------------------------------------


def area_band(area_sqm: float, band: float) -> str:
    """면적구간 라벨. `band <= 0` 이면 정수 m^2 반올림, 아니면 고정폭 구간."""
    if band <= 0:
        return f"~{round(area_sqm)}"
    lower = int(area_sqm // band) * band
    return f"[{lower:g},{lower + band:g})"


def cell_key(umd: str, apt: str, area_sqm: float, band: float) -> tuple[str, str, str]:
    return (umd.strip(), apt.strip(), area_band(area_sqm, band))


def group_deals(
    deals: Iterable[Deal], band: float
) -> dict[tuple[str, str, str], list[Deal]]:
    cells: dict[tuple[str, str, str], list[Deal]] = defaultdict(list)
    for d in deals:
        cells[cell_key(d.umd_name, d.apt_name, d.exclusive_area_sqm, band)].append(d)
    return cells


def group_trades(
    trades: Iterable[Trade], band: float
) -> dict[tuple[str, str, str], list[Trade]]:
    cells: dict[tuple[str, str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        cells[cell_key(t.umd_name, t.apt_name, t.exclusive_area_sqm, band)].append(t)
    return cells


def _median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


# --------------------------------------------------------------------------
# 한 지역
# --------------------------------------------------------------------------


def measure_region(
    code: str,
    name: str,
    *,
    raw_rent: Sequence[Mapping[str, str]],
    raw_trade: Sequence[Mapping[str, str]],
    max_area: float,
    min_sample: int,
    band: float,
) -> dict[str, Any]:
    deals = normalize_deals(raw_rent, region_code=code, max_area_sqm=max_area)
    trades = normalize_trades(raw_trade, region_code=code, max_area_sqm=max_area)
    jeonse = [d for d in deals if d.is_jeonse]
    monthly = [d for d in deals if not d.is_jeonse]

    # ---- B1: 현행 방식 (제품 함수를 그대로 부른다) -------------------------
    jeonse_median = median_krw([d.deposit_krw for d in jeonse])
    deposit_median = median_krw([d.deposit_krw for d in monthly])
    rent_median = median_krw([d.monthly_rent_krw for d in monthly])
    trade_median = (
        median_krw([t.amount_krw for t in trades]) if len(trades) >= min_sample else None
    )
    b1_ratio = jeonse_ratio_pct(jeonse_median, trade_median)
    b1_conv = conversion_rate_pct(jeonse_median, deposit_median, rent_median)

    # ---- B2: 짝지은 방식 ---------------------------------------------------
    jeonse_cells = group_deals(jeonse, band)
    monthly_cells = group_deals(monthly, band)
    trade_cells = group_trades(trades, band)

    # 전세가율 — 셀마다 median(전세)/median(매매)
    ratio_cells: list[dict[str, Any]] = []
    for key in sorted(set(jeonse_cells) & set(trade_cells)):
        j = _median_or_none([d.deposit_krw for d in jeonse_cells[key]])
        t = _median_or_none([x.amount_krw for x in trade_cells[key]])
        if not j or not t:
            continue
        ratio_cells.append(
            {
                "cell": list(key),
                "jeonse": j,
                "trade": t,
                "ratio_pct": round(j / t * 100, 2),
                "n_jeonse": len(jeonse_cells[key]),
                "n_trade": len(trade_cells[key]),
            }
        )
    b2_ratio = (
        round(statistics.median([c["ratio_pct"] for c in ratio_cells]), 2)
        if ratio_cells
        else None
    )

    # 전월세전환율 — 셀마다 median(월세)*12 / (median(전세) - median(월세보증금))
    conv_cells: list[dict[str, Any]] = []
    conv_nonpositive = 0
    for key in sorted(set(jeonse_cells) & set(monthly_cells)):
        j = median_krw([d.deposit_krw for d in jeonse_cells[key]])
        dep = median_krw([d.deposit_krw for d in monthly_cells[key]])
        rent = median_krw([d.monthly_rent_krw for d in monthly_cells[key]])
        value = conversion_rate_pct(j, dep, rent)
        if value is None:
            # 분모 <= 0 — 월세 보증금이 전세 중앙값 이상인 셀. **버리지 않고 센다.**
            conv_nonpositive += 1
            continue
        conv_cells.append(
            {
                "cell": list(key),
                "jeonse": j,
                "deposit": dep,
                "rent": rent,
                "conversion_pct": value,
                "n_jeonse": len(jeonse_cells[key]),
                "n_monthly": len(monthly_cells[key]),
            }
        )
    b2_conv = (
        round(statistics.median([c["conversion_pct"] for c in conv_cells]), 2)
        if conv_cells
        else None
    )

    return {
        "code": code,
        "name": name,
        "samples": {
            "rent_raw": len(raw_rent),
            "trade_raw": len(raw_trade),
            "deals_used": len(deals),
            "jeonse": len(jeonse),
            "monthly": len(monthly),
            "trades": len(trades),
        },
        "cells": {
            "jeonse": len(jeonse_cells),
            "monthly": len(monthly_cells),
            "trade": len(trade_cells),
            "ratio_matched": len(ratio_cells),
            "ratio_jeonse_only": len(set(jeonse_cells) - set(trade_cells)),
            "ratio_trade_only": len(set(trade_cells) - set(jeonse_cells)),
            "conv_matched": len(conv_cells),
            "conv_nonpositive_denominator": conv_nonpositive,
            "conv_jeonse_only": len(set(jeonse_cells) - set(monthly_cells)),
            "conv_monthly_only": len(set(monthly_cells) - set(jeonse_cells)),
        },
        # ★ 셀 수만으로는 [표본의 몇 %가 짝을 찾았나]를 말할 수 없다. 거래 1건짜리 셀과
        #   30건짜리 셀이 같은 1로 세어지기 때문이다. 그래서 **거래 건수**로도 센다.
        "coverage": {
            "jeonse_in_ratio_pairs": sum(len(jeonse_cells[k]) for k in
                                         set(jeonse_cells) & set(trade_cells)),
            "trade_in_ratio_pairs": sum(len(trade_cells[k]) for k in
                                        set(jeonse_cells) & set(trade_cells)),
            "jeonse_in_conv_pairs": sum(len(jeonse_cells[k]) for k in
                                        set(jeonse_cells) & set(monthly_cells)),
            "monthly_in_conv_pairs": sum(len(monthly_cells[k]) for k in
                                         set(jeonse_cells) & set(monthly_cells)),
        },
        "b1": {
            "jeonse_median": jeonse_median,
            "deposit_median": deposit_median,
            "rent_median": rent_median,
            "trade_median": trade_median,
            "jeonse_ratio_pct": b1_ratio,
            "conversion_rate_pct": b1_conv,
        },
        "b2": {"jeonse_ratio_pct": b2_ratio, "conversion_rate_pct": b2_conv},
        "ratio_cells": ratio_cells,
        "conv_cells": conv_cells,
    }


# --------------------------------------------------------------------------
# 보고
# --------------------------------------------------------------------------


def _fmt(value: float | None, width: int = 6) -> str:
    return "접근실패" if value is None else f"{value:>{width}.2f}"


def _share(used: int, total: int) -> str:
    return f"{used}/{total} ({used / total * 100:.1f}%)" if total else "0/0 (—)"


def _delta(b1: float | None, b2: float | None) -> tuple[str, str, str]:
    """(절대차, 상대차, 방향). 값이 없으면 세 칸 다 비운다 — 채우지 않는다."""
    if b1 is None or b2 is None:
        return ("—", "—", "—")
    abs_d = b1 - b2
    rel = abs_d / b2 * 100 if b2 else float("nan")
    direction = "B1이 낮다" if abs_d < 0 else ("B1이 높다" if abs_d > 0 else "같다")
    return (f"{abs_d:+.2f}", f"{rel:+.1f}%", direction)


def print_report(results: Sequence[dict[str, Any]], *, band: float, window: Sequence[str],
                 stats: Mapping[str, int]) -> None:
    print(f"\n수집 창(DEAL_YMD): {tuple(window)}")
    print(f"면적구간: {'정수 m^2 반올림' if band <= 0 else f'{band:g}m^2 고정폭'}")
    print(f"API 호출 {stats['api_calls']}건 · 캐시 적중 {stats['cache_hits']}건 · "
          f"원시 항목 {stats['items']}건")

    print("\n## 표본")
    print("| 지역 | 전월세 원시 | 집계 | 전세 | 월세 | 매매 원시 | 매매 집계 |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        s = r["samples"]
        print(f"| {r['code']} {r['name']} | {s['rent_raw']} | {s['deals_used']} | "
              f"{s['jeonse']} | {s['monthly']} | {s['trade_raw']} | {s['trades']} |")

    print("\n## 짝짓기 성립률 — 셀이 아니라 **거래 건수**로 센다")
    print("| 지역 | 전세가율: 짝지은 전세 | 짝지은 매매 | 전환율: 짝지은 전세 | 짝지은 월세 |")
    print("|---|---|---|---|---|")
    for r in results:
        s, c = r["samples"], r["coverage"]
        print(f"| {r['code']} {r['name']} | {_share(c['jeonse_in_ratio_pairs'], s['jeonse'])} | "
              f"{_share(c['trade_in_ratio_pairs'], s['trades'])} | "
              f"{_share(c['jeonse_in_conv_pairs'], s['jeonse'])} | "
              f"{_share(c['monthly_in_conv_pairs'], s['monthly'])} |")

    print("\n## 전세가율 — B1(중앙값의 비) vs B2(비의 중앙값)")
    print("| 지역 | B1 | B2 | 절대차 | 상대차 | 방향 | 짝 성립 셀 | 전세만 | 매매만 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        b1, b2 = r["b1"]["jeonse_ratio_pct"], r["b2"]["jeonse_ratio_pct"]
        a, rel, d = _delta(b1, b2)
        c = r["cells"]
        print(f"| {r['code']} {r['name']} | {_fmt(b1)} | {_fmt(b2)} | {a} | {rel} | {d} | "
              f"{c['ratio_matched']} | {c['ratio_jeonse_only']} | {c['ratio_trade_only']} |")

    print("\n## 전월세전환율 — B1(중앙값의 비) vs B2(비의 중앙값)")
    print("| 지역 | B1 | B2 | 절대차 | 상대차 | 방향 | 짝 성립 셀 | 분모<=0 셀 | 전세만 | 월세만 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        b1, b2 = r["b1"]["conversion_rate_pct"], r["b2"]["conversion_rate_pct"]
        a, rel, d = _delta(b1, b2)
        c = r["cells"]
        print(f"| {r['code']} {r['name']} | {_fmt(b1)} | {_fmt(b2)} | {a} | {rel} | {d} | "
              f"{c['conv_matched']} | {c['conv_nonpositive_denominator']} | "
              f"{c['conv_jeonse_only']} | {c['conv_monthly_only']} |")

    for title, key, index in (
        ("전월세전환율", "conversion_rate_pct", 1),
        ("전세가율", "jeonse_ratio_pct", 2),
    ):
        print(f"\n## 공표값과의 거리 — {title} (한국부동산원 아파트 · 시군구)")
        print("| 지역 | 공표값 | B1 | B1 차이 | B2 | B2 차이 |")
        print("|---|---|---|---|---|---|")
        errors: dict[str, list[float]] = {"b1": [], "b2": []}
        for r in results:
            row = REB_PUBLISHED_APT.get(r["code"])
            if row is None:
                continue
            label, published = row[0], row[index]
            b1, b2 = r["b1"][key], r["b2"][key]
            cells = []
            for tag, value in (("b1", b1), ("b2", b2)):
                if value is None:
                    cells.append("—")
                    continue
                errors[tag].append(abs(value - published))
                cells.append(f"{value - published:+.2f}")
            print(f"| {r['code']} {r['name']} | {published} ({label}) | {_fmt(b1)} | {cells[0]} | "
                  f"{_fmt(b2)} | {cells[1]} |")
        # ★ 요약 한 줄을 **계산해서** 낸다. 표를 눈으로 읽고 옮겨 적으면 그 순간 근거가 끊긴다.
        for tag in ("b1", "b2"):
            values = errors[tag]
            if values:
                print(f"  {tag.upper()} 평균절대오차(MAE) = {sum(values) / len(values):.2f}%p "
                      f"({len(values)}개 지역)")


def print_risk_bands(results: Sequence[dict[str, Any]], constants: Mapping[str, Any]) -> None:
    """전세가율이 `risk` 엔진의 어느 가중치 밴드에 떨어지는지. **판단 재료일 뿐 권고가 아니다.**

    밴드 경계와 가중치는 `contracts/model_constants.json` 에서 읽는다 — 여기에 숫자를
    적으면 등재된 상수와 두 벌이 된다 (SPEC 5.1.2 가 금지하는 것).
    """
    edges = [float(constants[f"risk.jeonse_ratio_threshold_{i}"]) for i in (1, 2, 3, 4)]
    weights = [float(constants[f"risk.jeonse_ratio_weight_{i}"]) for i in (1, 2, 3, 4, 5)]

    def band(value: float | None) -> str:
        if value is None:
            return "—"
        if value <= 0:
            return "0 (정보없음)"
        for edge, weight in zip(edges, weights):
            if value < edge:
                return f"{weight:g} (<{edge:g})"
        return f"{weights[4]:g} (>={edges[3]:g})"

    print("\n## 전세가율이 떨어지는 risk 가중치 밴드 (engines/risk.py `_jeonse_ratio_factor`)")
    print(f"  경계 {edges} · 가중치 {weights} — 전부 contracts/model_constants.json 에서 읽었다")
    print("| 지역 | B1 | 밴드 | B2 | 밴드 | 공표값 | 밴드 |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        row = REB_PUBLISHED_APT.get(r["code"])
        published = row[2] if row else None
        b1, b2 = r["b1"]["jeonse_ratio_pct"], r["b2"]["jeonse_ratio_pct"]
        print(f"| {r['code']} {r['name']} | {_fmt(b1)} | {band(b1)} | {_fmt(b2)} | {band(b2)} | "
              f"{'—' if published is None else published} | {band(published)} |")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="파생 비율의 모집단 불일치 편향 실측")
    parser.add_argument("--cache", help="원시 응답 캐시 디렉터리 (없으면 캐시하지 않는다)")
    parser.add_argument("--offline", action="store_true",
                        help="캐시만 쓴다. 없는 창이 있으면 실패한다 (값을 지어내지 않는다)")
    parser.add_argument("--band", type=float, default=0.0,
                        help="면적구간 폭 m^2. 0 이면 정수 m^2 반올림 (기본)")
    parser.add_argument("--now", help="수집 창 기준 시각 (RFC 3339). 없으면 현재 KST")
    parser.add_argument("--json", help="원자료를 포함한 결과를 이 경로에 쓴다")
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(KST)
    constants = load_constants()
    regions = load_regions()
    window = window_months(now, int(constants[LOOKBACK_KEY]))
    max_area = float(constants[MAX_AREA_KEY])
    min_sample = int(constants[MIN_SAMPLE_KEY])

    cache_dir = Path(args.cache) if args.cache else None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    client = None
    if not args.offline:
        client = MolitClient(
            max_attempts=int(constants[MAX_ATTEMPTS_KEY]),
            timeout_seconds=float(constants[TIMEOUT_KEY]),
        )

    raw, stats = fetch_all(client, regions=regions, window=window, cache_dir=cache_dir)

    results = [
        measure_region(
            code,
            name,
            raw_rent=raw[("rent", code)],
            raw_trade=raw[("trade", code)],
            max_area=max_area,
            min_sample=min_sample,
            band=args.band,
        )
        for code, name in regions
    ]

    print_report(results, band=args.band, window=window, stats=stats)
    print_risk_bands(results, constants)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "window": list(window),
                    "band": args.band,
                    "constants": {
                        LOOKBACK_KEY: constants[LOOKBACK_KEY],
                        MAX_AREA_KEY: constants[MAX_AREA_KEY],
                        MIN_SAMPLE_KEY: constants[MIN_SAMPLE_KEY],
                    },
                    "fetch_stats": dict(stats),
                    "regions": results,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\n결과 JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
