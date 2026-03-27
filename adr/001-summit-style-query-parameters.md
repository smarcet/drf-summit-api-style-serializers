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
| `?relations=` | Which relations to include in the response | All `allowed_relations` |

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
| `{"none": {}}` | "Block everything — truthy (so defaults not filled), but `none` matches no real field/relation" |

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

Every serializer declares up to three things:

- **`allowed_fields`** — non-relation fields the client can request via `?fields=`. Relations from `allowed_relations` are auto-merged, so don't list them here. Set to `None` (or omit) to allow all fields (same behavior as the PHP Summit API). Set to `"__all__"` as an explicit alias for "allow everything".
- **`allowed_relations`** — relations the client can expand or include. Auto-merged into the allowed field pool.
- **`expand_mappings`** — how to expand each relation (serializer, ORM strategy, etc.)

`Meta.fields` is **not needed** — `BaseModelSerializer` auto-sets `Meta.fields = "__all__"` via `__init_subclass__`. DRF discovers all model fields and declared fields automatically. The `allowed_fields` / `allowed_relations` system handles Summit-style filtering on top.

```python
from rest_framework import serializers
from base_api_utils.serializers.v2 import BaseModelSerializer
from base_api_utils.serializers.v2.expands import One2ManyExpandSerializer, Many2OneExpandSerializer


class OwnerSerializer(BaseModelSerializer):
    # No relations to expand — this is a leaf serializer
    allowed_fields = ["id", "name"]
    allowed_relations = []
    expand_mappings = {}

    class Meta:
        model = Owner


class MediaUploadSerializer(BaseModelSerializer):
    # 1. Fields the client can request via ?fields= (relations auto-merged from allowed_relations)
    allowed_fields = ["id", "url", "owner_id", "created", "modified"]

    # 2. Relations the client can expand (auto-merged into allowed fields)
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


class ItemSerializer(BaseModelSerializer):
    display_name = serializers.SerializerMethodField()  # Computed field
    expires_at = TimestampField(read_only=True, required=False)  # Calculated timestamp

    # Relations (media_upload, tags) auto-merged from allowed_relations — not listed here
    allowed_fields = [
        "id", "name", "quantity", "media_upload_id",
        "display_name", "expires_at", "created", "modified",
    ]
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

    def get_display_name(self, obj):
        return f"{obj.name} (x{obj.quantity})"
```

### Serializer Inheritance

All three attributes — `allowed_fields`, `allowed_relations`, and `expand_mappings` — are **merged across the inheritance chain** via MRO (method resolution order). Child classes only need to declare what they **add or override**, not redeclare the parent's values.

#### How merging works

`AbstractSerializer` walks the MRO in reverse (base → child) and collects values from every class:

| Attribute | Merge Strategy | Special Values |
|-----------|---------------|----------------|
| `allowed_fields` | Union — appends new fields, skips duplicates | `None` or omitted = allow all; `"__all__"` = explicit alias for allow all |
| `allowed_relations` | Union — appends new relations, skips duplicates | |
| `expand_mappings` | Dict merge — child keys override parent keys | `None` value **removes** an inherited mapping |

#### Example — extending a base serializer

```python
class BaseItemSerializer(BaseModelSerializer):
    allowed_fields = ["id", "name", "created", "modified"]
    allowed_relations = ["tags"]
    expand_mappings = {
        "tags": {
            "type": Many2OneExpandSerializer(),
            "serializer": TagSerializer,
            "source": "tags",
            "verify_relation": True,
            "orm": {"prefetch_related": ["tags"]},
        }
    }

    class Meta:
        model = Item


class ExtendedItemSerializer(BaseItemSerializer):
    # Only declare additions — parent's values are merged in automatically
    allowed_fields = ["quantity", "media_upload_id"]
    allowed_relations = ["media_upload"]
    expand_mappings = {
        "media_upload": {
            "type": One2ManyExpandSerializer(),
            "serializer": MediaUploadSerializer,
            "original_attribute": "media_upload_id",
            "source": "media_upload",
            "verify_relation": True,
            "orm": {"bulk_prefetch": "media_upload"},
        }
    }

    class Meta:
        model = Item

    # Effective result after merging:
    # allowed_fields = ["id", "name", "created", "modified", "quantity", "media_upload_id"]
    # allowed_relations = ["tags", "media_upload"]
    # expand_mappings = {"tags": {...}, "media_upload": {...}}
```

#### Removing inherited mappings

Set a key to `None` in `expand_mappings` to remove a parent's mapping:

```python
class SlimItemSerializer(BaseItemSerializer):
    expand_mappings = {
        "tags": None,  # removes parent's tags expansion
    }
    # Effective expand_mappings = {} (tags removed, nothing added)
```

This only works for `expand_mappings`. There is no mechanism to remove individual entries from inherited `allowed_fields` or `allowed_relations` — child classes can only add to those lists.

### Step 2: Choose the expansion type

| Type | Use When | Not Expanded | Expanded |
|------|----------|-------------|----------|
| `One2ManyExpandSerializer` | ForeignKey (many items point to one related object) | Shows `media_upload_id: 5` (removes the relation field, keeps the FK) | Shows `media_upload: {id: 5, url: "..."}` (removes the FK field) |
| `Many2OneExpandSerializer` | ManyToMany or reverse FK (one item has many related) | Shows `tags: [1, 2, 3]` (list of IDs) | Shows `tags: [{id: 1, name: "alpha"}, ...]` (list of objects) |

### Step 3: Add computed fields (SerializerMethodField)

DRF's `SerializerMethodField` works with the query parameter system. Declare the field, add it to `allowed_fields`, and implement the `get_<name>` method:

```python
class ItemSerializer(BaseModelSerializer):
    display_name = serializers.SerializerMethodField()

    allowed_fields = ["id", "name", "display_name", ...]  # ← include here

    class Meta:
        model = Item  # Meta.fields auto-set to '__all__' by BaseModelSerializer

    def get_display_name(self, obj):
        return f"{obj.name} (x{obj.quantity})"
```

The field behaves like any other field:
- **Default (no `?fields=`)** — included in the response
- **`?fields=id,display_name`** — included (explicitly requested)
- **`?fields=id,name`** — excluded (not requested)

No `expand_mappings` entry is needed — computed fields are not relations.

#### Custom Expansion Logic in SerializerMethodFields

For relations that require custom logic (filtering by context, conditional fetching, etc.), use `get_expand()` and `get_child_context()`:

```python
class ManagedMediaRequestModuleSerializer(BaseModelSerializer):
    media_upload = serializers.SerializerMethodField()
    allowed_relations = ['media_upload']

    def get_media_upload(self, obj):
        # Custom logic: filter by sponsor_id from context
        sponsor_id = self.context.get('sponsor_id')
        if not sponsor_id:
            return None

        media_upload = obj.get_media_uploads().filter(sponsor_id=sponsor_id).first()
        if not media_upload:
            return None

        # Check if expansion is requested using get_expand()
        if 'media_upload' not in self.get_expand():
            return media_upload.id

        # Build scoped context for child serializer using get_child_context()
        return SponsorMediaUploadSerializer(
            context=self.get_child_context('media_upload')
        ).to_representation(media_upload)
```

**Available methods:**
- `self.get_expand()` — returns list of relation names requested at this serializer's level (`["media_upload", "tags"]`)
- `self.get_child_context('attr')` — builds scoped context dict for child serializer, enabling nested `?fields=attr.id,attr.url`, `?expand=attr.nested`, and `?relations=attr.nested`

**⚠️ Important:** Always use `get_child_context()` when manually instantiating child serializers. Using `self.context` directly breaks nested query parameter scoping.

### Step 4: Add queryset annotation fields

Django queryset annotations (`.annotate()`) add computed columns at the database level — aggregates, conditional expressions, subqueries, etc. These work with the query parameter system because annotations become attributes on model instances, which DRF fields can read directly.

#### How it works

The annotation is applied in the ViewSet's `get_queryset()`. Since `ExpandQuerysetOptimizationMixin.get_queryset()` calls `super().get_queryset()` first and then chains `.select_related()` / `.prefetch_related()` on top, annotations added by the ViewSet survive the mixin's optimization — the mixin never replaces the queryset, it only appends to it.

```
ViewSet.get_queryset()
  → calls super().get_queryset()                    # ExpandQuerysetOptimizationMixin
    → calls super().get_queryset()                  # BaseView — returns self.queryset
    → chains .select_related() / .prefetch_related()
  → chains .annotate(tag_count=Count("tags"), ...)  # your annotations on top
```

#### IntegerField — Count annotation

```python
# views.py — add the annotation
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    def get_queryset(self):
        return super().get_queryset().annotate(tag_count=Count("tags"))

# serializers.py — expose via a direct DRF field
class ItemSerializer(BaseModelSerializer):
    tag_count = serializers.IntegerField(read_only=True)  # reads obj.tag_count

    allowed_fields = [..., "tag_count"]  # ← include here (no Meta.fields needed)
```

The DRF `IntegerField` reads the `tag_count` attribute from the model instance — which is the annotation value set by Django's `.annotate()`. No `SerializerMethodField` or `get_tag_count` method needed.

#### BooleanField — Q expression annotation

```python
# views.py — Q() produces a boolean expression
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    def get_queryset(self):
        return super().get_queryset().annotate(
            tag_count=Count("tags"),
            has_media=Q(media_upload_id__isnull=False),  # True when media_upload_id is not null
        )

# serializers.py — expose via BooleanField
class ItemSerializer(BaseModelSerializer):
    has_media = serializers.BooleanField(read_only=True)  # reads obj.has_media

    allowed_fields = [..., "has_media"]  # no Meta.fields needed
```

`Q()` expressions used as annotations produce boolean values. The `BooleanField` reads it directly.

#### Field filtering behavior

Annotation fields behave identically to model fields and `SerializerMethodField` for field filtering:

- **Default (no `?fields=`)** — included (it's in `allowed_fields`)
- **`?fields=id,tag_count`** — included (explicitly requested)
- **`?fields=id,name`** — excluded (not requested)
- **Works alongside expansion** — `?fields=id,tag_count&expand=media_upload` returns both the annotation and the expanded relation

#### When to use annotations vs SerializerMethodField

| Approach | Use When | Performance |
|----------|----------|-------------|
| Queryset annotation | Aggregates (`Count`, `Sum`, `Avg`), conditional expressions (`Q`, `Case`/`When`), subqueries | Computed in SQL — single query, no N+1 |
| `SerializerMethodField` | String formatting, logic that depends on multiple fields, non-database computations | Computed in Python — runs per object |

**Prefer annotations** for anything the database can compute — they scale to any result set size without additional queries. Use `SerializerMethodField` for presentation logic that doesn't involve database aggregation.

### Step 5: Custom field types (TimestampField)

`BaseModelSerializer` declares `created` and `modified` as `TimestampField` — a custom DRF field that converts Python `datetime` objects to Unix epoch integers on output and accepts epoch integers on input:

```python
# base_api_utils/serializers/timestamp_field.py
class TimestampField(serializers.Field):
    def to_internal_value(self, data):
        return datetime.fromtimestamp(int(data), tz=timezone.utc)

    def to_representation(self, value):
        return int(time.mktime(value.timetuple()))
```

```python
# base_api_utils/serializers/v2/base_model_serializer.py
class BaseModelSerializer(AbstractSerializer, serializers.ModelSerializer):
    id = serializers.ReadOnlyField(source="pk")
    created = TimestampField(read_only=True, required=False)
    modified = TimestampField(read_only=True, required=False)
```

All serializers inheriting from `BaseModelSerializer` automatically serialize `created` and `modified` as epoch integers (e.g., `1741132800`) instead of ISO 8601 strings. This matches the original PHP Summit API's `datetime_epoch` type coercion.

#### Using TimestampField with calculated model properties

`TimestampField` works with any model attribute that returns a `datetime`. For computed values, declare a `@property` on the model and a `TimestampField` on the serializer:

```python
# models.py — computed property returns a datetime
class Item(models.Model):
    created = models.DateTimeField(auto_now_add=True)

    @property
    def expires_at(self):
        from datetime import timedelta
        return self.created + timedelta(days=30)

# serializers.py — TimestampField reads the property, outputs epoch int
class ItemSerializer(BaseModelSerializer):
    expires_at = TimestampField(read_only=True, required=False)

    allowed_fields = [..., "expires_at"]  # ← include here (no Meta.fields needed)
```

The field behaves like any other field for query parameter filtering:
- **Default (no `?fields=`)** — included in the response as an epoch integer
- **`?fields=id,expires_at`** — included (explicitly requested)
- **`?fields=id,name`** — excluded (not requested)

No `expand_mappings` entry is needed — timestamp fields are not relations.

#### Comparison with PHP's type coercion

The PHP original handles this via `$array_mappings` type suffixes:

```php
protected static $array_mappings = [
    'StartDate' => 'start_date:datetime_epoch',  // ← coercion declared inline
    'Created'   => 'created:datetime_epoch',
];
```

The DRF port achieves the same result by declaring `TimestampField` at the serializer base class level. The PHP approach is more concise (one declaration per field), while the DRF approach uses the standard DRF field system, making it compatible with drf-spectacular schema generation (via `@extend_schema_field`).

### Step 6: Configure ORM optimization

The `"orm"` key in `expand_mappings` tells `ExpandQuerysetOptimizationMixin` how to fetch related data efficiently. There are three strategies, each solving a different problem.

#### `select_related` — SQL JOIN (single query)

```python
"orm": {"select_related": ["owner"]}
```

**What it does:** Django adds a `JOIN` to the main query, fetching the parent and the related object in a single SQL statement.

**When to use:** Real Django `ForeignKey` or `OneToOneField` relations — where one row in the parent table points to exactly one row in the related table.

**How the mixin uses it:** When the client sends `?expand=owner`, the mixin calls `queryset.select_related("owner")` before executing the query. For nested expansions like `?expand=media_upload.owner`, the mixin builds the Django ORM path `media_upload__owner` and calls `queryset.select_related("media_upload__owner")`.

**SQL result (conceptual):**

```sql
-- Without select_related: 1 query per item (N+1)
SELECT * FROM media_upload WHERE id = 1;
SELECT * FROM owner WHERE id = 3;  -- per media_upload

-- With select_related("owner"): single query
SELECT media_upload.*, owner.*
FROM media_upload
LEFT JOIN owner ON media_upload.owner_id = owner.id;
```

**Example:** `MediaUploadSerializer` expanding its `owner` FK:

```python
expand_mappings = {
    "owner": {
        "type": One2ManyExpandSerializer(),
        "serializer": OwnerSerializer,
        "original_attribute": "owner_id",
        "source": "owner",
        "verify_relation": True,
        "orm": {"select_related": ["owner"]},
    }
}
```

#### `prefetch_related` — Separate query (two queries total)

```python
"orm": {"prefetch_related": ["tags"]}
```

**What it does:** Django runs a second query to fetch all related objects, then stitches them together in Python. Unlike `select_related`, this works for relationships that return multiple objects per parent.

**When to use:** `ManyToManyField`, reverse `ForeignKey` (one parent has many children), or any relation where `select_related` would produce duplicate parent rows.

**How the mixin uses it:** When the client sends `?expand=tags`, the mixin calls `queryset.prefetch_related("tags")`. This is triggered even without `?expand=` — if the field is included in the response (even as IDs), the mixin prefetches to avoid N+1 when the serializer accesses `item.tags.all()`.

**SQL result (conceptual):**

```sql
-- Without prefetch_related: 1 query per item (N+1)
SELECT * FROM item;
SELECT tag.* FROM item_tags JOIN tag ON ... WHERE item_id = 1;  -- per item
SELECT tag.* FROM item_tags JOIN tag ON ... WHERE item_id = 2;  -- per item

-- With prefetch_related("tags"): exactly 2 queries regardless of item count
SELECT * FROM item;
SELECT tag.*, item_tags.item_id
FROM item_tags JOIN tag ON ...
WHERE item_id IN (1, 2, 3, ...);
```

**Example:** `ItemSerializer` expanding its `tags` M2M:

```python
expand_mappings = {
    "tags": {
        "type": Many2OneExpandSerializer(),
        "serializer": TagSerializer,
        "source": "tags",
        "verify_relation": True,
        "orm": {"prefetch_related": ["tags"]},
    }
}
```

#### `bulk_prefetch` — Custom ViewSet hook, driven by `ExpandQuerysetOptimizationMixin`

```python
"orm": {"bulk_prefetch": "media_upload"}
```

**What it does:** Instead of Django ORM optimization on the queryset, `ExpandQuerysetOptimizationMixin` calls a custom method `bulk_prefetch__<name>` on the ViewSet **after** the queryset executes. The ViewSet method receives the list of fetched objects and runs its own query to batch-load related data.

**When to use:** The relation is **not a real Django FK** — it's a computed property backed by a plain `IntegerField` (or any other non-ORM pattern). Django can't `select_related` or `prefetch_related` on these because the ORM doesn't know about the relationship.

**The relationship between the three pieces:**

The `bulk_prefetch` pattern involves three components that work together:

1. **Serializer** (`expand_mappings`) — declares `"orm": {"bulk_prefetch": "media_upload"}`. This is just a declaration — the serializer doesn't execute anything. It tells the mixin *what* needs to be bulk-loaded.

2. **`ExpandQuerysetOptimizationMixin`** (on the ViewSet) — the orchestrator. It does three things:
   - **`_collect_orm_recursive()`** — walks the serializer's `expand_mappings`, finds `bulk_prefetch` entries, and collects them into a hooks list with their subtrees
   - **`list()`** — overrides DRF's list action. After the queryset executes and pagination happens, it calls `_run_bulk_hooks(items)`
   - **`_run_bulk_hooks()`** — iterates the collected hooks and calls `self.bulk_prefetch__<name>(items, expand_subtree, fields_subtree, relations_subtree)` on the ViewSet

3. **ViewSet** (`bulk_prefetch__<name>` method) — the implementation. You write the actual loading logic: collect IDs, run a query, cache results on model instances. Without `ExpandQuerysetOptimizationMixin` on the ViewSet, this method would never be called.

**The full flow:**

```
1. Client sends: GET /api/items/?expand=media_upload

2. ExpandQuerysetOptimizationMixin.get_queryset()
   → _collect_orm_recursive() walks ItemSerializer.expand_mappings
   → Finds "orm": {"bulk_prefetch": "media_upload"}
   → Does NOT call select_related or prefetch_related (can't — not a real FK)
   → Returns the queryset unmodified for this relation

3. ExpandQuerysetOptimizationMixin.list()
   → Executes queryset: SELECT * FROM item
   → Paginates results
   → Calls _run_bulk_hooks(items)

4. _run_bulk_hooks()
   → Re-collects hooks via _collect_orm_recursive()
   → Finds bulk_prefetch hook "media_upload"
   → Calls self.bulk_prefetch__media_upload(items, expand_subtree, fields_subtree, relations_subtree)

5. ItemViewSet.bulk_prefetch__media_upload() runs:
   → Collects all media_upload_ids from items
   → Single query: SELECT * FROM media_upload WHERE id IN (1, 3, 7, ...)
   → Caches: item._prefetched_media_upload = uploads[item.media_upload_id]

6. Serializer accesses item.media_upload → @property returns cached value (no query)
```

**Why not just use a ForeignKey?** In the original Summit API, `Item.media_upload_id` is a plain integer rather than a Django FK because the related object might live in a different database, be managed by a different service, or need custom loading logic that doesn't fit Django's FK constraints.

**Example — all three pieces together:**

```python
# 1. serializers.py — declares the intent
expand_mappings = {
    "media_upload": {
        "type": One2ManyExpandSerializer(),
        "serializer": MediaUploadSerializer,
        "original_attribute": "media_upload_id",
        "source": "media_upload",
        "verify_relation": True,
        "orm": {"bulk_prefetch": "media_upload"},  # ← tells the mixin to use a hook
    }
}

# 2. views.py — the mixin orchestrates, the ViewSet implements the hook
class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):  # ← mixin required
    queryset = Item.objects.all().order_by("id")
    serializer_class = ItemSerializer

    def bulk_prefetch__media_upload(self, items, expand_subtree, fields_subtree, relations_subtree):
        """Called by ExpandQuerysetOptimizationMixin._run_bulk_hooks() when ?expand=media_upload."""
        qs = MediaUpload.objects.all()
        # Nested optimization: if client also expands media_upload.owner, join it in
        if has_key(expand_subtree, "owner") and has_key(relations_subtree, "owner"):
            qs = qs.select_related("owner")
        ids = {i.media_upload_id for i in items if getattr(i, "media_upload_id", None)}
        uploads = {m.id: m for m in qs.filter(id__in=ids)}
        for i in items:
            i._prefetched_media_upload = uploads.get(i.media_upload_id)

# 3. models.py — the property checks the cache first
class Item(models.Model):
    media_upload_id = models.IntegerField(null=True, blank=True)

    @property
    def media_upload(self):
        if hasattr(self, "_prefetched_media_upload"):
            return self._prefetched_media_upload  # ← cached by the hook, no query
        if not self.media_upload_id:
            return None
        return MediaUpload.objects.filter(pk=self.media_upload_id).first()  # ← fallback for single-object access
```

#### Choosing the right strategy

| Relation Type | Model Field | Strategy | Queries |
|---------------|-------------|----------|---------|
| FK / OneToOne (real Django relation) | `models.ForeignKey(Owner)` | `select_related` | 1 (SQL JOIN) |
| M2M / reverse FK | `models.ManyToManyField(Tag)` | `prefetch_related` | 2 (main + related) |
| Computed property (non-ORM FK) | `models.IntegerField()` + `@property` | `bulk_prefetch` | 2 (main + hook query) |

All three strategies are **conditional** — the mixin only applies them when the client actually requests the expansion via `?expand=`. Without `?expand=`, no joins or extra queries are added (except `prefetch_related` which also fires when the field is included as IDs in the response).

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
    "display_name": "Widget A (x2)",
    "expires_at": 1743724800,
    "created": 1741132800,
    "modified": 1741132800
  }
]
```

Relations shown as IDs. All allowed_fields included (including computed fields like `display_name` and `expires_at`). Timestamp fields (`created`, `modified`, `expires_at`) are serialized as Unix epoch integers via `TimestampField`.

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
      "created": 1741132800,
      "modified": 1741132800
    },
    "tags": [1, 2],
    "expires_at": 1743724800,
    "created": 1741132800,
    "modified": 1741132800
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
    "expires_at": 1743724800,
    "created": 1741132800,
    "modified": 1741132800
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
      "created": 1741132800,
      "modified": 1741132800
    },
    "tags": [1, 2],
    "expires_at": 1743724800,
    "created": 1741132800,
    "modified": 1741132800
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

### Control relation visibility with ?relations=

When `verify_relation: True` is set in `expand_mappings`, the `?relations=` parameter controls which relation fields appear in the response at all. Relations not listed are **removed entirely** — both the expanded object and the FK/ID field. If `?relations=` is omitted entirely, all `allowed_relations` are included by default.

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
    "created": "...",
    "modified": "..."
  }
]
```

`media_upload` is expanded (listed in both `expand` and `relations`). `tags` is **removed entirely** — not in `relations`, so neither the ID list nor the expanded objects appear.

### Block nested relations with `.none`

When expanding a relation, its child serializer fills in its own `allowed_relations` by default — so `?expand=media_upload,media_upload.owner` works without listing `owner` in `?relations=`. To expand a parent but **block all its nested relations**, use the `.none` suffix:

```
GET /api/items/?expand=media_upload,media_upload.owner&relations=media_upload.none
```
```json
[
  {
    "id": 1,
    "media_upload": {
      "id": 1,
      "url": "https://example.com/a.png",
      "owner_id": 3,
      "created": "...",
      "modified": "..."
    },
    "tags": [1, 2],
    "...": "..."
  }
]
```

Despite requesting `?expand=media_upload.owner`, the `owner` is NOT expanded — `relations=media_upload.none` blocks all nested relations within `media_upload`. The `owner_id` field remains visible instead.

**How it works:** `parse_tree("media_upload.none")` produces `{"media_upload": {"none": {}}}`. The root-level `normalize_none` only clears the tree when `"none"` appears at root level (e.g., `?relations=none`). When `"none"` is nested, it's preserved. The child serializer receives `relations_tree = {"none": {}}` — a truthy dict that prevents `_ensure_defaults` from filling in the child's `allowed_relations`. Since `"none"` isn't a real relation name, no nested expansion is permitted.

**Contrast with `?relations=media_upload`** (no `.none`): the child serializer receives `relations_tree = {}` (empty dict), which is falsy, so `_ensure_defaults` fills in `allowed_relations = ["owner"]` — allowing `owner` to expand.

The same `.none` pattern works with `?fields=` to block all nested fields:

```
GET /api/items/?fields=id,media_upload.none&expand=media_upload&relations=media_upload
```

This expands `media_upload` but strips all its fields — the child serializer's `_filter_local_fields` sees only `{"none": {}}` in `fields_tree`, and since `"none"` matches no real field names, everything is filtered out.

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

## Comparison with Original Summit API (PHP/Laravel)

This DRF implementation is a port of the query parameter system from the [OpenStack Summit API](https://github.com/OpenStackweb/summit-api/tree/main/app/ModelSerializers), originally written in PHP with Laravel/Doctrine. This section compares both implementations based on the actual source code.

### Serializer Declaration

**Original (PHP)** — three concerns, cleanly split:

```php
// 1. Field mapping: model getter → JSON key + type coercion
protected static $array_mappings = [
    'Title'      => 'title:json_string',
    'LocationId' => 'location_id:json_int',
    'StartDate'  => 'start_date:datetime_epoch',
];

// 2. Allowed fields / relations — flat lists
protected static $allowed_fields = ['id', 'title', 'location_id', ...];
protected static $allowed_relations = ['sponsors', 'tags', 'location', ...];

// 3. Expand mappings — per relation
protected static $expand_mappings = [
    'ticket_types' => [
        'type'   => Many2OneExpandSerializer::class,
        'getter' => 'getTicketTypes',
    ],
];
```

**DRF port (Python)** — similar structure, streamlined by auto-merging relations and auto-setting `Meta.fields`:

```python
allowed_fields = ["id", "name", "media_upload_id"]  # relations auto-merged from allowed_relations
allowed_relations = ["media_upload", "tags"]
expand_mappings = {
    "media_upload": {
        "type": One2ManyExpandSerializer(),
        "serializer": MediaUploadSerializer,       # explicit (PHP uses registry)
        "original_attribute": "media_upload_id",
        "source": "media_upload",
        "verify_relation": True,
        "orm": {"bulk_prefetch": "media_upload"},   # no PHP equivalent
    }
}

class Meta:
    model = Item  # Meta.fields auto-set to '__all__' by BaseModelSerializer
```

Key differences:

- PHP has `$array_mappings` that handle both field extraction AND type coercion (`json_int`, `datetime_epoch`, etc.). DRF handles this natively via its field system, so the port doesn't need this layer.
- PHP uses a **SerializerRegistry** singleton — you never specify the serializer class in `expand_mappings`. The registry auto-resolves `Entity → Serializer` by class name. The DRF port requires explicitly passing `"serializer": MediaUploadSerializer`. More verbose, but also more transparent.
- **PHP doesn't list allowed fields by default** — omitting `$allowed_fields` means "allow all". The DRF port matches this: `allowed_fields = None` (or omitted) allows all fields. `allowed_fields = "__all__"` is an explicit alias.
- **Relations don't need to be listed in `allowed_fields`** — `BaseModelSerializer` auto-merges `allowed_relations` into the allowed field pool, matching PHP's behavior where relations and fields are separate declarations.
- **`Meta.fields` is auto-set** — `BaseModelSerializer.__init_subclass__` injects `Meta.fields = "__all__"` on child classes, so only `Meta.model` is needed. DRF discovers all model fields and declared fields automatically.
- PHP's `expand_mappings` include a `getter` string (e.g., `'getTicketTypes'`) which is called via `$entity->{$this->getter}()`. The DRF port uses DRF's built-in field source resolution instead of magic string dispatch.
- The `"orm"` key in the DRF port has no PHP equivalent — Doctrine handles lazy loading differently (no `select_related`/`prefetch_related` dance needed).

### Expand Serializers

**Original One2ManyExpandSerializer (PHP):**

```php
public function serialize($entity, array $values, string $expand, ...): array
{
    $res = $entity->{$this->has}();          // Check if relation exists
    if (boolval($res) && $testRuleRes) {
        $values = $this->unsetOriginalAttribute($values);    // Remove _id
        $values[$this->attribute] = SerializerRegistry::getInstance()
            ->getSerializer($entity->{$this->getter}(), $this->serializer_type)
            ->serialize(
                AbstractSerializer::filterExpandByPrefix($expand, $this->attribute),
                AbstractSerializer::filterFieldsByPrefix($fields, $this->attribute),
                AbstractSerializer::filterFieldsByPrefix($relations, $this->attribute),
                $params
            );
    }
    return $values;
}
```

**Original Many2OneExpandSerializer (PHP):**

```php
public function serialize($entity, array $values, string $expand, ...): array
{
    $values = $this->unsetOriginalAttribute($values);
    if ($should_verify_relation && !in_array($this->attribute, $relations)) return $values;

    $childExpand    = AbstractSerializer::filterExpandByPrefix($expand, $this->attribute);
    $childFields    = AbstractSerializer::filterFieldsByPrefix($fields, $this->attribute);
    $childRelations = AbstractSerializer::filterFieldsByPrefix($relations, $this->attribute);

    $res = [];
    foreach ($entity->{$this->getter}() as $item) {
        $res[] = $registry->getSerializer($item, $this->serializer_type)
            ->serialize($childExpand, $childFields, $childRelations, $params);
    }
    $values[$this->attribute] = $res;
    return $values;
}
```

The PHP version is remarkably clean: call a `has` method, unset the FK ID, get the entity via a getter, look up the serializer via the registry, filter expand/fields/relations by dot prefix, and recurse. Three functions, stateless, string-based prefix filtering.

The DRF port does the same thing conceptually but has to work around DRF's context system — the `_own_context` / `_original_context` pattern exists solely because DRF's `field.bind()` overwrites child context. PHP doesn't have this problem because each serializer is instantiated fresh with its own scope.

### Recursive Expansion

**PHP** — string manipulation:

```php
// ?expand=media_upload,media_upload.owner
// filterExpandByPrefix("media_upload") → "owner"
// filterFieldsByPrefix("media_upload") → child fields
```

Flat CSV strings, filtered by dot-prefix, passed down recursively. Simple and stateless.

**DRF port** — tree data structures:

```python
# parse_tree("media_upload,media_upload.owner") → {"media_upload": {"owner": {}}}
# subtree(tree, "media_upload") → {"owner": {}}
```

Parses upfront into nested dicts, then extracts subtrees. More structured but introduces the `None` vs `{}` ambiguity that required documentation.

### Custom Serialization Logic

The PHP original allows inline custom logic in `serialize()` overrides. For example, `SummitSerializer` handles computed fields like `time_zone` (with timezone offsets calculation), `page_url` (URL assembly from config), and `payment_profiles` (conditional default profile injection) — all inside the serializer's `serialize()` method:

```php
public function serialize($expand = null, array $fields = [], array $relations = [], array $params = [])
{
    $values = parent::serialize($expand, $fields, $relations, $params);

    if (in_array('time_zone', $fields)) {
        // complex timezone offset calculation
        $values['time_zone'] = $time_zone_info;
    }

    if (in_array('payment_profiles', $relations)) {
        // serialize profiles, inject defaults if missing
        $values['payment_profiles'] = $payment_profiles;
    }

    // Inline expand handling for special cases
    if (!empty($expand)) {
        foreach (explode(',', $expand) as $relation) {
            switch ($relation) {
                case 'schedule':
                    // scope check, then serialize event_types, tracks, schedule, etc.
                    break;
                case 'locations':
                    if (in_array('locations', $relations)) {
                        // serialize with conditional expand override
                    }
                    break;
            }
        }
    }
    return $values;
}
```

In DRF, these patterns require custom fields, model properties, or view-level mixins — the serializer `serialize()` method is not typically overridden directly.

### Where PHP Wins

| Aspect | Why |
|--------|-----|
| **No context corruption** | Each serializer is a fresh object. No `field.bind()` overwriting child state. The `_own_context` workaround does not exist in the original. |
| **SerializerRegistry** | Entity→Serializer resolved automatically. No need to import and declare serializer classes in `expand_mappings`. |
| **`has` / `getter` pattern** | Simple string-based method dispatch. The serializer never touches the model directly — it asks the model if a relation exists, then gets it. Clean separation. |
| **Type coercion in mappings** | `'StartDate' => 'start_date:datetime_epoch'` — single declaration handles naming AND formatting. DRF does this implicitly via field types, but the PHP approach is more explicit about intent. |
| **No ORM optimization layer** | Doctrine lazy-loads. No `select_related`/`prefetch_related` or `bulk_prefetch` hooks needed. Simpler code, though at a potential performance cost. |
| **Custom `serialize()` overrides** | `SummitSerializer` handles computed fields (`time_zone`, `page_url`) and special relations (`schedule`, `locations`) with inline logic. In DRF, these patterns require custom fields, properties, or mixins. |

### Where DRF Wins

| Aspect | Why |
|--------|-----|
| **Explicit ORM optimization** | `select_related`/`prefetch_related` annotations prevent N+1 at the framework level. PHP defers to ORM caching and lazy loading, which works until it doesn't. |
| **Structured trees** | Nested dicts are easier to traverse programmatically than repeated string parsing with `filterExpandByPrefix`. |
| **DRF ecosystem** | Pagination, throttling, permissions, schema generation (drf-spectacular) come free. |
| **No SerializerRegistry** | The PHP registry is powerful but also a large singleton that maps every entity in the system. It's a maintenance bottleneck. |
| **Type safety** | Python type hints + dataclass `ExpandMapping` vs PHP arrays with string keys. Typos in PHP `expand_mappings` are silent failures. |

### Assessment

The original PHP implementation is **architecturally cleaner** for this specific feature. The core flow is:

```
serialize() → _expand() → expandSerializer.serialize() → recursion
```

Three functions, stateless, string-based prefix filtering, no context corruption workarounds. The PHP version doesn't fight its framework — it builds a serialization system from scratch, so there's no impedance mismatch.

The DRF port inherits DRF's strengths (validation, schema, permissions) but pays a tax for them. The `_own_context` workaround, the `_ensure_defaults` initialization dance, and the `_filter_local_fields` logic all exist because DRF was designed for simple flat serializers, not recursive tree-controlled expansion. The port grafts a fundamentally different serialization model onto DRF, and the seams show.

That said, the DRF port adds real value that the PHP version lacks: **explicit ORM optimization control**. The `bulk_prefetch` pattern and the `ExpandQuerysetOptimizationMixin` prevent N+1 queries by design — the PHP version trusts Doctrine's lazy loading, which can silently degrade on large datasets. The DRF port makes you declare optimization strategy upfront, which is more work but prevents performance surprises.

**Bottom line:** The PHP design is simpler because it owns the full serialization stack. The DRF port is more complex because it coexists with DRF's opinions about how serializers should work. Neither approach is wrong — they optimize for different constraints.

## Consequences

### Benefits
- Clients fetch only what they need — smaller payloads, fewer round trips
- ORM optimization is automatic — no manual `select_related` per endpoint
- Recursive: the same pattern works at any nesting depth
- `?relations=` acts as a server-side gate — relations not listed are removed entirely (both expanded objects and FK/ID fields). Even `?expand=secret_relation` won't work unless `allowed_relations` permits it

### Trade-offs
- Serializer setup has three declarations (`allowed_fields`, `allowed_relations`, `expand_mappings`) that must stay in sync — though relations are auto-merged into allowed fields and `Meta.fields` is auto-set, reducing duplication
- The tree data structure (`None` vs `{}`) has subtle semantics — see the codebase's `_ensure_defaults` and `_child_tree` for how defaults are resolved
- DRF's `field.bind()` replaces child serializer context with the parent's, requiring the `_own_context` / `_original_context` workaround to preserve each serializer's own trees
