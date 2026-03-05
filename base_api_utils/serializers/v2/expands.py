import copy
from dataclasses import dataclass

from rest_framework import serializers

from .query_params import should_expand, subtree


@dataclass(frozen=True)
class ExpandMapping:
    attribute: str
    serializer: type
    original_attribute: str | None = None
    source: str | None = None
    verify_relation: bool = False

    @property
    def source_kwargs(self) -> dict:
        """DRF asserts if source == field_name; only pass source when different."""
        src = self.source or self.attribute
        return {} if src == self.attribute else {"source": src}

    @property
    def fk_field(self) -> str:
        return self.original_attribute or f"{self.attribute}_id"


def _child_tree(tree, attr):
    """Extract the branch for *attr*, or None if *tree* doesn't mention it.

    None means "the parent didn't constrain this — let the child use its own
    defaults".  An empty dict means "the parent mentioned it but with no
    further nesting".
    """
    if tree is None or attr not in tree:
        return None
    return copy.deepcopy(subtree(tree, attr))


def _child_context(context, attr):
    """Build an isolated context for a child serializer being expanded at *attr*."""
    child = {**context}
    child["expand_tree"] = _child_tree(context.get("expand_tree", {}), attr) or {}
    child["fields_tree"] = _child_tree(context.get("fields_tree"), attr)
    child["relations_tree"] = _child_tree(context.get("relations_tree"), attr)
    return child


class IExpandSerializer:
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        raise NotImplementedError


class One2ManyExpandSerializer(IExpandSerializer):
    # to-one: not expanded => *_id; expanded => object (remove *_id)
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        attr = mapping.attribute
        fk = mapping.fk_field
        do_expand = should_expand(
            context.get("expand_tree", {}),
            context.get("relations_tree"),
            attr,
            mapping.verify_relation,
        )

        if do_expand:
            fields.pop(fk, None)
            fields[attr] = mapping.serializer(
                read_only=True,
                context=_child_context(context, attr),
                **mapping.source_kwargs,
            )
        else:
            fields.pop(attr, None)
            fields_tree = context.get("fields_tree")
            include_id = (fields_tree is None) or (fk in fields_tree)
            if include_id and fk not in fields:
                fields[fk] = serializers.IntegerField(source=fk, read_only=True)


class Many2OneExpandSerializer(IExpandSerializer):
    # to-many: keep same key; not expanded => list[int]; expanded => list[object]
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        attr = mapping.attribute
        do_expand = should_expand(
            context.get("expand_tree", {}),
            context.get("relations_tree"),
            attr,
            mapping.verify_relation,
        )

        if attr not in fields:
            return

        if do_expand:
            fields[attr] = mapping.serializer(
                many=True,
                read_only=True,
                context=_child_context(context, attr),
                **mapping.source_kwargs,
            )
        else:
            fields[attr] = serializers.PrimaryKeyRelatedField(
                many=True,
                read_only=True,
                **mapping.source_kwargs,
            )
