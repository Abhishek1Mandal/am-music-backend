from __future__ import annotations

from typing import Any

import httpx


class DeezerService:
    """
    Deezer public API service.

    Used only for resolving artist images.
    """

    BASE_URL = "https://api.deezer.com"

    TIMEOUT = httpx.Timeout(
        connect=5.0,
        read=10.0,
        write=5.0,
        pool=5.0,
    )

    @staticmethod
    def _normalize_name(
        value: str | None,
    ) -> str:
        if not value:
            return ""

        return (
            " ".join(
                value.strip().lower().split()
            )
        )

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = (
            f"{self.BASE_URL}/"
            f"{endpoint.lstrip('/')}"
        )

        async with httpx.AsyncClient(
            timeout=self.TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                url,
                params=params or {},
            )

            response.raise_for_status()

            return response.json()

    async def search_artists(
        self,
        name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        data = await self._get(
            "/search/artist",
            {
                "q": name,
                "limit": limit,
            },
        )

        return data.get(
            "data",
            [],
        )

    async def get_artist_image(
        self,
        name: str,
    ) -> str | None:
        name = name.strip()

        if not name:
            return None

        try:
            results = await self.search_artists(
                name=name,
                limit=10,
            )
        except Exception:
            # Image lookup is enrichment only.
            # Never fail artist discovery because
            # Deezer is unavailable.
            return None

        normalized_name = (
            self._normalize_name(name)
        )

        # IMPORTANT:
        # Do not blindly use the first Deezer result.
        #
        # That can produce the wrong artist image.
        for artist in results:
            deezer_name = artist.get(
                "name"
            )

            if (
                self._normalize_name(
                    deezer_name
                )
                != normalized_name
            ):
                continue

            image_url = (
                artist.get("picture_xl")
                or artist.get("picture_big")
                or artist.get("picture_medium")
                or artist.get("picture")
            )

            if image_url:
                return image_url

        return None


deezer_service = DeezerService()