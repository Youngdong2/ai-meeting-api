from rest_framework.routers import DefaultRouter

from .views import MeetingViewSet

router = DefaultRouter(trailing_slash=False)
router.register(r"", MeetingViewSet, basename="meetings")

urlpatterns = router.urls
