from django.contrib import admin

from .models import Meeting, SpeakerMapping


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["title", "team", "meeting_date", "status", "created_by", "created_at"]
    list_filter = ["status", "team", "meeting_date"]
    search_fields = ["title", "transcript", "summary"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-meeting_date"]


@admin.register(SpeakerMapping)
class SpeakerMappingAdmin(admin.ModelAdmin):
    list_display = ["meeting", "speaker_label", "speaker_name", "created_at"]
    list_filter = ["meeting"]
    search_fields = ["speaker_label", "speaker_name"]
