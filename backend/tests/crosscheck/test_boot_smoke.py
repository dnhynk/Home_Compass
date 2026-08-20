"""교차 테스트 — 부팅 스모크 (SPEC 9.1.2 · 9.2 #7, 코디네이터 소유).

Part 0-A 의 실패 유형 중 "통합 미검증"에 대응하는 장치다. 방어 방식은 9.1.2 가 못
박았고, 세 조건 전부를 여기서 만족시킨다.

  1. **2xx 만으로는 불합격이다.** 응답이 `contracts/openapi.json` 스키마와 일치해야 한다
  2. 기동 시 5.1.1 **상수 전수 검증을 통과한 상태**여야 한다. 뜨지 않으면 그 자체가 실패
  3. **전 엔드포인트를 호출한다** — 호출 목록이 계약과 어긋나면 그것도 실패다

`TestClient` 를 쓰지 않는다. 실제로 `python -m uvicorn` 을 띄우고 소켓으로 친다.
예선에서 깨진 것은 함수가 아니라 **기동 경로**였다 (Part 0-A "실행 미검증").
TestClient 는 ASGI 앱을 직접 부르므로 기동 경로를 한 줄도 지나지 않는다.

인증이 필요한 엔드포인트는 아직 없다 (SPEC Part 10 — 4단계). 거부 케이스(9.2 #3)는
그때 이 파일에 붙는다.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src"
OPENAPI = REPO_ROOT / "contracts" / "openapi.json"

sys.path.insert(0, str(SRC))

BOOT_TIMEOUT_S = 90
CONTRACT_BASE = "http://contract/openapi.json"

class _RawBody:
    """`json=` 으로는 보낼 수 없는 본문 — 파싱 자체가 실패해야 하므로 바이트로 보낸다."""

    def __init__(self, raw: bytes):
        self.raw = raw


#: 유효한 UTF-8 이 아니라 JSON 파서가 본문을 읽지 못한다.
_UNPARSEABLE = _RawBody(b'{"message": "\xff\xfe"}')

# --------------------------------------------------------------------------
# 4단계 인증 픽스처 (W-auth, 코디네이터 승인 — CALLS · _seed · responses 세 곳)
# --------------------------------------------------------------------------
#
# ★ 이름에 `smoke-` 가 붙는 이유: 저장소를 열어 본 사람이 **진짜 정책 개정안으로
#   오해하면 안 된다.** 시드(`store/seed.py`)에는 초안을 심지 않았다 — 시드는 시연
#   데이터이고 이것은 테스트 픽스처이며, 둘을 섞으면 5단계 검토 화면의 대기 큐에
#   가짜 초안이 상시 뜬다.
SMOKE_SOURCE_ID = "smoke-src-1"
SMOKE_DRAFT_APPROVE = "smoke-draft-approve"
SMOKE_DRAFT_REJECT = "smoke-draft-reject"

# --------------------------------------------------------------------------
# 5단계 규칙 관리 화면 (W-admin, 코디네이터 승인 — CALLS · _seed 두 곳)
# --------------------------------------------------------------------------
#
# ★ **왜 이 파일을 건드렸는가.** 5단계가 계약에 오퍼레이션 셋을 더했다 — 초안 상세 ·
#   승인 영향 · 일괄 승인. SPEC 9.1.2 의 스모크는 [계약에 있는 모든 오퍼레이션과 상태를
#   실제로 친다]를 강제하고 그 목록이 이 파일에 있으므로, **API 를 늘리는 변경과 스모크
#   목록은 원리적으로 같은 PR 에 있어야 한다.** 소유 경계가 그것을 막으면 CI 를 빨간불로
#   두거나 계약을 줄이는 두 오답 중 하나를 고르게 된다. 4단계 W-auth 때와 같은 판단이며
#   위 55행이 그 선례다. `responses` 픽스처는 손대지 않았다 — 경로 치환과 CSRF 나르기가
#   이미 있어서 새 항목이 그대로 얹힌다.
#
# 일괄 승인은 **서로 다른 정책**을 가리키는 초안 둘로 친다. 같은 정책 둘은 아래 DUP 이
# 맡는다 — 그 조합은 성공이 아니라 **409 로 거부되어야 하는** 요청이다 (D5).
SMOKE_DRAFT_BATCH_A = "smoke-draft-batch-a"
SMOKE_DRAFT_BATCH_B = "smoke-draft-batch-b"

#: ★ D5 — 서로 다른 초안이 **같은 `policy_id`** 를 가리키는 경우. 저장소는 이 경합을
#: 막지 못하고(PR #58 「검증하지 않은 것」) `supersede` 에서 500 이 난다. API 계층이
#: 그것을 409 로 끊는다는 것이 코디네이터 판정이며, 여기서 **원인 (b) 로 409 를 한 번
#: 친다.** 원인 (a)[이미 결정된 초안]와 코드 문자열이 달라야 화면이 사용자에게 무엇이
#: 잘못됐는지 말할 수 있다 — 그 구분은 `tests/api/test_batch_approval.py` 가 단언한다.
SMOKE_DRAFT_DUP_A = "smoke-draft-dup-a"
SMOKE_DRAFT_DUP_B = "smoke-draft-dup-b"

# --------------------------------------------------------------------------
# 8.1 `/api/health` 운영 정보 (W-health, 코디네이터 배정 — `_seed` 한 곳)
# --------------------------------------------------------------------------
#
# ★ **왜 `_seed` 를 또 건드렸는가.** 8.1 이 `/api/health` 에 더한 두 블록은 저장소에서
#   나온다. 시드에는 시세 수집 이력도 관측 기준시점도 없으므로, 그대로 두면 실기동에서
#   두 블록이 **항상 `null`** 이고 스모크는 [자리는 있다] 까지만 확인한 채 초록불이 된다.
#   그 상태에서는 값을 실어 나르는 배선이 끊겨도 여기서 잡히지 않는다. 4단계 W-auth ·
#   5단계 W-admin 과 같은 판단이며 위 두 절이 그 선례다. `CALLS` 는 손대지 않았다 —
#   `/api/health` 는 이미 목록에 있다.
SMOKE_MARKET_RUN_ID = "smoke-audit-market-run"

#: 관측 기준시점. **숫자 오프셋 필수**(`contracts/provenance.schema.json` — `Z` 금지)이며
#: `main._parse_at` 도 tz 없는 값을 버린다. 고정 리터럴인 이유는 스모크가 이 값을
#: **그대로** 응답에서 되찾는지 보기 때문이다 — 계산된 기대값은 같은 버그를 두 번 탄다.
SMOKE_OBSERVED_AT = "2026-08-01T00:00:00+09:00"

# --------------------------------------------------------------------------
# 6-A 이상 신고 (W-report, 코디네이터 승인 — CALLS 한 곳)
# --------------------------------------------------------------------------
#
# ★ **픽스처를 심지 않는다.** 신고는 사람이 만드는 것이므로 스모크가 상담원 세션에서
#   실제로 올린다 — 그것이 6.4 가 요구한 경로 그 자체다. 대상은 시드가 넣은 정책이며
#   (신고 대상은 실재해야 한다), 사유에는 **고객 상황을 적지 않는다** (SPEC 7.1).
_SMOKE_REPORT = {
    "targetKind": "policy",
    "targetId": "buttress_youth",
    "targetField": "status",
    "reason": "스모크 픽스처 — 현장에서 이 제도가 종료됐다는 문의가 있었다",
}

#: 상태변경 요청에 실을 CSRF 헤더 이름. 상수를 앱에서 가져와 이름이 갈리지 않게 한다.
from firsthome.auth import CSRF_HEADER_NAME  # noqa: E402

#: 시드 계정 비밀번호는 **환경변수로 주입된다** (SPEC 6.3). `conftest.py` 가 세션마다
#: 무작위로 만들어 걸고, `_server_env` 가 `os.environ` 을 그대로 넘기므로 스모크 서버가
#: 같은 값을 본다. 여기에 값을 적으면 그것이 곧 [커밋된 시드 비밀번호]다.
_COUNSELOR_LOGIN = {
    "username": "counselor",
    "password": os.environ.get("FIRSTHOME_SEED_COUNSELOR_PASSWORD", ""),
}
_RULE_MANAGER_LOGIN = {
    "username": "rulemanager",
    "password": os.environ.get("FIRSTHOME_SEED_RULE_MANAGER_PASSWORD", ""),
}

class _Call:
    """본문 + 요청 부가정보를 담는 봉투. `_RawBody` 와 같은 자리에 선다.

    부가정보를 **튜플 뒤가 아니라 본문 자리에** 담는 이유는 하나다 — CALLS 항목을
    4원소로 유지하면 이 파일의 단언·파라미터 id·커버리지 검사가 한 글자도 바뀌지 않는다.
    5원소로 늘리면 `for p, m, _, s in CALLS` 같은 해체가 전부 깨지고, 그것들은
    코디네이터가 [건드리지 마라]고 못박은 자리다.
    """

    def __init__(self, body=None, *, csrf: bool = False, path_params: dict | None = None):
        self.body = body
        self.csrf = csrf
        self.path_params = path_params


#: 실기동에서 칠 요청. `(path, method, body, expected_status)`.
#: `path` 는 **계약의 경로 템플릿 그대로**여야 한다 (커버리지 검사가 문자열로 비교한다).
#: 실제 요청 경로는 `_Call(path_params=...)` 이 치환한다.
#: 계약에 있는 모든 오퍼레이션이 여기 나와야 한다 — 아래 커버리지 검사가 강제한다.
CALLS = [
    ("/api/health", "get", None, 200),
    ("/api/meta", "get", None, 200),
    ("/api/regions", "get", None, 200),
    ("/api/analyze", "post", {
        "age": 28, "annualIncomeKRW": 42_000_000, "monthlyNetIncomeKRW": 3_000_000,
        "liquidAssetsKRW": 40_000_000, "existingDebtMonthlyKRW": 300_000,
        "householdSize": 1, "regionCode": "11440", "isHomeless": True,
        "isNewlywed": False, "isSMEEmployee": True, "preferredType": "any",
    }, 200),
    ("/api/analyze", "post", {}, 200),
    # 경계값 (SPEC 9.2 #6) — 0소득 · 최대 가구원수
    ("/api/analyze", "post", {"annualIncomeKRW": 0, "monthlyNetIncomeKRW": 0,
                              "householdSize": 15, "age": 0}, 200),
    # 없는 지역 -> 오류 봉투
    ("/api/analyze", "post", {"regionCode": "99999"}, 400),
    # 잘못된 타입/범위 -> 오류 봉투 (FastAPI 기본 422 가 아니라 우리 봉투여야 한다)
    ("/api/analyze", "post", {"age": -1}, 422),
    ("/api/analyze", "post", {"age": "스물여덟"}, 422),
    ("/api/chat", "post", {"message": "전세와 월세 중 뭐가 나을까요"}, 200),
    ("/api/chat", "post", {"history": "리스트가 아니다"}, 422),
    # 파싱 불가 본문 -> 400. 실기동에서 손으로 쳐 보다 발견했고, 그때 /api/chat 의
    # 계약에는 400 이 없었다 (SPEC 9.3 #3 이 있는 이유가 이것이다).
    ("/api/analyze", "post", _UNPARSEABLE, 400),
    ("/api/chat", "post", _UNPARSEABLE, 400),

    # ----------------------------------------------------------------------
    # 4단계 인증·권한 (SPEC 6.1 · 6.3 · 9.2 #3) — W-auth, 코디네이터 승인
    # ----------------------------------------------------------------------
    #
    # **순서가 곧 시나리오다.** 하나의 httpx.Client 를 재사용하므로 쿠키가 이어지고,
    # 로그인 -> 거부 -> 로그아웃 -> 다른 역할로 로그인이 한 줄기로 흐른다. 항목을
    # 중간에 끼워 넣으면 뒤가 전부 어긋나므로 새 항목은 이 블록 끝에 붙인다.

    # 익명 — 로그인하지 않은 상태에서 무엇이 막히는가
    ("/api/auth/session", "get", None, 200),
    ("/api/admin/drafts", "get", None, 401),
    ("/api/admin/audit", "get", None, 401),
    # 7단계 — 상태 화면의 재료도 같은 게이트 뒤에 있다 (SPEC 7.2)
    ("/api/admin/status", "get", None, 401),
    # 6-A — **익명은 신고할 수 없다** (SPEC 6.4). 큐는 규칙관리자 것이다
    ("/api/reports", "post", _SMOKE_REPORT, 401),
    ("/api/admin/reports", "get", None, 401),
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "익명"}, path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 401),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": "익명"}, path_params={"draft_id": SMOKE_DRAFT_REJECT}), 401),
    # 5단계 신규 셋 — 검토 화면의 재료도 같은 게이트 뒤에 있다 (W-admin)
    ("/api/admin/drafts/{draft_id}", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 401),
    ("/api/admin/drafts/{draft_id}/impact", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 401),
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": [SMOKE_DRAFT_BATCH_A]}), 401),
    ("/api/auth/logout", "post", None, 401),

    # 로그인 실패 — 없는 계정과 틀린 비밀번호가 같은 답이어야 한다
    ("/api/auth/login", "post", {"username": "counselor", "password": "wrong"}, 401),
    ("/api/auth/login", "post", {"username": [], "password": ""}, 422),

    # ★ 상담원 세션 — SPEC 6.1 의 SoD. 여기가 4단계의 산출물이다
    ("/api/auth/login", "post", _COUNSELOR_LOGIN, 200),
    ("/api/admin/drafts", "get", None, 403),
    ("/api/admin/audit", "get", None, 403),
    # 7단계 — 상담원은 지표도 보지 못한다. 대기 큐의 적체는 규칙관리자의 일이다
    ("/api/admin/status", "get", None, 403),
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "상담원이 승인을 시도한다"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 403),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": "상담원이 반려를 시도한다"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_REJECT}), 403),
    # 5단계 — 상담원은 **검토 화면의 재료조차** 받지 못한다. 초안 조회부터 rule_manager 다
    # (SPEC 6.1 「규칙 초안 조회」 행). 승인만 막고 근거를 보여 주면 SoD 가 반쪽이 된다.
    ("/api/admin/drafts/{draft_id}", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 403),
    ("/api/admin/drafts/{draft_id}/impact", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 403),
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": [SMOKE_DRAFT_BATCH_A]}, csrf=True), 403),
    # ----------------------------------------------------------------------
    # 6-A 이상 신고 (SPEC 6.4) — W-report
    # ----------------------------------------------------------------------
    #
    # ★ 상담원 세션에서 치는 것이 곧 이 단계의 산출물이다. 위의 403 들과 **같은 줄기**에
    #   붙여 두는 이유가 그것이다 — 상담원은 승인·초안 조회에서 전부 막히고, 신고만
    #   열린다. 신고가 규칙을 바꾸지 않는다는 것은 바로 위 403 들이 이미 말하고 있다.
    ("/api/reports", "post", _SMOKE_REPORT, 403),           # CSRF 토큰 없이 -> 거부
    ("/api/reports", "post", _Call(_SMOKE_REPORT, csrf=True), 200),
    ("/api/reports", "post",
     _Call({**_SMOKE_REPORT, "targetField": "없는항목"}, csrf=True), 400),
    ("/api/reports", "post", _Call({**_SMOKE_REPORT, "reason": 5}, csrf=True), 422),
    # 신고 큐는 규칙관리자 것이다 — 올리는 것과 보는 것은 다른 권한이다
    ("/api/admin/reports", "get", None, 403),
    ("/api/auth/logout", "post", _Call(csrf=True), 200),

    # 규칙관리자 세션 — 거부가 의미 있으려면 허용도 의미가 있어야 한다
    ("/api/auth/login", "post", _RULE_MANAGER_LOGIN, 200),
    ("/api/admin/drafts", "get", None, 200),
    ("/api/admin/audit", "get", None, 200),
    # 6-A — 상담원이 올린 신고가 **별도 유형**으로 이 큐에 쌓여 있다 (SPEC 10.2 6-A)
    ("/api/admin/reports", "get", None, 200),
    # 7단계 — 지표가 실제로 나온다 (SPEC 10.2 7단계 「상태 화면에 7.2 지표가 노출된다」).
    # 스모크는 **계약 스키마까지** 검증하므로(9.1.2) 여기 200 하나가 지표 응답의
    # 모양 전체를 잡는다 — 비율이 `null` 로 나가는 자리도 그 스키마 안에 있다.
    ("/api/admin/status", "get", None, 200),
    # CSRF 토큰 없이 상태변경 -> 거부 (SPEC 6.3)
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "토큰 없이"}, path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 403),
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": 5}, csrf=True, path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 422),
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "없는 초안"}, csrf=True, path_params={"draft_id": "no-such-draft"}), 404),
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "공고 개정 반영"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 200),
    # 두 번째 승인은 거부된다 (SPEC 4.6 — 승인은 한 번만 일어나야 한다)
    ("/api/admin/drafts/{draft_id}/approve", "post",
     _Call({"reason": "두 번째"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_APPROVE}), 409),
    # 반려는 사유가 필수다 (SPEC 10.2 5단계)
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({}, csrf=True, path_params={"draft_id": SMOKE_DRAFT_REJECT}), 400),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": 5}, csrf=True, path_params={"draft_id": SMOKE_DRAFT_REJECT}), 422),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": "없는 초안"}, csrf=True, path_params={"draft_id": "no-such-draft"}), 404),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": "원문과 다르다"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_REJECT}), 200),
    ("/api/admin/drafts/{draft_id}/reject", "post",
     _Call({"reason": "두 번째"}, csrf=True,
           path_params={"draft_id": SMOKE_DRAFT_REJECT}), 409),
    # ----------------------------------------------------------------------
    # 5단계 검토 화면 · 일괄 승인 (SPEC 4.4 · 4.5 · 4.6) — W-admin, 코디네이터 승인
    # ----------------------------------------------------------------------
    #
    # 규칙관리자 세션이 이어지는 자리에 붙인다. 아래 마지막 항목(로그아웃 403)보다 앞에
    # 두는 이유는 그 항목이 [세션을 끊지 않는 마지막 줄]이라는 자기 역할을 유지하기
    # 위해서다 — 뒤에 붙이면 그 주석이 사실이 아니게 된다.

    # 4.4 ①③ — 초안 상세 (근거 구간 + 변경 전/후)
    ("/api/admin/drafts/{draft_id}", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 200),
    ("/api/admin/drafts/{draft_id}", "get",
     _Call(path_params={"draft_id": "no-such-draft"}), 404),
    # 4.4 ② — 승인 영향 사례. **저장소를 건드리지 않는다**(그 사실은 API 테스트가 단언한다)
    ("/api/admin/drafts/{draft_id}/impact", "get",
     _Call(path_params={"draft_id": SMOKE_DRAFT_BATCH_A}), 200),
    ("/api/admin/drafts/{draft_id}/impact", "get",
     _Call(path_params={"draft_id": "no-such-draft"}), 404),

    # 4.5 · 4.6 — 일괄 승인. 거부 경로를 먼저 전부 친 뒤에 성공을 친다
    ("/api/admin/drafts/batch-approve", "post", _Call({"draftIds": []}, csrf=True), 400),
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": "목록이 아니다"}, csrf=True), 422),
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": ["no-such-draft"]}, csrf=True), 404),
    # 409 원인 (a) — 이미 결정된 초안이 섞였다 (`draft_already_decided`)
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": [SMOKE_DRAFT_BATCH_A, SMOKE_DRAFT_APPROVE]}, csrf=True), 409),
    # 409 원인 (b) — 같은 policy_id 를 가리키는 초안 둘 (`duplicate_policy_target`, D5)
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": [SMOKE_DRAFT_DUP_A, SMOKE_DRAFT_DUP_B]}, csrf=True), 409),
    # 성공 — 서로 다른 정책 둘. 위 거부들이 **아무것도 반영하지 않았기** 때문에 여기가 산다
    ("/api/admin/drafts/batch-approve", "post",
     _Call({"draftIds": [SMOKE_DRAFT_BATCH_A, SMOKE_DRAFT_BATCH_B],
            "reason": "일괄 검토 완료 (스모크)"}, csrf=True), 200),

    # 로그아웃도 상태변경이므로 토큰을 요구한다. 마지막에 두는 이유는 세션을 끊지
    # 않기 때문이다 — 403 은 거부이지 로그아웃이 아니다.
    ("/api/auth/logout", "post", None, 403),
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _seed(db_path: Path) -> str:
    from firsthome.store import PolicySource, RuleDraft, create_store
    from firsthome.store.seed import seed_all

    url = f"sqlite://{db_path}"
    now = datetime.now(timezone.utc)
    with create_store(url) as store:
        seed_all(store, at=now)
        _seed_smoke_drafts(store, now)
        _seed_smoke_operations(store, now)
    return url


def _seed_smoke_operations(store, now: datetime) -> None:
    """8.1 이 `/api/health` 에 요구한 두 사실을 실기동 저장소에 심는다 (W-health).

    배치 1회와 관측 기준시점 하나면 충분하다. 여러 건을 심지 않는 이유는 `/api/health`
    가 **마지막 실행 하나와 가장 오래된 관측 하나**만 싣기 때문이다 — 그 이상을 심으면
    스모크가 이 경로에 없는 집계를 재는 것처럼 보인다. 집계는 `/api/admin/status` 의
    몫이고 `backend/tests/api/test_status_metrics.py` 가 이미 붙들고 있다.
    """
    from dataclasses import replace

    from firsthome.store.models import AuditEvent

    store.audit.append(
        AuditEvent(
            id=SMOKE_MARKET_RUN_ID,
            actor="system:ingest",
            at=now,
            action="market.run",
            target="market-run-smoke",
            outcome="success",
            # 실행 식별자는 감사기록에 **남는다.** `/api/health` 가 그것을 싣지 않는다는
            # 것이 8.1 경계이며, 아래 검사가 이 값이 새어 나오지 않는지를 본다.
            after={"runId": "market-run-smoke", "committed": True},
        )
    )

    # 지역 하나에만 심는다. `/api/health` 는 **가장 오래된** 값을 내므로, 나머지가
    # `null` 인 채로 이 값이 나와야 [null 을 빼고 최소를 고른다]가 실제로 확인된다.
    region = store.regions.list()[0]
    provenance = replace(region.provenance, observed_at=SMOKE_OBSERVED_AT)
    store.regions.upsert(replace(region, provenance=provenance, field_provenance={}))


def _seed_smoke_drafts(store, now: datetime) -> None:
    """승인·반려를 실제로 칠 대상을 심는다 (W-auth, 코디네이터 승인).

    `seed_all` 은 초안을 만들지 않는다 — 시드는 시연 데이터이므로 지어낸 정책 개정안이
    상시 들어앉으면 안 된다. 그러나 초안이 하나도 없으면 승인 API 는 **영원히 404** 이고,
    계약에 적힌 200 을 스모크가 한 번도 칠 수 없다. 그래서 픽스처는 여기 있다.

    `not_found` 에 `/criteria/assetMaxKRW` 를 넣어 둔 것은 의도적이다 — 원문에 없던 값이
    기존 문턱을 `null` 로 덮지 않는지가 승인 경로의 조용한 실패 지점이다.
    """
    from firsthome.store import PolicySource, RuleDraft, RuleSpanMapping

    text = "청년전용 버팀목전세자금대출 신청 연령은 만 19세 이상 39세 이하입니다."
    store.policy_sources.add(
        PolicySource(
            id=SMOKE_SOURCE_ID,
            text=text,
            source_ref="https://nhuf.molit.go.kr/",
            fetched_at=now,
            attribution="주택도시기금 공고 (스모크 픽스처)",
        )
    )

    def payload_for(policy_id: str) -> dict:
        return {
            "policy_id": policy_id,
            "criteria": {
                "ageMin": 19, "ageMax": 39, "annualIncomeMaxKRW": 60_000_000,
                "assetMaxKRW": None, "requireHomeless": True, "requireNewlywed": False,
                "requireSME": False, "regionPrefixes": None,
            },
            "maxAmountKRW": 250_000_000,
            "rateRangePct": [1.8, 3.1],
            "conditionalChecks": [],
            "not_found": ["/criteria/assetMaxKRW"],
        }

    # ★ 정책 배정이 곧 시나리오다 (5단계, W-admin). 일괄 승인은 **서로 다른 정책**을
    #   묶어야 성립하고, 같은 정책 둘은 409 로 거부되어야 한다 (D5). 그래서 BATCH 는
    #   갈라 두고 DUP 은 붙여 두었다.
    drafts = {
        SMOKE_DRAFT_APPROVE: "buttress_youth",
        SMOKE_DRAFT_REJECT: "buttress_youth",
        SMOKE_DRAFT_BATCH_A: "youth_monthly_loan",
        SMOKE_DRAFT_BATCH_B: "newlywed_jeonse",
        SMOKE_DRAFT_DUP_A: "seoul_deposit_interest",
        SMOKE_DRAFT_DUP_B: "seoul_deposit_interest",
    }
    #: 근거 구간. 오프셋은 **원문에서 찾아** 넣는다 — 손으로 센 숫자를 적으면 그 숫자가
    #: 검증 대상이 되어 버린다. 파이썬 `str` 인덱스가 곧 SPEC 4.2.1 의 코드포인트다.
    quote = "만 19세 이상"
    start = text.index(quote)

    for draft_id, policy_id in drafts.items():
        store.rule_drafts.add(
            RuleDraft(
                id=draft_id,
                policy_source_id=SMOKE_SOURCE_ID,
                policy_id=policy_id,
                status="pending",
                payload=payload_for(policy_id),
                created_at=now,
            )
        )
        # 상세 화면이 [근거가 하나도 없는 초안]만 보고 통과하면, 대조 표시가 통째로
        # 비어 있어도 스모크는 초록불이다. 그래서 최소 하나를 심는다.
        store.rule_drafts.add_span(
            RuleSpanMapping(
                id=f"{draft_id}:span:0",
                draft_id=draft_id,
                field_path="/criteria/ageMin",
                start=start,
                end=start + len(quote),
            )
        )


def _server_env(store_url: str) -> dict:
    env = {
        **os.environ,
        "FIRSTHOME_STORE_URL": store_url,
        "PYTHONPATH": str(SRC),
        "PYTHONIOENCODING": "utf-8",
        # 키 없이 전 기능이 도는지가 요건이다 (SPEC 9.2 #8 · 9.2.1). 개발 머신의 .env 가
        # 스모크를 프로바이더 호출로 끌고 가면 이 테스트는 네트워크 상태를 재는 것이 된다.
        # 빈 문자열이면 config.resolve_provider() 가 offline 을 고르고, load_env_file 은
        # 이미 os.environ 에 있는 키를 덮지 않으므로 .env 가 이것을 되돌리지 못한다.
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
    }
    return env


class _Server:
    def __init__(self, store_url: str):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        #: 출력을 한 번만 읽는다. 캐시하지 않으면 "왜 안 떴는지"가 두 번째 독자에게서
        #: 사라진다 (파일 핸들은 읽은 뒤 닫는다).
        self._output: str | None = None
        # ★ 서버 출력을 **파일로** 받는다. `subprocess.PIPE` 로 받아놓고 요청을 치는
        #   동안 읽지 않으면, 500 이 한 번이라도 나는 순간 트레이스백(약 8KB)이 OS
        #   파이프 버퍼(약 4KB)를 채우고 uvicorn 의 로깅 `write()` 가 **이벤트 루프
        #   스레드에서 블로킹된다.** 그러면 응답이 플러시되지 못해 스모크가 시나리오
        #   도중 멈추고, CI 는 타임아웃으로 죽는데 **원인은 출력에 남지 않는다** —
        #   그것을 쓰다가 막혔으므로. 여기는 `--log-level warning` 이라 접근 로그가
        #   없어 아직 안 물렸을 뿐이고, 잠재적이라는 것은 안전하다는 뜻이 아니다.
        #   같은 수정이 `backend/tests/api/test_log_hygiene.py` 의 `_Server` 에도 있다.
        self._console = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "firsthome.main:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=str(SRC), env=_server_env(store_url),
            stdout=self._console, stderr=subprocess.STDOUT,
        )

    def _read_console(self) -> str:
        """자식이 죽은 뒤에 부른다 — 그래야 마지막 줄까지 파일에 닿아 있다."""
        self._console.flush()
        self._console.seek(0)
        text = self._console.read().decode("utf-8", "replace")
        self._console.close()
        return text

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    "서버가 기동 중에 죽었다. 상수 전수 검증(SPEC 5.1.1)이 실패했을 수 있다:\n"
                    + self.stop())
            try:
                if httpx.get(f"{self.base}/api/health", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.25)
        raise AssertionError(f"{BOOT_TIMEOUT_S}초 안에 기동하지 못했다:\n" + self.stop())

    def await_exit(self, timeout: int = BOOT_TIMEOUT_S) -> str:
        """서버가 **스스로** 죽기를 기다리며 출력을 끝까지 읽는다.

        `poll()` 로 종료를 감지한 뒤 읽으면 트레이스백 꼬리가 잘린 채로 잡히는 것을
        윈도우에서 실측했다 — 마지막 `RuntimeError:` 줄이 사라져서 "기동은 거부됐는데
        이유가 없는" 상태가 된다. 그래서 **종료를 먼저 기다린 뒤** 읽는다. 자식이 죽으면
        그때까지 쓴 것은 전부 파일에 닿아 있으므로 그 틈이 없다.
        """
        if self._output is None:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise AssertionError(
                    f"{timeout}초 안에 종료하지 않았다 — 기동이 거부되어야 했다:\n" + self.stop())
            self._output = self._read_console()
        return self._output

    def stop(self) -> str:
        if self._output is None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
            self._output = self._read_console()
        return self._output


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(OPENAPI.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry(contract: dict) -> Registry:
    return Registry().with_resource(
        CONTRACT_BASE, Resource(contents=contract, specification=DRAFT202012)
    )


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """실제로 기동한다. 여기서 뜨지 못하면 그 자체가 SPEC 9.1.2 불합격이다."""
    store_url = _seed(tmp_path_factory.mktemp("smoke-store") / "smoke.db")
    server = _Server(store_url)
    try:
        server.wait_until_ready()
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def responses(live_server) -> dict:
    """전 엔드포인트를 한 번씩 친 결과. 요청은 모듈당 1회만 나간다.

    4단계로 둘이 늘었다 (W-auth, 코디네이터 승인).

      · **CSRF 토큰 나르기** — 토큰은 로그인 응답에서 런타임에 나오므로 정적 표에 적을
        수 없다. 로그인이 200 이면 받아 두었다가 `csrf=True` 인 항목의 헤더에 싣는다.
      · **경로 템플릿 치환** — 커버리지 검사가 CALLS 의 path 와 계약의 경로를 문자열로
        비교하므로 표에는 `{draft_id}` 를 그대로 두고 요청할 때만 바꾼다.

    클라이언트 하나를 재사용하는 것은 원래 성질이며, 여기서는 그것이 **쿠키 세션이
    이어진다**는 뜻이 된다. 로그인 -> 거부 -> 로그아웃이 한 줄기로 흐르는 근거다.
    """
    collected = {}
    csrf_token = ""
    with httpx.Client(base_url=live_server.base, timeout=30.0) as client:
        for index, (path, method, body, expected) in enumerate(CALLS):
            headers: dict[str, str] = {}
            url = path
            if isinstance(body, _Call):
                if body.path_params:
                    url = path.format(**body.path_params)
                if body.csrf:
                    headers[CSRF_HEADER_NAME] = csrf_token
                body = body.body

            if isinstance(body, _RawBody):
                headers["Content-Type"] = "application/json"
                response = client.request(
                    method.upper(), url, content=body.raw, headers=headers)
            else:
                response = client.request(method.upper(), url, json=body, headers=headers)

            if path == "/api/auth/login" and response.status_code == 200:
                csrf_token = response.json()["csrfToken"]
            collected[index] = response
    return collected


def _schema_ref(contract: dict, path: str, method: str, status: int) -> str:
    operation = contract["paths"][path][method]
    response = operation["responses"][str(status)]
    return response["content"]["application/json"]["schema"]["$ref"]


# --- 1. 기동 자체 -----------------------------------------------------------

def test_the_server_boots_at_all(live_server):
    """SPEC 9.1.2 — 기동 시 5.1.1 상수 전수 검증을 통과한 상태여야 한다."""
    assert live_server.process.poll() is None, "서버가 죽어 있다"


def test_health_reports_offline_mode_without_api_keys(live_server):
    """SPEC 9.2 #8 — 키 없이 전 기능이 돈다. offline 은 오류가 아니라 정상 모드다."""
    body = httpx.get(f"{live_server.base}/api/health", timeout=10.0).json()
    # 8.1 은 **순수 추가**다. 기존 두 필드는 이름도 값도 그대로여야 한다.
    assert body["status"] == "ok"
    assert body["llm"] == "offline"


def test_health_carries_the_batch_state_and_freshness_spec_8_1_named(live_server):
    """SPEC 8.1 — `/api/health` 에 **배치 상태 · 데이터 신선도**가 실린다.

    형태는 위 `test_response_body_matches_the_contract_schema` 가 계약으로 검증한다.
    여기서 보는 것은 **값이 실기동 저장소에서 실제로 흘러왔는가** 다 — 두 블록이
    계약을 만족하면서 영원히 `null` 인 상태가 이 변경의 조용한 실패 지점이다.
    """
    body = httpx.get(f"{live_server.base}/api/health", timeout=10.0).json()

    assert body["batch"]["lastOutcome"] == "success", body["batch"]
    assert body["batch"]["lastRunAt"], "배치 실행 시각이 비어 있다"
    assert body["freshness"]["oldestObservedAt"] == SMOKE_OBSERVED_AT, body["freshness"]


def test_health_keeps_the_anonymous_payload_minimal(live_server):
    """8.1 경계 — 익명에 여는 것이므로 **최소**다 (코디네이터 판정).

    뺀 것을 검사로 적어 둔다. 「최소로 한다」는 판단이지 자명한 것이 아니므로, 적어
    두지 않으면 다음 사람이 [있으면 편하니까] 로 하나씩 되돌려 놓는다.
    """
    body = httpx.get(f"{live_server.base}/api/health", timeout=10.0).json()

    assert set(body) == {"status", "llm", "batch", "freshness"}
    # 배치 — 마지막 실행의 성공/실패와 그 시각뿐. 실행 식별자 · 오류 본문 · 대상 지역
    # 목록은 없다. 집계(횟수 · 성공률 · 분모 문장)도 `/api/admin/status` 에 남는다.
    assert set(body["batch"]) == {"lastRunAt", "lastOutcome"}
    # 신선도 — 요약 하나뿐. 필드별 계보도 `provenance` 전문도 없다.
    assert set(body["freshness"]) == {"oldestObservedAt"}
    # `dataGrade` 는 판정에 걸리는 것이고 `/api/health` 에는 판정이 없다.
    assert "dataGrade" not in json.dumps(body)
    # 감사기록에 있는 실행 식별자가 새어 나오지 않는다.
    assert "market-run-smoke" not in json.dumps(body)


# --- 2. 상태코드와 스키마 (9.1.2 "2xx 만으로는 불합격") ----------------------

@pytest.mark.parametrize("index", range(len(CALLS)), ids=[
    f"{m.upper()} {p} -> {s}" for p, m, _, s in CALLS])
def test_status_code_matches_the_contract(index, responses):
    path, method, _, expected = CALLS[index]
    assert responses[index].status_code == expected, responses[index].text[:400]


@pytest.mark.parametrize("index", range(len(CALLS)), ids=[
    f"{m.upper()} {p} -> {s}" for p, m, _, s in CALLS])
def test_response_body_matches_the_contract_schema(index, responses, contract, registry):
    """★ 합격 판정은 계약 파일 기준이다 (SPEC 9.1.2 · D-12).

    2xx 는 통과했는데 몸통이 계약과 다른 것이 예선의 계약 드리프트 그 자체다 —
    백엔드가 응답 계약을 바꿨는데 프론트가 몰라 상태 배지를 잘못 표시했다.
    """
    path, method, _, expected = CALLS[index]
    ref = _schema_ref(contract, path, method, expected)
    # 계약 문서를 하나의 리소스로 등록해 두었으므로, 문서 내 포인터를 그 기준 URI 에
    # 붙여 절대 참조로 만든다.
    validator = Draft202012Validator({"$ref": CONTRACT_BASE + ref}, registry=registry)
    errors = sorted(validator.iter_errors(responses[index].json()), key=lambda e: list(e.path))
    assert not errors, (
        f"{method.upper()} {path} -> {expected} 응답이 계약({ref})과 다르다:\n"
        + "\n".join(f"  /{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:8]))


# --- 3. 커버리지 — 전 엔드포인트를 실제로 쳤는가 ----------------------------

def test_every_contracted_operation_was_called(contract):
    """호출 목록이 계약보다 좁으면 스모크는 안 친 곳을 통과시킨다."""
    contracted = {
        (path, method)
        for path, item in contract["paths"].items()
        for method in item
        if method in ("get", "post", "put", "patch", "delete")
    }
    called = {(path, method) for path, method, _, _ in CALLS}
    assert contracted <= called, f"계약에 있는데 스모크가 치지 않은 오퍼레이션: {sorted(contracted - called)}"
    assert called <= contracted, f"계약에 없는 경로를 쳤다: {sorted(called - contracted)}"


def test_every_contracted_status_code_was_exercised(contract):
    """오류 봉투가 계약에 적혀 있는데 한 번도 확인되지 않는 상태를 막는다."""
    contracted = {
        (path, method, int(status))
        for path, item in contract["paths"].items()
        for method, operation in item.items()
        if method in ("get", "post", "put", "patch", "delete")
        for status in operation.get("responses", {})
        if status.isdigit()
    }
    exercised = {(path, method, status) for path, method, _, status in CALLS}
    assert contracted <= exercised, f"계약에 적혀 있으나 확인되지 않은 응답: {sorted(contracted - exercised)}"


def test_the_static_frontend_is_served(live_server):
    """SPEC 6.2 — 같은 오리진에서 화면이 뜬다. 계약 대상은 아니므로 상태만 본다."""
    response = httpx.get(f"{live_server.base}/", timeout=10.0)
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


# --- 4. fail-closed — 상수가 하나 없으면 아예 뜨지 않는다 -------------------

def test_the_server_refuses_to_boot_with_a_missing_constant(tmp_path):
    """SPEC 10.2 1-① 완료 기준 · Part 0-E #2 를 **기동 경로 전체**로 확인한다.

    `test_engine_constants.py` 는 로더 함수를 직접 부른다. 여기서는 실제로 uvicorn 을
    띄워 본다 — 그 둘 사이에 import 순서·기동 훅 같은 것이 끼어들 자리가 있고,
    fail-closed 가 무력화된다면 바로 거기서 무력화된다.
    """
    import sqlite3

    db = tmp_path / "broken.db"
    store_url = _seed(db)
    victim = "affordability.housing_cost_ratio_cap"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("DELETE FROM model_constant WHERE key = ?", (victim,))
    conn.close()

    server = _Server(store_url)
    try:
        output = server.await_exit()
    finally:
        server.stop()

    assert server.process.returncode not in (0, None), "상수가 없는데 정상 종료했다"
    assert victim in output and "fail-closed" in output, (
        "기동은 거부됐지만 이유가 출력에 없다. 시연 중이라면 원인을 못 찾는다:\n" + output[-1500:])
