#!/usr/bin/env python3
"""머지 + 정리 — `python scripts/coord_merge.py <PR번호> --reviewed`

왜 이 스크립트가 있는가. COORDINATION.md 가 적어 둔 절차 중 **머지 직후 정리**가
반복해서 깨졌다. 원인은 규율이 아니라 구조다 —

  `gh pr merge --delete-branch` 는 **Orca 워크트리가 그 브랜치를 체크아웃하고 있으면
  조용히 실패한다.** 실제로 워커 브랜치 9개와 워크트리 9개가 그렇게 쌓였고,
  상태판이 그것을 보지 않으므로 쌓이는 것을 아무도 몰랐다.

여러 단계를 손으로 이어 붙이면 언젠가 한 단계가 빠진다. 그래서 순서를 코드에 박는다.

  1. 기계 게이트 재확인 (CI · 소유 경로 · 계약 파일 · 충돌 · draft)
  2. squash 머지            ← `--delete-branch` 를 쓰지 않는다. 아래 3·4 가 먼저다
  3. Orca 워크트리 제거     ← 워커 브랜치를 놓게 만든다
  4. main 으로 이동 + 갱신  ← **코디네이터 워크트리**가 브랜치를 놓게 만든다
  5. 원격·로컬 브랜치 삭제
  6. main 의 CI 확인

**4 가 5 보다 먼저인 이유.** 코디네이터가 자기 PR 을 머지할 때는 그 브랜치가
코디네이터 워크트리에 체크아웃돼 있다. `git branch -D` 는 체크아웃된 브랜치를
거부하므로, 먼저 main 으로 옮겨야 놓아진다. 워커 브랜치는 3 에서 놓아지고
코디네이터 브랜치는 4 에서 놓아진다 — **둘은 다른 경로다.**

## 사람 게이트를 자동화하지 않는다

`--reviewed` 없이는 머지하지 않는다. COORDINATION.md 의 머지 게이트 5~9번
(9.3 여섯 항목의 답 · ③ 실행 명령과 출력 · ⑥ 미검증 목록 · Provenance · 값 날조)은
**사람이 PR 본문을 읽어야** 판정된다. 플래그는 그 읽기를 대신하지 않고, 읽었다는
사실을 기록으로 남긴다. 자동으로 켜지는 플래그를 만들지 않는다.

    python scripts/coord_merge.py 57 --reviewed
    python scripts/coord_merge.py 57 --dry-run       # 게이트만 보고 아무것도 하지 않는다
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _console import force_utf8_stdout  # noqa: E402


def _load_coord_status():
    """상태판의 소유 경로 판정기를 그대로 재사용한다.

    게이트 로직을 두 벌 갖지 않는다 — 두 벌이 되는 순간 한쪽만 갱신되고,
    그것이 이 프로젝트가 계약을 단일 파일로 두는 이유와 같은 규율이다.
    """
    path = Path(__file__).resolve().parent / "coord_status.py"
    spec = importlib.util.spec_from_file_location("coord_status", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["coord_status"] = module
    spec.loader.exec_module(module)
    return module


def run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, cwd=str(cwd or REPO_ROOT))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_json(cmd: list[str]):
    code, out = run(cmd)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def orca_bin() -> str:
    import shutil
    return shutil.which("orca") or shutil.which("orca-ide") or "orca"


# --------------------------------------------------------------------------
# 1. 기계 게이트
# --------------------------------------------------------------------------

def gate(coord, number: int) -> tuple[bool, str, list[str]]:
    """(통과 여부, 브랜치명, 사유 목록). 사유가 비어 있어야 통과다."""
    head = run_json(["gh", "pr", "view", str(number), "--repo", coord.REPO, "--json",
                     "number,title,headRefName,isDraft,mergeable,state,"
                     "files,statusCheckRollup"])
    if not head:
        return False, "", [f"PR #{number} 조회 실패 — gh 가 JSON 을 돌려주지 않았다"]

    pr = coord.PR(number=head["number"], title=head["title"], head=head["headRefName"],
                  draft=head["isDraft"], mergeable=head.get("mergeable", "?"))
    pr.files = [f["path"] for f in head.get("files") or []]
    pr.checks = head.get("statusCheckRollup") or []

    reasons: list[str] = []
    if head.get("state") != "OPEN":
        reasons.append(f"열려 있지 않다 (state={head.get('state')})")
    if pr.draft:
        reasons.append("draft 다")
    if pr.mergeable == "CONFLICTING":
        reasons.append("충돌 — 워커에게 리베이스를 지시한다")
    if pr.ci != "통과":
        reasons.append(f"CI={pr.ci} — SPEC D-10 은 CI 초록 없이 머지를 금지한다")
    reasons.extend(pr.violations())

    print(f"  PR #{pr.number} [{pr.head}]")
    print(f"    {pr.title[:72]}")
    ambiguous = (f" (후보 {len(pr.covering_workers)} — 라벨을 믿지 말고 브랜치를 봐라)"
                 if len(pr.covering_workers) > 1 else "")
    print(f"    CI={pr.ci}  파일={len(pr.files)}  "
          f"추정소유자={pr.owner_guess or '불명'}{ambiguous}")
    return (not reasons), pr.head, reasons


# --------------------------------------------------------------------------
# 3. Orca 워크트리 — 브랜치를 놓게 만든다
# --------------------------------------------------------------------------

def worktrees_holding(branch: str) -> list[str]:
    """이 브랜치를 체크아웃한 Orca 워크트리 id 목록. 없으면 빈 목록."""
    data = run_json([orca_bin(), "worktree", "list", "--json"])
    if not data or not data.get("ok"):
        print("    ! orca worktree list 실패 — Orca 런타임이 떠 있는지 본다")
        return []
    out = []
    for wt in data["result"].get("worktrees") or []:
        if wt.get("isMainWorktree"):
            continue
        ref = (wt.get("branch") or "").removeprefix("refs/heads/")
        if ref == branch:
            out.append(wt["id"])
    return out


def drop_worktrees(branch: str) -> list[str]:
    """워커 워크트리를 제거해 브랜치를 놓게 만든다.

    ★ **종료코드를 믿지 않고 재조회로 확인한다.** PR #59 를 머지할 때 `worktree rm` 이
    `runtime_unavailable`(exit 1)로 실패를 보고했는데 **워크트리는 실제로 지워져 있었다** —
    런타임이 효과를 적용한 뒤 응답 전에 연결을 끊었다. 이 환경에서 두 번째로 보는 부류이며
    (`worker-start` 의 exit 255 도 같다), 종료코드만 보면 **성공을 실패로 보고**한다.
    거짓 경보가 쌓이면 진짜 경보를 아무도 안 보게 되므로, 사실을 다시 물어본다.
    """
    problems: list[str] = []
    for wt_id in worktrees_holding(branch):
        code, out = run([orca_bin(), "worktree", "rm", "--worktree", f"id:{wt_id}",
                         "--force", "--json"])
        if code == 0:
            print(f"    워크트리 제거 {wt_id} -> exit=0")
            continue
        # 실패를 보고했다. 정말 남아 있는가를 사실로 확인한다.
        still_there = wt_id in worktrees_holding(branch)
        state = "남아 있다" if still_there else "이미 지워졌다 (보고만 실패)"
        print(f"    워크트리 제거 {wt_id} -> exit={code} · 재조회: {state}")
        if still_there:
            problems.append(f"워크트리 제거 실패: {wt_id}\n{out.strip()[:400]}")
    return problems


def dirty_tracked_files() -> list[str]:
    """추적 중인 파일의 커밋되지 않은 변경 목록. 비어 있어야 머지를 시작한다.

    `refresh_main()` 이 `git reset --hard` 를 쓰므로 이 목록이 비어 있지 않으면
    **그 변경이 지워진다.** PR #56 의 ⑥-3 에 위험으로 적어 두었고, 코디네이터가
    실제로 [머지를 기다리는 동안 SPEC 을 미리 고쳐 두자] 는 판단을 하다가 멈췄다.
    기다리는 시간이 길수록 그 유혹이 커지므로 규율이 아니라 검사로 막는다.

    추적되지 않는 파일(`??`)은 `reset --hard` 가 건드리지 않으므로 세지 않는다.
    """
    code, out = run(["git", "status", "--porcelain"])
    if code != 0:
        return ["git status 실패 — 안전을 확인할 수 없다"]
    return [line for line in out.splitlines()
            if line.strip() and not line.startswith("??")]


def refresh_main() -> list[str]:
    """코디네이터 워크트리를 main 으로 옮기고 원격에 맞춘다.

    브랜치 삭제보다 **먼저** 불러야 한다 — 코디네이터가 자기 PR 을 머지하는 경우
    그 브랜치가 여기 체크아웃돼 있고, `git branch -D` 는 그것을 거부한다.
    """
    problems: list[str] = []
    for cmd in (["git", "checkout", "main"], ["git", "fetch", "origin"],
                ["git", "reset", "--hard", "origin/main"]):
        code, out = run(cmd)
        print(f"    {' '.join(cmd)} -> exit={code}")
        if code != 0:
            problems.append(f"{' '.join(cmd)} 실패\n{out.strip()[:400]}")
    return problems


def cleanup(branch: str) -> list[str]:
    """머지된 브랜치의 흔적을 지운다. 실패는 죽이지 않고 모아서 보고한다."""
    problems: list[str] = []

    code, out = run(["git", "push", "origin", "--delete", branch])
    print(f"    원격 브랜치 삭제 -> exit={code}")
    if code != 0 and "remote ref does not exist" not in out:
        problems.append(f"원격 브랜치 삭제 실패: {branch}\n{out.strip()[:400]}")

    code, _ = run(["git", "rev-parse", "--verify", f"refs/heads/{branch}"])
    if code == 0:
        # squash 머지는 원본 커밋을 main 의 조상으로 만들지 않으므로 -d 는 거부한다.
        # 정본은 PR 상태이고, 여기 오는 시점에 PR 은 이미 MERGED 다.
        code, out = run(["git", "branch", "-D", branch])
        print(f"    로컬 브랜치 삭제 -> exit={code}")
        if code != 0:
            problems.append(f"로컬 브랜치 삭제 실패: {branch}\n{out.strip()[:400]}")

    run(["git", "worktree", "prune"])
    return problems


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    ap = argparse.ArgumentParser(description="PR 머지 + 정리 (COORDINATION.md 절차)")
    ap.add_argument("number", type=int, help="PR 번호")
    ap.add_argument("--reviewed", action="store_true",
                    help="PR 본문의 SPEC 9.3 여섯 항목을 사람이 읽었다. 없으면 머지하지 않는다")
    ap.add_argument("--dry-run", action="store_true", help="게이트만 보고 아무것도 하지 않는다")
    args = ap.parse_args(argv)

    coord = _load_coord_status()

    print("=" * 78)
    print(f"  머지 게이트 — PR #{args.number}")
    print("=" * 78)

    # 게이트보다 먼저 본다. 여기서 멈추면 아무것도 하지 않은 것이고,
    # 뒤에서 멈추면 이미 머지가 끝난 뒤라 되돌릴 것이 생긴다.
    dirty = dirty_tracked_files()
    if dirty and not args.dry_run:
        print("\n[ 안전 검사 불통과 ] 코디네이터 워크트리에 커밋되지 않은 변경이 있다")
        for line in dirty[:20]:
            print(f"  ✗ {line}")
        print("\n  이 절차는 `git reset --hard origin/main` 을 쓴다. 위 변경은 **지워진다.**")
        print("  커밋하거나 stash 한 뒤 다시 부른다. 머지하지 않았다.")
        return 5
    if dirty:
        print("\n[ 경고 ] 커밋되지 않은 변경이 있다 — 실제 실행은 여기서 거부된다")
        for line in dirty[:20]:
            print(f"  · {line}")

    ok, branch, reasons = gate(coord, args.number)

    if reasons:
        print("\n[ 기계 게이트 불통과 ]")
        for r in reasons:
            print(f"  ✗ {r}")
        print("\n머지하지 않았다.")
        return 1
    print("\n[ 기계 게이트 통과 ]  CI · 소유 경로 · 계약 파일 · 충돌 · draft")

    print("\n[ 사람이 읽어야 하는 것 — 자동화하지 않는다 ]")
    for line in (
        "PR 본문에 SPEC 9.3 여섯 항목의 답이 있는가 (특히 ③ 실행 명령·출력)",
        "⑥ 미검증 목록이 비어 있으면 반려한다 — 비어 있는 경우는 사실상 없다",
        "새 상수에 Provenance 가 붙었는가",
        "값을 지어내지 않았는가 — 실사 미정 항목을 그럴듯한 수치로 메웠는지",
    ):
        print(f"  · {line}")

    if args.dry_run:
        print("\n--dry-run 이므로 여기서 멈춘다.")
        return 0
    if not args.reviewed:
        print("\n✗ --reviewed 가 없다. 위 넷을 읽고 나서 다시 부른다.")
        return 2

    print(f"\n[ 머지 ]  squash · --delete-branch 를 쓰지 않는다 (워크트리가 먼저다)")
    code, out = run(["gh", "pr", "merge", str(args.number), "--repo", coord.REPO, "--squash"])
    print(out.strip()[:600])
    if code != 0:
        print("\n✗ 머지 실패. 정리 단계로 넘어가지 않는다.")
        return 3

    print(f"\n[ 워크트리 ]  브랜치 {branch} 를 잡고 있는 것")
    problems = drop_worktrees(branch)

    print("\n[ main 갱신 ]  코디네이터 워크트리도 브랜치를 놓아야 한다")
    problems += refresh_main()

    print(f"\n[ 브랜치 삭제 ]  {branch}")
    problems += cleanup(branch)

    print("\n[ main 의 CI ]  PR CI 는 strict 가 아니라 구 base 에서 돌았을 수 있다")
    runs = run_json(["gh", "run", "list", "--repo", coord.REPO, "--branch", "main",
                     "--limit", "1", "--json", "status,conclusion,headSha,displayTitle"])
    for r in runs or []:
        print(f"    {r.get('status')}/{r.get('conclusion')}  {r.get('headSha','')[:8]}  "
              f"{(r.get('displayTitle') or '')[:50]}")
    if not runs:
        print("    (아직 없음 — 잠시 뒤 다시 본다)")

    if problems:
        print("\n[ 남은 문제 — 손으로 닫는다 ]")
        for p in problems:
            print(f"  ✗ {p}")
        return 4

    print("\n완료. 정상 상태는 main + 열린 PR 브랜치뿐이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
