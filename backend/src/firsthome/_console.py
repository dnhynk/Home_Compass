"""표준출력을 콘솔 코덱에서 떼어낸다 — **backend 진입점 전부** 공용 (SPEC 9.1 "중복 구현 금지").

## 왜 `ingest/` 밖으로 나왔는가 (2026-08-16)

`store/__main__.py` 도 같은 결함을 갖고 있었는데(좁은 코덱에서 **첫 print 에** 죽는다)
**`store` 는 `ingest` 를 import 할 수 없다** — `test_architecture.FORBIDDEN["store"]` 가
막는다. 부록 A 의 저장소 교체 가능성을 지키는 규칙이고 옳다.

그래서 이 파일이 `ingest/` 안에 있는 한 **아키텍처 규칙이 세 번째 사본을 강요한다.**
그것이 정확히 아래 「왜 진입점마다 세 줄 넣지 않는가」가 경고한 실패이므로, 구현을
패키지 뿌리로 올려 **어느 컴포넌트도 아닌 자리**에 둔다. 형제 패키지가 아니므로
의존 방향 규칙에 걸리지 않는다 (`PACKAGES` 는 `FORBIDDEN` 의 키로만 만들어진다).

## 왜 `scripts/_console.py` 를 쓰지 않는가

**import 할 수 없다.** 그쪽은 `scripts/` 가 `sys.path` 에 있을 때만 잡히는 최상위
모듈이고(`from _console import force_utf8_stdout`), 이 패키지는 `backend/src` 아래
`firsthome.*` 로 산다. 두 뿌리는 서로를 모른다. 그래서 **규약은 같고 구현은 둘**이며,
그 사실을 여기 적어 둔다 — 한쪽만 고치면 다른 쪽이 조용히 남는다.

## 왜 필요한가

파이썬은 stdout 이 **진짜 콘솔**이면 WriteConsoleW 로 유니코드를 그대로 쓰지만,
**파이프·리다이렉트로 넘어가는 순간** 로케일 인코딩으로 되돌아간다. 윈도우 한국어
환경에서 그 값은 `cp949` 이고, 이 패키지의 진입점은 전부 한국어를 출력한다.

    python -m firsthome.ingest              # 콘솔 → 정상
    python -m firsthome.ingest > run.txt    # 리다이렉트 → UnicodeEncodeError, 종료코드 1

즉 **사람이 손으로 돌릴 때는 멀쩡하고, 출력을 갈무리하는 순간에만 죽는다.** 배치의
판정을 로그로 남기는 경로가 정확히 그것이다.

## 왜 진입점마다 세 줄 넣지 않는가

`scripts/_console.py` 가 적어 둔 이유와 같다 — 같은 규약을 여러 곳에 복사하면 진입점이
늘어날 때 따라오지 않는다. 실제로 `extract_cli` 만 이 가드를 갖고 있었고(커밋 4d740ad
직후) `__main__` 둘은 빠진 채 남아 있었다.
"""

from __future__ import annotations

import sys


def force_utf8_stdout() -> None:
    """`sys.stdout` · `sys.stderr` 를 UTF-8 로 고정한다. 진입점에서 가장 먼저 부른다.

    `reconfigure` 가 없는 스트림(테스트가 갈아끼운 `StringIO` 등)은 조용히 건너뛴다 —
    이 함수의 목적은 출력이지 스트림 검사가 아니다.

    `errors="backslashreplace"` 는 `extract_cli` 가 쓰던 값 그대로다. UTF-8 에서는
    거의 걸릴 일이 없지만, **출력 때문에 배치가 죽는 것**을 막는 것이 이 함수의 목적이므로
    남은 한 자리(짝 없는 서로게이트)에서도 예외 대신 문자를 내주는 쪽을 고른다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        reconfigure(encoding="utf-8", errors="backslashreplace")
