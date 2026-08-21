"""설정 문자열 하나로 백엔드를 고른다 (부록 A).

    HOME_COMPASS_STORE_URL=sqlite://./backend/var/home_compass.db
    HOME_COMPASS_STORE_URL=postgresql://user@host/home_compass     ← 드라이버 등록만 하면 된다

외부 DB 를 붙이는 쪽은 `register_backend(scheme, factory)` 를 부르면 되고, `store/` 안의
어떤 파일도 고치지 않는다. 호출자는 URL 만 바뀐다 — 이것이 "코드 변경 없이 설정으로 교체".

URL 형식은 `<scheme>://<target>` 이다. `target` 의 해석은 백엔드 소관이다
(SQLite 는 파일 경로 또는 `:memory:`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .errors import UnknownBackendError
from .interfaces import Store

#: 부록 A — 비밀·설정은 환경변수로 주입한다.
STORE_URL_ENV = "HOME_COMPASS_STORE_URL"

#: 환경변수가 없을 때의 로컬 기본값 (SPEC 1.3 로컬 단일 호스트).
DEFAULT_STORE_URL = f"sqlite://{Path(__file__).resolve().parents[3] / 'var' / 'home_compass.db'}"

_BACKENDS: dict[str, Callable[[str], Store]] = {}


def register_backend(scheme: str, factory: Callable[[str], Store]) -> None:
    """URL 스킴에 백엔드를 붙인다. 같은 스킴을 다시 등록하면 덮어쓴다."""
    _BACKENDS[scheme] = factory


def available_backends() -> list[str]:
    return sorted(_BACKENDS)


def create_store(url: str) -> Store:
    """설정 문자열이 가리키는 저장소를 연다."""
    if "://" not in (url or ""):
        raise UnknownBackendError(
            f"저장소 URL 에 스킴이 없다: {url!r}. '<scheme>://<target>' 형식이어야 한다. "
            f"등록된 스킴: {available_backends()}"
        )
    scheme, target = url.split("://", 1)
    factory = _BACKENDS.get(scheme)
    if factory is None:
        raise UnknownBackendError(
            f"등록되지 않은 저장소 백엔드: {scheme!r}. 등록된 스킴: {available_backends()}"
        )
    return factory(target)


def store_from_env(env: dict[str, str] | None = None) -> Store:
    """`HOME_COMPASS_STORE_URL` 을 읽어 저장소를 연다."""
    source = os.environ if env is None else env
    return create_store(source.get(STORE_URL_ENV) or DEFAULT_STORE_URL)
