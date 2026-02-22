# AgentEHR

An agent-based Electronic Health Record interface that allows clinicians to interact via text or voice without learning traditional EHR navigation.

## Vision

The system interprets clinical intent, orchestrates AI agents to perform tasks via MCP (Model Context Protocol), and presents action items for clinician approval. This represents the next evolution of healthcare UI - from portal-based to agent-based.

## Architecture

```
User (Voice/Text) → Agent Orchestration → MCP Server → FHIR R4 Backend (Medplum)
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+ (for Medplum tools)

### 1. Start Medplum FHIR Server

```bash
docker-compose up -d medplum
```

Access Medplum at: http://localhost:8103

### 2. Load Synthetic Data

```bash
./scripts/load_synthea.sh
```

### 3. Start MCP Server

```bash
cd fhir-mcp-server
pip install -r requirements.txt
python src/server.py
```

### 4. Configure Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "fhir": {
      "command": "python",
      "args": ["/path/to/AgentEHR/fhir-mcp-server/src/server.py"],
      "env": {
        "FHIR_SERVER_BASE_URL": "http://localhost:8103/fhir/R4"
      }
    }
  }
}
```

## Use Cases

### 1. Medication Ordering
```
"Order metformin 500mg twice daily for patient John Smith"
```

### 2. Post-Encounter Documentation
```
"Generate action items from today's encounter with Jane Doe"
```

## Project Structure

```
AgentEHR/
├── docker-compose.yml      # Medplum + supporting services
├── fhir-mcp-server/        # Python MCP server for FHIR
├── agents/                 # Agent orchestration workflows
├── frontend/               # Web UI (React/Streamlit)
├── data/synthea/           # Synthetic patient data
└── scripts/                # Setup and utility scripts
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| FHIR Backend | Medplum (self-hosted) |
| Sample Data | Synthea |
| MCP Server | Python |
| Agent Layer | Claude API |
| Voice | Whisper + ElevenLabs |

## References

- [Medplum Documentation](https://www.medplum.com/docs)
- [FHIR R4 Specification](https://hl7.org/fhir/R4/)
- [WSO2 FHIR MCP Server](https://github.com/wso2/fhir-mcp-server)
- [Wellsheet](https://www.wellsheet.com/) - Commercial validation of this approach
