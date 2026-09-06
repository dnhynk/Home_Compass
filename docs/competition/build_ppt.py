"""Build and verify the canonical Home_Compass technical deck.

The slide source lives in ``build_ppt.mjs`` and is rendered with Artifact Tool.
This Python entry point keeps the repository's documented command stable and
stores a manifest so CI can detect drift without requiring the authoring runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from pptx import Presentation


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DECK = HERE / "기술설명서_Home_Compass.pptx"
JS_BUILDER = HERE / "build_ppt.mjs"
MANIFEST = HERE / "technical_deck_manifest.json"
EXPECTED_SLIDES = 19
EXPECTED_SLIDE_SIZE_EMU = (12_191_695, 6_858_000)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_source_sha256(path: Path) -> str:
    """Hash UTF-8 source with platform line endings normalized to LF."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deck_text(path: str | os.PathLike[str] = DECK) -> list[str]:
    """Return all non-empty slide text in stable slide/shape order."""
    presentation = Presentation(str(path))
    result: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                value = "".join(run.text for run in paragraph.runs)
                if value.strip():
                    result.append(f"{slide_number:02d}|{value}")
    return result


def _text_sha256(path: Path = DECK) -> str:
    payload = json.dumps(
        deck_text(path), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _endpoint_counts() -> tuple[int, int, int]:
    """Return citizen, admin, and total endpoint counts from OpenAPI."""
    spec = json.loads(
        (REPO_ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8")
    )
    methods = {"get", "post", "put", "delete", "patch"}
    operations = [
        (path, method)
        for path, item in spec["paths"].items()
        for method in item
        if method in methods
    ]
    admin = sum(1 for path, _ in operations if path.startswith("/api/admin/"))
    auth = sum(1 for path, _ in operations if path.startswith("/api/auth/"))
    return len(operations) - admin - auth, admin, len(operations)


def _manifest_payload() -> dict[str, object]:
    presentation = Presentation(str(DECK))
    return {
        "schema": 1,
        "builder": JS_BUILDER.name,
        "builderSha256": _text_source_sha256(JS_BUILDER),
        "deck": DECK.name,
        "deckSha256": _sha256(DECK),
        "deckTextSha256": _text_sha256(DECK),
        "slideCount": len(presentation.slides),
        "slideSizeEmu": [presentation.slide_width, presentation.slide_height],
    }


def _write_manifest() -> None:
    MANIFEST.write_text(
        json.dumps(_manifest_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify() -> int:
    """Validate the committed deck against its source and manifest."""
    missing = [path for path in (JS_BUILDER, DECK, MANIFEST) if not path.is_file()]
    if missing:
        raise RuntimeError("missing technical-deck artifact: " + ", ".join(map(str, missing)))

    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = _manifest_payload()
    if expected != actual:
        differing = [key for key in actual if expected.get(key) != actual.get(key)]
        raise RuntimeError(
            "technical deck differs from build_ppt.mjs/manifest: " + ", ".join(differing)
        )

    if actual["slideCount"] != EXPECTED_SLIDES:
        raise RuntimeError(
            f"technical deck has {actual['slideCount']} slides; expected {EXPECTED_SLIDES}"
        )
    if tuple(actual["slideSizeEmu"]) != EXPECTED_SLIDE_SIZE_EMU:
        raise RuntimeError(
            f"technical deck size is {actual['slideSizeEmu']}; "
            f"expected {list(EXPECTED_SLIDE_SIZE_EMU)}"
        )
    print(
        f"OK  {DECK.name}: {actual['slideCount']} slides, "
        f"source/deck manifest matches"
    )
    return 0


def _first_existing(candidates: list[Path]) -> Path | None:
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _presentation_skill_dir() -> Path:
    configured = os.environ.get("PRESENTATIONS_SKILL_DIR")
    if configured and Path(configured).is_dir():
        return Path(configured)

    appdata = Path(os.environ.get("APPDATA", ""))
    matches = sorted(
        appdata.glob(
            "orca/codex-accounts/*/home/plugins/cache/"
            "openai-primary-runtime/presentations/*/skills/presentations"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]
    raise RuntimeError(
        "Artifact Tool presentation skill was not found. "
        "Set PRESENTATIONS_SKILL_DIR to its skills/presentations directory."
    )


def _authoring_environment() -> tuple[dict[str, str], Path]:
    user_root = Path(os.environ.get("USERPROFILE", Path.home()))
    dependencies = (
        user_root
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )
    node_candidates = [
        dependencies / "node" / "bin" / "node.exe",
        dependencies / "node" / "bin" / "node",
    ]
    if os.environ.get("RUNTIME_NODE"):
        node_candidates.insert(0, Path(os.environ["RUNTIME_NODE"]))
    node = _first_existing(node_candidates)

    python_candidates = [
        dependencies / "python" / "python.exe",
        dependencies / "python" / "bin" / "python",
    ]
    if os.environ.get("RUNTIME_PYTHON"):
        python_candidates.insert(0, Path(os.environ["RUNTIME_PYTHON"]))
    runtime_python = _first_existing(python_candidates)
    if node is None or runtime_python is None:
        raise RuntimeError(
            "Codex presentation runtime was not found; RUNTIME_NODE and "
            "RUNTIME_PYTHON may be set explicitly."
        )

    env = os.environ.copy()
    env.update(
        {
            "PRESENTATIONS_SKILL_DIR": str(_presentation_skill_dir()),
            "RUNTIME_NODE": str(node),
            "RUNTIME_NODE_MODULES": str(dependencies / "node" / "node_modules"),
            "RUNTIME_BIN_DIR": str(dependencies / "bin" / "override"),
            "RUNTIME_PYTHON": str(runtime_python),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "WORKSPACE_DIR": str(REPO_ROOT),
            "FINAL_PPTX": str(DECK),
        }
    )
    return env, node


def build() -> str:
    """Render, validate, and publish the canonical technical deck."""
    if not JS_BUILDER.is_file():
        raise RuntimeError(f"missing slide source: {JS_BUILDER}")
    env, node = _authoring_environment()
    subprocess.run(
        [str(node), str(JS_BUILDER)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    _write_manifest()
    verify()
    return str(DECK)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Home_Compass technical deck")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the committed deck and manifest without authoring it",
    )
    args = parser.parse_args(argv)
    if args.verify:
        return verify()
    build()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
