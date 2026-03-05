## Summit-Style Serializers

**Pattern for DRF serializers with nested expansion control via query parameters.**

### Core Components

Every serializer declares three attributes:

```python
class ItemSerializer(BaseModelSerializer):
    # 1. Fields allowed in ?fields= param
    allowed_fields = ["id", "name", "quantity", "media_upload_id"]

    # 2. Relations allowed in ?relations= param (must also be in allowed_fields)
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

Always declare nested serializers as `read_only` with `required=False`:

```python
media_upload = MediaUploadSerializer(read_only=True, required=False)
tags = TagSerializer(many=True, read_only=True, required=False)
```
