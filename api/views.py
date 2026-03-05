from django.db.models import Count, Q

from base_api_utils.serializers.v2.query_params import has_key
from base_api_utils.views import BaseView, ExpandQuerysetOptimizationMixin

from .models import Item, MediaUpload, Owner, Tag
from .serializers import (
    ItemSerializer,
    MediaUploadSerializer,
    OwnerSerializer,
    TagSerializer,
)


class ItemViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    queryset = Item.objects.all().order_by("id")
    serializer_class = ItemSerializer
    ordering_fields = {
        "id": "id",
        "name": "name",
        "quantity": "quantity",
        "tag_count": "tag_count",
    }

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(
                tag_count=Count("tags"),
                has_media=Q(media_upload_id__isnull=False),
            )
        )

    def bulk_prefetch__media_upload(
        self, items, expand_subtree, fields_subtree, relations_subtree
    ):
        qs = MediaUpload.objects.all()
        if has_key(expand_subtree, "owner") and has_key(relations_subtree, "owner"):
            qs = qs.select_related("owner")

        ids = {i.media_upload_id for i in items if getattr(i, "media_upload_id", None)}
        uploads = {m.id: m for m in qs.filter(id__in=ids)}
        for i in items:
            i._prefetched_media_upload = uploads.get(i.media_upload_id)


class MediaUploadViewSet(ExpandQuerysetOptimizationMixin, BaseView):
    queryset = MediaUpload.objects.all().order_by("id")
    serializer_class = MediaUploadSerializer
    ordering_fields = {"id": "id", "url": "url"}


class TagViewSet(BaseView):
    queryset = Tag.objects.all().order_by("id")
    serializer_class = TagSerializer
    ordering_fields = {"id": "id", "name": "name"}


class OwnerViewSet(BaseView):
    queryset = Owner.objects.all().order_by("id")
    serializer_class = OwnerSerializer
    ordering_fields = {"id": "id", "name": "name"}
