import json

from django.core.management import call_command
from django.test import TestCase


class SpectacularExtensionTestCase(TestCase):
    """Verify drf-spectacular generates proper nested $ref schemas for expand_mappings."""

    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        out = StringIO()
        call_command("spectacular", "--format", "openapi-json", stdout=out)
        cls.schema = json.loads(out.getvalue())
        cls.components = cls.schema["components"]["schemas"]

    def _get_component(self, name):
        """Get a schema component by name, trying common naming patterns."""
        if name in self.components:
            return self.components[name]
        # drf-spectacular may add direction suffixes
        for suffix in ["Response", "Request"]:
            key = f"{name}{suffix}"
            if key in self.components:
                return self.components[key]
        self.fail(f"Component '{name}' not found in schema. Available: {list(self.components.keys())}")

    def _get_property(self, component_name, prop_name):
        """Get a property schema from a component."""
        component = self._get_component(component_name)
        props = component.get("properties", {})
        self.assertIn(prop_name, props, f"Property '{prop_name}' not in {component_name}")
        return props[prop_name]

    def _extract_ref(self, prop):
        """Extract $ref string from a property, handling allOf wrapping.

        drf-spectacular wraps read-only $ref fields as:
            {"allOf": [{"$ref": "..."}], "readOnly": true}
        instead of a direct {"$ref": "..."}.
        """
        if "$ref" in prop:
            return prop["$ref"]
        all_of = prop.get("allOf", [])
        for item in all_of:
            if "$ref" in item:
                return item["$ref"]
        self.fail(f"No $ref found in property: {prop}")

    # -- Item schema assertions --

    def test_item_media_upload_is_ref(self):
        """Item.media_upload should be a $ref to MediaUpload, not an integer."""
        prop = self._get_property("Item", "media_upload")
        ref = self._extract_ref(prop)
        self.assertIn("MediaUpload", ref)

    def test_item_tags_is_array_of_ref(self):
        """Item.tags should be an array of $ref Tag, not an array of integers."""
        prop = self._get_property("Item", "tags")
        self.assertEqual(prop.get("type"), "array", f"Expected array type, got: {prop}")
        items = prop.get("items", {})
        self.assertIn("$ref", items, f"Expected $ref in tags items, got: {items}")
        self.assertIn("Tag", items["$ref"])

    def test_item_no_media_upload_id_when_expanded(self):
        """When media_upload is expanded, media_upload_id should not appear."""
        component = self._get_component("Item")
        props = component.get("properties", {})
        self.assertNotIn("media_upload_id", props,
                         "media_upload_id should be removed when media_upload is expanded")

    def test_item_nonrelation_fields_unchanged(self):
        """Non-relation fields like name, quantity, display_name should still be present."""
        component = self._get_component("Item")
        props = component.get("properties", {})
        for field in ("name", "quantity", "display_name"):
            self.assertIn(field, props, f"Expected field '{field}' in Item schema")

    # -- MediaUpload schema assertions --

    def test_media_upload_owner_is_ref(self):
        """MediaUpload.owner should be a $ref to Owner, not an integer."""
        prop = self._get_property("MediaUpload", "owner")
        ref = self._extract_ref(prop)
        self.assertIn("Owner", ref)

    def test_media_upload_no_owner_id_when_expanded(self):
        """When owner is expanded, owner_id should not appear."""
        component = self._get_component("MediaUpload")
        props = component.get("properties", {})
        self.assertNotIn("owner_id", props,
                         "owner_id should be removed when owner is expanded")

    def test_media_upload_nonrelation_fields(self):
        """MediaUpload should still have url, created, modified."""
        component = self._get_component("MediaUpload")
        props = component.get("properties", {})
        for field in ("url", "created", "modified"):
            self.assertIn(field, props, f"Expected field '{field}' in MediaUpload schema")

    # -- Leaf serializer assertions --

    def test_owner_schema_unaffected(self):
        """Owner (leaf serializer, no expand_mappings) should have id and name."""
        component = self._get_component("Owner")
        props = component.get("properties", {})
        self.assertIn("id", props)
        self.assertIn("name", props)

    def test_tag_schema_unaffected(self):
        """Tag (leaf serializer, no expand_mappings) should have id and name."""
        component = self._get_component("Tag")
        props = component.get("properties", {})
        self.assertIn("id", props)
        self.assertIn("name", props)

    # -- General schema validity --

    def test_schema_has_paths(self):
        """Generated schema should have API paths."""
        self.assertIn("paths", self.schema)
        self.assertTrue(len(self.schema["paths"]) > 0)

    def test_item_custom_expand_tags_is_array_of_ref(self):
        """ItemCustomExpand.tags should also be an array of $ref Tag."""
        prop = self._get_property("ItemCustomExpand", "tags")
        self.assertEqual(prop.get("type"), "array")
        items = prop.get("items", {})
        self.assertIn("$ref", items, f"Expected $ref in tags items, got: {items}")
        self.assertIn("Tag", items["$ref"])
