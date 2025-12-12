# AI Meeting API - 백엔드 기획서

## 0. 확정된 결정사항

| 항목 | 결정 |
|------|------|
| 데이터베이스 | PostgreSQL |
| 파일 스토리지 | 로컬 파일 시스템 (1차), 프로덕션 시 S3 전환 |
| 비동기 처리 | Celery + Redis |
| 배포 환경 | 사내 서버 (1차), 향후 클라우드 이전 가능 |
| 팀 구조 | 사용자가 프로필에서 팀 선택, 팀별 회의록 분리 |
| 관리자 기능 | 특정 사용자에게 팀 관리자 권한 부여 (is_team_admin) |
| 회의록 권한 | 모든 팀원이 수정/삭제 가능 |
| 녹음 방식 | 프론트엔드에서 실시간 녹음 → 완료 후 파일 업로드 |
| STT 처리 | 업로드 시 자동 시작 (클로바노트 방식) |
| 긴 녹음 처리 | 서버에서 25분 단위로 자동 분할 후 병합 |
| OpenAI API Key | 팀별 관리 (TeamSetting에 저장) |
| 인증 방식 | 현재 이메일/비밀번호 JWT 유지 |

---

## 1. 프로젝트 개요

### 1.1 목적
팀 회의 음성을 녹음하고, AI를 활용하여 자동으로 텍스트 변환(화자 분리 포함) 및 요약을 생성하는 웹 애플리케이션의 **백엔드 API 서버**

### 1.2 주요 사용자
- AI팀 (초기 사용자)
- 향후 다른 팀으로 확장 가능

---

## 2. 기술 스택

### 2.1 현재 구현 완료
| 기술 | 버전 | 용도 |
|------|------|------|
| Python | 3.11+ | 런타임 |
| Django | 5.1 | 웹 프레임워크 |
| Django REST Framework | 3.16.1 | REST API |
| djangorestframework-simplejwt | 5.5.1 | JWT 인증 |
| django-cors-headers | 4.9.0 | CORS 지원 |
| uv | - | 패키지 관리 |

### 2.2 추가 필요 기술
| 기술 | 용도 |
|------|------|
| PostgreSQL | 프로덕션 데이터베이스 (한국어 검색 지원) |
| psycopg2-binary | PostgreSQL 드라이버 |
| openai | OpenAI API 클라이언트 |
| celery + redis | 비동기 작업 큐 (STT, 요약 처리) |
| ffmpeg | 음성 파일 압축 (시스템 패키지) |
| django-storages | 파일 스토리지 추상화 (향후 S3 전환 대비) |
| requests | Confluence API 연동 |
| django-celery-beat | 스케줄러 (90일 파일 삭제) |

---

## 3. 데이터베이스 설계

### 3.1 ERD 개요

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│    Team     │────<│    User     │────<│     Meeting     │
└─────────────┘     └─────────────┘     └─────────────────┘
       │                                        │
       │            ┌─────────────────┐         │
       └───────────>│   TeamSetting   │         │
                    └─────────────────┘         │
                                                │
                    ┌─────────────────┐         │
                    │  SpeakerMapping │<────────┘
                    └─────────────────┘
```

### 3.2 모델 상세

#### Team (팀)
```python
class Team(models.Model):
    id: AutoField (PK)
    name: CharField(100)           # 팀 이름 (예: "AI팀")
    description: TextField         # 팀 설명
    created_at: DateTimeField
    updated_at: DateTimeField
```

#### User (사용자) - 기존 모델 확장
```python
class User(AbstractBaseUser):
    # 기존 필드 유지
    ...
    team: ForeignKey(Team)         # 소속 팀 (추가)
    is_team_admin: BooleanField    # 팀 관리자 여부 (추가) - 팀 설정 관리 권한
```

#### TeamSetting (팀 설정)
```python
class TeamSetting(models.Model):
    id: AutoField (PK)
    team: OneToOneField(Team)

    # OpenAI 설정
    openai_api_key: CharField(500, encrypted)  # 암호화 저장

    # Confluence 설정 (선택)
    confluence_site_url: URLField(null=True)   # 예: https://company.atlassian.net
    confluence_api_token: CharField(500, encrypted, null=True)
    confluence_space_key: CharField(50, null=True)  # 예: "AIDEV"
    confluence_parent_page_id: CharField(50, null=True)  # 상위 페이지 ID

    # Slack 설정 (선택)
    slack_webhook_url: URLField(null=True)     # Incoming Webhook URL
    slack_bot_token: CharField(500, encrypted, null=True)  # Bot User OAuth Token
    slack_default_channel: CharField(100, null=True)  # 기본 알림 채널 (예: #meeting-notes)

    created_at: DateTimeField
    updated_at: DateTimeField
```

#### Meeting (회의록)
```python
class Meeting(models.Model):
    id: AutoField (PK)
    team: ForeignKey(Team)
    created_by: ForeignKey(User)

    # 기본 정보
    title: CharField(200)
    meeting_date: DateTimeField

    # 음성 파일
    audio_file: FileField          # 음성 파일 경로
    audio_file_expires_at: DateTimeField  # 삭제 예정일 (생성일 + 90일)

    # STT 결과
    transcript: TextField          # STT 원본 텍스트
    speaker_data: JSONField        # 화자별 발언 데이터
    # 예: [{"speaker": "Speaker 0", "text": "...", "start": 0.0, "end": 5.2}, ...]

    # 교정된 텍스트
    corrected_transcript: TextField  # 맞춤법/문맥 교정된 텍스트

    # AI 요약
    summary: TextField             # 마크다운 형식 요약

    # 상태
    status: CharField(20)          # pending, compressing, transcribing, correcting, summarizing, completed, failed

    # Confluence 연동
    confluence_page_id: CharField(50, null=True)  # 업로드된 페이지 ID
    confluence_page_url: URLField(null=True)

    # Slack 연동
    slack_message_ts: CharField(50, null=True)    # 공유된 메시지 타임스탬프
    slack_channel: CharField(100, null=True)      # 공유된 채널

    created_at: DateTimeField
    updated_at: DateTimeField
```

#### SpeakerMapping (화자 이름 매핑)
```python
class SpeakerMapping(models.Model):
    id: AutoField (PK)
    meeting: ForeignKey(Meeting)
    speaker_label: CharField(50)   # "Speaker 0", "Speaker 1" 등
    speaker_name: CharField(100)   # 실제 이름 "김영도", "홍길동" 등
    created_at: DateTimeField
```

---

## 4. API 엔드포인트 설계

### 4.1 인증 (기존 구현 완료)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/v1/users/auth/signup` | 회원가입 |
| POST | `/v1/users/auth/login` | 로그인 |
| POST | `/v1/users/token/refresh` | 토큰 갱신 |

### 4.2 사용자/팀 (확장 필요)
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/v1/users/profile/me` | 내 정보 조회 (기존) |
| PATCH | `/v1/users/profile/update` | 프로필 수정 (팀 선택 추가) |
| GET | `/v1/teams/` | 팀 목록 조회 |
| GET | `/v1/teams/{id}/` | 팀 상세 조회 |

### 4.3 팀 설정 (팀 관리자만 접근 가능)
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/v1/teams/{id}/settings/` | 팀 설정 조회 |
| PATCH | `/v1/teams/{id}/settings/` | 팀 설정 수정 (API Key, Confluence 등) |

### 4.4 관리자 기능 (팀 관리자만)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/v1/teams/` | 팀 생성 (is_staff 사용자만) |
| PATCH | `/v1/teams/{id}/` | 팀 정보 수정 |
| POST | `/v1/teams/{id}/members/{user_id}/admin/` | 팀 관리자 권한 부여 |
| DELETE | `/v1/teams/{id}/members/{user_id}/admin/` | 팀 관리자 권한 해제 |

### 4.5 회의록 (모든 팀원 수정/삭제 가능)
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/v1/meetings/` | 회의록 목록 (팀 기준, 검색/페이징) |
| POST | `/v1/meetings/` | 회의록 생성 (음성 파일 업로드 → 자동 STT 시작) |
| GET | `/v1/meetings/{id}/` | 회의록 상세 |
| PATCH | `/v1/meetings/{id}/` | 회의록 수정 (제목, 요약 등) |
| DELETE | `/v1/meetings/{id}/` | 회의록 삭제 |
| POST | `/v1/meetings/{id}/transcribe/` | STT 수동 재실행 |
| POST | `/v1/meetings/{id}/summarize/` | 요약 수동 재생성 |
| GET | `/v1/meetings/{id}/status/` | 처리 상태 조회 |

### 4.6 화자 매핑
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/v1/meetings/{id}/speakers/` | 화자 목록 조회 |
| PATCH | `/v1/meetings/{id}/speakers/` | 화자 이름 일괄 매핑 |

### 4.7 Confluence 연동 (선택)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/v1/meetings/{id}/confluence/upload/` | Confluence에 업로드 |
| GET | `/v1/meetings/{id}/confluence/status/` | 업로드 상태 확인 |

### 4.8 Slack 연동 (선택)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/v1/meetings/{id}/slack/share/` | Slack 채널에 요약 공유 |
| GET | `/v1/meetings/{id}/slack/status/` | 공유 상태 확인 |

### 4.9 검색
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/v1/meetings/search/?q=키워드` | 회의록 검색 (제목, 전문, 요약) |

---

## 5. 핵심 기능 상세

### 5.1 음성 처리 전체 Flow

```
[프론트엔드]                    [백엔드]                      [OpenAI]
     │                            │                            │
     │  1. POST /meetings/        │                            │
     │     (audio file upload)    │                            │
     │ ────────────────────────>  │                            │
     │                            │  2. 파일 저장              │
     │                            │     (로컬 스토리지)         │
     │                            │                            │
     │  3. 202 Accepted           │                            │
     │     {meeting_id, status}   │                            │
     │ <────────────────────────  │                            │
     │                            │                            │
     │                            │  ┌─ Celery Pipeline ─────────────────┐
     │                            │  │                                   │
     │                            │  │  4. 음성 압축 (ffmpeg)            │
     │                            │  │     status: compressing           │
     │                            │  │           ↓                       │
     │                            │  │  5. STT 처리 ─────────────────────│──> gpt-4o-transcribe
     │                            │  │     status: transcribing          │
     │                            │  │           ↓                       │
     │                            │  │  6. 텍스트 교정 ──────────────────│──> gpt-4o-mini
     │                            │  │     status: correcting            │
     │                            │  │           ↓                       │
     │                            │  │  7. AI 요약 ──────────────────────│──> gpt-4o-mini
     │                            │  │     status: summarizing           │
     │                            │  │           ↓                       │
     │                            │  │  8. 완료                          │
     │                            │  │     status: completed             │
     │                            │  └───────────────────────────────────┘
     │                            │                            │
     │  9. GET /meetings/{id}/    │                            │
     │     status/ (폴링)         │                            │
     │ ────────────────────────>  │                            │
     │                            │                            │
     │ 10. {status: "completed"}  │                            │
     │ <────────────────────────  │                            │
```

### 5.2 음성 파일 압축

업로드된 음성 파일의 용량 최적화:
- 도구: `ffmpeg`
- 목적: 스토리지 절약 및 OpenAI API 업로드 속도 향상
- 압축 설정:
  - 코덱: AAC 또는 MP3
  - 비트레이트: 64-128kbps (음성에 적합)
  - 샘플레이트: 16kHz (STT 최적)

```python
def compress_audio(input_path, output_path):
    """음성 파일 압축 (ffmpeg 사용)"""
    command = [
        'ffmpeg', '-i', input_path,
        '-ac', '1',           # 모노 채널
        '-ar', '16000',       # 16kHz 샘플레이트
        '-b:a', '64k',        # 64kbps 비트레이트
        '-y', output_path
    ]
    subprocess.run(command, check=True)
```

### 5.3 텍스트 교정 처리

STT 결과물의 품질 향상을 위한 교정 단계:
- 모델: `gpt-4o-mini`
- 시점: STT 완료 후, 요약 전
- 교정 항목:
  - 맞춤법/띄어쓰기 교정
  - 문맥에 맞지 않는 단어 수정 (STT 오인식)
  - 불완전한 문장 보완
  - 자연스러운 흐름으로 정리

**교정 프롬프트 템플릿:**
```
다음은 회의 음성을 텍스트로 변환한 내용입니다.
아래 기준으로 교정해주세요:

1. 맞춤법과 띄어쓰기 교정
2. STT 오인식으로 보이는 단어를 문맥에 맞게 수정
3. 불완전한 문장을 자연스럽게 보완
4. 화자 구분은 그대로 유지

원본의 의미와 화자 발언 순서를 변경하지 마세요.

---
{raw_transcript}
```

### 5.4 AI 요약 처리

텍스트 교정 완료 후 자동으로 요약 Task 실행:
- 모델: `gpt-4o-mini`
- 입력: 교정된 전문 텍스트 (corrected_transcript)
- 출력: 구조화된 마크다운 요약

**요약 프롬프트 템플릿:**
```
다음 회의 내용을 분석하여 아래 형식으로 요약해주세요:

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
{transcript}
```

### 5.5 긴 오디오 파일 분할 처리

#### 5.5.1 OpenAI API 제한사항
| 항목 | 제한 |
|------|------|
| 파일 크기 | 25MB |
| 오디오 길이 | **1500초 (25분)** |
| 모델 | gpt-4o-transcribe-diarize |

#### 5.5.2 녹음 방식
- **프론트엔드**: Web Audio API / MediaRecorder API로 브라우저에서 실시간 녹음
- **녹음 완료 후**: Blob/File로 변환하여 기존 업로드 API 사용
- **백엔드 변경 불필요**: 프론트엔드에서 녹음 UI만 추가

#### 5.5.3 긴 파일 처리 흐름
```
[프론트엔드] 녹음 (30분~2시간)
    ↓
[프론트엔드] 녹음 완료 → Blob → 업로드
    ↓
[백엔드] 파일 저장
    ↓
[백엔드] 오디오 길이 체크
    ├─ 25분 이하 → 기존 단일 STT 처리
    └─ 25분 초과 → ffmpeg로 20분 단위 분할
                    ↓
                각 청크별 STT 처리 (순차)
                    ↓
                결과 병합 (transcript, speaker_data)
                    ↓
                교정 → 요약 (기존 흐름)
```

#### 5.5.4 분할 처리 로직
```python
MAX_CHUNK_DURATION = 20 * 60  # 20분 (여유를 두고 25분 제한 대비)

def split_audio_if_needed(audio_path: str) -> list[str]:
    """오디오 파일이 25분 초과 시 20분 단위로 분할"""
    duration = get_audio_duration(audio_path)

    if duration <= MAX_CHUNK_DURATION:
        return [audio_path]

    # ffmpeg로 20분 단위 분할
    # -f segment -segment_time 1200 (20분)
    # -reset_timestamps 1 (메타데이터 리셋 필수)
    chunks = split_audio_ffmpeg(audio_path, MAX_CHUNK_DURATION)
    return chunks

def transcribe_long_audio(audio_path: str, client: OpenAIClient) -> dict:
    """긴 오디오 파일 분할 STT 처리"""
    chunks = split_audio_if_needed(audio_path)

    all_text = []
    all_segments = []
    time_offset = 0.0

    for chunk_path in chunks:
        result = client.transcribe_audio(chunk_path)
        all_text.append(result["text"])

        # 시간 오프셋 적용하여 세그먼트 병합
        for segment in result["segments"]:
            all_segments.append({
                "speaker": segment["speaker"],
                "start": segment["start"] + time_offset,
                "end": segment["end"] + time_offset,
                "text": segment["text"],
            })

        time_offset += get_audio_duration(chunk_path)

    return {
        "text": " ".join(all_text),
        "segments": all_segments,
    }
```

#### 5.5.5 주의사항
- **`-reset_timestamps 1`**: ffmpeg 분할 시 필수 (메타데이터 리셋)
- **화자 연속성**: 분할 경계에서 동일 화자가 다른 라벨로 인식될 수 있음 (후처리 필요 시 검토)
- **파일 크기 제한 상향**: 100MB → 500MB (긴 녹음 지원)

### 5.6 음성 파일 자동 삭제 (90일)

Celery Beat 스케줄러로 매일 실행:
```python
@celery_app.task
def cleanup_expired_audio_files():
    expired = Meeting.objects.filter(
        audio_file_expires_at__lte=timezone.now(),
        audio_file__isnull=False
    )
    for meeting in expired:
        meeting.audio_file.delete()
        meeting.audio_file = None
        meeting.save()
```

### 5.7 Slack 연동

회의록 요약을 Slack 채널에 공유:
- 방식: Incoming Webhook 또는 Bot API
- 공유 내용: 회의 제목, 요약, 액션 아이템
- 채널 선택: 기본 채널 또는 사용자 지정

**Slack 메시지 포맷:**
```python
def format_slack_message(meeting):
    """Slack Block Kit 형식으로 메시지 생성"""
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📋 {meeting.title}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*회의 일시:* {meeting.meeting_date}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": meeting.summary[:2000]}  # Slack 제한
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "전문 보기"},
                        "url": f"{APP_URL}/meetings/{meeting.id}"
                    }
                ]
            }
        ]
    }
```

### 5.8 한국어 검색

PostgreSQL 기반 전문 검색:
```python
from django.contrib.postgres.search import SearchVector, SearchQuery

Meeting.objects.annotate(
    search=SearchVector('title', 'transcript', 'summary')
).filter(
    search=SearchQuery(query, search_type='plain')
)
```

---

## 6. 프로젝트 구조 (확장)

```
ai_meeting_api/
├── ai_meeting_api/           # 프로젝트 설정 (기존)
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   ├── celery.py             # (신규) Celery 설정
│   └── ...
│
├── ai_meeting_commons/       # 공통 기능 (기존)
│   ├── exceptions.py
│   ├── renderers.py
│   ├── permissions.py
│   └── ...
│
├── ai_meeting_users/         # 사용자 관리 (기존, 확장)
│   ├── models.py             # User 모델에 team FK 추가
│   └── ...
│
├── ai_meeting_teams/         # (신규) 팀 관리
│   ├── models.py             # Team, TeamSetting
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
│
├── ai_meeting_meetings/      # (신규) 회의록 관리
│   ├── models.py             # Meeting, SpeakerMapping
│   ├── views.py
│   ├── serializers.py
│   ├── urls.py
│   └── tasks.py              # Celery 비동기 작업
│
├── ai_meeting_integrations/  # (신규) 외부 연동
│   ├── openai_client.py      # OpenAI API 래퍼
│   ├── confluence_client.py  # Confluence API 래퍼
│   ├── slack_client.py       # Slack API 래퍼
│   └── ...
│
└── media/                    # (신규) 업로드 파일 저장
    └── audio/                # 음성 파일
```

---

## 7. 구현 순서 (권장)

### Phase 1: 기반 구축
1. PostgreSQL 설정 및 마이그레이션
2. Celery + Redis 설정
3. 파일 업로드 설정 (로컬 스토리지)

### Phase 2: 팀 기능
4. Team, TeamSetting 모델 및 API
5. User 모델에 team FK 추가
6. 팀 선택 기능

### Phase 3: 회의록 기본
7. Meeting 모델 및 CRUD API
8. 음성 파일 업로드

### Phase 4: AI 기능
9. 음성 파일 압축 (ffmpeg)
10. OpenAI 연동 (STT)
11. 텍스트 교정 기능
12. OpenAI 연동 (요약)
13. 화자 매핑 기능

### Phase 5: 부가 기능
14. 검색 기능
15. Confluence 연동 (선택)
16. Slack 연동 (선택)
17. 음성 파일 자동 삭제 스케줄러

---

## 8. 환경 설정

### 8.1 필요한 환경 변수
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/ai_meeting

# Redis (Celery)
REDIS_URL=redis://localhost:6379/0

# Django
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=your-domain.com

# File Storage
MEDIA_ROOT=/path/to/media
```

### 8.2 서버 요구사항
- PostgreSQL 14+
- Redis 6+
- Python 3.11+

---

## 9. 보안 고려사항

1. **API Key 암호화**: TeamSetting의 API Key는 암호화하여 저장
2. **파일 접근 제어**: 음성 파일은 인증된 사용자만 접근 가능
3. **팀 권한 분리**: 다른 팀의 회의록 접근 불가
4. **Rate Limiting**: API 호출 제한 (향후 구현)

---

## 10. 1차 MVP 범위 체크리스트

- [x] 사용자 인증 (로그인) - 기존 구현 완료
- [x] 팀 관리 및 팀별 설정
- [x] 음성 녹음 파일 업로드
- [x] 음성 파일 압축 (ffmpeg)
- [x] STT (화자 분리) - OpenAI gpt-4o-transcribe-diarize
- [x] 텍스트 교정 (STT 후처리)
- [x] AI 요약 - OpenAI gpt-4o-mini
- [x] 회의록 저장/조회
- [x] 화자 이름 매핑
- [x] 팀 공유 (팀 기준 회의록 필터링)
- [x] 검색 (제목, 전문, 요약) - PostgreSQL Full-text Search
- [x] Confluence 연동 (선택)
- [x] Slack 연동 (선택)
- [x] 음성 파일 자동 삭제 (90일) - Celery Beat
- [x] OpenAI API Key 관리 (팀별)
- [ ] **긴 오디오 파일 분할 처리** (25분 초과 시 자동 분할 → 병합)
