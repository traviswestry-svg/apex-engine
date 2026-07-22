# APEX Repository Architecture

## Production entry points

- `wsgi.py` is the stable Gunicorn/Render WSGI entry point.
- `engine/application_composition.py` owns application construction.
- `app.py` remains a compatibility surface for existing routes and imports.
- `scanner_worker.py` is the explicit scanner-process entry point. The web process must not start scanning during import.

## Directory ownership

- `engine/`: reusable domain, orchestration, persistence, provider, and route modules.
- `templates/` and `static/`: dashboard presentation assets.
- `tests/`: all automated tests. No `test_*.py` files belong in the repository root.
- `scripts/`: deployment, migration, audit, and operator scripts that are not imported by the web application.
- `tools/`: development-only utilities.
- `docs/architecture/`: current architecture and repository-governance documentation.

## Root-file policy

Root Python files are limited to production entry points, compatibility facades, and operator CLIs. New domain logic must be added beneath `engine/`. New tests must be added beneath `tests/`.

## Import and startup policy

Architecture work must preserve these constraints:

1. Importing `wsgi.py` constructs the web application only.
2. Provider fan-out, broker calls, scanning, and background workers are forbidden during module import.
3. Scanner startup remains explicit through `scanner_worker.py` or an approved runtime command.
4. Trade execution remains confirmation-gated and broker-neutral until the existing execution-control layer authorizes a preview.

## Automated guard

Run:

```bash
python scripts/architecture_audit.py
```

The guard fails when tests are placed in the root, required entry points disappear, unapproved root Python modules are introduced.
