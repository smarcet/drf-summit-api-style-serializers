from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Item, MediaUpload, Owner, Tag


class CustomExpandTestCase(TestCase):
    """Tests for ItemCustomExpandSerializer using get_expand() and get_child_context()."""

    @classmethod
    def setUpTestData(cls):
        cls.o1 = Owner.objects.create(name="Alice")
        cls.m1 = MediaUpload.objects.create(url="https://example.com/a.png", owner=cls.o1)
        cls.t1 = Tag.objects.create(name="alpha")
        cls.t2 = Tag.objects.create(name="beta")
        cls.i1 = Item.objects.create(name="Widget A", quantity=2, media_upload_id=cls.m1.id)
        cls.i1.tags.set([cls.t1, cls.t2])
        cls.i2 = Item.objects.create(name="Widget B", quantity=5, media_upload_id=None)

    def setUp(self):
        self.client = APIClient()

    def _get_items(self, params=""):
        resp = self.client.get(f"/api/items-custom-expand/{params}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _get_item(self, item_id, params=""):
        rows = self._get_items(params)
        return next(r for r in rows if r["id"] == item_id)

    # ──────────────────────────────────────────────
    # Group 1: media_upload without expansion
    # ──────────────────────────────────────────────

    def test_no_expand_returns_fk_id(self):
        """Without ?expand=media_upload, returns just the FK id."""
        row = self._get_item(self.i1.id, "?relations=media_upload")
        self.assertEqual(row["media_upload"], self.m1.id)

    def test_no_expand_null_media_upload(self):
        """Item with no media_upload_id returns None."""
        row = self._get_item(self.i2.id, "?relations=media_upload")
        self.assertIsNone(row["media_upload"])

    # ──────────────────────────────────────────────
    # Group 2: media_upload with expansion
    # ──────────────────────────────────────────────

    def test_expand_returns_full_object(self):
        """?expand=media_upload returns the full serialized object."""
        row = self._get_item(
            self.i1.id, "?expand=media_upload&relations=media_upload"
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")

    def test_expand_null_media_upload(self):
        """Expanding media_upload on item with no FK returns None."""
        row = self._get_item(
            self.i2.id, "?expand=media_upload&relations=media_upload"
        )
        self.assertIsNone(row["media_upload"])

    # ──────────────────────────────────────────────
    # Group 3: nested expansion via get_child_context
    # ──────────────────────────────────────────────

    def test_nested_expand_media_upload_owner(self):
        """?expand=media_upload,media_upload.owner expands owner inside media_upload."""
        row = self._get_item(
            self.i1.id,
            "?expand=media_upload,media_upload.owner"
            "&relations=media_upload,media_upload.owner",
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertIsInstance(mu["owner"], dict)
        self.assertEqual(mu["owner"]["id"], self.o1.id)
        self.assertEqual(mu["owner"]["name"], "Alice")

    def test_nested_expand_without_owner(self):
        """?expand=media_upload without .owner returns owner as FK id."""
        row = self._get_item(
            self.i1.id, "?expand=media_upload&relations=media_upload"
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        # owner not expanded → should be owner_id only, owner key absent
        self.assertEqual(mu["owner_id"], self.o1.id)
        self.assertNotIn("owner", mu)

    # ──────────────────────────────────────────────
    # Group 4: nested fields scoping via get_child_context
    # ──────────────────────────────────────────────

    def test_nested_fields_on_expanded_media_upload(self):
        """?fields=media_upload.id,media_upload.url scopes child fields."""
        row = self._get_item(
            self.i1.id,
            "?expand=media_upload&relations=media_upload"
            "&fields=id,media_upload.id,media_upload.url",
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")
        self.assertNotIn("owner_id", mu)
        self.assertNotIn("created", mu)
