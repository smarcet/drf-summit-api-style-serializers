from django.test import TestCase
from rest_framework.test import APIClient
from api.models import Item, MediaUpload, Tag, Owner

class RecursiveExpandShapeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        o1 = Owner.objects.create(name="Alice")
        m1 = MediaUpload.objects.create(url="https://example.com/a.png", owner=o1)
        t1 = Tag.objects.create(name="alpha")
        i1 = Item.objects.create(name="Widget A", quantity=2, media_upload_id=m1.id)
        i1.tags.set([t1])

    def setUp(self):
        self.client = APIClient()

    def test_nested_expand_media_upload_owner(self):
        resp = self.client.get("/api/items/?expand=media_upload,media_upload.owner&relations=media_upload,media_upload.owner")
        self.assertEqual(resp.status_code, 200)
        row = resp.json()[0]
        self.assertIn("media_upload", row)
        self.assertIsInstance(row["media_upload"], dict)
        self.assertIn("owner", row["media_upload"])
        self.assertNotIn("owner_id", row["media_upload"])
        self.assertIsInstance(row["media_upload"]["owner"], dict)
        self.assertIn("id", row["media_upload"]["owner"])
