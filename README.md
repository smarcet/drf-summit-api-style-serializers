# Summit-Style DRF Query Parameters Sample (v4.3)

Django REST Framework sample demonstrating client-controlled field selection, relation expansion, and ORM optimization via `?fields=`, `?expand=`, and `?relations=` query parameters.

## Quick Start

```bash
git clone <repo-url>
cd django_drf_summit_style_sample_v4_3
chmod +x start.sh
./start.sh
```

`start.sh` creates a virtual environment, installs dependencies, runs migrations, seeds sample data, runs the test suite, and starts the dev server at `http://127.0.0.1:8000`.

## What `start.sh` Does

1. Creates a Python virtual environment (`.venv`)
2. Installs dependencies from `requirements.txt`
3. Runs `makemigrations` and `migrate` (SQLite)
4. Seeds the database with sample data (`Owner`, `MediaUpload`, `Tag`, `Item`)
5. Runs the test suite
6. Starts the development server

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/items/` | Items with FK-like `media_upload` and M2M `tags` |
| `/api/media-uploads/` | Media uploads with FK `owner` |
| `/api/tags/` | Tags |
| `/api/owners/` | Owners |
| `/api/docs/` | Swagger UI (interactive API docs) |
| `/api/schema/` | OpenAPI schema |

## Query Parameters

### `?fields=` — Select which fields to return

```
GET /api/items/?fields=id,name
```

Dot notation filters nested fields when combined with `?expand=`:

```
GET /api/items/?fields=id,media_upload.id,media_upload.url&expand=media_upload
```

### `?expand=` — Expand relations into full objects

```
GET /api/items/?expand=media_upload        # FK as object
GET /api/items/?expand=tags                # M2M as list of objects
GET /api/items/?expand=media_upload,media_upload.owner  # Nested expansion
```

### `?relations=` — Control which relations appear in the response

```
GET /api/items/?relations=media_upload     # Only media_upload; tags removed
GET /api/items/?relations=none             # All relations removed
```

### `none` sentinel — Block fields or relations at any nesting level

```
?relations=none                            # Remove all relation fields
?fields=none                               # Remove all non-relation fields
?relations=media_upload.none               # Expand media_upload, block its nested relations
?fields=tags.none&expand=tags              # Expand tags, strip all tag fields
```

### `?order=` — Sort results

```
GET /api/items/?order=name                 # Ascending
GET /api/items/?order=-name                # Descending
GET /api/items/?order=-quantity,name        # Multiple fields
```

## Running Tests

```bash
source .venv/bin/activate
python manage.py test
```

## Architecture

See [ADR-001](adr/001-summit-style-query-parameters.md) for full documentation of the query parameter system, serializer setup, ORM optimization strategies, and comparison with the original PHP Summit API.
