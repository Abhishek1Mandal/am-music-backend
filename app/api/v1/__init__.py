from fastapi import APIRouter

from app.api.v1 import (
    albums,
    artists,
    artwork,
    auth,
    download_progress,
    downloads,
    favorites,
    genres,
    health,
    history,
    home,
    library,
    maintenance,
    metadata,
    playlists,
    preferences,
    search,
    streaming,
    tracks,
)

api_router = APIRouter()

# Health + auth first.
api_router.include_router(health.router)
api_router.include_router(auth.router)

# Catalog.
api_router.include_router(artists.router)
api_router.include_router(albums.router)
api_router.include_router(tracks.router)
api_router.include_router(genres.router)

# User-specific collections.
api_router.include_router(playlists.router)
api_router.include_router(library.router)
api_router.include_router(favorites.router)
api_router.include_router(history.router)

# Search + downloads.
api_router.include_router(search.router)

# IMPORTANT: register specific download sub-routes BEFORE the catch-all
# downloads router so /downloads/{id}/progress never gets shadowed.
api_router.include_router(download_progress.router)
api_router.include_router(downloads.router)

# Media.
api_router.include_router(streaming.router)
api_router.include_router(artwork.router)
api_router.include_router(metadata.router)

# Maintenance.
api_router.include_router(maintenance.router)

# Onboarding + discovery.
api_router.include_router(preferences.router)
api_router.include_router(home.router)