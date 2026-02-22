# Claude Desktop Configuration for AgentEHR

This document explains how to configure Claude Desktop to use the AgentEHR FHIR MCP Server.

## Prerequisites

1. **Medplum Running** - Ensure the FHIR server is running:
   ```bash
   cd /path/to/AgentEHR
   docker compose up -d
   ```

2. **Python Environment** - Set up the MCP server:
   ```bash
   cd fhir-mcp-server
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## Claude Desktop Configuration

Add the following to your Claude Desktop configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "agentehr-fhir": {
      "command": "python",
      "args": ["/Users/YOUR_USERNAME/CODING/AgentEHR/fhir-mcp-server/src/server.py"],
      "env": {
        "FHIR_SERVER_BASE_URL": "http://localhost:8103/fhir/R4",
        "FHIR_SERVER_DISABLE_AUTHORIZATION": "true"
      }
    }
  }
}
```

**Replace `/Users/YOUR_USERNAME/CODING/AgentEHR` with your actual path.**

## Claude Code Configuration

For Claude Code (CLI), add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agentehr-fhir": {
      "command": "python",
      "args": ["/Users/YOUR_USERNAME/CODING/AgentEHR/fhir-mcp-server/src/server.py"],
      "env": {
        "FHIR_SERVER_BASE_URL": "http://localhost:8103/fhir/R4",
        "FHIR_SERVER_DISABLE_AUTHORIZATION": "true"
      }
    }
  }
}
```

## Verification

After configuration, restart Claude Desktop/Claude Code and verify the tools are available:

1. Start a new conversation
2. Ask: "What FHIR tools do you have available?"
3. You should see tools like `search_patient`, `get_patient_summary`, etc.

## Example Usage

Once configured, you can interact with the EHR naturally:

```
User: Search for patients named Smith

Claude: [Uses search_patient tool]
Found 5 patients with the name Smith:
1. John Smith (ID: 12345) - DOB: 1965-03-15
2. Jane Smith (ID: 12346) - DOB: 1978-07-22
...

User: Get the patient summary for John Smith

Claude: [Uses get_patient_summary tool]
Patient Summary for John Smith (ID: 12345)

Demographics:
- DOB: March 15, 1965 (Age: 60)
- Gender: Male

Active Conditions:
- Type 2 Diabetes Mellitus
- Hypertension

Current Medications:
- Metformin 500mg twice daily
- Lisinopril 10mg once daily

Allergies:
- Penicillin (rash)
```

## Troubleshooting

### MCP Server Not Connecting
1. Check Python path is correct
2. Verify virtual environment has all dependencies
3. Check Medplum is running: `curl http://localhost:8103/healthcheck`

### FHIR Server Unreachable
1. Verify Docker containers are running: `docker compose ps`
2. Check port 8103 is not blocked
3. Review Medplum logs: `docker compose logs medplum-server`

### Tool Errors
1. Check MCP server logs for detailed errors
2. Verify patient IDs are valid
3. Ensure FHIR resources exist in Medplum
