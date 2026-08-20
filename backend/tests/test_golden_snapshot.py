"""골든 스냅샷 — 1-① 이 판정 숫자를 바꾸지 않았음의 증거 (SPEC 10.2 1-① · 5.3).

`golden/decision_numeric.json` 은 **구조 변경 이전 코드**로 생성해 커밋한 파일이다.
리팩터 뒤에 다시 생성해 바이트 비교하므로, 상수 하나라도 경로가 어긋나 값이 움직이면
여기서 걸린다.

`golden/rationale.json` 은 **별도 스냅샷**이다 (SPEC 5.3). rationale 문자열은 계약이
아니고 상수값을 문장에 직접 박고 있어 1-② 가 끝나면 전부 바뀐다. 숫자와 섞어 두면
상수 하나를 바꿀 때마다 회귀 테스트가 통째로 흔들려 아무것도 잡지 못한다.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from firsthome.engines import analyze  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed  # noqa: E402
from snapshot_util import (  # noqa: E402
    NUMERIC_PATH,
    TEXT_KEYS,
    TEXT_PATH,
    build_snapshots,
    dumps,
)

# SPEC 2.3 컷오버 — 지역·정책의 출처가 파일에서 **저장소**로 바뀌었다. 그래서 이 파일이
# 무엇을 증명하는지가 한 칸 강해졌다: 스냅샷이 그대로라는 것은 이제 「엔진이 같다」가
# 아니라 **「저장소를 거친 판정이 파일을 읽던 시절과 바이트 동일하다」** 이다.
# 파일에서 읽어 넣으면 그 증명이 사라지고 실기동과 다른 물건을 재는 테스트가 된다.


def _regenerate():
    constants = frozen_seed()
    regions = store_regions()
    policies = store_policies(FROZEN_NOW)
    return build_snapshots(
        lambda profile: analyze(
            profile,
            constants=constants,
            regions=regions,
            policies=policies,
            now=FROZEN_NOW,
        )
    )


def test_decision_numbers_and_states_are_unchanged():
    """1-① 완료 기준 중 가장 중요한 것 — 구조만 바뀌고 값은 그대로다."""
    numeric, _ = _regenerate()
    assert dumps(numeric) == NUMERIC_PATH.read_text(encoding="utf-8")


def test_rationale_snapshot_is_tracked_separately():
    _, text = _regenerate()
    assert dumps(text) == TEXT_PATH.read_text(encoding="utf-8")


def test_the_two_snapshots_do_not_overlap():
    """분리가 실제로 되어 있는지 — 숫자 스냅샷에 설명 문장이 새어 들어가면 의미가 없다."""
    numeric, text = _regenerate()

    def walk(node, sink):
        if isinstance(node, dict):
            for key, value in node.items():
                sink(key)
                walk(value, sink)
        elif isinstance(node, list):
            for item in node:
                walk(item, sink)

    leaked = []
    walk(numeric, lambda key: leaked.append(key) if key in TEXT_KEYS else None)
    assert not leaked, f"숫자 스냅샷에 설명 필드가 남아 있다: {sorted(set(leaked))}"

    kept = []
    walk(text, lambda key: kept.append(key) if key in TEXT_KEYS else None)
    assert kept, "rationale 스냅샷이 비어 있다 — 분리가 아니라 삭제가 되었다."


def test_regenerating_the_golden_twice_gives_the_same_bytes():
    """재생성 자체가 결정적인가 — 이 파일이 만드는 **산출물**에 거는 검사다.

    예전에는 여기에 프로필 한 건짜리 결정성 테스트가 있었고, 클럭이 주입식이 아니라
    `meta.generatedAt` 을 빼고 비교했다. 클럭 주입 후 그 자리는 `test_clock_injection.py`
    가 **응답 전체 바이트 비교**로 가져갔다 (SPEC 5.3 · 9.2 #5). 같은 단언을 두 벌 두는
    대신, 여기서는 그쪽이 덮지 않는 것 — 프로필 세트 전체를 도는 재생성 경로가 두 번
    돌려도 같은 바이트를 내는가 — 를 본다. 이게 흔들리면 커밋된 골든은 「그때 한 번
    그렇게 나온 것」일 뿐이다.
    """
    first_numeric, first_text = _regenerate()
    second_numeric, second_text = _regenerate()
    assert dumps(first_numeric) == dumps(second_numeric)
    assert dumps(first_text) == dumps(second_text)
