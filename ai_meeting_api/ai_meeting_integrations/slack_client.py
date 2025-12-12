"""
Slack API 클라이언트 모듈

회의록 요약을 Slack 채널에 공유하는 기능 제공
"""

import logging

import requests

logger = logging.getLogger(__name__)


class SlackClient:
    """Slack API 클라이언트"""

    def __init__(self, webhook_url: str | None = None, bot_token: str | None = None):
        """
        Args:
            webhook_url: Incoming Webhook URL (간단한 메시지 전송용)
            bot_token: Bot User OAuth Token (고급 기능용)
        """
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.api_url = "https://slack.com/api"

    def send_webhook_message(self, message: dict) -> dict:
        """
        Incoming Webhook으로 메시지 전송

        Args:
            message: Slack Block Kit 형식의 메시지

        Returns:
            dict: {"success": True/False, "error": "..."}
        """
        if not self.webhook_url:
            return {"success": False, "error": "Webhook URL이 설정되지 않았습니다."}

        try:
            response = requests.post(
                self.webhook_url,
                json=message,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code == 200 and response.text == "ok":
                return {"success": True}
            else:
                return {"success": False, "error": response.text}

        except requests.RequestException as e:
            logger.exception(f"Slack webhook error: {e}")
            return {"success": False, "error": str(e)}

    def send_bot_message(self, channel: str, message: dict) -> dict:
        """
        Bot API로 메시지 전송

        Args:
            channel: 채널 ID 또는 이름 (예: "#general", "C1234567890")
            message: Slack Block Kit 형식의 메시지

        Returns:
            dict: {"success": True/False, "ts": "메시지 타임스탬프", "channel": "채널 ID"}
        """
        if not self.bot_token:
            return {"success": False, "error": "Bot Token이 설정되지 않았습니다."}

        try:
            payload = {
                "channel": channel,
                **message,
            }

            response = requests.post(
                f"{self.api_url}/chat.postMessage",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.bot_token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            data = response.json()

            if data.get("ok"):
                return {
                    "success": True,
                    "ts": data.get("ts"),
                    "channel": data.get("channel"),
                }
            else:
                return {"success": False, "error": data.get("error", "Unknown error")}

        except requests.RequestException as e:
            logger.exception(f"Slack bot API error: {e}")
            return {"success": False, "error": str(e)}


def get_slack_client(webhook_url: str | None = None, bot_token: str | None = None) -> SlackClient:
    """Slack 클라이언트 인스턴스 생성"""
    return SlackClient(webhook_url=webhook_url, bot_token=bot_token)


def format_meeting_message(meeting, app_url: str = "") -> dict:
    """
    회의록을 Slack Block Kit 메시지로 포맷팅

    Args:
        meeting: Meeting 모델 인스턴스
        app_url: 애플리케이션 URL (선택)

    Returns:
        dict: Slack Block Kit 형식의 메시지
    """
    meeting_date_str = meeting.meeting_date.strftime("%Y-%m-%d %H:%M")

    # 요약 텍스트 (3000자 제한)
    summary_text = meeting.summary or "요약 없음"
    if len(summary_text) > 2500:
        summary_text = summary_text[:2500] + "\n\n... (이하 생략)"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📋 {meeting.title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*회의 일시:*\n{meeting_date_str}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*작성자:*\n{meeting.created_by.username if meeting.created_by else 'Unknown'}",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": summary_text,
            },
        },
    ]

    # 앱 URL이 있으면 버튼 추가
    if app_url:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📄 전문 보기",
                            "emoji": True,
                        },
                        "url": f"{app_url}/meetings/{meeting.id}",
                        "action_id": "view_full_meeting",
                    },
                ],
            }
        )

    return {"blocks": blocks}
