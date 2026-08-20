"""수집한 원문을 `PolicySource` 로 적재한다 (SPEC 4.1 #1).

`store` 의 **공개 API 만** 쓴다. NFC 정규화는 저장소가 저장 시 한 번 하며(계약 결정 #7)
여기서 미리 정규화하지 않는다 — 두 곳에서 정규화하면 어느 쪽이 span 오프셋의 기준인지가
흐려진다.

여기서 하지 않는 것 (다음 과업이다): LLM 추출 · `RuleDraft` 생성 · `RuleSpanMapping` 생성.
"""

from __future__ import annotations

from datetime import datetime

from ..store.interfaces import Store
from ..store.models import AuditEvent, PolicySource
from .sources import (
    COLLECTION_RUN_AT,
    INGEST_ACTION,
    INGEST_ACTOR,
    CollectedSource,
    loadable_sources,
)


def load_policy_sources(
    store: Store,
    *,
    run_at: datetime,
    only: tuple[CollectedSource, ...] | None = None,
) -> list[PolicySource]:
    """이용조건이 확인된 원문만 적재하고, 저장소가 돌려준 정규화된 객체를 반환한다.

    `run_at` 은 **배치를 돌린 시각**(감사기록용)이고, `PolicySource.fetched_at` 은
    **원문을 취득한 시각**이다. 둘을 같은 값으로 뭉개면 다시 적재할 때마다 자료가
    신선해 보인다.
    """
    targets = loadable_sources() if only is None else only
    stored: list[PolicySource] = []

    # 감사기록은 append-only 라 갱신이 없다 (SPEC 7.1). 배치를 두 번 돌리면 기록도 두 건
    # 남는 것이 사실이므로, id 를 고정하지 않고 기존 기록 수에서 이어붙인다.
    # `run_at` 을 id 에 넣는 방식은 같은 시각으로 재실행할 때 그대로 충돌한다.
    seq = len(store.audit.list())

    for index, source in enumerate(targets):
        if not source.loadable:  # 방어. 호출자가 `only` 로 게이트를 우회하지 못하게 한다.
            raise ValueError(f"이용조건이 확인되지 않은 원문이다: {source.policy_id}")

        # ★ 계약 결정 #15 — **출처표시 없이는 적재하지 않는다.**
        #   조용히 `None` 으로 넣으면 저장소에는 들어가고 의무만 사라진다. 그것이
        #   「계보가 끊기면 의무가 문서에만 남는다」의 실제 모습이다.
        #   ★ 걸러내지 않고 **예외로 낸다.** 걸러내면 「이용조건 때문에 안 넣었다」와
        #     「출처표시가 없어서 안 넣었다」가 적재 건수 하나로 뭉개진다.
        attribution = source.attribution
        if attribution is None:
            raise ValueError(
                f"출처표시가 없는 원문은 적재하지 않는다: {source.policy_id} "
                "(기관 · 저작물명 · 공고번호(또는 문서종류) · 이용근거 중 빠진 것이 있다)"
            )

        saved = store.policy_sources.add(
            PolicySource(
                id=source.source_id,
                text=source.read_text(),
                # 참조는 URL 그대로다. 출처표시 문구는 옆 칸(`attribution`)이 든다 —
                # 한 필드로 합치면 화면이 URL 만 뽑아내지 못한다.
                source_ref=source.url,
                fetched_at=COLLECTION_RUN_AT,
                attribution=attribution,
            )
        )
        store.audit.append(
            AuditEvent(
                id=f"audit-{seq + index + 1:06d}-{INGEST_ACTION}-{source.policy_id}",
                actor=INGEST_ACTOR,
                at=run_at,
                action=INGEST_ACTION,
                target=saved.id,
                outcome="stored",
                after={
                    "policy_id": source.policy_id,
                    "source_ref": saved.source_ref,
                    "codepoints": len(saved.text),
                    "doc_kind": source.doc_kind,
                    "licence": source.licence,
                    # 무엇을 출처로 적고 넣었는지가 감사기록에도 남는다. 나중에 출처표시가
                    # 바뀌면 **언제 무엇에서 무엇으로** 바뀌었는지가 여기서 읽힌다.
                    "attribution": saved.attribution,
                },
            )
        )
        stored.append(saved)

    return stored
