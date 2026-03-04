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
from enum import Enum
from pathlib import Path
from typing import Protocol

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


class Marker(str, Enum):
    """Recognized TODO marker types."""

    TODO = "TODO"
    FIXME = "FIXME"
    HACK = "HACK"
    XXX = "XXX"


DEFAULT_EXCLUDES: list[str] = [
    "node_modules",
    "target",
    "dist",
    ".git",
    "build",
    ".next",
]


IMPACT_KEYWORDS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bSECURITY\b|DATA\s+LOSS|\bP0\b|\bCRITICAL\b"), 5),
    (re.compile(r"\bBUG\b|\bFIXME\b"), 4),
    (re.compile(r"\bTODO\b"), 3),
    (re.compile(r"\bREFACTOR\b|\bCLEANUP\b"), 2),
    (re.compile(r"NICE\s+TO\s+HAVE"), 1),
]

EFFORT_SHORT: int = 50
EFFORT_LONG: int = 150

MIN_PRIORITY: int = 1
MAX_PRIORITY: int = 10


@dataclass(slots=True, frozen=True)
class TodoItem:
    """Represents a single TODO/FIXME/HACK/XXX comment found in a file."""

    marker: Marker
    text: str
    file_path: Path
    line_number: int
    raw_line: str

    def __post_init__(self) -> None:
        """Validate TodoItem fields on creation."""
        if self.line_number <= 0:
            raise ValueError(f"line_number must be > 0, got {self.line_number}")
        if not isinstance(self.marker, Marker):
            msg = f"Invalid marker {self.marker!r}; must be a Marker enum value"
            raise ValueError(msg)

    @property
    def normalized_text(self) -> str:
        """Whitespace-normalized comment text for deduplication."""
        return " ".join(self.text.split())

    @property
    def full_text(self) -> str:
        """Full marker + text representation."""
        return f"{self.marker.value}: {self.text.strip()}"

    @property
    def priority(self) -> int:
        """Compute priority score (1-10): impact + confidence_boost - effort."""
        return priority_score(self)


@dataclass(slots=True)
class ScanResult:
    """Result of a repository scan."""

    items: list[TodoItem] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    duplicates_removed: int = 0

    @property
    def total(self) -> int:
        """Total number of TODO items in the scan result."""
        return len(self.items)

    def by_marker(self) -> dict[Marker, list[TodoItem]]:
        """Group items by marker type."""
        result: dict[Marker, list[TodoItem]] = {}
        for item in self.items:
            result.setdefault(item.marker, []).append(item)
        return result

    def by_module(self, root: Path) -> dict[str, list[TodoItem]]:
        """Group items by detected module/package cluster."""
        clusters: dict[str, list[TodoItem]] = {}
        for item in self.items:
            module = detect_module(item.file_path, root)
            clusters.setdefault(module, []).append(item)
        return clusters

    def deduplicate(self) -> None:
        """Deduplicate by (marker, normalized_text), keeping first occurrence."""
        # Sort by file path so the first alphabetical occurrence is kept
        self.items.sort(key=lambda item: str(item.file_path))
        seen: set[tuple[Marker, str]] = set()
        unique: list[TodoItem] = []
        for item in self.items:
            key = (item.marker, item.normalized_text)
            if key not in seen:
                seen.add(key)
                unique.append(item)
            else:
                self.duplicates_removed += 1
        self.items = unique


def _impact_score(item: TodoItem) -> int:
    """Return impact score (1-5); highest-priority keyword match wins."""
    combined = f"{item.marker.value} {item.text}".upper()
    for pattern, score in IMPACT_KEYWORDS:
        if pattern.search(combined):
            return score
    return 3  # default: TODO level


def _effort_score(item: TodoItem) -> int:
    """Return effort score (1-3) based on normalized text length."""
    length = len(item.normalized_text)
    if length < EFFORT_SHORT:
        return 1
    if length <= EFFORT_LONG:
        return 2
    return 3


def _confidence_boost(item: TodoItem) -> int:
    """Return +1 if comment includes an issue ID (#123 or ABC-123), else 0."""
    return 1 if ISSUE_ID_RE.search(item.text) else 0


def priority_score(item: TodoItem) -> int:
    """Calculate priority score = impact + confidence_boost - effort, clamped 1-10."""
    score = _impact_score(item) + _confidence_boost(item) - _effort_score(item)
    return max(MIN_PRIORITY, min(MAX_PRIORITY, score))


class ModuleDetector(Protocol):
    """Callable protocol for module/package detection from a source file."""

    def __call__(self, file_path: Path, root: Path) -> str | None:
        """Detect module name for file_path relative to root, or None."""
        ...


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


def _detect_java_module(file_path: Path, root: Path) -> str | None:  # noqa: ARG001
    """Extract Java package declaration from file."""
    try:
        with file_path.open(encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                m = JAVA_PACKAGE_RE.match(line)
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


_DETECTOR_REGISTRY: dict[str, ModuleDetector] = {
    ".py": _detect_python_module,
    ".js": _detect_js_module,
    ".ts": _detect_js_module,
    ".jsx": _detect_js_module,
    ".tsx": _detect_js_module,
    ".mjs": _detect_js_module,
    ".cjs": _detect_js_module,
    ".java": _detect_java_module,
}


def detect_module(file_path: Path, root: Path) -> str:
    """
    Detect the module/package cluster name for a file.

    Dispatches to a registered `ModuleDetector` by file extension. Fallback:
    top-level directory under root, or "(root)" if file is at root level.
    """
    try:
        relative = file_path.relative_to(root)
    except ValueError:
        return file_path.parent.name or "(root)"

    parts = relative.parts
    if len(parts) <= 1:
        return "(root)"

    ext = file_path.suffix.lower()
    detector = _DETECTOR_REGISTRY.get(ext)
    module: str | None = detector(file_path, root) if detector is not None else None

    return module if module is not None else parts[0]


def is_excluded(path: Path, root: Path, excludes: list[str]) -> bool:
    """Return True if any part of path matches an exclude pattern."""
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
        if fnmatch.fnmatch(relative_str, pattern) or fnmatch.fnmatch(
            path.name, pattern
        ):
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


def scan_file(file_path: Path, root: Path) -> Iterator[TodoItem]:
    """
    Scan a single file for TODO markers, yielding items lazily.

    Raises FileReadError if the file cannot be read.
    """
    try:
        with file_path.open(encoding="utf-8", errors="ignore") as f:
            for line_number, line in enumerate(f, start=1):
                match = TODO_PATTERN.search(line)
                if match:
                    yield TodoItem(
                        marker=Marker(match.group("marker").upper()),
                        text=match.group("text").strip(),
                        file_path=file_path,
                        line_number=line_number,
                        raw_line=line.rstrip(),
                    )
    except OSError as e:
        raise FileReadError(f"Cannot read file: {file_path}") from e


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
            rel_display = ""
            if verbose:
                try:
                    rel_display = str(file_path.relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel_display = str(file_path)
            for item in scan_file(file_path, root):
                result.items.append(item)
                if verbose:
                    print(
                        f"  [{item.marker.value}] {rel_display}:{item.line_number}"
                        f" - {item.text}"
                    )
            result.files_scanned += 1
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
        for marker in Marker:
            count = len(by_marker.get(marker, []))
            if count:
                print(f"    {marker.value:8}: {count}")

    clusters = result.by_module(root)
    if clusters:
        print("\n  By module:")
        for module_name, module_items in sorted(clusters.items()):
            print(f"    {module_name}: {len(module_items)}")


def _backlog_lines(result: ScanResult, root: Path) -> Iterator[str]:
    """Yield BACKLOG.md lines lazily."""
    yield "# TODO Backlog"
    yield ""
    yield f"Generated: {date.today().isoformat()}"
    yield ""

    # Summary section
    yield "## Summary"
    yield ""
    yield f"- **Total**: {result.total} items"
    yield f"- **Duplicates removed**: {result.duplicates_removed}"
    yield f"- **Files scanned**: {result.files_scanned}"
    yield ""

    by_marker = result.by_marker()
    yield "### By Marker Type"
    yield ""
    yield "| Marker | Count |"
    yield "|--------|-------|"
    for marker in Marker:
        count = len(by_marker.get(marker, []))
        yield f"| {marker.value:<6} | {count:<5} |"
    yield ""

    # Top 10 highest priority items
    yield "## Top 10 Highest Priority Items"
    yield ""
    sorted_items = sorted(result.items, key=lambda x: x.priority, reverse=True)
    for rank, item in enumerate(sorted_items[:10], start=1):
        try:
            rel_path: Path = item.file_path.relative_to(root)
        except ValueError:
            rel_path = item.file_path
        rel_str = str(rel_path).replace("\\", "/")
        issue_match = ISSUE_ID_RE.search(item.text)
        issue_suffix = f" ({issue_match.group()})" if issue_match else ""
        heading = (
            f"### {rank}. [Score: {item.priority}] {item.marker.value}"
            f" — `{rel_str}:{item.line_number}`"
        )
        yield heading
        yield ""
        yield f"> {item.normalized_text}{issue_suffix}"
        yield ""
        yield "---"
        yield ""

    # By module section
    yield "## By Module"
    yield ""
    clusters = result.by_module(root)
    for module_name, module_items in sorted(clusters.items()):
        count = len(module_items)
        yield f"### {module_name} ({count} item{'s' if count != 1 else ''})"
        yield ""
        for item in sorted(module_items, key=lambda x: x.priority, reverse=True):
            try:
                item_rel: Path = item.file_path.relative_to(root)
            except ValueError:
                item_rel = item.file_path
            item_rel_str = str(item_rel).replace("\\", "/")
            m = ISSUE_ID_RE.search(item.text)
            item_issue = f" ({m.group()})" if m else ""
            loc = f"`{item_rel_str}:{item.line_number}`"
            yield (
                f"- **[{item.priority}]** `{item.marker.value}` "
                f"{loc} — {item.normalized_text}{item_issue}"
            )
        yield ""


def generate_backlog_md(result: ScanResult, root: Path) -> str:
    """Generate BACKLOG.md content as a string."""
    return "\n".join(_backlog_lines(result, root))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="backlog_scanner",
        description=(
            "Scan a codebase for TODO/FIXME/HACK/XXX comments"
            " and generate a prioritized backlog."
        ),
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
        help=(
            "File patterns to include (default: **/*). "
            "Can be specified multiple times."
        ),
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
    excludes: list[str] = (
        args.excludes if args.excludes is not None else list(DEFAULT_EXCLUDES)
    )

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
        f"✗ Verification failed: original scan={original_count},"
        f" re-scan={verification.total}",
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
