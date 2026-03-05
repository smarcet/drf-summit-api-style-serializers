## Annotation Fields

**Expose Django queryset annotations through serializers.**

### Pattern

1. **Annotate in ViewSet.get_queryset():**

```python
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    def get_queryset(self):
        return super().get_queryset().annotate(
            tag_count=Count("tags"),
            has_media=Q(media_upload_id__isnull=False),
        )
```

2. **Declare in serializer:**

```python
class ItemSerializer(BaseModelSerializer):
    tag_count = serializers.IntegerField(read_only=True)
    has_media = serializers.BooleanField(read_only=True)

    allowed_fields = ["id", "name", "tag_count", "has_media", ...]
```

3. **Include in Meta.fields:**

```python
class Meta:
    model = Item
    fields = ["id", "name", "tag_count", "has_media", ...]
```

### Rules

- Always `read_only=True` - annotations are computed
- Include in `allowed_fields` for query parameter filtering
- NOT in `allowed_relations` - annotations are fields, not relations
- Annotations don't require `expand_mappings` - they're pre-computed

### Common Annotations

| Type | Example | Serializer Field |
|------|---------|------------------|
| Aggregate | `Count("tags")` | `IntegerField(read_only=True)` |
| Boolean | `Q(field__isnull=False)` | `BooleanField(read_only=True)` |
| Computed | `F("price") * F("quantity")` | `DecimalField(read_only=True)` |
