from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import yt_dlp

from app.core.config import settings


class SourceResolverError(Exception):
    """Raised when a suitable YouTube source cannot be found."""


@dataclass(slots=True)
class ResolvedSource:
    url: str
    title: str
    artist: str | None
    duration_seconds: float | None
    video_id: str | None = None
    uploader: str | None = None
    score: float = 0.0


# Words that usually add noise rather than identity to music titles.
_TITLE_NOISE = {
    "official",
    "officially",
    "video",
    "music",
    "audio",
    "lyrics",
    "lyric",
    "visualizer",
    "hd",
    "4k",
    "remastered",
    "full",
    "song",
    "mv",
}


def _normalize_text(value: str | None) -> str:
    """
    Normalize text for fuzzy title/artist matching.

    Examples:
        "Lashcurry Hai Kya" -> "lashcurry hai kya"
        "Lash Curry"       -> "lash curry"
        "Song (Official)"  -> "song"
    """
    if not value:
        return ""

    value = value.lower()

    # Remove bracketed/parenthetical metadata.
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\[[^\]]*\]", " ", value)

    # Normalize separators.
    value = re.sub(r"[_/\\:–—-]+", " ", value)

    # Keep letters/numbers/spaces.
    value = re.sub(r"[^a-z0-9\s]", " ", value)

    # Collapse whitespace.
    value = re.sub(r"\s+", " ", value).strip()

    return value


def _compact_text(value: str | None) -> str:
    """
    Return normalized text without spaces.

    This helps with artist/name variations such as:

        Lash curry
        Lashcurry
        LASH CURRY

    which should be treated as the same artist.
    """
    normalized = _normalize_text(value)

    if not normalized:
        return ""

    return normalized.replace(" ", "")


def _tokens(value: str | None) -> set[str]:
    normalized = _normalize_text(value)

    if not normalized:
        return set()

    return {
        token
        for token in normalized.split()
        if token and token not in _TITLE_NOISE
    }


def _token_similarity(
    expected: str | None,
    candidate: str | None,
) -> float:
    """
    Calculate token-overlap similarity.

    Returns:
        0.0 -> no overlap
        1.0 -> all expected tokens matched
    """
    expected_tokens = _tokens(expected)
    candidate_tokens = _tokens(candidate)

    if not expected_tokens or not candidate_tokens:
        return 0.0

    intersection = expected_tokens & candidate_tokens

    if not intersection:
        return 0.0

    # Recall-like score is useful because YouTube titles often contain
    # additional words such as "Official Video".
    return len(intersection) / len(expected_tokens)


def _jaccard_similarity(
    first: str | None,
    second: str | None,
) -> float:
    first_tokens = _tokens(first)
    second_tokens = _tokens(second)

    if not first_tokens or not second_tokens:
        return 0.0

    intersection = first_tokens & second_tokens
    union = first_tokens | second_tokens

    if not union:
        return 0.0

    return len(intersection) / len(union)


def _duration_score(
    expected_ms: int | None,
    candidate_seconds: float | int | None,
) -> float:
    """
    Score duration similarity.

    Duration is intentionally a low-weight signal.

    MusicBrainz and YouTube durations can differ because of:
    - intros
    - outros
    - TV/MTV edits
    - platform-specific versions
    - uploaded performances
    - additional metadata/audio
    """
    if expected_ms is None or candidate_seconds is None:
        return 0.0

    try:
        expected_seconds = float(expected_ms) / 1000.0
        candidate_seconds = float(candidate_seconds)
    except (TypeError, ValueError):
        return 0.0

    if expected_seconds <= 0 or candidate_seconds <= 0:
        return 0.0

    difference = abs(expected_seconds - candidate_seconds)

    # Exact / near exact.
    if difference <= 5:
        return 1.0

    if difference <= 10:
        return 0.9

    if difference <= 20:
        return 0.75

    if difference <= 40:
        return 0.55

    if difference <= 60:
        return 0.35

    if difference <= 90:
        return 0.15

    return 0.0


def _artist_score(
    expected_artist: str | None,
    candidate_title: str | None,
    candidate_uploader: str | None,
) -> float:
    """
    Calculate artist similarity.

    Artist matching uses:
    1. Artist appearing in the video title.
    2. Artist appearing in uploader/channel name.

    Title artist matches are stronger than uploader matches.

    Also handles formatting differences such as:
        "Lash curry"
        "Lashcurry"
    """
    if not expected_artist:
        return 0.0

    expected_normalized = _normalize_text(expected_artist)
    expected_compact = _compact_text(expected_artist)

    if not expected_normalized or not expected_compact:
        return 0.0

    candidate_title_normalized = _normalize_text(candidate_title)
    candidate_uploader_normalized = _normalize_text(candidate_uploader)

    candidate_title_compact = _compact_text(candidate_title)
    candidate_uploader_compact = _compact_text(candidate_uploader)

    # Strong exact compact match.
    #
    # "Lash curry" -> "lashcurry"
    # "Lashcurry"  -> "lashcurry"
    if expected_compact and expected_compact in candidate_title_compact:
        title_score = 1.0
    else:
        title_score = _token_similarity(
            expected_artist,
            candidate_title,
        )

    if expected_compact and expected_compact in candidate_uploader_compact:
        uploader_score = 1.0
    else:
        uploader_score = _token_similarity(
            expected_artist,
            candidate_uploader,
        )

    # Artist in the title is the strongest artist signal.
    #
    # Uploader/channel is useful but weaker because a label/channel can
    # upload many artists.
    return min(
        (title_score * 0.75) + (uploader_score * 0.25),
        1.0,
    )


def _title_score(
    expected_title: str,
    candidate_title: str | None,
) -> float:
    """
    Calculate title similarity.

    The track title is the strongest identity signal.
    """
    if not candidate_title:
        return 0.0

    normalized_expected = _normalize_text(expected_title)
    normalized_candidate = _normalize_text(candidate_title)

    if not normalized_expected or not normalized_candidate:
        return 0.0

    # Exact normalized title.
    if normalized_expected == normalized_candidate:
        return 1.0

    token_score = _token_similarity(
        expected_title,
        candidate_title,
    )

    jaccard_score = _jaccard_similarity(
        expected_title,
        candidate_title,
    )

    score = max(
        token_score,
        jaccard_score,
    )

    # Expected title appears inside candidate title.
    #
    # Example:
    # "Lashcurry Hai Kya"
    # ->
    # "Lashcurry Hai Kya Lashcurry MTV Hustle 4"
    if normalized_expected in normalized_candidate:
        score = max(score, 0.95)

    # Candidate title appears inside expected title.
    if normalized_candidate in normalized_expected:
        score = max(score, 0.90)

    return min(score, 1.0)


def _candidate_score(
    *,
    expected_title: str,
    expected_artist: str | None,
    expected_duration_ms: int | None,
    candidate: dict[str, Any],
) -> float:
    """
    Calculate the overall YouTube candidate score.

    Weighting:

        Title    = 60%
        Artist   = 30%
        Duration = 10%

    Title and artist identify the recording.

    Duration is supporting evidence only because YouTube uploads
    frequently differ in duration from MusicBrainz recordings.
    """
    candidate_title = candidate.get("title")
    candidate_uploader = candidate.get("uploader")

    title_score = _title_score(
        expected_title,
        candidate_title,
    )

    artist_score = _artist_score(
        expected_artist,
        candidate_title,
        candidate_uploader,
    )

    duration_score = _duration_score(
        expected_duration_ms,
        candidate.get("duration"),
    )

    # ---------------------------------------------------------
    # Main weighting
    # ---------------------------------------------------------
    #
    # Title    = 60%
    # Artist   = 30%
    # Duration = 10%
    #
    # This intentionally gives identity more importance than
    # duration because MusicBrainz and YouTube durations can differ.
    #
    score = (
        (title_score * 0.60)
        + (artist_score * 0.30)
        + (duration_score * 0.10)
    )

    return min(score, 1.0)


def _build_search_queries(
    *,
    title: str,
    artist: str | None,
    album: str | None,
) -> list[str]:
    """
    Build several YouTube search queries.

    We intentionally do not depend on the literal MusicBrainz title
    because titles can contain metadata such as:

        (From "Movie")
        (Official Version)
        (Live)
    """
    normalized_title = _normalize_text(title)

    # Remove common MusicBrainz title suffixes from the search text.
    clean_title = normalized_title

    queries: list[str] = []

    if artist and clean_title:
        queries.append(
            f"{artist} {clean_title}"
        )

    if artist and album and clean_title:
        queries.append(
            f"{artist} {clean_title} {album}"
        )

    if clean_title:
        queries.append(clean_title)

    # Preserve ordering while removing duplicates.
    unique_queries: list[str] = []

    for query in queries:
        query = query.strip()

        if query and query not in unique_queries:
            unique_queries.append(query)

    return unique_queries


def _extract_video_url(
    entry: dict[str, Any],
) -> str | None:
    """
    Extract a stable YouTube webpage URL.

    Prefer webpage_url.

    If yt-dlp only gives an ID, construct the normal YouTube
    watch URL.
    """
    webpage_url = entry.get("webpage_url")

    if webpage_url:
        return str(webpage_url)

    video_id = entry.get("id")

    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    return None


def _search_youtube_sync(
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Execute yt-dlp search synchronously.

    This function is intentionally synchronous because yt-dlp itself
    is synchronous. The public resolver moves it into a worker thread.
    """
    search_prefix = getattr(
        settings,
        "source_search_prefix",
        "ytsearch5",
    )

    search_target = f"{search_prefix}:{query}"

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        result = ydl.extract_info(
            search_target,
            download=False,
        )

    if not result:
        return []

    entries = result.get("entries") or []

    candidates: list[dict[str, Any]] = []

    for entry in entries[:limit]:
        if not entry:
            continue

        url = _extract_video_url(entry)

        if not url:
            continue

        candidate = dict(entry)
        candidate["webpage_url"] = url

        candidates.append(candidate)

    return candidates


async def _search_youtube(
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Run yt-dlp without blocking FastAPI's event loop.
    """
    return await asyncio.to_thread(
        _search_youtube_sync,
        query,
        limit,
    )


async def resolve_source(
    *,
    title: str,
    artist: str | None = None,
    album: str | None = None,
    duration_ms: int | None = None,
    strict_duration: bool = False,
) -> ResolvedSource:
    """
    Automatically find the best matching YouTube source.

    The caller supplies MusicBrainz metadata only.

    No YouTube URL is required from the client.
    """
    if not title or not title.strip():
        raise SourceResolverError(
            "Cannot resolve a source without a track title."
        )

    queries = _build_search_queries(
        title=title,
        artist=artist,
        album=album,
    )

    if not queries:
        raise SourceResolverError(
            "Unable to build a YouTube search query."
        )

    all_candidates: list[dict[str, Any]] = []

    for query in queries:
        try:
            candidates = await _search_youtube(
                query=query,
                limit=5,
            )
        except Exception:
            # Continue to the next query.
            #
            # One failed YouTube search should not immediately fail
            # the entire resolution.
            continue

        all_candidates.extend(candidates)

        # If we already have enough candidates, don't make
        # unnecessary additional searches.
        if len(all_candidates) >= 10:
            break

    if not all_candidates:
        raise SourceResolverError(
            f"No YouTube source found for '{title}'."
        )

    # Remove duplicate videos.
    unique_candidates: dict[str, dict[str, Any]] = {}

    for candidate in all_candidates:
        url = candidate.get("webpage_url")

        if not url:
            continue

        unique_candidates[url] = candidate

    ranked: list[
        tuple[float, dict[str, Any]]
    ] = []

    for candidate in unique_candidates.values():
        candidate_duration = candidate.get("duration")
        if strict_duration and duration_ms:
            # Music discovery metadata can contain very short intros/skits.
            # Never substitute a much longer video for the requested recording.
            try:
                candidate_duration = float(candidate_duration)
            except (TypeError, ValueError):
                continue
            expected_seconds = duration_ms / 1000.0
            tolerance_seconds = max(12.0, expected_seconds * 0.12)
            if abs(candidate_duration - expected_seconds) > tolerance_seconds:
                continue

        score = _candidate_score(
            expected_title=title,
            expected_artist=artist,
            expected_duration_ms=duration_ms,
            candidate=candidate,
        )
        # Online playback requires a strong identity match; no fallback to an
        # arbitrary first search result when the title/artist/duration disagree.
        if strict_duration and score < 0.68:
            continue

        ranked.append(
            (
                score,
                candidate,
            )
        )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    if not ranked:
        raise SourceResolverError(
            f"No usable YouTube source found for '{title}'."
        )

    best_score, best = ranked[0]

    # ---------------------------------------------------------
    # Minimum matching threshold
    # ---------------------------------------------------------
    #
    # Keep this at 0.55.
    #
    # We are NOT lowering the threshold to solve the Lashcurry case.
    # The scoring model now gives more importance to title + artist,
    # which allows genuine matches with different durations through
    # while still rejecting weak title matches.
    #
    if best_score < 0.55:
        raise SourceResolverError(
            f"No sufficiently matching source found for "
            f"'{title}'. Best score: {best_score:.2f}."
        )

    url = best.get("webpage_url")

    if not url:
        raise SourceResolverError(
            f"Resolved YouTube candidate has no URL for '{title}'."
        )

    duration = best.get("duration")

    try:
        duration_value = (
            float(duration)
            if duration is not None
            else None
        )
    except (TypeError, ValueError):
        duration_value = None

    return ResolvedSource(
        url=url,
        title=str(
            best.get("title")
            or title
        ),
        artist=(
            str(best["uploader"])
            if best.get("uploader")
            else artist
        ),
        duration_seconds=duration_value,
        video_id=(
            str(best["id"])
            if best.get("id")
            else None
        ),
        uploader=(
            str(best["uploader"])
            if best.get("uploader")
            else None
        ),
        score=best_score,
    )