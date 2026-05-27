import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests
import schedule


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"

logger = logging.getLogger(__name__)


def load_env_file(env_path: Path = ENV_PATH) -> None:
    """간단한 .env 로더입니다. 이미 설정된 환경변수는 덮어쓰지 않습니다."""
    if not env_path.exists():
        logger.warning(".env 파일이 없습니다: %s", env_path)
        return

    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        logger.exception(".env 파일 읽기 실패: %s", exc)


def update_env_file(updates: Dict[str, str], env_path: Path = ENV_PATH) -> None:
    """갱신된 access_token 등을 .env에 반영합니다."""
    try:
        lines = []
        existing_keys = set()

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updated_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                updated_lines.append(line)
                continue

            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                updated_lines.append(f"{key}={updates[key]}")
                existing_keys.add(key)
            else:
                updated_lines.append(line)

        for key, value in updates.items():
            if key not in existing_keys:
                updated_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.exception(".env 파일 업데이트 실패: %s", exc)


def refresh_kakao_token(refresh_token: str) -> Optional[str]:
    """카카오 Refresh Token으로 새 access_token을 발급받는 예시 구조입니다."""
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")

    if not rest_api_key:
        logger.error("KAKAO_REST_API_KEY가 없습니다.")
        return None
    if not refresh_token:
        logger.error("KAKAO_REFRESH_TOKEN이 없습니다.")
        return None

    data = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        response = requests.post(KAKAO_TOKEN_URL, data=data, timeout=10)
        response.raise_for_status()
        token_data = response.json()
    except requests.RequestException as exc:
        response_text = getattr(exc.response, "text", "") if exc.response else ""
        logger.exception("카카오 토큰 갱신 요청 실패: %s %s", exc, response_text)
        return None
    except ValueError as exc:
        logger.exception("카카오 토큰 응답 JSON 파싱 실패: %s", exc)
        return None

    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")

    if not access_token:
        logger.error("카카오 토큰 응답에 access_token이 없습니다: %s", token_data)
        return None

    updates = {"KAKAO_ACCESS_TOKEN": access_token}
    os.environ["KAKAO_ACCESS_TOKEN"] = access_token

    if new_refresh_token:
        updates["KAKAO_REFRESH_TOKEN"] = new_refresh_token
        os.environ["KAKAO_REFRESH_TOKEN"] = new_refresh_token

    update_env_file(updates)
    logger.info("카카오 access_token 갱신 완료")
    return access_token


def run_briefing_job() -> None:
    """뉴스/날씨 수집, OpenAI 요약, 카카오톡 발송을 한 번 실행합니다."""
    try:
        from morning_briefing_data import (
            generate_briefing,
            get_naver_news,
            get_weather_info,
            send_kakao_message,
        )

        location = os.getenv("BRIEFING_LOCATION", "서울")
        logger.info("아침 브리핑 작업 시작: location=%s", location)

        news_list = get_naver_news()
        weather_data = get_weather_info(location)
        briefing_text = generate_briefing(news_list, weather_data)

        if not briefing_text:
            logger.error("브리핑 문장 생성 실패로 카카오톡 발송을 건너뜁니다.")
            return

        access_token = os.getenv("KAKAO_ACCESS_TOKEN")
        refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")

        refreshed_token = refresh_kakao_token(refresh_token) if refresh_token else None
        if refreshed_token:
            access_token = refreshed_token

        if not access_token:
            logger.error("사용 가능한 카카오 access_token이 없어 발송할 수 없습니다.")
            return

        sent = send_kakao_message(access_token, briefing_text)
        if sent:
            logger.info("카카오톡 브리핑 발송 완료")
        else:
            logger.error("카카오톡 브리핑 발송 실패")
    except Exception as exc:
        logger.exception("브리핑 작업 중 처리되지 않은 오류: %s", exc)


def format_next_run() -> str:
    next_run = schedule.next_run()
    if not next_run:
        return "등록된 다음 실행 시간이 없습니다."

    now = datetime.now()
    remaining = max(next_run - now, datetime.min - datetime.min)
    total_seconds = int(remaining.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return (
        f"현재 시간: {now:%Y-%m-%d %H:%M:%S}, "
        f"다음 실행: {next_run:%Y-%m-%d %H:%M:%S}, "
        f"남은 시간: {hours:02d}:{minutes:02d}:{seconds:02d}"
    )


def main() -> None:
    load_env_file()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    if "--once" in sys.argv:
        run_briefing_job()
        return

    schedule.every().day.at("07:30").do(run_briefing_job)
    logger.info("아침 브리핑 스케줄러 시작")
    logger.info(format_next_run())

    log_interval = int(os.getenv("STATUS_LOG_INTERVAL_SECONDS", "60"))

    while True:
        try:
            schedule.run_pending()
            logger.info(format_next_run())
            time.sleep(log_interval)
        except KeyboardInterrupt:
            logger.info("사용자 요청으로 스케줄러를 종료합니다.")
            break
        except Exception as exc:
            logger.exception("스케줄러 루프 오류. 계속 대기합니다: %s", exc)
            time.sleep(min(log_interval, 60))


if __name__ == "__main__":
    main()
