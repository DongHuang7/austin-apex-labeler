import unittest
from unittest.mock import Mock, patch

from photo_cache import _cache_one


class PhotoCacheRetryTest(unittest.TestCase):
    @patch("photo_cache.time.sleep")
    @patch("photo_cache.UploadedPhoto")
    @patch("photo_cache.requests.get")
    def test_retries_rate_limited_mls_media(self, get, uploaded_photo, sleep):
        uploaded_photo.query.filter_by.return_value.first.return_value = None
        limited = Mock(status_code=429)
        first = Mock()
        first.raise_for_status.side_effect = __import__("requests").HTTPError(response=limited)
        success = Mock(content=b"image", headers={"Content-Type": "image/jpeg"})
        success.raise_for_status.return_value = None
        get.side_effect = [first, success]

        with patch("photo_cache.db"), patch("photo_cache._serving_url", return_value="/social/photo/token"):
            self.assertIsNotNone(_cache_one("https://media.example/cover.jpg", retries=1))
        sleep.assert_called_once_with(1.25)
        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
