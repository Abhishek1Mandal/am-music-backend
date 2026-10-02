from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# IMPORTANT:
# Import the model package first so all SQLAlchemy relationships
# are registered before Language is queried/instantiated.
import app.models  # noqa: F401

from app.models.language import Language


DEFAULT_LANGUAGES = [
    ("English", "en"),
    ("Hindi", "hi"),
    ("Telugu", "te"),
    ("Tamil", "ta"),
    ("Malayalam", "ml"),
    ("Kannada", "kn"),
    ("Bengali", "bn"),
    ("Punjabi", "pa"),
    ("Marathi", "mr"),
    ("Gujarati", "gu"),
    ("Bhojpuri", "bho"),
    ("Odia", "or"),
    ("Assamese", "as"),
    ("Urdu", "ur"),
    ("Konkani", "kok"),
    ("Rajasthani", "raj"),
]


async def seed_languages(
    db: AsyncSession,
) -> None:
    for name, code in DEFAULT_LANGUAGES:
        result = await db.execute(
            select(Language).where(
                Language.code == code
            )
        )

        language = result.scalar_one_or_none()

        if language is None:
            db.add(
                Language(
                    name=name,
                    code=code,
                )
            )

    await db.commit()