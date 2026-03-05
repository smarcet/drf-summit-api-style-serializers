# ADR-001: Summit-Style Query Parameters

## Status

Accepted

## Context

REST APIs commonly return fixed response shapes — every client gets every field and every nested object, whether they need it or not. This wastes bandwidth, increases serialization time, and causes N+1 query problems when relations are eagerly loaded.

We need a system where **the client controls** what comes back: which fields, which relations get expanded into full objects, and which relations are even allowed.

## Decision

Three query parameters control serialization:

| Parameter | Purpose | Default (when omitted) |
|-----------|---------|----------------------|
| `?fields=` | Which fields to include | All `allowed_fields` |
| `?expand=` | Which relations to expand into objects | None (show IDs only) |
| `?relations=` | Which relations are permitted to expand | All `allowed_relations` |

The system is built on four components:

1. **`BaseModelSerializer`** — serializer base class that reads query params and filters fields
2. **`One2ManyExpandSerializer`** / **`Many2OneExpandSerializer`** — expansion strategies for FK and M2M relations
3. **`ExpandQuerysetOptimizationMixin`** — view mixin that auto-applies `select_related` / `prefetch_related` / bulk prefetch hooks based on what the client requested
4. **`query_params` module** — parses CSV+dot notation into nested tree dicts

## How It Works

### The Tree Data Structure

Query params are parsed into nested dicts. The string `media_upload,media_upload.owner` becomes:

```python
{"media_upload": {"owner": {}}}
```

Each key is a field name. Nested dicts represent child fields. This tree is sliced at each serializer level — a child serializer only sees its own subtree.

**Convention for tree values:**

| Value | Meaning |
|-------|---------|
| `None` | "Not specified — use all defaults for this serializer" |
| `{}` (empty dict) | Same as `None` after `_ensure_defaults` runs |
| `{"id": {}, "name": {}}` | "Only include these specific fields/relations" |

### Request Lifecycle

```
1. Client sends: GET /api/items/?fields=id,name&expand=media_upload&relations=media_upload

2. ExpandQuerysetOptimizationMixin.get_queryset()
   - Parses query params into trees
   - Walks expand_mappings recursively
   - Collects select_related / prefetch_related / bulk_prefetch hooks
   - Optimizes the queryset BEFORE hitting the database

3. ExpandQuerysetOptimizationMixin.list()
   - Executes the optimized query
   - Runs bulk_prefetch hooks (for computed relations like Item.media_upload)
   - Passes objects to the serializer

4. BaseModelSerializer.get_fields()
   - _ensure_defaults(): fills in allowed_fields/relations when client didn't specify
   - _filter_local_fields(): removes fields not in ?fields= (keeping expanded/relation fields)
   - For each expand_mapping: expand or collapse the relation based on ?expand= and ?relations=

5. Response: {"id": 1, "name": "Widget A", "media_upload": {"id": 1, "url": "...", ...}}
```

## Serializer Setup

### Step 1: Define the serializer

Every serializer declares three things:

```python
from base_api_utils.serializers.v2 import BaseModelSerializer
from base_api_utils.serializers.v2.expands import One2ManyExpandSerializer, Many2OneExpandSerializer


class OwnerSerializer(BaseModelSerializer):
    # No relations to expand — this is a leaf serializer
    allowed_fields = ["id", "name"]
    allowed_relations = []
    expand_mappings = {}

    class Meta:
        model = Owner
        fields = ["id", "name"]


class MediaUploadSerializer(BaseModelSerializer):
    # Declare the nested serializer field (DRF needs this for expansion)
    owner = OwnerSerializer(read_only=True, required=False)

    # 1. Fields the client can request via ?fields=
    allowed_fields = ["id", "url", "owner_id", "created", "modified"]

    # 2. Relations the client can expand (must also appear in Meta.fields)
    allowed_relations = ["owner"]

    # 3. How to expand each relation
    expand_mappings = {
        "owner": {
            "type": One2ManyExpandSerializer(),  # FK relation (many items -> one owner)
            "serializer": OwnerSerializer,        # What serializer to use when expanded
            "original_attribute": "owner_id",     # The FK field to remove when expanded
            "source": "owner",                    # The model attribute to read from
            "verify_relation": True,              # Require ?relations=owner to expand
            "orm": {"select_related": ["owner"]}, # ORM optimization when expanded
        }
    }

    class Meta:
        model = MediaUpload
        fields = ["id", "url", "owner_id", "owner", "created", "modified"]


class ItemSerializer(BaseModelSerializer):
    media_upload = MediaUploadSerializer(read_only=True, required=False)
    tags = TagSerializer(many=True, read_only=True, required=False)

    allowed_fields = ["id", "name", "quantity", "media_upload_id", "media_upload", "tags", "created", "modified"]
    allowed_relations = ["media_upload", "tags"]

    expand_mappings = {
        "media_upload": {
            "type": One2ManyExpandSerializer(),
            "serializer": MediaUploadSerializer,
            "original_attribute": "media_upload_id",
            "source": "media_upload",
            "verify_relation": True,
            "orm": {"bulk_prefetch": "media_upload"},  # Computed property — uses bulk hook
        },
        "tags": {
            "type": Many2OneExpandSerializer(),  # M2M relation (one item -> many tags)
            "serializer": TagSerializer,
            "source": "tags",
            "verify_relation": True,
            "orm": {"prefetch_related": ["tags"]},
        },
    }

    class Meta:
        model = Item
        fields = ["id", "name", "quantity", "media_upload_id", "media_upload", "tags", "created", "modified"]
```

### Step 2: Choose the expansion type

| Type | Use When | Not Expanded | Expanded |
|------|----------|-------------|----------|
| `One2ManyExpandSerializer` | ForeignKey (many items point to one related object) | Shows `media_upload_id: 5` (removes the relation field, keeps the FK) | Shows `media_upload: {id: 5, url: "..."}` (removes the FK field) |
| `Many2OneExpandSerializer` | ManyToMany or reverse FK (one item has many related) | Shows `tags: [1, 2, 3]` (list of IDs) | Shows `tags: [{id: 1, name: "alpha"}, ...]` (list of objects) |

### Step 3: Configure ORM optimization

The `"orm"` key in expand_mappings tells the view mixin how to optimize queries:

```python
"orm": {"select_related": ["owner"]}        # FK join — use for One2Many with real FK
"orm": {"prefetch_related": ["tags"]}        # Separate query — use for M2M
"orm": {"bulk_prefetch": "media_upload"}     # Custom hook — use for computed properties
```

## View Setup

### Basic view (no computed relations)

```python
from base_api_utils.views import BaseView, ExpandQuerysetOptimizationMixin

class MediaUploadViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    queryset = MediaUpload.objects.all().order_by("id")
    serializer_class = MediaUploadSerializer
    ordering_fields = {"id": "id", "url": "url"}
```

That's it. The mixin reads expand_mappings from the serializer and auto-applies `select_related`/`prefetch_related`.

### View with bulk prefetch hook (computed relations)

When a relation is a computed property (not a real Django FK), the ORM can't `select_related` it. Instead, declare `"orm": {"bulk_prefetch": "media_upload"}` in the serializer, then implement the hook on the view:

```python
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    queryset = Item.objects.all().order_by("id")
    serializer_class = ItemSerializer
    ordering_fields = {"id": "id", "name": "name", "quantity": "quantity"}

    def bulk_prefetch__media_upload(self, items, expand_subtree, fields_subtree, relations_subtree):
        """Called when ?expand=media_upload is requested. Runs ONE query for all items."""
        from base_api_utils.serializers.v2.query_params import has_key

        qs = MediaUpload.objects.all()

        # If the client also asked to expand media_upload.owner, join it in
        if has_key(expand_subtree, "owner") and has_key(relations_subtree, "owner"):
            qs = qs.select_related("owner")

        # Single query: fetch all needed media uploads
        ids = {i.media_upload_id for i in items if getattr(i, "media_upload_id", None)}
        uploads = {m.id: m for m in qs.filter(id__in=ids)}

        # Cache on each model instance (the property checks for this)
        for i in items:
            i._prefetched_media_upload = uploads.get(i.media_upload_id)
```

The corresponding model property checks the cache first:

```python
class Item(models.Model):
    media_upload_id = models.IntegerField(null=True, blank=True)

    @property
    def media_upload(self):
        if hasattr(self, "_prefetched_media_upload"):
            return self._prefetched_media_upload
        if not self.media_upload_id:
            return None
        return MediaUpload.objects.filter(pk=self.media_upload_id).first()
```

### Bulk prefetch hook signature

```python
def bulk_prefetch__<name>(self, items, expand_subtree, fields_subtree, relations_subtree):
```

| Argument | Type | Description |
|----------|------|-------------|
| `items` | `list` | The model instances being serialized |
| `expand_subtree` | `dict` | Nested expansions below this relation (e.g., `{"owner": {}}` if client sent `?expand=media_upload.owner`) |
| `fields_subtree` | `dict \| None` | Nested field restrictions below this relation |
| `relations_subtree` | `dict \| None` | Nested relation restrictions below this relation |

## Client Usage (API Examples)

All examples assume the models described above: `Item` has a `media_upload` (FK-like) and `tags` (M2M).

### Default — no parameters

```
GET /api/items/
```
```json
[
  {
    "id": 1,
    "name": "Widget A",
    "quantity": 2,
    "media_upload_id": 1,
    "tags": [1, 2],
    "created": "2026-03-05T00:00:00Z",
    "modified": "2026-03-05T00:00:00Z"
  }
]
```

Relations shown as IDs. All allowed_fields included.

### Select specific fields

```
GET /api/items/?fields=id,name
```
```json
[{"id": 1, "name": "Widget A", "tags": [1, 2]}]
```

Only `id` and `name` requested. `tags` still appears because `allowed_relations` fields are kept by default (the system ensures relations are always available for potential expansion).

### Expand a FK relation

```
GET /api/items/?expand=media_upload
```
```json
[
  {
    "id": 1,
    "name": "Widget A",
    "quantity": 2,
    "media_upload": {
      "id": 1,
      "url": "https://example.com/a.png",
      "owner_id": 3,
      "created": "2026-03-05T00:00:00Z",
      "modified": "2026-03-05T00:00:00Z"
    },
    "tags": [1, 2],
    "created": "2026-03-05T00:00:00Z",
    "modified": "2026-03-05T00:00:00Z"
  }
]
```

`media_upload_id` is removed and replaced by the full `media_upload` object.

### Expand a M2M relation

```
GET /api/items/?expand=tags
```
```json
[
  {
    "id": 1,
    "name": "Widget A",
    "quantity": 2,
    "media_upload_id": 1,
    "tags": [
      {"id": 1, "name": "alpha"},
      {"id": 2, "name": "beta"}
    ],
    "created": "2026-03-05T00:00:00Z",
    "modified": "2026-03-05T00:00:00Z"
  }
]
```

### Nested expansion (dot notation)

```
GET /api/items/?expand=media_upload,media_upload.owner
```
```json
[
  {
    "id": 1,
    "name": "Widget A",
    "quantity": 2,
    "media_upload": {
      "id": 1,
      "url": "https://example.com/a.png",
      "owner": {"id": 3, "name": "Alice"},
      "created": "2026-03-05T00:00:00Z",
      "modified": "2026-03-05T00:00:00Z"
    },
    "tags": [1, 2],
    "created": "2026-03-05T00:00:00Z",
    "modified": "2026-03-05T00:00:00Z"
  }
]
```

`owner_id` is removed from `media_upload` because `owner` is expanded.

### Filter nested fields (dot notation)

```
GET /api/items/?fields=id,media_upload.id,media_upload.url&expand=media_upload
```
```json
[{"id": 1, "media_upload": {"id": 1, "url": "https://example.com/a.png"}}]
```

The dot notation `media_upload.id,media_upload.url` restricts the nested serializer to only those fields.

### Block expansion with ?relations=

When `verify_relation: True` is set in `expand_mappings`, the client must include the relation in `?relations=` for expansion to work. If `?relations=` is omitted entirely, all `allowed_relations` are permitted by default.

```
GET /api/items/?expand=media_upload,tags&relations=media_upload
```
```json
[
  {
    "id": 1,
    "name": "Widget A",
    "quantity": 2,
    "media_upload": {"id": 1, "url": "...", "owner_id": 3, "created": "...", "modified": "..."},
    "tags": [1, 2],
    "created": "...",
    "modified": "..."
  }
]
```

`media_upload` is expanded (listed in both `expand` and `relations`). `tags` stays as IDs (listed in `expand` but NOT in `relations`).

### All three combined

```
GET /api/items/?fields=id,media_upload.id,media_upload.owner.name&expand=media_upload,media_upload.owner&relations=media_upload,media_upload.owner
```
```json
[{"id": 1, "media_upload": {"id": 1, "owner": {"name": "Alice"}}}]
```

Three levels deep: only `id` on the item, only `id` and `owner` on media_upload, only `name` on owner.

### Null relations

```
GET /api/items/?expand=media_upload
```
```json
[
  {"id": 1, "media_upload": {"id": 1, "url": "..."}, ...},
  {"id": 2, "media_upload": null, ...}
]
```

Item 2 has `media_upload_id = None`, so the expanded value is `null`.

## Consequences

### Benefits
- Clients fetch only what they need — smaller payloads, fewer round trips
- ORM optimization is automatic — no manual `select_related` per endpoint
- Recursive: the same pattern works at any nesting depth
- `?relations=` acts as a server-side gate — even if a client sends `?expand=secret_relation`, it won't work unless `allowed_relations` permits it

### Trade-offs
- Serializer setup has three parallel declarations (`allowed_fields`, `allowed_relations`, `expand_mappings` plus `Meta.fields`) that must stay in sync
- The tree data structure (`None` vs `{}`) has subtle semantics — see the codebase's `_ensure_defaults` and `_child_tree` for how defaults are resolved
- DRF's `field.bind()` replaces child serializer context with the parent's, requiring the `_own_context` / `_original_context` workaround to preserve each serializer's own trees
