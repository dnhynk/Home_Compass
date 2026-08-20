"""실기동 스모크 - `python -m firsthome.store`.

저장소에는 HTTP 가 없으므로 SPEC 9.3 #3("실제로 기동해서 손으로 호출")의 대응물은
이 스크립트다. 저장·조회·**수정 거부**를 실제로 실행하고 결과를 그대로 찍는다.

    python -m firsthome.store                      # 임시 DB 에 실행 후 정리
    python -m firsthome.store --db ./var/smoke.db  # 파일을 남긴다
    FIRSTHOME_STORE_URL=sqlite://./var/x.db python -m firsthome.store --from-env

성공하면 0, 하나라도 어긋나면 1로 끝난다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .._console import force_utf8_stdout
from . import create_store
from .errors import ProvenanceError, StoreError
from .factory import DEFAULT_STORE_URL, STORE_URL_ENV
from .models import (
    VERIFICATIONS,
    AnomalyReport,
    ApprovalRecord,
    AuditEvent,
    ModelConstant,
    PolicySource,
    Provenance,
    RuleDraft,
    RuleVersion,
)
from .seed import load_registry, seed_all

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 13, 9, 0, 0, tzinfo=KST)

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

    with create_store(url) as store:
        section("1. 시드 - 계약과 data/*.json 을 저장소로")
        counts = seed_all(store, at=NOW)
        print(f"  적재: {counts}")
        # 개수는 계약·시드 파일에서 끌어온다. 여기 숫자를 박으면 계약이 바뀔 때 조용히 어긋난다.
        expected = len(load_registry()["entries"])
        check(f"ModelConstant {expected}종 (계약 entries 전수)",
              len(store.model_constants.list()) == expected)
        check("Region 은 regions.json 전수", len(store.regions.list()) == counts["regions"])
        check("RuleVersion 은 policies.json 전수", len(store.rule_versions.list()) == counts["rule_versions"])

        section("2. 조회 - 판정에 나가는 것만 나간다 (SPEC 2.3)")
        active = store.rule_versions.active(NOW)
        print(f"  활성 규칙 {len(active)}건: {[v.policy_id for v in active][:3]} ...")
        check("전부 approved", all(v.status == "approved" for v in active))
        check("전부 origin=seed", all(v.origin == "seed" for v in active))
        check("시드에 승인자가 없다", all(v.approved_by is None for v in active))

        mapping = store.model_constants.as_mapping()
        print(f"  상수 주입 매핑 예: housing_cost_ratio_cap={mapping['affordability.housing_cost_ratio_cap']}"
              f" / living_cost_by_household={mapping['affordability.living_cost_by_household']}")
        check("가구원수 키가 int", all(isinstance(k, int) for k in mapping["affordability.living_cost_by_household"]))

        section("3. 계보 - 잘못된 Provenance 는 저장되지 않는다 (SPEC 2.1)")
        # 국면(어느 키가 아직 unverified 인가)을 못 박는 것은 이 스모크가 아니라
        # tests/store/test_seed.py 의 STILL_UNVERIFIED 자기소거 목록이다. 여기서는
        # 계약 어휘를 벗어난 값이 저장되지 않았는지만 보고 분포를 눈에 보이게 출력한다.
        # 고정 집합을 단정하면 1-② 처럼 실사가 진행될 때마다 스모크가 깨진다.
        grades = [c.provenance.verification for c in store.model_constants.list()]
        distribution = {v: grades.count(v) for v in VERIFICATIONS if grades.count(v)}
        print("  시드된 상수의 verification 분포: "
              + " / ".join(f"{k} {n}" for k, n in distribution.items()))
        check("계약 어휘(VERIFICATIONS) 안의 값뿐", set(grades) <= set(VERIFICATIONS))
        try:
            store.model_constants.put(
                ModelConstant(
                    key="bad.constant", engine="x", legacy_symbol="X", spec_class="b",
                    value_type="ratio", value=0.1,
                    provenance=Provenance("statistic", None, None, None, None, "our_choice"),
                )
            )
            check("our_choice 를 statistic 에 붙이면 거부", False, "거부되지 않았다")
        except ProvenanceError as exc:
            check("our_choice 를 statistic 에 붙이면 거부", True, str(exc)[:70])

        section("4. RuleDraft 누수 - approved 인 draft 도 판정에 못 간다 (SPEC 2.3)")
        store.policy_sources.add(
            PolicySource(id="src-1", text="만 19세 이상 34세 이하", source_ref="notice-1", fetched_at=NOW)
        )
        store.rule_drafts.add(
            RuleDraft(id="d-1", policy_source_id="src-1", policy_id="buttress_youth",
                      status="pending", payload={"criteria": {"ageMin": 19}}, created_at=NOW)
        )
        store.rule_drafts.set_status("d-1", "approved")
        after_draft = store.rule_versions.active(NOW)
        check("draft 승인 후에도 활성 규칙 수가 그대로",
              len(after_draft) == len(active), f"{len(active)} -> {len(after_draft)}")

        section("5. 재기동 없이 반영 (SPEC 2.3 캐시 금지) - 승인 -> 시민 화면 변화")
        cutover = NOW + timedelta(days=30)
        before_ids = [v.id for v in store.rule_versions.active(cutover) if v.policy_id == "buttress_youth"]
        store.approvals.add(
            ApprovalRecord(id="ap-1", actor_user_id="u-admin", at=cutover,
                           target_kind="rule_version", target_id="rv-buttress-2",
                           decision="approved", reason="공고 개정 반영")
        )
        store.rule_versions.supersede(
            "seed:buttress_youth",
            RuleVersion(
                id="rv-buttress-2", policy_id="buttress_youth",
                payload={"id": "buttress_youth", "maxAmountKRW": 250_000_000},
                status="approved", origin="human_approval",
                effective_from=cutover, effective_to=None, supersedes="seed:buttress_youth",
                approved_by="u-admin",
                provenance=Provenance("statute", "주택도시기금", None, None, None, "unverified"),
                created_at=cutover,
            ),
            at=cutover,
        )
        after_ids = [v.id for v in store.rule_versions.active(cutover) if v.policy_id == "buttress_youth"]
        print(f"  승인 전 {before_ids} -> 승인 후 {after_ids}  (같은 프로세스, 재기동 없음)")
        check("판정에 나가는 규칙이 즉시 바뀐다", before_ids != after_ids and after_ids == ["rv-buttress-2"])
        check("이전 버전은 여전히 조회된다 (이력 보존)",
              store.rule_versions.get("seed:buttress_youth").effective_to == cutover)

        section("6. 승인 위조 - 승인 기록 없는 human_approval 은 거부 (계약 #5)")
        try:
            store.rule_versions.add(
                RuleVersion(id="rv-forged", policy_id="p", payload={}, status="approved",
                            origin="human_approval", effective_from=None, effective_to=None,
                            supersedes=None, approved_by="u-admin",
                            provenance=Provenance("statute", None, None, None, None, "unverified"),
                            created_at=NOW)
            )
            check("ApprovalRecord 없는 승인 거부", False, "거부되지 않았다")
        except StoreError as exc:
            check("ApprovalRecord 없는 승인 거부", True, str(exc)[:70])

        section("6-A. 이상 신고 - RuleDraft 와 별개이고, 대상은 항목으로 한정된다 (SPEC 6.4 · 7.1)")
        versions_before = len(store.rule_versions.list())
        store.reports.add(
            AnomalyReport(id="rep-1", reporter="counselor", at=NOW,
                          target_kind="policy", target_id="buttress_youth",
                          target_field="status", reason="현장에서 종료됐다는 안내를 받았다",
                          status="open")
        )
        check("신고를 올려도 RuleVersion 이 생기지 않는다 (제안이지 변경이 아니다)",
              len(store.rule_versions.list()) == versions_before)
        check("신고가 초안 목록에 섞이지 않는다",
              [d.id for d in store.rule_drafts.list()] == ["d-1"])
        report_methods = sorted(m for m in dir(store.reports) if not m.startswith("_"))
        print(f"  AnomalyReportRepository 공개 메서드: {report_methods}")
        check("add / get / list 뿐 - 신고를 결정하는 메서드가 없다",
              report_methods == ["add", "get", "list"])
        try:
            store.reports.add(
                AnomalyReport(id="rep-2", reporter="counselor", at=NOW,
                              target_kind="policy", target_id="buttress_youth",
                              target_field="고객 상황", reason="자유 텍스트 대상",
                              status="open")
            )
            check("자유 텍스트 대상 거부", False, "거부되지 않았다")
        except StoreError as exc:
            check("자유 텍스트 대상 거부", True, str(exc)[:70])

        section("7. AuditEvent append-only 겹 (a) - 인터페이스에 수정·삭제가 없다 (SPEC 7.1)")
        store.audit.append(
            AuditEvent(id="ae-1", actor="u-admin", at=NOW, action="rule.approve",
                       target="buttress_youth", outcome="success", after={"status": "approved"})
        )
        methods = sorted(m for m in dir(store.audit) if not m.startswith("_"))
        print(f"  AuditLog 공개 메서드: {methods}")
        check("append / list 뿐", methods == ["append", "list"])
        for name in ("update", "delete", "remove"):
            check(f"audit.{name} 이 존재하지 않는다", not hasattr(store.audit, name))
        print(f"  감사기록 {len(store.audit.list())}건")

    if url.startswith("sqlite://") and not url.endswith(":memory:"):
        path = url.split("://", 1)[1]
        section("8. append-only 겹 (b) - DB 를 직접 열어 원시 SQL 로 때린다")
        conn = sqlite3.connect(path)
        for label, sql in (
            ("UPDATE audit_event", "UPDATE audit_event SET outcome='tampered'"),
            ("DELETE audit_event", "DELETE FROM audit_event"),
            ("UPDATE rule_version.payload", "UPDATE rule_version SET payload_json='{}'"),
            ("DELETE rule_version", "DELETE FROM rule_version"),
            ("effective_to 되돌리기", "UPDATE rule_version SET effective_to=NULL WHERE effective_to IS NOT NULL"),
        ):
            try:
                conn.execute(sql)
                conn.commit()
                check(f"원시 {label} 차단", False, "통과해버렸다")
            except sqlite3.IntegrityError as exc:
                check(f"원시 {label} 차단", True, str(exc))
        remaining = conn.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0]
        print(f"  감사기록 잔존: {remaining}건 (한 건도 지워지지 않았다)")
        conn.close()

    section("결과")
    if _failures:
        print(f"  실패 {len(_failures)}건: {_failures}")
        return 1
    print("  전 항목 통과")
    return 0


def main(argv: list[str] | None = None) -> int:
    # ★ 가장 먼저 부른다. 이 스크립트는 첫 줄부터 한국어를 찍으므로, 출력을 파이프·파일로
    #   넘기는 순간 cp949 에서 그 자리에서 죽는다 — 실측했다. 콘솔에서만 멀쩡했다.
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="store 실기동 스모크")
    parser.add_argument("--db", help="SQLite 파일 경로. 없으면 임시 파일에 실행한다")
    parser.add_argument("--from-env", action="store_true", help="FIRSTHOME_STORE_URL 을 쓴다")
    args = parser.parse_args(argv)

    if args.from_env:
        return run(os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL)

    if args.db:
        return run(f"sqlite://{args.db}")

    with tempfile.TemporaryDirectory() as tmp:
        return run(f"sqlite://{Path(tmp) / 'smoke.db'}")


if __name__ == "__main__":
    sys.exit(main())
