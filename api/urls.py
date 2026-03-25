from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from .views import ItemCustomExpandViewSet, ItemViewSet, MediaUploadViewSet, TagViewSet, OwnerViewSet

router = DefaultRouter()
router.register(r"items", ItemViewSet, basename="items")
router.register(r"items-custom-expand", ItemCustomExpandViewSet, basename="items-custom-expand")
router.register(r"media-uploads", MediaUploadViewSet, basename="media-uploads")
router.register(r"tags", TagViewSet, basename="tags")
router.register(r"owners", OwnerViewSet, basename="owners")

urlpatterns = [
    path("", include(router.urls)),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
