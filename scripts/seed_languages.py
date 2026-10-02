import asyncio

from app.core.database import AsyncSessionLocal
from app.services.preferences.languages import seed_languages


async def main():
    async with AsyncSessionLocal() as db:
        await seed_languages(db)


if __name__ == "__main__":
    asyncio.run(main())