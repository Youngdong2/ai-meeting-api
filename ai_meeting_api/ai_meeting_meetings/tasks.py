"""
회의록 처리 Celery Tasks

음성 파일 업로드 후 자동으로 실행되는 비동기 작업:
1. 음성 파일 압축 (ffmpeg)
2. STT 처리 (OpenAI gpt-4o-transcribe)
3. 텍스트 교정 (OpenAI gpt-4o-mini)
4. AI 요약 생성 (OpenAI gpt-4o-mini)
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from ai_meeting_integrations.openai_client import OpenAIClient, get_openai_client
from celery import shared_task
from django.utils import timezone

from .models import Meeting, MeetingStatus

logger = logging.getLogger(__name__)

# OpenAI API 제한: 최대 25분 (1500초)
# 여유를 두고 20분 단위로 분할
MAX_CHUNK_DURATION = 20 * 60  # 20분 (1200초)


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

        # 2. STT 처리 (긴 파일은 분할 처리)
        meeting.status = MeetingStatus.TRANSCRIBING
        meeting.save()
        client = get_openai_client(api_key)
        stt_result = transcribe_audio_with_split(compressed_path, client)

        meeting.transcript = stt_result["text"]
        meeting.speaker_data = stt_result["segments"]
        meeting.save()

        # 3. 텍스트 교정 (화자별 교정 + 전체 텍스트 교정)
        meeting.status = MeetingStatus.CORRECTING
        meeting.save()

        # 화자별 발언 데이터 교정 (채팅형 UI용)
        corrected_speaker_data = client.correct_speaker_data(stt_result["segments"])
        meeting.corrected_speaker_data = corrected_speaker_data

        # 교정된 화자별 데이터에서 전체 텍스트 생성
        corrected_text = " ".join([seg["text"] for seg in corrected_speaker_data])
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


def get_audio_duration(audio_path: str) -> float:
    """
    오디오 파일의 길이(초)를 반환

    Args:
        audio_path: 오디오 파일 경로

    Returns:
        float: 오디오 길이 (초)
    """
    try:
        # format과 stream 모두에서 duration을 가져오도록 설정
        # WebM 등 일부 포맷은 format에 duration이 없고 stream에만 있음
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration:stream=duration",
            "-of",
            "json",
            audio_path,
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)

        # 1. format.duration 확인
        duration_str = data.get("format", {}).get("duration")
        if duration_str:
            duration = float(duration_str)
            logger.info(f"Audio duration (format): {duration:.2f} seconds ({duration/60:.1f} minutes)")
            return duration

        # 2. streams[0].duration 확인 (WebM 등)
        streams = data.get("streams", [])
        if streams:
            for stream in streams:
                stream_duration = stream.get("duration")
                if stream_duration:
                    duration = float(stream_duration)
                    logger.info(f"Audio duration (stream): {duration:.2f} seconds ({duration/60:.1f} minutes)")
                    return duration

        # 3. duration을 찾을 수 없는 경우 - ffprobe로 직접 계산
        logger.warning(f"No duration in metadata, trying to probe directly: {audio_path}")
        return _get_duration_by_decode(audio_path)

    except subprocess.CalledProcessError as e:
        logger.warning(f"ffprobe failed for {audio_path}: {e.stderr}")
        return 0.0
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse ffprobe output for {audio_path}: {e}")
        return 0.0
    except FileNotFoundError:
        logger.warning("ffprobe not found")
        return 0.0


def _get_duration_by_decode(audio_path: str) -> float:
    """
    메타데이터에 duration이 없는 경우 파일을 디코딩하여 길이 계산

    Args:
        audio_path: 오디오 파일 경로

    Returns:
        float: 오디오 길이 (초), 실패 시 0.0
    """
    try:
        # -count_frames 옵션으로 실제 프레임 수 기반 계산
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            "-sexagesimal",  # 시:분:초.밀리초 형식
            audio_path,
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        output = result.stdout.strip()

        if output and output != "N/A":
            # HH:MM:SS.microseconds 형식 파싱
            parts = output.split(":")
            if len(parts) == 3:
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                duration = hours * 3600 + minutes * 60 + seconds
                logger.info(f"Audio duration (decoded): {duration:.2f} seconds ({duration/60:.1f} minutes)")
                return duration

        # 마지막 수단: ffmpeg로 전체 디코딩하여 계산
        command = [
            "ffmpeg",
            "-i",
            audio_path,
            "-f",
            "null",
            "-",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        # stderr에서 "time=" 패턴 찾기
        import re

        match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", result.stderr)
        if match:
            hours = float(match.group(1))
            minutes = float(match.group(2))
            seconds = float(match.group(3))
            duration = hours * 3600 + minutes * 60 + seconds
            logger.info(f"Audio duration (ffmpeg decode): {duration:.2f} seconds ({duration/60:.1f} minutes)")
            return duration

        logger.warning(f"Could not determine duration for {audio_path}")
        return 0.0

    except Exception as e:
        logger.warning(f"Failed to get duration by decode for {audio_path}: {e}")
        return 0.0


def split_audio_ffmpeg(audio_path: str, chunk_duration: int = MAX_CHUNK_DURATION) -> list[str]:
    """
    오디오 파일을 지정된 길이로 분할

    Args:
        audio_path: 원본 오디오 파일 경로
        chunk_duration: 청크당 최대 길이 (초)

    Returns:
        list[str]: 분할된 청크 파일 경로 목록
    """
    input_file = Path(audio_path)
    temp_dir = tempfile.mkdtemp(prefix="audio_chunks_")
    output_pattern = str(Path(temp_dir) / f"chunk_%03d{input_file.suffix}")

    try:
        command = [
            "ffmpeg",
            "-i",
            audio_path,
            "-f",
            "segment",
            "-segment_time",
            str(chunk_duration),
            "-reset_timestamps",
            "1",  # 메타데이터 리셋 (필수!)
            "-c",
            "copy",  # 재인코딩 없이 분할
            "-y",
            output_pattern,
        ]
        subprocess.run(command, check=True, capture_output=True)

        # 생성된 청크 파일 목록
        chunks = sorted(Path(temp_dir).glob(f"chunk_*{input_file.suffix}"))
        chunk_paths = [str(chunk) for chunk in chunks]

        logger.info(f"Split audio into {len(chunk_paths)} chunks")
        return chunk_paths

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to split audio: {e}")
        # 분할 실패 시 원본 반환
        return [audio_path]
    except FileNotFoundError:
        logger.error("ffmpeg not found for splitting")
        return [audio_path]


def transcribe_audio_with_split(audio_path: str, client: OpenAIClient) -> dict:
    """
    긴 오디오 파일을 분할하여 STT 처리 후 결과 병합

    Args:
        audio_path: 오디오 파일 경로
        client: OpenAI 클라이언트

    Returns:
        dict: {"text": 전체 텍스트, "segments": 화자별 세그먼트}
    """
    duration = get_audio_duration(audio_path)

    # 25분 이하면 단일 처리
    if duration <= MAX_CHUNK_DURATION or duration == 0:
        logger.info("Audio is short enough, processing as single file")
        return client.transcribe_audio(audio_path)

    logger.info(f"Audio is {duration/60:.1f} minutes, splitting into chunks")

    # 오디오 분할
    chunk_paths = split_audio_ffmpeg(audio_path, MAX_CHUNK_DURATION)

    if len(chunk_paths) == 1:
        # 분할 실패 또는 불필요
        return client.transcribe_audio(audio_path)

    all_text = []
    all_segments = []
    time_offset = 0.0

    try:
        for i, chunk_path in enumerate(chunk_paths):
            logger.info(f"Processing chunk {i+1}/{len(chunk_paths)}: {chunk_path}")

            # 각 청크 STT 처리
            result = client.transcribe_audio(chunk_path)
            all_text.append(result["text"])

            # 청크의 길이 가져오기
            chunk_duration = get_audio_duration(chunk_path)

            # 시간 오프셋 적용하여 세그먼트 병합
            for segment in result["segments"]:
                all_segments.append(
                    {
                        "speaker": segment["speaker"],
                        "start": segment["start"] + time_offset,
                        "end": segment["end"] + time_offset,
                        "text": segment["text"],
                    }
                )

            time_offset += chunk_duration
            logger.info(f"Chunk {i+1} completed, time offset: {time_offset:.2f}s")

    finally:
        # 임시 청크 파일들 정리
        for chunk_path in chunk_paths:
            if chunk_path != audio_path:  # 원본 파일은 삭제하지 않음
                Path(chunk_path).unlink(missing_ok=True)
        # 임시 디렉토리도 정리
        for chunk_path in chunk_paths:
            if chunk_path != audio_path:
                parent_dir = Path(chunk_path).parent
                if parent_dir.exists() and parent_dir.name.startswith("audio_chunks_"):
                    try:
                        parent_dir.rmdir()
                    except OSError:
                        pass  # 디렉토리가 비어있지 않으면 무시
                break

    merged_result = {
        "text": " ".join(all_text),
        "segments": all_segments,
    }

    logger.info(
        f"Merged {len(chunk_paths)} chunks: {len(merged_result['text'])} chars, "
        f"{len(merged_result['segments'])} segments"
    )

    return merged_result


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
        meeting_date_short = meeting.meeting_date.strftime("%m%d")
        meeting_date_full = meeting.meeting_date.strftime("%Y-%m-%d %H:%M")
        page_title = f"[회의록] {meeting_date_short} {meeting.title}"

        # 화자 분리된 전문 생성
        transcript_content = ""
        if meeting.speaker_data:
            # speaker_data에서 화자별 대화 추출
            for segment in meeting.speaker_data:
                speaker = segment.get("speaker", "Unknown")
                text = segment.get("text", "")
                if text:
                    transcript_content += f"<p><strong>{speaker}:</strong> {text}</p>\n"
        elif meeting.corrected_transcript:
            transcript_content = f"<p>{meeting.corrected_transcript}</p>"
        elif meeting.transcript:
            transcript_content = f"<p>{meeting.transcript}</p>"
        else:
            transcript_content = "<p>전문 없음</p>"

        # 마크다운을 Confluence 형식으로 변환
        summary_storage = markdown_to_confluence_storage(meeting.summary or "요약 없음")

        # Confluence Storage Format으로 직접 구성 (expand 매크로 포함)
        content_storage = f"""
<h1>{meeting.title}</h1>
<p><strong>회의 일시:</strong> {meeting_date_full}</p>
<p><strong>작성자:</strong> {meeting.created_by.username if meeting.created_by else "Unknown"}</p>
<hr/>
<h2>요약</h2>
{summary_storage}
<hr/>
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">전문 보기</ac:parameter>
  <ac:rich-text-body>
{transcript_content}
  </ac:rich-text-body>
</ac:structured-macro>
"""

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
            parent_id = team_setting.confluence_parent_page_id or None
            logger.info(f"Creating Confluence page with parent_id: {parent_id}, space_id: {space_id}")
            result = client.create_page(
                space_id=space_id,
                title=page_title,
                content=content_storage,
                parent_id=parent_id,
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
