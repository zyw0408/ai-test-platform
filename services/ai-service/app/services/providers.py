from __future__ import annotations
import json
import logging
import httpx
from abc import ABC, abstractmethod
from typing import Any, Optional
from app.config import Settings

logger = logging.getLogger(__name__)

class ModelProvider(ABC):
    @abstractmethod
    async def complete_json(self, prompt: str) -> dict[str, Any] | None:
        """Deprecated: use generate_structured_response instead"""
        raise NotImplementedError

    @abstractmethod
    async def generate_structured_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_model: Any = None,
    ) -> Any:
        raise NotImplementedError


class OpenAICompatibleProvider(ModelProvider):
    def __init__(
        self,
        settings: Settings,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = base_url or settings.model_base_url
        self.api_key = api_key or settings.model_api_key
        self.model_name = model_name or settings.model_name

    async def complete_json(self, prompt: str) -> dict[str, Any] | None:
        """Compatibility shim for old code"""
        return await self.generate_structured_response(prompt)

    async def generate_structured_response(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_model: Any = None,
    ) -> Any:
        if not self.base_url or not self.api_key:
            logger.error("AI Provider configured without base_url or api_key")
            return {"error": "AI provider not configured"}

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
                
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                return {"error": "AI returned empty content"}
                
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If it's not JSON but was requested as JSON, try to wrap it or return as is
                return {"summary": content, "source": "raw-text"}
        except Exception as e:
            logger.error(f"AI call failed: {str(e)}")
            return {"error": f"AI call failed: {str(e)}"}


def build_provider(
    settings: Settings,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> ModelProvider:
    return OpenAICompatibleProvider(
        settings, base_url=base_url, api_key=api_key, model_name=model_name
    )
