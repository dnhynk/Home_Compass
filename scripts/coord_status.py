#!/usr/bin/env python3
"""코디네이터 상태판 — Orca 조율 상태 + GitHub PR + CI 를 한 화면에 모은다.

  python scripts/coord_status.py

왜 필요한가. 코디네이터는 세 곳을 동시에 봐야 한다 — Orca 의 task/dispatch,
GitHub 의 PR/CI, 그리고 SPEC Part 10 의 단계 순서. 셋을 손으로 대조하면
"머지해도 되는가" 판단이 매번 즉흥이 되고, 즉흥은 SPEC Part 0-A 가 기록한
실패 유형(경계 조건 미합의)을 코디네이터 쪽에서 재현한다.

이 스크립트는 판단하지 않는다. **판단 재료를 빠짐없이 모으고, 자동으로 확인할 수
있는 것만 자동으로 확인한다.** 머지 결정은 사람(또는 코디네이터 에이전트)이 한다.

자동으로 확인하는 것:
  - CI 결과 (SPEC D-10 — 워커의 자기보고가 아니라 이것이 근거다)
  - **소유 경로 준수** (SPEC 9.4) — PR 이 남의 경로를 건드렸는지
  - 계약 파일 변경 여부 (SPEC 8.2 #5 — 코디네이터만 바꾼다)

확인하지 않는 것 (사람이 PR 본문을 읽어야 한다):
  - SPEC 9.3 완료 판정 6항목의 답이 실제로 적혀 있는지
  - 값을 지어내지 않았는지
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 이 파일만 `spec_from_file_location` 으로도 적재된다 (test_coord_ownership_gate 가 소유
# 경로 분류기를 직접 부른다). 그 적재 경로는 `scripts/` 를 sys.path 에 넣어주지 않으므로
# — 서브프로세스 실행과 달리 — 옆 모듈을 직접 찾아준다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _console import force_utf8_stdout  # noqa: E402

REPO = "dnhynk/Home_Compass"

# --- SPEC 9.4 소유 경로 배정표의 기계 판독본 -------------------------------
# SPEC 이 정본이다. 이 표는 거울이며, 어긋나면 SPEC 을 따른다.
#
# ★★ **테스트도 여기 적는다** (2026-08-16 · `task_0974dc98c7c7`).
#   SPEC 9.4 는 「테스트는 대상 코드의 소유자가 **함께 소유**한다」고 적는데 이 표가 그
#   조항을 통째로 빠뜨리고 있었다. 그래서 워커를 회수할 때마다 테스트 디렉터리가
#   무주공산이 되고 다음 워커에게 **매번 손으로 다시 적어 왔다.**
#
#   ★ **고치기 전에 쟀다** (과업이 요구한 순서). 결과가 과업의 전제를 뒤집었다 —
#     `OWNERSHIP` 을 읽는 곳은 **두 자리뿐**이다: 아래 `WORKER_PATHS["Coordinator"]` 의
#     `OWNERSHIP["coordinator"]` 와, 교차 테스트의 `COORDINATOR_ONLY` 대조.
#     즉 **`coordinator` 이외 항목은 게이트에 한 글자도 들어가지 않는다.**
#     `store` 에 테스트 경로를 더해도 `owner_guess` 도 `violations()` 도 안 움직인다.
#     과업이 「넓히면 `owner_guess` 가 움직인다」고 걱정한 것은 **사실이 아니었고**,
#     자동 판정 네 번의 실패(PR #75 · #83)는 `WORKER_PATHS` 쪽 이야기다.
#
#   그래서 이 표는 **계기가 아니라 거울**이고, 거울이 조항 하나를 빠뜨리면 그것을 보고
#   배정을 쓰는 사람이 매번 같은 것을 빠뜨린다. 실제로 그렇게 됐다.
#   **새 배정을 쓸 때 여기서 베껴 간다.**
OWNERSHIP: dict[str, list[str]] = {
    "engines": ["backend/src/home_compass/engines/", "backend/src/home_compass/common.py",
                # 최상위 테스트 중 **엔진 거동을 재는 것**. 디렉터리가 없어 파일로 적는다 —
                # `backend/tests/` 를 통째로 주면 #57 이 재현된다(`W-engines` 가
                # `W-harness` 의 PR 을 삼켰다).
                "backend/tests/test_engines.py",
                "backend/tests/test_engine_constants.py",
                "backend/tests/test_hug_guarantee.py",
                "backend/tests/test_schwabe_and_recommendation.py",
                "backend/tests/test_clock_injection.py",
                "backend/tests/test_sensitivity.py",
                "backend/tests/test_golden_snapshot.py",
                "backend/tests/test_format_golden.py"],
    "api": ["backend/src/home_compass/main.py", "backend/src/home_compass/config.py",
            # 인증은 api 의 책임이다 (SPEC 1.1). main.py 에 400줄을 더 얹지 않으려고
            # 파일로 나눈 것이며 새 컴포넌트가 아니다. 모듈·패키지 두 형태를 다 잡는다.
            "backend/src/home_compass/auth.py", "backend/src/home_compass/auth/",
            "backend/tests/api/"],
    "store": ["backend/src/home_compass/store/", "backend/src/home_compass/data/",
              "backend/tests/store/"],
    "ingest": ["backend/src/home_compass/ingest/", "backend/tests/ingest/"],
    "llm": ["backend/src/home_compass/llm/", "backend/tests/llm/"],
    "web": ["frontend/",
            # 생성물이 손으로 쓴 사본으로 되돌아가지 않는지 재는 것들. 대상은 `frontend/` 다.
            "backend/tests/test_frontend_format_golden_js.py",
            "backend/tests/test_frontend_local_engine_equivalence.py",
            "backend/tests/test_frontend_no_handwritten_constants.py"],
    "admin": ["admin/"],
    "coordinator": ["contracts/", "scripts/", "docs/engineering/SPEC.md",
                    ".github/", ".githooks/", ".gitattributes",
                    "backend/tests/crosscheck/",
                    # ★ **컴포넌트 간 공용 유틸.** SPEC 9.4 의 컴포넌트 표에 이 부류의 행이
                    #   **없다.** `home_compass/_console.py` 는 `ingest` 와 `store` 가 함께
                    #   쓰고(진입점의 출력 인코딩 가드) 어느 쪽 것도 아니다 — `store` 가
                    #   `ingest` 를 import 할 수 없어서 뿌리로 올린 파일이다(#122).
                    #   주인을 안 적으면 **다음 회수 때 무주공산이 되고**, 그것이 방금
                    #   `task_0974dc98c7c7` 로 고친 부류다. 그래서 공용 테스트 하네스와
                    #   같은 논리로 코디네이터가 진다.
                    #   ★ 다만 이것은 **SPEC 을 늘린 것이 아니라 빈칸을 코디네이터 판단으로
                    #     메운 것**이다. 같은 부류가 또 생기면 SPEC 9.4 에 행을 만든다.
                    "backend/src/home_compass/_console.py",
                    # ★ **발표 자료는 생성기 + 생성물이다** (2026-08-16 · 항구 배정).
                    #   `build_ppt.py` 는 `scripts/gen_contracts.py` 와 같은 부류의 생성기이고
                    #   `.pptx` 는 SPEC 9.4 의 [모든 생성물] 행이다. 지금까지 **어느 표에도
                    #   없었고**, 그래서 PR #76 이 생성기 22곳을 고치고도 **생성물을 다시
                    #   뽑지 않은 것을 아무도 못 잡았다** — 커밋된 제출물에 옛 거짓이 그대로
                    #   남아 있었다. `frontend/generated/` 가 바이트 비교로 막는 바로 그 사고다.
                    "docs/competition/",
                    # ★ **공용 하네스.** 어느 컴포넌트의 테스트도 아니고 **모든 컴포넌트의
                    #   테스트가 import 한다.** 한 워커가 여기를 고치면 남의 테스트가 갈리므로
                    #   교차 테스트와 같은 부류다 (SPEC 9.4 — 교차 테스트는 코디네이터 소유).
                    "backend/tests/conftest.py", "backend/tests/decision_inputs.py",
                    "backend/tests/seed_constants.py", "backend/tests/snapshot_util.py",
                    "backend/tests/js_runner.py", "backend/tests/sensitivity.py",
                    # ★ **생성물.** SPEC 9.4 의 [모든 생성물] 행이다.
                    #   과업이 「재생성은 시드를 바꾼 워커가 하는데 소유는 코디네이터라 모순」
                    #   이라고 적었는데 **모순이 아니다** — `contracts/` 와
                    #   `frontend/generated/` 가 이미 같은 모양이고, 규율은 불변조건 11 이
                    #   적어 두었다(재생성은 시드된 저장소 안에서만). 워커는 요청하고
                    #   코디네이터가 재생성한다.
                    "backend/tests/golden/", "backend/tests/artifacts/"],
}

# 워커별 허용 경로 — **지금 배정된 것만.** 테스트는 대상 코드의 소유자가 함께 소유한다 (SPEC 9.4).
#
# ★★ **이 표는 기록이 아니라 계기다. 과업이 끝나면 항목을 지운다.**
#
#   `owner_guess` 는 선언 순서로 첫 일치를 돌려주고 위임 판정은 그 하나로 한다. 그래서
#   **끝난 배정이 넓으면 살아 있는 위임을 가리고**, 그 워커의 PR 이
#   「코디네이터 전용 경로 변경」 오탐으로 떨어진다. **두 번 물렸다** —
#   `W-platform` 이 `W-500-hang`(PR #81)을, `W-admin` 이 `W-health`(PR #85)를 가로챘다.
#
#   자동 판정은 네 번 시도해 네 번 실패했다 (좁은 일치 2회 · 합성 PR 불변식 · 표 불변식.
#   경위는 PR #75 · #83 본문). **경로만으로는 「의도된 소유자」를 알 수 없다** — 그것은
#   표에 적혀 있지 않다. 표를 짧게 유지하는 것이 유일한 방어다.
#
#   지운 항목의 기록은 git 과 각 PR 본문에 있다. 컴포넌트 소유는 위 `OWNERSHIP` 이 진다 —
#   **그쪽이 SPEC 9.4 의 거울이고 여기는 그때그때의 배정이다.**
WORKER_PATHS: dict[str, list[str]] = {
    # 코디네이터 자신. 이 항목이 없으면 코디네이터 PR 이 항상 '불명'으로 떨어지고,
    # 그러면 게이트가 매번 빨간불이라 아무도 보지 않게 된다 — 경보 피로가 곧 게이트 실패다.
    # ★ docs/engineering/ 를 통째로 주면 안 된다. diligence/ 를 삼켜서 리서처가 SPEC.md 를
    #   건드려도 '코디네이터 PR' 로 통과한다. 파일 단위로만 더한다 (아래 회귀 테스트가 막는다).
    # ★ `frontend/generated/` 는 SPEC 9.4 의 [모든 생성물] 행이다 — web 소유에서 제외돼 있다.
    # ★ `README.md` · `REHEARSAL.md` 는 SPEC 9.4 배정표에 **없던 경로**다. 저장소 정문과
    #   시연 대본이고 컴포넌트가 아니라 `COORDINATION.md` · `HANDOFF.md` 와 같은 부류이므로
    #   코디네이터가 진다. 리허설 과업이 살아 있는 동안만 그 워커에게 함께 준다.
    # ★★ **워커를 회수할 때 그 워커만 갖고 있던 경로가 무주공산이 되는지 본다.**
    #   두 번 물렸다 — `README.md`(#87 이 막힘) · `REHEARSAL.md`(#95 가 막힘).
    #   둘 다 「등재 PR 을 먼저」 규칙으로 풀렸지만, 애초에 회수 시점에 봤으면 없었을 왕복이다.
    # ★ `admin/` 은 **이 세션에서 두 번 들었다 두 번 뺐다** (#101→#103 · #108→여기).
    #   두 번 다 코디네이터가 그 화면을 직접 고치는 동안만 들었고 끝나자마자 뺐다.
    #   **왜 남기지 않는가 — 라벨이 틀리는 것보다 나쁜 일이 있다.** 미래의 admin 워커 PR 이
    #   `admin/` 과 `contracts/` 를 함께 담으면 `owner_guess` 가 선언 순서로 Coordinator 를
    #   돌려주고, Coordinator 는 `CONTRACT_DELEGATED` 에 있으므로 `violations()` 가
    #   **계약 변경을 못 잡는다.** SPEC 8.2 #5 게이트가 조용히 열리는 경로다.
    #   ★ 그 대가로 **등재 PR 왕복**이 생긴다. 두 규율이 같은 경로에서 당기는 이 자리가
    #     `task_0974dc98c7c7` 이며, 이 세션이 그 증거를 두 번 만들었다.
    "Coordinator": OWNERSHIP["coordinator"] + [
        "docs/engineering/COORDINATION.md", "docs/engineering/HANDOFF.md",
        "docs/engineering/REHEARSAL.md",
        "README.md", "frontend/generated/", ".gitattributes", ".gitignore",
        # --- 임시 등재 (제출 배포 파동 · run_b70307c8c66d) — **끝나면 뺀다** ------
        # 공개 배포 경로는 한 컴포넌트 안에 없다. 쿠키 Secure 경계는 `api`(auth·main),
        # 컨테이너 정의는 무주공산, 축 겹침 수정은 `web` 이다. 배포는 이 셋이 **함께**
        # 맞아야 성립하므로 컴포넌트별로 쪼개면 어느 PR 도 단독으로 검증되지 않는다.
        # 그래서 코디네이터가 한 번에 들고 간다 — 이 세션이 네 번 하고 네 번 뺀 그 패턴이다.
        #
        # ★ **회수 시점: 배포 URL 이 확정되고 T1 이 닫힌 직후.** 남겨 두면 미래의 admin·web
        #   워커 PR 이 이 경로들과 겹칠 때 `owner_guess` 가 선언 순서로 Coordinator 를
        #   돌려주고, Coordinator 는 `CONTRACT_DELEGATED` 에 있으므로 `violations()` 가
        #   **계약 변경을 못 잡는다.** SPEC 8.2 #5 게이트가 조용히 열린다.
        "Dockerfile", ".dockerignore", "render.yaml", ".env.example",
        "backend/src/home_compass/auth.py", "backend/src/home_compass/main.py",
        "backend/tests/api/test_auth.py", "frontend/styles.css",
    ],
    # --- 백로그 마감 파동 (2026-08-16) — **전부 회수했다** -------------------
    #
    # `W-store3`(#114) · `W-pipe`(#121) · `W-small`(#113·#115·#118) 셋 다 과업이 닫혔다.
    # 코디네이터가 임시로 들었던 셋(`store/__main__.py` · `_console.py` 둘)도 #122 가
    # 머지되어 뺐다. `home_compass/_console.py` 만 위 `OWNERSHIP["coordinator"]` 로
    # **항구 배정**했다 — 회수하면 무주공산이 되는 자리라 그렇게 두지 않았다.
    #
    # ★ **배정이 Coordinator 하나뿐인 것이 정상 상태다.** 워커가 없으면 표도 비어 있어야
    #   한다. 다음 워커를 띄우는 사람이 등재 PR 을 먼저 낸다.
    #
    # --- 제출 UI 파동 (run_b70307c8c66d) — **과업이 닫히면 지운다** -------------
    #
    # ui-skills 감사 기반 정밀 수정. 두 화면은 경로가 갈려 있어 서로 충돌하지 않는다.
    "W-web-ui": OWNERSHIP["web"],
    # ★ `test_admin_screen.py` 하나만 더 준다. 이 워커가 화면에 `DRAFT_STATUS_LABEL`
    #   손사본을 만들기 때문이며, **손사본은 파수병 없이 두지 않는다** — 같은 파일 ③ 절이
    #   `REJECTION_LABEL` 에 대해 이미 그 형태를 세워 두었다(`label_table_drift` + 프로브 셋).
    #   `backend/tests/api/` 를 통째로 주면 인증·헬스 테스트까지 삼켜 `api` 배정과 겹친다.
    "W-admin-ui": OWNERSHIP["admin"] + ["backend/tests/api/test_admin_screen.py"],
}

# 코디네이터만 바꿀 수 있는 것 (SPEC 8.2 #5). 워커 PR 에 이게 있으면 즉시 반려.
COORDINATOR_ONLY = ("contracts/", "backend/tests/crosscheck/", "docs/engineering/SPEC.md")

# 위 금지의 예외 — 코디네이터가 **과업 단위로** 계약 경로를 위임한 워커.
# 위임 사유는 각 항목의 WORKER_PATHS 주석에 있다. 게이트는 경로만 보므로,
# 위임 범위 밖의 변경은 코디네이터가 diff 를 읽어 반려한다.
#
# ★ **과업이 끝나면 뺀다.** 끝난 일회성 권한이 살아 있는 표에 남으면 그게 먼저 썩는다.
#   WORKER_PATHS 의 항목은 배정 기록이라 남기지만, **권한을 주는 것은 이 목록**이다.
#   뺀 것: W-platform(Wave 2·배정까지 삭제) · W-concurrency(#58) · W-genweb(#59) ·
#          W-admin(#65) · W-web(#67) · W-market-2(#68) · W-api-d13(#74) · W-report(#77) ·
#          W-observability(#79) · W-500-hang(#81) · W-health(#85) · W-rehearsal(#90) ·
#          W-seedfixture(#94).
#   **끝난 위임이 쌓여 PR #81 을 가로챘다** — 그 뒤 전수 회수했고 계속 그렇게 한다.
#          W-seedfixture(#94) · W-pipe(#121 · crosscheck 파일 하나짜리 위임이었다).
CONTRACT_DELEGATED = ("Coordinator",)

# --- SPEC Part 10 실행 순서의 거울 ------------------------------------------
WAVES: list[dict] = [
    {
        "wave": 1,
        "done": True,
        "label": "0단계 저장소 ∥ 1-① 엔진 구조 ∥ 실사",
        "spec": "Part 10 — 0단계와 1-①은 병렬이 명시적으로 허용된 유일한 조합",
        "workers": ["W-store", "W-engines", "W-research"],
    },
    {
        "wave": 2,
        "done": True,
        "label": "W-platform — 계약 생성기 · 부팅 전수검증 · 교차 테스트",
        "spec": "0단계·1-① 완료 기준(10.2)을 닫는다. Wave 1 전부 머지 후 착수",
        "workers": ["W-platform"],
        "needs": [1],
    },
    {
        "wave": 3,
        "done": True,
        "label": "2단계 정책 추출 파이프라인 (본선의 기술적 중심)",
        # 착수를 막던 사용자 결정 둘은 닫혔다 — 수집 대상은 SOURCES.md 로 확정(확보 8 ·
        # 적재 7 · 미특정 2)됐고, 원문 크기 상한은 실측(최대 12,248 · 합계 56,758 코드포인트)
        # 으로 확정돼 분할 설계가 불필요해졌다. **닫힌 표시는 지운다** — 늘 켜져 있는
        # 경고는 정보가 아니고, 이 프로젝트가 이상치 표시에서 같은 것을 이미 겪었다.
        "spec": "Part 10 — 0 선행. 수집 대상·원문 크기 상한 확정됨 (SPEC 잔여 실사 C)",
        "workers": ["W-ingest-policy"],
        "needs": [2],
    },
    {
        "wave": 4,
        "done": True,
        "label": "3단계 시세 파이프라인 · 4단계 인증·권한",
        "spec": "Part 10 — 둘 다 0 선행. 소유 경로가 분리되어 병렬 가능",
        "workers": ["W-ingest-market", "W-auth"],
        "needs": [2],
    },
    {
        "wave": 5,
        "label": "5·6단계 선행 정리 — 감도분석 하네스 · 벽시계 · 4.6 동시성 · D-11 생성 파이프라인",
        "spec": "단계가 아니라 부채다. 5단계가 들어오기 전에 닫는 편이 싸다",
        "workers": ["W-harness", "W-concurrency", "W-genweb", "W-research"],
        "needs": [4],
    },
    {
        "wave": 6,
        "label": "5단계 규칙 관리 화면 · 6단계 판정 화면 확장",
        "spec": "Part 10 — 5는 2·4 선행, 6은 1-③·4 선행. 6은 W-genweb 의 생성물이 선행",
        "workers": ["W-admin", "W-web"],
        "needs": [5],
    },
    {
        "wave": 7,
        "label": "6-A 이상 신고 · 7단계 감사·관측 · 8단계 시연 리허설",
        "spec": "Part 10 — 8단계는 전체 선행. 3회 재현 + 네트워크 차단",
        "workers": ["W-report", "W-observability", "W-rehearsal"],
        "needs": [6],
    },
]


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_json(cmd: list[str]):
    code, out = run(cmd)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


@dataclass
class PR:
    number: int
    title: str
    head: str
    draft: bool
    mergeable: str
    files: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    @property
    def covering_workers(self) -> list[str]:
        """이 PR 의 파일을 **전부** 담을 수 있는 배정 전부. 여럿이면 귀속이 애매한 것이다."""
        if not self.files:
            return []
        return [w for w, prefixes in WORKER_PATHS.items()
                if all(any(f.startswith(p) for p in prefixes) for f in self.files)]

    @property
    def owner_guess(self) -> str | None:
        """담을 수 있는 배정 중 **선언 순서로 첫 번째.** 여럿일 수 있다 — `covering_workers` 참조.

        ★ **자동으로 [가장 좁은 것] 을 고르려다 두 번 실패하고 되돌렸다** (PR #75 경위).
        배정이 겹치면 이 값이 실제 작성자와 다를 수 있다 — `backend/tests/` 만 건드린
        `W-harness` 의 PR(#57)이 `W-engines` 로 나온다. **위반 판정은 정확하고 틀리는 것은
        라벨뿐이다.**

        고치려고 [접두사 개수·길이가 작은 쪽] 을 골라 봤더니 —
          1차: 위임 판정까지 `covering` 으로 바꿨다가 **끝난 위임이 다른 워커의 살아 있는
               위임 덕분에 통과**하는 것을 만들었다
          2차: 되돌리고 좁은 일치만 남겼더니 **코디네이터 PR 이 `W-genweb`(위임 종료)으로
               귀속돼 자기 게이트에 걸렸다.** 부분집합 예외를 넣었으나 `W-platform` 이
               `api` 경로를 갖고 있어 안 먹었다

        **접두사의 개수와 길이는 [의도된 소유자] 의 대리물이 못 된다.** 그것은 경로에 적혀
        있지 않다. 그래서 자동 판정을 포기하고 **애매하다는 사실을 드러내는 쪽**을 골랐다 —
        `covering_workers` 가 여럿이면 상태판과 머지 게이트가 그 수를 함께 보인다.
        확신 없는 것을 확신한 척하지 않는다.
        """
        covering = self.covering_workers
        return covering[0] if covering else None

    @property
    def ci(self) -> str:
        if not self.checks:
            return "없음"
        states = {c.get("state") or c.get("conclusion") or "" for c in self.checks}
        if states & {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED"}:
            return "실패"
        if states & {"PENDING", "IN_PROGRESS", "QUEUED", ""}:
            return "진행중"
        return "통과"

    def violations(self) -> list[str]:
        out = []
        touched_coord = [f for f in self.files if f.startswith(COORDINATOR_ONLY)]
        if touched_coord and self.owner_guess not in CONTRACT_DELEGATED:
            out.append(f"코디네이터 전용 경로 변경: {touched_coord[:5]}")
        if self.files and self.owner_guess is None:
            known = {w: [f for f in self.files
                         if not any(f.startswith(p) for p in ps)]
                     for w, ps in WORKER_PATHS.items()}
            best = min(known.items(), key=lambda kv: len(kv[1]))
            out.append(f"소유 경로 밖 (가장 가까운 {best[0]} 기준): {best[1][:5]}")
        return out


def gather_prs() -> list[PR]:
    data = run_json(["gh", "pr", "list", "--repo", REPO, "--state", "open",
                     "--json", "number,title,headRefName,isDraft,mergeable", "--limit", "50"])
    prs = []
    for row in data or []:
        pr = PR(row["number"], row["title"], row["headRefName"],
                row["isDraft"], row.get("mergeable", "?"))
        detail = run_json(["gh", "pr", "view", str(pr.number), "--repo", REPO,
                           "--json", "files,statusCheckRollup"])
        if detail:
            pr.files = [f["path"] for f in detail.get("files") or []]
            pr.checks = detail.get("statusCheckRollup") or []
        prs.append(pr)
    return prs


def gather_tasks() -> list[dict]:
    orca = shutil.which("orca") or shutil.which("orca-ide") or "orca"
    data = run_json([orca, "orchestration", "task-list", "--json"])
    if not data or not data.get("ok"):
        return []
    return data["result"]["tasks"]


def first_line(spec: str) -> str:
    return (spec or "").strip().splitlines()[0][:60] if spec else "(빈 spec)"


def main() -> int:
    force_utf8_stdout()
    tasks = gather_tasks()
    prs = gather_prs()

    print("=" * 78)
    print(f"  Home_Compass 코디네이터 상태판   repo={REPO}")
    print("=" * 78)

    print("\n[ ORCA 과업 — 현재 런타임 전체 ]")
    if not tasks:
        print("  (없음 — orca 런타임이 안 떴거나 Run 이 비었다)")
    for t in tasks:
        print(f"  {t['id']}  {t['status']:<11} {first_line(t.get('spec'))}")

    print("\n[ 열린 PR ]")
    if not prs:
        print("  (없음)")
    mergeable, blocked = [], []
    for pr in prs:
        v = pr.violations()
        flag = "DRAFT " if pr.draft else ""
        ambiguous = (f" (후보 {len(pr.covering_workers)})"
                     if len(pr.covering_workers) > 1 else "")
        print(f"  #{pr.number} {flag}[{pr.head}]  CI={pr.ci}  파일={len(pr.files)}  "
              f"추정소유자={pr.owner_guess or '불명'}{ambiguous}")
        print(f"      {pr.title[:70]}")
        for line in v:
            print(f"      ✗ {line}")
        if pr.ci == "실패":
            print("      ✗ CI 실패 — 머지 금지 (SPEC D-10)")
        if pr.mergeable == "CONFLICTING":
            print("      ✗ 충돌 — 워커에게 리베이스 지시")
        ok = (pr.ci == "통과" and not v and not pr.draft
              and pr.mergeable != "CONFLICTING")
        (mergeable if ok else blocked).append(pr.number)

    print("\n[ 자동 확인 통과 — 사람이 PR 본문의 9.3 답변을 읽고 머지 ]")
    print(f"  {mergeable or '(없음)'}")
    if blocked:
        print(f"  보류: {blocked}")

    print("\n[ SPEC Part 10 파동 ]")
    # `done` 은 **손으로 유지한다.** 자동 판정할 신호가 없기 때문이다 — 파동의 완료는
    # PR 머지가 아니라 SPEC 10.2 단계 완료 기준의 충족이고, 그것은 사람이 읽어야 한다.
    # 그래도 이 칸은 있어야 한다: 비워 두면 `done_waves` 가 영원히 비고, 끝난 파동까지
    # 전부 '대기'로 보인다. **계기가 거짓말하면 아무도 안 본다.**
    done_waves = {w["wave"] for w in WAVES if w.get("done")}
    for w in WAVES:
        needs = w.get("needs", [])
        if w.get("done"):
            state = "완료"
        elif set(needs) - done_waves:
            state = "대기"
        else:
            state = "착수가능"
        if any(t["status"] == "dispatched" for t in tasks) and state == "착수가능":
            state = "진행중"
        print(f"  W{w['wave']} [{state}] {w['label']}")
        print(f"       {w['spec']}")
        for b in w.get("blocked_on_user", []):
            print(f"       ★ 사용자 결정 필요: {b}")

    print("\n[ 머지 전 사람이 확인할 것 — 자동화하지 않는다 ]")
    for line in (
        "PR 본문에 SPEC 9.3 여섯 항목의 답이 있는가 (특히 ③ 실행 명령·출력, ⑥ 미검증 목록)",
        "⑥ 미검증 목록이 비어 있으면 반려한다 — 비어 있는 경우는 사실상 없다",
        "새 상수에 Provenance 가 붙었는가 (SPEC 9.3 #5)",
        "값을 지어내지 않았는가 (실사 미정 항목을 그럴듯한 수치로 메웠는지)",
    ):
        print(f"  · {line}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
