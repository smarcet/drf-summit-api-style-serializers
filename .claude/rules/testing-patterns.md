## Testing Query Parameters

**Helper methods for testing Summit-style query parameter endpoints.**

### Pattern

Create reusable helpers in test case setUp:

```python
class QueryParamTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _get_items(self, params=""):
        """Fetch list endpoint with optional query params."""
        resp = self.client.get(f"/api/items/{params}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _get_item(self, item_id, params=""):
        """Get specific item from list by id."""
        rows = self._get_items(params)
        return next(r for r in rows if r["id"] == item_id)
```

### Usage

```python
def test_fields_subset(self):
    """Test ?fields=id,name returns only requested fields."""
    row = self._get_item(self.i1.id, "?fields=id,name")
    self.assertEqual(row["id"], self.i1.id)
    self.assertEqual(row["name"], "Widget A")
    self.assertNotIn("quantity", row)
```

### Benefits

- Consistent error checking (status code assertions)
- Reduce boilerplate in each test
- Easy to test both list and detail behavior
- Clear separation of data fetch vs assertions
