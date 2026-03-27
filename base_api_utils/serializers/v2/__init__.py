from .base_model_serializer import BaseModelSerializer, AbstractSerializer

try:
    import base_api_utils.serializers.v2.spectacular  # noqa: F401
except ImportError:
    pass  # drf-spectacular not installed
