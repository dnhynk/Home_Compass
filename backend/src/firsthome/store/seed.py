"""계약과 기존 시드 데이터를 저장소로 옮긴다.

두 출처가 있고 성격이 다르다.

  `contracts/model_constants.json`  계약이다. `seedRule` 절을 **그대로** 따른다.
                                    값도 계보도 여기 적힌 것을 옮겨 적을 뿐 판단하지 않는다.
  `firsthome/data/*.json`           SPEC 9.4 에 따라 0단계에 `store` 소유로 넘어온 시드다.
                                    파일은 제자리에 두고 소유권만 옮긴다 — `engines` 의
                                    읽기 경로 제거는 Wave 2 컷오버다.

**판정 숫자를 바꾸지 않는다.** 이관은 구조 변경이며, 값이 움직이면 1-① 완료 기준
(SPEC 10.2)과 정면으로 충돌한다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import StoreError
from .interfaces import Store
from .models import (
    REGION_FACT_FIELDS,
    AuditEvent,
    ModelConstant,
    PolicySource,
    Provenance,
    Region,
    RuleDraft,
    RuleSpanMapping,
    RuleVersion,
)
from .provenance import contracts_dir
from .validation import require_aware

#: SPEC 9.4 — 0단계에 `store` 로 이관된다. 이관 후 소유자는 `store` 다.
SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

#: 저장소 루트. 원문 텍스트의 정본이 여기 아래에 있다 (`ingest/sources.py` 와 같은 자리).
REPO_ROOT = Path(__file__).resolve().parents[4]

#: 계약 결정 #5 — 사람 승인이 아니라 시드였음이 감사로그에 드러나게 하는 행위자.
SEED_ACTOR = "system:seed"

#: 시연 대기 큐 시드가 감사로그에 남기는 행위. `system:extract` 의 `rule_draft.extract`
#: 와 **다른 이름**이다 — 이 초안들은 지금 이 기계가 뽑은 것이 아니라 굳힌 것을 옮긴 것이고,
#: 둘을 같은 이름으로 적으면 감사로그가 「방금 배치가 돌았다」고 말하게 된다.
DEMO_QUEUE_ACTION = "rule_draft.seed"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_registry() -> dict[str, Any]:
    return _read(contracts_dir() / "model_constants.json")


def _coerce(value: Any, value_type: str) -> Any:
    """계약의 `valueTypeVocabulary` 를 파이썬 타입으로 되살린다.

    JSON 에는 int 키도 튜플도 없다. `frozen_current_value` 를 그대로 쓰면
    `LIVING_COST_BY_HOUSEHOLD[size]` 가 문자열 키를 만나 KeyError 로 터진다.
    """
    if value_type == "krw_by_household":
        return {int(k): v for k, v in value.items()}
    if value_type == "policy_id_order":
        return tuple(value)
    return value


def seed_model_constants(store: Store) -> int:
    """`entries` 를 그대로 등재한다.

    `seed_provenance` 를 손대지 않는다 — (d)는 `our_choice`, (a)(b)(c)는 `unverified` 다.
    `pending_diligence` 에 적힌 준거 후보는 **실사 승인 전까지 계보에 기재하지 않는다.**
    모집단·기준시점을 밝히지 않은 인용은 심사에서 즉시 반박당한다 (SPEC Part 0-C).
    """
    entries = load_registry()["entries"]
    for entry in entries:
        store.model_constants.put(
            ModelConstant(
                key=entry["key"],
                engine=entry["engine"],
                legacy_symbol=entry["legacy_symbol"],
                spec_class=entry["spec_class"],
                value_type=entry["value_type"],
                value=_coerce(entry["frozen_current_value"], entry["value_type"]),
                provenance=Provenance.from_dict(entry["seed_provenance"]),
            )
        )
    return len(entries)


def seed_regions(store: Store) -> int:
    """`regions.json` 을 `Region` 으로 옮긴다.

    ★ **파일이 바뀌었다 — 이제 실수집 결과를 굳힌 것이다** (계약 결정 #40, 8단계 집행).
    시연 경로는 네트워크를 쓰지 않으므로(D-8) 무대에서 배치를 돌려 값을 받을 수 없다.
    그래서 미리 받아 굳혔고, 시드는 **파일이 적어 둔 계보를 그대로 옮긴다.**

    여기서 계보를 만들어 내지 않는 것이 이 함수의 전부다. 8필드가 한 덩어리이던 시절에는
    이 자리에서 `unverified` 하나를 만들어 여덟에 뿌렸는데, 그때는 여덟이 전부 예시값이라
    그것이 사실이었다. 지금은 **필드별로 갈린다** — 실측 5필드는 `verified`, 실거래가에
    대응물이 없는 3필드는 `unverified` 다 (SPEC 3.1). 여기서 다시 뭉치면 그 구분이 사라진다.

    요약은 파일에 있는 것을 그대로 쓴다. 최악값 규칙(SPEC 2.4)은 저장소가 upsert 에서
    강제하므로, 요약이 필드보다 좋게 적힌 파일은 여기서 거부된다.

    `fetched_at` 은 **실제 수집 시각**이고 시연일과 벌어진다. 그것을 숨기지 않는 것이
    결정 #40 이 명시한 조건이다.
    """
    regions = _read(SEED_DATA_DIR / "regions.json")["regions"]
    for raw in regions:
        payload = raw["payload"]
        store.regions.upsert(
            Region(
                code=payload["code"],
                name=payload["name"],
                jeonse_median_krw=payload["jeonseMedianKRW"],
                monthly_deposit_krw=payload["monthlyDepositKRW"],
                monthly_rent_krw=payload["monthlyRentKRW"],
                maintenance_fee_krw=payload["maintenanceFeeKRW"],
                jeonse_ratio_pct=payload["jeonseRatioPct"],
                conversion_rate_pct=payload["conversionRatePct"],
                market_risk=payload["marketRisk"],
                guarantee_available=payload["guaranteeAvailable"],
                provenance=Provenance.from_dict(raw["provenance"]),
                field_provenance={
                    name: Provenance.from_dict(raw["fieldProvenance"][name])
                    for name in REGION_FACT_FIELDS
                },
            )
        )
    return len(regions)


def seed_policies(store: Store, at: datetime | None = None) -> int:
    """`policies.json` 을 `RuleVersion` 으로 옮긴다 (계약 결정 #5 · #6).

    SPEC 2.2 에 `Policy` 엔티티가 없으므로 정책이 들어갈 곳은 '승인된 규칙'인
    `RuleVersion` 뿐이다. 그러나 이 데이터는 **사람이 승인한 적이 없다.**

      - `origin='seed'` · `approved_by=NULL` · `ApprovalRecord` 없음
      - `effective_from`/`effective_to` 는 **NULL** — 시행 시점을 모른다.
        시드 실행 시각을 적으면 'DB 를 만든 시각' 을 '제도가 시행된 시각' 인 척하게 되고,
        고정 클럭을 과거로 잡는 순간 전 규칙이 비활성이 되어 판정이 통째로 바뀐다.
      - 대신 `actor='system:seed'` 인 `AuditEvent` 를 남겨 감사로그에 드러낸다.

    `status` 는 `approved` 다 — 그래야 SPEC 2.3 술어에 걸려 기존 판정이 유지된다.
    """
    stamp = require_aware(at or datetime.now(timezone.utc), "at")
    policies = _read(SEED_DATA_DIR / "policies.json")["policies"]

    for raw in policies:
        version_id = f"seed:{raw['id']}"
        if store.rule_versions.get(version_id) is not None:
            continue  # 재시드는 아무것도 바꾸지 않는다. RuleVersion 은 불변이다.

        store.rule_versions.add(
            RuleVersion(
                id=version_id,
                policy_id=raw["id"],
                payload=raw,
                status="approved",
                origin="seed",
                effective_from=None,
                effective_to=None,
                supersedes=None,
                approved_by=None,
                provenance=Provenance(
                    source_kind="statute",
                    source_name=raw.get("source"),
                    source_ref=None,
                    observed_at=None,
                    fetched_at=None,
                    verification="unverified",
                ),
                created_at=stamp,
            )
        )
        store.audit.append(
            AuditEvent(
                id=f"seed:rule_version:{raw['id']}",
                actor=SEED_ACTOR,
                at=stamp,
                action="rule_version.seed",
                target=raw["id"],
                outcome="success",
                before=None,
                after={"ruleVersionId": version_id, "origin": "seed"},
            )
        )
    return len(policies)


def load_demo_queue() -> dict[str, Any]:
    """굳힌 대기 큐 픽스처. 파일이 없으면 여기서 터진다 — 조용히 빈 큐를 만들지 않는다."""
    return _read(SEED_DATA_DIR / "rule_drafts.json")


def _aware(stamp: str, field: str) -> datetime:
    """픽스처가 적어 둔 RFC 3339 시각. 오프셋이 없으면 여기서 거부된다 (SPEC 2.1).

    굳힌 시각은 **실제로 일어난 사건의 시각**이라 오프셋이 있어야 뜻이 선다 — 없으면
    로컬시각으로 조용히 해석되어 「언제 추출됐나」의 답이 읽는 기계마다 달라진다.
    """
    return require_aware(datetime.fromisoformat(stamp), field)


def seed_policy_sources(store: Store) -> int:
    """굳힌 원문을 `PolicySource` 로 옮긴다 (계약 결정 #42).

    ★ **텍스트를 픽스처에 복사해 두지 않았다.** 정본은 `data/policy_sources/*.txt` 하나뿐이고
      (`ingest/sources.py` 가 그렇게 못박았다) 픽스처는 `sha256Nfc` 로 **그 파일이 그
      파일인지**만 붙든다. 복사본을 두면 span 오프셋이 어느 텍스트 기준인지가 둘로 갈리고,
      갈린 뒤에는 어느 쪽이 근거인지 아무도 모른다.

    ★ **적재 경로(`ingest.loader`)를 부르지 않는다.** SPEC 1.2 가 `store -> ingest` 를
      금지하기 때문이며 아키텍처 테스트가 그것을 잡는다. 그래서 여기는 적재를 다시 구현하는
      것이 아니라 **적재가 낸 결과를 옮겨 적는다** — 이용조건·출처표시 게이트(계약 결정 #15)를
      통과한 것은 굳힐 때의 그 배치이고, 이 함수가 그것을 흉내 내지 않는다는 사실을
      `tests/store/test_demo_queue_matches_ingest.py` 가 두 경로를 실제로 돌려 대조한다.

    해시가 어긋나면 **터진다.** 원문이 바뀌었는데 초안이 그대로면 span 이 가리키는 자리가
    조용히 다른 글자가 되고, 그것은 근거 대조 화면(SPEC 4.4 #1)이 거짓을 보이는 상태다.
    """
    entries = load_demo_queue()["policySources"]
    for entry in entries:
        path = REPO_ROOT / entry["textFile"]
        stored = store.policy_sources.add(
            PolicySource(
                id=entry["id"],
                text=path.read_text(encoding="utf-8"),
                source_ref=entry["sourceRef"],
                fetched_at=_aware(entry["fetchedAt"], "fetchedAt"),
                attribution=entry["attribution"],
            )
        )
        # 저장소가 NFC 정규화한 **뒤**의 텍스트로 잰다 (계약 결정 #7). span 오프셋의 기준이
        # 그 텍스트이므로, 파일 바이트로 재면 정규화가 바꾼 자리를 놓친다.
        digest = hashlib.sha256(stored.text.encode("utf-8")).hexdigest()
        if digest != entry["sha256Nfc"]:
            raise StoreError(
                f"원문이 굳힐 때와 다르다: {entry['id']} — {entry['textFile']} "
                f"(기대 {entry['sha256Nfc'][:12]}… / 실제 {digest[:12]}…). "
                "초안의 span 이 다른 글자를 가리키게 되므로 여기서 멈춘다. "
                "원문을 바꿨다면 초안도 다시 뽑아야 한다 (rule_drafts.json 의 _regeneration)."
            )
    return len(entries)


def seed_demo_queue(store: Store, at: datetime | None = None) -> dict[str, int]:
    """굳힌 추출 초안을 대기 큐에 세운다 (계약 결정 #42 — #40 의 연장).

    핵심 시연 장면(승인 → 시민 화면 변화)에는 **승인할 초안이 큐에 있어야** 하는데,
    `extract_cli --offline-only` 는 `extract_all()` 을 건너뛰어 초안을 0건 만들고 키 없이
    돌리면 SPEC 9.2.1 대로 정상 실패해 `extraction_failed` 만 남는다. 그리고 `.gitignore` 가
    `backend/var/` 를 제외하므로 그 저장소는 repo 에 없었다. SPEC 9.2.1 의 표가 키 없이 도는
    후반부의 입력으로 이름 붙인 **「draft 픽스처」가 이것**이다.

    **실패한 초안도 함께 세운다.** 통과한 것만 고르면 큐가 「추출은 늘 성공한다」고 말하게
    되는데, 그것은 이 저장소가 SPEC 4.2 에서 세운 주장(부분 저장 금지 · 실패를 숨기지 않는다)의
    반대다. `extraction_failed` 는 승인 대상이 아니며 사유와 함께 큐에 남는다.

    두 번 돌려도 결과가 같다 — 이미 있는 초안은 건너뛴다. `RuleDraft` 는 갱신 대상이 아니고
    (`add` 가 upsert 가 아니다), 재시드가 같은 초안을 다시 만들면 그것은 「다시 일어난 추출」인
    척하는 것이 된다.
    """
    stamp = require_aware(at or datetime.now(timezone.utc), "at")
    fixture = load_demo_queue()
    run = fixture["extractionRun"]

    sources = seed_policy_sources(store)
    added = 0
    for entry in fixture["drafts"]:
        if store.rule_drafts.get(entry["id"]) is not None:
            continue
        store.rule_drafts.add(
            RuleDraft(
                id=entry["id"],
                policy_source_id=entry["policySourceId"],
                policy_id=entry["policyId"],
                status=entry["status"],
                payload=entry["payload"],
                # ★ **실제 추출 시각이다.** 시드를 돌린 시각(`at`)이 아니다 — 그것을 적으면
                #   시연할 때마다 초안이 방금 뽑힌 것처럼 보이고, 계보가 거짓이 된다.
                created_at=_aware(entry["createdAt"], "createdAt"),
                failure_reason=entry["failureReason"],
            )
        )
        for span in entry["spans"]:
            store.rule_drafts.add_span(
                RuleSpanMapping(
                    id=span["id"],
                    draft_id=entry["id"],
                    field_path=span["fieldPath"],
                    start=span["start"],
                    end=span["end"],
                )
            )
        store.audit.append(
            AuditEvent(
                id=f"seed:rule_draft:{entry['id']}",
                actor=SEED_ACTOR,
                at=stamp,
                action=DEMO_QUEUE_ACTION,
                target=entry["id"],
                outcome=entry["status"],
                # ★ **계보가 저장소 안에서도 읽혀야 한다.** 파일에만 있으면 돌아가는
                #   시스템에게 물어볼 수 없고, 그것이 rehearsal-baseline.db 가 계보 불명이
                #   됐던 경위 그대로다. `RuleDraft` 에는 계보 칸이 없으므로(SPEC 2.2)
                #   남길 자리는 감사기록이다 — `seed_policies` 가 쓰는 것과 같은 자리다.
                after={
                    "policyId": entry["policyId"],
                    "policySourceId": entry["policySourceId"],
                    "spans": len(entry["spans"]),
                    "provenance": entry["provenance"],
                    "extraction": entry["extraction"],
                    "frozenRun": {
                        "provider": run["provider"],
                        "modelRequested": run["modelRequested"],
                        "startedAt": run["startedAt"],
                        "maxAttempts": run["maxAttempts"],
                        "ruleDraftSchemaSha256": run["ruleDraftSchemaSha256"],
                    },
                },
            )
        )
        added += 1
    return {"policy_sources": sources, "rule_drafts": added}


def seed_all(
    store: Store, at: datetime | None = None, *, demo_queue: bool = False
) -> dict[str, int]:
    """전부 시드한다. 두 번 돌려도 결과가 같다 — 시연 중 재실행은 반드시 일어난다.

    **계정은 만들지 않는다.** 시드 계정의 비밀번호는 저장소에 커밋하지 않고 기동 시
    환경변수로 주입한다 (SPEC 6.3). 그것은 인증 계층(4단계)의 일이다.

    `demo_queue` 는 **기본이 꺼짐**이다. 시연 대기 큐는 기동에 필요한 것이 아니라 시연에
    필요한 것이고, 켜 두면 `seed_all` 을 부르는 모든 시험이 초안 7건을 안고 시작한다 —
    빈 큐를 전제하는 단정(`queue.pending == 0` 등)이 무관한 이유로 깨진다. 켜는 것은
    **시연 저장소를 만드는 쪽의 선택**이다.
    """
    stamp = require_aware(at or datetime.now(timezone.utc), "at")
    counts = {
        "model_constants": seed_model_constants(store),
        "regions": seed_regions(store),
        "rule_versions": seed_policies(store, at=stamp),
    }
    if demo_queue:
        counts.update(seed_demo_queue(store, at=stamp))
    return counts
