"""Production-safe single-process entry point.

The competition URL must survive restarts and must never expose authentication
cookies without HTTPS. This script validates those deployment-only invariants,
idempotently seeds the persistent store, and starts exactly one Uvicorn worker.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from home_compass.auth import (  # noqa: E402
    COUNSELOR_PASSWORD_ENV,
    RULE_MANAGER_PASSWORD_ENV,
    cookie_secure,
)
from home_compass.engines import required_constant_keys  # noqa: E402
from home_compass.store import DEFAULT_STORE_URL, STORE_URL_ENV, create_store  # noqa: E402
from home_compass.store.seed import seed_all  # noqa: E402

DEPLOYMENT_ENV = "HOME_COMPASS_ENV"
PRODUCTION = "production"
MIN_DEMO_PASSWORD_LENGTH = 16


def _port() -> int:
    raw = (os.environ.get("PORT") or "8000").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"PORT must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"PORT must be between 1 and 65535, got {port}")
    return port


def validate_environment() -> None:
    """Fail before binding a public port when production secrets are missing."""
    if (os.environ.get(DEPLOYMENT_ENV) or "").strip().lower() != PRODUCTION:
        return
    if not cookie_secure():
        raise RuntimeError(
            "Production requires HOME_COMPASS_COOKIE_SECURE=true so auth cookies "
            "cannot travel over plain HTTP."
        )
    missing = []
    for key in (COUNSELOR_PASSWORD_ENV, RULE_MANAGER_PASSWORD_ENV):
        value = os.environ.get(key) or ""
        if len(value) < MIN_DEMO_PASSWORD_LENGTH:
            missing.append(key)
    if missing:
        raise RuntimeError(
            "Production requires non-committed demo passwords of at least "
            f"{MIN_DEMO_PASSWORD_LENGTH} characters: {', '.join(missing)}"
        )


def seed_store() -> None:
    """Prepare the durable demo store; repeated deployment starts are harmless."""
    url = os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL
    with create_store(url) as store:
        counts = seed_all(store, at=datetime.now(timezone.utc), demo_queue=True)
        keys = set(store.model_constants.as_mapping())
    missing = sorted(set(required_constant_keys()) - keys)
    if missing:
        raise RuntimeError(f"Seed completed but required model constants are missing: {missing}")
    print(f"[startup] store ready: {url} / {counts}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate, seed, and start Home_Compass")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and seed, then exit without starting Uvicorn",
    )
    args = parser.parse_args(argv)

    validate_environment()
    seed_store()
    if args.check:
        print("[startup] deployment preflight passed", flush=True)
        return 0

    host = (os.environ.get("HOST") or "0.0.0.0").strip()
    port = _port()
    os.chdir(BACKEND_SRC)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "home_compass.main:app",
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        "1",
        "--proxy-headers",
        "--forwarded-allow-ips",
        "*",
    ]
    print(f"[startup] serving http://{host}:{port} with one worker", flush=True)
    os.execv(sys.executable, command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
