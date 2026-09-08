from __future__ import annotations

import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SUFFIXES = {".py"}
SCRIPT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    ".build",
    "__pycache__",
    "generated",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "deck",
    "mockups",
    "new_plan",
}
SKIP_FILE_NAMES = {"complete_package.py", "revise_design.py"}
ALLOWED_PYTHON = (
    "noqa",
    "type: ignore",
    "type:ignore",
    "ruff:",
    "mypy:",
    "pragma:",
    "pyright:",
    "pylint:",
    "fmt:",
    "isort:",
    "spdx-",
    "copyright",
    "licen",
)
ALLOWED_SCRIPT = (
    "eslint-disable",
    "biome-ignore",
    "prettier-ignore",
    "@ts-expect-error",
    "@ts-ignore",
    "@ts-nocheck",
    "webpack",
    "vite-ignore",
    "spdx-",
    "copyright",
    "licen",
)


def is_skipped(path: Path) -> bool:
    return (
        any(part in SKIP_DIR_NAMES for part in path.parts)
        or path.name.startswith("._")
        or path.name in SKIP_FILE_NAMES
    )


def python_comment_allowed(text: str) -> bool:
    body = text.lstrip("#").strip().lower()
    if not body:
        return False
    return any(body.startswith(prefix) or prefix in body for prefix in ALLOWED_PYTHON)


def script_comment_allowed(text: str) -> bool:
    body = text.lstrip("/*").rstrip("*/").lstrip("/").strip().lower()
    if not body:
        return True
    return any(prefix in body for prefix in ALLOWED_SCRIPT)


def check_python(path: Path) -> list[str]:
    findings: list[str] = []
    source = path.read_bytes()
    try:
        tokens = tokenize.tokenize(io.BytesIO(source).readline)
    except tokenize.TokenError as exc:
        return [f"{path}: tokenize failed: {exc}"]
    except StopIteration:
        return []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if token.string.startswith("#!") or token.string.lower().startswith("# -*-"):
            continue
        if python_comment_allowed(token.string):
            continue
        findings.append(f"{path}:{token.start[0]}: comment is not allowed")
    return findings


REGEX_PREV = set("([{,;=!&|?:~^+-*%>\n\r")


def prev_significant(text: str, index: int) -> str:
    j = index - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    if j < 0:
        return "\n"
    return text[j]


def looks_like_regex(text: str, index: int) -> bool:
    nxt = text[index + 1] if index + 1 < len(text) else ""
    if nxt == ">":
        return False
    prev = prev_significant(text, index)
    if prev == "<":
        return False
    if prev in REGEX_PREV or prev in " \t":
        return True
    if prev.isalpha() or prev.isdigit() or prev in ")]}`'\"":
        return False
    return False


def check_script(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    i = 0
    n = len(text)
    line = 1
    in_single = False
    in_double = False
    in_template = False
    in_regex = False
    template_depth = 0
    while i < n:
        char = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if char == "\n":
            line += 1
        if in_single:
            if char == "\\" and nxt:
                i += 2
                continue
            if char == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if char == "\\" and nxt:
                i += 2
                continue
            if char == '"':
                in_double = False
            i += 1
            continue
        if in_template:
            if char == "\\" and nxt:
                i += 2
                continue
            if char == "`" and template_depth == 0:
                in_template = False
                i += 1
                continue
            if char == "$" and nxt == "{":
                template_depth += 1
                i += 2
                continue
            if char == "}" and template_depth:
                template_depth -= 1
                i += 1
                continue
            i += 1
            continue
        if in_regex:
            if char == "\\" and nxt:
                i += 2
                continue
            if char == "/":
                in_regex = False
            i += 1
            continue
        if char == "'":
            in_single = True
            i += 1
            continue
        if char == '"':
            in_double = True
            i += 1
            continue
        if char == "`":
            in_template = True
            i += 1
            continue
        if char == "/" and nxt == "/":
            end = text.find("\n", i)
            comment = text[i:] if end == -1 else text[i:end]
            if not script_comment_allowed(comment):
                findings.append(f"{path}:{line}: comment is not allowed")
            if end == -1:
                break
            i = end
            continue
        if char == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            comment = text[i:] if end == -1 else text[i : end + 2]
            if not script_comment_allowed(comment):
                findings.append(f"{path}:{line}: comment is not allowed")
            if end == -1:
                break
            line += comment.count("\n")
            i = end + 2
            continue
        if char == "/" and looks_like_regex(text, i):
            in_regex = True
            i += 1
            continue
        i += 1
    return findings


def main() -> int:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or is_skipped(path):
            continue
        if path.suffix in PYTHON_SUFFIXES:
            findings.extend(check_python(path))
        elif path.suffix in SCRIPT_SUFFIXES:
            findings.extend(check_script(path))
    if findings:
        print("\n".join(findings))
        print(f"{len(findings)} comment policy violations")
        return 1
    print("comment policy: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
