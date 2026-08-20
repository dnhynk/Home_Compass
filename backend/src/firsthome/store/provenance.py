"""`contracts/provenance.schema.json` 을 저장 시점에 건다.

**스키마를 캐시하지 않는다.** 매 검증마다 계약 파일을 다시 읽는다. SPEC 2.3 의 캐시 금지는
데이터를 겨냥한 규칙이지만, 여기서도 같은 이유가 성립한다 — 계약을 고치고 재기동해야
반영되는 구조를 만들지 않는다. 쓰기는 드물고(시드 44행) 스키마는 작아서 비용이 문제되지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .errors import ProvenanceError

#: 부록 A — 설정은 환경변수로 주입한다. `.env` 는 편의 수단일 뿐 유일 경로가 아니다.
CONTRACTS_DIR_ENV = "FIRSTHOME_CONTRACTS_DIR"

_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts"


def contracts_dir() -> Path:
    override = os.environ.get(CONTRACTS_DIR_ENV)
    return Path(override) if override else _DEFAULT_CONTRACTS_DIR


def provenance_schema() -> dict[str, Any]:
    """계약 원본을 그대로 돌려준다. 저장소가 사본을 들고 있으면 계약이 갈라진다."""
    path = contracts_dir() / "provenance.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - 배치 오류 시에만
        raise ProvenanceError(f"계약 파일을 찾을 수 없다: {path}") from exc


def validate_provenance_dict(data: Mapping[str, Any]) -> None:
    """SPEC 2.1 을 위반한 계보면 `ProvenanceError` 로 터진다."""
    errors = sorted(Draft202012Validator(provenance_schema()).iter_errors(dict(data)), key=str)
    if errors:
        detail = " / ".join(e.message for e in errors)
        raise ProvenanceError(f"Provenance 가 계약을 위반한다: {detail}")
