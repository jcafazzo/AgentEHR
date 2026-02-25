# CONVENTIONS - Code Style & Patterns

## Python (Backend)

### Style
- Python 3.11+ with type hints throughout
- `from __future__ import annotations` for forward references
- `async/await` for all I/O operations (httpx, FHIR calls)
- Dataclasses for structured data; Pydantic BaseModel for API request/response
- `logging` module (named loggers: `agentehr.api`, `agentehr.scoring`, etc.)

### Naming
- `snake_case` for files, functions, variables
- `PascalCase` for classes
- FHIR handlers: `handle_<verb>_<resource>(args: dict) -> dict`
- Private helpers: `_helper_name()`

### Error Handling
- FHIR handlers: return `{"error": "message"}` dicts (no exceptions to caller)
- API layer: try/except with `HTTPException` for user-facing errors
- Agent orchestrator: catches tool execution errors, returns error messages to LLM
- Logging: `logger.exception()` for unexpected errors, `logger.warning()` for expected issues

### Patterns
- **Tool handler pattern**: Each FHIR tool is an async function taking `args: dict`, returning `dict`
- **Approval queue pattern**: Write actions create draft FHIR resources, queued for human approval
- **Singleton pattern**: Module-level instances (`fhir_client`, `_auth`, `settings`)
- **Cache pattern**: Hash-based in-memory caching with explicit invalidation (narratives)

### Imports
- Standard library first, then third-party, then local
- `sys.path.insert()` used in `api/main.py` to resolve cross-package imports
- Relative imports within packages (`.module` style)

## TypeScript/React (Frontend)

### Style
- Next.js 15 App Router with React 19
- Tailwind CSS for styling (no CSS modules)
- Functional components with hooks (no class components)
- `"use client"` directive for interactive components

### Naming
- `PascalCase` for component files and exports
- `camelCase` for functions, variables, hooks
- `types.ts` for shared TypeScript interfaces

### Component Pattern
```tsx
"use client";
import { useState } from "react";

interface Props {
  data: SomeType;
  onAction: (id: string) => void;
}

export default function ComponentName({ data, onAction }: Props) {
  const [state, setState] = useState<Type>(initial);
  // ... component logic
  return <div className="tailwind-classes">...</div>;
}
```

### API Calls
- `fetch()` with explicit timeout via `AbortController`
- Error handling: try/catch with user-facing error states
- API base URL: relative `/api/...` paths (proxied in dev)

## FHIR Conventions

### Resource Patterns
- All FHIR resources follow R4 specification
- Patient references: `"reference": "Patient/{id}"`
- Coding: `{"system": "http://...", "code": "...", "display": "..."}`
- Status fields: FHIR standard codes (active, completed, cancelled, etc.)

### Tool Registration
- Tools defined as JSON Schema objects in `openrouter_orchestrator.py`
- Each tool has: `name`, `description`, `input_schema` with properties/required
- Handler mapping in `_import_handlers()` method

## Configuration
- Environment variables via `.env` file (loaded by `python-dotenv`)
- `pydantic_settings.BaseSettings` for typed config with env prefix
- Docker Compose for infrastructure (Medplum, PostgreSQL, Redis)
- CORS origins explicitly listed (localhost:3000, localhost:3010)
