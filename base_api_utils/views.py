from typing import Optional, Type, Dict, Any, Iterable, Set, List, Tuple
from django.conf import settings
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response

from base_api_utils.serializers.v2.query_params import parse_request_trees, has_key, subtree

class ReadWriteSerializerMixin:
    read_serializer_class: Optional[Type[BaseSerializer]] = None
    write_serializer_class: Optional[Type[BaseSerializer]] = None
    action_read_serializer_classes: Optional[Dict[str, Type[BaseSerializer]]] = None
    action_write_serializer_classes: Optional[Dict[str, Type[BaseSerializer]]] = None

    def _drf_serializer_cls(self):
        get_sc = getattr(type(self), "get_serializer_class", None)
        if get_sc is None:
            return None
        try:
            return get_sc(self)
        except AssertionError:
            return None

    def _default_read_cls(self):
        cls = self.read_serializer_class or self._drf_serializer_cls() or getattr(self, "serializer_class", None)
        if cls is None:
            raise AssertionError("Read serializer is not configured.")
        return cls

    def _default_write_cls(self):
        return self.write_serializer_class or self._default_read_cls()

    def _action_read_cls(self, action):
        if not action or not self.action_read_serializer_classes:
            return None
        return self.action_read_serializer_classes.get(action)

    def _action_write_cls(self, action):
        if not action or not self.action_write_serializer_classes:
            return None
        return self.action_write_serializer_classes.get(action)

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())
        action = getattr(self, "action", None)
        has_data = "data" in kwargs
        has_instance_kw = "instance" in kwargs
        has_positional_instance = bool(args) and not has_data

        if has_data:
            serializer_class = self._action_write_cls(action) or self._default_write_cls()
        elif has_instance_kw or has_positional_instance:
            serializer_class = self._action_read_cls(action) or self._default_read_cls()
        else:
            serializer_class = self._action_read_cls(action) or self._default_read_cls()

        return serializer_class(*args, **kwargs)

class BaseView(ReadWriteSerializerMixin, ModelViewSet):
    ordering_fields = {}

    def get_queryset(self):
        return self.queryset

    def apply_ordering(self, queryset):
        ordering_param = getattr(settings, "REST_FRAMEWORK", {}).get("ORDERING_PARAM", "order")
        ordering = self.request.query_params.get(ordering_param, None)

        if ordering:
            ordering_list = ordering.split(",")
        elif hasattr(self, "ordering") and self.ordering:
            ordering_list = self.ordering if isinstance(self.ordering, list) else [self.ordering]
        else:
            return queryset

        ordering_fields = []
        for field in ordering_list:
            is_desc = field.startswith("-")
            field_name = field[1:] if is_desc else field

            if isinstance(self.ordering_fields, dict):
                mapped_field = self.ordering_fields.get(field_name)
                if mapped_field:
                    ordering_fields.append(f"-{mapped_field}" if is_desc else mapped_field)
            elif isinstance(self.ordering_fields, list):
                if field_name in self.ordering_fields:
                    ordering_fields.append(field if not is_desc else f"-{field_name}")

        if ordering_fields:
            return queryset.order_by(*ordering_fields)
        return queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        return self.apply_ordering(queryset)

class ExpandQuerysetOptimizationMixin:
    """Auto-optimizes queryset from serializer.expand_mappings (recursive), plus runs bulk hooks for computed relations."""

    def _parse_trees(self):
        return parse_request_trees(self.request)

    def _effective_expand(self, expand_tree: dict, relations_tree: dict|None, attr: str, verify_relation: bool) -> bool:
        if not has_key(expand_tree, attr):
            return False
        if verify_relation and not has_key(relations_tree, attr):
            return False
        return True

    def _include_field(self, fields_tree: dict|None, attr: str) -> bool:
        if fields_tree is None:
            return True
        return attr in fields_tree

    def _collect_orm_recursive(
        self,
        serializer_cls: type,
        *,
        expand_tree: dict,
        fields_tree: dict|None,
        relations_tree: dict|None,
        prefix: str = ""
    ) -> Tuple[Set[str], Set[str], List[Tuple[str, dict, dict|None, dict|None]]]:
        select_paths: Set[str] = set()
        prefetch_paths: Set[str] = set()
        bulk_hooks: List[Tuple[str, dict, dict|None, dict|None]] = []

        mappings = getattr(serializer_cls, "expand_mappings", {}) or {}
        for attr, spec in mappings.items():
            if not spec:
                continue

            orm = spec.get("orm") or {}
            verify = bool(spec.get("verify_relation", False))

            is_included = self._include_field(fields_tree, attr)
            is_expanded = self._effective_expand(expand_tree, relations_tree, attr, verify)

            for sr in orm.get("select_related", []) or []:
                if is_expanded:
                    select_paths.add(f"{prefix}{sr}" if prefix else sr)

            for pr in orm.get("prefetch_related", []) or []:
                if is_included:
                    prefetch_paths.add(f"{prefix}{pr}" if prefix else pr)

            hook = orm.get("bulk_prefetch")
            if hook and is_expanded:
                bulk_hooks.append((hook, subtree(expand_tree, attr) or {}, subtree(fields_tree, attr), subtree(relations_tree, attr)))

            # recurse only if expanded
            if is_expanded:
                child_cls = spec.get("serializer")
                if child_cls:
                    child_expand = subtree(expand_tree, attr) or {}
                    child_fields = subtree(fields_tree, attr)
                    child_relations = subtree(relations_tree, attr)

                    join_seg = (spec.get("source") or attr)
                    if orm.get("nested_prefix") is not None:
                        join_seg = orm.get("nested_prefix")

                    # If this relation is computed/bulk, we can't build ORM paths on base qs,
                    # but recursion still matters for hooks (they get subtrees).
                    if not orm.get("bulk_prefetch"):
                        child_prefix = f"{prefix}{join_seg}__" if prefix else f"{join_seg}__"
                        c_sel, c_pre, c_hooks = self._collect_orm_recursive(
                            child_cls,
                            expand_tree=child_expand,
                            fields_tree=child_fields,
                            relations_tree=child_relations,
                            prefix=child_prefix,
                        )
                        select_paths |= c_sel
                        prefetch_paths |= c_pre
                        bulk_hooks += c_hooks

        return select_paths, prefetch_paths, bulk_hooks

    def get_queryset(self):
        qs = super().get_queryset()
        expand_tree, fields_tree, relations_tree = self._parse_trees()
        serializer_cls = self.get_serializer_class()

        select_paths, prefetch_paths, _ = self._collect_orm_recursive(
            serializer_cls, expand_tree=expand_tree, fields_tree=fields_tree, relations_tree=relations_tree, prefix=""
        )

        if select_paths:
            qs = qs.select_related(*sorted(select_paths))
        if prefetch_paths:
            qs = qs.prefetch_related(*sorted(prefetch_paths))
        return qs

    def _run_bulk_hooks(self, objects: Iterable[Any]):
        expand_tree, fields_tree, relations_tree = self._parse_trees()
        serializer_cls = self.get_serializer_class()
        _, _, hooks = self._collect_orm_recursive(
            serializer_cls, expand_tree=expand_tree, fields_tree=fields_tree, relations_tree=relations_tree, prefix=""
        )
        for hook_name, ex_sub, fi_sub, rel_sub in hooks:
            fn = getattr(self, f"bulk_prefetch__{hook_name}", None)
            if fn:
                fn(objects, ex_sub, fi_sub, rel_sub)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = page if page is not None else list(queryset)

        self._run_bulk_hooks(items)

        serializer = self.get_serializer(items, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
