import copy

from rest_framework import serializers

from .expands import ExpandMapping
from .query_params import normalize_none, parse_tree
from ..timestamp_field import TimestampField


class AbstractSerializer:
    allowed_fields = None
    allowed_relations = []
    expand_mappings = {}

    @property
    def _own_context(self):
        """Return this serializer's context, not the parent's.

        DRF's field.bind() replaces self.context with the parent serializer's
        context dict.  We stash the real one in __init__ so child serializers
        keep their own expand / fields / relations trees.
        """
        if hasattr(self, "_original_context"):
            return self._original_context
        return self.context

    def __init__(self, *args, **kwargs):
        context = kwargs.get("context") or {}
        request = context.get("request")
        params = kwargs.pop("params", None) if "params" in kwargs else None

        already_parsed = any(
            k in context for k in ("expand_tree", "fields_tree", "relations_tree")
        )
        if not already_parsed:
            expand_raw = kwargs.pop("expand", None)
            expands_raw = kwargs.pop("expands", None)
            fields_raw = kwargs.pop("fields", None)
            relations_raw = kwargs.pop("relations", None)

            if isinstance(params, dict):
                expand_raw = expand_raw or params.get("expand") or params.get("expands")
                fields_raw = fields_raw or params.get("fields")
                relations_raw = relations_raw or params.get("relations")

            if request is not None:
                qp = request.query_params
                expand_raw = (
                    expand_raw or expands_raw or qp.get("expand") or qp.get("expands")
                )
                fields_raw = fields_raw or qp.get("fields")
                relations_raw = relations_raw or qp.get("relations")

            context["expand_tree"] = normalize_none(parse_tree(expand_raw))
            context["fields_tree"] = (
                normalize_none(parse_tree(fields_raw)) if fields_raw else None
            )
            context["relations_tree"] = (
                normalize_none(parse_tree(relations_raw)) if relations_raw else None
            )

        # Store original context before DRF can rebind it via field.bind()
        self._original_context = context
        self._ensure_defaults()

        kwargs["context"] = context
        super().__init__(*args, **kwargs)

    def _merged_allowed_fields(self):
        merged, saw_any = [], False
        for cls in reversed(self.__class__.mro()):
            af = getattr(cls, "allowed_fields", None)
            if af is not None:
                saw_any = True
                for f in af:
                    if f not in merged:
                        merged.append(f)
        return merged if saw_any else None

    def _merged_allowed_relations(self):
        merged = []
        for cls in reversed(self.__class__.mro()):
            rels = getattr(cls, "allowed_relations", None)
            if rels:
                for r in rels:
                    if r not in merged:
                        merged.append(r)
        return merged

    def _merged_expand_mappings(self):
        merged = {}
        for cls in reversed(self.__class__.mro()):
            m = getattr(cls, "expand_mappings", None)
            if not m:
                continue
            for k, v in m.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = copy.deepcopy(v)
        return merged

    def _ensure_defaults(self):
        ctx = self._own_context
        ctx.setdefault("expand_tree", {})
        ctx.setdefault("fields_tree", None)
        ctx.setdefault("relations_tree", None)

        # Treat empty dict {} same as None — means "use all allowed" for this serializer
        if not ctx["fields_tree"]:
            df = self._merged_allowed_fields()
            if df is not None:
                ctx["fields_tree"] = {k: {} for k in df}

        if not ctx["relations_tree"]:
            dr = self._merged_allowed_relations()
            ctx["relations_tree"] = {k: {} for k in dr}

    def _filter_local_fields(self, fields):
        ctx = self._own_context
        ft = ctx.get("fields_tree")
        if ft is None or (isinstance(ft, dict) and len(ft) == 0):
            return fields
        keep = (
            set(ft.keys())
            | set(ctx.get("expand_tree", {}).keys())
            | set(ctx.get("relations_tree", {}).keys())
        )
        for k in list(fields.keys()):
            if k not in keep:
                fields.pop(k, None)
        return fields

    def get_fields(self):
        fields = super().get_fields()
        self._ensure_defaults()
        fields = self._filter_local_fields(fields)

        for attr, spec in self._merged_expand_mappings().items():
            expand_type = spec["type"]
            mapping = ExpandMapping(
                attribute=attr,
                serializer=spec["serializer"],
                original_attribute=spec.get("original_attribute"),
                source=spec.get("source"),
                verify_relation=bool(spec.get("verify_relation", False)),
            )
            expand_type.apply(
                fields=fields,
                mapping=mapping,
                context=self._own_context,
            )

        return fields


class BaseModelSerializer(AbstractSerializer, serializers.ModelSerializer):
    id = serializers.ReadOnlyField(source="pk")
    created = TimestampField(read_only=True, required=False)
    modified = TimestampField(read_only=True, required=False)
