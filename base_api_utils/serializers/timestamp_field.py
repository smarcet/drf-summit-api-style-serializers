from datetime import timezone, datetime

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
import time

@extend_schema_field(
    {
        'type': 'integer',
        'format': 'int64',
        'description': 'Unix timestamp (epoch)',
        'example': 1723488000
    })
class TimestampField(serializers.Field):
    def to_internal_value(self, data):
        try:
            return datetime.fromtimestamp(int(data), tz=timezone.utc)
        except (ValueError, OSError):
            raise serializers.ValidationError("Invalid timestamp format.")

    def to_representation(self, value):
        return int(time.mktime(value.timetuple()))