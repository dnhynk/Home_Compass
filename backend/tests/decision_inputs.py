"""판정 입력(지역·정책)을 테스트에 공급한다 — 컷오버 후의 경로는 저장소 하나다.

컷오버 전에는 `engines.load_regions()` · `engines.load_policies()` 가 이 자리를 맡았다.
그 둘은 `backend/src/home_compass/data/*.json` 을 `lru_cache(maxsize=1)` 로 읽었고,
SPEC 2.3 이 정면으로 금지하는 프로세스 수명 캐시였다. 지금 엔진에는 그 경로가 없다.

테스트가 **저장소에서** 읽는 이유는 편의가 아니다. api 가 요청마다 저장소에서 읽어
주입하므로, 파일에서 읽어 넣는 테스트는 실기동과 다른 물건을 검증하게 된다
(`test_engine_constants.test_boot_loader_and_test_seed_agree` 가 상수에 대해 지키는 것과
같은 규율이다).

저장소는 `conftest.py` 가 세션 시작에 임시 경로로 시드해 둔 것이다. **읽기 전용으로만
쓴다** — 여기서 꺼낸 값을 바꾸는 테스트는 자기 `tmp_path` 에 별도 저장소를 만든다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from home_compass.store import store_from_env

#: 테스트의 요청 시각. 실기동에서 `main.request_now()` 가 서는 자리이며, 테스트는 그것을
#: 고정값으로 대신한다 (SPEC 5.3 — 결정성 테스트는 클럭을 고정한다).
#:
#: **2026-01-01 이라는 날짜 자체에는 아무 의미가 없다.** 요점은 「고정되어 있다」이지
#: 「이 날이다」가 아니므로, 이 값에서 의미를 찾지 마라. 다른 날짜로 바꿔도 골든의
#: `meta.generatedAt` 문자열만 그만큼 바뀌고 판정 숫자는 하나도 움직이지 않는다.
#:
#: 다만 **아무 값이나 되는 것은 아니다.** 계약 결정 #6 이 적어 둔 대로, 고정 클럭이 규칙의
#: 시행일보다 과거이면 전 규칙이 비활성이 되어 판정이 통째로 바뀐다. 시드 규칙은
#: `effective_from` 이 NULL(시행 시점 미상)이라 지금은 어떤 값으로도 전부 활성이지만,
#: 유효기간이 있는 규칙이 들어오면 그 제약이 실제로 걸린다. 그래서 과거로 멀리 잡지 않는다.
FROZEN_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def store_regions() -> list[dict]:
    """세션 저장소의 지역을 엔진이 받는 dict 로 꺼낸다."""
    with store_from_env() as store:
        return [region.to_engine_dict() for region in store.regions.list()]


def store_policies(at: datetime) -> list[dict]:
    """SPEC 2.3 활성 규칙만 꺼낸다. `RuleDraft` 는 여기 실리지 않는다.

    시드 정책은 `effective_from` · `effective_to` 가 둘 다 NULL(시행 시점 미상 · 무기한)
    이므로 어떤 시각으로 물어도 전부 활성이다 (계약 결정 #5 · #6).

    **`at` 에 기본값을 두지 않는다.** 기본값은 `datetime.now()` 일 수밖에 없고, 그러면
    인자를 빠뜨린 호출이 조용히 벽시계를 읽는다 — 판정은 `FROZEN_NOW` 로 고정해 놓고
    활성 규칙만 돌리는 날에 따라 달라지는 상태가 된다. 지금은 시드 규칙이 전부 무기한이라
    결과가 같지만 유효기간 있는 규칙이 들어오는 순간 그 테스트들은 날짜에 따라 깨지고,
    그때 원인을 찾는 비용이 훨씬 크다. 계약 결정 #24(`analyze(now=...)` 에 기본값 금지)와
    같은 부류이며, `test_clock_injection.py` (e) 절이 파수병으로 지킨다.
    """
    with store_from_env() as store:
        return [version.payload for version in store.rule_versions.active(at)]
