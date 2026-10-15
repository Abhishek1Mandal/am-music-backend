from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.download import Download
from app.models.track import Track

logger = logging.getLogger(__name__)


AUDIO_EXTENSIONS = {".mp3"}
ACTIVE_DOWNLOAD_STATUSES = {"pending", "resolving", "downloading", "processing"}
TERMINAL_DOWNLOAD_STATUSES = {"completed", "failed", "cancelled"}
DEFAULT_ORPHAN_GRACE_HOURS = 24
DEFAULT_STALE_DOWNLOAD_HOURS = 6


@dataclass
class MaintenanceFile:
    path: str
    size_bytes: int
    age_hours: float


@dataclass
class MaintenanceReport:
    dry_run: bool
    library_root: str
    started_at: str
    finished_at: str | None = None

    scanned_files: int = 0
    scanned_bytes: int = 0

    referenced_files: int = 0
    orphan_files: int = 0
    orphan_bytes: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0

    missing_tracks: int = 0
    repaired_tracks: int = 0

    stale_downloads: int = 0
    repaired_downloads: int = 0

    empty_directories: int = 0
    removed_directories: int = 0

    skipped_files: int = 0
    errors: list[str] = field(default_factory=list)

    orphan_candidates: list[MaintenanceFile] = field(default_factory=list)
    stale_download_ids: list[str] = field(default_factory=list)
    missing_track_ids: list[str] = field(default_factory=list)


class MaintenanceService:
    """Safe music-library reconciliation and cleanup service."""

    def __init__(self, library_root: str | Path | None = None) -> None:
        configured_root = library_root or settings.music_library_path
        self.library_root = Path(configured_root).expanduser().resolve()

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    def ensure_library_root(self) -> None:
        self.library_root.mkdir(parents=True, exist_ok=True)

    def is_inside_library(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.library_root)
            return True
        except ValueError:
            return False

    def resolve_safe_path(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None

        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError):
            return None

        if not self.is_inside_library(path):
            return None

        return path

    def iter_audio_files(self) -> Iterable[Path]:
        if not self.library_root.exists():
            return []

        def generator() -> Iterable[Path]:
            for path in self.library_root.rglob("*"):
                try:
                    if not path.is_file():
                        continue
                    if path.suffix.lower() not in AUDIO_EXTENSIONS:
                        continue
                    if not self.is_inside_library(path):
                        continue
                    yield path
                except OSError:
                    continue

        return generator()

    @staticmethod
    def file_age_hours(path: Path, now: datetime) -> float:
        try:
            modified = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            )
            return max(0.0, (now - modified).total_seconds() / 3600)
        except OSError:
            return 0.0

    # ------------------------------------------------------------------
    # Database reference collection
    # ------------------------------------------------------------------

    async def get_referenced_file_paths(self, db: AsyncSession) -> set[Path]:
        references: set[Path] = set()

        track_result = await db.execute(
            select(Track.file_path).where(Track.file_path.is_not(None))
        )
        for raw_path in track_result.scalars().all():
            path = self.resolve_safe_path(raw_path)
            if path is not None:
                references.add(path)

        download_result = await db.execute(
            select(Download.file_path).where(Download.file_path.is_not(None))
        )
        for raw_path in download_result.scalars().all():
            path = self.resolve_safe_path(raw_path)
            if path is not None:
                references.add(path)

        return references

    # ------------------------------------------------------------------
    # Missing track reconciliation
    # ------------------------------------------------------------------

    async def reconcile_missing_tracks(
        self,
        db: AsyncSession,
        report: MaintenanceReport,
        *,
        apply_changes: bool,
    ) -> None:
        result = await db.execute(
            select(Track).where(
                Track.file_path.is_not(None),
                Track.is_available.is_(True),
            )
        )
        tracks = result.scalars().all()

        for track in tracks:
            path = self.resolve_safe_path(track.file_path)
            available = path is not None and path.is_file()

            if available:
                continue

            report.missing_tracks += 1
            report.missing_track_ids.append(str(track.id))

            if apply_changes:
                track.is_available = False
                report.repaired_tracks += 1

        if apply_changes and report.repaired_tracks:
            await db.flush()

    # ------------------------------------------------------------------
    # Stale download reconciliation
    # ------------------------------------------------------------------

    async def reconcile_stale_downloads(
        self,
        db: AsyncSession,
        report: MaintenanceReport,
        *,
        stale_hours: int,
        apply_changes: bool,
    ) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)

        result = await db.execute(
            select(Download).where(
                Download.status.in_(ACTIVE_DOWNLOAD_STATUSES),
                Download.created_at < cutoff,
            )
        )
        downloads = result.scalars().all()

        for download in downloads:
            report.stale_downloads += 1
            report.stale_download_ids.append(str(download.id))

            if apply_changes:
                download.status = "failed"
                download.error_message = (
                    f"Download automatically marked failed by maintenance "
                    f"after exceeding {stale_hours} hours."
                )
                download.completed_at = None
                report.repaired_downloads += 1

        if apply_changes and report.repaired_downloads:
            await db.flush()

    # ------------------------------------------------------------------
    # Orphan scan / cleanup
    # ------------------------------------------------------------------

    async def scan_orphans(
        self,
        db: AsyncSession,
        report: MaintenanceReport,
        *,
        orphan_grace_hours: int,
    ) -> list[Path]:
        references = await self.get_referenced_file_paths(db)
        report.referenced_files = len(references)

        now = datetime.now(timezone.utc)
        candidates: list[Path] = []

        for path in self.iter_audio_files():
            report.scanned_files += 1

            try:
                stat = path.stat()
                report.scanned_bytes += stat.st_size
            except OSError as exc:
                report.skipped_files += 1
                report.errors.append(f"Could not stat {path}: {exc}")
                continue

            if path in references:
                continue

            age_hours = self.file_age_hours(path, now)
            if age_hours < orphan_grace_hours:
                report.skipped_files += 1
                continue

            size = stat.st_size
            report.orphan_files += 1
            report.orphan_bytes += size
            report.orphan_candidates.append(
                MaintenanceFile(
                    path=str(path),
                    size_bytes=size,
                    age_hours=round(age_hours, 2),
                )
            )
            candidates.append(path)

        return candidates

    async def delete_orphans(
        self,
        candidates: list[Path],
        report: MaintenanceReport,
    ) -> None:
        for path in candidates:
            try:
                # Re-check safety immediately before deletion.
                if not self.is_inside_library(path):
                    report.skipped_files += 1
                    continue

                if not path.exists() or not path.is_file():
                    continue

                size = path.stat().st_size
                path.unlink()
                report.deleted_files += 1
                report.deleted_bytes += size

                logger.info("[MAINTENANCE] Deleted orphan file: %s", path)
            except OSError as exc:
                report.errors.append(f"Could not delete {path}: {exc}")
                logger.exception("[MAINTENANCE] Failed to delete %s", path)

    # ------------------------------------------------------------------
    # Empty directory cleanup
    # ------------------------------------------------------------------

    async def cleanup_empty_directories(
        self,
        report: MaintenanceReport,
        *,
        apply_changes: bool,
    ) -> None:
        if not self.library_root.exists():
            return

        directories: list[Path] = []
        for path in self.library_root.rglob("*"):
            try:
                if path.is_dir() and self.is_inside_library(path):
                    directories.append(path)
            except OSError:
                continue

        # Deepest directories first.
        directories.sort(key=lambda value: len(value.parts), reverse=True)

        for directory in directories:
            try:
                if any(directory.iterdir()):
                    continue

                report.empty_directories += 1

                if apply_changes:
                    directory.rmdir()
                    report.removed_directories += 1
                    logger.info(
                        "[MAINTENANCE] Removed empty directory: %s",
                        directory,
                    )
            except OSError as exc:
                report.errors.append(
                    f"Could not inspect/remove directory {directory}: {exc}"
                )

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def health(self, db: AsyncSession) -> dict:
        self.ensure_library_root()

        total_tracks = await db.scalar(select(func.count(Track.id))) or 0
        total_downloads = await db.scalar(select(func.count(Download.id))) or 0

        track_result = await db.execute(select(Track))
        tracks = track_result.scalars().all()

        download_result = await db.execute(select(Download))
        downloads = download_result.scalars().all()

        audio_files = list(self.iter_audio_files())
        total_bytes = 0
        for path in audio_files:
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass

        missing = 0
        for track in tracks:
            path = self.resolve_safe_path(track.file_path)
            if path is None or not path.is_file():
                if track.file_path:
                    missing += 1

        active = sum(
            1 for download in downloads
            if download.status in ACTIVE_DOWNLOAD_STATUSES
        )

        return {
            "status": "healthy",
            "library_root": str(self.library_root),
            "library_exists": self.library_root.exists(),
            "track_count": int(total_tracks),
            "download_count": int(total_downloads),
            "active_downloads": active,
            "missing_track_files": missing,
            "audio_file_count": len(audio_files),
            "audio_bytes": total_bytes,
        }

    async def cleanup(
        self,
        db: AsyncSession,
        *,
        dry_run: bool = True,
        orphan_grace_hours: int = DEFAULT_ORPHAN_GRACE_HOURS,
        stale_download_hours: int = DEFAULT_STALE_DOWNLOAD_HOURS,
        cleanup_stale_downloads: bool = True,
        cleanup_missing_tracks: bool = True,
        cleanup_orphans: bool = True,
        cleanup_empty_dirs: bool = True,
    ) -> MaintenanceReport:
        if orphan_grace_hours < 1:
            raise ValueError("orphan_grace_hours must be at least 1")
        if stale_download_hours < 1:
            raise ValueError("stale_download_hours must be at least 1")

        started = datetime.now(timezone.utc)
        self.ensure_library_root()

        report = MaintenanceReport(
            dry_run=dry_run,
            library_root=str(self.library_root),
            started_at=started.isoformat(),
        )

        apply_changes = not dry_run

        try:
            if cleanup_missing_tracks:
                await self.reconcile_missing_tracks(
                    db,
                    report,
                    apply_changes=apply_changes,
                )

            if cleanup_stale_downloads:
                await self.reconcile_stale_downloads(
                    db,
                    report,
                    stale_hours=stale_download_hours,
                    apply_changes=apply_changes,
                )

            candidates: list[Path] = []
            if cleanup_orphans:
                candidates = await self.scan_orphans(
                    db,
                    report,
                    orphan_grace_hours=orphan_grace_hours,
                )

                if apply_changes:
                    await self.delete_orphans(candidates, report)

            if cleanup_empty_dirs:
                await self.cleanup_empty_directories(
                    report,
                    apply_changes=apply_changes,
                )

            if apply_changes:
                await db.commit()
            else:
                await db.rollback()

        except Exception:
            await db.rollback()
            raise
        finally:
            report.finished_at = datetime.now(timezone.utc).isoformat()

        return report
