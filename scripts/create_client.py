#!/usr/bin/env python3
"""
Create a ClientApplication in Medplum for API access.

Usage:
1. First, register at http://localhost:3001 to create your admin account
2. Run: python scripts/create_client.py
3. Enter your email and password when prompted
4. The script will create a client and output the credentials
"""

import json
import sys

import httpx

MEDPLUM_BASE_URL = "http://localhost:8103"


def main():
    print("AgentEHR - Create API Client")
    print("=" * 40)
    print("\nFirst, make sure you've registered at http://localhost:3001")
    print()

    email = input("Enter your Medplum email: ").strip()
    password = input("Enter your Medplum password: ").strip()

    if not email or not password:
        print("Error: Email and password are required")
        sys.exit(1)

    print("\n1. Logging in...")

    # Step 1: Login
    login_resp = httpx.post(
        f"{MEDPLUM_BASE_URL}/auth/login",
        json={
            "email": email,
            "password": password,
            "scope": "openid",
            "codeChallengeMethod": "plain",
            "codeChallenge": "xyz",
        },
    )

    if login_resp.status_code != 200:
        print(f"Login failed: {login_resp.text}")
        sys.exit(1)

    login_data = login_resp.json()
    login_id = login_data.get("login")

    # Step 2: Get profile
    profile_resp = httpx.post(
        f"{MEDPLUM_BASE_URL}/auth/profile",
        json={"login": login_id},
    )

    if profile_resp.status_code != 200:
        print(f"Profile failed: {profile_resp.text}")
        sys.exit(1)

    profile_data = profile_resp.json()
    code = profile_data.get("code")

    # Step 3: Exchange code for token
    token_resp = httpx.post(
        f"{MEDPLUM_BASE_URL}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "xyz",
        },
    )

    if token_resp.status_code != 200:
        print(f"Token exchange failed: {token_resp.text}")
        sys.exit(1)

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    print("2. Logged in successfully!")
    print("\n3. Creating ClientApplication...")

    # Step 4: Create ClientApplication
    client_app = {
        "resourceType": "ClientApplication",
        "name": "AgentEHR MCP Server",
        "description": "Client for MCP server FHIR access",
    }

    create_resp = httpx.post(
        f"{MEDPLUM_BASE_URL}/fhir/R4/ClientApplication",
        json=client_app,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if create_resp.status_code not in (200, 201):
        print(f"Create client failed: {create_resp.text}")
        sys.exit(1)

    client_data = create_resp.json()
    client_id = client_data.get("id")
    client_secret = client_data.get("secret")

    print("\n" + "=" * 40)
    print("SUCCESS! ClientApplication created")
    print("=" * 40)
    print(f"\nClient ID:     {client_id}")
    print(f"Client Secret: {client_secret}")
    print()
    print("Add these to your environment:")
    print(f"  export FHIR_SERVER_CLIENT_ID='{client_id}'")
    print(f"  export FHIR_SERVER_CLIENT_SECRET='{client_secret}'")
    print()
    print("Or add to .env file in fhir-mcp-server/")

    # Save to .env file
    env_path = "fhir-mcp-server/.env"
    with open(env_path, "w") as f:
        f.write(f"FHIR_SERVER_BASE_URL={MEDPLUM_BASE_URL}/fhir/R4\n")
        f.write(f"FHIR_SERVER_CLIENT_ID={client_id}\n")
        f.write(f"FHIR_SERVER_CLIENT_SECRET={client_secret}\n")

    print(f"\nCredentials saved to {env_path}")


if __name__ == "__main__":
    main()
