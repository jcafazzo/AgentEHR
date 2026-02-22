#!/bin/bash
# AgentEHR Setup Script
# Sets up the complete development environment

set -e

echo "=== AgentEHR Setup ==="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install Python 3.11+ first."
    exit 1
fi

echo -e "${GREEN}Prerequisites OK${NC}"

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Start Medplum stack
echo -e "${YELLOW}Starting Medplum FHIR server...${NC}"
docker compose up -d

echo -e "${YELLOW}Waiting for Medplum to be healthy (this may take 1-2 minutes)...${NC}"
sleep 10

# Wait for health check
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:8103/healthcheck > /dev/null 2>&1; then
        echo -e "${GREEN}Medplum server is healthy!${NC}"
        break
    fi
    echo "Waiting for Medplum... ($((RETRY_COUNT + 1))/$MAX_RETRIES)"
    sleep 5
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Medplum did not become healthy in time. Check docker logs."
    exit 1
fi

# Set up Python virtual environment for MCP server
echo -e "${YELLOW}Setting up Python environment for MCP server...${NC}"
cd "$PROJECT_ROOT/fhir-mcp-server"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --quiet --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install --quiet -r requirements.txt
fi

echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "Services running:"
echo "  - Medplum Server: http://localhost:8103"
echo "  - Medplum App:    http://localhost:3000"
echo "  - PostgreSQL:     localhost:5432"
echo "  - Redis:          localhost:6379"
echo ""
echo "FHIR R4 endpoint: http://localhost:8103/fhir/R4"
echo ""
echo "Next steps:"
echo "  1. Run ./scripts/load_synthea.sh to load synthetic patient data"
echo "  2. Start the MCP server: cd fhir-mcp-server && source venv/bin/activate && python src/server.py"
