from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai_meeting_commons.exceptions import ForbiddenException, NotFoundException
from ai_meeting_commons.permissions import IsTeamMember

from .models import Meeting, SpeakerMapping
from .serializers import (
    MeetingCreateSerializer,
    MeetingDetailSerializer,
    MeetingListSerializer,
    MeetingStatusSerializer,
    MeetingUpdateSerializer,
    SpeakerMappingBulkUpdateSerializer,
    SpeakerMappingSerializer,
)


class MeetingViewSet(viewsets.ModelViewSet):
    """회의록 ViewSet"""

    queryset = Meeting.objects.all()
    permission_classes = [IsAuthenticated, IsTeamMember]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """팀 기준으로 회의록 필터링"""
        user = self.request.user
        if not user.team:
            return Meeting.objects.none()
        return Meeting.objects.filter(team=user.team)

    def get_serializer_class(self):
        if self.action == "list":
            return MeetingListSerializer
        elif self.action == "create":
            return MeetingCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return MeetingUpdateSerializer
        elif self.action == "meeting_status":
            return MeetingStatusSerializer
        return MeetingDetailSerializer

    def get_object(self):
        """객체 조회 및 팀 권한 확인"""
        obj = super().get_object()
        if obj.team != self.request.user.team:
            raise ForbiddenException("해당 회의록에 접근할 권한이 없습니다.")
        return obj

    def create(self, request, *args, **kwargs):
        """회의록 생성 (음성 파일 업로드)"""
        if not request.user.team:
            raise ForbiddenException("팀에 소속되어야 회의록을 생성할 수 있습니다.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meeting = serializer.save()

        # 음성 파일이 있으면 비동기 처리 시작 (Phase 4에서 구현)
        # if meeting.audio_file:
        #     process_meeting_audio.delay(meeting.id)

        response_serializer = MeetingDetailSerializer(meeting, context={"request": request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="status")
    def meeting_status(self, request, pk=None):
        """처리 상태 조회"""
        meeting = self.get_object()
        serializer = MeetingStatusSerializer(meeting)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="speakers")
    def speakers(self, request, pk=None):
        """화자 목록 조회"""
        meeting = self.get_object()

        # speaker_data에서 화자 라벨 추출
        speaker_labels = set()
        for segment in meeting.speaker_data:
            if "speaker" in segment:
                speaker_labels.add(segment["speaker"])

        # 기존 매핑 조회
        mappings = meeting.speaker_mappings.all()
        mapping_dict = {m.speaker_label: m for m in mappings}

        # 결과 구성
        result = []
        for label in sorted(speaker_labels):
            if label in mapping_dict:
                result.append(SpeakerMappingSerializer(mapping_dict[label]).data)
            else:
                result.append({"speaker_label": label, "speaker_name": "", "id": None, "created_at": None})

        return Response(result)

    @speakers.mapping.patch
    def update_speakers(self, request, pk=None):
        """화자 이름 일괄 매핑"""
        meeting = self.get_object()

        serializer = SpeakerMappingBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        mappings = serializer.validated_data["mappings"]

        for mapping_data in mappings:
            speaker_label = mapping_data["speaker_label"]
            speaker_name = mapping_data["speaker_name"]

            SpeakerMapping.objects.update_or_create(
                meeting=meeting,
                speaker_label=speaker_label,
                defaults={"speaker_name": speaker_name},
            )

        # 업데이트된 매핑 반환
        updated_mappings = meeting.speaker_mappings.all()
        return Response(SpeakerMappingSerializer(updated_mappings, many=True).data)

    @action(detail=True, methods=["post"], url_path="transcribe")
    def transcribe(self, request, pk=None):
        """STT 수동 재실행"""
        meeting = self.get_object()

        if not meeting.audio_file:
            raise NotFoundException("음성 파일이 없습니다.")

        # Phase 4에서 구현
        # process_meeting_audio.delay(meeting.id)

        return Response({"message": "STT 처리가 시작되었습니다.", "status": meeting.status})

    @action(detail=True, methods=["post"], url_path="summarize")
    def summarize(self, request, pk=None):
        """요약 수동 재생성"""
        meeting = self.get_object()

        if not meeting.transcript and not meeting.corrected_transcript:
            raise NotFoundException("STT 텍스트가 없습니다. 먼저 STT를 실행하세요.")

        # Phase 4에서 구현
        # generate_summary.delay(meeting.id)

        return Response({"message": "요약 생성이 시작되었습니다.", "status": meeting.status})
