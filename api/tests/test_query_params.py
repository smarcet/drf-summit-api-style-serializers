from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Item, MediaUpload, Owner, Tag


class QueryParamTestCase(TestCase):
    """Exhaustive tests for ?fields=, ?expand=, and ?relations= query parameter combinations."""

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
        resp = self.client.get(f"/api/items/{params}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _get_item(self, item_id, params=""):
        """Get a specific item from the list response by id."""
        rows = self._get_items(params)
        return next(r for r in rows if r["id"] == item_id)

    # ──────────────────────────────────────────────
    # Group 1: Default behavior (no params)
    # ──────────────────────────────────────────────

    def test_default_no_params(self):
        """No query params: all allowed_fields present, relations as IDs, no expansion."""
        row = self._get_item(self.i1.id)
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["name"], "Widget A")
        self.assertEqual(row["quantity"], 2)
        self.assertEqual(row["media_upload_id"], self.m1.id)
        self.assertEqual(row["display_name"], "Widget A (x2)")
        self.assertIn("created", row)
        self.assertIn("modified", row)
        # tags as list of IDs (not expanded)
        self.assertCountEqual(row["tags"], [self.t1.id, self.t2.id])
        # media_upload is NOT present (One2Many not expanded → replaced by _id)
        self.assertNotIn("media_upload", row)

    # ──────────────────────────────────────────────
    # Group 2: ?fields= only
    # ──────────────────────────────────────────────

    def test_fields_subset(self):
        """?fields=id,name → id, name returned; quantity, timestamps, media_upload_id absent.

        Note: tags still appears as IDs because relations_tree defaults to all
        allowed_relations, and _filter_local_fields keeps relation keys.
        """
        row = self._get_item(self.i1.id, "?fields=id,name")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["name"], "Widget A")
        # tags leaks through via default relations_tree
        self.assertIn("tags", row)
        # these are excluded by fields filter
        self.assertNotIn("quantity", row)
        self.assertNotIn("media_upload_id", row)
        self.assertNotIn("media_upload", row)
        self.assertNotIn("created", row)
        self.assertNotIn("modified", row)

    def test_fields_includes_fk_id(self):
        """?fields=id,media_upload_id → raw FK field is present."""
        row = self._get_item(self.i1.id, "?fields=id,media_upload_id")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["media_upload_id"], self.m1.id)
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("media_upload", row)

    def test_fields_excludes_unlisted(self):
        """?fields=id → only id (plus tags from default relations_tree); quantity, timestamps absent."""
        row = self._get_item(self.i1.id, "?fields=id")
        self.assertEqual(row["id"], self.i1.id)
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("media_upload_id", row)
        self.assertNotIn("media_upload", row)
        self.assertNotIn("created", row)
        self.assertNotIn("modified", row)

    def test_fields_relation_without_expand(self):
        """?fields=id,media_upload → media_upload removed (not expanded), media_upload_id absent."""
        row = self._get_item(self.i1.id, "?fields=id,media_upload")
        self.assertEqual(row["id"], self.i1.id)
        # One2Many not expanded: relation field removed, _id not in fields_tree → absent
        self.assertNotIn("media_upload", row)
        self.assertNotIn("media_upload_id", row)

    def test_fields_m2m_without_expand(self):
        """?fields=id,tags → tags shown as ID list (not expanded)."""
        row = self._get_item(self.i1.id, "?fields=id,tags")
        self.assertEqual(row["id"], self.i1.id)
        self.assertCountEqual(row["tags"], [self.t1.id, self.t2.id])
        self.assertNotIn("media_upload", row)
        self.assertNotIn("media_upload_id", row)

    # ──────────────────────────────────────────────
    # Group 3: ?expand= only
    # ──────────────────────────────────────────────

    def test_expand_one2many(self):
        """?expand=media_upload → media_upload as object, media_upload_id removed."""
        row = self._get_item(self.i1.id, "?expand=media_upload")
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")
        self.assertEqual(mu["owner_id"], self.o1.id)
        self.assertIn("created", mu)
        self.assertIn("modified", mu)
        # owner not expanded
        self.assertNotIn("owner", mu)
        # media_upload_id removed when expanded
        self.assertNotIn("media_upload_id", row)
        # other item fields present
        self.assertEqual(row["name"], "Widget A")
        self.assertCountEqual(row["tags"], [self.t1.id, self.t2.id])

    def test_expand_m2m(self):
        """?expand=tags → tags as list of objects."""
        row = self._get_item(self.i1.id, "?expand=tags")
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        tag_names = {t["name"] for t in row["tags"]}
        self.assertEqual(tag_names, {"alpha", "beta"})
        for t in row["tags"]:
            self.assertIn("id", t)
            self.assertIn("name", t)
        # media_upload not expanded → media_upload_id present
        self.assertNotIn("media_upload", row)
        self.assertIn("media_upload_id", row)

    def test_expand_both_relations(self):
        """?expand=media_upload,tags → both expanded."""
        row = self._get_item(self.i1.id, "?expand=media_upload,tags")
        self.assertIsInstance(row["media_upload"], dict)
        self.assertEqual(row["media_upload"]["id"], self.m1.id)
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        # media_upload_id removed when expanded
        self.assertNotIn("media_upload_id", row)

    def test_expand_nested(self):
        """?expand=media_upload,media_upload.owner → owner nested inside media_upload.

        No ?relations= needed — defaults fill in at each serializer level.
        """
        row = self._get_item(self.i1.id, "?expand=media_upload,media_upload.owner")
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertIn("owner", mu)
        self.assertIsInstance(mu["owner"], dict)
        self.assertEqual(mu["owner"]["id"], self.o1.id)
        self.assertEqual(mu["owner"]["name"], "Alice")
        # owner_id removed when owner is expanded
        self.assertNotIn("owner_id", mu)
        self.assertNotIn("media_upload_id", row)

    def test_expand_null_relation(self):
        """?expand=media_upload on item with null media_upload_id → media_upload is null."""
        row = self._get_item(self.i2.id, "?expand=media_upload")
        self.assertIsNone(row["media_upload"])
        self.assertNotIn("media_upload_id", row)

    # ──────────────────────────────────────────────
    # Group 4: ?relations= only
    # ──────────────────────────────────────────────

    def test_relations_only_no_expand(self):
        """?relations=media_upload → tags removed (not in relations), media_upload as ID."""
        row = self._get_item(self.i1.id, "?relations=media_upload")
        self.assertEqual(row["media_upload_id"], self.m1.id)
        self.assertNotIn("media_upload", row)
        # tags removed — not in relations_tree
        self.assertNotIn("tags", row)

    def test_relations_restricts_m2m(self):
        """?relations=media_upload → tags removed (blocked), other fields present."""
        row = self._get_item(self.i1.id, "?relations=media_upload")
        self.assertIn("id", row)
        self.assertIn("name", row)
        self.assertIn("quantity", row)
        self.assertIn("media_upload_id", row)
        # tags removed — not in relations_tree
        self.assertNotIn("tags", row)
        self.assertIn("created", row)
        self.assertIn("modified", row)

    def test_relations_none(self):
        """?relations=none → removes all relation fields entirely.

        ``none`` is a sentinel: {"none": {}} is truthy (so _ensure_defaults
        doesn't fill in allowed_relations) and "none" matches no real relation
        name, so blocked relations are fully stripped from the response.
        """
        row = self._get_item(self.i1.id, "?relations=none")
        # All relation fields removed entirely
        self.assertNotIn("media_upload", row)
        self.assertNotIn("media_upload_id", row)
        self.assertNotIn("tags", row)
        # Non-relation fields still present
        self.assertIn("name", row)
        self.assertIn("id", row)
        self.assertIn("quantity", row)

    # ──────────────────────────────────────────────
    # Group 5: ?expand= + ?relations=
    # ──────────────────────────────────────────────

    def test_expand_with_matching_relations(self):
        """?expand=media_upload&relations=media_upload → expands media_upload, tags removed."""
        row = self._get_item(self.i1.id, "?expand=media_upload&relations=media_upload")
        self.assertIsInstance(row["media_upload"], dict)
        self.assertEqual(row["media_upload"]["id"], self.m1.id)
        self.assertNotIn("media_upload_id", row)
        # tags removed — not in relations_tree
        self.assertNotIn("tags", row)

    def test_expand_blocked_by_missing_relation(self):
        """?expand=media_upload&relations=tags → media_upload removed (not in relations)."""
        row = self._get_item(self.i1.id, "?expand=media_upload&relations=tags")
        # media_upload blocked and removed entirely (both field and FK)
        self.assertNotIn("media_upload", row)
        self.assertNotIn("media_upload_id", row)
        # tags in relations but not in expand → IDs
        self.assertCountEqual(row["tags"], [self.t1.id, self.t2.id])

    def test_expand_m2m_blocked_by_relations(self):
        """?expand=tags&relations=media_upload → tags removed (not in relations)."""
        row = self._get_item(self.i1.id, "?expand=tags&relations=media_upload")
        # tags blocked and removed entirely
        self.assertNotIn("tags", row)
        # media_upload not in expand_tree → not expanded, but in relations → shows as _id
        self.assertNotIn("media_upload", row)
        self.assertIn("media_upload_id", row)

    def test_expand_partial_relations(self):
        """?expand=media_upload,tags&relations=media_upload → media_upload expanded, tags removed."""
        row = self._get_item(self.i1.id, "?expand=media_upload,tags&relations=media_upload")
        self.assertIsInstance(row["media_upload"], dict)
        self.assertEqual(row["media_upload"]["id"], self.m1.id)
        self.assertNotIn("media_upload_id", row)
        # tags blocked and removed entirely — not in relations_tree
        self.assertNotIn("tags", row)

    def test_nested_expand_with_relations(self):
        """?expand=media_upload,media_upload.owner&relations=media_upload,media_upload.owner → full nested."""
        row = self._get_item(
            self.i1.id,
            "?expand=media_upload,media_upload.owner&relations=media_upload,media_upload.owner",
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertIn("owner", mu)
        self.assertIsInstance(mu["owner"], dict)
        self.assertEqual(mu["owner"]["id"], self.o1.id)
        self.assertEqual(mu["owner"]["name"], "Alice")
        self.assertNotIn("owner_id", mu)
        self.assertNotIn("media_upload_id", row)

    # ──────────────────────────────────────────────
    # Group 6: ?fields= + ?expand=
    # ──────────────────────────────────────────────

    def test_fields_and_expand_subset(self):
        """?fields=id,name&expand=media_upload → media_upload expanded and included
        even though not listed in fields (expand_tree adds it to keep set).
        """
        row = self._get_item(self.i1.id, "?fields=id,name&expand=media_upload")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["name"], "Widget A")
        self.assertIsInstance(row["media_upload"], dict)
        self.assertEqual(row["media_upload"]["id"], self.m1.id)
        # media_upload_id removed by expansion
        self.assertNotIn("media_upload_id", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("created", row)
        self.assertNotIn("modified", row)

    def test_fields_nested_notation(self):
        """?fields=id,media_upload.id,media_upload.url&expand=media_upload
        → media_upload with only id and url (dot notation creates nested fields_tree).
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,media_upload.url&expand=media_upload",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")
        # these fields are filtered out by nested fields_tree
        self.assertNotIn("owner_id", mu)
        self.assertNotIn("created", mu)
        self.assertNotIn("modified", mu)
        self.assertNotIn("owner", mu)

    def test_fields_nested_m2m(self):
        """?fields=id,tags.id&expand=tags → tags as objects with only id."""
        row = self._get_item(self.i1.id, "?fields=id,tags.id&expand=tags")
        self.assertEqual(row["id"], self.i1.id)
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        for t in row["tags"]:
            self.assertIn("id", t)
            self.assertNotIn("name", t)

    def test_fields_nested_deep(self):
        """?fields=id,media_upload.id,media_upload.owner.id&expand=media_upload,media_upload.owner
        → 3-level nesting with field filtering at each level.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,media_upload.owner.id"
            "&expand=media_upload,media_upload.owner",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        # url filtered out
        self.assertNotIn("url", mu)
        # owner expanded and filtered to id only
        self.assertIsInstance(mu["owner"], dict)
        self.assertEqual(mu["owner"]["id"], self.o1.id)
        self.assertNotIn("name", mu["owner"])

    def test_expand_without_field_listed(self):
        """?fields=id,name&expand=tags → tags expanded and included (expand implies inclusion)."""
        row = self._get_item(self.i1.id, "?fields=id,name&expand=tags")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["name"], "Widget A")
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        # tags expanded with all TagSerializer allowed_fields (no nested fields restriction)
        for t in row["tags"]:
            self.assertIn("id", t)
            self.assertIn("name", t)
        self.assertNotIn("quantity", row)

    # ──────────────────────────────────────────────
    # Group 7: All three params combined
    # ──────────────────────────────────────────────

    def test_all_params_full(self):
        """?fields=id,media_upload.id,media_upload.url&expand=media_upload&relations=media_upload
        → filtered nested expansion, only id and media_upload in response.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,media_upload.url"
            "&expand=media_upload&relations=media_upload",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")
        self.assertNotIn("owner_id", mu)
        # tags not in relations → not in keep set → absent from response
        self.assertNotIn("tags", row)
        self.assertNotIn("name", row)

    def test_all_params_nested(self):
        """?fields=id,media_upload.id,media_upload.owner.name
        &expand=media_upload,media_upload.owner
        &relations=media_upload,media_upload.owner
        → deep filtered nested expansion.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,media_upload.owner.name"
            "&expand=media_upload,media_upload.owner"
            "&relations=media_upload,media_upload.owner",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertNotIn("url", mu)
        owner = mu["owner"]
        self.assertIsInstance(owner, dict)
        self.assertEqual(owner["name"], "Alice")
        # owner filtered to name only — id not in nested fields
        self.assertNotIn("id", owner)
        self.assertNotIn("tags", row)

    def test_all_params_relations_blocks(self):
        """?fields=id,media_upload&expand=media_upload&relations=tags
        → media_upload removed entirely (not in relations), tags kept.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload&expand=media_upload&relations=tags",
        )
        self.assertEqual(row["id"], self.i1.id)
        # media_upload blocked and removed entirely (not in relations_tree)
        self.assertNotIn("media_upload", row)
        self.assertNotIn("media_upload_id", row)
        # tags in relations_tree → kept as IDs
        self.assertIn("tags", row)

    def test_all_params_multiple_expands(self):
        """?fields=id,media_upload.id,tags.name&expand=media_upload,tags&relations=media_upload,tags
        → both expanded with nested field filtering.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,tags.name"
            "&expand=media_upload,tags&relations=media_upload,tags",
        )
        self.assertEqual(row["id"], self.i1.id)
        # media_upload expanded, filtered to id only
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertNotIn("url", mu)
        self.assertNotIn("owner_id", mu)
        # tags expanded, filtered to name only
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        tag_names = {t["name"] for t in row["tags"]}
        self.assertEqual(tag_names, {"alpha", "beta"})
        for t in row["tags"]:
            self.assertNotIn("id", t)
        # no other fields leaked
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)

    # ──────────────────────────────────────────────
    # Group 8: SerializerMethodField (display_name)
    # ──────────────────────────────────────────────

    def test_method_field_in_default_response(self):
        """display_name (SerializerMethodField) is present by default."""
        row = self._get_item(self.i1.id)
        self.assertEqual(row["display_name"], "Widget A (x2)")
        row2 = self._get_item(self.i2.id)
        self.assertEqual(row2["display_name"], "Widget B (x5)")

    def test_method_field_in_fields_subset(self):
        """?fields=id,display_name → only id and display_name returned."""
        row = self._get_item(self.i1.id, "?fields=id,display_name")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["display_name"], "Widget A (x2)")
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("media_upload_id", row)

    def test_method_field_excluded_by_fields(self):
        """?fields=id,name → display_name absent (not requested)."""
        row = self._get_item(self.i1.id, "?fields=id,name")
        self.assertNotIn("display_name", row)
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["name"], "Widget A")

    def test_method_field_with_expand(self):
        """?fields=id,display_name&expand=media_upload → both computed field and expansion work."""
        row = self._get_item(self.i1.id, "?fields=id,display_name&expand=media_upload")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["display_name"], "Widget A (x2)")
        self.assertIsInstance(row["media_upload"], dict)
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)

    # ──────────────────────────────────────────────
    # Group 9: Queryset annotations (tag_count, has_media)
    # ──────────────────────────────────────────────

    def test_annotation_int_in_default_response(self):
        """tag_count (Count annotation) is present by default."""
        row = self._get_item(self.i1.id)
        self.assertEqual(row["tag_count"], 2)
        row2 = self._get_item(self.i2.id)
        self.assertEqual(row2["tag_count"], 0)

    def test_annotation_bool_in_default_response(self):
        """has_media (Q annotation with BooleanField) is present by default."""
        row = self._get_item(self.i1.id)
        self.assertIs(row["has_media"], True)
        row2 = self._get_item(self.i2.id)
        self.assertIs(row2["has_media"], False)

    def test_annotation_in_fields_subset(self):
        """?fields=id,tag_count,has_media → only requested fields returned."""
        row = self._get_item(self.i1.id, "?fields=id,tag_count,has_media")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["tag_count"], 2)
        self.assertIs(row["has_media"], True)
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("display_name", row)

    def test_annotation_excluded_by_fields(self):
        """?fields=id,name → annotation fields absent (not requested)."""
        row = self._get_item(self.i1.id, "?fields=id,name")
        self.assertNotIn("tag_count", row)
        self.assertNotIn("has_media", row)

    def test_annotation_with_expand(self):
        """?fields=id,tag_count,has_media&expand=media_upload → annotations and expansion coexist."""
        row = self._get_item(self.i1.id, "?fields=id,tag_count,has_media&expand=media_upload")
        self.assertEqual(row["id"], self.i1.id)
        self.assertEqual(row["tag_count"], 2)
        self.assertIs(row["has_media"], True)
        self.assertIsInstance(row["media_upload"], dict)
        self.assertNotIn("name", row)

    # ──────────────────────────────────────────────
    # Group 10: Ordering (?order=)
    # ──────────────────────────────────────────────

    def test_order_ascending(self):
        """?order=name → items sorted by name ascending."""
        rows = self._get_items("?order=name")
        names = [r["name"] for r in rows]
        self.assertEqual(names, sorted(names))

    def test_order_descending(self):
        """?order=-name → items sorted by name descending."""
        rows = self._get_items("?order=-name")
        names = [r["name"] for r in rows]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_order_multiple_fields(self):
        """?order=-quantity,name → primary desc quantity, secondary asc name."""
        rows = self._get_items("?order=-quantity,name")
        # i2 (qty=5) before i1 (qty=2)
        self.assertEqual(rows[0]["id"], self.i2.id)
        self.assertEqual(rows[1]["id"], self.i1.id)

    def test_order_by_annotation(self):
        """?order=-tag_count → items ordered by annotated field."""
        rows = self._get_items("?order=-tag_count")
        # i1 has 2 tags, i2 has 0 tags
        self.assertEqual(rows[0]["id"], self.i1.id)
        self.assertEqual(rows[1]["id"], self.i2.id)

    def test_order_invalid_field_ignored(self):
        """?order=nonexistent → unknown field ignored, default ordering used."""
        rows = self._get_items("?order=nonexistent")
        self.assertEqual(len(rows), 2)

    def test_order_with_expand(self):
        """?order=name&expand=media_upload → ordering and expansion coexist."""
        rows = self._get_items("?order=name&expand=media_upload")
        names = [r["name"] for r in rows]
        self.assertEqual(names, sorted(names))
        self.assertIsInstance(rows[0]["media_upload"], dict)

    # ──────────────────────────────────────────────
    # Group 11: Nested "none" blocking
    # ──────────────────────────────────────────────

    def test_nested_none_blocks_child_relations(self):
        """?expand=media_upload,media_upload.owner&relations=media_upload.none
        → media_upload expanded but owner removed entirely (blocked by nested none).
        """
        row = self._get_item(
            self.i1.id,
            "?expand=media_upload,media_upload.owner&relations=media_upload.none",
        )
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertEqual(mu["url"], "https://example.com/a.png")
        # owner removed entirely — blocked by nested none
        self.assertNotIn("owner", mu)
        self.assertNotIn("owner_id", mu)

    def test_nested_none_vs_without_none(self):
        """?relations=media_upload (no .none) allows child defaults → owner can expand.
        ?relations=media_upload.none blocks child defaults → owner removed entirely.
        """
        # Without .none: owner expands (child gets empty relations_tree → defaults fill in)
        row_with = self._get_item(
            self.i1.id,
            "?expand=media_upload,media_upload.owner&relations=media_upload",
        )
        self.assertIn("owner", row_with["media_upload"])
        self.assertIsInstance(row_with["media_upload"]["owner"], dict)

        # With .none: owner removed entirely (child gets {"none": {}} → blocked)
        row_none = self._get_item(
            self.i1.id,
            "?expand=media_upload,media_upload.owner&relations=media_upload.none",
        )
        self.assertNotIn("owner", row_none["media_upload"])
        self.assertNotIn("owner_id", row_none["media_upload"])

    def test_nested_none_fields_blocks_child_fields(self):
        """?fields=id,media_upload.none&expand=media_upload&relations=media_upload
        → media_upload expanded but with no visible fields (all blocked by nested none).
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.none&expand=media_upload&relations=media_upload",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        # All child fields blocked — none fills fields_tree with {"none": {}},
        # _filter_local_fields keeps only keys in the tree, which is just "none" (no real fields)
        self.assertNotIn("url", mu)
        self.assertNotIn("owner_id", mu)
        self.assertNotIn("created", mu)

    def test_nested_none_fields_on_m2m(self):
        """?fields=id,tags.none&expand=tags → tags expanded but all tag fields stripped."""
        row = self._get_item(
            self.i1.id,
            "?fields=id,tags.none&expand=tags",
        )
        self.assertEqual(row["id"], self.i1.id)
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        # Each tag object has no visible fields — all stripped by nested none
        for t in row["tags"]:
            self.assertNotIn("id", t)
            self.assertNotIn("name", t)

    def test_nested_none_three_levels_deep(self):
        """?fields=id,media_upload.id,media_upload.owner.none
        &expand=media_upload,media_upload.owner
        &relations=media_upload,media_upload.owner
        → owner expanded but all owner fields stripped by none at 3rd level.
        """
        row = self._get_item(
            self.i1.id,
            "?fields=id,media_upload.id,media_upload.owner.none"
            "&expand=media_upload,media_upload.owner"
            "&relations=media_upload,media_upload.owner",
        )
        self.assertEqual(row["id"], self.i1.id)
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        # owner expanded but all fields stripped by .owner.none
        self.assertIsInstance(mu["owner"], dict)
        self.assertNotIn("id", mu["owner"])
        self.assertNotIn("name", mu["owner"])

    def test_combined_relations_none_and_fields_none(self):
        """?relations=media_upload,media_upload.none,tags
        &fields=id,tags.none
        &expand=media_upload,tags
        → media_upload expanded (owner blocked by relations media_upload.none),
          tags expanded (all tag fields blocked by fields tags.none).
        """
        row = self._get_item(
            self.i1.id,
            "?relations=media_upload,media_upload.none,tags"
            "&fields=id,tags.none"
            "&expand=media_upload,tags",
        )
        self.assertEqual(row["id"], self.i1.id)
        # media_upload expanded, owner removed by media_upload.none
        mu = row["media_upload"]
        self.assertIsInstance(mu, dict)
        self.assertEqual(mu["id"], self.m1.id)
        self.assertNotIn("owner", mu)
        self.assertNotIn("owner_id", mu)
        # tags expanded but all tag fields stripped by tags.none
        self.assertIsInstance(row["tags"], list)
        self.assertEqual(len(row["tags"]), 2)
        for t in row["tags"]:
            self.assertNotIn("id", t)
            self.assertNotIn("name", t)

    def test_fields_none_blocks_all_fields(self):
        """?fields=none → strips all non-relation fields.

        ``{"none": {}}`` is truthy so _ensure_defaults doesn't fill in
        allowed_fields. _filter_local_fields keeps only keys in fields_tree
        (just "none") plus expand_tree and relations_tree keys. Since "none"
        matches no real field, only relation keys (from default relations_tree)
        survive.
        """
        rows = self._get_items("?fields=none")
        row = rows[0]
        # All regular fields stripped — including id
        self.assertNotIn("id", row)
        self.assertNotIn("name", row)
        self.assertNotIn("quantity", row)
        self.assertNotIn("display_name", row)
        self.assertNotIn("created", row)
        self.assertNotIn("modified", row)
        self.assertNotIn("media_upload_id", row)
        # Relations survive via default relations_tree
        self.assertIn("tags", row)
