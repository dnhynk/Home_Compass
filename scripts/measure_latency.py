"""응답 지연 실측 — SPEC 8.3 #1 "타임아웃은 측정에서 유도한다".

8.3 은 값을 정하지 않고 규칙만 고정했고, #1 이 **"저장소 도입 후의 실측 지연 분포를
근거로 삼는다"** 였다. 저장소가 들어왔으므로 이제 잴 수 있다.

이 스크립트는 **값을 정하지 않는다.** 분포를 내고 끝난다. 값은 코디네이터가 8.2 절차로
정하고 계약 파일의 `x-` 확장에만 존재한다 (8.3 #3).

    python scripts/measure_latency.py
    python scripts/measure_latency.py --samples 500 --out backend/tests/api/artifacts/analyze_latency.md

재는 것은 **클라이언트가 겪는 시간**이다 — 루프백 HTTP 왕복을 포함한 벽시계이며,
서버 내부 함수 시간이 아니다. 프론트 타임아웃과 비교되는 값이 그것이기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from _console import force_utf8_stdout

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

import httpx  # noqa: E402

#: 대표 프로필. 한 프로필만 재면 그 프로필의 분기만 재게 된다.
PROFILES = [
    {"id": "typical", "body": {
        "age": 28, "annualIncomeKRW": 42_000_000, "monthlyNetIncomeKRW": 3_000_000,
        "liquidAssetsKRW": 40_000_000, "existingDebtMonthlyKRW": 300_000,
        "householdSize": 1, "regionCode": "11440", "isHomeless": True,
        "isNewlywed": False, "isSMEEmployee": True, "preferredType": "any"}},
    {"id": "defaults", "body": {}},
    {"id": "zero-income", "body": {
        "age": 24, "annualIncomeKRW": 0, "monthlyNetIncomeKRW": 0,
        "householdSize": 3, "regionCode": "11620"}},
    {"id": "high-income", "body": {
        "age": 39, "annualIncomeKRW": 180_000_000, "monthlyNetIncomeKRW": 11_000_000,
        "liquidAssetsKRW": 900_000_000, "householdSize": 4,
        "regionCode": "41117", "preferredType": "jeonse"}},
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _seed(db: Path) -> str:
    from home_compass.store import create_store
    from home_compass.store.seed import seed_all

    url = f"sqlite://{db}"
    with create_store(url) as store:
        seed_all(store, at=datetime.now(timezone.utc))
    return url


def _percentile(values: list[float], q: float) -> float:
    """선형보간 없는 최근접 순위. 표본이 적을 때 없는 값을 만들어 내지 않는다."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(q / 100 * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "min": min(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


#: `frontend/app.js` 의 타임아웃 배정. **4500ms 는 analyze 에 걸린 값이 아니다** —
#: `timeoutFor()` 가 /api/chat 과 /api/analyze 만 따로 잡고 나머지를 기본값으로
#: 떨어뜨리므로, 예선 실패로 기록된 그 값이 실제로 지배하는 것은 아래 세 GET 이다.
#: 재는 대상을 analyze 로만 잡으면 정작 문제의 값이 걸린 곳을 안 재게 된다.
GET_ENDPOINTS = ["/api/health", "/api/regions", "/api/meta"]


def measure(base: str, samples: int, warmup: int) -> dict:
    result: dict = {"analyze": {}, "chat": {}, "get": {}}
    with httpx.Client(base_url=base, timeout=120.0) as client:
        # 콜드 1회는 따로 기록한다. 첫 요청에는 import·연결 수립이 섞여 분포를 오염시키고,
        # 그렇다고 버리면 사용자가 실제로 겪는 최악을 숨기게 된다.
        started = time.perf_counter()
        first = client.post("/api/analyze", json=PROFILES[0]["body"])
        result["coldFirstRequestMs"] = (time.perf_counter() - started) * 1000
        first.raise_for_status()

        for _ in range(warmup):
            client.post("/api/analyze", json=PROFILES[0]["body"]).raise_for_status()

        everything: list[float] = []
        for profile in PROFILES:
            timings = []
            for _ in range(samples):
                started = time.perf_counter()
                response = client.post("/api/analyze", json=profile["body"])
                elapsed = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                timings.append(elapsed)
            result["analyze"][profile["id"]] = _summary(timings)
            everything.extend(timings)
        result["analyze"]["ALL"] = _summary(everything)

        for endpoint in GET_ENDPOINTS:
            timings = []
            for _ in range(samples):
                started = time.perf_counter()
                response = client.get(endpoint)
                timings.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
            result["get"][endpoint] = _summary(timings)

        chat_timings = []
        for _ in range(max(10, samples // 10)):
            started = time.perf_counter()
            response = client.post("/api/chat", json={
                "message": "전세와 월세 중 뭐가 나을까요", "profile": PROFILES[0]["body"]})
            chat_timings.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
        result["chat"]["offline"] = _summary(chat_timings)
    return result


def render(result: dict, meta: dict) -> str:
    def table(rows: dict) -> str:
        head = ("| 케이스 | n | min | p50 | p90 | p95 | p99 | max | mean |\n"
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        body = ""
        for name, s in rows.items():
            body += (f"| `{name}` | {s['n']} | {s['min']:.1f} | {s['p50']:.1f} | {s['p90']:.1f} "
                     f"| {s['p95']:.1f} | {s['p99']:.1f} | {s['max']:.1f} | {s['mean']:.1f} |\n")
        return head + body

    return f"""# `/api/analyze` 응답 지연 실측 (SPEC 8.3 #1)

> **이 문서는 값을 정하지 않는다.** 분포만 낸다. 타임아웃 값은 코디네이터가 8.2 절차로
> 정하고 `contracts/openapi.json` 의 `x-boundary-conditions` 에만 존재한다 (8.3 #3).

## 측정 방법

- 재는 것: **클라이언트가 겪는 벽시계 시간**. 루프백 HTTP 왕복을 포함한다.
  서버 내부 함수 시간이 아니다 — 프론트 타임아웃과 비교되는 값이 그것이기 때문이다.
- 서버: `python -m uvicorn home_compass.main:app` 실기동 (TestClient 아님)
- 저장소: 시드된 임시 SQLite. 모델 상수 {meta['constants']}키가 기동 시 전수 검증된 상태
- 프로바이더: `offline` (API 키 없음). `/api/analyze` 는 원칙 1 에 따라 LLM 을 부르지 않으므로
  이 설정이 analyze 분포에 영향을 주지 않는다. `/api/chat` 은 템플릿 경로를 잰 값이다
- 연결: `httpx.Client` 하나를 재사용하는 **순차 호출**. 동시 요청 없음
- 측정 시각: {meta['at']}
- 실행 환경: {meta['platform']} / Python {meta['python']}
- 명령: `{meta['command']}`

## 결과 (밀리초)

### `/api/analyze`

{table(result['analyze'])}

- **콜드 1회차**: {result['coldFirstRequestMs']:.1f} ms
  (첫 요청에는 연결 수립이 섞인다. 분포에서 빼되 숨기지 않는다)

### GET 엔드포인트 — **현행 4500ms 가 실제로 지배하는 곳**

{table(result['get'])}

### `/api/chat` (offline 템플릿 경로)

{table(result['chat'])}

## 읽는 법 — 예선 실패와의 대조

Part 0-A 에 기록된 사고는 **프론트 타임아웃 4500ms < 실제 응답 2700~6900ms** 였고,
결과는 조용한 폴백이었다.

**측정하면서 확인한 것 하나 — 4500ms 는 `/api/analyze` 에 걸린 값이 아니다.**
`frontend/app.js` 의 `timeoutFor()` 는 이렇게 배정한다.

| 경로 | 현행 값 |
|---|---|
| `/api/chat` | `CHAT_TIMEOUT_MS` = 75,000 |
| `/api/analyze` | `ANALYZE_TIMEOUT_MS` = 15,000 |
| **그 밖 전부** (`/api/health` · `/api/regions` · `/api/meta`) | `FETCH_TIMEOUT_MS` = **4,500** |

SPEC 8.3 과 Part 0-A 는 4500ms 를 실패 원인으로 기록하면서 그것이 어느 경로에 걸린
값인지는 적지 않았다. 따라서 값을 정할 때 **세 GET 을 analyze 와 같은 기준으로 다루면
안 된다** — 지금 위험한 것은 analyze 쪽이 아니다.

SPEC 8.3 #2 는 `클라이언트 타임아웃 > 서버 응답 예산 + 마진` 을 요구한다.
그 둘을 정하는 근거가 이 표이며, **판단은 코디네이터가 한다.**

## 이 측정이 담지 못한 것

- **동시 요청 없음.** 시연은 단일 사용자·로컬 단일 호스트(D-8)라 순차가 대표값이지만,
  상담원 화면과 시민 화면을 동시에 여는 시연 장면에서는 다를 수 있다
- **판정 경로만.** 3단계 배치·2단계 추출의 지연은 여기 없다 (해당 모듈이 아직 없다)
- **이 머신 하나.** 시연 노트북이 다르면 다시 재야 한다
- 시세·정책 데이터는 시드 규모(지역 {meta['regions']}건 · 정책 {meta['policies']}건) 기준이다.
  실데이터가 붙으면 `evaluate_policies` 의 순회가 늘어난다
"""


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="응답 지연 실측 (SPEC 8.3)")
    parser.add_argument("--samples", type=int, default=200, help="프로필당 표본 수")
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--out", default="backend/tests/api/artifacts/analyze_latency.md")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        store_url = _seed(Path(tmp) / "latency.db")
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "HOME_COMPASS_STORE_URL": store_url, "PYTHONPATH": str(SRC),
               "PYTHONIOENCODING": "utf-8", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}
        # ★ 서버 출력을 **파일로** 받는다. `subprocess.PIPE` 로 받아놓고 측정하는 동안
        #   읽지 않으면, 500 이 한 번이라도 나는 순간 트레이스백(약 8KB)이 OS 파이프
        #   버퍼(약 4KB)를 채우고 uvicorn 의 로깅 `write()` 가 **이벤트 루프 스레드에서
        #   블로킹된다.** 그러면 응답이 플러시되지 못해 **그 요청의 지연이 앱의 지연이
        #   아니라 로그가 막힌 시간이 된다** — 재려던 것이 아닌 것을 재게 된다. 이 저장소는
        #   SPEC 8.3 의 타임아웃 값을 이 스크립트의 측정에서 유도했으므로, 오염된 수가
        #   그대로 계약의 근거가 된다. `--log-level error` 라 접근 로그가 없어 아직 안
        #   물렸을 뿐이다. 같은 수정이 `backend/tests/api/test_log_hygiene.py` 에도 있다.
        console = open(Path(tmp) / "server-console.log", "w+b")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "home_compass.main:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            cwd=str(SRC), env=env, stdout=console, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"{base}/api/health", timeout=2.0).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                raise SystemExit("서버가 기동하지 않았다")

            print(f"측정 시작 — 프로필 {len(PROFILES)}종 x {args.samples}회")
            result = measure(base, args.samples, args.warmup)

            from home_compass.store import create_store
            with create_store(store_url) as store:
                meta = {
                    "constants": len(store.model_constants.list()),
                    "regions": len(store.regions.list()),
                    "policies": len(store.rule_versions.list()),
                }
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=15)
            console.close()

    meta.update({
        "at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "command": f"python scripts/measure_latency.py --samples {args.samples}",
    })

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(result, meta))

    print(json.dumps(result["analyze"]["ALL"], indent=1))
    print(f"기록: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
