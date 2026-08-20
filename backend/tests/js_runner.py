"""프론트엔드 JS 를 **실제로 실행해** 출력을 보는 최소 하네스 (계약 결정 #36).

왜 실행하는가 — SPEC 9.1.1 이 「**판정 기준은 구현이 아니라 출력이다**」라고 못박았다.
파일을 파싱해 구조를 비교하는 검사는 *구현*을 보는 것이고, 그것을 9.1.1 만족이라고
부르면 검증한 척이 된다. 출력으로 판정하려면 실행하는 수밖에 없다.

**skip 하지 않는다.** `node` 가 없으면 이 파일을 쓰는 테스트는 **실패**한다. skip 은
「검사가 돌지 않았다」를 초록으로 칠하는 것이고, 이 저장소가 D-11 에서 금지한 침묵 폴백과
같은 것이다 (코디네이터 결정 2026-08-15, 조건 2).

**새 의존성은 없다.** pip 패키지도, npm install 도, 커밋된 번들도, CI 워크플로 단계도
추가하지 않는다 — 계약 결정 #31 이 막은 것은 빌드 툴체인이고 여기는 테스트 시점
인터프리터다. 파이썬은 `subprocess` 로 `node` 를 부르고 JSON 만 주고받는다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
GENERATED_DIR = FRONTEND_DIR / "generated"
CONTRACTS_DIR = REPO_ROOT / "contracts"

#: 브라우저가 `<script src>` 로 읽는 순서 그대로. 생성물이 먼저다 —
#: `local_engine.js` 가 `window.FIRSTHOME_*` 를 조회하기 때문이다.
GENERATED_FILES = (
    "contract_constants.js",
    "model_constants.js",
    "policy_rules.js",
    "regions.js",
)
FRONTEND_FILES = ("format.js", "local_engine.js")
#: 화면 코드까지 올릴 때. `app.js` 는 `typeof document !== 'undefined'` 로 부팅을 가드하므로
#: node 컨텍스트에서는 `FirstHomeCompass` 만 붙고 `init()` 은 돌지 않는다.
SCREEN_FILE = "app.js"


class NodeMissing(RuntimeError):
    """`node` 를 찾지 못했다. 무엇이 없어서 못 도는지를 메시지가 말한다."""


def node_executable() -> str:
    found = shutil.which("node")
    if found is None:
        raise NodeMissing(
            "PATH 에서 `node` 를 찾지 못해 JS 변을 실행할 수 없습니다 "
            "(SPEC 9.1.1 · 계약 결정 #36). 이 테스트는 skip 하지 않습니다 — "
            "skip 은 검사가 돌지 않은 상태를 초록으로 칠하는 것이고, "
            "그것이 D-11 이 금지한 침묵 폴백입니다. "
            "Node.js 를 설치하거나 CI 러너에 setup-node 를 넣어야 합니다."
        )
    return found


def node_version() -> str:
    return subprocess.run(
        [node_executable(), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()


def run_js(
    body: str,
    *,
    include_generated: bool = True,
    include_screen: bool = False,
    extra_globals: dict | None = None,
):
    """빈 컨텍스트에 프론트 파일들을 순서대로 올린 뒤 `body` 를 실행하고 반환값을 JSON 으로 받는다.

    `body` 는 표현식이 아니라 **문장들**이며 마지막에 `return` 한다 (함수 몸통에 들어간다).
    브라우저처럼 `window` 와 `globalThis` 가 같은 객체를 가리키게 해 둔다 —
    생성물은 `window.FIRSTHOME_*` 에, 프론트 모듈은 `globalThis` 에 붙기 때문이다.
    """
    files = []
    if include_generated:
        files += [str(GENERATED_DIR / name) for name in GENERATED_FILES]
    files += [str(FRONTEND_DIR / name) for name in FRONTEND_FILES]
    if include_screen:
        files.append(str(FRONTEND_DIR / SCREEN_FILE))

    payload = {
        "files": files,
        "globals": extra_globals or {},
        "body": body,
    }
    script = r"""
const fs = require('fs');
const vm = require('vm');
let input = '';
process.stdin.on('data', c => (input += c));
process.stdin.on('end', () => {
  const spec = JSON.parse(input);
  const context = {};
  context.window = context;
  context.globalThis = context;
  context.console = console;
  Object.assign(context, spec.globals);
  vm.createContext(context);
  for (const file of spec.files) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), context, { filename: file });
  }
  const fn = vm.runInContext('(function () {\n' + spec.body + '\n})', context);
  let out;
  try {
    out = { ok: true, value: fn() };
  } catch (err) {
    out = { ok: false, error: String(err && err.stack ? err.stack : err) };
  }
  process.stdout.write(JSON.stringify(out));
});
"""
    completed = subprocess.run(
        [node_executable(), "-e", script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"node 실행이 실패했습니다 (exit {completed.returncode}).\n"
            f"stderr:\n{completed.stderr}"
        )
    result = json.loads(completed.stdout)
    if not result["ok"]:
        raise RuntimeError("JS 쪽에서 예외가 났습니다:\n" + result["error"])
    return result["value"]


def load_golden_fixture() -> dict:
    """`contracts/format_golden.json` — **양쪽 테스트가 읽는 그 파일 하나**다 (9.1.1)."""
    return json.loads((CONTRACTS_DIR / "format_golden.json").read_text(encoding="utf-8"))
