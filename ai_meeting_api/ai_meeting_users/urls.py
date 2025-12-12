from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import UserViewSet

router = DefaultRouter(trailing_slash=False)
router.register("", UserViewSet, basename="user")

urlpatterns = [
    path("", include(router.urls)),
    path("token/refresh", TokenRefreshView.as_view(), name="token_refresh"),
]
