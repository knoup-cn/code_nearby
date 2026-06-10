# brain

CLI tools for managing Git repositories.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
brain --help
```

## Commands

```bash
brain status [PATH]
brain repos [PATH]
```

- `status` prints the current Git branch and porcelain status for one repository.
- `repos` finds Git repositories under a directory.

## Development

```bash
python -m pytest
python -m ruff check .
```
