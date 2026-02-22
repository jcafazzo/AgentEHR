#!/bin/bash
# Load Synthea Synthetic Patient Data into Medplum
# Downloads pre-generated synthetic data and uploads to FHIR server

set -e

echo "=== Loading Synthea Synthetic Data ==="

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data/synthea"

# Configuration
FHIR_BASE_URL="${FHIR_BASE_URL:-http://localhost:8103/fhir/R4}"
SYNTHEA_SAMPLE_SIZE="${SYNTHEA_SAMPLE_SIZE:-100}"

# Check if Medplum is running
echo -e "${YELLOW}Checking Medplum connectivity...${NC}"
if ! curl -s "$FHIR_BASE_URL/metadata" > /dev/null 2>&1; then
    echo "Cannot connect to FHIR server at $FHIR_BASE_URL"
    echo "Make sure Medplum is running: docker compose up -d"
    exit 1
fi
echo -e "${GREEN}FHIR server is accessible${NC}"

# Create data directory if it doesn't exist
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

# Option 1: Download pre-generated Synthea data
echo -e "${YELLOW}Downloading Synthea sample data...${NC}"

# Check if we need to download
if [ ! -f "fhir" ] && [ ! -d "fhir" ]; then
    # Download Synthea 1K sample from official source
    SYNTHEA_URL="https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_fhir_r4_sep2019.zip"

    if command -v wget &> /dev/null; then
        wget -q --show-progress -O synthea_sample.zip "$SYNTHEA_URL" || {
            echo "Failed to download from official source. Trying alternative..."
            # Alternative: generate fresh data
            echo "Will generate fresh Synthea data instead."
        }
    elif command -v curl &> /dev/null; then
        curl -L -o synthea_sample.zip "$SYNTHEA_URL" || {
            echo "Failed to download. Will generate fresh data."
        }
    fi

    if [ -f "synthea_sample.zip" ]; then
        echo "Extracting data..."
        unzip -q synthea_sample.zip
        rm synthea_sample.zip
    fi
fi

# Option 2: Generate fresh data with Synthea (if download failed or user wants fresh)
generate_synthea_data() {
    echo -e "${YELLOW}Generating fresh Synthea data...${NC}"

    # Check if Java is available
    if ! command -v java &> /dev/null; then
        echo "Java is required for Synthea. Please install Java 11+ or use pre-generated data."
        return 1
    fi

    # Download Synthea if not present
    if [ ! -f "synthea-with-dependencies.jar" ]; then
        echo "Downloading Synthea..."
        curl -L -o synthea-with-dependencies.jar \
            "https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar"
    fi

    # Generate patients
    echo "Generating $SYNTHEA_SAMPLE_SIZE synthetic patients..."
    java -jar synthea-with-dependencies.jar \
        -p "$SYNTHEA_SAMPLE_SIZE" \
        --exporter.fhir.export true \
        --exporter.fhir.bulk_data false \
        --exporter.baseDirectory "$DATA_DIR"

    echo -e "${GREEN}Generated $SYNTHEA_SAMPLE_SIZE patients${NC}"
}

# Upload FHIR bundles to Medplum
upload_to_medplum() {
    echo -e "${YELLOW}Uploading data to Medplum...${NC}"

    # Find FHIR bundle files
    FHIR_DIR="$DATA_DIR/fhir"
    if [ ! -d "$FHIR_DIR" ]; then
        FHIR_DIR="$DATA_DIR/output/fhir"
    fi

    if [ ! -d "$FHIR_DIR" ]; then
        echo "No FHIR data directory found. Please check the download or generation."
        return 1
    fi

    # Count files
    FILE_COUNT=$(find "$FHIR_DIR" -name "*.json" -type f 2>/dev/null | wc -l)
    echo "Found $FILE_COUNT FHIR bundle files"

    # Upload each bundle (limit for demo)
    UPLOADED=0
    MAX_UPLOAD="${MAX_UPLOAD:-100}"

    for file in "$FHIR_DIR"/*.json; do
        if [ $UPLOADED -ge $MAX_UPLOAD ]; then
            echo "Reached upload limit of $MAX_UPLOAD bundles"
            break
        fi

        if [ -f "$file" ]; then
            # Upload as transaction bundle
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                -X POST \
                -H "Content-Type: application/fhir+json" \
                -d @"$file" \
                "$FHIR_BASE_URL")

            if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 201 ]; then
                UPLOADED=$((UPLOADED + 1))
                echo -ne "\rUploaded: $UPLOADED / $MAX_UPLOAD bundles"
            else
                echo -e "\nWarning: Failed to upload $(basename "$file") (HTTP $HTTP_CODE)"
            fi
        fi
    done

    echo ""
    echo -e "${GREEN}Successfully uploaded $UPLOADED patient bundles${NC}"
}

# Main flow
if [ -d "$DATA_DIR/fhir" ] || [ -d "$DATA_DIR/output/fhir" ]; then
    echo "Found existing Synthea data"
    upload_to_medplum
elif [ "$1" == "--generate" ]; then
    generate_synthea_data
    upload_to_medplum
else
    echo "No Synthea data found and download may have failed."
    echo ""
    echo "Options:"
    echo "  1. Re-run this script to retry download"
    echo "  2. Run with --generate flag to generate fresh data (requires Java)"
    echo "  3. Manually download from https://synthea.mitre.org/downloads"
    echo ""
    echo "Example: ./load_synthea.sh --generate"
fi

echo ""
echo "=== Data Loading Complete ==="
echo ""
echo "Verify data at: $FHIR_BASE_URL/Patient"
echo "Or use Medplum App: http://localhost:3000"
