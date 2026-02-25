# TESTING - Test Structure & Practices

## Current State

Testing infrastructure is minimal. The codebase relies primarily on:
- Manual testing via CLI agents (`scripts/cli_agent.py`, `scripts/cli_openrouter.py`)
- Approval flow testing script (`scripts/test_approval_flow.py`)
- MCP server test file (`fhir-mcp-server/src/test_server.py`)

## Test Files

| File | Purpose |
|------|---------|
| `fhir-mcp-server/src/test_server.py` | MCP server unit tests |
| `scripts/test_approval_flow.py` | Integration test for approval queue workflow |
| `scripts/cli_agent.py` | Interactive CLI for manual testing |
| `scripts/cli_openrouter.py` | OpenRouter CLI for manual testing |

## Testing Approach

### Manual Testing
- Primary testing method is interactive CLI sessions
- 5 seeded test patients cover different clinical scenarios
- Approval queue tested via `test_approval_flow.py` script

### Integration Testing
- Docker Compose stack must be running (Medplum + PostgreSQL + Redis)
- Tests hit live FHIR server (no mocking)
- `scripts/seed_patients.py` creates reproducible test data

### What's Tested
- FHIR CRUD operations via handlers
- Drug interaction validation
- Medication safety checks (allergies, renal dosing)
- Approval queue lifecycle (create → approve/reject → execute)
- AI orchestrator tool calling and response formatting

### What's NOT Tested
- No automated unit test suite (pytest)
- No frontend tests (no Jest/Vitest/Playwright)
- No CI/CD pipeline
- No load/performance testing
- Clinical scoring systems (newly added, need tests)
- Simulation engine (newly added, need tests)

## Recommended Testing Strategy (Phase 1)

1. **pytest** for Python backend (scoring, alerts, FHIR handlers)
2. **Vitest** for frontend components
3. **Simulation engine** provides its own E2E testing framework via scenario assertions
4. Scoring systems are deterministic — ideal for unit testing with known inputs/outputs
