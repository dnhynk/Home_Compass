# `store` — 저장소 계층

SQLite 기본, 교체 가능 (SPEC 1.1 · 부록 A). 소유자: `store` (SPEC 9.4).

## 쓰는 법

```python
from datetime import datetime, timezone
from firsthome.store import store_from_env

with store_from_env() as store:
    rules = store.rule_versions.active(datetime.now(timezone.utc))
```

`FIRSTHOME_STORE_URL` 이 백엔드를 정한다. 없으면 `backend/var/firsthome.db` 다.

```
FIRSTHOME_STORE_URL=sqlite://./backend/var/firsthome.db
FIRSTHOME_STORE_URL=sqlite://:memory:
```

실기동 확인:

```
python -m firsthome.store                      # 임시 DB 에 저장·조회·수정거부를 실행
python -m firsthome.store --db ./var/smoke.db
```

## 부록 A — 외부 DB 로 바꾸려면

`store/` 안의 어떤 파일도 고치지 않는다. 호출자도 고치지 않는다. 두 가지만 한다.

1. `Store` 와 8개 리포지터리 ABC(`interfaces.py`)를 구현한다
2. 기동 시 `register_backend("postgresql", MyStore.open)` 을 부르고
   `FIRSTHOME_STORE_URL=postgresql://...` 로 기동한다

이 주장이 실제로 성립하는지는 `backend/tests/store/` 가 매번 검증한다. 계약 테스트 전부가
**두 백엔드**(SQLite + `memory_backend.py` 의 딕셔너리 구현)에서 돌고, 하나라도 어긋나면
실패한다. 구현이 하나뿐이면 "교체 가능"은 검증되지 않은 주장이다.

`memory_backend.py` 는 테스트에만 있고 배포물에 들어가지 않는다.

## 이 계층이 지고 있는 보장

| 보장 | 근거 | 강제 방식 |
|---|---|---|
| `AuditEvent` append-only | SPEC 7.1 | (a) 인터페이스에 update·delete 가 **없다** (b) SQLite `BEFORE UPDATE`/`BEFORE DELETE` 트리거 `RAISE(ABORT)` |
| `RuleVersion` 불변 | SPEC 2.2 · 계약 #6 | `effective_to` 의 `NULL`→값 **1회 전이만** 허용. 값→값·값→`NULL`·다른 컬럼은 전부 ABORT |
| 판정에 나가는 것은 승인된 규칙뿐 | SPEC 2.3 | `rule_versions.active(at)` 하나가 유일한 판정 경로. `RuleDraft` 는 다른 테이블이며 여기 실리지 않는다 |
| 승인 위조 불가 | 계약 #5 | `origin='human_approval'` 이면 `approved_by` + 대응 `ApprovalRecord` 가 있어야 INSERT 된다 |
| 잘못된 계보 저장 불가 | SPEC 2.1 | 쓰기 시점에 `contracts/provenance.schema.json` 으로 검증 |
| **프로세스 수명 캐시 없음** | SPEC 2.3 | 캐시가 아예 없다. 승인·배치 반영이 재기동 없이 다음 조회에 보인다 |

마지막 항목이 핵심 시연 장면(승인 → 시민 화면 변화)을 떠받친다. 캐시를 넣으려면
**저장소 갱신에 연동된 무효화**가 함께 와야 한다. 없으면 넣지 않는다.

## 시각 표기

`Provenance` 의 `observed_at` · `fetched_at` 은 계약이 정한 문자열 그대로 저장된다
(숫자 오프셋 필수, `Z` 금지 — SPEC 2.1). 손대지 않는다.

엔티티의 `at` · `effective_from` · `effective_to` · `created_at` 은 **UTC 로 정규화한
RFC 3339** 로 적는다. 오프셋이 섞이면 문자열 비교가 시각 비교와 어긋나 활성 규칙 창이
조용히 틀린다. 반환값은 aware `datetime` 이므로 호출자에게는 같은 순간 그대로다.

## 목록의 순서 — `ORDER BY` 를 고르는 규칙

**목록의 순서는 백엔드의 성질이 아니라 `interfaces.py` 의 계약이다.** 두 백엔드가 같은
답을 내야 하므로 새 조회를 더할 때 순서를 먼저 정하고 그 자리에 적는다.

고르는 규칙은 하나다.

> **호출자가 [자리]를 [시각]에 대한 주장으로 읽으면 시각순으로 정렬한다.
> 그렇지 않으면 등재순(`rowid`)이다.**

「시각 열이 있으니 시각순으로」가 아니다. 등재순은 임의의 순서가 아니라 **그 자체로
사실**(적재 파일의 순서·큐에 들어온 순서)이고, 그것을 다른 열로 갈아 끼우는 것은 한
사실을 다른 사실로 바꾸는 변경이다.

지금 이 규칙이 시각순을 요구하는 조회는 **`AuditLog.list` 하나**다. `main.build_batch_status`
가 그 목록의 **마지막 원소**를 「마지막 배치 실행」이라 부르고, `/api/health` 는 그것을
`lastRunAt` · `lastOutcome` 두 칸으로만 싣는다 — **어긋나도 화면에 단서가 없다.**
나머지 조회는 목록을 훑거나 세기만 하고, 화면에 그리는 것들은 행마다 자기 시각을
(`createdAt` · `at`) 함께 싣는다.

`at` 오름차순의 보조 키는 **`rowid`** 다. 한 배치 실행은 지역별 행과 실행 행을 같은
`now` 로 쓰므로 동률이 예외가 아니라 정상 경로이고, 거기서 순서를 정해 두지 않으면
[실행 행이 지역별 행 뒤에 온다] 는 기록의 뜻이 실행마다 흔들린다.

> ★ **한 번 틀렸던 자리다.** 여기 있던 주석은 「append-only 이므로 삽입순과 시각순이
> 어긋날 수 없다」고 적었는데 그것이 거짓이다. append-only 가 막는 것은 [행을 고치는
> 것]이지 [지난 시각의 행을 나중에 붙이는 것]이 아니다.
> 갈리는 상황은 `backend/tests/store/test_audit_ordering.py` 가 만들어 보인다.

## 데이터 시드

| 출처 | 대상 | 규칙 |
|---|---|---|
| `contracts/model_constants.json` | `ModelConstant` | `seedRule` 을 그대로 따른다. (d)=`our_choice`, (a)(b)(c)=`unverified`. `pending_diligence` 의 준거 후보는 계보에 **적지 않는다** |
| `firsthome/data/regions.json` | `Region` | 전 필드 `unverified` (SPEC 3.1) |
| `firsthome/data/policies.json` | `RuleVersion` | `origin='seed'`, `approved_by=NULL`, `effective_from/to=NULL`, `actor='system:seed'` 감사기록 |

`data/*.json` 은 SPEC 9.4 에 따라 0단계에 `store` 소유로 넘어왔다. **파일은 제자리에 있다** —
`engines` 의 읽기 경로 제거는 Wave 2 컷오버이며 `api` 가 상수·데이터를 주입하는 시점에 일어난다.
그때까지 두 경로가 같은 파일을 본다.
