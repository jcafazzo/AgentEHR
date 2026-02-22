"""
Authentication helper for Medplum FHIR server.

Handles OAuth token acquisition and refresh using password grant.
"""

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("fhir-mcp-server.auth")


@dataclass
class TokenInfo:
    """OAuth token information."""

    access_token: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"


class MedplumAuth:
    """Handles Medplum authentication using password flow."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
    ):
        self.base_url = base_url.rstrip("/").replace("/fhir/R4", "")
        self.email = email
        self.password = password
        self._token: TokenInfo | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        # Check if current token is valid (with 60s buffer)
        if self._token and self._token.expires_at > time.time() + 60:
            return self._token.access_token

        # Get new token
        await self._refresh_token()
        return self._token.access_token

    async def _refresh_token(self) -> None:
        """Get a new access token using password flow."""
        client = await self._get_client()

        # Step 1: Login
        code_challenge = "medplum_mcp_server_challenge"

        login_resp = await client.post(
            f"{self.base_url}/auth/login",
            json={
                "email": self.email,
                "password": self.password,
                "scope": "openid profile",
                "codeChallengeMethod": "plain",
                "codeChallenge": code_challenge,
            },
        )

        if login_resp.status_code != 200:
            raise Exception(f"Login failed: {login_resp.text}")

        login_data = login_resp.json()
        code = login_data.get("code")

        if not code:
            raise Exception(f"No auth code in login response: {login_data}")

        # Step 2: Exchange code for token
        token_resp = await client.post(
            f"{self.base_url}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_challenge,
            },
        )

        if token_resp.status_code != 200:
            raise Exception(f"Token exchange failed: {token_resp.text}")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)

        if not access_token:
            raise Exception(f"No access token in response: {token_data}")

        self._token = TokenInfo(
            access_token=access_token,
            expires_at=time.time() + expires_in,
        )

        logger.info("Successfully obtained new access token")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
