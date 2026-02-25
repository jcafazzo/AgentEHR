# Stack Research

## Current Stack Assessment

### Backend (Python 3.12 + FastAPI)
- **Verdict: Keep** — FastAPI is ideal for async FHIR operations, WebSocket support built-in, Pydantic v2 for FHIR resource validation
- asyncio-native aligns perfectly with multi-agent concurrent monitoring
- OpenRouter client already handles multi-model routing (Claude, Gemini, GPT-4, GLM)

### Frontend (Next.js 15 + React 19)
- **Verdict: Keep** — Server components for initial patient census load, client components for real-time dashboard
- React 19 concurrent features help with streaming vital signs updates
- App Router for simulation and admin pages

### FHIR Server (Medplum)
- **Verdict: Keep** — Self-hosted, FHIR R4 compliant, supports Subscriptions
- PostgreSQL 16 backend handles relational queries for patient census
- Redis for session/cache (expandable for pub/sub of vital sign events)

### Agent Orchestration (OpenRouter + Custom)
- **Verdict: Extend** — Current single-orchestrator per conversation needs to become supervisor→sub-agent pattern
- OpenRouter gateway stays for model flexibility
- Need to add: agent lifecycle management, concurrent agent coordination, shared patient state

## New Stack Components Needed

### Agent Framework
| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| Claude Agent SDK | Native supervisor→subagent, isolated contexts, tool delegation | Anthropic-specific | **Use this** — matches our architecture exactly |
| LangGraph | State machines, checkpointing, multi-model | Complex, overkill for our pattern | Skip |
| Custom (extend current) | Full control, no new deps | Maintenance burden, reinvent lifecycle management | Fallback only |

**Decision: Claude Agent SDK** — The supervisor→subagent pattern maps directly to our clinical care team model. Each sub-agent gets isolated context with only the relevant patient data and specialty guidelines.

### Vector Store (for Knowledge Base RAG)
| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| ChromaDB | Local, free, Python-native, good for <100K docs | Not cloud-scalable | **Use this** — sufficient for guidelines |
| pgvector | Already have PostgreSQL | Requires extension, mixing concerns | Later if needed |
| Pinecone | Managed, scalable | External dependency, cost | Overkill for dev |

**Decision: ChromaDB** — Clinical guidelines are a bounded corpus (~500-2000 documents). Local, zero-cost, Python-native.

### Real-Time Communication
| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| WebSocket (native FastAPI) | Already in stack, low-latency | Manual connection management | **Use this** for vital signs streaming |
| Server-Sent Events | Simpler, HTTP-based | One-directional | Use for alert feed only |
| FHIR Subscriptions (REST-hook) | Standards-compliant | Medplum support varies, added complexity | Phase 4 |

**Decision: WebSocket first** — FastAPI native WebSocket for dashboard streaming. FHIR Subscriptions in Phase 4 for standards compliance.

### Agent Observability
| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| LangFuse | Open-source, LLM-specific tracing, self-hostable | Another Docker service | **Use this** |
| OpenTelemetry + Jaeger | Standard, language-agnostic | Generic, not LLM-aware | Complement LangFuse |
| Arize Phoenix | Good UI, open-source | Less mature | Monitor |

**Decision: LangFuse + OpenTelemetry** — LangFuse for LLM-specific traces (token usage, reasoning steps), OpenTelemetry for infrastructure spans.

### Dashboard Visualization
| Component | Library | Rationale |
|-----------|---------|-----------|
| Agent graph | ReactFlow | Interactive node graph, established, React-native |
| Vital signs charts | Recharts | Lightweight, real-time capable, good for streaming data |
| Timeline | Custom + Recharts | No perfect fit; build on Recharts with custom annotations |
| Data tables | TanStack Table | Sortable/filterable patient census |

## Build Order Dependencies

```
Phase 1: FHIR tools + Supervisor agent + Scoring + Dashboard + Simulation core
    ↓
Phase 2: Sub-agents + Knowledge base (ChromaDB) + Agent lifecycle + Scenarios
    ↓
Phase 3: Admin UI + Clinical trials + Assertions + Reporting
    ↓
Phase 4: WebSocket streaming + FHIR Subscriptions + Observability + Scale testing
```

## Package Additions (estimated)

```
# Python backend
claude-agent-sdk          # Agent framework (supervisor→subagent)
chromadb                  # Vector store for RAG
langfuse                  # LLM observability
opentelemetry-api         # Distributed tracing
opentelemetry-sdk
pyyaml                    # Scenario parsing (already likely installed)
synthea                   # Synthetic patient generation (CLI tool, not pip)

# Frontend
reactflow                 # Agent visualization graph
recharts                  # Already installed or add for vital charts
@tanstack/react-table     # Patient census table
```

---
*Research: 2026-02-25*
