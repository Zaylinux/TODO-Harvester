# PRD: TODO Backlog Scanner CLI

## Introduction

A Python CLI tool that scans codebases for TODO, FIXME, HACK, and XXX comments, then generates a prioritized backlog to help teams make informed decisions during sprint planning. The tool deduplicates entries, clusters them by module/package structure, assigns priority scores based on impact/effort/confidence heuristics, and outputs a human-readable BACKLOG.md file.

## Goals

- Automatically discover all technical debt markers (TODO/FIXME/HACK/XXX) in a repository
- Provide actionable priority scores to guide sprint planning decisions
- Cluster items by logical module/package boundaries for better organization
- Generate a clean, readable BACKLOG.md that teams can review in meetings
- Verify completeness by re-scanning and confirming all items were captured

## User Stories

### US-001: Scan repository for TODO markers
**Description:** As a developer, I want to scan my entire repository for TODO/FIXME/HACK/XXX comments so I can see all technical debt in one place.

**Acceptance Criteria:**
- [ ] CLI accepts repo root path (default: current directory)
- [ ] Scans all files matching include patterns (default: **/*)
- [ ] Excludes: node_modules, target, dist, .git, build, .next
- [ ] Detects TODO:, FIXME:, HACK:, XXX: markers (case-insensitive)
- [ ] Extracts file path, line number, and comment text for each marker
- [ ] Typecheck/lint passes

### US-002: Deduplicate exact matches
**Description:** As a developer, I want duplicate TODO comments to appear only once so the backlog isn't cluttered with repetition.

**Acceptance Criteria:**
- [ ] Exact text matches are deduplicated (same comment text = one entry)
- [ ] First occurrence (by file path alphabetically) is kept
- [ ] Duplicate count is tracked and shown in summary
- [ ] Typecheck/lint passes

### US-003: Cluster by module/package structure
**Description:** As a team lead, I want TODOs grouped by module so I can assign work by area of responsibility.

**Acceptance Criteria:**
- [ ] Python: detect packages via __init__.py or directory structure
- [ ] JavaScript/TypeScript: detect modules via package.json or directory structure
- [ ] Java: detect packages via package declarations
- [ ] Fallback: group by top-level directory if no package structure detected
- [ ] Each cluster shows count of items
- [ ] Typecheck/lint passes

### US-004: Calculate priority scores
**Description:** As a developer, I want each TODO to have a priority score so I know what to tackle first.

**Acceptance Criteria:**
- [ ] Impact score (1-5) based on keywords: SECURITY|DATA LOSS|P0|CRITICAL=5, BUG|FIXME=4, TODO=3, REFACTOR|CLEANUP=2, NICE TO HAVE=1
- [ ] Effort score (1-3) based on comment length: <50 chars=1, 50-150=2, >150=3
- [ ] Confidence boost (+1, max 5) if comment includes issue ID pattern (#123 or ABC-123)
- [ ] Priority = impact + confidence - effort (clamped 1-10)
- [ ] Typecheck/lint passes

### US-005: Generate BACKLOG.md
**Description:** As a team lead, I want a formatted BACKLOG.md file so I can review it in sprint planning meetings.

**Acceptance Criteria:**
- [ ] Summary section: total count, breakdown by marker type (TODO/FIXME/HACK/XXX)
- [ ] Top 10 highest priority items section with full details
- [ ] By module section: grouped clusters with item counts
- [ ] Each item shows: priority score, tag, file:line, text, optional owner/date/issue ID
- [ ] File written to repo root as BACKLOG.md
- [ ] Typecheck/lint passes

### US-006: Verify scan completeness
**Description:** As a developer, I want confirmation that all TODOs were captured so I can trust the backlog.

**Acceptance Criteria:**
- [ ] After generating BACKLOG.md, re-scan repository
- [ ] Compare item counts: original scan vs verification scan
- [ ] Print confirmation message: "✓ Verified: captured X items"
- [ ] Exit with error if counts don't match
- [ ] Typecheck/lint passes

## Functional Requirements

- FR-1: CLI must accept `--root` flag for repository path (default: current directory)
- FR-2: CLI must accept `--include` flag for file patterns (default: **/*, supports multiple)
- FR-3: CLI must accept `--exclude` flag for exclusion patterns (default: node_modules, target, dist, .git, build, .next, supports multiple)
- FR-4: Scanner must detect TODO:, FIXME:, HACK:, XXX: markers (case-insensitive, with or without colon)
- FR-5: Deduplication must use exact text matching (whitespace-normalized)
- FR-6: Clustering must detect module/package structure for Python, JavaScript/TypeScript, Java
- FR-7: Priority scoring must follow: priority = impact + confidence - effort (clamped 1-10)
- FR-8: BACKLOG.md must include: summary, top 10 priorities, by-module breakdown
- FR-9: Each backlog item must show: score, tag, file:line, text, optional metadata (owner/date/issue)
- FR-10: Tool must verify completeness by re-scanning and comparing counts
- FR-11: Exit code 0 on success, non-zero on verification failure or errors

## Non-Goals

- No JSON output (backlog.json) in initial version
- No git integration (--since flag) in initial version
- No watch mode or auto-update on file changes
- No configuration file support (.backlog.yaml)
- No issue tracker integration (GitHub/Jira API calls)
- No web UI or visualization
- No automatic TODO creation or management
- No multi-repository scanning

## Design Considerations

### CLI Interface
```bash
# Basic usage
python backlog_scanner.py

# Custom root
python backlog_scanner.py --root /path/to/repo

# Custom patterns
python backlog_scanner.py --include "**/*.py" --include "**/*.js" --exclude "tests/**"
```

### BACKLOG.md Format Example
```markdown
# Technical Debt Backlog

## Summary
- Total: 43 items (31 TODO, 10 FIXME, 2 HACK)
- Duplicates removed: 7

## Top 10 Priorities

1. [P=9] FIXME: src/auth/token.py:45 - Token refresh race condition causes 401s in production (issue: SEC-789)
2. [P=8] CRITICAL: src/payments/stripe.py:123 - Data loss risk if webhook fails (owner: @alice, 2024-03-01)
3. [P=7] BUG: src/api/users.py:67 - Email validation allows invalid formats (#456)
...

## By Module

### src/auth (12 items)
- [P=9] FIXME: token.py:45 - Token refresh race condition...
- [P=6] TODO: session.py:89 - Add session timeout configuration
...

### src/payments (9 items)
- [P=8] CRITICAL: stripe.py:123 - Data loss risk if webhook fails...
...
```

## Technical Considerations

- Python 3.8+ required
- Use `pathlib` for cross-platform path handling
- Use `argparse` for CLI argument parsing
- Use `re` module for pattern matching (TODO markers, issue IDs)
- Consider using `gitignore_parser` or similar for exclude pattern matching
- File encoding: assume UTF-8, handle decode errors gracefully
- Performance: stream file reading for large repos (don't load all into memory)
- Language detection: use file extensions and simple heuristics (no heavy dependencies)

### Module Detection Strategy
- Python: look for `__init__.py` or use directory structure
- JavaScript/TypeScript: look for `package.json` or use directory structure
- Java: parse `package` declarations from .java files
- Fallback: use top-level directory as module name

### Priority Scoring Details
```python
# Impact (keyword-based)
IMPACT_KEYWORDS = {
    5: ['security', 'data loss', 'p0', 'critical'],
    4: ['bug', 'fixme'],
    3: ['todo'],
    2: ['refactor', 'cleanup', 'tech debt'],
    1: ['nice to have', 'optional']
}

# Effort (length-based)
def calculate_effort(text):
    if len(text) < 50: return 1
    if len(text) < 150: return 2
    return 3

# Confidence (issue ID boost)
def has_issue_id(text):
    return bool(re.search(r'#\d+|[A-Z]+-\d+', text))
```

## Success Metrics

- Tool completes scan of 10k+ file repo in under 30 seconds
- Priority scores correlate with team's manual prioritization (>80% agreement in testing)
- BACKLOG.md is readable and actionable in sprint planning meetings
- Verification step catches 100% of scan inconsistencies
- Zero false negatives (all TODOs are captured)

## Open Questions

- Should we support custom marker keywords (e.g., NOTE:, OPTIMIZE:)?
- Should owner/date extraction be mandatory or optional?
- How should we handle TODOs in multi-line comments?
- Should we support output to stdout instead of file?
