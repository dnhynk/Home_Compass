"""부록 A — "SQLite ↔ 외부 DB 교체가 코드 변경 없이 설정으로 가능하다".

부록 A 는 이것을 **문서가 아니라 0단계 코드 결정**이라고 못 박는다. 부록으로 미루면
사후 증명이 불가능해진다. 그래서 여기서 증명한다.

증명 방식은 하나뿐이다 — 저장 매체가 완전히 다른 **두 번째 구현체**(`memory_backend.py`)를
두고, 같은 계약 테스트를 통과시키며, 호출자가 바꾸는 것이 **설정 문자열 하나뿐**임을 보인다.
구현이 하나면 인터페이스가 실제로 지켜지는지 아무도 모른다.
"""

from __future__ import annotations

import inspect
import os

import pytest
from conftest import make_audit_event, make_region

from home_compass.store import create_store, register_backend, store_from_env
from home_compass.store.errors import UnknownBackendError
from home_compass.store.interfaces import Store


def test_the_caller_changes_only_the_url(tmp_path):
    """같은 코드가 두 백엔드에서 똑같이 돈다. 분기도 import 도 없다."""

    def use(store):  # 호출자 코드 — 백엔드를 모른다
        store.regions.upsert(make_region("11440", jeonse_median_krw=280_000_000))
        store.audit.append(make_audit_event("ae-1"))
        return store.regions.get("11440").jeonse_median_krw, len(store.audit.list())

    with create_store(f"sqlite://{tmp_path / 'a.db'}") as sqlite_store:
        from_sqlite = use(sqlite_store)
    with create_store("memory://swap") as memory_store:
        from_memory = use(memory_store)

    assert from_sqlite == from_memory == (280_000_000, 1)


def test_both_backends_satisfy_the_same_interface(store):
    assert isinstance(store, Store)
    for name in (
        "regions", "policy_sources", "rule_drafts", "rule_versions",
        "model_constants", "users", "approvals", "reports", "audit",
    ):
        assert getattr(store, name) is not None, name


def test_every_abstract_method_is_implemented(store):
    """ABC 가 형식적으로만 존재하고 구현이 비어 있으면 교체 가능성은 허구다."""
    missing = []
    for attr in dir(type(store)):
        if attr.startswith("_"):
            continue
        value = getattr(store, attr, None)
        if value is None:
            missing.append(attr)
    assert not missing, missing

    for repo_name in ("regions", "rule_versions", "audit", "model_constants", "reports"):
        repo = getattr(store, repo_name)
        for method_name in (n for n in dir(repo) if not n.startswith("_")):
            method = getattr(repo, method_name)
            assert callable(method), f"{repo_name}.{method_name}"
            assert not getattr(method, "__isabstractmethod__", False), f"{repo_name}.{method_name}"


def test_unknown_scheme_fails_loudly_and_names_what_is_available():
    with pytest.raises(UnknownBackendError) as err:
        create_store("postgresql://localhost/home_compass")
    assert "postgresql" in str(err.value)
    assert "sqlite" in str(err.value), "무엇을 쓸 수 있는지 알려주지 않으면 설정 오류를 못 고친다"


def test_a_url_without_a_scheme_is_rejected():
    with pytest.raises(UnknownBackendError):
        create_store("./store.db")


def test_a_new_backend_needs_no_change_to_the_store_package(tmp_path):
    """외부 DB 를 붙이는 쪽이 `register_backend` 만 부르면 된다 — store/ 는 그대로다."""
    calls = []

    class Recorded:
        def __init__(self, target):
            calls.append(target)

    register_backend("pretend", Recorded)
    create_store("pretend://host:5432/db")
    assert calls == ["host:5432/db"]


def test_the_store_url_comes_from_the_environment(tmp_path, monkeypatch):
    """부록 A — 설정은 환경변수로 주입한다. `.env` 는 편의 수단일 뿐 유일 경로가 아니다."""
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", f"sqlite://{tmp_path / 'env.db'}")
    with store_from_env() as store:
        store.regions.upsert(make_region("11440"))
    assert (tmp_path / "env.db").exists()


def test_the_environment_can_select_a_completely_different_backend(monkeypatch):
    register_backend("memory", __import__("memory_backend").MemoryStore.open)
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", "memory://from-env")
    with store_from_env() as store:
        assert type(store).__name__ == "MemoryStore"


def test_store_package_holds_no_sqlite_specific_call_in_its_public_surface():
    """공개 표면이 sqlite3 를 흘리면 교체가 '코드 변경 없이' 가 되지 않는다."""
    import home_compass.store as pkg

    for name in pkg.__all__:
        obj = getattr(pkg, name)
        if inspect.isclass(obj) or inspect.isfunction(obj):
            source_file = getattr(inspect.getmodule(obj), "__file__", "") or ""
            assert "sqlite" not in os.path.basename(source_file).lower(), (
                f"{name} 이 SQLite 전용 모듈에서 나온다"
            )
