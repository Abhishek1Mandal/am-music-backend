import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

import asyncio

from app.services.music.source_resolver import (
    _build_search_queries,
    _search_youtube,
    _candidate_score,
)


async def main():
    title = "Lashcurry Hai Kya"
    artist = "Lash curry"
    album = "MTV Hustle 4, Episode 18"
    duration_ms = 180857

    queries = _build_search_queries(
        title=title,
        artist=artist,
        album=album,
    )

    print("\nSEARCH QUERIES")
    print("=" * 80)

    for query in queries:
        print(query)

    print("\nYOUTUBE CANDIDATES")
    print("=" * 80)

    seen = set()

    for query in queries:
        try:
            candidates = await _search_youtube(
                query=query,
                limit=5,
            )
        except Exception as exc:
            print(f"\nQuery failed: {query}")
            print(exc)
            continue

        for candidate in candidates:
            url = candidate.get("webpage_url")

            if not url or url in seen:
                continue

            seen.add(url)

            score = _candidate_score(
                expected_title=title,
                expected_artist=artist,
                expected_duration_ms=duration_ms,
                candidate=candidate,
            )

            print("\n----------------------------------------")
            print(f"Score:     {score:.4f}")
            print(f"Title:     {candidate.get('title')}")
            print(f"Uploader:  {candidate.get('uploader')}")
            print(f"Duration:  {candidate.get('duration')}")
            print(f"URL:       {url}")

    print("\nTOTAL UNIQUE CANDIDATES:", len(seen))


if __name__ == "__main__":
    asyncio.run(main())