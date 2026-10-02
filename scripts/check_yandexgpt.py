from __future__ import annotations

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

PLACEHOLDER_PREFIX = "replace_with_"


async def check_yandexgpt() -> None:
    load_dotenv()

    api_key = os.getenv("YANDEX_API_KEY", "")
    folder_id = os.getenv("YANDEX_FOLDER_ID", "")
    model = os.getenv("YANDEX_GPT_MODEL", "yandexgpt/latest")
    endpoint = os.getenv(
        "YANDEX_GPT_ENDPOINT",
        "https://ai.api.cloud.yandex.net/foundationModels/v1/completion",
    )

    if not api_key or api_key.startswith(PLACEHOLDER_PREFIX):
        raise RuntimeError("Заполните YANDEX_API_KEY в .env")
    if not folder_id or folder_id.startswith(PLACEHOLDER_PREFIX):
        raise RuntimeError("Заполните YANDEX_FOLDER_ID в .env")

    payload = {
        "modelUri": f"gpt://{folder_id}/{model}",
        "completionOptions": {
            "stream": False,
            "temperature": 0,
            "maxTokens": "32",
        },
        "messages": [
            {
                "role": "user",
                "text": "Ответь одним словом: сколько будет два плюс пять?",
            }
        ],
    }
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()

    result = response.json()
    text = result["result"]["alternatives"][0]["message"]["text"]
    print(f"[OK] YandexGPT ответил: {text.strip()}")


def main() -> int:
    try:
        asyncio.run(check_yandexgpt())
    except (RuntimeError, httpx.HTTPError, KeyError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
