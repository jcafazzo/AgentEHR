#!/usr/bin/env python3
"""
OpenRouter Client for AgentEHR

Provides an OpenAI-compatible interface to OpenRouter, allowing use of
various models including GLM-5, Claude, GPT-4, etc.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("agentehr.openrouter")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


@dataclass
class ToolCall:
    """Represents a tool call from the model."""
    id: str
    name: str
    arguments: dict


@dataclass
class OpenRouterMessage:
    """A message in OpenRouter format."""
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class OpenRouterResponse:
    """Response from OpenRouter API."""
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    model: str
    usage: dict


class OpenRouterClient:
    """
    Client for OpenRouter API with tool/function calling support.

    Supports models like:
    - thudm/glm-4-plus (GLM-4)
    - anthropic/claude-3.5-sonnet
    - openai/gpt-4o
    - google/gemini-2.0-flash-exp
    """

    # Model aliases for convenience
    MODEL_ALIASES = {
        "glm-5": "z-ai/glm-5",              # GLM-5 flagship model
        "glm-4": "z-ai/glm-4.5",            # GLM-4.5 (current gen)
        "glm-flash": "z-ai/glm-4.7-flash",  # Fast/cheap option
        "claude-sonnet": "anthropic/claude-3.5-sonnet",
        "claude-opus": "anthropic/claude-3-opus",
        "gpt-4o": "openai/gpt-4o",
        "gemini": "google/gemini-2.5-flash-lite",
        "gemini-3-flash": "google/gemini-3-flash-preview",
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "glm-5",
        site_url: str = "https://agentehr.local",
        site_name: str = "AgentEHR",
    ):
        """
        Initialize OpenRouter client.

        Args:
            api_key: OpenRouter API key (or from OPENROUTER_API_KEY env var)
            model: Model to use (can be alias or full model ID)
            site_url: Your site URL (for OpenRouter rankings)
            site_name: Your site name
        """
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY or ANTHROPIC_API_KEY environment variable required")

        # Resolve model alias
        self.model = self.MODEL_ALIASES.get(model, model)
        self.site_url = site_url
        self.site_name = site_name

        self.client = httpx.AsyncClient(
            base_url=OPENROUTER_API_BASE,
            timeout=120.0,
        )

        logger.info(f"OpenRouter client initialized with model: {self.model}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def _convert_tools_to_openai_format(self, tools: list[dict]) -> list[dict]:
        """Convert Anthropic-style tools to OpenAI format."""
        openai_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            openai_tools.append(openai_tool)
        return openai_tools

    def _convert_messages_to_openai_format(self, messages: list[dict]) -> list[dict]:
        """Convert messages to OpenAI format."""
        openai_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")

            # Handle tool results
            if role == "user" and isinstance(content, list):
                # Check for tool_result blocks
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content": json.dumps(block.get("content", "")),
                        })
                continue

            # Handle assistant messages with tool calls
            if role == "assistant" and isinstance(content, list):
                text_content = ""
                tool_calls = []

                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_content += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })

                msg_dict = {"role": "assistant"}
                if text_content:
                    msg_dict["content"] = text_content
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                openai_messages.append(msg_dict)
                continue

            # Standard message
            openai_messages.append({
                "role": role,
                "content": content if isinstance(content, str) else json.dumps(content),
            })

        return openai_messages

    async def create_message(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> OpenRouterResponse:
        """
        Create a chat completion with OpenRouter.

        Args:
            messages: Conversation messages
            system: System prompt
            tools: Available tools (Anthropic format)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            OpenRouterResponse with content and/or tool calls
        """
        # Build request
        openai_messages = self._convert_messages_to_openai_format(messages)

        # Add system message at the start
        if system:
            openai_messages.insert(0, {"role": "system", "content": system})

        request_body = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Add tools if provided
        if tools:
            request_body["tools"] = self._convert_tools_to_openai_format(tools)
            request_body["tool_choice"] = "auto"

        # Make request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
            "Content-Type": "application/json",
        }

        logger.debug(f"Sending request to OpenRouter: {self.model}")

        response = await self.client.post(
            "/chat/completions",
            json=request_body,
            headers=headers,
        )

        if response.status_code != 200:
            error_text = response.text
            logger.error(f"OpenRouter error: {response.status_code} - {error_text}")
            raise Exception(f"OpenRouter API error: {response.status_code} - {error_text}")

        data = response.json()

        # Parse response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        # Extract tool calls
        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))

        return OpenRouterResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
        )


# Convenience function to get available models
async def list_models(api_key: str | None = None) -> list[dict]:
    """List available models on OpenRouter."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{OPENROUTER_API_BASE}/models",
            headers={"Authorization": f"Bearer {key}"},
        )

        if response.status_code == 200:
            return response.json().get("data", [])
        return []
