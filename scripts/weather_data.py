"""Import weather observations and generate reproducible held-out evaluation sets."""

import argparse
import asyncio
import json
from pathlib import Path
from random import Random

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.db.models import Base, GlossaryEntry, KnowledgeBaseEntry
from backend.db.session import AsyncSessionLocal, async_engine

CITIES = {
    "Казань": (55.79, 49.12),
    "Москва": (55.75, 37.62),
    "Санкт-Петербург": (59.93, 30.31),
    "Екатеринбург": (56.84, 60.61),
}
SOURCE = "https://open-meteo.com/en/docs/historical-weather-api"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
CODES = {
    0: "ясно",
    1: "малооблачно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман с изморозью",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "слабая ледяная морось",
    57: "ледяная морось",
    61: "слабый дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "слабый ледяной дождь",
    67: "ледяной дождь",
    71: "слабый снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "слабый ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "снежный заряд",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с сильным градом",
}
VISUALS = {
    "день": "сохранить дневное освещение",
    "ночь": "затемнить сцену с сохранением контуров",
    "сухой асфальт": "не добавлять луж без осадков",
    "мокрый асфальт": "показать отражения в местах намокания",
    "далёкие здания": "учесть снижение видимости при осадках",
    "открытая площадь": "сохранить планировку площади",
    "парк": "сохранить положение деревьев и дорожек",
    "набережная": "сохранить линию берега",
    "жилой квартал": "сохранить фасады и окна",
    "центр города": "сохранить узнаваемые здания",
}
SCENES = ["день", "ночь"]


async def observations(start: str, end: str) -> dict[str, list[dict]]:
    async def city_data(client, city, latitude, longitude):
        response = await client.get(
            ARCHIVE,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start,
                "end_date": end,
                "hourly": "temperature_2m,weather_code,precipitation",
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        hourly = response.json()["hourly"]
        result = []
        for time, temperature, code, rain in zip(
            hourly["time"],
            hourly["temperature_2m"],
            hourly["weather_code"],
            hourly["precipitation"],
            strict=True,
        ):
            if None in (temperature, code, rain):
                continue
            result.append(
                {
                    "time": time,
                    "city": city,
                    "temperature": temperature,
                    "code": code,
                    "precipitation": rain,
                    "question": f"{city} {CODES.get(code, code)}",
                    "reference": (
                        f"{temperature} °C, {CODES.get(code, code)}, осадки {rain} мм"
                    ),
                }
            )
        return city, result

    async with httpx.AsyncClient(timeout=60) as client:
        return dict(
            await asyncio.gather(
                *(city_data(client, city, *coords) for city, coords in CITIES.items())
            )
        )


async def import_rows(rows: dict[str, list[dict]]) -> None:
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    insert = sqlite_insert if async_engine.dialect.name == "sqlite" else pg_insert
    glossary = [
        {
            "id": f"wmo-{code}-{scene}-{period}",
            "term": f"{name}, {subject}, {period}",
            "definition": f"Код WMO {code} означает «{name}». Для сцены «{subject}» "
            f"рекомендация: {rule}; период — {period}.",
            "category": "weather",
            "source_url": "https://open-meteo.com/en/docs",
        }
        for code, name in CODES.items()
        for scene, (subject, rule) in enumerate(VISUALS.items())
        for period in SCENES
    ]
    memory = [
        {
            "id": f"wx-{index}-{row['time']}",
            "question": row["question"],
            "content": row["question"],
            "answer": row["reference"],
            "category": "weather",
            "source_url": SOURCE,
        }
        for index, entries in enumerate(rows.values())
        for row in entries
    ]
    async with AsyncSessionLocal() as session:
        for model, batch in [(GlossaryEntry, glossary), (KnowledgeBaseEntry, memory)]:
            added = 0
            for offset in range(0, len(batch), 100):
                stmt = (
                    insert(model)
                    .values(batch[offset : offset + 100])
                    .on_conflict_do_nothing(index_elements=["id"])
                    .returning(model.id)
                )
                added += len((await session.scalars(stmt)).all())
            await session.commit()
            count = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.category == "weather")
            )
            print(f"{model.__tablename__}: added={added}, total={count}")


def export_eval(rows: dict[str, list[dict]]) -> None:
    root = Path("eval_datasets")
    root.mkdir(exist_ok=True)
    manifest = {}
    for index, (city, entries) in enumerate(rows.items()):
        shuffled = list(entries)
        Random(42).shuffle(shuffled)
        manifest[city] = {}
        for size in (10, 20, 50, 100, 200, 500, 1000):
            if len(shuffled) < size:
                raise ValueError(f"{city}: insufficient held-out observations")
            path = root / f"city_{index}_{size}.json"
            path.write_text(json.dumps(shuffled[:size], ensure_ascii=False, indent=2))
            manifest[city][size] = path.name
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["import", "eval"])
    parser.add_argument(
        "--json", type=Path, help="Read exported archive rows from local JSON"
    )
    args = parser.parse_args()
    try:
        dates = (
            ("2024-01-01", "2024-01-31")
            if args.action == "import"
            else ("2024-02-01", "2024-03-31")
        )
        rows = (
            json.loads(args.json.read_text())
            if args.json
            else await observations(*dates)
        )
        if args.action == "import":
            await import_rows(rows)
        else:
            export_eval(rows)
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
