from rest_framework.routers import DefaultRouter

from .views import TeamViewSet

router = DefaultRouter(trailing_slash=False)
router.register(r"", TeamViewSet, basename="teams")

urlpatterns = router.urls
