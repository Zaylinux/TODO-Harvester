#!/usr/bin/env python3
"""TODO Backlog Scanner - Scans codebases for TODO/FIXME/HACK/XXX comments."""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


# Regex pattern to detect TODO markers (case-insensitive)
# Matches: TODO, FIXME, HACK, XXX (with optional colon)
TODO_PATTERN = re.compile(
    r"(?P<marker>TODO|FIXME|HACK|XXX):?\s*(?P<text>.*)",
    re.IGNORECASE,
)

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


def scan_file(file_path: Path, root: Path) -> tuple[list[TodoItem], bool]:
    """
    Scan a single file for TODO markers.

    Returns (items, success). success=False if file could not be read.
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
    except OSError:
        return [], False
    return items, True


def scan_repository(
    root: Path,
    includes: list[str],
    excludes: list[str],
    verbose: bool = False,
) -> ScanResult:
    """Scan a repository for TODO markers and return results."""
    result = ScanResult()

    for file_path in iter_files(root, includes, excludes):
        items, success = scan_file(file_path, root)
        if success:
            result.files_scanned += 1
            result.items.extend(items)
            if verbose and items:
                for item in items:
                    rel = file_path.relative_to(root)
                    print(f"  [{item.marker.upper()}] {rel}:{item.line_number} - {item.text}")
        else:
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
    """Validate and resolve CLI arguments."""
    root = args.root.resolve()
    if not root.exists():
        print(f"Error: root path does not exist: {root}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"Error: root path is not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    includes: list[str] = args.includes if args.includes is not None else ["**/*"]
    excludes: list[str] = args.excludes if args.excludes is not None else list(DEFAULT_EXCLUDES)

    return root, includes, excludes


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the backlog scanner CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    root, includes, excludes = resolve_args(args)

    print(f"Scanning: {root}")
    print(f"  Include patterns : {includes}")
    print(f"  Exclude patterns : {excludes}")

    if args.verbose:
        print("\nFound items:")

    result = scan_repository(root, includes, excludes, verbose=args.verbose)
    print_summary(result, root)

    return 0


if __name__ == "__main__":
    sys.exit(main())
