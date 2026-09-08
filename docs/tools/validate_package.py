from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BRIEF_FOLDERS = (
    "backend",
    "contracts",
    "data",
    "demo",
    "design",
    "driver-display",
    "engineer-console",
    "estimation",
    "learning",
    "operations",
    "planning",
    "rules",
    "simulation",
    "simulation-lab",
    "tracks",
    "validation",
)
MOCKUPS = (
    "index.html",
    "app.html",
    "driver.html",
    "concepts.html",
    "landing.html",
    "simulation.html",
)
SKIP_DIR_NAMES = {".build", "handoffs"}


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        for key in ("href", "src"):
            value = found.get(key)
            if value:
                self.links.append(value)
        identifier = found.get("id")
        if identifier:
            self.ids.append(identifier)


def iter_files(suffix: str) -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob(f"*{suffix}"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith("._"):
            continue
        files.append(path)
    return files


errors: list[str] = []


def check_link(path: Path, target: str) -> None:
    target = target.strip("<>")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return
    resolved = (path.parent / unquote(parsed.path)).resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        errors.append(f"{path.relative_to(ROOT)}: link escapes package: {target}")
        return
    if not resolved.exists():
        errors.append(f"{path.relative_to(ROOT)}: missing {target}")


markdown = iter_files(".md")
html = iter_files(".html")
jsonfiles = iter_files(".json")
for path in markdown:
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        check_link(path, target)
for path in html:
    parser = Links()
    parser.feed(path.read_text(encoding="utf-8"))
    for target in parser.links:
        check_link(path, target)
    if len(parser.ids) != len(set(parser.ids)):
        errors.append(f"{path.name}: duplicate static IDs")
for path in jsonfiles:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}: invalid JSON: {exc}")

schema = json.loads((ROOT / "contracts/schemas/telemetry-event.schema.json").read_text())
event = json.loads((ROOT / "contracts/schemas/telemetry-event.example.json").read_text())
if set(event) != set(schema["required"]):
    errors.append("Telemetry fixture fields mismatch")
if event["provenance"] != "simulated":
    errors.append("Fixture provenance must be simulated")
scenario = json.loads((ROOT / "simulation/scenario.example.json").read_text())
if scenario["observation"]["expose_rival_energy"]:
    errors.append("Fixture leaks rival energy")
if not scenario["synthetic"]:
    errors.append("Scenario is not marked synthetic")
for folder in BRIEF_FOLDERS:
    if not (ROOT / folder / "AGENT_BRIEF.md").exists():
        errors.append(f"{folder}: no agent brief")
for name in MOCKUPS:
    if not (ROOT / "design/mockups" / name).exists():
        errors.append(f"missing mockup {name}")

words = sum(len(re.findall(r"\b\w+\b", path.read_text(encoding="utf-8"))) for path in markdown)
print(
    f"{len(markdown)} Markdown files; {len(html)} HTML entrypoints; "
    f"{len(jsonfiles)} JSON files; approximately {words:,} documentation words."
)
print(
    "Checks: local links, static HTML IDs, JSON parsing, fixture provenance, "
    "hidden-state flag, agent briefs and mockup inventory."
)
if errors:
    print("\n".join(errors))
    sys.exit(1)
print("PASS")
