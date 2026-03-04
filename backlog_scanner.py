#!/usr/bin/env python3
"""TODO Backlog Scanner - Scans codebases for TODO/FIXME/HACK/XXX comments."""

import argparse
import fnmatch
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


# Regex pattern to detect TODO markers (case-insensitive)
# Matches: TODO, FIXME, HACK, XXX (with optional colon)
TODO_PATTERN = re.compile(
    r"(?P<marker>TODO|FIXME|HACK|XXX):?\s*(?P<text>.*)",
    re.IGNORECASE,
)

JAVA_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;")

# Matches GitHub-style (#123) or Jira-style (ABC-123) issue IDs
ISSUE_ID_RE = re.compile(r"#\d+|[A-Z]+-\d+")

class ScannerError(Exception):
    """Base exception for backlog scanner errors."""


class FileReadError(ScannerError):
    """Raised when a file cannot be read due to an I/O failure."""


class ConfigError(ScannerError):
    """Raised for invalid CLI arguments or configuration."""


DEFAULT_EXCLUDES: list[str] = [
    "node_modules",
    "target",
    "dist",
    ".git",
    "build",
    ".next",
]


@dataclass
class TodoItem:
    """Represents a single TODO/FIXME/HACK/XXX comment found in a file."""

    marker: str
    text: str
    file_path: Path
    line_number: int
    raw_line: str

    @property
    def normalized_text(self) -> str:
        """Whitespace-normalized comment text for deduplication."""
        return " ".join(self.text.split())

    @property
    def full_text(self) -> str:
        """Full marker + text representation."""
        return f"{self.marker.upper()}: {self.text.strip()}"

    @property
    def priority(self) -> int:
        """Priority score (1-10): impact + confidence_boost - effort, clamped to 1-10."""
        return priority_score(self)


@dataclass
class ScanResult:
    """Result of a repository scan."""

    items: list[TodoItem] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    duplicates_removed: int = 0

    @property
    def total(self) -> int:
        return len(self.items)

    def by_marker(self) -> dict[str, list[TodoItem]]:
        """Group items by marker type."""
        result: dict[str, list[TodoItem]] = {}
        for item in self.items:
            key = item.marker.upper()
            result.setdefault(key, []).append(item)
        return result

    def by_module(self, root: Path) -> dict[str, list[TodoItem]]:
        """Group items by detected module/package cluster."""
        clusters: dict[str, list[TodoItem]] = {}
        for item in self.items:
            module = detect_module(item.file_path, root)
            clusters.setdefault(module, []).append(item)
        return clusters

    def deduplicate(self) -> None:
        """Deduplicate items by normalized text, keeping first occurrence by file path (alphabetical)."""
        # Sort by file path so the first alphabetical occurrence is kept
        self.items.sort(key=lambda item: str(item.file_path))
        seen: set[tuple[str, str]] = set()
        unique: list[TodoItem] = []
        for item in self.items:
            key = (item.marker.upper(), item.normalized_text)
            if key not in seen:
                seen.add(key)
                unique.append(item)
            else:
                self.duplicates_removed += 1
        self.items = unique


def _impact_score(item: TodoItem) -> int:
    """Return impact score (1-5) based on marker and text keywords (highest match wins)."""
    combined = f"{item.marker} {item.text}".upper()
    if re.search(r"\bSECURITY\b|DATA\s+LOSS|\bP0\b|\bCRITICAL\b", combined):
        return 5
    if re.search(r"\bBUG\b|\bFIXME\b", combined):
        return 4
    if re.search(r"\bTODO\b", combined):
        return 3
    if re.search(r"\bREFACTOR\b|\bCLEANUP\b", combined):
        return 2
    if re.search(r"NICE\s+TO\s+HAVE", combined):
        return 1
    return 3  # default: TODO level


def _effort_score(item: TodoItem) -> int:
    """Return effort score (1-3) based on normalized text length."""
    length = len(item.normalized_text)
    if length < 50:
        return 1
    if length <= 150:
        return 2
    return 3


def _confidence_boost(item: TodoItem) -> int:
    """Return +1 if comment includes an issue ID (#123 or ABC-123), else 0."""
    return 1 if ISSUE_ID_RE.search(item.text) else 0


def priority_score(item: TodoItem) -> int:
    """Calculate priority score = impact + confidence_boost - effort, clamped 1-10."""
    score = _impact_score(item) + _confidence_boost(item) - _effort_score(item)
    return max(1, min(10, score))


def _detect_python_module(file_path: Path, root: Path) -> str | None:
    """Find the top-level Python package containing this file (via __init__.py)."""
    top_pkg: Path | None = None
    current = file_path.parent
    while current != root:
        if current.parent == current:
            break
        if (current / "__init__.py").exists():
            top_pkg = current
        current = current.parent
    if top_pkg is None:
        return None
    try:
        pkg_rel = top_pkg.relative_to(root)
        return ".".join(pkg_rel.parts)
    except ValueError:
        return None


def _detect_js_module(file_path: Path, root: Path) -> str | None:
    """Find the nearest package.json for a JS/TS file and return its name."""
    current = file_path.parent
    while current != root:
        pkg_json = current / "package.json"
        if pkg_json.exists():
            try:
                raw = pkg_json.read_text(encoding="utf-8", errors="ignore")
                data: dict[str, object] = json.loads(raw)
                name = data.get("name")
                if isinstance(name, str) and name:
                    return name
                pkg_rel = current.relative_to(root)
                return ".".join(pkg_rel.parts)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        if current.parent == current:
            break
        current = current.parent
    return None


def _detect_java_module(file_path: Path) -> str | None:
    """Extract Java package declaration from file."""
    try:
        with file_path.open(encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                m = JAVA_PACKAGE_RE.match(line)
                if m:
                    return m.group(1)
    except OSError as e:
        raise FileReadError(f"Cannot read Java file: {file_path}") from e
    return None


def detect_module(file_path: Path, root: Path) -> str:
    """
    Detect the module/package cluster name for a file.

    Detection by file type:
    - .py  : top-level Python package (via __init__.py), else fallback
    - .js/.ts/.jsx/.tsx/.mjs/.cjs: nearest package.json name, else fallback
    - .java: package declaration in file, else fallback
    - Fallback: top-level directory under root, or "(root)" if file is at root level
    """
    try:
        relative = file_path.relative_to(root)
    except ValueError:
        return file_path.parent.name or "(root)"

    parts = relative.parts
    if len(parts) <= 1:
        return "(root)"

    ext = file_path.suffix.lower()
    module: str | None = None

    if ext == ".py":
        module = _detect_python_module(file_path, root)
    elif ext in {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}:
        module = _detect_js_module(file_path, root)
    elif ext == ".java":
        try:
            module = _detect_java_module(file_path)
        except FileReadError:
            module = None

    return module if module is not None else parts[0]


def is_excluded(path: Path, root: Path, excludes: list[str]) -> bool:
    """Return True if path is under an excluded directory or matches an exclude pattern."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False

    parts = relative.parts
    for exclude in excludes:
        # Check if any path component matches the exclude pattern
        for part in parts:
            if fnmatch.fnmatch(part, exclude):
                return True
    return False


def matches_include(path: Path, root: Path, includes: list[str]) -> bool:
    """Return True if path matches any of the include patterns."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False

    relative_str = str(relative).replace("\\", "/")
    for pattern in includes:
        if fnmatch.fnmatch(relative_str, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def iter_files(
    root: Path,
    includes: list[str],
    excludes: list[str],
) -> Iterator[Path]:
    """Yield all files under root that match include patterns and aren't excluded."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_excluded(path, root, excludes):
            continue
        if not matches_include(path, root, includes):
            continue
        yield path


def scan_file(file_path: Path, root: Path) -> list[TodoItem]:
    """
    Scan a single file for TODO markers.

    Raises FileReadError if the file cannot be read.
    """
    items: list[TodoItem] = []
    try:
        with file_path.open(encoding="utf-8", errors="ignore") as f:
            for line_number, line in enumerate(f, start=1):
                match = TODO_PATTERN.search(line)
                if match:
                    items.append(
                        TodoItem(
                            marker=match.group("marker"),
                            text=match.group("text").strip(),
                            file_path=file_path,
                            line_number=line_number,
                            raw_line=line.rstrip(),
                        )
                    )
    except OSError as e:
        raise FileReadError(f"Cannot read file: {file_path}") from e
    return items


def scan_repository(
    root: Path,
    includes: list[str],
    excludes: list[str],
    verbose: bool = False,
) -> ScanResult:
    """Scan a repository for TODO markers and return results."""
    result = ScanResult()

    for file_path in iter_files(root, includes, excludes):
        try:
            items = scan_file(file_path, root)
            result.files_scanned += 1
            result.items.extend(items)
            if verbose and items:
                for item in items:
                    rel = file_path.relative_to(root)
                    print(f"  [{item.marker.upper()}] {rel}:{item.line_number} - {item.text}")
        except FileReadError:
            result.files_skipped += 1

    result.deduplicate()
    return result


def print_summary(result: ScanResult, root: Path) -> None:
    """Print a summary of scan results to stdout."""
    print(f"\nScan complete: {root}")
    print(f"  Files scanned      : {result.files_scanned}")
    print(f"  Files skipped      : {result.files_skipped}")
    print(f"  Duplicates removed : {result.duplicates_removed}")
    print(f"  Total items        : {result.total}")

    by_marker = result.by_marker()
    if by_marker:
        print("\n  Breakdown by marker:")
        for marker in ["TODO", "FIXME", "HACK", "XXX"]:
            count = len(by_marker.get(marker, []))
            if count:
                print(f"    {marker:8}: {count}")

    clusters = result.by_module(root)
    if clusters:
        print("\n  By module:")
        for module_name, module_items in sorted(clusters.items()):
            print(f"    {module_name}: {len(module_items)}")


def generate_backlog_md(result: ScanResult, root: Path) -> str:
    """Generate BACKLOG.md content as a string."""
    lines: list[str] = []
    lines.append("# TODO Backlog")
    lines.append("")
    lines.append(f"Generated: {date.today().isoformat()}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total**: {result.total} items")
    lines.append(f"- **Duplicates removed**: {result.duplicates_removed}")
    lines.append(f"- **Files scanned**: {result.files_scanned}")
    lines.append("")

    by_marker = result.by_marker()
    lines.append("### By Marker Type")
    lines.append("")
    lines.append("| Marker | Count |")
    lines.append("|--------|-------|")
    for marker in ["TODO", "FIXME", "HACK", "XXX"]:
        count = len(by_marker.get(marker, []))
        lines.append(f"| {marker:<6} | {count:<5} |")
    lines.append("")

    # Top 10 highest priority items
    lines.append("## Top 10 Highest Priority Items")
    lines.append("")
    sorted_items = sorted(result.items, key=lambda x: x.priority, reverse=True)
    for rank, item in enumerate(sorted_items[:10], start=1):
        try:
            rel_path: Path = item.file_path.relative_to(root)
        except ValueError:
            rel_path = item.file_path
        rel_str = str(rel_path).replace("\\", "/")
        issue_match = ISSUE_ID_RE.search(item.text)
        issue_suffix = f" ({issue_match.group()})" if issue_match else ""
        lines.append(
            f"### {rank}. [Score: {item.priority}] {item.marker.upper()} — `{rel_str}:{item.line_number}`"
        )
        lines.append("")
        lines.append(f"> {item.normalized_text}{issue_suffix}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # By module section
    lines.append("## By Module")
    lines.append("")
    clusters = result.by_module(root)
    for module_name, module_items in sorted(clusters.items()):
        count = len(module_items)
        lines.append(f"### {module_name} ({count} item{'s' if count != 1 else ''})")
        lines.append("")
        for item in sorted(module_items, key=lambda x: x.priority, reverse=True):
            try:
                item_rel: Path = item.file_path.relative_to(root)
            except ValueError:
                item_rel = item.file_path
            item_rel_str = str(item_rel).replace("\\", "/")
            m = ISSUE_ID_RE.search(item.text)
            item_issue = f" ({m.group()})" if m else ""
            lines.append(
                f"- **[{item.priority}]** `{item.marker.upper()}` "
                f"`{item_rel_str}:{item.line_number}` — {item.normalized_text}{item_issue}"
            )
        lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="backlog_scanner",
        description="Scan a codebase for TODO/FIXME/HACK/XXX comments and generate a prioritized backlog.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        metavar="DIR",
        help="Repository root path (default: current directory)",
    )
    parser.add_argument(
        "--include",
        dest="includes",
        action="append",
        default=None,
        metavar="PATTERN",
        help="File patterns to include (default: **/*). Can be specified multiple times.",
    )
    parser.add_argument(
        "--exclude",
        dest="excludes",
        action="append",
        default=None,
        metavar="PATTERN",
        help=(
            "Directory/file patterns to exclude. Can be specified multiple times. "
            f"Defaults: {', '.join(DEFAULT_EXCLUDES)}"
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print each found item as it is discovered.",
    )
    return parser


def resolve_args(args: argparse.Namespace) -> tuple[Path, list[str], list[str]]:
    """Validate and resolve CLI arguments.

    Raises ConfigError if the root path is invalid.
    """
    root = args.root.resolve()
    if not root.exists():
        raise ConfigError(f"root path does not exist: {root}")
    if not root.is_dir():
        raise ConfigError(f"root path is not a directory: {root}")

    includes: list[str] = args.includes if args.includes is not None else ["**/*"]
    excludes: list[str] = args.excludes if args.excludes is not None else list(DEFAULT_EXCLUDES)

    return root, includes, excludes


def verify_completeness(
    original_count: int,
    root: Path,
    includes: list[str],
    excludes: list[str],
) -> int:
    """Re-scan repository and verify item count matches original scan.

    Returns 0 if counts match, 1 if they don't.
    """
    verification = scan_repository(root, includes, excludes)
    if verification.total == original_count:
        print(f"✓ Verified: captured {original_count} items")
        return 0
    print(
        f"✗ Verification failed: original scan={original_count}, re-scan={verification.total}",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for the backlog scanner CLI."""
    # Ensure UTF-8 output so Unicode characters (e.g. ✓) work on all platforms
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        root, includes, excludes = resolve_args(args)
    except ScannerError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Always exclude the generated BACKLOG.md so it doesn't pollute scans
    if "BACKLOG.md" not in excludes:
        excludes = excludes + ["BACKLOG.md"]

    print(f"Scanning: {root}")
    print(f"  Include patterns : {includes}")
    print(f"  Exclude patterns : {excludes}")

    if args.verbose:
        print("\nFound items:")

    result = scan_repository(root, includes, excludes, verbose=args.verbose)
    print_summary(result, root)

    backlog_path = root / "BACKLOG.md"
    content = generate_backlog_md(result, root)
    backlog_path.write_text(content, encoding="utf-8")
    print(f"\nBacklog written to: {backlog_path}")

    return verify_completeness(result.total, root, includes, excludes)


if __name__ == "__main__":
    sys.exit(main())
