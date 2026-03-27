## Summit-Style Serializers

**Pattern for DRF serializers with nested expansion control via query parameters.**

### Core Components

Every serializer declares up to three attributes. `Meta.fields` is auto-set to `"__all__"` by `BaseModelSerializer` — only `Meta.model` is needed. Relations from `allowed_relations` are auto-merged into the allowed field pool.

```python
class ItemSerializer(BaseModelSerializer):
    # 1. Non-relation fields allowed in ?fields= param (relations auto-merged)
    allowed_fields = ["id", "name", "quantity", "media_upload_id"]

    # 2. Relations allowed in ?relations= param (auto-merged into allowed fields)
    allowed_relations = ["media_upload", "tags"]

    # 3. How to expand each relation
    expand_mappings = {
        "media_upload": {
            "type": One2ManyExpandSerializer(),
            "serializer": MediaUploadSerializer,
            "original_attribute": "media_upload_id",  # FK field name
            "source": "media_upload",  # Relation attribute
            "verify_relation": True,  # Require ?relations= param
            "orm": {"bulk_prefetch": "media_upload"},  # Optimization strategy
        }
    }

    class Meta:
        model = Item  # Meta.fields auto-set to '__all__'
```

### Expansion Types

| Type | Use When |
|------|----------|
| `One2ManyExpandSerializer()` | ForeignKey (many items → one related) |
| `Many2OneExpandSerializer()` | ManyToMany or reverse FK (one item → many related) |

### ORM Optimization

```python
"orm": {
    "select_related": ["field"],      # For ForeignKey (one-to-one joins)
    "prefetch_related": ["field"],    # For ManyToMany or reverse FK
    "bulk_prefetch": "method_name",   # For computed properties (see bulk-prefetch.md)
}
```

### Recursive Expansion

Child serializers can have their own `expand_mappings`. The system automatically chains ORM optimizations:

```python
# ?expand=media_upload.owner
# → Generates: select_related("media_upload__owner")
```

### Field Declaration

**Do NOT declare explicit nested serializer fields** for relations handled by `expand_mappings`. The expansion types create fields dynamically:

- `One2ManyExpandSerializer.apply()` creates the serializer field when expanded, or an `IntegerField` for the FK when not
- `Many2OneExpandSerializer.apply()` replaces the DRF-auto-generated field with the serializer or `PrimaryKeyRelatedField`

Explicit declarations like `media_upload = MediaUploadSerializer(read_only=True, required=False)` are redundant — they get overwritten by `apply()` in all cases.

**Exception:** `SerializerMethodField` for custom expansion logic (see below) — these must be declared since they're not managed by `expand_mappings`.

### Custom Expansion Logic

For cases where `expand_mappings` can't handle the expansion (e.g., custom filtering, conditional logic), use `SerializerMethodField` with `get_expand()` and `get_child_context()`:

```python
class ManagedMediaRequestModuleSerializer(BaseModelSerializer):
    media_upload = serializers.SerializerMethodField()
    allowed_relations = ['media_upload']

    def get_media_upload(self, obj):
        sponsor_id = self.context.get('sponsor_id')
        if not sponsor_id:
            return None

        media_upload = obj.get_media_uploads().filter(sponsor_id=sponsor_id).first()
        if not media_upload:
            return None

        # Check if expansion is requested
        if 'media_upload' not in self.get_expand():
            return media_upload.id  # Not expanded → return just the ID

        # Expanded → return full object with scoped context for nested params
        return SponsorMediaUploadSerializer(
            context=self.get_child_context('media_upload')
        ).to_representation(media_upload)
```

**Key methods:**

- `self.get_expand()` — returns list of relation names requested at current serializer level
- `self.get_child_context('attr')` — builds scoped context for child serializer, enabling nested `?fields=`, `?expand=`, and `?relations=`

**⚠️ Important:** Always use `get_child_context()` when instantiating child serializers. Using `self.context` directly works for flat expansions but breaks nested query parameter scoping.
