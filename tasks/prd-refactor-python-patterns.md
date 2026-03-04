# PRD: Refactor Backlog Scanner with Python Patterns

## Introduction

Refactor the existing `backlog_scanner.py` codebase to align with idiomatic Python patterns and best practices as defined in the python-patterns skill. The code is functional and well-structured but has opportunities to adopt modern Python 3.13 idioms, stronger typing, proper error handling patterns, and tooling configuration. This refactoring improves maintainability, readability, testability, and performance without changing external behavior.

## Goals

- Apply python-patterns idioms consistently across the codebase (type hints, EAFP, protocols, etc.)
- Improve code maintainability and readability through modern Python 3.13 conventions
- Make the code more testable by reducing coupling and improving separation of concerns
- Improve performance for large repository scans using generators and lazy evaluation
- Add full tooling configuration (pyproject.toml) for formatting, linting, type checking, and testing
- Preserve all existing CLI behavior and output formats (no breaking changes)

## User Stories

### US-001: Modernize type hints to Python 3.13 style
**Description:** As a developer, I want the codebase to use modern Python 3.13 type hints so the code is cleaner and doesn't rely on legacy typing imports.

**Acceptance Criteria:**
- [ ] Remove `from __future__ import annotations`
- [ ] Replace `Optional[X]` with `X | None` throughout
- [ ] Replace `typing.Iterator` with `collections.abc.Iterator`
- [ ] Remove unused imports from `typing` module
- [ ] Use built-in `list`, `dict`, `tuple` generics (already mostly done, verify consistency)
- [ ] Typecheck passes with `mypy --strict`

### US-002: Add custom exception hierarchy
**Description:** As a developer, I want specific exception types so error handling is explicit and debuggable rather than catching broad `OSError` everywhere.

**Acceptance Criteria:**
- [ ] Create `ScannerError` base exception class
- [ ] Create `FileReadError(ScannerError)` for file I/O failures
- [ ] Create `ConfigError(ScannerError)` for invalid CLI arguments or configuration
- [ ] Replace bare `OSError` catches with specific exception handling and chaining (`raise ... from e`)
- [ ] `resolve_args` raises `ConfigError` instead of calling `sys.exit` directly
- [ ] `main()` catches `ScannerError` and exits cleanly with error message
- [ ] Typecheck passes

### US-003: Apply EAFP pattern and improve error handling
**Description:** As a developer, I want the code to follow Python's EAFP idiom so exception handling is idiomatic and consistent.

**Acceptance Criteria:**
- [ ] `relative_to()` calls use try/except instead of pre-checking (already partially done, verify consistency)
- [ ] File reading uses EAFP with specific exception types
- [ ] Exception chaining (`from e`) used wherever exceptions are re-raised
- [ ] No silent exception swallowing (no bare `except: pass`)
- [ ] Typecheck passes

### US-004: Improve dataclass usage and add validation
**Description:** As a developer, I want dataclasses to use `__post_init__` validation and `__slots__` for memory efficiency so the data model is robust and performant.

**Acceptance Criteria:**
- [ ] Add `__slots__` to `TodoItem` and `ScanResult` dataclasses (via `slots=True` on Python 3.10+)
- [ ] Add `__post_init__` validation to `TodoItem` (e.g., `line_number > 0`, `marker` is valid)
- [ ] Use `frozen=True` on `TodoItem` since items shouldn't be mutated after creation
- [ ] Typecheck passes

### US-005: Use generators for lazy evaluation in large scans
**Description:** As a developer, I want the scanner to use generators and lazy evaluation so it handles large repositories without excessive memory usage.

**Acceptance Criteria:**
- [ ] `scan_file` returns an `Iterator[TodoItem]` instead of building a full list
- [ ] `scan_repository` streams items lazily where possible
- [ ] `generate_backlog_md` uses `StringIO` or generator-based string building instead of list concatenation
- [ ] String building avoids `+=` in loops (use `"".join()` or `StringIO`)
- [ ] Typecheck passes

### US-006: Extract constants and use enums for marker types
**Description:** As a developer, I want marker types and scoring constants defined as enums/constants so the scoring logic is self-documenting and easy to modify.

**Acceptance Criteria:**
- [ ] Create `Marker` enum with `TODO`, `FIXME`, `HACK`, `XXX` values
- [ ] Extract impact keyword mappings into a structured constant (dict or enum)
- [ ] Extract effort thresholds into named constants (`EFFORT_SHORT = 50`, `EFFORT_LONG = 150`)
- [ ] Extract priority clamping bounds into constants (`MIN_PRIORITY = 1`, `MAX_PRIORITY = 10`)
- [ ] Typecheck passes

### US-007: Improve function signatures and use Protocol for extensibility
**Description:** As a developer, I want clean function signatures and protocol-based abstractions so the code is extensible and self-documenting.

**Acceptance Criteria:**
- [ ] Module detection functions follow a consistent `Protocol` or callable signature
- [ ] Create a `ModuleDetector` protocol: `def detect(file_path: Path, root: Path) -> str | None`
- [ ] Register detectors by file extension instead of if/elif chain in `detect_module`
- [ ] Typecheck passes

### US-008: Add pyproject.toml with full tooling configuration
**Description:** As a developer, I want a `pyproject.toml` with formatter, linter, type checker, and test runner configuration so the project has consistent development standards.

**Acceptance Criteria:**
- [ ] `pyproject.toml` created with project metadata (name, version, requires-python = ">=3.13")
- [ ] `[tool.black]` configured with `line-length = 88`, `target-version = ['py313']`
- [ ] `[tool.ruff]` configured with select rules: `["E", "F", "I", "N", "W"]`
- [ ] `[tool.mypy]` configured with `python_version = "3.13"`, `warn_return_any = true`, `disallow_untyped_defs = true`
- [ ] `[tool.pytest.ini_options]` configured with `testpaths` and coverage options
- [ ] Dev dependencies listed: pytest, pytest-cov, black, ruff, mypy
- [ ] Typecheck passes

### US-009: Apply naming and style conventions
**Description:** As a developer, I want consistent naming and style conventions so the code reads naturally and follows PEP 8.

**Acceptance Criteria:**
- [ ] All functions have docstrings (already mostly done, verify completeness)
- [ ] Import order follows: stdlib → third-party → local (add `isort` via ruff)
- [ ] No mutable default arguments (verify none exist)
- [ ] `None` comparisons use `is None` / `is not None` (already done, verify)
- [ ] `isinstance()` used instead of `type()` for type checks (already done, verify)
- [ ] Typecheck passes

## Functional Requirements

- FR-1: All existing CLI flags (`--root`, `--include`, `--exclude`, `--verbose`) must continue to work identically
- FR-2: BACKLOG.md output format must remain unchanged
- FR-3: Exit codes must remain: 0 on success, non-zero on verification failure
- FR-4: Priority scoring algorithm must produce identical results
- FR-5: Deduplication logic must produce identical results
- FR-6: Module detection must produce identical results for Python, JS/TS, and Java files
- FR-7: All refactoring must be behavior-preserving (no functional changes)
- FR-8: Code must pass `mypy --strict` with zero errors
- FR-9: Code must pass `ruff check` with zero errors
- FR-10: Code must pass `black --check` with zero changes needed

## Non-Goals

- No new features or CLI flags
- No change to output format or content
- No splitting into a multi-file package (unless the flexible structure decision warrants it for clarity)
- No adding third-party runtime dependencies
- No changing the priority scoring algorithm
- No adding tests (separate effort)
- No async/await refactoring (the tool is I/O-bound but single-threaded is fine for its use case)

## Technical Considerations

- Python 3.13 is the target — use all modern syntax freely (`X | None`, built-in generics, `match` if appropriate)
- `dataclasses(slots=True, frozen=True)` available since Python 3.10
- Keep the single-file structure unless a natural split emerges (e.g., models vs. CLI vs. scanning logic)
- The `from __future__ import annotations` import can be removed since we're targeting 3.13
- `StringIO` from `io` module for efficient string building in `generate_backlog_md`
- Protocol-based module detection allows future language support without modifying `detect_module`
- All refactoring should be incremental — each user story can be applied independently

## Success Metrics

- `mypy --strict` passes with zero errors
- `ruff check .` passes with zero errors
- `black --check .` reports no changes needed
- Running the scanner on the same repo produces byte-identical BACKLOG.md output before and after refactoring
- No new runtime dependencies added
- Code is measurably more readable (shorter functions, clearer types, self-documenting constants)

## Open Questions

- Should `TodoItem` be truly frozen, or does the deduplication sort require mutability on the containing list?
- Is `match` statement appropriate for the impact scoring logic, or is the dict-lookup pattern cleaner?
- Should the module detector registry be a simple dict or a more formal plugin system?
