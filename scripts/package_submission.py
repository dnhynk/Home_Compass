"""Create a deterministic, secret-safe Home_Compass source archive.

The archive contains the tracked repository plus non-ignored files in the
working tree. Generated output, local profiles, virtual environments, and
credentials are deliberately excluded. A hash manifest inside the ZIP makes
the exact handoff inspectable without extracting it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "output" / "submission" / "Home_Compass_source.zip"
ROOT_IN_ZIP = PurePosixPath("Home_Compass")

EXCLUDED_TOP_LEVEL = {".git", ".venv", "output", "tmp"}
FORBIDDEN_NAMES = {
    ".env",
    "submission_profile.local.json",
    "id_rsa",
    "id_ed25519",
}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


def _git_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if relative.parts and relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if relative.name in FORBIDDEN_NAMES or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"refusing to package credential-like file: {relative}")
        absolute = (REPO_ROOT / relative).resolve()
        absolute.relative_to(REPO_ROOT.resolve())
        if absolute.is_file():
            paths.append(relative)
    return sorted(set(paths), key=lambda item: item.as_posix())


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout.strip()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def build(output: Path) -> tuple[int, str]:
    files = _git_files()
    entries: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    for relative in files:
        payload = (REPO_ROOT / relative).read_bytes()
        archive_name = (ROOT_IN_ZIP / PurePosixPath(relative.as_posix())).as_posix()
        payloads.append((archive_name, payload))
        entries.append({
            "path": relative.as_posix(),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    manifest = {
        "project": "Home_Compass",
        "baseGitCommit": _git_commit(),
        "workingTreeIncluded": True,
        "fileCount": len(entries),
        "files": entries,
    }
    manifest_payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_name = (ROOT_IN_ZIP / "SUBMISSION_MANIFEST.json").as_posix()

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in payloads:
            archive.writestr(_zip_info(name), payload)
        archive.writestr(_zip_info(manifest_name), manifest_payload)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return len(entries), digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Home_Compass source submission ZIP")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    count, digest = build(output)
    print(output)
    print(f"files={count} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
