"""시연 대기 큐 초안을 **계보를 기록하며** 다시 뽑아 굳힌다 (계약 결정 #42).

    python backend/tests/store/refreeze_rule_drafts.py            # 3회 돌리고 1회차를 굳힌다
    python backend/tests/store/refreeze_rule_drafts.py --runs 1   # 1회만
    python backend/tests/store/refreeze_rule_drafts.py --from a.json b.json
                                                                  # LLM 없이 기록에서 재조립

네트워크와 `OPENAI_API_KEY` 가 필요하다. 키가 없으면 **터진다** — 키 없이 `extract_all()`
을 돌리면 SPEC 9.2.1 대로 정상 실패해 `extraction_failed` 만 남고, 그것을 굳히면
「대기 큐가 있다」는 픽스처가 조용히 거짓이 된다.

## 왜 `extract_cli` 를 쓰지 않는가

`extract_cli` 는 `NOW` 를 `2026-08-14 09:00 KST` 로 **박아 두었고** 그 값이 그대로
`RuleDraft.created_at` 이 된다. 결정 #42 는 실제 추출 시각을 쓰라고 했으므로 여기서는
건마다 호출 직전의 벽시계를 넘긴다. `extract_cli` 자체는 `ingest` 소유라 손대지 않았다.

## 왜 여러 번 돌리는가

실패가 **주사위인지 계통적인지**는 한 번 돌려서는 알 수 없고, 모르면 「이번엔 운이 나빴다」와
「이 문서는 이 모델로 안 된다」가 같은 얼굴을 한다. 그래서 여러 번 돌려 회차별 결과를
픽스처에 함께 적는다. **굳히는 것은 언제나 첫 회차다** — 결과를 보고 회차를 고르는 순간
이 픽스처가 사려던 정직성이 사라진다.

## 왜 `tests/` 에 있는가

이 스크립트는 `ingest` 를 부른다. `store` 아래에 두면 SPEC 1.2 의 `store -> ingest` 금지에
걸리고(`crosscheck/test_architecture.py`), `scripts/` 는 코디네이터 소유다. `tests/` 는
`test_` 로 시작하지 않는 도구 모듈을 이미 여럿 두고 있다 (`js_runner.py` · `memory_backend.py`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "src"))

from home_compass.config import openai_model  # noqa: E402
from home_compass.ingest.extraction import (  # noqa: E402
    MAX_ATTEMPTS_KEY,
    default_targets,
    extract_one,
)
from home_compass.ingest.extraction_verify import rule_draft_schema  # noqa: E402
from home_compass.ingest.loader import load_policy_sources  # noqa: E402
from home_compass.ingest.sources import loadable_sources  # noqa: E402
from home_compass.llm.extraction import extraction_provider  # noqa: E402
from home_compass.store import create_store  # noqa: E402
from home_compass.store.seed import SEED_DATA_DIR, seed_model_constants  # noqa: E402

KST = timezone(timedelta(hours=9))
FIXTURE = SEED_DATA_DIR / "rule_drafts.json"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iso(moment: datetime) -> str:
    return moment.astimezone(KST).isoformat()


# --------------------------------------------------------------------------
# 한 회차 — 실제로 LLM 을 부른다
# --------------------------------------------------------------------------

def run_batch(db_path: Path) -> dict:
    """`ingest` 의 적재·추출 경로를 그대로 부르고 그 결과를 기록으로 돌려준다."""
    if db_path.exists():
        db_path.unlink()

    provider = extraction_provider()
    if provider != "openai":
        raise SystemExit(
            f"추출 프로바이더가 없다 (현재: {provider}). OPENAI_API_KEY 를 넣어라 — "
            "키 없이 굳히면 extraction_failed 만 남고 그것은 승인 대상이 아니다."
        )

    requested = openai_model()
    schema = rule_draft_schema()
    started = datetime.now(KST)

    with create_store(f"sqlite://{db_path}") as store:
        seed_model_constants(store)
        constants = store.model_constants.as_mapping()
        load_policy_sources(store, run_at=started)
        ledger = {s.source_id: s for s in loadable_sources()}

        records = []
        for source_id, policy_id in default_targets(store):
            at = datetime.now(KST)
            outcome = extract_one(
                store, source_id, policy_id, constants=constants, now=at
            )
            done = datetime.now(KST)
            stored = store.policy_sources.get(source_id)
            draft = store.rule_drafts.get(outcome.draft_id)
            records.append({
                "draft": {
                    "id": draft.id,
                    "policy_source_id": draft.policy_source_id,
                    "policy_id": draft.policy_id,
                    "status": draft.status,
                    "payload": draft.payload,
                    "created_at": iso(draft.created_at),
                    "failure_reason": draft.failure_reason,
                },
                "spans": [
                    {
                        "id": s.id,
                        "field_path": s.field_path,
                        "start": s.start,
                        "end": s.end,
                        "quote": store.rule_drafts.resolve_span(s),
                    }
                    for s in store.rule_drafts.spans_for(outcome.draft_id)
                ],
                "extraction": {
                    "provider": provider,
                    "model_requested": requested,
                    "model_reported": outcome.model,
                    "started_at": iso(at),
                    "finished_at": iso(done),
                    "attempts": outcome.attempts,
                    "latency_s": round(outcome.latency_s, 3),
                    "usage": outcome.usage,
                    "attempt_codes": [list(c) for c in outcome.attempt_codes],
                    "codes": list(outcome.codes),
                    "ambiguous_spans": outcome.ambiguous_spans,
                },
                "source": {
                    "id": stored.id,
                    "policy_id": policy_id,
                    "source_ref": stored.source_ref,
                    "attribution": stored.attribution,
                    "fetched_at": iso(stored.fetched_at),
                    "text_file": ledger[source_id].text_file,
                    "codepoints": len(stored.text),
                    "sha256_nfc": sha256(stored.text),
                    "nfc_is_identity": stored.text == unicodedata.normalize("NFC", stored.text),
                },
            })
            print(f"  {policy_id:<24} {draft.status:<18} 시도{outcome.attempts} "
                  f"span{len(records[-1]['spans']):>3} {outcome.latency_s:>6.2f}s "
                  f"model={outcome.model}")

        return {
            "run": {
                "started_at": iso(started),
                "finished_at": iso(datetime.now(KST)),
                "provider": provider,
                "model_requested": requested,
                "max_attempts": constants[MAX_ATTEMPTS_KEY],
                "rule_draft_schema_sha256": sha256(
                    json.dumps(schema, ensure_ascii=False, sort_keys=True)),
                "rule_draft_schema_title": schema["title"],
                "pending": sum(1 for r in records if r["draft"]["status"] == "pending"),
                "failed": sum(
                    1 for r in records if r["draft"]["status"] == "extraction_failed"),
            },
            "records": records,
        }


# --------------------------------------------------------------------------
# 굳히기 — 기록을 픽스처로
# --------------------------------------------------------------------------

def build_fixture(runs: list[dict]) -> dict:
    """**첫 회차를 굳힌다.** 나머지 회차는 요약만 실어 반복 관측을 드러낸다."""
    frozen = runs[0]
    run = frozen["run"]

    sources: list[dict] = []
    drafts: list[dict] = []
    for record in frozen["records"]:
        source, draft, extraction = record["source"], record["draft"], record["extraction"]

        if not any(s["id"] == source["id"] for s in sources):
            sources.append({
                "id": source["id"],
                "policyId": source["policy_id"],
                # 텍스트를 복사하지 않는다 — 정본은 아래 파일 하나뿐이다.
                "textFile": f"data/policy_sources/{source['text_file']}",
                "sourceRef": source["source_ref"],
                "attribution": source["attribution"],
                "fetchedAt": source["fetched_at"],
                "codepoints": source["codepoints"],
                "sha256Nfc": source["sha256_nfc"],
            })

        drafts.append({
            "id": draft["id"],
            "policySourceId": draft["policy_source_id"],
            "policyId": draft["policy_id"],
            "status": draft["status"],
            "payload": draft["payload"],
            "createdAt": draft["created_at"],
            "failureReason": draft["failure_reason"],
            "spans": [
                {
                    "id": s["id"],
                    "fieldPath": s["field_path"],
                    "start": s["start"],
                    "end": s["end"],
                    "quote": s["quote"],
                }
                for s in record["spans"]
            ],
            "extraction": {
                "model": extraction["model_reported"],
                "startedAt": extraction["started_at"],
                "finishedAt": extraction["finished_at"],
                "attempts": extraction["attempts"],
                "latencySeconds": extraction["latency_s"],
                "usage": extraction["usage"],
                "attemptCodes": extraction["attempt_codes"],
                "codes": extraction["codes"],
                "ambiguousSpans": extraction["ambiguous_spans"],
            },
            # SPEC 2.1. `RuleDraft` 엔티티에는 이 칸이 없으므로(SPEC 2.2) 파일이 든다.
            # 값은 main.py 의 승인 경로가 같은 원문에서 만드는 것과 **같은 모양**이다 —
            # 승인 전후로 계보가 달라지면 승인이 계보를 바꾼 것이 된다.
            "provenance": {
                "source_kind": "statute",
                "source_name": source["attribution"],
                "source_ref": source["source_ref"],
                # 제도 문서가 공표 기준시점을 밝히지 않는다. 없는 것을 지어내지 않는다.
                "observed_at": None,
                "fetched_at": source["fetched_at"],
                "verification": "unverified",
            },
        })

    return {
        "_disclaimer": (
            "시연 대기 큐의 추출 초안을 **실제 LLM 호출 결과 그대로** 굳힌 것이다 "
            "(계약 결정 #42, #40 의 연장). 손으로 고친 값은 한 건도 없다 — 통과한 초안도 "
            "실패한 초안도 그 배치가 낸 그대로다. SPEC 9.2.1 표 마지막 줄이 키 없이 도는 "
            "후반부의 입력으로 이름 붙인 「draft 픽스처」가 이것이다."
        ),
        "_lineage": (
            "**어떤 모델로 · 언제 · 어떤 원문에서** 추출했는지가 이 파일의 존재 이유다. "
            "직전 시연이 쓰던 rehearsal-baseline.db 는 유실된 세션이 만든 파일이라 그 셋을 "
            "아무도 몰랐다 (REHEARSAL.md Part 5-⑤). 계보가 이 제품의 논지인데 시연의 중심 "
            "산출물이 계보 불명이었다."
        ),
        "_timestamps": (
            "createdAt · extraction.startedAt · fetchedAt 은 전부 **실제 시각**이다. "
            "시연일과 벌어지는 것이 정상이고 계보가 그것을 드러내는 것이 설계다 (결정 #40)."
        ),
        "_text": (
            "원문 텍스트를 여기 복사하지 않는다. 정본은 data/policy_sources/*.txt 하나뿐이고 "
            "(ingest/sources.py) 여기는 sha256Nfc 로 **그 파일이 그 파일인지**만 붙든다. "
            "복사본을 두면 span 오프셋이 어느 텍스트 기준인지가 둘로 갈린다."
        ),
        "_regeneration": (
            "다시 굳히려면 네트워크와 OPENAI_API_KEY 가 있는 상태에서 "
            "python backend/tests/store/refreeze_rule_drafts.py 를 돌린다. "
            "그 스크립트는 ingest 의 적재·추출 경로를 **그대로** 부르고 결과를 이 파일로 쓴다."
        ),
        "extractionRun": {
            "provider": run["provider"],
            "modelRequested": run["model_requested"],
            "modelReported": frozen["records"][0]["extraction"]["model_reported"],
            "startedAt": run["started_at"],
            "finishedAt": run["finished_at"],
            "maxAttempts": run["max_attempts"],
            "ruleDraftSchemaSha256": run["rule_draft_schema_sha256"],
            "pending": run["pending"],
            "extractionFailed": run["failed"],
            "_repeatedRuns": (
                "배치를 여러 번 돌려 실패가 주사위인지 계통적인지 쟀다. **굳힌 것은 첫 회차**이며 "
                "「원하는 결과가 나온 회차」를 고르지 않았다. 아래 byPolicy 가 회차별 결과다."
            ),
            "repeatedRuns": [
                {
                    "startedAt": other["run"]["started_at"],
                    "pending": other["run"]["pending"],
                    "extractionFailed": other["run"]["failed"],
                    "frozen": index == 0,
                    "byPolicy": {
                        r["draft"]["policy_id"]: r["draft"]["status"]
                        for r in other["records"]
                    },
                }
                for index, other in enumerate(runs)
            ],
        },
        "policySources": sources,
        "drafts": drafts,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # 콘솔 코덱(cp949)에 한글을 맡기지 않는다
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description="시연 대기 큐 초안을 다시 굳힌다 (결정 #42)")
    parser.add_argument("--runs", type=int, default=3,
                        help="배치 반복 횟수. 첫 회차를 굳히고 나머지는 요약만 싣는다")
    parser.add_argument("--from", dest="records", nargs="+", type=Path,
                        help="LLM 을 부르지 않고 저장된 회차 기록에서 재조립한다")
    parser.add_argument("--record-dir", type=Path,
                        help="회차 기록을 남길 디렉터리. 없으면 남기지 않는다")
    parser.add_argument("--out", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)

    if args.records:
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in args.records]
    else:
        if args.runs < 1:
            parser.error("--runs 는 1 이상이어야 한다")
        runs = []
        for index in range(1, args.runs + 1):
            print(f"[{index}/{args.runs}] 배치 실행")
            db = (args.record_dir or args.out.parent) / f".refreeze-{index}.db"
            db.parent.mkdir(parents=True, exist_ok=True)
            record = run_batch(db)
            db.unlink(missing_ok=True)
            runs.append(record)
            if args.record_dir:
                args.record_dir.mkdir(parents=True, exist_ok=True)
                (args.record_dir / f"run-{index}.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    fixture = build_fixture(runs)
    args.out.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = fixture["extractionRun"]
    print(f"\n굳혔다: {args.out}")
    print(f"  모델 {run['modelReported']} · {run['startedAt']}")
    print(f"  원문 {len(fixture['policySources'])}건 · 초안 {len(fixture['drafts'])}건 "
          f"(대기 {run['pending']} · 실패 {run['extractionFailed']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
