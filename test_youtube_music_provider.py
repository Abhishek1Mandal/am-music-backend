"""Small dependency-free tests for YouTube Music result normalization."""
import unittest

from app.services.providers.youtube_music import _duration_ms, _normalize


class YouTubeMusicNormalizationTests(unittest.TestCase):
    def test_duration_from_colon_format(self):
        self.assertEqual(_duration_ms("3:42"), 222_000)

    def test_duration_from_seconds(self):
        self.assertEqual(_duration_ms(182), 182_000)

    def test_song_normalization(self):
        item = {
            "videoId": "abcdefghijk",
            "title": "Example Song",
            "artists": [{"name": "Example Artist", "id": "UCartist"}],
            "album": {"name": "Example Album", "id": "MPREb"},
            "duration_seconds": 201,
            "thumbnails": [{"url": "https://example.com/art.jpg"}],
            "isExplicit": True,
        }
        result = _normalize(item, "songs")
        self.assertIsNotNone(result)
        self.assertEqual(result["video_id"], "abcdefghijk")
        self.assertEqual(result["artist_name"], "Example Artist")
        self.assertEqual(result["duration_ms"], 201_000)
        self.assertTrue(result["is_explicit"])

    def test_missing_title_is_discarded(self):
        self.assertIsNone(_normalize({"videoId": "abcdefghijk"}, "songs"))


if __name__ == "__main__":
    unittest.main()
