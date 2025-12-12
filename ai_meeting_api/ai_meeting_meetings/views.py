from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai_meeting_commons.exceptions import ForbiddenException, NotFoundException
from ai_meeting_commons.permissions import IsTeamMember

from .models import Meeting, MeetingStatus, SpeakerMapping
from .serializers import (
    MeetingCreateSerializer,
    MeetingDetailSerializer,
    MeetingListSerializer,
    MeetingSearchSerializer,
    MeetingStatusSerializer,
    MeetingUpdateSerializer,
    SpeakerMappingBulkUpdateSerializer,
    SpeakerMappingSerializer,
)
from .tasks import process_meeting_audio, regenerate_summary, share_to_slack, upload_to_confluence


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

        # 음성 파일이 있으면 비동기 처리 시작
        if meeting.audio_file:
            process_meeting_audio.delay(meeting.id)

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

        meeting.status = MeetingStatus.PENDING
        meeting.save()
        process_meeting_audio.delay(meeting.id)

        return Response({"message": "STT 처리가 시작되었습니다.", "status": meeting.status})

    @action(detail=True, methods=["post"], url_path="summarize")
    def summarize(self, request, pk=None):
        """요약 수동 재생성"""
        meeting = self.get_object()

        if not meeting.transcript and not meeting.corrected_transcript:
            raise NotFoundException("STT 텍스트가 없습니다. 먼저 STT를 실행하세요.")

        regenerate_summary.delay(meeting.id)

        return Response({"message": "요약 생성이 시작되었습니다.", "status": meeting.status})

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        """
        회의록 검색 (제목, 전문, 요약)

        Query Parameters:
            q: 검색어 (필수)
            field: 검색 필드 (선택, 기본값: all)
                - all: 전체 필드 검색
                - title: 제목만 검색
                - transcript: 전문만 검색
                - summary: 요약만 검색
        """
        query = request.query_params.get("q", "").strip()
        field = request.query_params.get("field", "all")

        if not query:
            return Response({"results": [], "count": 0, "query": ""})

        user = request.user
        if not user.team:
            return Response({"results": [], "count": 0, "query": query})

        queryset = Meeting.objects.filter(team=user.team, status=MeetingStatus.COMPLETED)

        # 검색 필드에 따른 처리
        if field == "title":
            # 제목 검색 (LIKE 기반)
            queryset = queryset.filter(title__icontains=query)
        elif field == "transcript":
            # 전문 검색
            queryset = queryset.filter(Q(transcript__icontains=query) | Q(corrected_transcript__icontains=query))
        elif field == "summary":
            # 요약 검색
            queryset = queryset.filter(summary__icontains=query)
        else:
            # 전체 필드 검색 (PostgreSQL Full-text Search)
            search_vector = (
                SearchVector("title", weight="A")
                + SearchVector("corrected_transcript", weight="B")
                + SearchVector("summary", weight="C")
                + SearchVector("transcript", weight="D")
            )

            search_query = SearchQuery(query, search_type="plain")

            queryset = (
                queryset.annotate(search=search_vector, rank=SearchRank(search_vector, search_query))
                .filter(
                    Q(search=search_query)
                    | Q(title__icontains=query)
                    | Q(transcript__icontains=query)
                    | Q(corrected_transcript__icontains=query)
                    | Q(summary__icontains=query)
                )
                .order_by("-rank", "-meeting_date")
                .distinct()
            )

        # 결과 직렬화
        serializer = MeetingSearchSerializer(queryset[:50], many=True)

        return Response(
            {
                "results": serializer.data,
                "count": len(serializer.data),
                "query": query,
                "field": field,
            }
        )

    @action(detail=True, methods=["post"], url_path="confluence/upload")
    def confluence_upload(self, request, pk=None):
        """Confluence에 회의록 업로드"""
        meeting = self.get_object()

        if meeting.status != MeetingStatus.COMPLETED:
            return Response(
                {"error": "완료된 회의록만 Confluence에 업로드할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 팀 설정 확인
        try:
            team_setting = meeting.team.setting
            if not team_setting.confluence_site_url:
                return Response(
                    {"error": "Confluence 설정이 완료되지 않았습니다. 팀 설정에서 Confluence 정보를 입력하세요."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception:
            return Response(
                {"error": "팀 설정을 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 비동기 업로드 시작
        upload_to_confluence.delay(meeting.id)

        return Response(
            {
                "message": "Confluence 업로드가 시작되었습니다.",
                "meeting_id": meeting.id,
            }
        )

    @action(detail=True, methods=["get"], url_path="confluence/status")
    def confluence_status(self, request, pk=None):
        """Confluence 업로드 상태 확인"""
        meeting = self.get_object()

        return Response(
            {
                "uploaded": bool(meeting.confluence_page_id),
                "page_id": meeting.confluence_page_id or None,
                "page_url": meeting.confluence_page_url or None,
            }
        )

    @action(detail=True, methods=["post"], url_path="slack/share")
    def slack_share(self, request, pk=None):
        """Slack 채널에 회의록 요약 공유"""
        meeting = self.get_object()

        if meeting.status != MeetingStatus.COMPLETED:
            return Response(
                {"error": "완료된 회의록만 Slack에 공유할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 팀 설정 확인
        try:
            team_setting = meeting.team.setting
            if not team_setting.slack_webhook_url and not team_setting.slack_bot_token:
                return Response(
                    {"error": "Slack 설정이 완료되지 않았습니다. 팀 설정에서 Slack 정보를 입력하세요."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception:
            return Response(
                {"error": "팀 설정을 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 채널 파라미터 (선택)
        channel = request.data.get("channel")

        # 비동기 공유 시작
        share_to_slack.delay(meeting.id, channel=channel)

        return Response(
            {
                "message": "Slack 공유가 시작되었습니다.",
                "meeting_id": meeting.id,
            }
        )

    @action(detail=True, methods=["get"], url_path="slack/status")
    def slack_status(self, request, pk=None):
        """Slack 공유 상태 확인"""
        meeting = self.get_object()

        return Response(
            {
                "shared": bool(meeting.slack_channel),
                "message_ts": meeting.slack_message_ts or None,
                "channel": meeting.slack_channel or None,
            }
        )
