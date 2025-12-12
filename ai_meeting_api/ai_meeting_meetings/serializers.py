from rest_framework import serializers

from .models import Meeting, MeetingStatus, SpeakerMapping


class SpeakerMappingSerializer(serializers.ModelSerializer):
    """화자 매핑 Serializer"""

    class Meta:
        model = SpeakerMapping
        fields = ["id", "speaker_label", "speaker_name", "created_at"]
        read_only_fields = ["id", "created_at"]


class MeetingListSerializer(serializers.ModelSerializer):
    """회의록 목록 Serializer"""

    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    has_audio = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "title",
            "meeting_date",
            "status",
            "status_display",
            "has_audio",
            "created_by_name",
            "created_at",
            "updated_at",
        ]

    def get_has_audio(self, obj):
        return bool(obj.audio_file)


class MeetingDetailSerializer(serializers.ModelSerializer):
    """회의록 상세 Serializer"""

    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    speaker_mappings = SpeakerMappingSerializer(many=True, read_only=True)
    has_audio = serializers.SerializerMethodField()
    audio_file_url = serializers.SerializerMethodField()
    chat_transcript = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "title",
            "meeting_date",
            "audio_file_url",
            "audio_file_expires_at",
            "has_audio",
            "transcript",
            "speaker_data",
            "corrected_transcript",
            "corrected_speaker_data",
            "chat_transcript",
            "summary",
            "status",
            "status_display",
            "error_message",
            "confluence_page_id",
            "confluence_page_url",
            "slack_message_ts",
            "slack_channel",
            "speaker_mappings",
            "created_by_name",
            "created_at",
            "updated_at",
        ]

    def get_has_audio(self, obj):
        return bool(obj.audio_file)

    def get_audio_file_url(self, obj):
        if obj.audio_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.audio_file.url)
            return obj.audio_file.url
        return None

    def get_chat_transcript(self, obj):
        """
        채팅 형식의 전문 반환 (화자 이름 매핑 적용)

        Returns:
            list: [{"speaker": "김영도", "text": "...", "start": 0.0, "end": 5.2}, ...]
        """
        # 교정된 화자별 데이터 우선, 없으면 원본 사용
        speaker_data = obj.corrected_speaker_data or obj.speaker_data
        if not speaker_data:
            return []

        # 화자 이름 매핑 딕셔너리 생성
        speaker_name_map = {mapping.speaker_label: mapping.speaker_name for mapping in obj.speaker_mappings.all()}

        # 화자 이름 적용
        chat_transcript = []
        for segment in speaker_data:
            speaker_label = segment.get("speaker", "")
            chat_transcript.append(
                {
                    "speaker": speaker_name_map.get(speaker_label, speaker_label),
                    "text": segment.get("text", ""),
                    "start": segment.get("start", 0.0),
                    "end": segment.get("end", 0.0),
                }
            )

        return chat_transcript


class MeetingCreateSerializer(serializers.ModelSerializer):
    """회의록 생성 Serializer"""

    audio_file = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = Meeting
        fields = ["title", "meeting_date", "audio_file"]

    def validate_audio_file(self, value):
        if value:
            # 파일 크기 제한 (500MB) - 긴 녹음 파일 지원
            max_size = 500 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError("음성 파일은 500MB를 초과할 수 없습니다.")

            # 지원 포맷 확인
            allowed_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".webm", ".mp4"]
            ext = "." + value.name.split(".")[-1].lower() if "." in value.name else ""
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(allowed_extensions)}"
                )
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["team"] = request.user.team
        validated_data["created_by"] = request.user

        # 음성 파일이 있으면 상태를 pending으로 설정
        if validated_data.get("audio_file"):
            validated_data["status"] = MeetingStatus.PENDING
        else:
            validated_data["status"] = MeetingStatus.COMPLETED

        return super().create(validated_data)


class MeetingUpdateSerializer(serializers.ModelSerializer):
    """회의록 수정 Serializer"""

    class Meta:
        model = Meeting
        fields = ["title", "meeting_date", "summary", "corrected_transcript"]


class SpeakerMappingBulkUpdateSerializer(serializers.Serializer):
    """화자 매핑 일괄 수정 Serializer"""

    mappings = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        required=True,
    )

    def validate_mappings(self, value):
        for mapping in value:
            if "speaker_label" not in mapping or "speaker_name" not in mapping:
                raise serializers.ValidationError("각 매핑에는 'speaker_label'과 'speaker_name'이 필요합니다.")
        return value


class MeetingStatusSerializer(serializers.ModelSerializer):
    """회의록 상태 조회 Serializer"""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Meeting
        fields = ["id", "status", "status_display", "error_message"]


class MeetingSearchSerializer(serializers.ModelSerializer):
    """회의록 검색 결과 Serializer"""

    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    summary_preview = serializers.SerializerMethodField()
    transcript_preview = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "title",
            "meeting_date",
            "summary_preview",
            "transcript_preview",
            "created_by_name",
            "created_at",
        ]

    def get_summary_preview(self, obj):
        """요약 미리보기 (처음 200자)"""
        if obj.summary:
            return obj.summary[:200] + "..." if len(obj.summary) > 200 else obj.summary
        return ""

    def get_transcript_preview(self, obj):
        """전문 미리보기 (처음 200자)"""
        text = obj.corrected_transcript or obj.transcript
        if text:
            return text[:200] + "..." if len(text) > 200 else text
        return ""
