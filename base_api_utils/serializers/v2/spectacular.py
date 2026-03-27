from drf_spectacular.extensions import OpenApiSerializerExtension


class ExpandMappingSerializerExtension(OpenApiSerializerExtension):
    """Generate OpenAPI schemas with all expand_mappings expanded.

    Without this extension, drf-spectacular calls get_fields() on our serializers
    without request context, which collapses all relations to ID fields. This
    extension builds a synthetic "all expanded" context so the schema shows
    nested serializer types ($ref) instead of integer IDs.
    """

    target_class = (
        "base_api_utils.serializers.v2.base_model_serializer.AbstractSerializer"
    )
    match_subclasses = True

    def map_serializer(self, auto_schema, direction):
        serializer = self.target
        mappings = serializer._merged_expand_mappings()

        # Leaf serializers (no expand_mappings) — delegate to default handling
        if not mappings:
            return auto_schema._map_serializer(serializer, direction, bypass_extensions=True)

        # Build synthetic context with all relations expanded
        expand_tree = {}
        for attr, spec in mappings.items():
            child_serializer_cls = spec["serializer"]
            child_mappings = {}
            # Build child expand tree from the child serializer's own mappings
            if hasattr(child_serializer_cls, "_merged_expand_mappings"):
                try:
                    child_instance = child_serializer_cls(context={})
                    child_mappings = child_instance._merged_expand_mappings()
                except Exception:
                    pass
            expand_tree[attr] = {k: {} for k in child_mappings}

        relations_tree = {attr: {} for attr in mappings}
        # Also include any allowed_relations not covered by expand_mappings
        for rel in serializer._merged_allowed_relations():
            if rel not in relations_tree:
                relations_tree[rel] = {}

        context = {
            "expand_tree": expand_tree,
            "fields_tree": None,
            "relations_tree": relations_tree,
        }

        # Create a new instance with the synthetic context
        expanded = serializer.__class__(context=context)
        return auto_schema._map_serializer(expanded, direction, bypass_extensions=True)
