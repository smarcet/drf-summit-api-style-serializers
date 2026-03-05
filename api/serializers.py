from rest_framework import serializers

from base_api_utils.serializers.v2 import BaseModelSerializer
from base_api_utils.serializers.v2.expands import (
    Many2OneExpandSerializer,
    One2ManyExpandSerializer,
)

from .models import Item, MediaUpload, Owner, Tag


class OwnerSerializer(BaseModelSerializer):
    allowed_fields = ["id", "name"]
    allowed_relations = []
    expand_mappings = {}

    class Meta:
        model = Owner
        fields = ["id", "name"]


class MediaUploadSerializer(BaseModelSerializer):
    owner = OwnerSerializer(read_only=True, required=False)

    allowed_fields = ["id", "url", "owner_id", "created", "modified"]
    allowed_relations = ["owner"]
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

    class Meta:
        model = MediaUpload
        fields = ["id", "url", "owner_id", "owner", "created", "modified"]


class TagSerializer(BaseModelSerializer):
    allowed_fields = ["id", "name"]
    allowed_relations = []
    expand_mappings = {}

    class Meta:
        model = Tag
        fields = ["id", "name"]


class ItemSerializer(BaseModelSerializer):
    media_upload = MediaUploadSerializer(read_only=True, required=False)
    tags = TagSerializer(many=True, read_only=True, required=False)
    display_name = serializers.SerializerMethodField()
    tag_count = serializers.IntegerField(read_only=True)
    has_media = serializers.BooleanField(read_only=True)

    allowed_fields = [
        "id",
        "name",
        "quantity",
        "media_upload_id",
        "media_upload",
        "tags",
        "display_name",
        "tag_count",
        "has_media",
        "created",
        "modified",
    ]
    allowed_relations = ["media_upload", "tags"]

    expand_mappings = {
        "media_upload": {
            "type": One2ManyExpandSerializer(),
            "serializer": MediaUploadSerializer,
            "original_attribute": "media_upload_id",
            "source": "media_upload",
            "verify_relation": True,
            "orm": {"bulk_prefetch": "media_upload"},
        },
        "tags": {
            "type": Many2OneExpandSerializer(),
            "serializer": TagSerializer,
            "source": "tags",
            "verify_relation": True,
            "orm": {"prefetch_related": ["tags"]},
        },
    }

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "quantity",
            "media_upload_id",
            "media_upload",
            "tags",
            "display_name",
            "tag_count",
            "has_media",
            "created",
            "modified",
        ]

    def get_display_name(self, obj):
        return f"{obj.name} (x{obj.quantity})"
