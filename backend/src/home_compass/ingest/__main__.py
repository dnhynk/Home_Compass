"""실기동 - `python -m home_compass.ingest`.

SPEC 9.3 #3 의 **배치 작업** 대응물이다 — 배치를 실제로 실행하고 저장소 변화 전후를 찍는다.
수집 대장의 숫자가 **저장소에 실제로 들어간 텍스트**와 일치하는지도 여기서 눈으로 확인한다.

    python -m home_compass.ingest                       # 임시 DB 에 실행 후 정리
    python -m home_compass.ingest --db ./var/collect.db # 파일을 남긴다
    HOME_COMPASS_STORE_URL=sqlite://./var/x.db python -m home_compass.ingest --from-env

성공하면 0, 하나라도 어긋나면 1로 끝난다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._console import force_utf8_stdout

force_utf8_stdout()  # 아래 import 보다 먼저 — 그 뒤로는 전부 한국어를 찍는다

from ..store import create_store
from ..store.factory import DEFAULT_STORE_URL, STORE_URL_ENV
from .loader import load_policy_sources
from .sources import (
    COLLECTION_RUN_AT,
    DOC_KIND_LABELS,
    INGEST_ACTION,
    LICENCE_BASIS_COPYRIGHT_ACT,
    LICENCE_BASIS_KOGL_TYPE_4,
    LICENCE_KOGL_TYPED,
    LICENCE_UNCONFIRMED,
    LICENCES_CLEARED,
    POLICIES_JSON,
    RETRIEVED_ON,
    SOURCES,
    collection_report,
    text_dir,
)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 14, 0, 52, 0, tzinfo=KST)

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def run(url: str) -> int:
    print(f"저장소 URL: {url}")
    print(f"조회일: {RETRIEVED_ON} · 취득 시각(fetched_at): {COLLECTION_RUN_AT.isoformat()}")

    section("1. 수집 대장 - 현행 policies.json 전수")
    report = collection_report()
    print(f"  {report}")
    for source in SOURCES:
        if source.loadable:
            state = "적재"
        elif source.secured:
            state = f"보류·미보관({source.licence})"
        else:
            state = "출처 미특정"
        size = f"{source.codepoints:>6,}자" if source.codepoints else "     —"
        print(f"    {source.policy_id:<24} {size}  {state:<14} {source.doc_kind or '-'}")
    # ★ `report["policies"]` 는 **대장(`SOURCES`)의 길이**이지 `policies.json` 의 건수가 아니다.
    # 그래서 여기에 건수를 적으면 대장을 대장 자신과 맞춰 보는 것이 되고, 「대장이 현행 정책을
    # 덮는가」는 실제로 아무것도 검사하지 않은 채 **손으로 적은 수만 낡는다.** PR #36 이
    # 실재하지 않는 정책 2건을 폐기한 뒤 이 줄이 `== 10` 으로 남아 실기동이 FAIL 이었다.
    # 대장이 덮어야 할 대상은 `policies.json` 이므로 **그쪽과 직접 대조**한다 — 수는 안 적는다.
    current_ids = [p["id"] for p in json.loads(POLICIES_JSON.read_text("utf-8"))["policies"]]
    check(
        "대장이 현행 정책 전부를 같은 순서로 덮는다",
        current_ids == [s.policy_id for s in SOURCES],
        f"policies.json {len(current_ids)}건",
    )
    check(
        "확보 = 적재 + 이용조건 보류 (조용히 빠진 건이 없다)",
        report["secured"] == report["loaded"] + report["blocked_by_licence"],
    )

    with create_store(url) as store:
        section("2. 적재 전 - 저장소는 비어 있다")
        before = store.policy_sources.list()
        print(f"  PolicySource {len(before)}건")
        check("전: 0건", len(before) == 0)

        section("3. 배치 실행 - load_policy_sources()")
        loaded = load_policy_sources(store, run_at=NOW)
        print(f"  적재 {len(loaded)}건: {[s.id for s in loaded]}")
        check("적재 수 = 대장의 적재 대상 수", len(loaded) == report["loaded"])

        section("4. 적재 후 - 조회해서 실제로 들어간 것을 본다")
        after = store.policy_sources.list()
        print(f"  PolicySource {len(before)}건 -> {len(after)}건")
        # 저장소는 시각을 UTC 로 정규화해 적는다 (store/README 「시각 표기」). 같은 순간이며
        # 반환값은 aware 이므로 KST 로 되돌려 찍어 대장과 눈으로 대조되게 한다.
        for stored in after:
            head = stored.text[:34].replace("\n", "⏎")
            print(
                f"    {stored.id:<28} {len(stored.text):>6,}자  "
                f"fetched_at={stored.fetched_at.astimezone(KST).isoformat()}  «{head}…»"
            )
        check(
            "fetched_at 이 대장의 취득 시각과 같은 순간",
            all(s.fetched_at == COLLECTION_RUN_AT for s in after),
        )

        section("5. NFC 정규화가 실제로 걸렸는가 (계약 결정 #7 · SPEC 4.2.1)")
        for stored in after:
            normalized = unicodedata.normalize("NFC", stored.text)
            check(
                f"{stored.id}: 저장된 텍스트가 NFC",
                unicodedata.is_normalized("NFC", stored.text)
                and normalized == stored.text,
            )

        section("6. 코드포인트 수가 대장과 일치하는가")
        ledger = {s.source_id: s for s in SOURCES}
        for stored in after:
            expected = ledger[stored.id].codepoints
            check(
                f"{stored.id}: {len(stored.text):,} == 대장 {expected:,}",
                len(stored.text) == expected,
            )

        section("7. 이용조건 게이트 - 이용조건이 확인된 문서만 들어간다")
        stored_ids = {s.id for s in after}
        blocked = [s for s in SOURCES if s.secured and s.licence not in LICENCES_CLEARED]
        for source in blocked:
            check(
                f"{source.policy_id}: 미적재 ({source.licence})",
                source.source_id not in stored_ids,
            )
            # 저장소뿐 아니라 작업트리에도 두지 않는다 — 커밋도 저장·배포다.
            check(
                f"{source.policy_id}: 작업트리에도 원문 없음",
                source.text_file is None and not (text_dir() / f"{source.policy_id}.txt").exists(),
            )
        print(
            f"  미적재 {len(blocked)}건은 대장에 URL·크기만 남는다 "
            "(SPEC 잔여 실사 — 확인하지 않은 채 저장·배포하지 않는다)"
        )
        # ★ 미적재라고 다 같은 상태가 아니다. `kogl_typed` 는 유형이 **확인된** 것이고
        #   막고 있는 것은 협의가 아니라 그 유형의 조건 판단이다 (SOURCES.md 6.2).
        #   `unconfirmed` 는 유형을 정하는 문서를 찾지 못한 것이다 (6.4). 뭉치면
        #   어느 것이 열 수 있는 문인지가 사라진다.
        for licence in (LICENCE_KOGL_TYPED, LICENCE_UNCONFIRMED):
            same = [s.policy_id for s in blocked if s.licence == licence]
            if same:
                print(f"    - {licence}: {', '.join(same)}")

        section("8. ★ 출처표시 - 계약 결정 #15 의 유일하게 남는 의무")
        print("  적재된 7건이 저장·조회 왕복 뒤에도 출처표시를 들고 있는가.")
        print("  URL 은 source_ref, 출처표시 문구는 attribution 이다 - 합치지 않는다.")
        for stored in after:
            source = ledger[stored.id]
            fetched = store.policy_sources.get(stored.id)
            print(f"    {stored.id}")
            print(f"      source_ref  = {fetched.source_ref}")
            print(f"      attribution = {fetched.attribution}")
            check(
                f"{stored.id}: 왕복 뒤에도 출처표시가 남는다",
                fetched.attribution == source.attribution and bool(fetched.attribution),
            )
            # 4요소가 실제로 문자열 안에 있는지 본다. 「비어 있지 않다」로는 부족하다.
            qualifier = source.notice_no or DOC_KIND_LABELS[source.doc_kind]
            check(
                f"{stored.id}: 기관·공고번호(또는 문서종류)·이용근거가 문구 안에 있다",
                all(
                    part in (fetched.attribution or "")
                    for part in (source.authority, qualifier, source.licence_basis)
                ),
            )
            check(f"{stored.id}: URL 이 참조 칸에 그대로 있다", fetched.source_ref == source.url)

        # 두 갈래는 지켜야 할 조건이 다르다. 계보만 보고 나눌 수 있어야 한다.
        by_basis: dict[str, list[str]] = {}
        for source in SOURCES:
            if source.loadable:
                by_basis.setdefault(source.licence_basis, []).append(source.policy_id)
        for basis, ids in by_basis.items():
            print(f"    [{basis}] {len(ids)}건: {', '.join(ids)}")
        check(
            "제4유형 2건 · 저작권법 24조의2 5건으로 갈래가 나뉜다",
            {k: len(v) for k, v in by_basis.items()}
            == {LICENCE_BASIS_KOGL_TYPE_4: 2, LICENCE_BASIS_COPYRIGHT_ACT: 5},
        )

        # 음성 - 출처표시가 없으면 적재 자체가 거부된다.
        victim = dataclasses.replace(next(s for s in SOURCES if s.loadable), authority=None)
        try:
            load_policy_sources(store, run_at=NOW, only=(victim,))
        except ValueError as exc:
            check("출처표시 없이 적재하면 거부된다", "출처표시" in str(exc), str(exc)[:60])
        else:
            check("출처표시 없이 적재하면 거부된다", False, "거부되지 않았다")

        section("9. 멱등성 - 같은 수집을 다시 돌린다")
        snapshot = [(s.id, s.text, s.source_ref, s.fetched_at) for s in after]
        load_policy_sources(store, run_at=NOW)
        again = [(s.id, s.text, s.source_ref, s.fetched_at) for s in store.policy_sources.list()]
        check("저장소 상태가 그대로", snapshot == again, f"{len(snapshot)}건")

        section("10. 감사기록 (SPEC 7.1)")
        events = store.audit.list(action=INGEST_ACTION)
        print(f"  {INGEST_ACTION} {len(events)}건, actor={sorted({e.actor for e in events})}")
        # 위에서 배치를 **두 번** 돌렸다. 저장소 상태는 멱등이지만 감사기록은 append-only 이므로
        # 두 번 돌린 사실이 그대로 남는다 — 덮어써서 한 번처럼 보이면 그것이 감사 위조다.
        check("적재 건마다 기록이 있다 (배치 2회 × 적재 건수)", len(events) == 2 * len(loaded))
        check("전부 system:ingest", {e.actor for e in events} == {"system:ingest"})

    section("결과")
    if _failures:
        print(f"  실패 {len(_failures)}건: {_failures}")
        return 1
    print("  전 항목 통과")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ingest 실기동 (수집 -> 적재)")
    parser.add_argument("--db", help="SQLite 파일 경로. 없으면 임시 파일에 실행한다")
    parser.add_argument("--from-env", action="store_true", help="HOME_COMPASS_STORE_URL 을 쓴다")
    args = parser.parse_args(argv)

    if args.from_env:
        return run(os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL)
    if args.db:
        return run(f"sqlite://{args.db}")
    with tempfile.TemporaryDirectory() as tmp:
        return run(f"sqlite://{Path(tmp) / 'ingest.db'}")


if __name__ == "__main__":
    sys.exit(main())
