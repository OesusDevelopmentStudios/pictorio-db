# Contributing to pictorio-db

Readability comes first. The code should be easy to understand and maintain for someone who has
never seen it before.

## Workflow

- **Small commits.** Each commit does one thing, passes the tests and can be reviewed on its own.
- **Tests come with the code.** New logic comes with a test in `tests/`.
- Before committing:
  ```sh
  pytest
  flake8
  ```

## Code layout

```
src/pictorio_db/
├── app.py          creates the services and the web application; contains no logic of its own
├── config.py       settings read from environment variables at startup
├── db/             database tables (models.py), connection and migrations
├── api/v1/         REST API: one router per resource
├── admin_web/      web admin pages
├── services/       one package per service, each with a single responsibility
└── utils/          small helpers shared by several services
tests/              mirrors src/pictorio_db/: tests/api/v1/test_server.py tests api/v1/server.py
```

**Routers and admin pages are thin.** They validate the input, call a service and turn the result
into a response. Decisions live in the services, where they can be unit-tested, and the REST API
and the admin pages use the same services.

### Service layout

```
services/<service_name>/       snake_case, e.g. services/tags/
├── __init__.py                public interface: the only module other code may import
└── _<module>.py               internals, e.g. _normalise.py
```

- Services never create each other. `app.py` creates them and passes in their dependencies, so
  tests can pass in fakes.

## Database changes

The schema changes only through Alembic migrations in `src/pictorio_db/db/migrations/versions/`,
one migration per reviewable change. The server applies them itself when it starts.

1. Change the tables in `src/pictorio_db/db/models.py`.
2. Let Alembic write the migration. It compares the models with `migration-dev.sqlite3` in the
   repository root (ignored by git), so bring that file up to date first. Use the next number as id:
   ```sh
   alembic upgrade head
   alembic revision --autogenerate --rev-id 0002 -m "short description"
   ```
3. Read the generated file and tidy it up; it is code like any other.
4. `pytest` fails if the models and the migrations do not describe the same schema.

## Python style

Formatting follows PEP 8, checked by flake8 with a maximum line length of 120 columns.

| What | Style | Example |
|---|---|---|
| Modules, packages, functions, variables | `snake_case` | `server_info()` |
| Classes | `PascalCase` | `ServerInfo` |
| Constants | `UPPER_SNAKE_CASE` | `API_VERSION` |
| Internal modules and names | leading `_` | `_normalise.py` |

- **Type hints everywhere.** Every function has type hints for its parameters and its return type.
- **Names are verbose.** No single-letter names, not even for loop counters: `image_index`, not `i`.
- **Each function has a single responsibility.**
- **Comments are short** and only where they add something the code does not already say.

## License headers

Every source file starts with an SPDX header:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios
```
