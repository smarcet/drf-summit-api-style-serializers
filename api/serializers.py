from rest_framework import serializers

from base_api_utils.serializers.timestamp_field import TimestampField
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


class TagSerializer(BaseModelSerializer):
    allowed_fields = ["id", "name"]
    allowed_relations = []
    expand_mappings = {}

    class Meta:
        model = Tag


class ItemSerializer(BaseModelSerializer):
    media_upload = MediaUploadSerializer(read_only=True, required=False)
    tags = TagSerializer(many=True, read_only=True, required=False)
    display_name = serializers.SerializerMethodField()
    tag_count = serializers.IntegerField(read_only=True)
    has_media = serializers.BooleanField(read_only=True)
    expires_at = TimestampField(read_only=True, required=False)

    allowed_fields = [
        "id",
        "name",
        "quantity",
        "media_upload_id",
        "display_name",
        "tag_count",
        "has_media",
        "expires_at",
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

    def get_display_name(self, obj):
        return f"{obj.name} (x{obj.quantity})"


class ItemCustomExpandSerializer(BaseModelSerializer):
    """Demonstrates manual expansion using get_expand() and get_child_context().

    Unlike ItemSerializer which uses expand_mappings for declarative expansion,
    this serializer handles media_upload expansion manually via SerializerMethodField.
    Use this pattern when expansion requires custom logic (filtering, conditional, etc.).
    """

    media_upload = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True, required=False)

    allowed_fields = ["id", "name", "quantity", "media_upload_id"]
    allowed_relations = ["media_upload", "tags"]

    expand_mappings = {
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

    def get_media_upload(self, obj):
        if not obj.media_upload_id:
            return None

        # Not expanded → return just the FK id
        if "media_upload" not in self.get_expand():
            return obj.media_upload_id

        # Expanded → return full serialized object with scoped child context
        media = obj.media_upload
        if not media:
            return None

        return MediaUploadSerializer(
            context=self.get_child_context("media_upload")
        ).to_representation(media)
