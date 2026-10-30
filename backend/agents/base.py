"""Abstract interfaces for rule-based and LLM-backed agents."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.core.config import Settings, get_settings
from backend.core.constants import DEFAULT_GENERATION_SEED
from backend.core.exceptions import ConfigurationError, ModelNotLoadedError
from backend.utils.async_utils import retry
from backend.utils.hf_llm import HuggingFaceLLM
from backend.utils.http_client import get_http_client

logger = logging.getLogger(__name__)
AgentState = dict[str, Any]


class BaseAgent(ABC):
    """Common interface driven by the Supervisor."""

    def __init__(self, name: str | None = None):
        self.name = name or self.__class__.__name__
        self._last_result: Any = None

    @abstractmethod
    async def process(self, state: AgentState) -> AgentState:
        """Process and return the mutable pipeline state."""

    def get_last_result(self) -> Any:
        return self._last_result


class Agent(BaseAgent):
    """Base class for agents that can call YandexGPT or HuggingFace."""

    temperature = 0.0
    max_new_tokens = 768

    def __init__(self, name: str | None = None, engine: str | None = None):
        super().__init__(name)
        self.settings: Settings = get_settings()
        self.engine = self._resolve_engine(engine or self.settings.agent_engine)
        self.hf_llm: HuggingFaceLLM | None = None
        if self.engine == "huggingface":
            self.hf_llm = HuggingFaceLLM(self.settings.hf_model)

    def _resolve_engine(self, requested: str) -> str:
        normalized = (requested or "auto").lower()
        if normalized == "auto":
            return "yandexgpt" if self.settings.yandex_api_key else "huggingface"
        if normalized in {"yandexgpt", "huggingface"}:
            return normalized
        logger.warning("[%s] Unknown engine %s; using yandexgpt", self.name, requested)
        return "yandexgpt"

    @retry(max_attempts=3, delay=1.0)
    async def _call_llm(self, prompt: str) -> str:
        if self.engine == "huggingface":
            if self.hf_llm is None:
                raise ModelNotLoadedError("HuggingFace model is not initialized")
            return await self.hf_llm.generate(
                prompt,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                seed=DEFAULT_GENERATION_SEED,
            )

        if not self.settings.yandex_api_key or not self.settings.yandex_folder_id:
            raise ConfigurationError(
                "YANDEX_API_KEY and YANDEX_FOLDER_ID are required for YandexGPT"
            )
        payload = {
            "modelUri": (
                f"gpt://{self.settings.yandex_folder_id}/"
                f"{self.settings.yandex_gpt_model}"
            ),
            "completionOptions": {
                "stream": False,
                "temperature": self.temperature,
                "maxTokens": str(self.max_new_tokens),
            },
            "messages": [{"role": "user", "text": prompt}],
        }
        headers = {
            "Authorization": (
                f"Api-Key {self.settings.yandex_api_key.get_secret_value()}"
            ),
            "Content-Type": "application/json",
        }
        response = await get_http_client().post(
            self.settings.yandex_gpt_endpoint, json=payload, headers=headers
        )
        response.raise_for_status()
        return str(
            response.json()["result"]["alternatives"][0]["message"]["text"]
        ).strip()
