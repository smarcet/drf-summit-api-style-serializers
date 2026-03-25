from django.test import TestCase

from api.serializers import ItemSerializer, MediaUploadSerializer


class GetExpandTestCase(TestCase):
    """Comprehensive tests for get_expand() and get_child_context() methods."""

    # ──────────────────────────────────────────────
    # Test Group 1: get_expand() - root level
    # ──────────────────────────────────────────────

    def test_get_expand_no_expand_param(self):
        """No ?expand= → empty list."""
        context = {"expand_tree": {}, "fields_tree": None, "relations_tree": None}
        serializer = ItemSerializer(context=context)
        result = serializer.get_expand()
        self.assertEqual(result, [])

    def test_get_expand_single_relation(self):
        """?expand=media_upload → ["media_upload"]."""
        context = {
            "expand_tree": {"media_upload": {}},
            "fields_tree": None,
            "relations_tree": None,
        }
        serializer = ItemSerializer(context=context)
        result = serializer.get_expand()
        self.assertEqual(result, ["media_upload"])

    def test_get_expand_multiple_relations(self):
        """?expand=media_upload,tags → contains both."""
        context = {
            "expand_tree": {"media_upload": {}, "tags": {}},
            "fields_tree": None,
            "relations_tree": None,
        }
        serializer = ItemSerializer(context=context)
        result = serializer.get_expand()
        self.assertCountEqual(result, ["media_upload", "tags"])

    def test_get_expand_with_none_sentinel(self):
        """?expand=none → ["none"] (truthy but matches no real field)."""
        context = {
            "expand_tree": {"none": {}},
            "fields_tree": None,
            "relations_tree": None,
        }
        serializer = ItemSerializer(context=context)
        result = serializer.get_expand()
        self.assertEqual(result, ["none"])

    # ──────────────────────────────────────────────
    # Test Group 2: get_child_context() - tree scoping
    # ──────────────────────────────────────────────

    def test_get_child_context_scopes_expand_tree(self):
        """?expand=media_upload,media_upload.owner → child expand_tree is {"owner": {}}."""
        context = {
            "expand_tree": {"media_upload": {"owner": {}}},
            "fields_tree": None,
            "relations_tree": None,
        }
        serializer = ItemSerializer(context=context)
        child_context = serializer.get_child_context("media_upload")

        self.assertIn("expand_tree", child_context)
        self.assertEqual(child_context["expand_tree"], {"owner": {}})

    def test_get_child_context_scopes_fields_tree(self):
        """?fields=media_upload.id,media_upload.url → child fields_tree is {"id": {}, "url": {}}."""
        context = {
            "expand_tree": {},
            "fields_tree": {"media_upload": {"id": {}, "url": {}}},
            "relations_tree": None,
        }
        serializer = ItemSerializer(context=context)
        child_context = serializer.get_child_context("media_upload")

        self.assertIn("fields_tree", child_context)
        self.assertEqual(child_context["fields_tree"], {"id": {}, "url": {}})

    def test_get_child_context_scopes_relations_tree(self):
        """?relations=media_upload.owner → child relations_tree is {"owner": {}}."""
        context = {
            "expand_tree": {},
            "fields_tree": None,
            "relations_tree": {"media_upload": {"owner": {}}},
        }
        serializer = ItemSerializer(context=context)
        child_context = serializer.get_child_context("media_upload")

        self.assertIn("relations_tree", child_context)
        self.assertEqual(child_context["relations_tree"], {"owner": {}})

    def test_get_expand_on_child_serializer_with_child_context(self):
        """Child serializer instantiated with get_child_context → get_expand() returns child-level keys."""
        # Parent context: ?expand=media_upload,media_upload.owner
        parent_context = {
            "expand_tree": {"media_upload": {"owner": {}}},
            "fields_tree": None,
            "relations_tree": None,
        }
        parent_serializer = ItemSerializer(context=parent_context)

        # Get scoped context for child
        child_context = parent_serializer.get_child_context("media_upload")

        # Instantiate child serializer with scoped context
        child_serializer = MediaUploadSerializer(context=child_context)

        # Child's get_expand() should return ["owner"], not ["media_upload"]
        result = child_serializer.get_expand()
        self.assertEqual(result, ["owner"])
