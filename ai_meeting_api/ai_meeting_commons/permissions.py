from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """
    Object-level permission to only allow owners of an object to access it.
    """

    def has_object_permission(self, request, view, obj):
        return obj == request.user


class IsOwnerOrReadOnly(BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return True
        return obj == request.user


class IsTeamAdmin(BasePermission):
    """
    팀 관리자만 접근 가능
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_team_admin

    def has_object_permission(self, request, view, obj):
        # obj가 Team인 경우
        if hasattr(obj, "members"):
            return request.user.team == obj and request.user.is_team_admin
        # obj가 TeamSetting인 경우
        if hasattr(obj, "team"):
            return request.user.team == obj.team and request.user.is_team_admin
        return False


class IsTeamMember(BasePermission):
    """
    팀 멤버만 접근 가능
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.team is not None

    def has_object_permission(self, request, view, obj):
        # obj가 Team인 경우
        if hasattr(obj, "members"):
            return request.user.team == obj
        # obj가 TeamSetting인 경우
        if hasattr(obj, "team"):
            return request.user.team == obj.team
        return False
