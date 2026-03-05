import copy
from dataclasses import dataclass

from rest_framework import serializers

from .query_params import has_key, subtree


@dataclass(frozen=True)
class ExpandMapping:
    attribute: str
    serializer: type
    original_attribute: str | None = None
    source: str | None = None
    verify_relation: bool = False


class IExpandSerializer:
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        raise NotImplementedError


class One2ManyExpandSerializer(IExpandSerializer):
    # to-one: not expanded => *_id; expanded => object (remove *_id)
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        expand_tree = context.get("expand_tree", {})
        fields_tree = context.get("fields_tree")
        relations_tree = context.get("relations_tree")

        attr = mapping.attribute
        src = mapping.source or attr
        original = mapping.original_attribute or f"{attr}_id"

        relation_allowed = True
        if mapping.verify_relation:
            relation_allowed = has_key(relations_tree, attr)

        do_expand = has_key(expand_tree, attr) and relation_allowed

        # DRF asserts if source == field_name; only pass source when different.
        source_kwargs = {} if src == attr else {"source": src}

        if do_expand:
            fields.pop(original, None)

            # Shallow copy context, but deep copy tree values to prevent mutations
            child_ctx = {**context}
            child_ctx["expand_tree"] = copy.deepcopy(subtree(expand_tree, attr) or {})
            child_fields_tree = (
                None
                if fields_tree is None or attr not in fields_tree
                else copy.deepcopy(subtree(fields_tree, attr))
            )
            child_ctx["fields_tree"] = child_fields_tree
            child_ctx["relations_tree"] = (
                None
                if relations_tree is None or attr not in relations_tree
                else copy.deepcopy(subtree(relations_tree, attr))
            )

            fields[attr] = mapping.serializer(
                read_only=True,
                context=child_ctx,
                **source_kwargs,
            )
        else:
            fields.pop(attr, None)
            include_id = (fields_tree is None) or has_key(fields_tree, original)
            if include_id and original not in fields:
                fields[original] = serializers.IntegerField(
                    source=original, read_only=True
                )


class Many2OneExpandSerializer(IExpandSerializer):
    # to-many: keep same key; not expanded => list[int]; expanded => list[object]
    def apply(self, *, fields: dict, mapping: ExpandMapping, context: dict) -> None:
        expand_tree = context.get("expand_tree", {})
        relations_tree = context.get("relations_tree")
        fields_tree = context.get("fields_tree")

        attr = mapping.attribute
        src = mapping.source or attr

        relation_allowed = True
        if mapping.verify_relation:
            relation_allowed = has_key(relations_tree, attr)

        do_expand = has_key(expand_tree, attr) and relation_allowed

        if attr not in fields:
            return

        # DRF asserts if source == field_name; only pass source when different.
        source_kwargs = {} if src == attr else {"source": src}

        if do_expand:
            # Shallow copy context, but deep copy tree values to prevent mutations
            child_ctx = {**context}
            child_ctx["expand_tree"] = copy.deepcopy(subtree(expand_tree, attr) or {})
            child_ctx["fields_tree"] = (
                None
                if fields_tree is None or attr not in fields_tree
                else copy.deepcopy(subtree(fields_tree, attr))
            )
            child_ctx["relations_tree"] = (
                None
                if relations_tree is None or attr not in relations_tree
                else copy.deepcopy(subtree(relations_tree, attr))
            )

            fields[attr] = mapping.serializer(
                many=True,
                read_only=True,
                context=child_ctx,
                **source_kwargs,
            )
        else:
            fields[attr] = serializers.PrimaryKeyRelatedField(
                many=True,
                read_only=True,
                **source_kwargs,
            )
