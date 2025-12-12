from django.db import models


class Team(models.Model):
    """팀 모델"""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teams"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TeamSetting(models.Model):
    """팀 설정 모델 (API Key, Confluence, Slack 설정 등)"""

    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name="setting")

    # OpenAI 설정
    openai_api_key = models.CharField(max_length=500, blank=True, default="")

    # Confluence 설정
    confluence_site_url = models.URLField(blank=True, default="")
    confluence_api_token = models.CharField(max_length=500, blank=True, default="")
    confluence_user_email = models.EmailField(blank=True, default="")
    confluence_space_key = models.CharField(max_length=50, blank=True, default="")
    confluence_parent_page_id = models.CharField(max_length=50, blank=True, default="")

    # Slack 설정
    slack_webhook_url = models.URLField(blank=True, default="")  # Incoming Webhook URL
    slack_bot_token = models.CharField(max_length=500, blank=True, default="")  # Bot User OAuth Token
    slack_default_channel = models.CharField(max_length=100, blank=True, default="")  # 기본 알림 채널

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "team_settings"

    def __str__(self):
        return f"{self.team.name} Settings"
