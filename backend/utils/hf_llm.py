"""Lazy HuggingFace text-generation adapter."""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache
from typing import Any

_generation_lock = threading.Lock()


class HuggingFaceLLM:
    """Load a Transformers pipeline only when generation is first requested."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._pipeline: Any = None

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline("text-generation", model=self.model_name)
        return self._pipeline

    async def generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int,
        temperature: float,
        seed: int,
    ) -> str:
        def run() -> str:
            import torch

            torch.manual_seed(seed)
            result = self._get_pipeline()(
                prompt,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=max(temperature, 0.01),
                return_full_text=False,
            )
            return str(result[0]["generated_text"]).strip()

        def locked_run() -> str:
            with _generation_lock:
                return run()

        return await asyncio.to_thread(locked_run)


@lru_cache(maxsize=1)
def get_hf_llm(model_name: str) -> HuggingFaceLLM:
    return HuggingFaceLLM(model_name)


def unload_hf_llm() -> None:
    get_hf_llm.cache_clear()
