# Contributing to AI Mail Manager

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Environment Setup

### Prerequisites

- Python 3.13+
- Node.js 24+
- Docker & Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python dependency management)
- Git

### Backend

```bash
cd backend
pip install uv                       # if not already installed
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Frontend

```bash
cd frontend
npm install
```

### Infrastructure

```bash
cp .env.example .env                 # fill in required values
docker compose up -d postgres valkey # start database and cache
cd backend && alembic upgrade head   # run migrations
```

See `.env.example` for all configuration variables and their descriptions.

## Code Style & Linting

### Backend (Python)

- **Formatter/linter**: ruff (line-length 120, target py313)
- **Type checking**: mypy in strict mode with the pydantic plugin
- **Imports**: absolute only (`from app.core.config import ...`), sorted by ruff/isort
- **Docstrings**: Google-style on all public classes, methods, and service functions
- **Comments**: English only. Comment the *why*, not the *what*. No commented-out code

```bash
cd backend
ruff check app/ tests/        # lint
ruff format app/ tests/       # format
mypy app/                     # type check
```

### Frontend (TypeScript)

- **TypeScript**: strict mode, `noUnusedLocals`, `noUnusedParameters`, `noUncheckedIndexedAccess`
- **Styling**: TailwindCSS 4 utility classes
- **Path alias**: `@/` maps to `src/` (e.g. `import { Button } from "@/components/ui/button"`)
- **File naming**: kebab-case (`mail-accounts.tsx`), except `App.tsx` and auto-generated files

```bash
cd frontend
npx tsc --noEmit              # type check
```

## Frontend Conventions

### API Client (orval)

The API client in `src/services/api/` and types in `src/types/api/` are **auto-generated** from `openapi.json` by orval. **Never edit these files manually.**

To regenerate after backend API changes:

```bash
cd frontend
npx orval
```

The orval config (`orval.config.ts`) uses tags-split mode with a react-query client and a custom fetch wrapper (`src/services/client.ts`) that handles CSRF tokens, credentials, and 401 redirects.

### UI Components

- Use [Radix UI](https://www.radix-ui.com/) primitives from `src/components/ui/` for accessible, unstyled components
- Forms use `react-hook-form` with `zod` v4 schemas for validation (via `@hookform/resolvers`)
- Server state is managed with TanStack React Query 5 (staleTime 30s, retry 1)
- Pages are lazy-loaded with `React.lazy()` and `Suspense`

## How to Write a New Plugin

The AI pipeline uses a plugin architecture. Adding a new AI function requires **no changes to existing code** — just new files.

### 1. Create the plugin file

Create `backend/app/plugins/my_plugin.py`:

```python
from pydantic import BaseModel, Field

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import register_plugin


class MyPluginResponse(BaseModel):
    """Validated LLM response schema."""
    detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=500)


@register_plugin
class MyPlugin(AIFunctionPlugin[MyPluginResponse]):
    """One-line description of what this plugin does."""

    name = "my_plugin"
    display_name = "My Plugin"
    description = "What this plugin does in the pipeline"
    default_prompt_template = "prompts/my_plugin.j2"
    execution_order = 50          # 10=spam, 20=newsletter, ..., 75=summary
    icon = "LucideIconName"       # from lucide-react
    approval_key = "my_plugin"
    has_view_page = True
    view_route = "/my-plugin"

    async def execute(self, context: MailContext, ai_response: MyPluginResponse) -> ActionResult:
        if not ai_response.detected:
            return self._no_action("my_plugin_passed")

        return ActionResult(
            success=True,
            actions_taken=["description_of_action_taken"],
        )

    def get_approval_summary(self, ai_response: MyPluginResponse) -> str:
        return f"Detected ({ai_response.confidence:.0%}): {ai_response.reason}"
```

Key points:
- Subclass `AIFunctionPlugin[YourResponseModel]` with a Pydantic response type
- Decorate with `@register_plugin` — the registry auto-discovers it at startup
- Set `runs_in_pipeline = False` for plugins that don't go through the LLM (e.g. rules, notifications)
- Use `self.pipeline` to read results from earlier plugins via `PipelineContext`
- Use `self._meets_threshold()` and `self._no_action()` helpers where appropriate

### 2. Add the prompt template

Create `backend/app/templates/prompts/my_plugin.j2` with the Jinja2 prompt template. The template receives a `MailContext` object as context.

### 3. Add model and schema (if storing results)

- Add a SQLAlchemy model in `backend/app/models/` (new file or extend existing)
- Add Pydantic schemas in `backend/app/schemas/` (`MyPluginResponse`, `MyPluginCreate`, etc.)
- Export the model from `backend/app/models/__init__.py`
- Create an Alembic migration (see [Database Migrations](#database-migrations))

### 4. Add an API route (if the plugin has a view page)

Create `backend/app/api/my_plugin.py` with a FastAPI router. Use the shared dependencies from `app.api.deps` (`DbSession`, `CurrentUserId`, `get_or_404`, `paginate`).

### 5. Add the frontend page

- Create `frontend/src/pages/my-plugin.tsx` (or a folder for multi-file pages)
- Use the auto-generated API hooks from orval after regenerating the client
- Register the route in `frontend/src/plugin-routes.ts`

### 6. Add tests

- Plugin unit test: `backend/tests/test_plugins/test_my_plugin.py`
- API route test: `backend/tests/test_api/test_my_plugin.py`
- Frontend test: `frontend/src/pages/__tests__/my-plugin.test.tsx`

See `backend/app/plugins/spam_detection.py` for a complete, minimal example.

## Testing

### Backend

```bash
cd backend
pytest tests/ -v                                          # run all tests
pytest tests/ --cov=app --cov-report=term-missing         # with coverage (min 80%)
pytest tests/test_plugins/test_spam_detection.py -v       # single file
```

- **pytest-asyncio** in `auto` mode — async test functions are detected automatically
- **factory-boy** for test data factories (see `tests/conftest.py`)
- **FakeValkey** and **FakeEncryption** fixtures replace real infrastructure in tests
- Test directories mirror source structure: `test_api/`, `test_services/`, `test_plugins/`, `test_workers/`
- Minimum coverage: **80%**

### Frontend

```bash
cd frontend
npm run test                    # single run (vitest)
npm run test:watch              # watch mode
```

- **Vitest** with jsdom environment and globals enabled
- **@testing-library/react** for component testing
- Custom render with providers in `src/test/test-utils.tsx`
- Shared mocks in `src/test/mocks.ts`

## Database Migrations

We use Alembic for schema migrations.

```bash
cd backend

# Auto-generate a migration after model changes
alembic revision --autogenerate -m "add_my_plugin_results"

# Apply migrations
alembic upgrade head
```

**Important:**
- Always review auto-generated migrations — Alembic can miss or misinterpret changes
- Naming convention: `YYYYMMDD_description.py` (e.g. `20260427_add_my_plugin_results.py`)
- Migrations run automatically on app startup via `docker-entrypoint.sh`

## Commit Message Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>

<optional footer>
```

### Types

| Type | Use for |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `ci` | CI/CD pipeline changes |
| `chore` | Dependency updates, tooling, config |

### Examples

```
feat(plugins): add coupon extraction plugin

Extracts discount codes and expiry dates from promotional emails.
Stores results in the extracted_coupons table.

Closes #42
```

```
fix(worker): prevent duplicate IMAP IDLE connections per account
```

## Branch & MR Workflow

We use **GitLab flow**:

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature main
   ```
2. Make your changes, commit following the conventions above
3. Push and open a Merge Request targeting `main`:
   ```bash
   git push -u origin feat/my-feature
   ```
4. MRs are **squash-merged** into `main`
5. CI runs automatically on non-default branches (lint, tests, coverage, Helm lint for chart changes)

### Branch naming

- `feat/short-description` — new features
- `fix/short-description` — bug fixes
- `refactor/short-description` — refactoring
- `docs/short-description` — documentation

## Security Vulnerability Reporting

**Do not open a public issue for security vulnerabilities.**

Please report security issues responsibly by emailing the maintainers directly. Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

Contact: Open a confidential issue on [git.teccave.de](https://git.teccave.de) or reach out to the project maintainers directly.

We aim to acknowledge reports within 48 hours and provide a fix or mitigation plan within 7 days.

## License

This project is licensed under the **GNU General Public License v3.0** (GPLv3). See [LICENSE](LICENSE) for the full text.

By contributing, you agree that your contributions will be licensed under the same GPLv3 license.
