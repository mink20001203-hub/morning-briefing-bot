import logging
import json
import os
import re
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

OPENWEATHERMAP_URL = "https://api.openweathermap.org/data/2.5/weather"
KAKAO_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465
DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BRIEFING_SYSTEM_PROMPT = (
    "당신은 유능하고 친절한 개인 AI 비서입니다. 입력받은 뉴스 헤드라인 5개와 "
    "날씨 정보를 바탕으로, 사용자가 아침에 가볍게 읽기 좋은 따뜻하고 정중한 "
    "어조의 브리핑 문장을 작성하세요."
)

LOCATION_ALIASES = {
    "서울": "Seoul,KR",
    "서울시": "Seoul,KR",
    "대전": "Daejeon,KR",
    "대전시": "Daejeon,KR",
    "부산": "Busan,KR",
    "부산시": "Busan,KR",
    "인천": "Incheon,KR",
    "인천시": "Incheon,KR",
    "대구": "Daegu,KR",
    "광주": "Gwangju,KR",
    "울산": "Ulsan,KR",
    "제주": "Jeju,KR",
}


def get_naver_news(limit: int = 5) -> List[Dict[str, str]]:
    """네이버 뉴스 홈에서 주요/헤드라인 뉴스 제목과 링크를 가져옵니다."""
    url = "https://news.naver.com/"

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("네이버 뉴스 요청 실패: %s", exc)
        return []

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        candidates: List[Dict[str, str]] = []
        seen_links: Set[str] = set()

        selectors = [
            "a.cjs_news_a",
            "a.cjs_t",
            "a.cnf_news_title",
            "a.cluster_text_headline",
            "a[href*='n.news.naver.com']",
        ]

        for selector in selectors:
            for anchor in soup.select(selector):
                title = anchor.get_text(" ", strip=True)
                link = anchor.get("href", "").strip()

                if not title or not link:
                    continue
                if link.startswith("//"):
                    link = f"https:{link}"
                elif link.startswith("/"):
                    link = f"https://news.naver.com{link}"

                if "news.naver.com" not in link and "n.news.naver.com" not in link:
                    continue
                if link in seen_links:
                    continue

                seen_links.add(link)
                candidates.append({"title": title, "link": link})

                if len(candidates) >= limit:
                    return candidates

        return candidates
    except Exception as exc:
        logger.exception("네이버 뉴스 파싱 실패: %s", exc)
        return []


def get_weather_info(location: str) -> Optional[Dict[str, Any]]:
    """OpenWeatherMap에서 오늘 현재 날씨 정보를 가져옵니다.

    환경변수 OPENWEATHERMAP_API_KEY 또는 OWM_API_KEY에 API 키를 설정해야 합니다.
    """
    api_key = os.getenv("OPENWEATHERMAP_API_KEY") or os.getenv("OWM_API_KEY")
    if not api_key:
        logger.error(
            "OpenWeatherMap API 키가 없습니다. "
            "OPENWEATHERMAP_API_KEY 또는 OWM_API_KEY 환경변수를 설정하세요."
        )
        return None

    query_location = LOCATION_ALIASES.get(location.strip(), location.strip())
    params = {
        "q": query_location,
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
    }

    try:
        response = requests.get(
            OPENWEATHERMAP_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.exception("%s 날씨 요청 실패: %s", location, exc)
        return None
    except ValueError as exc:
        logger.exception("%s 날씨 응답 JSON 파싱 실패: %s", location, exc)
        return None

    try:
        weather = data.get("weather", [{}])[0]
        main = data.get("main", {})

        return {
            "location": data.get("name", location),
            "temperature": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "temp_min": main.get("temp_min"),
            "temp_max": main.get("temp_max"),
            "humidity": main.get("humidity"),
            "condition": weather.get("description") or weather.get("main"),
        }
    except Exception as exc:
        logger.exception("%s 날씨 데이터 변환 실패: %s", location, exc)
        return None


def generate_briefing(
    news_list: List[Dict[str, str]],
    weather_data: Optional[Dict[str, Any]],
) -> str:
    """수집된 뉴스와 날씨 데이터를 OpenAI API로 아침 브리핑 문장으로 요약합니다."""
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OpenAI API 키가 없습니다. OPENAI_API_KEY 환경변수를 설정하세요.")
        return ""

    news_lines: List[str] = []
    for index, news in enumerate(news_list[:5], start=1):
        title = news.get("title", "").strip()
        link = news.get("link", "").strip()

        if not title:
            continue

        if link:
            news_lines.append(f"{index}. [{title}]({link})")
        else:
            news_lines.append(f"{index}. {title}")

    if not news_lines:
        news_lines.append("수집된 뉴스가 없습니다.")

    if weather_data:
        weather_text = (
            f"- 지역: {weather_data.get('location', '알 수 없음')}\n"
            f"- 기온: {weather_data.get('temperature', '알 수 없음')}도\n"
            f"- 체감온도: {weather_data.get('feels_like', '알 수 없음')}도\n"
            f"- 최저/최고: {weather_data.get('temp_min', '알 수 없음')}도 / "
            f"{weather_data.get('temp_max', '알 수 없음')}도\n"
            f"- 습도: {weather_data.get('humidity', '알 수 없음')}%\n"
            f"- 날씨 상태: {weather_data.get('condition', '알 수 없음')}"
        )
    else:
        weather_text = "수집된 날씨 정보가 없습니다."

    user_prompt = (
        "아래 데이터를 바탕으로 아침 브리핑을 작성해 주세요.\n\n"
        "## 뉴스 헤드라인\n"
        f"{chr(10).join(news_lines)}\n\n"
        "## 날씨 정보\n"
        f"{weather_text}\n\n"
        "## 작성 조건\n"
        "- 마크다운 형식을 적절히 사용해 주세요.\n"
        "- 뉴스와 날씨를 자연스럽게 연결해 주세요.\n"
        "- 너무 길지 않게, 아침에 읽기 좋은 분량으로 작성해 주세요."
    )

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model=DEFAULT_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )

        content = response.choices[0].message.content
        return content.strip() if content else ""
    except ImportError as exc:
        logger.exception("openai 패키지가 설치되어 있지 않습니다: %s", exc)
        return ""
    except Exception as exc:
        logger.exception("OpenAI 브리핑 생성 실패: %s", exc)
        return ""


def send_kakao_message(access_token: str, text: str) -> bool:
    """카카오톡 '나에게 보내기' API로 텍스트 메시지를 전송합니다.

    access_token은 코드에 직접 저장하지 말고 환경변수, 암호화된 설정 파일,
    또는 별도 토큰 저장소에서 읽어오세요. 만료 시 refresh_token으로 재발급하는
    흐름을 별도로 구현하는 것이 안전합니다.
    """
    if not access_token:
        logger.error("카카오 access_token이 없습니다.")
        return False
    if not text:
        logger.error("전송할 카카오 메시지 내용이 없습니다.")
        return False

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": "https://developers.kakao.com",
            "mobile_web_url": "https://developers.kakao.com",
        },
        "button_title": "자세히 보기",
    }
    data = {
        "template_object": json.dumps(template_object, ensure_ascii=False),
    }

    try:
        response = requests.post(
            KAKAO_MEMO_SEND_URL,
            headers=headers,
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        response_text = getattr(exc.response, "text", "") if exc.response else ""
        logger.exception("카카오 메시지 전송 실패: %s %s", exc, response_text)
        return False


def _basic_markdown_to_html(content: str) -> str:
    """메일 본문용으로 제목, 목록, 링크 정도만 간단히 HTML로 변환합니다."""
    html_parts: List[str] = []
    in_list = False
    link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

    def convert_inline(text: str) -> str:
        escaped = escape(text)
        return link_pattern.sub(
            r'<a href="\2" style="color:#2563eb;text-decoration:none;">\1</a>',
            escaped,
        )

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        if line.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(
                f'<h2 style="font-size:18px;margin:24px 0 10px;color:#111827;">'
                f"{convert_inline(line[3:])}</h2>"
            )
        elif line.startswith("# "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(
                f'<h1 style="font-size:24px;margin:0 0 18px;color:#111827;">'
                f"{convert_inline(line[2:])}</h1>"
            )
        elif line.startswith(("- ", "* ")):
            if not in_list:
                html_parts.append('<ul style="padding-left:22px;margin:10px 0;">')
                in_list = True
            html_parts.append(
                f'<li style="margin:6px 0;line-height:1.6;">'
                f"{convert_inline(line[2:])}</li>"
            )
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(
                f'<p style="margin:10px 0;line-height:1.7;">'
                f"{convert_inline(line)}</p>"
            )

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _build_email_html(content: str) -> str:
    body_html = _basic_markdown_to_html(content)
    return f"""<!doctype html>
<html lang="ko">
  <body style="margin:0;padding:0;background:#f3f4f6;">
    <div style="max-width:680px;margin:0 auto;padding:28px 16px;">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:28px;font-family:Arial,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#374151;">
        {body_html}
      </div>
    </div>
  </body>
</html>"""


def send_briefing_email(
    to_emails: List[str],
    subject: str,
    content: str,
) -> Dict[str, bool]:
    """Gmail SMTP로 여러 수신자에게 아침 브리핑 메일을 개별 발송합니다.

    Gmail 계정과 앱 비밀번호는 소스코드에 직접 쓰지 말고 .env의
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD 환경변수로 관리하세요.
    """
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_address or not gmail_app_password:
        logger.error("GMAIL_ADDRESS 또는 GMAIL_APP_PASSWORD 환경변수가 없습니다.")
        return {email: False for email in to_emails}
    if not to_emails:
        logger.error("메일 수신자 목록이 비어 있습니다.")
        return {}
    if not subject or not content:
        logger.error("메일 제목 또는 본문이 비어 있습니다.")
        return {email: False for email in to_emails}

    html_content = _build_email_html(content)
    plain_content = content
    results: Dict[str, bool] = {}

    try:
        with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=15) as smtp:
            smtp.login(gmail_address, gmail_app_password)

            for to_email in to_emails:
                try:
                    message = MIMEMultipart("alternative")
                    message["Subject"] = str(Header(subject, "utf-8"))
                    message["From"] = formataddr(("Morning Briefing", gmail_address))
                    message["To"] = to_email

                    message.attach(MIMEText(plain_content, "plain", "utf-8"))
                    message.attach(MIMEText(html_content, "html", "utf-8"))

                    smtp.sendmail(gmail_address, [to_email], message.as_string())
                    results[to_email] = True
                    logger.info("브리핑 메일 발송 완료: %s", to_email)
                except Exception as exc:
                    results[to_email] = False
                    logger.exception("브리핑 메일 발송 실패: %s %s", to_email, exc)
    except smtplib.SMTPException as exc:
        logger.exception("Gmail SMTP 연결 또는 인증 실패: %s", exc)
        return {email: False for email in to_emails}
    except OSError as exc:
        logger.exception("Gmail SMTP 네트워크 오류: %s", exc)
        return {email: False for email in to_emails}

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    print(get_naver_news())
    print(get_weather_info("서울"))
