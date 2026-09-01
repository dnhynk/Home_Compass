"""골든 스냅샷 분리 규칙 (SPEC 5.3).

`rationale` 문자열은 계약이 아니다. 상수값을 문장에 직접 박고 있어("주거비 상한을 30%로
설정했습니다") 1-② 가 끝나면 전부 바뀐다. 숫자·상태 필드와 섞어 두면 상수 하나를 바꿀
때마다 회귀 테스트가 통째로 흔들려 아무것도 잡지 못한다.

그래서 `analyze()` 의 결과를 두 갈래로 쪼갠다.

  numeric  판정 숫자와 상태 필드. **1-① 전후로 바이트 동일해야 한다.**
  text     설명 문장. 1-② 에서 의도적으로 갱신되는 쪽.

두 스냅샷은 같은 트리 모양을 유지한다 — 리스트 인덱스가 어긋나면 어느 시나리오의 문장인지
알 수 없게 되기 때문이다.
"""

from __future__ import annotations

import json
from pathlib import Path

# 설명 문장을 담는 키. 이 키에 걸린 값은 통째로 text 쪽으로 간다.
TEXT_KEYS = frozenset({"rationale", "reasons", "summary", "note", "disclaimer",
                       # `failures` 는 `reasons` 의 부분집합이고 같은 산문이다.
                       # 여기 없으면 상수를 박은 문장(「연소득 3,000만원 이하 요건
                       # 미충족」)이 **숫자 골든**으로 들어가, 상수 하나를 바꿀 때마다
                       # 엄격한 대조가 통째로 흔들린다 — SPEC 5.3 이 금지한 그것이다.
                       "failures"})

# 제외 목록은 **없다.** 예전에는 `VOLATILE_KEYS = {"generatedAt"}` 가 여기 있었다 —
# 엔진이 `datetime.now()` 를 직접 읽어 그 필드를 고정할 수 없었기 때문이다. SPEC 5.3 이
# "필드를 빼고 비교하지 않는다 — 제외 목록은 자라기 때문이다" 라고 금지한 바로 그것이었다.
# 클럭을 주입받게 되면서 `generatedAt` 도 결정적이 되었으므로 뺄 이유가 사라졌다.
# **비워서 남기지도 않는다** — 빈 목록이 있으면 다음 사람이 거기에 하나를 더한다.
# `test_clock_injection.py` 가 이 이름이 되살아나지 않는지 지킨다.

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# 프로필 세트는 **계약이다** (SPEC 9.2.2 — `contracts/` 에 고정 파일로 두고 버전을 매긴다).
# 골든 안에 두면 세트를 바꾸는 것이 계약 변경으로 취급되지 않고, 소유 경로 게이트에도
# 걸리지 않는다. 세트가 바뀌면 골든이 통째로 바뀌므로 그 경로는 코디네이터만 열어야 한다.
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
PROFILES_PATH = CONTRACTS_DIR / "regression_profiles.json"
NUMERIC_PATH = GOLDEN_DIR / "decision_numeric.json"
TEXT_PATH = GOLDEN_DIR / "rationale.json"


def split_snapshot(node):
    """(numeric, text) 두 갈래로 쪼갠다. 리스트 인덱스는 양쪽에서 보존된다."""
    if isinstance(node, dict):
        numeric, text = {}, {}
        for key, value in node.items():
            if key in TEXT_KEYS:
                text[key] = value
                continue
            sub_numeric, sub_text = split_snapshot(value)
            numeric[key] = sub_numeric
            text[key] = sub_text
        return numeric, text
    if isinstance(node, list):
        pairs = [split_snapshot(item) for item in node]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    return node, None


def load_profiles() -> list[dict]:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    return data["profiles"]


def build_snapshots(run) -> tuple[dict, dict]:
    """`run(profile) -> dict` 을 프로필 세트 전체에 돌려 두 스냅샷을 만든다.

    ValueError 는 판정 거부라는 **상태**이므로 numeric 쪽에 기록한다. 없는 지역 축
    (SPEC 9.2.2)이 조용히 스냅샷에서 빠지면 그 축을 검증하지 않은 것과 같다.
    """
    numeric, text = {}, {}
    for case in load_profiles():
        try:
            result = run(case["profile"])
        except ValueError as exc:
            numeric[case["id"]] = {"raised": "ValueError"}
            text[case["id"]] = {"message": str(exc)}
            continue
        numeric[case["id"]], text[case["id"]] = split_snapshot(result)
    return numeric, text


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
