from rest_framework import serializers

from .models import Team, TeamSetting


class TeamSerializer(serializers.ModelSerializer):
    """팀 기본 정보 Serializer"""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ["id", "name", "description", "member_count", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_member_count(self, obj):
        return obj.members.count()


class TeamCreateSerializer(serializers.ModelSerializer):
    """팀 생성 Serializer"""

    class Meta:
        model = Team
        fields = ["name", "description"]


class TeamSettingSerializer(serializers.ModelSerializer):
    """팀 설정 Serializer (민감 정보 마스킹)"""

    openai_api_key = serializers.SerializerMethodField()
    confluence_api_token = serializers.SerializerMethodField()

    class Meta:
        model = TeamSetting
        fields = [
            "id",
            "openai_api_key",
            "confluence_site_url",
            "confluence_api_token",
            "confluence_user_email",
            "confluence_space_key",
            "confluence_parent_page_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_openai_api_key(self, obj):
        """API Key 마스킹 처리"""
        if obj.openai_api_key:
            return f"{'*' * 20}...{obj.openai_api_key[-4:]}"
        return ""

    def get_confluence_api_token(self, obj):
        """Confluence Token 마스킹 처리"""
        if obj.confluence_api_token:
            return f"{'*' * 20}...{obj.confluence_api_token[-4:]}"
        return ""


class TeamSettingUpdateSerializer(serializers.ModelSerializer):
    """팀 설정 수정 Serializer"""

    class Meta:
        model = TeamSetting
        fields = [
            "openai_api_key",
            "confluence_site_url",
            "confluence_api_token",
            "confluence_user_email",
            "confluence_space_key",
            "confluence_parent_page_id",
        ]
        extra_kwargs = {
            "openai_api_key": {"required": False},
            "confluence_site_url": {"required": False},
            "confluence_api_token": {"required": False},
            "confluence_user_email": {"required": False},
            "confluence_space_key": {"required": False},
            "confluence_parent_page_id": {"required": False},
        }
