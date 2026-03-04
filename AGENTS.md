# Agent Instructions

## Project

TODO Backlog Scanner — a Python 3.13+ CLI tool that scans codebases for TODO/FIXME/HACK/XXX comments and generates a prioritized `BACKLOG.md`. Single-file script: `backlog_scanner.py`.

## Python Standards

Always follow the python-patterns skill (`.kiro/skills/python-patterns/SKILL.md`). Key rules:

- Python 3.13+ — use modern built-in generics (`list[str]`, `dict[str, Any]`, `X | None`) instead of `typing.List`, `typing.Dict`, `typing.Optional`
- Type-annotate every function signature; pass `mypy --strict`
- Use `dataclasses` for data containers, `NamedTuple` for immutable records
- EAFP over LBYL — prefer `try/except` over pre-checking conditions
- Specific exceptions only — never bare `except:` or `except Exception`
- Chain exceptions with `raise ... from e`
- Context managers (`with`) for all resource handling
- List comprehensions for simple transforms; generators for large/lazy iteration
- `pathlib.Path` over `os.path`
- f-strings for formatting
- Import order: stdlib → third-party → local (isort style)
- No mutable default arguments — use `None` + create inside function
- `isinstance()` over `type()` checks; `is None` over `== None`

## Quality Checks

```bash
python -m mypy backlog_scanner.py --strict
```

All code must typecheck cleanly before committing.

## Workflow

- PRD lives in `prd.json`, progress log in `progress.txt`
- Work one user story at a time, highest priority first
- Commit with: `feat: [Story ID] - [Story Title]`
- Update `prd.json` (`passes: true`) and append to `progress.txt` after each story
