## Bulk Prefetch Pattern

**Optimize computed model properties in list endpoints.**

### Problem

Django model properties that query the database cause N+1 problems:

```python
class Item(models.Model):
    media_upload_id = models.IntegerField(null=True)

    @property
    def media_upload(self):
        # ❌ N+1 query when listing items
        return MediaUpload.objects.filter(pk=self.media_upload_id).first()
```

### Solution

1. **Declare in `expand_mappings`:**

```python
"orm": {"bulk_prefetch": "media_upload"}
```

2. **Implement `bulk_prefetch__<name>` in ViewSet:**

```python
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    def bulk_prefetch__media_upload(self, items, expand_subtree, fields_subtree, relations_subtree):
        # Collect all IDs
        ids = {i.media_upload_id for i in items if i.media_upload_id}

        # Single query with nested optimization
        qs = MediaUpload.objects.filter(id__in=ids)
        if has_key(expand_subtree, "owner") and has_key(relations_subtree, "owner"):
            qs = qs.select_related("owner")

        # Cache on model instances
        uploads = {m.id: m for m in qs}
        for i in items:
            i._prefetched_media_upload = uploads.get(i.media_upload_id)
```

3. **Check cache in property:**

```python
@property
def media_upload(self):
    if hasattr(self, "_prefetched_media_upload"):
        return self._prefetched_media_upload
    # Fallback for single-object access
    return MediaUpload.objects.filter(pk=self.media_upload_id).first()
```

### Method Signature

```python
def bulk_prefetch__<name>(
    self,
    items: list,              # Objects being serialized
    expand_subtree: dict,     # Nested ?expand= for this relation
    fields_subtree: dict|None,# Nested ?fields= for this relation
    relations_subtree: dict|None # Nested ?relations= for this relation
):
```

### Recursive Optimization

Use subtree params to optimize nested expansions:

```python
if has_key(expand_subtree, "owner"):
    # User requested ?expand=media_upload.owner
    qs = qs.select_related("owner")
```
