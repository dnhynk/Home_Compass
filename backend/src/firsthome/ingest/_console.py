"""옛 자리의 껍데기 — 구현은 `firsthome._console` 로 올라갔다 (2026-08-16).

`store` 가 `ingest` 를 import 할 수 없어서(아키텍처 규칙) 구현을 패키지 뿌리로 옮겼다.
경위는 그쪽 docstring 에 있다.

**여기를 지우지 않은 이유** — 이 패키지의 진입점 셋이 PR #118 에서 막 `._console` 로
고쳐졌다. 같은 PR 에서 import 경로까지 흔들면 **방금 닫은 결함이 무엇 때문에 통과하는지**가
흐려진다. 다음에 이 패키지를 만질 때 호출부를 `firsthome._console` 로 옮기고 이 파일을 지운다.

★ **여기에 구현을 다시 넣지 마라.** 두 벌이 되는 순간 한쪽만 고쳐지고, 그것이 이
가드가 처음 생긴 이유다 (`extract_cli` 만 갖고 `__main__` 둘이 빠져 있었다).
"""

from __future__ import annotations

from .._console import force_utf8_stdout

__all__ = ["force_utf8_stdout"]
