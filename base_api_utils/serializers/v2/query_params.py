def parse_csv(value):
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_tree(csv):
    tree = {}
    for path in parse_csv(csv):
        node = tree
        for part in path.split("."):
            node = node.setdefault(part, {})
    return tree


def subtree(tree, key):
    if tree is None:
        return None
    return tree.get(key, {})


def has_key(tree, key):
    return tree is not None and key in tree


def should_expand(expand_tree, relations_tree, attr, verify_relation):
    if not has_key(expand_tree, attr):
        return False
    if verify_relation and not has_key(relations_tree, attr):
        return False
    return True


def normalize_none(tree):
    """No-op — the ``none`` keyword is a natural sentinel.

    ``{"none": {}}`` is truthy, so ``_ensure_defaults`` won't fill in
    defaults.  ``"none"`` matches no real field or relation name, so
    ``_filter_local_fields`` and ``should_expand`` exclude everything.

    Works at any level:
    - ``?relations=none`` → blocks all expansion at the current serializer
    - ``?relations=media_upload.none`` → blocks all nested expansion within
      ``media_upload`` (child serializer sees ``{"none": {}}``)
    - ``?fields=none`` → strips all non-relation fields
    """
    return tree


def parse_request_trees(request):
    qp = request.query_params
    expand_raw = qp.get("expand") or qp.get("expands")
    fields_raw = qp.get("fields")
    relations_raw = qp.get("relations")
    expand_tree = normalize_none(parse_tree(expand_raw))
    fields_tree = normalize_none(parse_tree(fields_raw)) if fields_raw else None
    relations_tree = (
        normalize_none(parse_tree(relations_raw)) if relations_raw else None
    )
    return expand_tree, fields_tree, relations_tree
