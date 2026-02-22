#!/usr/bin/env python3
"""
Test the FHIR MCP Server functionality.

Run from the fhir-mcp-server directory:
  python test_server.py
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from server import fhir_client, handle_search_patient, handle_get_patient_summary


async def test_fhir_connection():
    """Test basic FHIR server connectivity."""
    print("Testing FHIR server connection...")

    try:
        result = await fhir_client.search("Patient", {"_count": "5"})
        patients = result.get("entry", [])
        print(f"  Found {len(patients)} patients")

        if patients:
            patient = patients[0]["resource"]
            name = patient.get("name", [{}])[0]
            print(f"  First patient: {name.get('given', [''])[0]} {name.get('family', '')}")

        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


async def test_search_patient():
    """Test patient search tool."""
    print("\nTesting search_patient tool...")

    try:
        result = await handle_search_patient({"name": "Smith"})
        patients = result.get("patients", [])
        print(f"  Found {len(patients)} patients named Smith")

        for p in patients[:3]:
            print(f"    - {p['name']} (ID: {p['id']})")

        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


async def test_patient_summary():
    """Test patient summary tool."""
    print("\nTesting get_patient_summary tool...")

    try:
        # First get a patient ID
        search_result = await fhir_client.search("Patient", {"_count": "1"})
        patients = search_result.get("entry", [])

        if not patients:
            print("  No patients found to test")
            return False

        patient_id = patients[0]["resource"]["id"]
        print(f"  Getting summary for patient {patient_id}...")

        result = await handle_get_patient_summary({"patient_id": patient_id})
        print(f"  Patient: {result['patient']['name']}")
        print(f"  Active Conditions: {len(result.get('activeConditions', []))}")
        print(f"  Active Medications: {len(result.get('activeMedications', []))}")
        print(f"  Allergies: {len(result.get('allergies', []))}")

        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 50)
    print("AgentEHR FHIR MCP Server Test Suite")
    print("=" * 50)

    results = []

    results.append(("FHIR Connection", await test_fhir_connection()))
    results.append(("Search Patient", await test_search_patient()))
    results.append(("Patient Summary", await test_patient_summary()))

    print("\n" + "=" * 50)
    print("Results:")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed!")
    else:
        print("Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
