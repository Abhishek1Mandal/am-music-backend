from app.schemas.album import AlbumResponse
from app.schemas.artist import ArtistResponse

from app.schemas.common import (
    IDResponse,
    MessageResponse,
    TimestampResponse,
)

from app.schemas.download import (
    DownloadCreate,
    DownloadResponse,
)

from app.schemas.metadata import (
    MusicAlbumResult,
    MusicArtistResult,
    MusicSearchResponse,
    MusicTrackResult,
)

from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistResponse,
)

from app.schemas.track import (
    TrackResponse,
    TrackDetailResponse,
    TrackAvailabilityResponse,
)

from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
)