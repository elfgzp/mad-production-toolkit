#!/usr/bin/env python3
"""Validate the distributable plugin and execute each skill's synthetic tests."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "mad-production-toolkit"
SKILLS = PLUGIN / "skills"
EXPECTED = {
    "mad-source-assets", "mad-plan-shots", "mad-align-stems",
    "mad-time-lyrics", "mad-mix-audio", "mad-edit-video",
    "mad-deliver-project",
}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate() -> None:
    portable = json.loads((PLUGIN / "plugin.json").read_text())
    legacy = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    check(portable["name"] == legacy["name"] == "mad-production-toolkit", "manifest names differ")
    check(portable["version"] == legacy["version"], "manifest versions differ")
    check(market["plugins"][0]["name"] == portable["name"], "marketplace name differs")
    check(market["plugins"][0]["source"]["path"] == "./plugins/mad-production-toolkit", "marketplace path differs")
    for manifest in (portable["extensions"]["com.openai"], legacy):
        interface = manifest["interface"]
        for field in ("composerIcon", "logo"):
            path = (PLUGIN / interface[field]).resolve()
            check(path.is_file() and path.is_relative_to(PLUGIN), f"missing icon {path}")
    names = {item.name for item in SKILLS.iterdir() if (item / "SKILL.md").is_file()}
    check(names == EXPECTED, f"unexpected skill names: {names ^ EXPECTED}")
    for name in sorted(names):
        content = (SKILLS / name / "SKILL.md").read_text()
        check(content.startswith("---\n"), f"{name}: missing YAML frontmatter")
        front = content.split("---", 2)[1]
        check(f"name: {name}" in front and "description:" in front,
              f"{name}: missing name or description")
        check("[TODO:" not in content, f"{name}: unfinished placeholder")
        for folder in ("scripts", "tests"):
            check((SKILLS / name / folder).is_dir(), f"{name}: missing {folder}")
    for document in ROOT.rglob("*.md"):
        if ".git" in document.parts:
            continue
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            local = target.split("#", 1)[0]
            if not local or "://" in local or local.startswith("/"):
                continue
            destination = (document.parent / local).resolve()
            check(destination.exists(), f"{document}: broken link {target}")
    print(f"Validated {len(names)} skills and plugin metadata")


def run_tests() -> None:
    for name in sorted(EXPECTED):
        tests = SKILLS / name / "tests"
        print(f"\n== {name} ==", flush=True)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(tests),
                        "-p", "test_*.py", "-v"], check=True)
    integration = ROOT / "tests"
    if integration.is_dir() and any(integration.glob("test_*.py")):
        print("\n== end-to-end integration ==", flush=True)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(integration),
                        "-p", "test_*.py", "-v"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-tests", action="store_true")
    args = parser.parse_args()
    validate()
    if not args.no_tests:
        run_tests()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
