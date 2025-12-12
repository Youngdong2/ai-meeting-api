"""
OpenAI API 클라이언트 모듈

STT(음성-텍스트 변환), 텍스트 교정, AI 요약 기능 제공
"""

import json
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
                model="gpt-4o-transcribe-diarize",
                file=audio_file,
                language=language,
                response_format="diarized_json",
                chunking_strategy="auto",
            )

        return {
            "text": response.text,
            "segments": [
                {
                    "speaker": getattr(segment, "speaker", ""),
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

    def correct_speaker_data(self, speaker_data: list[dict]) -> list[dict]:
        """
        화자별 발언 데이터를 교정 (채팅형 전문 표시용)

        Args:
            speaker_data: STT 원본 화자별 발언 데이터
                [{"speaker": "Speaker 0", "text": "...", "start": 0.0, "end": 5.2}, ...]

        Returns:
            list[dict]: 교정된 화자별 발언 데이터 (동일 형식)
        """
        if not speaker_data:
            return []

        # 입력 데이터를 JSON 문자열로 변환
        input_json = json.dumps(speaker_data, ensure_ascii=False, indent=2)

        prompt = """다음은 회의 음성을 텍스트로 변환한 화자별 발언 데이터입니다.
각 발언의 text 필드만 아래 기준으로 교정하고, 동일한 JSON 형식으로 반환해주세요:

1. 맞춤법과 띄어쓰기 교정
2. STT 오인식으로 보이는 단어를 문맥에 맞게 수정
3. 불완전한 문장을 자연스럽게 보완
4. speaker, start, end 값은 절대 변경하지 마세요

원본의 의미와 화자 발언 순서를 변경하지 마세요.
반드시 유효한 JSON 배열만 출력하세요. 다른 설명은 포함하지 마세요.

---
입력:
"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 한국어 텍스트 교정 전문가입니다. JSON 형식의 데이터를 받아 text 필드만 교정하여 동일한 JSON 형식으로 반환합니다.",
                    },
                    {"role": "user", "content": prompt + input_json},
                ],
                temperature=0.3,
            )

            result_text = response.choices[0].message.content or "[]"

            # JSON 파싱 시도
            # 마크다운 코드 블록 제거 (```json ... ```)
            result_text = result_text.strip()
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                # 첫 번째와 마지막 줄 제거
                result_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                result_text = result_text.strip()

            corrected_data = json.loads(result_text)

            # 검증: 원본과 동일한 개수인지 확인
            if len(corrected_data) != len(speaker_data):
                logger.warning(f"Corrected data count mismatch: {len(corrected_data)} vs {len(speaker_data)}")
                return speaker_data

            # speaker, start, end 값이 유지되었는지 확인하고 복원
            for original, corrected in zip(speaker_data, corrected_data, strict=False):
                corrected["speaker"] = original["speaker"]
                corrected["start"] = original["start"]
                corrected["end"] = original["end"]

            return corrected_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse corrected speaker data JSON: {e}")
            return speaker_data
        except Exception as e:
            logger.error(f"Error correcting speaker data: {e}")
            return speaker_data

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
