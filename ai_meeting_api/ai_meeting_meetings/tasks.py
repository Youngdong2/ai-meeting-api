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


@shared_task(bind=True, max_retries=2)
def upload_to_confluence(self, meeting_id: int):
    """
    회의록을 Confluence 페이지로 업로드

    Args:
        meeting_id: 회의록 ID
    """
    from ai_meeting_integrations.confluence_client import (
        get_confluence_client,
        markdown_to_confluence_storage,
    )

    try:
        meeting = Meeting.objects.select_related("team").get(id=meeting_id)
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found")
        return {"success": False, "error": "회의록을 찾을 수 없습니다."}

    # 팀 설정에서 Confluence 설정 가져오기
    try:
        team_setting = meeting.team.setting
        if not all(
            [
                team_setting.confluence_site_url,
                team_setting.confluence_api_token,
                team_setting.confluence_user_email,
                team_setting.confluence_space_key,
            ]
        ):
            raise ValueError("Confluence 설정이 완료되지 않았습니다.")
    except Exception as e:
        logger.error(f"Confluence settings not configured for team {meeting.team.id}: {e}")
        return {"success": False, "error": str(e)}

    try:
        client = get_confluence_client(
            site_url=team_setting.confluence_site_url,
            user_email=team_setting.confluence_user_email,
            api_token=team_setting.confluence_api_token,
        )

        # 스페이스 ID 조회
        space_id = client.get_space_id_by_key(team_setting.confluence_space_key)
        if not space_id:
            raise ValueError(f"스페이스 '{team_setting.confluence_space_key}'를 찾을 수 없습니다.")

        # 페이지 내용 구성
        meeting_date_str = meeting.meeting_date.strftime("%Y-%m-%d %H:%M")
        page_title = f"[회의록] {meeting.title} ({meeting_date_str})"

        # 마크다운을 Confluence 형식으로 변환
        status_display = dict(MeetingStatus.choices).get(meeting.status, meeting.status)
        content_md = f"""# {meeting.title}

**회의 일시:** {meeting_date_str}
**작성자:** {meeting.created_by.username if meeting.created_by else "Unknown"}
**상태:** {status_display}

---

{meeting.summary or "요약 없음"}

---

## 전문

{meeting.corrected_transcript or meeting.transcript or "전문 없음"}
"""
        content_storage = markdown_to_confluence_storage(content_md)

        # 이미 업로드된 페이지가 있으면 업데이트, 없으면 생성
        if meeting.confluence_page_id:
            existing_page = client.get_page(meeting.confluence_page_id)
            if existing_page:
                version = existing_page.get("version", {}).get("number", 1)
                result = client.update_page(
                    page_id=meeting.confluence_page_id,
                    title=page_title,
                    content=content_storage,
                    version=version,
                )
                logger.info(f"Updated Confluence page for meeting {meeting_id}")
            else:
                # 페이지가 삭제된 경우 새로 생성
                result = client.create_page(
                    space_id=space_id,
                    title=page_title,
                    content=content_storage,
                    parent_id=team_setting.confluence_parent_page_id or None,
                )
                logger.info(f"Re-created Confluence page for meeting {meeting_id}")
        else:
            result = client.create_page(
                space_id=space_id,
                title=page_title,
                content=content_storage,
                parent_id=team_setting.confluence_parent_page_id or None,
            )
            logger.info(f"Created Confluence page for meeting {meeting_id}")

        # 결과 저장
        meeting.confluence_page_id = result["id"]
        meeting.confluence_page_url = result["url"]
        meeting.save()

        return {
            "success": True,
            "page_id": result["id"],
            "page_url": result["url"],
        }

    except Exception as e:
        logger.exception(f"Error uploading meeting {meeting_id} to Confluence: {e}")
        raise self.retry(exc=e, countdown=30) from e


@shared_task(bind=True, max_retries=2)
def share_to_slack(self, meeting_id: int, channel: str | None = None):
    """
    회의록 요약을 Slack 채널에 공유

    Args:
        meeting_id: 회의록 ID
        channel: Slack 채널 (없으면 팀 기본 채널 사용)
    """
    from ai_meeting_integrations.slack_client import format_meeting_message, get_slack_client
    from django.conf import settings

    try:
        meeting = Meeting.objects.select_related("team", "created_by").get(id=meeting_id)
    except Meeting.DoesNotExist:
        logger.error(f"Meeting {meeting_id} not found")
        return {"success": False, "error": "회의록을 찾을 수 없습니다."}

    # 팀 설정에서 Slack 설정 가져오기
    try:
        team_setting = meeting.team.setting
        webhook_url = team_setting.slack_webhook_url
        bot_token = team_setting.slack_bot_token
        default_channel = team_setting.slack_default_channel

        if not webhook_url and not bot_token:
            raise ValueError("Slack 설정이 완료되지 않았습니다.")
    except Exception as e:
        logger.error(f"Slack settings not configured for team {meeting.team.id}: {e}")
        return {"success": False, "error": str(e)}

    try:
        client = get_slack_client(webhook_url=webhook_url, bot_token=bot_token)

        # 앱 URL (설정에서 가져오거나 빈 문자열)
        app_url = getattr(settings, "APP_URL", "")
        message = format_meeting_message(meeting, app_url=app_url)

        # Bot Token이 있으면 Bot API 사용, 없으면 Webhook 사용
        if bot_token:
            target_channel = channel or default_channel
            if not target_channel:
                raise ValueError("채널이 지정되지 않았습니다.")

            result = client.send_bot_message(target_channel, message)

            if result.get("success"):
                meeting.slack_message_ts = result.get("ts", "")
                meeting.slack_channel = result.get("channel", target_channel)
                meeting.save()
                logger.info(f"Shared meeting {meeting_id} to Slack channel {target_channel}")
        else:
            result = client.send_webhook_message(message)
            if result.get("success"):
                meeting.slack_channel = "webhook"
                meeting.save()
                logger.info(f"Shared meeting {meeting_id} via Slack webhook")

        return result

    except Exception as e:
        logger.exception(f"Error sharing meeting {meeting_id} to Slack: {e}")
        raise self.retry(exc=e, countdown=30) from e
