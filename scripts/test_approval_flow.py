#!/usr/bin/env python3
"""
Test the end-to-end approval flow.

Tests:
1. Create a medication order (draft)
2. List pending actions
3. Approve the action
4. Verify status changed to active
"""

import asyncio
import sys

sys.path.insert(0, "fhir-mcp-server/src")

from handlers import (
    fhir_client,
    handle_search_patient,
    handle_create_medication_request,
    handle_list_pending_actions,
    handle_approve_action,
    handle_reject_action,
)
from approval_queue import get_approval_queue


async def test_approval_flow():
    print("=" * 60)
    print("AgentEHR - Approval Flow Test")
    print("=" * 60)

    # Step 1: Search for a patient
    print("\n1. Searching for patient 'John Smith'...")
    search_result = await handle_search_patient({"query": "John Smith"})

    if search_result.get("total", 0) == 0:
        print("   No patient found. Creating test patient...")
        # Create a test patient
        patient = await fhir_client.create("Patient", {
            "resourceType": "Patient",
            "name": [{"given": ["John"], "family": "Smith"}],
            "gender": "male",
            "birthDate": "1980-01-15",
        })
        patient_id = patient.get("id")
        print(f"   Created patient: {patient_id}")
    else:
        patient = search_result["patients"][0]
        patient_id = patient["id"]
        print(f"   Found patient: {patient['name']} (ID: {patient_id})")

    # Step 2: Create a medication order
    print("\n2. Creating medication order (Metformin 500mg)...")
    order_result = await handle_create_medication_request({
        "patient_id": patient_id,
        "medication_name": "Metformin",
        "dosage": "500mg",
        "frequency": "twice daily",
    })

    print(f"   Status: {order_result.get('status')}")
    print(f"   Action ID: {order_result.get('action_id')}")
    print(f"   FHIR ID: {order_result.get('medicationRequest', {}).get('id')}")
    print(f"   Message: {order_result.get('message')}")

    if order_result.get("warnings"):
        print("   Warnings:")
        for w in order_result["warnings"]:
            print(f"     - {w['severity']}: {w['message']}")

    action_id = order_result.get("action_id")
    fhir_id = order_result.get("medicationRequest", {}).get("id")

    # Step 3: List pending actions
    print("\n3. Listing pending actions...")
    pending = await handle_list_pending_actions({"patient_id": patient_id})
    print(f"   Found {pending.get('count', 0)} pending action(s)")

    for action in pending.get("actions", []):
        print(f"     - {action['summary']} (ID: {action['action_id'][:8]}...)")

    # Step 4: Approve the action
    print("\n4. Approving the medication order...")
    approve_result = await handle_approve_action({"action_id": action_id})
    print(f"   Status: {approve_result.get('status')}")
    print(f"   Message: {approve_result.get('message')}")

    # Step 5: Verify the FHIR resource status
    print("\n5. Verifying FHIR resource status...")
    med_request = await fhir_client.read("MedicationRequest", fhir_id)
    status = med_request.get("status")
    print(f"   MedicationRequest status: {status}")

    if status == "active":
        print("\n✅ SUCCESS: Medication order approved and activated!")
    else:
        print(f"\n❌ UNEXPECTED: Status is '{status}', expected 'active'")

    # Step 6: Verify queue is empty
    print("\n6. Verifying queue is empty...")
    pending_after = await handle_list_pending_actions({"patient_id": patient_id})
    print(f"   Pending actions: {pending_after.get('count', 0)}")

    # Step 7: Test rejection flow
    print("\n7. Testing rejection flow...")
    print("   Creating another medication order...")
    order2_result = await handle_create_medication_request({
        "patient_id": patient_id,
        "medication_name": "Lisinopril",
        "dosage": "10mg",
        "frequency": "once daily",
    })
    action_id_2 = order2_result.get("action_id")
    fhir_id_2 = order2_result.get("medicationRequest", {}).get("id")
    print(f"   Created order with Action ID: {action_id_2[:8]}...")

    print("   Rejecting the order...")
    reject_result = await handle_reject_action({
        "action_id": action_id_2,
        "reason": "Test rejection",
    })
    print(f"   Status: {reject_result.get('status')}")
    print(f"   Draft deleted: {reject_result.get('draft_deleted')}")

    # Verify the draft was deleted
    try:
        await fhir_client.read("MedicationRequest", fhir_id_2)
        print("   ❌ Draft still exists!")
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            print("   ✅ Draft successfully deleted")
        else:
            print(f"   ⚠️ Error checking draft: {e}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

    # Print queue stats
    queue = get_approval_queue()
    print(f"\nQueue Stats: {queue.stats()}")


async def test_drug_interaction():
    """Test that drug interactions are detected."""
    print("\n" + "=" * 60)
    print("Drug Interaction Test")
    print("=" * 60)

    # Find a patient
    search_result = await handle_search_patient({"query": "John"})
    if search_result.get("total", 0) == 0:
        print("No patient found for interaction test")
        return

    patient_id = search_result["patients"][0]["id"]

    # First, create an active warfarin order
    print("\n1. Creating active Warfarin prescription...")
    warfarin = await fhir_client.create("MedicationRequest", {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "subject": {"reference": f"Patient/{patient_id}"},
        "medicationCodeableConcept": {"text": "Warfarin 5mg"},
    })
    print(f"   Created Warfarin prescription: {warfarin.get('id')}")

    # Now try to order aspirin (should trigger interaction warning)
    print("\n2. Ordering Aspirin (should detect interaction)...")
    order_result = await handle_create_medication_request({
        "patient_id": patient_id,
        "medication_name": "Aspirin",
        "dosage": "81mg",
        "frequency": "once daily",
    })

    print(f"   Safety check safe: {order_result.get('safety', {}).get('safe')}")
    print(f"   Warning count: {order_result.get('safety', {}).get('warning_count')}")

    if order_result.get("warnings"):
        print("   ⚠️ Interaction warnings detected:")
        for w in order_result["warnings"]:
            print(f"     - {w['severity'].upper()}: {w['message']}")
        print("\n✅ Drug interaction detection working!")
    else:
        print("\n❌ No warnings detected (expected interaction warning)")

    # Clean up - reject the aspirin order
    action_id = order_result.get("action_id")
    if action_id:
        await handle_reject_action({"action_id": action_id, "reason": "Test cleanup"})


async def main():
    await test_approval_flow()
    await test_drug_interaction()


if __name__ == "__main__":
    asyncio.run(main())
