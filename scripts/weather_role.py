"""Assign the editor/admin role to a registered user from a trusted terminal."""

import argparse
import asyncio

from sqlalchemy import update

from backend.db.models import User
from backend.db.session import AsyncSessionLocal, async_engine


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("role", choices=["user", "editor", "admin"])
    args = parser.parse_args()
    try:
        async with AsyncSessionLocal() as db:
            updated = await db.scalar(
                update(User)
                .where(User.email == args.email.lower())
                .values(role=args.role)
                .returning(User.id)
            )
            if updated is None:
                raise SystemExit("Сначала зарегистрируйте пользователя")
            await db.commit()
            print(f"Роль обновлена: {args.role}")
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
