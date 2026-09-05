# 무료 PC 배포 운영

사용자가 심사 기간 동안 PC를 켜 두기로 하여, 서버 임대 없이 Windows PC에서 운영한다.
Python/FastAPI 서버는 로컬 루프백에만 바인딩하고 Tailscale Funnel이 고정 HTTPS 주소로 연결한다.
Tailscale Funnel은 무료 Personal 요금제에도 제공된다. OpenAI API 이용료는 별도다.

공식 안내: <https://tailscale.com/docs/features/tailscale-funnel>

## 실행 구성

- `output/pc-host/release/`: 검증한 Git 커밋의 운영 복사본.
- `output/pc-host/runtime.local.json`: 모델·API 키·두 심사 계정 비밀번호. Git 및 제출 ZIP 제외.
- `output/pc-host/data/`: 영구 SQLite, 시간별 백업, 관측 기록.
- `output/pc-host/supervisor.py`: 단일 감독 프로세스. 운영 환경과 시드를 검증하고 단일 Uvicorn 서버를 실행한다.
- `HomeCompass-Submission-Watchdog`: Windows 로그인 시 감독 프로세스를 실행한다. 분 단위 트리거와 중복 실행 방지로 감독 프로세스 중단도 복구한다.
- `127.0.0.1:18174`: 서버 포트. Funnel 외에 LAN/인터넷으로 직접 노출하지 않는다.

Funnel은 다음과 같이 영구 백그라운드 모드로 연결한다. 계정의 최초 Funnel 사용 권한은 사용자가 승인했다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel --bg http://127.0.0.1:18174
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

실제 주소는 제출용 로컬 문서 `output/submission/FINAL_STATUS.md`에 보관한다.

## 검증

```powershell
python scripts/submission_preflight.py --strict --url https://실제주소
Get-ScheduledTask -TaskName HomeCompass-Submission-Watchdog
Invoke-RestMethod http://127.0.0.1:18174/api/health
```

`submission_preflight.py`의 배포 구성 검사는 저장소의 Render 대안 설정을 검사한다.
실제 PC 환경은 `output/pc-host/local-verification.json`과 `public-accounts-verification.json`으로 별도 검증했다.
공개 주소로 로그인한 뒤 후속 요청에 Secure 쿠키가 전송되고 역할이 유지되는지도 확인했다.

외부 네트워크 검사는 GitHub Actions의 **Public deployment check**를 수동 실행하고 실제 HTTPS 주소를 입력한다.
이 검사는 로그인 정보나 LLM API 키가 필요 없고, LLM을 호출하지 않는다. 주소와 호스트명은 실행 로그에서 마스킹한다.

### 가용 시간 자동 감시 — Secret 하나로 켠다

같은 워크플로가 **20분마다 예약 실행**된다. 저장소 Settings → Secrets and variables →
Actions 에 `PUBLIC_URL` 을 실제 HTTPS 주소로 넣으면 켜진다. 넣지 않으면 예약 실행은
아무것도 하지 않고 지나간다.

필수 가용 시간(09-07 11:00 ~ 09-11 23:59 KST) **밖에서는 건너뛴다.** 창 밖의 실패는
결격과 무관하고, 그것으로 알림을 울리면 진짜 신호가 묻히기 때문이다.

검사가 실패하면 GitHub 이 저장소 소유자에게 워크플로 실패 알림을 보낸다. 그것이
**PC가 죽은 것을 늦게 아는 일**을 막는 장치다.

> ⚠️ **보증이 아니라 안전망이다.** GitHub 예약 실행은 best-effort 라 지연되거나
> 건너뛸 수 있다. 사람이 하루 두 번 직접 여는 것을 대체하지 않는다.

### 재부팅 뒤 스스로 돌아오게 하려면

Watchdog 작업의 Principal 이 `Interactive` 라 **Windows 에 로그인한 상태에서만** 복구된다.
정전이나 강제 재시작 뒤 PC가 켜져도 로그인 화면에 멈춰 있으면 그 시점부터 결격이다.

심사 기간 동안만 자동 로그인을 켜 두면 그 구멍이 닫힌다 (`netplwiz` → 비밀번호 입력
해제). **물리적 접근이 있는 사람이 PC를 쓸 수 있게 되므로** 그 대가를 감수할지는
운영자가 판단한다. 09-12 이후 되돌린다.

확인해 둘 것 (2026-09-05 실측):

```powershell
# Windows Update 가 창 안에서 재시작하지 않는가 — 일시중지 만료일을 본다
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings' |
  Select-Object PauseUpdatesExpiryTime

# AC 전원에서 절전으로 내려가지 않는가 — 색인이 0 이어야 한다
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
```

## 심사 기간

필수 가용 시간은 **2026-09-07 11:00 ~ 2026-09-11 23:59 KST**다.
09-12 00:10까지 PC 전원·인터넷·Windows 로그인·Tailscale을 유지한다.
화면을 잠그는 것은 가능하지만 로그아웃·절전·재부팅은 중단을 일으킬 수 있다.
현재 권한 구성에서는 재부팅 후 Windows에 로그인해야 앱이 다시 시작된다.

09-07 10:30 이후 운영 복사본, 비밀 설정, Tailscale 장치 이름·계정, Python 가상 환경을 바꾸지 않는다.
상태와 복구 이력은 `output/pc-host/supervisor.jsonl`에서 확인한다.
자동 복구와 백업은 실제 검증했지만 정전·인터넷 장애와 같은 미래 가용성을 보장하지는 않는다.
