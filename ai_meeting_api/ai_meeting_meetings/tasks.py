"""
회의록 처리 Celery Tasks

음성 파일 업로드 후 자동으로 실행되는 비동기 작업:
1. 음성 파일 압축 (ffmpeg)
2. STT 처리 (OpenAI gpt-4o-transcribe)
3. 텍스트 교정 (OpenAI gpt-4o-mini)
4. AI 요약 생성 (OpenAI gpt-4o-mini)
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from ai_meeting_integrations.openai_client import get_openai_client
from celery import shared_task
from django.utils import timezone

from .models import Meeting, MeetingStatus

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_meeting_audio(self, meeting_id: int):
    """
    회의록 음성 파일 전체 처리 파이프라인

    1. 음성 파일 압축
    2. STT 처리
    3. 텍스트 교정
    4. AI 요약 생성
    """
    try:
        meeting = Meeting.objects.select_related("team").get(id=meeting_id)
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found")
        return

    if not meeting.audio_file:
        logger.error(f"Meeting {meeting_id} has no audio file")
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = "음성 파일이 없습니다."
        meeting.save()
        return

    # 팀 설정에서 API 키 가져오기
    try:
        team_setting = meeting.team.setting
        api_key = team_setting.openai_api_key
        if not api_key:
            raise ValueError("OpenAI API 키가 설정되지 않았습니다.")
    except Exception as e:
        logger.error(f"Failed to get API key for meeting {meeting_id}: {e}")
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = str(e)
        meeting.save()
        return

    try:
        # 1. 음성 파일 압축
        meeting.status = MeetingStatus.COMPRESSING
        meeting.save()
        compressed_path = compress_audio(meeting.audio_file.path)

        # 2. STT 처리
        meeting.status = MeetingStatus.TRANSCRIBING
        meeting.save()
        client = get_openai_client(api_key)
        stt_result = client.transcribe_audio(compressed_path)

        meeting.transcript = stt_result["text"]
        meeting.speaker_data = stt_result["segments"]
        meeting.save()

        # 3. 텍스트 교정
        meeting.status = MeetingStatus.CORRECTING
        meeting.save()
        corrected_text = client.correct_transcript(stt_result["text"])
        meeting.corrected_transcript = corrected_text
        meeting.save()

        # 4. AI 요약 생성
        meeting.status = MeetingStatus.SUMMARIZING
        meeting.save()
        summary = client.generate_summary(corrected_text)
        meeting.summary = summary
        meeting.save()

        # 완료
        meeting.status = MeetingStatus.COMPLETED
        meeting.error_message = ""
        meeting.save()

        # 임시 압축 파일 삭제
        if compressed_path != meeting.audio_file.path:
            Path(compressed_path).unlink(missing_ok=True)

        logger.info(f"Meeting {meeting_id} processing completed")

    except Exception as e:
        logger.exception(f"Error processing meeting {meeting_id}: {e}")
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = str(e)
        meeting.save()

        # 재시도
        raise self.retry(exc=e, countdown=60) from e


def compress_audio(input_path: str) -> str:
    """
    음성 파일 압축 (ffmpeg 사용)

    Args:
        input_path: 원본 음성 파일 경로

    Returns:
        str: 압축된 파일 경로
    """
    input_file = Path(input_path)

    # 이미 작은 파일은 압축 스킵 (10MB 이하)
    if input_file.stat().st_size <= 10 * 1024 * 1024:
        return input_path

    # 임시 출력 파일 생성
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        output_path = tmp.name

    try:
        command = [
            "ffmpeg",
            "-i",
            input_path,
            "-ac",
            "1",  # 모노 채널
            "-ar",
            "16000",  # 16kHz 샘플레이트
            "-b:a",
            "64k",  # 64kbps 비트레이트
            "-y",  # 덮어쓰기
            output_path,
        ]
        subprocess.run(command, check=True, capture_output=True)
        logger.info(f"Compressed {input_path} -> {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.warning(f"ffmpeg compression failed: {e}, using original file")
        Path(output_path).unlink(missing_ok=True)
        return input_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found, using original file")
        return input_path


@shared_task
def regenerate_summary(meeting_id: int):
    """요약만 재생성"""
    try:
        meeting = Meeting.objects.select_related("team").get(id=meeting_id)
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found")
        return

    text = meeting.corrected_transcript or meeting.transcript
    if not text:
        logger.error(f"Meeting {meeting_id} has no transcript")
        return

    try:
        team_setting = meeting.team.setting
        api_key = team_setting.openai_api_key
        if not api_key:
            raise ValueError("OpenAI API 키가 설정되지 않았습니다.")

        meeting.status = MeetingStatus.SUMMARIZING
        meeting.save()

        client = get_openai_client(api_key)
        summary = client.generate_summary(text)

        meeting.summary = summary
        meeting.status = MeetingStatus.COMPLETED
        meeting.error_message = ""
        meeting.save()

        logger.info(f"Meeting {meeting_id} summary regenerated")

    except Exception as e:
        logger.exception(f"Error regenerating summary for meeting {meeting_id}: {e}")
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = str(e)
        meeting.save()


@shared_task
def cleanup_expired_audio_files():
    """만료된 음성 파일 삭제 (90일 경과)"""
    expired_meetings = Meeting.objects.filter(
        audio_file_expires_at__lte=timezone.now(),
        audio_file__isnull=False,
    ).exclude(audio_file="")

    count = 0
    for meeting in expired_meetings:
        try:
            meeting.audio_file.delete(save=False)
            meeting.audio_file = None
            meeting.audio_file_expires_at = None
            meeting.save()
            count += 1
            logger.info(f"Deleted expired audio for meeting {meeting.id}")
        except Exception as e:
            logger.error(f"Failed to delete audio for meeting {meeting.id}: {e}")

    logger.info(f"Cleaned up {count} expired audio files")
    return count
