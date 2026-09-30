from urllib.parse import quote

import httpx

from app.core.config import settings


class CoverArtService:
    def __init__(self) -> None:
        self.base_url = settings.cover_art_base_url.rstrip("/")

    async def get_front_cover(
        self,
        release_mbid: str,
        size: int = 500,
    ) -> str | None:
        """
        Return a Cover Art Archive front-cover URL.

        Supported sizes:
        250, 500, 1200
        """

        if size not in {250, 500, 1200}:
            size = 500

        encoded_mbid = quote(release_mbid, safe="")

        url = (
            f"{self.base_url}/release/"
            f"{encoded_mbid}/front-{size}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                response = await client.head(url)

                if response.status_code == 200:
                    return url

                return None

        except httpx.HTTPError:
            return None

    def get_front_cover_url(
        self,
        release_mbid: str,
        size: int = 500,
    ) -> str:
        if size not in {250, 500, 1200}:
            size = 500

        return (
            f"{self.base_url}/release/"
            f"{release_mbid}/front-{size}"
        )


cover_art_service = CoverArtService()