"""교차 테스트 — SPEC 1.2 의존 방향 (코디네이터 소유, SPEC 9.4).

SPEC 1.2 는 금지 규칙을 넷 적었고 "위반 시 테스트 실패"라고 못 박았다. 그중 첫 줄이
가장 무겁다:

    engines 는 llm 을 import 하지 않는다
      <- 원칙 1(판정 경로에 AI 없음)의 기계적 강제

원칙 1 은 이 제품의 서사 전체가 얹혀 있는 주장이다 — "LLM 장애나 API 키 부재가 핵심
판정 기능을 건드리지 못한다". 그 주장을 문서가 아니라 import 그래프로 증명한다.

SPEC 10.2 는 0단계 완료 기준으로 "아키텍처 테스트가 1.2 금지 규칙을 **실제로 잡는다**
(위반을 일부러 심어 실패 확인)"를 요구한다. 이 파일 자체가 그 검사이며, 심어서 확인한
기록은 PR 본문에 남긴다.

W-store 가 PR #7 본문에서 "store 에도 1.2 를 걸지 판단 바란다"고 요청했다. 건다 —
store 가 engines 를 import 하면 판정 경로가 저장소에 묶여 부록 A 의 교체 가능성이
무너지고, llm 을 import 하면 원칙 1 의 구멍이 저장소 쪽으로 열린다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "home_compass"

#: SPEC 1.2 의 의존 방향. 값은 "이 패키지가 import 하면 안 되는 형제 패키지".
FORBIDDEN: dict[str, tuple[str, ...]] = {
    # engines: 순수. 아무것도 의존하지 않는다 (common 은 engines 소유라 형제가 아니다)
    "engines": ("llm", "store", "ingest", "main", "config", "auth"),
    # ingest ──→ store · llm 만. api 를 부르지 않는다
    "ingest": ("main", "engines", "auth"),
    # store: 저장소. 판정도 LLM 도 모른다 (부록 A 교체 가능성 · 원칙 1)
    "store": ("engines", "llm", "ingest", "main", "auth"),
    # llm: 프로바이더 추상화. 저장소·판정을 직접 만지지 않는다
    "llm": ("store", "ingest", "auth"),
    # ★ 위 네 행의 "auth" 는 **역방향** 금지다. 한 방향만 막으면 [auth 가 남을 부르는 것]만
    #   막히고 [남이 auth 를 부르는 것]은 아무도 안 막는다. W-auth 가 잡아냈다.
    #   특히 engines 쪽이 중요하다 — 판정 경로에 인증이 새면 원칙 1 옆에 구멍이 하나 더 생긴다.
    # auth: api 의 일부다 (SPEC 1.1 컴포넌트 표에서 인증은 api 의 책임이다).
    # main.py 에 400줄을 더 얹지 않으려고 파일로 나눈 것이며 새 컴포넌트가 아니다.
    # store·config 는 쓴다. 판정과 LLM 은 인증이 알 이유가 없다.
    "auth": ("engines", "llm", "ingest"),
}

#: 아직 없는 것은 건너뛴다. 생기면 자동으로 검사 대상이 된다.
#: ★ 디렉터리만 보면 **단일 모듈(`auth.py`)이 조용히 검사에서 빠진다.** 그 상태는
#:   [규칙을 적어 뒀는데 아무것도 검사하지 않는] 최악의 형태다 — 아래 존재 검사가 그것을 막는다.
PACKAGES = [
    name for name in FORBIDDEN
    if (SRC / name).is_dir() or (SRC / f"{name}.py").is_file()
]


def _imported_siblings(package: str) -> dict[str, list[str]]:
    """`home_compass.<sibling>` 형태로 끌어오는 것을 전부 찾는다.

    절대 import(`from home_compass.llm import x`)와 상대 import(`from ..llm import x`)를
    모두 잡는다. 상대 import 만 검사하면 절대 경로로 우회할 수 있고, 그 반대도 같다.
    """
    hits: dict[str, list[str]] = {}
    root = SRC / package
    top_level_module = not root.is_dir()
    paths = sorted(root.rglob("*.py")) if root.is_dir() else [SRC / f"{package}.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                # ★ level 1 의 의미는 **파일이 어디 있느냐**에 따라 다르다.
                #   `engines/tco.py` 의 `from .helper import x` 는 패키지 안쪽이라 형제가 아니다.
                #   `auth.py` 의 `from .engines import x` 는 SRC 바로 아래라 **형제다.**
                #   모듈을 검사 대상에 넣으면서 이 갈래를 안 만들면 규칙이 표에만 남고
                #   아무것도 잡지 않는다 — 실제로 프로브를 심어 그 상태를 확인했다.
                if node.level == 1 and top_level_module and node.module:
                    targets.append(node.module.split(".")[0])
                elif node.level == 0 and node.module:
                    parts = node.module.split(".")
                    if parts[:1] == ["home_compass"] and len(parts) > 1:
                        targets.append(parts[1])
                elif node.level >= 2:
                    if node.module:
                        # `from ..llm import chat` -> 형제는 module 쪽이다.
                        # names 는 심볼이므로 여기서 보면 안 된다 —
                        # `from ..common import config` 를 config 의존으로 오인한다.
                        targets.append(node.module.split(".")[0])
                    else:
                        # `from .. import llm` -> 형제가 names 쪽에 온다.
                        targets.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[:1] == ["home_compass"] and len(parts) > 1:
                        targets.append(parts[1])
            for target in targets:
                hits.setdefault(target, []).append(
                    f"{path.relative_to(SRC)}:{getattr(node, 'lineno', '?')}")
    return hits


def test_the_packages_under_check_actually_exist():
    """패키지가 사라지거나 이름이 바뀌면 아래 검사들이 조용히 0건을 통과시킨다."""
    assert "engines" in PACKAGES, f"engines 패키지를 찾지 못했다: {SRC}"
    assert "store" in PACKAGES, "store 는 0단계 산출물이다. 사라졌다면 검사가 무력화된다"


def test_every_forbidden_entry_that_exists_is_actually_checked():
    """규칙을 적어 뒀는데 **대상이 잡히지 않는** 상태를 막는다.

    `auth` 는 패키지가 아니라 단일 모듈(`auth.py`)이다. 존재 검사를 디렉터리로만 하면
    규칙은 표에 남고 검사는 0건이 되며, 그 조합은 [지켜지고 있다]로 오독된다.
    """
    for name in FORBIDDEN:
        exists = (SRC / name).is_dir() or (SRC / f"{name}.py").is_file()
        if exists:
            assert name in PACKAGES, f"{name} 이 존재하는데 검사 대상에서 빠졌다"


@pytest.mark.parametrize("package", PACKAGES)
def test_package_does_not_import_forbidden_siblings(package: str):
    hits = _imported_siblings(package)
    violations = {
        sibling: sites
        for sibling, sites in hits.items()
        if sibling in FORBIDDEN[package]
    }
    assert not violations, (
        f"SPEC 1.2 의존 방향 위반 — {package} 가 import 하면 안 되는 것을 끌어온다: "
        f"{violations}")


def test_engines_does_not_import_llm_anywhere():
    """SPEC 1.2 첫 줄 · 원칙 1 의 기계적 강제. 위 파라미터 테스트와 중복이지만 남긴다.

    중복이 아니라 이름이다 — 이 줄이 빨간불이면 무엇이 무너졌는지가 테스트 이름에서
    바로 읽혀야 한다. 원칙 1 은 이 제품의 서사 전체가 얹혀 있는 주장이다.
    """
    assert "llm" not in _imported_siblings("engines"), (
        "engines 가 llm 을 import 한다. 판정 경로에 AI 가 없다는 원칙 1 이 깨졌다 "
        "— LLM 장애나 API 키 부재가 핵심 판정을 건드릴 수 있게 된다")


def test_engines_does_not_import_store():
    """SPEC 1.2 — 데이터는 주입받는다 (주입 경로는 5.1.1)."""
    assert "store" not in _imported_siblings("engines"), (
        "engines 가 store 를 import 한다. 5.1.1 의 명시적 주입이 무너진다")
