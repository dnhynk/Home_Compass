"""SPEC 7.1 — **로그에 요청 본문이 없다** (소유자: `api` · SPEC 10.2 7단계 기준 ②).

7.1 의 표는 파일 로그에 한 줄을 건다 —
「**파일 로그**(7.2) — 요청 본문을 찍지 않는다. **오류 로그도 예외가 아니다**」.

이 파일은 그것을 **두 층**으로 붙든다. 둘이 다른 것을 재기 때문에 하나로 줄이지 않는다.

  (1) **구조** — 기록자가 본문을 받을 수 있는 **자리 자체가 없는가.** 서명에 `**kwargs`
      가 없고, 허용 키 목록 밖의 이름은 파일에 닿지 못하고, 미들웨어가 본문을 읽는
      호출을 아예 하지 않는다. 읽지 않은 것은 샐 수 없다.

  (2) **실기동** — 진짜 `uvicorn` 을 띄우고 **특징적인 프로필 숫자**로 요청을 친 뒤,
      파일 로그와 **서버의 표준출력·표준오류 전문**을 문자열로 훑는다. 눈으로 훑는 것은
      증거가 아니므로 기계가 훑는다.

## 왜 서버 출력까지 보는가

우리 기록자만 보면 **uvicorn 의 기본 접근 로그**가 검사 밖에 남는다. 그것은 우리가 쓴
코드가 아니지만 같은 콘솔에 찍히고 같은 파일로 리다이렉트되며, 새면 새는 것이다.
그래서 이 테스트는 `--log-level info`(기본)로 띄운다 — `warning` 으로 띄우면 접근 로그가
꺼져 **검사가 스스로 과녁을 치우는** 꼴이 된다.

## 예외 경로

  · **422** — 검증 실패는 [무엇이 틀렸는지] 를 말하려고 값을 인용하는 경향이 있다.
    타입 오류 · 범위 초과 · JSON 문법 오류 셋을 친다
  · **400** — 유효한 UTF-8 이 아닌 본문. 디코딩 오류는 실패한 바이트 주변을 인용하기 쉽다
  · **500** — 처리되지 않은 예외. **프로세스 안에서** 프로바이더 호출을 터뜨려
    만드는 것(2절)과 **실기동에서** 저장소를 깨서 만드는 것(4절) 둘 다 있다

## ★ 실기동 500 이 멈추던 이유 — 정정된 기록

7단계는 이 자리를 「검증하지 못한 것」으로 남겼다. 실기동에서 500 을 만들면 uvicorn 이
접근 로그에 `"POST /api/analyze HTTP/1.1" 500 Internal Server Error` 를 찍고도 응답이
클라이언트에 도달하지 않고 요청이 멈췄으며, 트레이스백도 찍히지 않았다. 그때의 진단은
**「실행 환경(uvicorn 0.38.0 · starlette 0.50.0 · fastapi 0.122.0) 쪽이고 우리 코드가
아니다」** 였다. **그 진단은 틀렸다.** 원인은 **이 파일의 하네스**였다.

원인은 `_Server` 가 서버 출력을 `subprocess.PIPE` 로 받아놓고 요청을 치는 동안 **읽지
않은 것**이다. 500 의 트레이스백은 8KB 가까이 되고 윈도우 익명 파이프 버퍼는 4KB
남짓이므로, 버퍼가 차는 순간 uvicorn 의 로깅 `write()` 가 **이벤트 루프 스레드에서
블로킹된다.** 그러면 이미 헤더까지 나간 응답의 본문이 플러시되지 못해 요청이 멈추고,
트레이스백은 **쓰다가 막혔으므로** 보이지 않는다. 세 가지로 갈라 확인한 것(이 브랜치 ·
HEAD · 맨 FastAPI 앱)이 전부 멈춘 것은 맞지만, 셋 다 **같은 하네스로** 재서 그렇다.
바뀌지 않은 변수가 원인이었다.

네 관측으로 갈랐다 (앱 · 클라이언트 · 의존성 버전 고정, **출력 목적지만** 변경) —

  · PIPE, 배수 안 함 · 500      -> 헤더 172B 만 오고 본문 0B, 트레이스백 없음 · **멈춤**
  · 파일 리다이렉트 · 500        -> 본문까지 193B 도달, 트레이스백 5376자 · 정상
  · PIPE + 배수 스레드 · 500     -> 본문까지 193B 도달, 트레이스백 5376자 · 정상
  · PIPE, 배수 안 함 · **200 만** -> 70번째 요청에서 **멈춤** (출력 3979자에서 정지)

마지막 줄이 [500 특정 결함] 과 [의존성 조합] 둘 다를 기각한다 — 예외가 하나도 없는 200
경로도 로그가 파이프를 채우면 똑같이 멈춘다. 멈춘 뒤 **파이프만 배수하면** 막혀 있던
응답이 0.00초에 완결되는 것으로 기전(이벤트 루프가 `write()` 에서 블로킹)을 확정했다.

그래서 의존성 버전은 내리지 않았고 `backend/requirements.txt` 도 바꾸지 않았다 —
버전은 원인이 아니므로 핀을 박는 것은 증상만 가리는 수정이 된다. 고친 것은 하네스이고,
그 결과 7단계가 남긴 [500 의 콘솔 트레이스백에 본문이 없다] 를 4절에서 실제로 관측한다.

## ★ 그 문턱은 **플랫폼에서 유도한다** — 상수로 박으면 리눅스 CI 에서 빈 검사가 된다

위 관측은 전부 **윈도우 11** 에서 했고 `4096` 은 그 플랫폼의 익명 파이프 용량이다.
그런데 **CI 는 `ubuntu-latest` 다.** 재 보면 리눅스 파이프는 **65536 바이트**를 삼킨다 —
500 트레이스백 하나(약 7KB)로는 채우지 못한다. 즉 문턱을 `4096` 으로 박아 두면 리눅스에서는
**옛 미배수 하네스로도 초록**이 나오고, 그 순간 이 회귀 테스트는 [무조건 통과하는 검사] 가
된다. 없는 검사는 실패하지 않으므로 그것이 가장 나쁜 실패다.

그래서 두 가지를 바꿨다 —

  · 문턱을 **실제로 잰다** (`_measure_pipe_capacity`). 파이프를 하나 열어 쓰는 쪽을
    논블로킹으로 두고 막힐 때까지 채우면 그 플랫폼의 용량이 나온다. 하드코딩된 `4096` 을
    다른 상수로 바꾸는 것은 같은 결함을 다른 수로 옮기는 것이므로 하지 않는다
  · 실기동이 **그 용량을 넘길 때까지** 500 을 친다. 윈도우는 한 번이면 넘고, 리눅스는
    열몇 번이 필요하다. 넘기지 못하면 **skip 하지 않고** [이 플랫폼에서는 이 검사가
    의미 없다] 를 말하며 **실패한다** — skip 은 침묵 폴백이다 (계약 결정 #36 조건 ② 와
    같은 규율)
"""

from __future__ import annotations

import inspect
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import CSRF_HEADER_NAME, ensure_seed_accounts
from home_compass.main import LOG_FIELDS, app
from home_compass.store import create_store
from home_compass.store.seed import seed_all

SRC = Path(__file__).resolve().parents[2] / "src"
T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
BOOT_TIMEOUT_S = 60

COUNSELOR_PW = os.environ["HOME_COMPASS_SEED_COUNSELOR_PASSWORD"]

# --------------------------------------------------------------------------
# 대역 — 이 값들이 로그 어딘가에 있으면 실패다
# --------------------------------------------------------------------------
#
# 값이 특이한 이유는 우연히 다른 곳에서 나오는 숫자와 겹치지 않기 위해서다. 판정 결과에는
# 이 값에서 **유도된** 숫자가 실리지만(그건 시민에게 가는 응답이다) 로그에는 그 원본이
# 한 자리도 있으면 안 된다.

PROFILE = {
    "age": 37,
    "annualIncomeKRW": 73_412_000,
    "monthlyNetIncomeKRW": 4_931_000,
    "liquidAssetsKRW": 61_237_000,
    "existingDebtMonthlyKRW": 812_000,
    "householdSize": 4,
    "regionCode": "11440",
}

#: 6-A 이상 신고의 **자유 입력** (계약 결정 #38). 여기에 고객 상황이 섞일 수 있고,
#: 구조로 막을 수 없는 부분이므로 최소한 로그에는 안 남아야 한다.
REPORT_REASON = "고객이 소득 4931000원이라는데 판정이 이상하다 — 연락처 010-9182-7364"

#: 422 를 유발하면서 값을 인용하게 만들려는 미끼. 정수 칸에 문자열을 넣는다.
BAIT_STRING = "서른일곱-91827364"


def _marks() -> tuple[str, ...]:
    """로그에서 찾아볼 자국. 정수 그대로와 콤마 표기 **둘 다** 본다.

    어느 표기로 새는지는 새는 코드가 정하지 우리가 정하지 않는다.
    """
    numbers = (
        PROFILE["annualIncomeKRW"], PROFILE["monthlyNetIncomeKRW"],
        PROFILE["liquidAssetsKRW"], PROFILE["existingDebtMonthlyKRW"],
    )
    marks = [str(n) for n in numbers] + [f"{n:,}" for n in numbers]
    marks += [BAIT_STRING, "010-9182-7364", "연락처"]
    return tuple(marks)


MARKS = _marks()


def leaked(text: str) -> list[str]:
    return sorted({mark for mark in MARKS if mark in text})


# ==========================================================================
# 1. 구조 — 본문을 실을 자리가 없다
# ==========================================================================

class TestTheLoggersCannotCarryARequestBody:
    @pytest.mark.parametrize("name", ["log_http", "log_llm_chat"])
    def test_the_logger_takes_no_open_ended_keyword_arguments(self, name):
        """`**kwargs` 가 있으면 그 순간 본문을 넣는 것이 **한 줄짜리 일**이 된다."""
        signature = inspect.signature(getattr(main_module, name))
        kinds = [p.kind for p in signature.parameters.values()]
        assert inspect.Parameter.VAR_KEYWORD not in kinds, f"{name} 에 **kwargs 가 있다"
        assert inspect.Parameter.VAR_POSITIONAL not in kinds

    @pytest.mark.parametrize("name", ["log_http", "log_llm_chat"])
    def test_no_parameter_is_named_like_a_body(self, name):
        forbidden = ("body", "payload", "profile", "message", "reason", "content",
                     "request", "json", "query", "params")
        signature = inspect.signature(getattr(main_module, name))
        offenders = [p for p in signature.parameters if p.lower() in forbidden]
        assert not offenders, f"{name} 이 본문을 받을 수 있는 인자를 갖고 있다: {offenders}"

    def test_the_allowlist_has_no_body_shaped_field(self):
        forbidden = ("body", "payload", "profile", "message", "reason", "content",
                     "query", "params", "input")
        offenders = [f for f in LOG_FIELDS if f.lower() in forbidden]
        assert not offenders, f"파일 로그 허용 키에 본문 자리가 있다: {offenders}"

    def test_an_unknown_field_is_refused_rather_than_dropped(self, tmp_path, monkeypatch):
        """★ 조용히 버리면 [적었다고 믿는데 안 적힌] 상태가 된다. 터지는 편이 낫다."""
        monkeypatch.setenv("HOME_COMPASS_LOG_FILE", str(tmp_path / "x.jsonl"))
        with pytest.raises(ValueError) as err:
            main_module._emit_log({"at": "2026-01-01T00:00:00+00:00", "body": "샜다"})
        assert "허용되지 않은" in str(err.value)
        assert not (tmp_path / "x.jsonl").exists(), "거부된 줄이 파일에 닿았다"

    def test_the_middleware_never_reads_the_request_body(self):
        """읽지 않은 것은 샐 수 없다 — 그 규율이 소스에 남아 있는지 본다."""
        source = inspect.getsource(main_module._observe_request)
        for call in ("request.body", "request.json", "request.form", "request.stream"):
            assert call not in source, f"미들웨어가 본문을 읽는다: {call}"
        # 예외는 **타입 이름만** 싣는다. `str(exc)` 에는 검증기가 인용한 입력값이 실린다.
        assert "type(exc).__name__" in source
        assert "str(exc)" not in source

    def test_the_error_envelope_does_not_echo_the_exception_message_either(self):
        source = inspect.getsource(main_module._unhandled_handler)
        assert "type(exc).__name__" in source
        assert "str(exc)" not in source


# ==========================================================================
# 2. 예외 경로 — 500 의 트레이스백에 본문이 없다
# ==========================================================================

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'hygiene.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", url)
    return url


@pytest.fixture
def log_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "observability.jsonl"
    monkeypatch.setenv("HOME_COMPASS_LOG_FILE", str(path))
    return path


class TestTheFiveHundredPathLogsOnlyTheExceptionType:
    def test_a_provider_blow_up_leaves_no_profile_value_in_the_log(
            self, store_url, log_path, monkeypatch):
        """★ **오류 로그도 예외가 아니다.**

        프로바이더 호출을 터뜨린다. 예외 메시지에 프로필 값을 일부러 실어서, 그 메시지가
        로그로 새는지를 본다 — 실제 라이브러리 예외는 우리가 통제하지 못하므로
        [메시지에 값이 들어 있는 예외] 를 최악의 경우로 놓고 잰다.
        """
        boom = RuntimeError(f"프로바이더 호출 실패: 소득 {PROFILE['annualIncomeKRW']}")

        def explode(*_args, **_kwargs):
            raise boom

        monkeypatch.setattr(main_module, "chat", explode)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/chat",
                                   json={"message": "테스트", "profile": PROFILE})
        assert response.status_code == 500, response.text

        # 응답 봉투에도 값이 없다 (기존 규율. 여기서 함께 붙든다).
        assert not leaked(response.text), response.text

        text = log_path.read_text(encoding="utf-8")
        assert '"error": "RuntimeError"' in text, text
        assert not leaked(text), f"500 경로가 프로필 값을 흘렸다: {leaked(text)}"

    def test_the_failed_llm_call_is_still_counted(self, store_url, log_path, monkeypatch):
        """실패한 호출이 기록에서 빠지면 성공률이 늘 100% 가 된다."""
        def explode(*_args, **_kwargs):
            raise RuntimeError("프로바이더 실패")

        monkeypatch.setattr(main_module, "chat", explode)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.post("/api/chat", json={"message": "테스트", "profile": PROFILE})

        records = [json.loads(line) for line in
                   log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        chat_records = [r for r in records if r.get("event") == "llm.chat"]
        assert [r["outcome"] for r in chat_records] == ["failure"]
        assert "latencyMs" in chat_records[0]
        # 대화 내용은 없다 (SPEC 7.1 — 프로바이더로 나가는 내용은 로컬에 남기지 않는다).
        assert set(chat_records[0]) == {"at", "event", "mode", "outcome", "latencyMs"}


# ==========================================================================
# 3. 실기동 — 진짜 uvicorn 을 띄우고 로그 전문을 훑는다
# ==========================================================================
#
# ★ `--log-level` 을 낮추지 않는다. 기본(info)이어야 **uvicorn 의 접근 로그**가 실제로
#   찍히고, 그것까지 훑어야 이 검사가 과녁을 다 덮는다.

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Server:
    def __init__(self, store_url: str, log_file: Path, console_file: Path):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self._output: str | None = None
        self._output_bytes: int | None = None
        # ★ 서버 출력을 **파일로** 받는다. `subprocess.PIPE` 로 받아 종료 시점에
        #   `communicate()` 로 읽으면, 요청을 치는 동안 파이프에 **읽는 쪽이 없다.**
        #   500 의 트레이스백은 8KB 가까이 되고 OS 파이프 버퍼는 그보다 작으므로
        #   (윈도우 4096 · 리눅스 65536 — `_measure_pipe_capacity` 가 잰다),
        #   버퍼가 차는 순간 uvicorn 의 로깅 `write()` 가 **이벤트 루프 스레드에서
        #   블로킹된다.** 그러면 이미 헤더까지 보낸 응답의 본문이 플러시되지 못해
        #   요청이 그대로 멈춘다 — 서버가 죽은 것이 아니라 **로그를 못 써서** 멈춘다.
        #   접근 로그에 500 이 찍히고도 트레이스백이 안 나오는 이유가 이것이다.
        #   트레이스백을 쓰다가 막힌 것이므로.
        #
        #   파일은 차지 않으므로 그 자리가 아예 없어진다. 배수 스레드를 붙이는 길도
        #   있지만 스레드 수명을 이 하네스가 지게 되므로 파일 쪽이 얕다.
        self._console_handle = console_file.open("w+b")
        env = {
            **os.environ,
            "HOME_COMPASS_STORE_URL": store_url,
            "HOME_COMPASS_LOG_FILE": str(log_file),
            "PYTHONPATH": str(SRC),
            "PYTHONIOENCODING": "utf-8",
            # 키 없이 돈다 (SPEC 9.2.1). 개발 머신의 .env 가 이 테스트를 프로바이더
            # 호출로 끌고 가면 재는 것이 네트워크 상태가 된다.
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        }
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "home_compass.main:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "info"],
            cwd=str(SRC), env=env,
            stdout=self._console_handle, stderr=subprocess.STDOUT,
        )

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("서버가 기동 중에 죽었다:\n" + self.stop())
            try:
                if httpx.get(f"{self.base}/api/health", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.25)
        raise AssertionError(f"{BOOT_TIMEOUT_S}초 안에 기동하지 못했다:\n" + self.stop())

    def console_size(self) -> int:
        """지금까지 자식이 콘솔에 쓴 **바이트** 수. 서버가 살아 있는 동안에도 볼 수 있다.

        문턱은 파이프 용량이고 그것은 바이트로 세는 수이므로 여기서도 바이트로 센다.
        디코딩된 문자 수로 재면 한글 한 자가 3바이트인 만큼 과녁이 흐려진다.
        """
        if self._output_bytes is not None:
            return self._output_bytes
        return os.fstat(self._console_handle.fileno()).st_size

    def stop(self) -> str:
        """서버를 세우고 출력 전문을 돌려준다. 두 번 불러도 같은 값이다."""
        if self._output is None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
            # 자식이 죽은 뒤에 읽는다 — 그래야 마지막 줄까지 파일에 닿아 있다.
            self._console_handle.flush()
            self._console_handle.seek(0)
            raw = self._console_handle.read()
            self._output_bytes = len(raw)
            self._output = raw.decode("utf-8", "replace")
            self._console_handle.close()
        return self._output


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """실기동 1회. 아래 검사들이 **같은 실행의 로그**를 나눠 본다."""
    root = tmp_path_factory.mktemp("log-hygiene")
    store_url = f"sqlite://{root / 'live.db'}"
    with create_store(store_url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)

    log_file = root / "observability.jsonl"
    server = _Server(store_url, log_file, root / "console.log")
    try:
        server.wait_until_ready()
        responses = _drive(server)
        console = server.stop()
    finally:
        server.stop()
    return {
        "responses": responses,
        "console": console,
        "log": log_file.read_text(encoding="utf-8") if log_file.exists() else "",
        "log_file": log_file,
    }


def _drive(server: _Server) -> dict:
    """정상 · 검증 실패 · 파싱 실패 · 자유 입력을 한 줄기로 친다."""
    out: dict[str, httpx.Response] = {}
    with httpx.Client(base_url=server.base, timeout=30.0) as client:
        out["analyze"] = client.post("/api/analyze", json=PROFILE)
        out["chat"] = client.post("/api/chat",
                                  json={"message": "전세와 월세 중 뭐가 나을까요",
                                        "profile": PROFILE})
        # 422 — 정수 칸에 문자열. 검증기가 값을 인용하면 여기서 잡힌다.
        out["unprocessable"] = client.post("/api/analyze", json={**PROFILE, "age": BAIT_STRING})
        # 422 — 범위 초과. 상한을 넘겨 [값이 얼마였는지] 를 말하고 싶어지는 자리다.
        out["out_of_range"] = client.post(
            "/api/analyze", json={**PROFILE, "householdSize": 91827364})
        # 422 — JSON 문법이 깨진 본문. 파서가 [어디가 틀렸는지] 를 말하려고 본문 조각을
        # 인용할 여지가 있다.
        out["malformed"] = client.post(
            "/api/analyze",
            content=f'{{"annualIncomeKRW": {PROFILE["annualIncomeKRW"]},,}}'.encode(),
            headers={"Content-Type": "application/json"},
        )
        # 400 — 유효한 UTF-8 이 아니라 본문을 읽지 못한다. 디코딩 오류는 실패한 바이트
        # 주변을 인용하는 것이 라이브러리들의 통상 동작이다.
        out["unparseable"] = client.post(
            "/api/analyze",
            content=(f'{{"annualIncomeKRW": {PROFILE["annualIncomeKRW"]}, "note": "'.encode()
                     + b"\xff\xfe" + b'"}'),
            headers={"Content-Type": "application/json"},
        )
        # 6-A 자유 입력 — 신고 사유가 로그에 새는지 (계약 결정 #38).
        login = client.post("/api/auth/login",
                            json={"username": "counselor", "password": COUNSELOR_PW})
        out["login"] = login
        if login.status_code == 200:
            csrf = login.json()["csrfToken"]
            out["report"] = client.post(
                "/api/reports",
                json={"targetKind": "policy", "targetId": "buttress_youth",
                      "targetField": "status", "reason": REPORT_REASON},
                headers={CSRF_HEADER_NAME: csrf},
            )
            # 400 — 없는 항목. 오류 문구가 입력값을 되비추는지.
            out["bad_target"] = client.post(
                "/api/reports",
                json={"targetKind": "policy", "targetId": "buttress_youth",
                      "targetField": BAIT_STRING, "reason": REPORT_REASON},
                headers={CSRF_HEADER_NAME: csrf},
            )
    return out


class TestALiveRunLeavesNoRequestBodyInAnyLog:
    def test_the_run_actually_exercised_the_paths(self, live):
        """★ 검사가 **무엇을 훑었는지** 먼저 고정한다. 아무것도 안 쳤으면 아래는 공허하다."""
        codes = {name: r.status_code for name, r in live["responses"].items()}
        assert codes["analyze"] == 200, codes
        assert codes["chat"] == 200, codes
        assert codes["unprocessable"] == 422, codes
        assert codes["out_of_range"] == 422, codes
        assert codes["malformed"] == 422, codes
        assert codes["unparseable"] == 400, codes
        assert codes["login"] == 200, codes
        assert codes["report"] == 200, codes
        assert codes["bad_target"] == 400, codes

    def test_the_log_file_was_actually_written(self, live):
        """빈 파일을 훑고 [샌 것 없음] 이라고 말하는 것을 막는다."""
        records = [json.loads(line) for line in live["log"].splitlines() if line.strip()]
        assert len(records) >= 8, f"실기동 요청 수보다 기록이 적다: {len(records)}"
        paths = {r.get("path") for r in records}
        assert {"/api/analyze", "/api/chat", "/api/reports"} <= paths, paths
        assert any(r.get("event") == "llm.chat" for r in records), "LLM 호출이 안 남았다"

    def test_no_profile_value_reaches_the_file_log(self, live):
        found = leaked(live["log"])
        assert not found, f"파일 로그에 요청 본문이 남았다 (SPEC 7.1): {found}"

    def test_no_profile_value_reaches_the_server_console(self, live):
        """★ **uvicorn 의 접근 로그와 트레이스백까지** 본다. 우리 코드만 보면 반쪽이다."""
        assert live["console"].strip(), "서버 출력이 비어 있다 — 이 검사가 아무것도 안 훑었다"
        found = leaked(live["console"])
        assert not found, f"서버 콘솔에 요청 본문이 남았다 (SPEC 7.1): {found}"

    def test_the_access_log_really_was_on(self, live):
        """`--log-level warning` 으로 낮춰 검사를 통과시키는 길을 막는다."""
        assert re.search(r'"(GET|POST) /api/\S+ HTTP/1\.1"', live["console"]), (
            "uvicorn 접근 로그가 출력에 없다 — 이 테스트가 그 경로를 훑지 못했다:\n"
            + live["console"][-2000:]
        )

    def test_the_error_responses_do_not_quote_the_input_either(self, live):
        """★ 422 는 [무엇이 틀렸는지] 를 말하려고 값을 인용하는 경향이 있다."""
        for name in ("unprocessable", "out_of_range", "malformed", "unparseable",
                     "bad_target"):
            body = live["responses"][name].text
            assert not leaked(body), f"{name} 응답이 입력값을 인용한다: {leaked(body)}"

    def test_the_free_text_report_reason_is_stored_but_not_logged(self, live):
        """★ 신고 사유는 **감사기록에는 남고**(SPEC 6.4) 파일 로그에는 안 남는다.

        둘은 다른 규칙이다. 6.4 가 「신고자·시각·대상·사유를 `AuditEvent` 로 남긴다」고
        요구했고, 7.1 이 금지한 것은 **파일 로그**다. 한쪽을 다른 쪽으로 읽으면 둘 중
        하나가 무너진다 — 여기서 그 경계를 함께 고정한다.
        """
        assert REPORT_REASON not in live["log"]
        assert REPORT_REASON not in live["console"]
        assert live["responses"]["report"].json()["reason"] == REPORT_REASON


# ==========================================================================
# 4. 실기동 500 — 오류 응답이 **클라이언트에 도달하고** 트레이스백에 본문이 없다
# ==========================================================================
#
# 7단계는 이 자리를 「검증하지 못한 것」으로 남겼다. 실기동에서 500 을 내면 요청이
# 멈췄기 때문이고, 그 멈춤의 원인은 **이 하네스가 서버 출력을 읽지 않는 PIPE 로 받는
# 것**이었다 (`_Server` 주석 참고). 원인이 없어졌으므로 그 검사를 여기서 마친다.
#
# ★ 이 검사는 두 가지를 **동시에** 붙든다. 하나로 줄이지 않는다 —
#
#   (1) SPEC 7.1 — 500 의 **콘솔 트레이스백**에 요청 본문이 없다. 7단계가 재려 했던 것.
#   (2) SPEC 6.2 「침묵 폴백 금지」의 서버 쪽 전제 — 500 이 났을 때 화면이 오류를 말할 수
#       있으려면 **응답이 실제로 도착해야 한다.** 응답이 멈추면 화면은 아무 말도 못 하고,
#       그러면 6.2 는 서버 사정으로 무력해진다. 그 전제를 여기서 기계로 붙든다.

#: 진짜 500 을 만드는 법 — **제품 코드를 건드리지 않는다.** 기동이 끝난 뒤 sqlite 파일을
#: 쓰레기로 덮는다. 요청마다 `store_from_env()` 로 새로 여므로 다음 요청이 터진다.
#: `analyze_endpoint` 는 `analyze()` 주변의 `ValueError` 만 잡으므로 이것은 **미처리
#: 예외**로 끝까지 올라간다 — `sqlite3.DatabaseError: file is not a database`.
#: 예외를 삼켜 500 을 없애는 것이 아니라, 진짜 500 을 내고 그 응답이 도착하는지를 본다.
_STORE_WRECKAGE = b"NOT-A-SQLITE-DATABASE" * 64

#: 용량을 잴 때 한 번에 쓰는 바이트. 막히면 절반씩 줄여 마지막 한 바이트까지 채운다.
_PROBE_CHUNK = 4096

#: 안전장치. 이만큼 넣어도 안 막히면 익명 파이프가 아닌 무언가를 재고 있는 것이다.
_PROBE_CEILING = 16 * 1024 * 1024


def _measure_pipe_capacity() -> int:
    """**이 플랫폼의** 익명 파이프가 읽는 쪽 없이 삼키는 바이트 수를 잰다.

    ★ 문턱을 상수로 박으면 그 상수를 관측한 플랫폼 밖에서 검사가 비어 버린다.
    윈도우는 4096, 리눅스는 65536 으로 **16배** 차이가 나므로 하나로 덮이지 않는다.
    `4096` 을 다른 상수로 바꾸는 것도 같은 결함을 다른 수로 옮기는 것일 뿐이다.
    그래서 재서 쓴다 — 파이프를 열고 쓰는 쪽을 논블로킹으로 바꾼 뒤 `BlockingIOError`
    가 날 때까지 채우면, 그때까지 들어간 바이트가 곧 그 플랫폼의 용량이다.

    `subprocess.PIPE` 와 같은 것을 재는가 — 그렇다. CPython 은 두 경로를 같은 기본
    크기로 만든다 (POSIX `pipe(2)` · 윈도우 `CreatePipe(..., 0)`).

    **못 재면 상수로 물러서지 않는다.** 호출자가 그것을 실패로 말해야 한다.
    """
    read_fd, write_fd = os.pipe()
    try:
        os.set_blocking(write_fd, False)
        filler = b"\0" * _PROBE_CHUNK
        written = 0
        chunk = _PROBE_CHUNK
        while chunk:
            try:
                written += os.write(write_fd, filler[:chunk])
            except BlockingIOError:
                chunk //= 2  # 막혔으면 남은 자리를 더 잘게 채워 마지막까지 본다
            if written > _PROBE_CEILING:
                raise AssertionError(
                    f"파이프가 {written} 바이트를 삼켜도 막히지 않는다 — "
                    "익명 파이프가 아닌 것을 재고 있다")
        return written
    finally:
        os.close(read_fd)
        os.close(write_fd)


try:
    PIPE_CAPACITY_BYTES: int | None = _measure_pipe_capacity()
    PIPE_CAPACITY_ERROR: str | None = None
except (OSError, AssertionError) as exc:  # 재지 못한 것을 조용히 덮지 않는다
    PIPE_CAPACITY_BYTES = None
    PIPE_CAPACITY_ERROR = f"{type(exc).__name__}: {exc}"

#: 500 을 몇 번까지 칠 것인가. 윈도우(4096)는 트레이스백 하나로 넘지만 리눅스(65536)는
#: 열몇 번이 필요하다. 상한은 무한 루프를 막는 자리지 과녁이 아니다 — 상한에 걸려 용량을
#: 못 넘기면 아래 검사가 그것을 **실패로 말한다.**
_MAX_FIVE_HUNDRED_REQUESTS = 60


@pytest.fixture(scope="module")
def live_five_hundred(tmp_path_factory):
    """실기동 1회. 정상 요청 하나로 대조군을 잡고, 그 뒤 진짜 500 을 만든다.

    500 을 **한 번이 아니라 이 플랫폼의 파이프 용량을 넘길 때까지** 친다. 옛 미배수
    하네스가 멈추려면 서버 출력이 그 용량을 넘겨야 하고, 넘기지 못하면 이 회귀 테스트는
    [무조건 통과하는 검사] 가 되기 때문이다 — 윈도우는 한 번이면 넘고 리눅스는 아니다.
    """
    root = tmp_path_factory.mktemp("log-hygiene-500")
    db = root / "live.db"
    store_url = f"sqlite://{db}"
    with create_store(store_url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)

    log_file = root / "observability.jsonl"
    server = _Server(store_url, log_file, root / "console.log")
    healthy = broken = None
    failure: Exception | None = None
    attempts = 0
    try:
        server.wait_until_ready()
        # ★ keep-alive 를 끈다. uvicorn 은 **미처리 예외로 500 을 낸 뒤 연결을 닫는다** —
        #   그러면 다음 요청이 풀에 남은 죽은 연결을 재사용해 `ReadError` 로 깨진다.
        #   실측(리눅스·6회): keep-alive 켜면 `500 · ReadError` 가 번갈아 나오고,
        #   끄면 여섯 번 다 500 이 온다. 그 `ReadError` 는 우리가 잡으려는 멈춤이 아니라
        #   연결 재사용 사고이므로, 켜 둔 채로는 아래 [응답이 도달했는가] 가 헛짚는다.
        limits = httpx.Limits(max_keepalive_connections=0)
        with httpx.Client(base_url=server.base, timeout=15.0, limits=limits) as client:
            # 대조군 — 저장소가 성한 동안은 같은 본문으로 200 이 나온다.
            healthy = client.post("/api/analyze", json=PROFILE)
            db.write_bytes(_STORE_WRECKAGE)
            for _ in range(_MAX_FIVE_HUNDRED_REQUESTS):
                attempts += 1
                try:
                    response = client.post("/api/analyze", json=PROFILE)
                except httpx.HTTPError as exc:
                    # 멈추면 여기로 온다 (ReadTimeout). 검사가 그것을 보고 실패해야
                    # 하므로 예외를 들고만 있는다 — 여기서 터뜨리면 실패 문구가
                    # 픽스처 쪽에 남는다.
                    failure = exc
                    break
                if broken is None:
                    broken = response  # 응답 검사는 **첫** 500 으로 한다
                # 용량을 못 쟀으면 더 쳐도 기준이 없다. 그 사실은 아래 검사가 말한다.
                if PIPE_CAPACITY_BYTES is None:
                    break
                if server.console_size() > PIPE_CAPACITY_BYTES:
                    break
        console = server.stop()
    finally:
        server.stop()
    return {
        "healthy": healthy,
        "broken": broken,
        "failure": failure,
        "console": console,
        "console_bytes": server.console_size(),
        "five_hundreds": attempts,
        "log": log_file.read_text(encoding="utf-8") if log_file.exists() else "",
    }


class TestALiveFiveHundredReachesTheClient:
    def test_the_control_request_succeeded_before_the_store_was_wrecked(
            self, live_five_hundred):
        """★ 대조군을 먼저 고정한다. 200 도 못 냈다면 아래 500 은 다른 것을 재고 있다."""
        healthy = live_five_hundred["healthy"]
        assert healthy is not None and healthy.status_code == 200, (
            f"저장소가 성한데도 200 이 안 나왔다: {healthy}")

    def test_the_client_actually_receives_the_error_response(self, live_five_hundred):
        """★ **이 파일의 과녁.** 500 이 났을 때 클라이언트가 응답을 받는다.

        받지 못하면 화면은 오류를 말할 수 없고, SPEC 6.2 「침묵 폴백 금지」가 서버
        사정으로 무력해진다 — 무대에서는 오류 화면이 아니라 **멈춤**으로 보인다.
        """
        failure = live_five_hundred["failure"]
        assert failure is None, (
            "진짜 500 에서 응답이 클라이언트에 도달하지 않았다 "
            f"({type(failure).__name__}: {failure}). "
            "서버 출력을 읽지 않는 파이프에 로그가 막혀 이벤트 루프가 멈추면 이렇게 된다 "
            "— `_Server` 주석 참고.\n" + live_five_hundred["console"][-2000:])
        broken = live_five_hundred["broken"]
        assert broken.status_code == 500, broken.text
        # 오류 봉투도 계약이다 (SPEC 8.1). 멈춤은 봉투가 없는 것과 같다.
        assert broken.json()["error"]["code"] == "internal_error", broken.text

    def test_it_really_was_an_unhandled_exception(self, live_five_hundred):
        """★ 500 을 **반환한 것**과 예외가 **끝까지 올라간 것**은 다르다.

        여기서 재려는 것은 후자다 — 콘솔 트레이스백은 후자에서만 나온다. 앞의 것으로
        바꿔치기하면 (1) 의 과녁이 사라진다.
        """
        console = live_five_hundred["console"]
        assert "Traceback (most recent call last)" in console, (
            "미처리 예외의 트레이스백이 콘솔에 없다 — 이 검사가 훑을 것이 없다:\n"
            + console[-2000:])
        assert "DatabaseError" in console, console[-2000:]

    def test_this_platforms_pipe_capacity_was_actually_measured(self):
        """★ 문턱을 **재지 못했으면 상수로 물러서지 않는다.**

        물러서는 순간 그 상수를 관측한 플랫폼 밖에서 이 검사가 비어 버린다. 문턱 없이
        통과하는 검사는 없는 검사와 같고, 없는 검사는 실패하지 않는다.
        """
        assert PIPE_CAPACITY_ERROR is None, (
            f"이 플랫폼({sys.platform})의 파이프 용량을 재지 못했다: {PIPE_CAPACITY_ERROR}. "
            "재지 못했으면 아래 문턱 검사는 기준이 없다 — 옛 상수(4096)로 물러서면 "
            "그 상수를 관측한 윈도우 밖에서 이 검사가 아무것도 잡지 못한다")
        assert PIPE_CAPACITY_BYTES and PIPE_CAPACITY_BYTES > 0, PIPE_CAPACITY_BYTES

    def test_the_output_still_crosses_this_platforms_pipe_capacity(self, live_five_hundred):
        """★ 이 검사가 **스스로 과녁을 치우지 않았는지** 본다 — 문턱은 플랫폼에서 유도한다.

        옛 미배수 하네스가 멈추려면 서버 출력이 **이 플랫폼의** 파이프 용량을 넘겨야
        한다. 넘기지 못하면 옛 하네스로도 초록이 나오므로 이 검사는 회귀를 막지 못한다.

        그때 **skip 하지 않는다.** skip 은 침묵 폴백이고, [이 플랫폼에서는 이 검사가
        의미 없다] 는 말해져야 하는 사실이다 (계약 결정 #36 조건 ② 와 같은 규율).
        """
        assert PIPE_CAPACITY_BYTES is not None, (
            f"파이프 용량을 재지 못해 문턱이 없다: {PIPE_CAPACITY_ERROR}")
        size = live_five_hundred["console_bytes"]
        assert size > PIPE_CAPACITY_BYTES, (
            f"이 플랫폼({sys.platform})에서는 이 검사가 의미 없다 — "
            f"파이프 용량이 {PIPE_CAPACITY_BYTES} 바이트인데, 실기동 500 을 "
            f"{live_five_hundred['five_hundreds']}번 쳐서 나온 서버 출력이 {size} 바이트뿐이다. "
            "옛 미배수 하네스라도 이 크기로는 버퍼를 채우지 못하므로 멈춤 회귀를 잡지 못한다. "
            f"상한({_MAX_FIVE_HUNDRED_REQUESTS})을 올리거나 500 이 실제로 나고 있는지 봐라")

    def test_the_five_hundred_traceback_carries_no_profile_value(self, live_five_hundred):
        """SPEC 7.1 「오류 로그도 예외가 아니다」 — 7단계가 관측하지 못한 자리."""
        found = leaked(live_five_hundred["console"])
        assert not found, f"500 의 콘솔 출력에 요청 본문이 남았다 (SPEC 7.1): {found}"

    def test_the_error_envelope_does_not_quote_the_input(self, live_five_hundred):
        assert not leaked(live_five_hundred["broken"].text), \
            live_five_hundred["broken"].text

    def test_the_file_log_recorded_the_five_hundred_with_only_the_type(
            self, live_five_hundred):
        """500 이 기록에서 빠지면 [오류만 안 남는 로그] 가 된다 (`_observe_request`)."""
        records = [json.loads(line) for line
                   in live_five_hundred["log"].splitlines() if line.strip()]
        five_hundreds = [r for r in records if r.get("status") == 500]
        assert five_hundreds, f"500 이 파일 로그에 안 남았다: {records}"
        assert five_hundreds[0]["error"] == "DatabaseError", five_hundreds[0]
        assert five_hundreds[0]["path"] == "/api/analyze", five_hundreds[0]
        assert not leaked(live_five_hundred["log"]), leaked(live_five_hundred["log"])

