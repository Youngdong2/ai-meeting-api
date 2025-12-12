from datetime import timedelta

from django.db import models
from django.utils import timezone


def audio_file_path(instance, filename):
    """음성 파일 저장 경로 생성"""
    return f"audio/{instance.team.id}/{timezone.now().strftime('%Y/%m')}/{filename}"


class MeetingStatus(models.TextChoices):
    """회의록 처리 상태"""

    PENDING = "pending", "대기 중"
    COMPRESSING = "compressing", "압축 중"
    TRANSCRIBING = "transcribing", "STT 처리 중"
    CORRECTING = "correcting", "텍스트 교정 중"
    SUMMARIZING = "summarizing", "요약 중"
    COMPLETED = "completed", "완료"
    FAILED = "failed", "실패"


class Meeting(models.Model):
    """회의록 모델"""

    team = models.ForeignKey(
        "ai_meeting_teams.Team",
        on_delete=models.CASCADE,
        related_name="meetings",
    )
    created_by = models.ForeignKey(
        "ai_meeting_users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_meetings",
    )

    # 기본 정보
    title = models.CharField(max_length=200)
    meeting_date = models.DateTimeField()

    # 음성 파일
    audio_file = models.FileField(upload_to=audio_file_path, null=True, blank=True)
    audio_file_expires_at = models.DateTimeField(null=True, blank=True)

    # STT 결과
    transcript = models.TextField(blank=True, default="")
    speaker_data = models.JSONField(default=list, blank=True)
    # 예: [{"speaker": "Speaker 0", "text": "...", "start": 0.0, "end": 5.2}, ...]

    # 교정된 텍스트
    corrected_transcript = models.TextField(blank=True, default="")

    # AI 요약
    summary = models.TextField(blank=True, default="")

    # 상태
    status = models.CharField(
        max_length=20,
        choices=MeetingStatus.choices,
        default=MeetingStatus.PENDING,
    )
    error_message = models.TextField(blank=True, default="")

    # Confluence 연동
    confluence_page_id = models.CharField(max_length=50, blank=True, default="")
    confluence_page_url = models.URLField(blank=True, default="")

    # Slack 연동
    slack_message_ts = models.CharField(max_length=50, blank=True, default="")
    slack_channel = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "meetings"
        ordering = ["-meeting_date"]

    def __str__(self):
        return f"{self.title} ({self.meeting_date.strftime('%Y-%m-%d')})"

    def save(self, *args, **kwargs):
        # 음성 파일 만료일 자동 설정 (90일)
        if self.audio_file and not self.audio_file_expires_at:
            self.audio_file_expires_at = timezone.now() + timedelta(days=90)
        super().save(*args, **kwargs)


class SpeakerMapping(models.Model):
    """화자 이름 매핑 모델"""

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="speaker_mappings",
    )
    speaker_label = models.CharField(max_length=50)  # "Speaker 0", "Speaker 1" 등
    speaker_name = models.CharField(max_length=100)  # 실제 이름 "김영도", "홍길동" 등

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "speaker_mappings"
        unique_together = ["meeting", "speaker_label"]

    def __str__(self):
        return f"{self.meeting.title}: {self.speaker_label} -> {self.speaker_name}"
