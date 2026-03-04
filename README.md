# TODO Backlog Scanner

A Python CLI tool that scans codebases for `TODO`, `FIXME`, `HACK`, and `XXX` comments, then generates a prioritized `BACKLOG.md` to help teams make informed decisions during sprint planning.

## Usage

```bash
# Scan current directory
python backlog_scanner.py

# Scan a specific repo
python backlog_scanner.py --root /path/to/repo

# Custom include/exclude patterns
python backlog_scanner.py --include "**/*.py" --include "**/*.js" --exclude "tests/**"

# Verbose output
python backlog_scanner.py --verbose
```

## Features

- Detects `TODO:`, `FIXME:`, `HACK:`, `XXX:` markers (case-insensitive)
- Deduplicates exact matches, keeping the first occurrence alphabetically
- Clusters items by module/package structure (Python, JS/TS, Java)
- Assigns priority scores (1–10) based on impact, effort, and confidence heuristics
- Generates a formatted `BACKLOG.md` with summary, top 10 priorities, and per-module breakdown
- Verifies scan completeness by re-scanning after generation

## Requirements

- Python 3.13+

## Output

The tool writes `BACKLOG.md` to the repository root with:

- Summary: total count, duplicates removed, marker type breakdown
- Top 10 highest priority items
- Items grouped by detected module

## Priority Scoring

`priority = impact + confidence - effort` (clamped 1–10)

- Impact (1–5): keyword-based (e.g., SECURITY/CRITICAL = 5, BUG/FIXME = 4, TODO = 3)
- Effort (1–3): based on comment length
- Confidence (+1): boost if an issue ID pattern (`#123` or `ABC-123`) is present

## Development

Quality checks:

```bash
python -m mypy backlog_scanner.py --strict
```

See `tasks/` for PRDs covering the original implementation and a planned refactoring to adopt modern Python 3.13 idioms, stronger typing, and tooling configuration.
