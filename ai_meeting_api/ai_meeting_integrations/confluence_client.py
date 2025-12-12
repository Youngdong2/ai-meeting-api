"""
Confluence API 클라이언트 모듈

회의록을 Confluence 페이지로 업로드하는 기능 제공
"""

import logging
from base64 import b64encode

import requests

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Confluence REST API 클라이언트"""

    def __init__(self, site_url: str, user_email: str, api_token: str):
        """
        Args:
            site_url: Confluence 사이트 URL (예: https://company.atlassian.net)
            user_email: Atlassian 계정 이메일
            api_token: Atlassian API 토큰
        """
        self.site_url = site_url.rstrip("/")
        self.api_url = f"{self.site_url}/wiki/api/v2"
        self.auth = b64encode(f"{user_email}:{api_token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {self.auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_page(
        self,
        space_id: str,
        title: str,
        content: str,
        parent_id: str | None = None,
    ) -> dict:
        """
        Confluence 페이지 생성

        Args:
            space_id: 스페이스 ID
            title: 페이지 제목
            content: 페이지 내용 (HTML 또는 Atlassian Storage Format)
            parent_id: 상위 페이지 ID (선택)

        Returns:
            dict: 생성된 페이지 정보 {"id": "...", "url": "..."}
        """
        url = f"{self.api_url}/pages"

        body = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": content,
            },
        }

        if parent_id:
            body["parentId"] = parent_id

        response = requests.post(url, json=body, headers=self.headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        page_id = data["id"]

        return {
            "id": page_id,
            "url": f"{self.site_url}/wiki/spaces/{space_id}/pages/{page_id}",
            "title": data.get("title", title),
        }

    def update_page(
        self,
        page_id: str,
        title: str,
        content: str,
        version: int,
    ) -> dict:
        """
        Confluence 페이지 업데이트

        Args:
            page_id: 페이지 ID
            title: 페이지 제목
            content: 페이지 내용
            version: 현재 버전 번호 (version + 1로 업데이트됨)

        Returns:
            dict: 업데이트된 페이지 정보
        """
        url = f"{self.api_url}/pages/{page_id}"

        body = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": content,
            },
            "version": {
                "number": version + 1,
            },
        }

        response = requests.put(url, json=body, headers=self.headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        return {
            "id": page_id,
            "url": data.get("_links", {}).get("webui", ""),
            "version": data.get("version", {}).get("number"),
        }

    def get_page(self, page_id: str) -> dict | None:
        """
        페이지 정보 조회

        Args:
            page_id: 페이지 ID

        Returns:
            dict: 페이지 정보 또는 None
        """
        url = f"{self.api_url}/pages/{page_id}"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_space_id_by_key(self, space_key: str) -> str | None:
        """
        스페이스 키로 스페이스 ID 조회

        Args:
            space_key: 스페이스 키 (예: "AIDEV")

        Returns:
            str: 스페이스 ID 또는 None
        """
        url = f"{self.api_url}/spaces"
        params = {"keys": space_key}

        response = requests.get(url, params=params, headers=self.headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if results:
            return results[0]["id"]
        return None


def get_confluence_client(site_url: str, user_email: str, api_token: str) -> ConfluenceClient:
    """Confluence 클라이언트 인스턴스 생성"""
    return ConfluenceClient(site_url, user_email, api_token)


def markdown_to_confluence_storage(markdown_text: str) -> str:
    """
    마크다운 텍스트를 Confluence Storage Format으로 변환

    Args:
        markdown_text: 마크다운 형식 텍스트

    Returns:
        str: Confluence Storage Format (XML)
    """
    import re

    html = markdown_text

    # 헤딩 변환
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # 볼드/이탤릭
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # 체크박스 리스트
    html = re.sub(
        r"^- \[ \] (.+)$",
        r"<ac:task-list><ac:task><ac:task-status>incomplete</ac:task-status><ac:task-body>\1</ac:task-body></ac:task></ac:task-list>",
        html,
        flags=re.MULTILINE,
    )
    html = re.sub(
        r"^- \[x\] (.+)$",
        r"<ac:task-list><ac:task><ac:task-status>complete</ac:task-status><ac:task-body>\1</ac:task-body></ac:task></ac:task-list>",
        html,
        flags=re.MULTILINE,
    )

    # 일반 리스트
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"^(\d+)\. (.+)$", r"<li>\2</li>", html, flags=re.MULTILINE)

    # 연속된 li 태그를 ul로 감싸기
    html = re.sub(r"(<li>.+</li>\n?)+", lambda m: f"<ul>{m.group(0)}</ul>", html)

    # 줄바꿈을 <br/>로 변환 (헤딩, 리스트 제외)
    lines = html.split("\n")
    result_lines = []
    for line in lines:
        if not line.strip():
            result_lines.append("<p></p>")
        elif not any(tag in line for tag in ["<h1>", "<h2>", "<h3>", "<ul>", "<li>", "<ac:task"]):
            result_lines.append(f"<p>{line}</p>")
        else:
            result_lines.append(line)

    return "\n".join(result_lines)
