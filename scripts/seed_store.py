"""저장소 시드 — `python scripts/seed_store.py`

Wave 2 컷오버 이후 `api` 는 모델 상수를 **저장소에서만** 읽는다 (SPEC 1.2 생성 방향).
따라서 저장소가 비어 있으면 서버는 기동을 거부한다 (SPEC 5.1.1 fail-closed).
그 상태를 푸는 것이 이 스크립트이며, `scripts/dev.bat` 이 기동 직전에 부른다.

**기동 경로에 자동 시드를 넣지 않았다.** 넣으면 "상수 하나를 지우면 기동이 거부된다"
(SPEC 10.2 1-① 완료 기준)가 성립하지 않는다 — 지운 상수가 그 자리에서 되살아나기
때문이다. 시드는 설치 단계이고 기동은 검증 단계다. 둘을 섞지 않는다.

    python scripts/seed_store.py
    python scripts/seed_store.py --url sqlite://./backend/var/home_compass.db

두 번 돌려도 결과가 같다 (`seed_all` 이 멱등이다). 종료코드 0 = 성공.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _console import force_utf8_stdout

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from home_compass.engines import required_constant_keys  # noqa: E402
from home_compass.store import DEFAULT_STORE_URL, STORE_URL_ENV, create_store  # noqa: E402
from home_compass.store.seed import seed_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="저장소 시드 (SPEC 0단계)")
    parser.add_argument(
        "--url",
        help=f"저장소 URL. 없으면 ${STORE_URL_ENV}, 그것도 없으면 {DEFAULT_STORE_URL}",
    )
    args = parser.parse_args(argv)

    url = args.url or os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL
    print(f"저장소 URL: {url}")

    with create_store(url) as store:
        # `demo_queue=True` 는 시연 대기 큐(원문 7건 · 초안 7건)를 함께 싣는다 (결정 #42).
        # ★ 기본값이 아니라 **여기서만** 켠다. `seed_all` 의 기본을 켜면 그것을 부르는
        #   api 시험들이 빈 큐 전제를 잃는다 (`test_auth.py` 의 초안 목록 · `test_status_metrics.py`
        #   의 `drafts == 1`). 시연 저장소를 채우는 것은 이 스크립트의 일이고, 시험이
        #   자기 상태를 스스로 만드는 것은 시험의 일이다 — 둘을 한 기본값으로 묶지 않는다.
        counts = seed_all(store, at=datetime.now(timezone.utc), demo_queue=True)
        mapping = store.model_constants.as_mapping()

    print(f"  적재: {counts}")

    # 시드가 끝났는데도 서버가 뜨지 못하는 상태를 여기서 잡는다. 여기서 통과하지 못하면
    # 기동은 반드시 실패하므로, 실패를 서버 트레이스백이 아니라 이 자리에서 읽게 한다.
    missing = sorted(set(required_constant_keys()) - set(mapping))
    if missing:
        print(f"  [!] 엔진이 요구하는 상수가 저장소에 없습니다: {missing}")
        return 1

    print(f"  기동 전수 검증 통과 — 엔진 요구 {len(required_constant_keys())}키 전부 존재")
    return 0


if __name__ == "__main__":
    sys.exit(main())
