"""테스트용 상수 매핑 — contracts/model_constants.json 의 frozen_current_value.

`store` 는 아직 머지되지 않았고, `engines` 는 `store` 를 import 하지 않는다 (SPEC 1.2).
그래서 테스트는 값의 정본이 아니라 **계약이 고정한 시드값**으로 매핑을 만든다.
frozen_current_value 는 3bce651 시점의 코드 리터럴이며, 1-① 이 "판정 숫자를 바꾸지 않는
구조 변경" 임을 기계적으로 증명하기 위한 시드다 (레지스트리 description).

값의 정본은 store 의 ModelConstant 다. Wave 2 가 배선을 그쪽으로 갈아끼운다.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "contracts" / "model_constants.json"


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def frozen_seed() -> dict:
    """레지스트리 entries 를 그대로 상수 매핑으로 편다.

    JSON 은 객체 키를 문자열로만 담을 수 있으므로 `krw_by_household` 만 int 키로
    되돌린다 (valueTypeVocabulary: "가구원수(int) -> 원(int) 매핑"). 이 변환은
    `main.py` 의 부트스트랩 로더와 같아야 하며, 같은지를 테스트가 고정한다.
    """
    mapping: dict = {}
    for entry in load_registry()["entries"]:
        value = entry["frozen_current_value"]
        if entry["value_type"] == "krw_by_household":
            value = {int(k): int(v) for k, v in value.items()}
        elif entry["value_type"] == "policy_id_order":
            value = tuple(value)
        mapping[entry["key"]] = value
    return mapping
