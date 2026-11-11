"""Evaluate the eight text-pipeline modes against held-out archive facts."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sacrebleu.metrics import CHRF

from backend.data.weather import Weather
from backend.db.session import AsyncSessionLocal, async_engine
from backend.services.weather import MODES, EngineUnavailable, explain


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--engine", choices=["rules", "yandexgpt", "huggingface"], default="rules"
    )
    args = parser.parse_args()
    rows = json.loads(args.dataset.read_text())[: args.limit]
    if not rows:
        parser.error("Нужна хотя бы одна запись")
    results = {}
    try:
        for mode in MODES:
            outputs, refs, temps, conditions = [], [], [], []
            for row in rows:
                time = datetime.fromisoformat(row["time"]).replace(tzinfo=UTC)
                data = Weather(
                    time=time,
                    temperature_2m=row["temperature"],
                    precipitation_probability=0,
                    precipitation=row["precipitation"],
                    weather_code=row["code"],
                    cloud_cover=0,
                    is_day=6 <= time.hour < 18,
                )
                async with AsyncSessionLocal() as db:
                    try:
                        result = await explain(
                            db, data, row["city"], mode, args.engine, True
                        )
                    except EngineUnavailable:
                        continue
                text = result["description"]
                outputs.append(text)
                refs.append(row["reference"])
                temperatures = re.findall(r"(-?\d+(?:[.,]\d+)?)\s*°\s*C", text)
                temps.append(
                    any(
                        float(value.replace(",", ".")) == row["temperature"]
                        for value in temperatures
                    )
                )
                conditions.append(data.condition in text.casefold())
            results[mode] = {
                "count": len(outputs),
                "failed": len(rows) - len(outputs),
                "temperature_accuracy": sum(temps) / len(temps) if temps else None,
                "condition_accuracy": (
                    sum(conditions) / len(conditions) if conditions else None
                ),
                "chrf": CHRF().corpus_score(outputs, [refs]).score if outputs else None,
            }
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
