# AI Meeting API - 프론트엔드 개발 참조 문서

## 목차

1. [API 기본 정보](#1-api-기본-정보)
2. [인증](#2-인증)
3. [사용자 API](#3-사용자-api)
4. [팀 API](#4-팀-api)
5. [회의록 API](#5-회의록-api)
6. [에러 처리](#6-에러-처리)
7. [프론트엔드 구현 가이드](#7-프론트엔드-구현-가이드)

---

## 1. API 기본 정보

### Base URL

```
개발: http://localhost:8000/v1
```

### 공통 헤더

```http
Content-Type: application/json
Authorization: Bearer <access_token>
```

### 주요 설정값

| 설정 | 값 |
|------|-----|
| Access Token 유효시간 | 1시간 |
| Refresh Token 유효시간 | 7일 |
| 최대 음성 파일 크기 | 500MB |
| 최대 녹음 길이 | 제한 없음 (25분 초과 시 서버에서 자동 분할 처리) |
| 음성 파일 보관 기간 | 90일 |
| 지원 오디오 형식 | `.mp3`, `.wav`, `.m4a`, `.ogg`, `.webm`, `.mp4` |

---

## 2. 인증

### 2.1 JWT 토큰 구조

```
Authorization: Bearer <access_token>
```

### 2.2 토큰 갱신

```http
POST /v1/users/token/refresh
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

**응답:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

---

## 3. 사용자 API

### 3.1 회원가입

```http
POST /v1/users/auth/signup
```

**요청:**
```json
{
  "username": "string (필수, 고유)",
  "email": "string (필수, 이메일 형식, 고유)",
  "password": "string (필수, 8자 이상)",
  "password_confirm": "string (필수, password와 동일)",
  "gender": "M | F (필수)",
  "birth_date": "YYYY-MM-DD (필수)",
  "phone_number": "string (필수)"
}
```

**응답: 201 Created**
```json
{
  "message": "User created successfully.",
  "user_id": 1
}
```

### 3.2 로그인

```http
POST /v1/users/auth/login
```

**요청:**
```json
{
  "email": "string",
  "password": "string"
}
```

**응답: 200 OK**
```json
{
  "message": "Login successful.",
  "tokens": {
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
  },
  "user": {
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "gender": "M",
    "birth_date": "1990-01-01",
    "phone_number": "010-1234-5678",
    "team": {
      "id": 1,
      "name": "AI팀"
    },
    "is_team_admin": false,
    "created_at": "2025-01-01T12:00:00Z"
  }
}
```

### 3.3 이메일 중복 확인

```http
POST /v1/users/auth/check-email
```

**요청:**
```json
{
  "email": "string"
}
```

**응답: 200 OK** (사용 가능)
```json
{
  "message": "Email is available."
}
```

**응답: 409 Conflict** (중복)
```json
{
  "error": {
    "message": "이미 사용 중인 이메일입니다.",
    "error_code": "DUPLICATE_EMAIL"
  }
}
```

### 3.4 현재 사용자 정보 조회

```http
GET /v1/users/profile/me
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "gender": "M",
  "birth_date": "1990-01-01",
  "phone_number": "010-1234-5678",
  "team": {
    "id": 1,
    "name": "AI팀"
  },
  "is_team_admin": false,
  "created_at": "2025-01-01T12:00:00Z"
}
```

### 3.5 프로필 수정

```http
PATCH /v1/users/profile/update
Authorization: Bearer <token>
```

**요청:**
```json
{
  "phone_number": "string (선택)",
  "team": 1  // 팀 ID (선택) - 팀 가입/변경
}
```

**응답: 200 OK**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "gender": "M",
  "birth_date": "1990-01-01",
  "phone_number": "010-9999-8888",
  "team": 2,
  "team_info": {
    "id": 2,
    "name": "개발팀"
  },
  "is_team_admin": false,
  "created_at": "2025-01-01T12:00:00Z"
}
```

> **팀 가입/변경 안내:**
> - 사용자는 `team` 필드에 팀 ID를 전달하여 원하는 팀에 가입할 수 있습니다.
> - 팀을 변경하면 기존 팀 관리자 권한(`is_team_admin`)이 자동으로 `false`로 초기화됩니다.
> - 팀 관리자 권한은 해당 팀의 기존 관리자가 부여해야 합니다.
> - `team`에 `null`을 전달하면 팀에서 탈퇴합니다.

### 3.6 비밀번호 변경

```http
POST /v1/users/profile/change-password
Authorization: Bearer <token>
```

**요청:**
```json
{
  "current_password": "string",
  "new_password": "string (8자 이상)",
  "new_password_confirm": "string"
}
```

---

## 4. 팀 API

### 4.1 팀 목록 조회

```http
GET /v1/teams/
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
[
  {
    "id": 1,
    "name": "AI팀",
    "description": "AI 연구개발팀",
    "member_count": 5,
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": "2025-01-01T12:00:00Z"
  }
]
```

### 4.2 팀 상세 조회

```http
GET /v1/teams/{id}/
Authorization: Bearer <token>
```

### 4.3 팀 생성

```http
POST /v1/teams/
Authorization: Bearer <token>
```

**요청:**
```json
{
  "name": "string (필수, 고유)",
  "description": "string (선택)"
}
```

**응답: 201 Created**
```json
{
  "id": 1,
  "name": "AI팀",
  "description": "AI 연구개발팀",
  "member_count": 1,
  "created_at": "2025-01-15T12:00:00Z",
  "updated_at": "2025-01-15T12:00:00Z"
}
```

> **참고**: 팀 생성 시 생성자가 자동으로 해당 팀에 배정되고 팀 관리자 권한이 부여됩니다.

### 4.4 팀 설정 조회 (팀 관리자만)

```http
GET /v1/teams/{id}/settings
Authorization: Bearer <team_admin_token>
```

**응답: 200 OK**
```json
{
  "id": 1,
  "openai_api_key_set": true,
  "confluence_site_url": "https://company.atlassian.net",
  "confluence_space_key": "AIDEV",
  "confluence_configured": true,
  "slack_webhook_configured": true,
  "slack_bot_configured": false,
  "slack_default_channel": "#meeting-notes",
  "created_at": "2025-01-01T12:00:00Z",
  "updated_at": "2025-01-01T12:00:00Z"
}
```

### 4.5 팀 설정 수정 (팀 관리자만)

```http
PATCH /v1/teams/{id}/settings
Authorization: Bearer <team_admin_token>
```

**요청:**
```json
{
  "openai_api_key": "sk-...",
  "confluence_site_url": "https://company.atlassian.net",
  "confluence_api_token": "...",
  "confluence_user_email": "admin@company.com",
  "confluence_space_key": "AIDEV",
  "confluence_parent_page_id": "12345",
  "slack_webhook_url": "https://hooks.slack.com/...",
  "slack_bot_token": "xoxb-...",
  "slack_default_channel": "#meeting-notes"
}
```

### 4.6 팀 멤버 목록 조회

```http
GET /v1/teams/{id}/members
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
[
  {
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "is_team_admin": true
  },
  {
    "id": 2,
    "username": "jane_smith",
    "email": "jane@example.com",
    "is_team_admin": false
  }
]
```

### 4.7 팀 관리자 권한 부여/해제

```http
POST /v1/teams/{id}/members/{user_id}/admin    # 권한 부여
DELETE /v1/teams/{id}/members/{user_id}/admin  # 권한 해제
Authorization: Bearer <team_admin_token>
```

---

## 5. 회의록 API

### 5.1 회의록 상태값

| 상태 | 설명 | UI 표시 |
|------|------|---------|
| `pending` | 대기 중 | 처리 대기 |
| `compressing` | 압축 중 | 처리 중... |
| `transcribing` | STT 처리 중 | 음성 인식 중... |
| `correcting` | 텍스트 교정 중 | 텍스트 교정 중... |
| `summarizing` | 요약 중 | 요약 생성 중... |
| `completed` | 완료 | 완료 |
| `failed` | 실패 | 실패 (재시도 필요) |

### 5.2 회의록 목록 조회

```http
GET /v1/meetings/
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
[
  {
    "id": 1,
    "title": "주간 회의",
    "meeting_date": "2025-01-15T14:00:00Z",
    "status": "completed",
    "status_display": "완료",
    "has_audio": true,
    "created_by_name": "john_doe",
    "created_at": "2025-01-15T15:00:00Z",
    "updated_at": "2025-01-15T16:30:00Z"
  }
]
```

### 5.3 회의록 상세 조회

```http
GET /v1/meetings/{id}/
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "id": 1,
  "title": "주간 회의",
  "meeting_date": "2025-01-15T14:00:00Z",
  "audio_file_url": "http://localhost:8000/media/audio/1/2025/01/meeting.m4a",
  "audio_file_expires_at": "2025-04-15T15:00:00Z",
  "has_audio": true,
  "transcript": "원본 STT 텍스트...",
  "speaker_data": [
    {
      "speaker": "Speaker 0",
      "text": "안녕하세요",
      "start": 0.0,
      "end": 2.5
    },
    {
      "speaker": "Speaker 1",
      "text": "네, 안녕하세요",
      "start": 2.6,
      "end": 4.0
    }
  ],
  "corrected_transcript": "교정된 텍스트...",
  "corrected_speaker_data": [
    {
      "speaker": "Speaker 0",
      "text": "안녕하세요.",
      "start": 0.0,
      "end": 2.5
    },
    {
      "speaker": "Speaker 1",
      "text": "네, 안녕하세요.",
      "start": 2.6,
      "end": 4.0
    }
  ],
  "chat_transcript": [
    {
      "speaker": "김영도",
      "text": "안녕하세요.",
      "start": 0.0,
      "end": 2.5
    },
    {
      "speaker": "홍길동",
      "text": "네, 안녕하세요.",
      "start": 2.6,
      "end": 4.0
    }
  ],
  "summary": "## 회의 요약\n\n### 참석자\n- Speaker 0\n- Speaker 1\n\n### 주요 논의 사항\n...",
  "status": "completed",
  "status_display": "완료",
  "error_message": "",
  "confluence_page_id": "12345",
  "confluence_page_url": "https://company.atlassian.net/wiki/...",
  "slack_message_ts": "1234567890.123456",
  "slack_channel": "#meeting-notes",
  "speaker_mappings": [
    {
      "id": 1,
      "speaker_label": "Speaker 0",
      "speaker_name": "김영도",
      "created_at": "2025-01-15T15:00:00Z"
    }
  ],
  "created_by_name": "john_doe",
  "created_at": "2025-01-15T15:00:00Z",
  "updated_at": "2025-01-15T16:30:00Z"
}
```

### 5.4 회의록 생성 (음성 파일 업로드)

```http
POST /v1/meetings/
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

**요청 (FormData):**
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `title` | string | O | 회의 제목 |
| `meeting_date` | datetime | O | 회의 일시 (ISO 8601) |
| `audio_file` | file | X | 음성 파일 (최대 500MB) |

**JavaScript 예시:**
```javascript
const formData = new FormData();
formData.append('title', '주간 회의');
formData.append('meeting_date', '2025-01-15T14:00:00Z');
formData.append('audio_file', audioFile);

const response = await fetch('/v1/meetings/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`
  },
  body: formData
});
```

**응답: 201 Created**
```json
{
  "id": 1,
  "title": "주간 회의",
  "meeting_date": "2025-01-15T14:00:00Z",
  "status": "pending",
  "status_display": "대기 중",
  ...
}
```

### 5.5 회의록 수정

```http
PATCH /v1/meetings/{id}/
Authorization: Bearer <token>
```

**요청:**
```json
{
  "title": "string (선택)",
  "meeting_date": "datetime (선택)",
  "summary": "string (선택)",
  "corrected_transcript": "string (선택)"
}
```

### 5.6 회의록 삭제

```http
DELETE /v1/meetings/{id}/
Authorization: Bearer <token>
```

**응답: 204 No Content**

### 5.7 처리 상태 조회 (폴링용)

```http
GET /v1/meetings/{id}/status
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "id": 1,
  "status": "transcribing",
  "status_display": "STT 처리 중",
  "error_message": ""
}
```

### 5.8 화자 목록 조회

```http
GET /v1/meetings/{id}/speakers
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
[
  {
    "id": 1,
    "speaker_label": "Speaker 0",
    "speaker_name": "김영도",
    "created_at": "2025-01-15T15:00:00Z"
  },
  {
    "id": null,
    "speaker_label": "Speaker 1",
    "speaker_name": "",
    "created_at": null
  }
]
```

### 5.9 화자 이름 일괄 매핑

```http
PATCH /v1/meetings/{id}/speakers
Authorization: Bearer <token>
```

**요청:**
```json
{
  "mappings": [
    {"speaker_label": "Speaker 0", "speaker_name": "김영도"},
    {"speaker_label": "Speaker 1", "speaker_name": "홍길동"}
  ]
}
```

### 5.10 STT 수동 재실행

```http
POST /v1/meetings/{id}/transcribe
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "message": "STT 처리가 시작되었습니다.",
  "status": "pending"
}
```

### 5.11 요약 수동 재생성

```http
POST /v1/meetings/{id}/summarize
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "message": "요약 생성이 시작되었습니다.",
  "status": "summarizing"
}
```

### 5.12 회의록 검색

```http
GET /v1/meetings/search?q={keyword}&field={field}
Authorization: Bearer <token>
```

**쿼리 파라미터:**
| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `q` | O | 검색어 |
| `field` | X | 검색 필드 (`all`, `title`, `transcript`, `summary`), 기본값: `all` |

**응답: 200 OK**
```json
{
  "results": [
    {
      "id": 1,
      "title": "주간 회의",
      "meeting_date": "2025-01-15T14:00:00Z",
      "summary_preview": "주요 결정 사항: ...",
      "transcript_preview": "이번 회의에서는...",
      "created_by_name": "john_doe",
      "created_at": "2025-01-15T15:00:00Z"
    }
  ],
  "count": 1,
  "query": "회의",
  "field": "all"
}
```

### 5.13 Confluence 업로드

```http
POST /v1/meetings/{id}/confluence/upload
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "message": "Confluence 업로드가 시작되었습니다.",
  "meeting_id": 1
}
```

### 5.14 Confluence 상태 확인

```http
GET /v1/meetings/{id}/confluence/status
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "uploaded": true,
  "page_id": "12345",
  "page_url": "https://company.atlassian.net/wiki/..."
}
```

### 5.15 Slack 공유

```http
POST /v1/meetings/{id}/slack/share
Authorization: Bearer <token>
```

**요청 (선택):**
```json
{
  "channel": "#channel-name"
}
```

**응답: 200 OK**
```json
{
  "message": "Slack 공유가 시작되었습니다.",
  "meeting_id": 1
}
```

### 5.16 Slack 상태 확인

```http
GET /v1/meetings/{id}/slack/status
Authorization: Bearer <token>
```

**응답: 200 OK**
```json
{
  "shared": true,
  "message_ts": "1234567890.123456",
  "channel": "#meeting-notes"
}
```

---

## 6. 에러 처리

### 6.1 HTTP 상태 코드

| 코드 | 설명 |
|------|------|
| 200 | 성공 |
| 201 | 생성 성공 |
| 204 | 삭제 성공 (응답 없음) |
| 400 | 잘못된 요청 |
| 401 | 인증 실패 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 409 | 충돌 (중복 등) |
| 500 | 서버 오류 |

### 6.2 에러 응답 형식

```json
{
  "error": {
    "message": "에러 메시지",
    "error_code": "ERROR_CODE",
    "details": {}
  }
}
```

### 6.3 주요 에러 코드

| 코드 | 설명 |
|------|------|
| `INVALID_CREDENTIALS` | 이메일 또는 비밀번호 오류 |
| `DUPLICATE_EMAIL` | 이메일 중복 |
| `DUPLICATE_USERNAME` | 사용자명 중복 |
| `TOKEN_EXPIRED` | 토큰 만료 |
| `FORBIDDEN` | 권한 없음 |
| `NOT_FOUND` | 리소스 없음 |
| `VALIDATION_ERROR` | 유효성 검증 실패 |

---

## 7. 프론트엔드 구현 가이드

### 7.1 인증 흐름

```
1. 로그인 → access_token, refresh_token 저장
2. API 요청 시 Authorization 헤더에 access_token 포함
3. 401 응답 시 → refresh_token으로 갱신 시도
4. refresh 실패 시 → 로그인 페이지로 이동
```

### 7.2 회의록 처리 상태 폴링

```javascript
async function pollMeetingStatus(meetingId) {
  const pollInterval = 3000; // 3초

  const poll = async () => {
    const response = await fetch(`/v1/meetings/${meetingId}/status`, {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });
    const data = await response.json();

    if (data.status === 'completed') {
      // 처리 완료 - 상세 정보 로드
      loadMeetingDetail(meetingId);
    } else if (data.status === 'failed') {
      // 처리 실패 - 에러 메시지 표시
      showError(data.error_message);
    } else {
      // 처리 중 - 상태 표시 업데이트 후 계속 폴링
      updateStatusDisplay(data.status_display);
      setTimeout(poll, pollInterval);
    }
  };

  poll();
}
```

### 7.3 화자별 발언 표시 (채팅형 UI)

`chat_transcript` 필드를 사용하면 화자 이름 매핑이 이미 적용된 데이터를 바로 사용할 수 있습니다.

```javascript
// 방법 1: chat_transcript 사용 (권장)
// - 교정된 텍스트 + 화자 이름 매핑이 적용된 데이터
function renderChatTranscript(chatTranscript) {
  return chatTranscript.map(segment => ({
    speaker: segment.speaker,  // 이미 실제 이름으로 매핑됨
    text: segment.text,        // 교정된 텍스트
    startTime: formatTime(segment.start),
    endTime: formatTime(segment.end)
  }));
}

// 방법 2: speaker_data + speakerMappings 사용 (원본 데이터 필요 시)
function renderSpeakerData(speakerData, speakerMappings) {
  const mappingDict = {};
  speakerMappings.forEach(m => {
    mappingDict[m.speaker_label] = m.speaker_name || m.speaker_label;
  });

  return speakerData.map(segment => ({
    speaker: mappingDict[segment.speaker] || segment.speaker,
    text: segment.text,
    startTime: formatTime(segment.start),
    endTime: formatTime(segment.end)
  }));
}
```

**필드 비교:**
| 필드 | 설명 |
|------|------|
| `speaker_data` | 원본 STT 결과 (화자 라벨: "Speaker 0") |
| `corrected_speaker_data` | 교정된 화자별 데이터 (화자 라벨 유지) |
| `chat_transcript` | 교정 + 화자 이름 매핑 적용 (실제 이름: "김영도") |

### 7.4 마크다운 요약 렌더링

요약(`summary`)은 마크다운 형식입니다. `react-markdown` 또는 `marked` 등의 라이브러리로 렌더링하세요.

```javascript
import ReactMarkdown from 'react-markdown';

function MeetingSummary({ summary }) {
  return <ReactMarkdown>{summary}</ReactMarkdown>;
}
```

### 7.5 권장 UI 구조

```
/                       → 대시보드 (최근 회의록)
/login                  → 로그인
/signup                 → 회원가입
/meetings               → 회의록 목록
/meetings/new           → 회의록 생성 (음성 업로드)
/meetings/:id           → 회의록 상세
/meetings/:id/edit      → 회의록 수정
/meetings/search        → 검색 결과
/settings               → 사용자 설정
/team/settings          → 팀 설정 (관리자)
```

### 7.6 필수 화면 목록

1. **로그인/회원가입**
2. **회의록 목록** (상태 필터, 날짜 정렬)
3. **회의록 상세** (요약, 전문, 화자별 발언, 오디오 재생)
4. **회의록 생성** (드래그&드롭 파일 업로드)
5. **화자 이름 매핑**
6. **검색**
7. **팀 설정** (API Key, Confluence, Slack 설정)

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| 1.0 | 2025-01-15 | 최초 작성 - Phase 4-5 완료 |
| 1.1 | 2025-01-15 | 팀 생성 권한 변경 (인증된 사용자 모두 가능), 프로필 수정으로 팀 가입/변경 기능 문서화 |
| 1.2 | 2025-12-12 | 긴 오디오 파일 분할 처리 기능 추가 (25분 초과 시 자동 분할), 파일 크기 제한 상향 (100MB → 500MB) |
| 1.3 | 2025-12-12 | 채팅형 전문 표시 기능 추가 - `corrected_speaker_data`, `chat_transcript` 필드 추가 |
