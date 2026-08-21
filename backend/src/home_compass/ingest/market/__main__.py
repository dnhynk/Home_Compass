"""실기동 — `python -m home_compass.ingest.market`.

SPEC 9.3 #3 의 **배치 작업** 대응물이다: 배치를 실제로 실행하고 저장소 변화 전후를 찍는다.
SPEC 1.3 이 요구하는 「배치를 눈앞에서 돌린다」의 진입점이며 `scripts/ingest.bat` 이 이것을 부른다.

    python -m home_compass.ingest.market --demo        # 키 없이 전 과정 (합성 거래)
    python -m home_compass.ingest.market               # 실수집 (키 필요)
    python -m home_compass.ingest.market --db ./var/market.db
    python -m home_compass.ingest.market --from-env    # HOME_COMPASS_STORE_URL 을 쓴다

**`--demo` 의 거래는 합성이다.** 화면과 계보에 그렇게 적힌다 — 시연용 숫자가 실데이터인
척하는 경로를 만들지 않는 것이 이 파일의 규율이다 (SPEC 3.1).

성공하면 0, 하나라도 어긋나면 1로 끝난다.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .._console import force_utf8_stdout

force_utf8_stdout()  # 아래 import 보다 먼저 — 그 뒤로는 전부 한국어를 찍는다

from ...store import create_store
from ...store.factory import DEFAULT_STORE_URL, STORE_URL_ENV
from ...store.models import REGION_FACT_FIELDS
from ...store.seed import seed_all
from .pipeline import (
    CONSTANT_KEYS,
    MIN_SAMPLE_KEY,
    NO_COUNTERPART_FIELDS,
    PAIR_AREA_BAND_KEY,
    RENT_DERIVED_FIELDS,
    TRADE_DERIVED_FIELDS,
    collect_market,
)
from .source import (
    API_KEY_ENV,
    ENDPOINTS,
    SERVICE_KEY_ENV,
    MolitClient,
    resolve_api_key,
)

KST = timezone(timedelta(hours=9))

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


#: `--demo` 에서 이상치를 섞을 지역. **일부러 전부가 아니다.**
#:
#: 이상치가 걸린 지역은 `unverified` 가 되고, `verification` 은 한 칸이므로 그 지역에서는
#: 나중에 `stale` 이 보이지 않는다. 전 지역에 이상치를 심으면 실기동이 10.2 의
#: 「외부 실패 시 stale」을 **한 번도 보여 주지 못한다.** 두 상태를 같은 실행에서 보려면
#: 갈라야 한다. (이 사실 자체가 보고 대상이다 — PR 본문 참조)
DEMO_OUTLIER_CODES = frozenset({"11440", "12330"})


#: 합성 거래를 흩어 놓을 단지 수. **모델 상수가 아니다** — 시연용 표본의 모양이다.
#:
#: 파생 비율 2종이 셀(법정동+단지명+전용면적 구간) 단위로 짝지어지므로(SPEC 3.1 3차 정정)
#: 한 단지에 몰아넣으면 셀이 하나가 되어 최소 건수 문턱에 걸리고, 실기동은 **두 비율이
#: 갱신되지 않는 화면**만 보여 주게 된다. 실데이터의 짝짓기는 그런 모양이 아니다
#: (실측 셀 수 67~265, FINDINGS-6.md B3·B4).
DEMO_COMPLEXES = 12


def _demo_fetch(now: datetime):
    """합성 거래. **실데이터가 아니다** — 파이프라인이 도는 것만 보인다.

    일부 지역에 이상치를 섞는다. 「자동 폐기되지 않는다」가 실기동에서도 보여야 한다.
    """
    base_year, base_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)

    def item(deposit: int, rent: int, area: float = 59.9, apt: str = "합성아파트") -> dict:
        return {
            "deposit": f"{deposit:,}", "monthlyRent": str(rent), "exclUseAr": str(area),
            "dealYear": str(base_year), "dealMonth": str(base_month), "dealDay": "15",
            "aptNm": apt, "umdNm": "합성동",
        }

    def trade(amount: int, area: float = 59.9, apt: str = "합성아파트") -> dict:
        return {
            "dealAmount": f"{amount:,}", "excluUseAr": str(area),
            "dealYear": str(base_year), "dealMonth": str(base_month), "dealDay": "15",
            "aptNm": apt, "umdNm": "합성동",
        }

    served: set[tuple[str, str]] = set()

    def fetch(service: str, region_code: str, ym: str) -> list[dict]:
        if (service, region_code) in served:
            return []
        served.add((service, region_code))
        # 지역 코드로 값을 흔들어 전 지역이 같은 숫자가 되지 않게 한다.
        bump = int(region_code[-2:])
        names = [f"합성아파트{i:02d}" for i in range(DEMO_COMPLEXES)]
        if service == "trade":
            return [trade(40_000 + bump * 100, apt=apt) for apt in names]
        deals = [item(25_000 + bump * 100, 0, apt=apt) for apt in names]
        deals += [item(2_000 + bump * 10, 70 + bump, apt=apt) for apt in names]
        if region_code in DEMO_OUTLIER_CODES:
            deals += [item(120_000, 0, apt="합성펜트하우스")]      # 이상치 1건
        return deals

    return fetch


def _live_fetch(constants: Mapping[str, Any]):
    client = MolitClient(
        max_attempts=int(constants["ingest.market_max_attempts"]),
        timeout_seconds=float(constants["ingest.market_request_timeout_seconds"]),
    )
    return client.fetch


def _print_regions(store, title: str) -> None:
    print(f"  {title}")
    for region in store.regions.list():
        engine = region.to_engine_dict()
        marks = "".join(
            {"verified": "V", "stale": "S", "unverified": "U", "our_choice": "O"}[
                region.provenance_for(name).verification
            ]
            for name in REGION_FACT_FIELDS
        )
        print(
            f"    {region.code} {region.name:<14}"
            f" 전세 {engine['jeonseMedianKRW']:>12,}"
            f" 보증 {engine['monthlyDepositKRW']:>11,}"
            f" 월세 {engine['monthlyRentKRW']:>9,}"
            f" 전세가율 {engine['jeonseRatioPct']:>6}"
            f" 전환율 {engine['conversionRatePct']:>5}"
            f"  [{marks}] {region.provenance.verification}"
        )
    print(f"    계보 표시 순서: {' '.join(REGION_FACT_FIELDS)}  (V=verified S=stale U=unverified)")


def run(url: str, *, demo: bool, now: datetime) -> int:
    print(f"저장소 URL: {url}")
    print(f"배치 시각(fetched_at): {now.isoformat()}")
    print(f"모드: {'--demo (합성 거래 · 실데이터 아님)' if demo else '실수집 (국토교통부 오픈API)'}")

    section("0. 키 상태 — 키가 없어도 배치는 정상 실패로 끝난다 (SPEC 9.2.1)")
    for service, endpoint in ENDPOINTS.items():
        key = resolve_api_key(service)
        print(f"  {service:<6} {endpoint}")
        print(f"         키: {'있음 (' + str(len(key)) + '자)' if key else '없음'}"
              f"  ({SERVICE_KEY_ENV[service]} 또는 {API_KEY_ENV})")

    with create_store(url) as store:
        section("1. 시드 — 배치 이전 상태")
        counts = seed_all(store, at=now)
        print(f"  시드: {counts}")
        _print_regions(store, "적재 전 (굳힌 실수집 시드 — 계약 결정 #40)")
        before = {r.code: r.to_engine_dict() for r in store.regions.list()}
        check("시드 지역 10건", len(before) == 10)
        # ★ **이 단정이 한 번 뒤집혔다.** 예전에는 「시드는 8필드 전부 unverified」였고
        #   그때는 여덟이 전부 예시값이라 그것이 사실이었다. 계약 결정 #40 이 시드를
        #   실수집으로 굳히면서 계보가 **필드별로 갈렸다** — 실측 5필드는 `verified`,
        #   실거래가에 대응물이 없는 3필드는 `unverified` 다 (SPEC 3.1).
        #   그래서 「전부 같다」가 아니라 **「갈려 있다」**를 조인다.
        check(
            "시드의 대응물 없는 3필드는 unverified 다",
            all(
                r.provenance_for(f).verification == "unverified"
                for r in store.regions.list() for f in NO_COUNTERPART_FIELDS
            ),
        )

        constants = store.model_constants.as_mapping()
        section("2. 모델 상수 — fail-closed 조회 (등재 전이면 여기서 거부된다)")
        for key in CONSTANT_KEYS:
            print(f"    {key:<44} = {constants[key]}")

        fetch = _demo_fetch(now) if demo else _live_fetch(constants)

        section("3. 배치 실행 — collect_market()")
        report = collect_market(store, fetch=fetch, constants=constants, now=now)
        print(f"  수집 창(DEAL_YMD): {report.window}")
        print(f"  커밋 여부: {report.committed}")
        for outcome in report.regions:
            print(
                f"    {outcome.code} 원시 전월세 {outcome.deals_read:>4}건 -> 집계 "
                f"{outcome.deals_used:>4}건 (전세 {outcome.jeonse_sample} · 월세 "
                f"{outcome.monthly_sample}) · 매매 {outcome.trades_read:>4}건 -> "
                f"{outcome.trade_sample}건"
                + (f"  실패: {outcome.error}" if outcome.error else "")
            )
        for reason in report.failures:
            print(f"    실패 사유: {reason}")

        # ★ 파생 비율 2종은 **셀 단위 비의 중앙값**이다 (SPEC 3.1 3차 정정 · 결정 #35).
        #   표본이 몇 건인가와 짝이 몇 셀인가는 **다른 사실**이므로 따로 찍는다. 최소 건수
        #   문턱은 셀 수에 걸리고(새 상수를 만들지 않았다), 미달이면 그 필드는 갱신되지
        #   않는다 — 그 사실이 화면에 안 보이면 이전 값이 새 값인 척하게 된다.
        band = constants[PAIR_AREA_BAND_KEY]
        min_cells = int(constants[MIN_SAMPLE_KEY])
        section(f"3-1. 짝짓기 — 셀 = 법정동 + 단지명 + 전용면적 {band}m^2 구간"
                f" (최소 {min_cells}셀)")
        for outcome in report.regions:
            if outcome.values is None:
                continue
            skipped = [name for name in ("jeonseRatioPct", "conversionRatePct")
                       if name not in outcome.values]
            print(
                f"    {outcome.code} 전세가율 {outcome.ratio_cells:>4}셀"
                f" · 전환율 {outcome.conversion_cells:>4}셀"
                f" (분모<=0 으로 빠진 셀 {outcome.conversion_cells_dropped})"
                + (f"  ** 문턱 미달로 갱신 안 함: {', '.join(skipped)}" if skipped else "")
            )

        section("4. ★ 이상치 — 자동 폐기되지 않는다 (SPEC 3)")
        # ★ **기록**과 **판정**을 나눠 적는다. 규칙이 [건수]에서 [비율]로 바뀐 뒤로 둘이
        #   달라졌다 — 이상치가 기록된 지역과 그 때문에 unverified 가 되는 지역은 다르다.
        #   한 줄로 뭉치면 [9개 지역이 걸렸다]로 읽혀 판정이 실제보다 나쁜 것처럼 보인다.
        marked = sorted({o.region_code for o in report.outliers if o.exceeds_threshold})
        print(f"  기록: 이상치 {len(report.outliers)}건 ·"
              f" 이상치가 있는 지역 {len(report.outlier_regions)}개 / 전체 {len(report.regions)}개")
        print(f"  판정: 비율 문턱을 넘어 unverified 가 된 지역 {len(marked)}개"
              f"{' — ' + ', '.join(marked) if marked else ' (문턱 아래는 이상이 아니라 산포다)'}")
        for outlier in report.outliers[:6]:
            print(f"    {outlier.region_code} {outlier.statistic:<18}"
                  f" 값 {outlier.value_krw:>13,.0f} vs 중앙값 {outlier.median_krw:>13,.0f}"
                  f"  {outlier.apt_name}")
        if len(report.outliers) > 6:
            print(f"    … 외 {len(report.outliers) - 6}건")
        flagged = set(report.outlier_regions)
        if flagged:
            check(
                "이상치가 있던 지역의 표본이 줄지 않았다 (폐기 아님)",
                all(o.deals_used > 0 for o in report.regions if o.code in flagged),
            )

        section("5. 배치 이후 — 저장소 변화")
        _print_regions(store, "적재 후")
        after = {r.code: r.to_engine_dict() for r in store.regions.list()}
        changed = [code for code in before if before[code] != after[code]]
        print(f"  값이 바뀐 지역: {len(changed)}개")
        if report.committed:
            check("전건 커밋 — 10개 지역 전부 갱신", len(changed) == len(before))
        else:
            check("실패 시 값은 하나도 바뀌지 않는다", changed == [])

        section("6. ★ 대응물 없는 3필드 (SPEC 3.1 · 10.2 3단계)")
        sample = store.regions.list()[0]
        for name in NO_COUNTERPART_FIELDS:
            provenance = sample.provenance_for(name)
            print(f"    {name:<20} {provenance.verification:<11} {provenance.source_name}")
            check(f"{name} 이 unverified", provenance.verification == "unverified")
            check(f"{name} 에 국토부 이름이 붙지 않았다",
                  "국토교통부" not in (provenance.source_name or ""))

        section("7. 도출된 필드의 계보 — 관측 기준시점과 취득 시각을 섞지 않는다 (결정 #12)")
        for name in RENT_DERIVED_FIELDS + TRADE_DERIVED_FIELDS:
            provenance = sample.provenance_for(name)
            print(f"    {name}")
            print(f"      verification = {provenance.verification}")
            print(f"      observed_at  = {provenance.observed_at}")
            print(f"      fetched_at   = {provenance.fetched_at}")
            print(f"      source_name  = {provenance.source_name}")
        if report.committed:
            check(
                "observed_at(거래일) 과 fetched_at(배치) 이 다르다",
                sample.provenance_for("jeonseMedianKRW").observed_at
                != sample.provenance_for("jeonseMedianKRW").fetched_at,
            )
            check(
                "Z 표기를 쓰지 않는다 (계약 결정 #4)",
                not (sample.provenance_for("jeonseMedianKRW").observed_at or "").endswith("Z"),
            )

        section("8. 멱등성 — 같은 시각으로 한 번 더 돌린다 (SPEC 10.2 3단계)")
        snapshot = _snapshot(store)
        collect_market(store, fetch=_demo_fetch(now) if demo else _live_fetch(constants),
                       constants=constants, now=now)
        check("저장소 상태가 그대로", _snapshot(store) == snapshot, f"{len(snapshot)}개 지역")

        section("9. ★ 외부 실패 — 이전 값 유지 + stale (SPEC 10.2 3단계)")

        def broken(service: str, region_code: str, ym: str) -> list[dict]:
            raise RuntimeError("실기동에서 일부러 낸 수집 실패")

        kept = {r.code: r.to_engine_dict() for r in store.regions.list()}
        # ★ 기대값을 **실패 직전 상태에서** 뽑는다. 규칙은 「이미 낡은 것은 더 낡지 않고,
        #   `verified` 였던 것만 `stale` 로 내려가고, 출처가 없던 것은 그대로」다.
        #
        #   ★★ 예전에는 `verified` 인 필드만 모아 두고 나머지를 전부 `unverified` 로 기대했다.
        #      그것은 **이 실행에서 3절이 성공했을 때만** 맞는 식이었다. 3절이 실패하면
        #      (키가 없거나 네트워크가 끊긴 정상 경로다 — SPEC 9.2.1) 그때 이미 `stale` 로
        #      내려간 필드가 9절에서 `unverified` 로 기대돼 **전 지역이 헛되이 빨간불**이 났다.
        #      굳힌 시드(결정 #40)가 `verified` 필드를 갖게 되면서 실제로 그렇게 됐다.
        #      상태를 셋으로 나눠 그대로 옮긴다 — 판정 규칙은 바꾸지 않는다.
        before_fail = {
            r.code: {n: r.provenance_for(n).verification for n in REGION_FACT_FIELDS}
            for r in store.regions.list()
        }
        failed = collect_market(store, fetch=broken, constants=constants,
                                now=now + timedelta(days=1))
        after_fail = {r.code: r.to_engine_dict() for r in store.regions.list()}
        print(f"  커밋 여부: {failed.committed} · stale 표시 지역 {len(failed.stale_marked)}개")
        check("값은 하나도 바뀌지 않았다", kept == after_fail)

        for region in store.regions.list():
            for name in RENT_DERIVED_FIELDS + TRADE_DERIVED_FIELDS:
                expected = ("stale" if before_fail[region.code][name] in ("verified", "stale")
                            else "unverified")
                check(f"{region.code} {name} -> {expected}",
                      region.provenance_for(name).verification == expected)
            for name in NO_COUNTERPART_FIELDS:
                check(f"{region.code} {name} 은 여전히 unverified (실패로 등급이 좋아지지 않는다)",
                      region.provenance_for(name).verification == "unverified")

        downgraded = sorted(c for c, names in before_fail.items()
                            if "verified" in names.values())
        print(f"  실패 직전 verified 필드를 갖고 있던 지역: {len(downgraded)}개 -> 전부 stale")
        print("  ※ 이상치가 걸린 지역은 이미 unverified 라 stale 이 보이지 않는다 —"
              " verification 이 한 칸이기 때문이며, 그 사실을 여기서 그대로 드러낸다")
        print("  ※ 3절이 이미 실패했다면 여기 오기 전에 stale 로 내려가 있다."
              " 그때 이 절이 재는 것은 **반복 실패가 더 나빠지지 않는다**는 멱등이다")

        section("10. 감사기록 (SPEC 7.1)")
        for action in ("market.ingest", "market.outlier", "market.run_failed"):
            events = store.audit.list(action=action)
            print(f"  {action:<20} {len(events)}건")
        outlier_events = store.audit.list(action="market.outlier")
        if outlier_events:
            check("이상치 기록이 폐기가 아님을 명시한다",
                  all(e.after.get("discarded") is False for e in outlier_events))

    section("결과")
    # ★ 두 가지를 섞지 않는다. 「점검 통과」는 배치가 **규칙대로 동작했다**는 뜻이지
    #   「시세가 갱신됐다」가 아니다. 키 없이 돌리면 정상 실패가 정답이며 그때도 점검은
    #   통과한다. 한 줄로 뭉치면 EXIT=0 이 「수집 성공」으로 읽힌다.
    print(f"  수집 결과: {'커밋됨 (10개 지역 갱신)' if report.committed else '미커밋 — 이전 값 유지'}")
    if _failures:
        print(f"  실기동 점검 실패 {len(_failures)}건: {_failures}")
        return 1
    print("  실기동 점검 전 항목 통과")
    return 0


def _snapshot(store) -> list[tuple]:
    return [
        (r.code, r.to_engine_dict(),
         tuple(sorted((n, p.to_dict()["verification"], p.to_dict()["fetched_at"])
                      for n, p in r.field_provenance.items())))
        for r in store.regions.list()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="시세 수집 배치 실기동 (SPEC Part 3)")
    parser.add_argument("--db", help="SQLite 파일 경로. 없으면 임시 파일에 실행한다")
    parser.add_argument("--from-env", action="store_true", help=f"{STORE_URL_ENV} 를 쓴다")
    parser.add_argument("--demo", action="store_true",
                        help="합성 거래로 전 과정을 보인다 (키 불필요 · 실데이터 아님)")
    parser.add_argument("--now", help="배치 시각 (RFC 3339). 없으면 현재 KST")
    args = parser.parse_args(argv)

    # 배치는 시계를 **한 번만** 읽는다. 아래로 내려가는 모든 시각이 같은 순간이어야
    # `observed_at`/`fetched_at` 이 어긋나지 않는다 (SPEC 5.3 의 같은 규율).
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(KST)

    if args.from_env:
        return run(os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL, demo=args.demo, now=now)
    if args.db:
        return run(f"sqlite://{args.db}", demo=args.demo, now=now)
    with tempfile.TemporaryDirectory() as tmp:
        return run(f"sqlite://{Path(tmp) / 'market.db'}", demo=args.demo, now=now)


if __name__ == "__main__":
    sys.exit(main())
