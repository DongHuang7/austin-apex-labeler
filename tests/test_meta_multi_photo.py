import json
import unittest
from unittest.mock import MagicMock, patch

from social import meta_client


class MetaMultiPhotoTest(unittest.TestCase):
    @staticmethod
    def response(identifier):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": identifier}
        return response

    @patch("social.meta_client.requests.post")
    def test_facebook_uploads_unpublished_photos_then_attaches_them(self, post):
        post.side_effect = [self.response("p1"), self.response("p2"), self.response("feed1")]
        result = meta_client.publish_to_facebook_page(
            "page", "token", "caption", image_urls=["https://x/1.jpg", "https://x/2.jpg"]
        )
        self.assertEqual(result, "feed1")
        self.assertEqual(post.call_args_list[0].kwargs["data"]["published"], "false")
        attached = json.loads(post.call_args_list[-1].kwargs["data"]["attached_media"])
        self.assertEqual(attached, [{"media_fbid": "p1"}, {"media_fbid": "p2"}])

    @patch("social.meta_client.requests.post")
    def test_instagram_builds_and_publishes_carousel(self, post):
        post.side_effect = [self.response("c1"), self.response("c2"),
                            self.response("carousel"), self.response("published")]
        result = meta_client.publish_to_instagram(
            "ig", "token", "caption", image_urls=["https://x/1.jpg", "https://x/2.jpg"]
        )
        self.assertEqual(result, "published")
        self.assertEqual(post.call_args_list[0].kwargs["data"]["is_carousel_item"], "true")
        container = post.call_args_list[2].kwargs["data"]
        self.assertEqual(container["media_type"], "CAROUSEL")
        self.assertEqual(container["children"], "c1,c2")
        self.assertEqual(post.call_args_list[3].kwargs["data"]["creation_id"], "carousel")


if __name__ == "__main__":
    unittest.main()
