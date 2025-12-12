from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai_meeting_commons.exceptions import ForbiddenException, NotFoundException
from ai_meeting_commons.permissions import IsTeamAdmin
from ai_meeting_users.models import User

from .models import Team, TeamSetting
from .serializers import (
    TeamCreateSerializer,
    TeamSerializer,
    TeamSettingSerializer,
    TeamSettingUpdateSerializer,
)


class TeamViewSet(viewsets.ModelViewSet):
    """팀 관리 ViewSet"""

    queryset = Team.objects.all()
    serializer_class = TeamSerializer

    def get_permissions(self):
        """액션별 권한 설정"""
        if self.action == "create":
            # 팀 생성은 인증된 사용자 누구나 가능
            return [IsAuthenticated()]
        elif self.action in ["update", "partial_update", "destroy"]:
            # 팀 수정/삭제는 팀 관리자만 가능
            return [IsAuthenticated(), IsTeamAdmin()]
        elif self.action in ["team_settings", "update_settings"]:
            # 팀 설정 조회/수정은 팀 관리자만 가능
            return [IsAuthenticated(), IsTeamAdmin()]
        elif self.action in ["grant_admin", "revoke_admin"]:
            # 관리자 권한 부여/해제는 팀 관리자만 가능
            return [IsAuthenticated(), IsTeamAdmin()]
        else:
            # 목록 조회, 상세 조회는 인증된 사용자
            return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "create":
            return TeamCreateSerializer
        return TeamSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        """팀 생성 시 TeamSetting 생성 및 생성자를 팀 관리자로 설정"""
        team = serializer.save()
        TeamSetting.objects.create(team=team)

        # 생성자를 해당 팀의 관리자로 설정
        user = self.request.user
        user.team = team
        user.is_team_admin = True
        user.save()

    @action(detail=True, methods=["get"], url_path="settings")
    def team_settings(self, request, pk=None):
        """팀 설정 조회"""
        team = self.get_object()

        # 팀 멤버인지 확인
        if request.user.team != team:
            raise ForbiddenException("해당 팀의 멤버가 아닙니다.")

        # 팀 관리자인지 확인
        if not request.user.is_team_admin:
            raise ForbiddenException("팀 설정을 조회할 권한이 없습니다.")

        try:
            setting = team.setting
        except TeamSetting.DoesNotExist:
            # 설정이 없으면 생성
            setting = TeamSetting.objects.create(team=team)

        serializer = TeamSettingSerializer(setting)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"], url_path="settings/update")
    def update_settings(self, request, pk=None):
        """팀 설정 수정"""
        team = self.get_object()

        # 팀 멤버인지 확인
        if request.user.team != team:
            raise ForbiddenException("해당 팀의 멤버가 아닙니다.")

        # 팀 관리자인지 확인
        if not request.user.is_team_admin:
            raise ForbiddenException("팀 설정을 수정할 권한이 없습니다.")

        try:
            setting = team.setting
        except TeamSetting.DoesNotExist:
            setting = TeamSetting.objects.create(team=team)

        serializer = TeamSettingUpdateSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # 수정 후 마스킹된 데이터 반환
        return Response(TeamSettingSerializer(setting).data)

    @action(detail=True, methods=["post"], url_path=r"members/(?P<user_id>\d+)/admin")
    def grant_admin(self, request, pk=None, user_id=None):
        """팀 관리자 권한 부여"""
        team = self.get_object()

        # 요청자가 해당 팀 관리자인지 확인
        if request.user.team != team or not request.user.is_team_admin:
            raise ForbiddenException("팀 관리자 권한을 부여할 권한이 없습니다.")

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise NotFoundException("사용자를 찾을 수 없습니다.") from None

        # 대상 사용자가 같은 팀인지 확인
        if user.team != team:
            raise ForbiddenException("해당 사용자는 이 팀의 멤버가 아닙니다.")

        user.is_team_admin = True
        user.save()

        return Response({"message": f"{user.username}님에게 팀 관리자 권한이 부여되었습니다."})

    @grant_admin.mapping.delete
    def revoke_admin(self, request, pk=None, user_id=None):
        """팀 관리자 권한 해제"""
        team = self.get_object()

        # 요청자가 해당 팀 관리자인지 확인
        if request.user.team != team or not request.user.is_team_admin:
            raise ForbiddenException("팀 관리자 권한을 해제할 권한이 없습니다.")

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise NotFoundException("사용자를 찾을 수 없습니다.") from None

        # 자기 자신의 권한은 해제 불가
        if user == request.user:
            raise ForbiddenException("자신의 관리자 권한은 해제할 수 없습니다.")

        # 대상 사용자가 같은 팀인지 확인
        if user.team != team:
            raise ForbiddenException("해당 사용자는 이 팀의 멤버가 아닙니다.")

        user.is_team_admin = False
        user.save()

        return Response({"message": f"{user.username}님의 팀 관리자 권한이 해제되었습니다."})

    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request, pk=None):
        """팀 멤버 목록 조회"""
        team = self.get_object()
        members = team.members.all().values("id", "username", "email", "is_team_admin")
        return Response(list(members))
