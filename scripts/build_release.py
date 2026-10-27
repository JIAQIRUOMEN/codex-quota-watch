#!/usr/bin/env python3
"""Build allowlisted source/tool and standalone skill ZIPs plus SHA256SUMS."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    ".gitignore", "LICENSE", "README.md", "pyproject.toml", "docs/INSTALL.md",
    "docs/index.html", "docs/cover.png",
    "src/codex_quota_watch/__init__.py", "src/codex_quota_watch/__main__.py",
    "src/codex_quota_watch/cli.py", "src/codex_quota_watch/core.py",
    "src/codex_quota_watch/daily.py",
    "src/codex_quota_watch/notifier.py", "src/codex_quota_watch/source.py",
    "src/codex_quota_watch/store.py", "src/codex_quota_watch/windows/Show-CodexQuotaAlert.ps1",
    "windows/Show-CodexQuotaAlert.ps1",
    "windows/Invoke-SmokeTest.ps1", "examples/announcement.json",
    "examples/baseline.json", "examples/confirmed.json",
    "tests/test_monitor.py", "tests/test_daily_pause.py", "tests/test_popup_language.py", "tests/popup_language_wpf_smoke.ps1", "tests/windows_gui_smoke.py", "tests/browser_extractor_smoke.cjs",
    "scripts/build_release.py", "skills/codex-quota-watch/SKILL.md",
    "skills/codex-quota-watch/references/browser-source.md",
    "skills/codex-quota-watch/scripts/extract-posts.js",
    ".github/workflows/release.yml", ".github/workflows/tests.yml",
)
SKILL_FILES = (
    "skills/codex-quota-watch/SKILL.md",
    "skills/codex-quota-watch/references/browser-source.md",
    "skills/codex-quota-watch/scripts/extract-posts.js",
)


def add_files(archive: zipfile.ZipFile, files: tuple[str, ...], root_prefix: str = "") -> None:
    for relative in files:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"required release file is missing: {relative}")
        archive.write(source, root_prefix + relative.replace("\\", "/"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_zip = output / "codex-quota-watch-source.zip"
    skill_zip = output / "codex-quota-watch-skill.zip"
    for path in (source_zip, skill_zip):
        if path.exists():
            path.unlink()
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        add_files(archive, SOURCE_FILES, "codex-quota-watch/")
    with zipfile.ZipFile(skill_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in SKILL_FILES:
            source = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(f"required release file is missing: {relative}")
            skill_relative = Path(relative).relative_to(Path("skills/codex-quota-watch"))
            archive.write(source, (Path("codex-quota-watch") / skill_relative).as_posix())
    sums = output / "SHA256SUMS"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in (source_zip, skill_zip)), encoding="ascii")
    print(f"Created {source_zip}\nCreated {skill_zip}\nCreated {sums}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
