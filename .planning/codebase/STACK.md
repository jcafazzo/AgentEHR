# Technology Stack

**Analysis Date:** 2026-02-25

## Languages

**Primary:**
- Python 3.12.1 - Backend API, AI agents, FHIR MCP server, simulation engine
- TypeScript 5.7 - Next.js frontend

**Secondary:**
- JavaScript - Next.js/Tailwind config files (`frontend/next.config.js`, `frontend/tailwind.config.js`)

## Runtime

**Environment:**
- Python: 3.12.1 (via pyenv, venv at `.venv/`)
- Node.js: Used by Next.js frontend (version managed via npm)

**Package Manager:**
- Python: pip with per-module `requirements.txt` files (no unified top-level file)
  - `agents/requirements.txt`
  - `api/requirements.txt`
  - `fhir-mcp-server/requirements.txt`
- JavaScript: npm
- Lockfile: `frontend/package-lock.json` present

## Frameworks

**Backend API:**
- FastAPI >= 0.109.0 - HTTP API server (`api/main.py`), served via uvicorn on port 8000
- uvicorn[standard] >= 0.27.0 - ASGI server for FastAPI

**Frontend:**
- Next.js 15.1.0 - React framework with App Router, served on port 3000
- React 19.0.0 - UI library
- Tailwind CSS 3.4.15 - Utility-first CSS framework

**AI/Agent:**
- Anthropic SDK >= 0.40.0 - Direct Claude API client (`agents/orchestrator.py`)
- MCP SDK >= 1.0.0 - Model Context Protocol server (`fhir-mcp-server/src/server.py`)

**Testing:**
- pytest >= 8.0.0 - Python test runner
- pytest-asyncio >= 0.23.0 - Async test support

**Build/Dev:**
- Next.js dev server: `npm run dev` (port 3000)
- Python: Direct script execution with uvicorn

## Key Dependencies

**Critical:**
- `anthropic >= 0.40.0` - Claude SDK for the direct-Anthropic orchestrator path (`agents/orchestrator.py`); uses `claude-sonnet-4-20250514` as default model
- `mcp >= 1.0.0` - MCP protocol SDK for the FHIR MCP server (`fhir-mcp-server/src/server.py`)
- `fhir.resources >= 7.0.0` - FHIR R4 resource modeling in the MCP server
- `httpx >= 0.27.0` - Async HTTP client used across all Python modules for FHIR API calls and OpenRouter calls
- `pydantic >= 2.0.0` - Data validation; used for FastAPI request/response models and settings
- `pydantic-settings >= 2.0.0` - Settings from env vars (`fhir-mcp-server/src/server.py` `Settings` class)
- `python-dotenv >= 1.0.0` - Loads `.env` file at startup in `api/main.py` and MCP server

**Frontend:**
- `next 15.1.0` - Core framework with API proxy rewrites
- `react-markdown 10.1.0` - Renders AI-generated markdown responses in chat UI
- `lucide-react 0.468.0` - Icon library used in components
- `@tailwindcss/typography 0.5.19` - Prose styling for AI-generated content

**Infrastructure:**
- `anyio >= 4.0.0` - Async compatibility layer

**Optional/Voice (declared, not confirmed active):**
- `openai-whisper >= 20231117` - Local speech-to-text (declared in `fhir-mcp-server/requirements.txt`)
- `elevenlabs >= 1.0.0` - Text-to-speech (declared in `fhir-mcp-server/requirements.txt`)

## Configuration

**Environment:**
- Primary config file: `.env` at project root
- Required variables:
  - `OPENROUTER_API_KEY` - Required for chat feature; API server returns 503 without it
  - `MEDPLUM_BASE_URL` - FHIR server URL (default: `http://localhost:8103/fhir/R4`)
- FHIR MCP server env vars (prefix `FHIR_SERVER_`):
  - `FHIR_SERVER_BASE_URL` (default: `http://localhost:8103/fhir/R4`)
  - `FHIR_SERVER_ACCESS_TOKEN` (optional static token)
  - `FHIR_SERVER_EMAIL` (default: `admin@agentehr.local`)
  - `FHIR_SERVER_PASSWORD` (default: `medplum123`)

**Build:**
- Frontend: `frontend/next.config.js` - configures API proxy rewrites and 120s proxy timeout
- Frontend: `frontend/tsconfig.json` - strict TypeScript, `@/*` alias mapped to `./src/*`
- Frontend: `frontend/tailwind.config.js` - custom design tokens (Stitch design system)
- Docker: `docker-compose.yml` - full-stack infrastructure definition

## Platform Requirements

**Development:**
- Python 3.12.x (pyenv recommended)
- Node.js (LTS)
- Docker + Docker Compose (for Medplum stack)
- OpenRouter API key for AI features

**Production:**
- No production deployment configuration detected (no Dockerfile for app services, no cloud config)
- Infrastructure via Docker Compose only

---

*Stack analysis: 2026-02-25*
