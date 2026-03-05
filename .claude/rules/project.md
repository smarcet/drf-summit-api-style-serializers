# Project: Summit-Style DRF Sample (v4.3)

**Last Updated:** 2026-03-05

## Overview

Django REST Framework sample demonstrating advanced serializer patterns for nested field expansion and query optimization. Showcases recursive relationship expansion with fine-grained control over included fields and relations.

## Technology Stack

- **Language:** Python 3.12+
- **Framework:** Django 4.2+, Django REST Framework 3.14+
- **API Documentation:** drf-spectacular 0.27+
- **Database:** SQLite (development)
- **Package Manager:** pip + venv (migrate to uv recommended)
- **Testing:** Django TestCase with APIClient

## Directory Structure

```
.
├── api/                      # Main API app
│   ├── models.py            # Item, MediaUpload, Tag, Owner models
│   ├── views.py             # ViewSet implementations
│   ├── serializers.py       # Serializer implementations
│   ├── urls.py              # API routing
│   ├── tests/               # Integration tests
│   └── management/commands/ # Custom management commands (seed)
├── base_api_utils/          # Reusable base classes
│   ├── views.py             # BaseView, ExpandQuerysetOptimizationMixin
│   └── serializers/v2/      # BaseModelSerializer, expand utilities
├── summitstyle/             # Django project configuration
│   └── settings.py
├── manage.py
├── requirements.txt
└── start.sh
```

## Key Files

- **Configuration:** `summitstyle/settings.py`
- **Entry Point:** `manage.py`
- **Dependencies:** `requirements.txt`
- **Tests:** `api/tests/test_query_params.py` (main suite), `api/tests/test_recursive_expand.py`
- **Setup Script:** `start.sh`

## Development Commands

| Task | Command |
|------|---------|
| Install | `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| Migrate | `python manage.py migrate` |
| Seed Data | `python manage.py seed` |
| Run Tests | `python manage.py test` |
| Dev Server | `python manage.py runserver` |
| API Docs | Visit `http://localhost:8000/api/docs/` after server starts |

**Recommended:** Migrate to `uv` for faster dependency management:
```bash
uv pip install -r requirements.txt
uv run python manage.py test
```

## Architecture Notes

**Summit-Style API Pattern:**
- **BaseModelSerializer** declares `allowed_fields`, `allowed_relations`, and `expand_mappings`
- **Query Parameters:** `?expand=relation,relation.nested&fields=id,name&relations=relation`
- **Auto-Optimization:** `ExpandQuerysetOptimizationMixin` automatically applies `select_related`/`prefetch_related` based on `expand_mappings`
- **Bulk Prefetch:** Custom `bulk_prefetch__<name>` methods in ViewSets for computed relations (e.g., `Item.media_upload` via property)
- **Nested Expansion:** Supports recursive expansion like `?expand=media_upload.owner` with proper ORM optimization

**Models:**
- `Owner` → `MediaUpload` (ForeignKey) → `Item` (computed property via `media_upload_id`)
- `Item` ↔ `Tag` (ManyToMany)
