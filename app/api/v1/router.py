from fastapi import APIRouter

from app.api.v1 import (
    albums,
    artists,
    artwork,
    auth,
    downloads,
    favorites,
    health,
    history,
    library,
    playlists,
    search,
    maintenance,
    tracks,
    streaming,
    genres, 
    metadata, 
    download_progress,
)

api_router = APIRouter()


api_router.include_router(
    health.router,
)

api_router.include_router(
    auth.router,
)

api_router.include_router(
    artists.router,
)

api_router.include_router(
    albums.router,
)

api_router.include_router(
    tracks.router,
)

api_router.include_router(
    playlists.router,
)

api_router.include_router(
    library.router,
)

api_router.include_router(
    favorites.router,
)

api_router.include_router(
    history.router,
)

api_router.include_router(
    search.router,
)

api_router.include_router(
    downloads.router,
)

api_router.include_router(
    streaming.router,
)

api_router.include_router(
    artwork.router,
)

api_router.include_router(
    maintenance.router,
)

api_router.include_router(
    genres.router,
)

api_router.include_router(
    metadata.router,
)

api_router.include_router(
    download_progress.router,
)