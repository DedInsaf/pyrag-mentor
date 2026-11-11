"""Run reproducible combinations of weather data, retrieval and agents."""

import asyncio
import hashlib
import json
import os
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.base import Agent
from backend.agents.critic import Critic
from backend.agents.editor import Editor
from backend.agents.supervisor import Supervisor
from backend.agents.validator import Validator
from backend.core.config import get_settings
from backend.data.weather import Weather
from backend.db.models import GlossaryEntry, ResponseCache
from backend.db.weather import WeatherReview
from backend.retrieval.weather_index import index

Mode = Literal[
    "baseline",
    "glossary",
    "tm",
    "tm_hybrid",
    "agents_only",
    "tm_hybrid_critic",
    "tm_hybrid_editor",
    "full",
]
Engine = Literal["rules", "auto", "yandexgpt", "huggingface"]
MODES = (
    "baseline",
    "glossary",
    "tm",
    "tm_hybrid",
    "agents_only",
    "tm_hybrid_critic",
    "tm_hybrid_editor",
    "full",
)
LIMIT = asyncio.Semaphore(4)


class EngineUnavailable(RuntimeError):
    pass


class WeatherWriter(Agent):
    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        state["answer"] = await self._call_llm(state["prompt"])
        return state


async def explain(
    db: AsyncSession,
    weather: Weather,
    label: str,
    mode: Mode,
    engine: Engine,
    strict: bool,
) -> dict[str, Any]:
    async with LIMIT:
        return await _explain(db, weather, label, mode, engine, strict)


async def _explain(
    db: AsyncSession,
    weather: Weather,
    label: str,
    mode: Mode,
    engine: Engine,
    strict: bool,
) -> dict[str, Any]:
    settings = get_settings()
    target = engine
    if engine == "auto":
        target = (
            "yandexgpt"
            if settings.yandex_api_key and settings.yandex_folder_id
            else "huggingface"
        )
    facts = weather.model_dump(mode="json")
    key = hashlib.sha256(
        json.dumps([facts, label, mode, target, strict], sort_keys=True).encode()
    ).hexdigest()
    stmt = select(ResponseCache).where(
        ResponseCache.category == "weather",
        ResponseCache.parameters_hash == key,
        ResponseCache.model_used == target,
    )
    cached = await db.scalar(stmt)
    if cached:
        await db.execute(
            update(ResponseCache)
            .where(ResponseCache.id == cached.id)
            .values(hits=ResponseCache.hits + 1)
        )
        await db.commit()
        return {**json.loads(cached.output), "cached": True}

    question = f"Как будет выглядеть {label} при погоде «{weather.condition}»?"
    context: list[str] = []
    if mode not in {"baseline", "agents_only"}:
        context.extend(
            await db.scalars(
                select(GlossaryEntry.definition)
                .where(
                    GlossaryEntry.category == "weather",
                    GlossaryEntry.id.like(f"wmo-{weather.weather_code}-%")
                    | GlossaryEntry.term.icontains(weather.condition, autoescape=True),
                )
                .order_by(GlossaryEntry.id)
                .limit(2)
            )
        )
    if mode in {"tm", "tm_hybrid", "tm_hybrid_critic", "tm_hybrid_editor", "full"}:
        context.extend(
            await index.search(db, f"{label} {weather.condition}", mode != "tm")
        )
    text = (
        f"{label}. Ожидается {weather.condition}, {weather.temperature_2m:g} °C. "
        f"Вероятность осадков {weather.precipitation_probability}%, "
        f"облачность {weather.cloud_cover}%. "
        "На изображении показано "
        f"{'дневное' if weather.is_day else 'ночное'} освещение."
    )
    used = target
    if target != "rules":
        prompt = (
            "Кратко опиши ожидаемый вид улицы на русском. Факты прогноза обязательны; "
            "архивные примеры — только для описания. Не выдумывай данные. "
            f"{text}\nКонтекст: {context}"
        )
        for provider in (target, "huggingface"):
            try:
                state = await WeatherWriter(engine=provider).process({"prompt": prompt})
                text, used = state["answer"], provider
                break
            except Exception as exc:
                if (
                    strict
                    or provider == "huggingface"
                    or not settings.fallback_to_huggingface
                ):
                    raise EngineUnavailable(
                        "Выбранный текстовый движок недоступен"
                    ) from exc
    state = {
        "question": question,
        "answer": text,
        "sources": ["Open-Meteo", *context],
        "reasoning_log": [],
    }
    if mode in {"full", "agents_only", "tm_hybrid_critic", "tm_hybrid_editor"}:
        if used == "rules":
            state = await Validator().process(state)
        elif mode == "tm_hybrid_critic":
            state = await Critic(engine=used).process(await Validator().process(state))
        elif mode == "tm_hybrid_editor":
            state = await Editor(engine=used).process(await Validator().process(state))
        else:
            state = await Supervisor(
                critic=Critic(engine=used), editor=Editor(engine=used)
            ).process(state)
    uncertain = state.get("validation_passed") is False or state.get(
        "critic_failed", False
    )
    score = state.get("critic_score")
    if (uncertain or (score is not None and score < 7)) and os.getenv(
        "ACTIVE_LEARNING_ENABLED", "true"
    ) == "true":
        insert = (
            sqlite_insert if db.bind and db.bind.dialect.name == "sqlite" else pg_insert
        )
        await db.execute(
            insert(WeatherReview)
            .values(id=key, question=question, draft=state["answer"])
            .on_conflict_do_nothing(index_elements=["id"])
        )

    result = {
        "description": state["answer"],
        "engine_used": used,
        "mode": mode,
        "cached": False,
        "reasoning_log": state["reasoning_log"],
        "critic_score": score,
        "context": context,
    }
    insert = (
        sqlite_insert if db.bind and db.bind.dialect.name == "sqlite" else pg_insert
    )
    await db.execute(
        insert(ResponseCache)
        .values(
            category="weather",
            parameters_hash=key,
            model_used=used,
            input_text=label,
            output=json.dumps(result, ensure_ascii=False),
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
    return result
