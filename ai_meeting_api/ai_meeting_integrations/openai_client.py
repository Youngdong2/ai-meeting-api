"""
OpenAI API 클라이언트 모듈

STT(음성-텍스트 변환), 텍스트 교정, AI 요약 기능 제공
"""

import logging
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI API 클라이언트"""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def transcribe_audio(
        self,
        audio_file_path: str | Path,
        language: str = "ko",
    ) -> dict:
        """
        음성 파일을 텍스트로 변환 (STT)

        Args:
            audio_file_path: 음성 파일 경로
            language: 언어 코드 (기본: 한국어)

        Returns:
            dict: {
                "text": 전체 텍스트,
                "segments": [{"start": 0.0, "end": 5.2, "text": "..."}],
            }
        """
        audio_path = Path(audio_file_path)

        with open(audio_path, "rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=audio_file,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        return {
            "text": response.text,
            "segments": [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
                for segment in (response.segments or [])
            ],
        }

    def correct_transcript(self, transcript: str) -> str:
        """
        STT 결과 텍스트 교정

        Args:
            transcript: 교정할 텍스트

        Returns:
            str: 교정된 텍스트
        """
        prompt = """다음은 회의 음성을 텍스트로 변환한 내용입니다.
아래 기준으로 교정해주세요:

1. 맞춤법과 띄어쓰기 교정
2. STT 오인식으로 보이는 단어를 문맥에 맞게 수정
3. 불완전한 문장을 자연스럽게 보완
4. 화자 구분은 그대로 유지

원본의 의미와 화자 발언 순서를 변경하지 마세요.
교정된 텍스트만 출력하세요.

---
"""
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 한국어 텍스트 교정 전문가입니다."},
                {"role": "user", "content": prompt + transcript},
            ],
            temperature=0.3,
        )

        return response.choices[0].message.content or transcript

    def generate_summary(self, transcript: str) -> str:
        """
        회의 내용 요약 생성

        Args:
            transcript: 회의 전문 텍스트

        Returns:
            str: 마크다운 형식의 요약
        """
        prompt = """다음 회의 내용을 분석하여 아래 형식으로 요약해주세요:

## 회의 요약

### 참석자
- (화자 기반으로 추출)

### 주요 논의 사항
1. [주제]: 내용 요약
...

### 결정 사항
- [결정 내용]
...

### 액션 아이템
- [ ] [할 일] - 담당: [화자]
...

---
회의 내용:
"""
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 회의록 요약 전문가입니다. 구조화된 마크다운 형식으로 요약을 작성합니다.",
                },
                {"role": "user", "content": prompt + transcript},
            ],
            temperature=0.5,
        )

        return response.choices[0].message.content or ""


def get_openai_client(api_key: str) -> OpenAIClient:
    """OpenAI 클라이언트 인스턴스 생성"""
    return OpenAIClient(api_key=api_key)
