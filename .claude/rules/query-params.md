## Query Parameter API

**Client-controlled field selection and expansion.**

### Basic Syntax

```
?fields=id,name            # Return only id and name
?expand=media_upload       # Include media_upload object
?relations=media_upload    # Required when verify_relation=True
```

### Nested Expansion

```
?expand=media_upload,media_upload.owner
&relations=media_upload,media_upload.owner
```

Generates dotted ORM paths:
- `select_related("media_upload__owner")`

### Fields Filtering

```
?fields=id,name,media_upload
&expand=media_upload
&relations=media_upload
```

**Rules:**
- If `fields` is omitted → all `allowed_fields` included
- Expanded relations automatically included even if not in `fields`

### Nested Fields

```
?fields=id,name,media_upload(id,url)
&expand=media_upload
&relations=media_upload
```

Serializer applies nested `fields` to child serializers.

### Common Patterns

| Use Case | Query Params |
|----------|--------------|
| Minimal response | `?fields=id,name` |
| Include relation | `?expand=relation&relations=relation` |
| Deep expansion | `?expand=a.b.c&relations=a.b.c` |
| Selective nesting | `?fields=id,rel(id,name)&expand=rel&relations=rel` |

### ViewSet Implementation

Must use `ExpandQuerysetOptimizationMixin`:

```python
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
```

Mixin automatically:
1. Parses query params into trees
2. Collects ORM optimizations from `expand_mappings`
3. Applies `select_related`/`prefetch_related`
4. Runs `bulk_prefetch__*` hooks
