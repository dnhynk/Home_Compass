"""표준출력을 콘솔 코덱에서 떼어낸다 — `scripts/` 공용 (SPEC 9.1 "중복 구현 금지").

## 왜 필요한가

파이썬은 stdout 이 **진짜 콘솔**이면 WriteConsoleW 로 유니코드를 그대로 쓰지만,
**파이프로 넘어가는 순간** 로케일 인코딩으로 되돌아간다. 윈도우 한국어 환경에서
그 값은 `cp949` 이고, 이 저장소의 스크립트는 전부 한국어를 출력한다.

    python scripts/coord_status.py            # 콘솔 → 정상
    python scripts/coord_status.py | more     # 파이프 → UnicodeEncodeError

즉 **사람이 손으로 돌릴 때는 멀쩡하고, 출력을 갈무리하는 순간에만 죽는다.**
코디네이터의 무인 루프가 바로 그 경로다 — 상태판이 죽으면 판단 재료가 사라진다.

## 왜 스크립트마다 두 줄 넣지 않는가

같은 규약을 여러 곳에 복사하면 함수가 늘어날 때 따라오지 않는다. 이 저장소는 그
실패를 이미 겪었다 — `common.money()` 의 "byte-for-byte" 규약이 주석으로만 있었고
`pct()` 에는 따라붙지 않아 두 구현이 다른 문자열을 냈다 (SPEC 9.1.1). 여기서도
구현을 하나로 두고, `test_scripts_encoding.py` 가 **호출 여부**를 강제한다.

UTF-8 을 고르는 이유는 `gen_contracts.py --stdout` 이 이미 같은 선택을 했기 때문이다
(커밋 7883335). 출력 바이트가 실행 환경에 따라 달라지지 않는다.
"""

from __future__ import annotations

import sys


def force_utf8_stdout() -> None:
    """`sys.stdout` · `sys.stderr` 를 UTF-8 로 고정한다. 진입점에서 가장 먼저 부른다.

    `reconfigure` 가 없는 스트림(테스트가 갈아끼운 `StringIO` 등)은 조용히 건너뛴다 —
    이 함수의 목적은 출력이지 스트림 검사가 아니다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        reconfigure(encoding="utf-8")
