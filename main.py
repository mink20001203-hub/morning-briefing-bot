import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

import schedule


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

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


def configure_timezone() -> None:
    """서버 시간이 UTC여도 한국 시간 기준 스케줄이 동작하도록 TZ를 설정합니다."""
    timezone = os.getenv("APP_TIMEZONE", "Asia/Seoul")
    os.environ["TZ"] = timezone

    if hasattr(time, "tzset"):
        time.tzset()


def parse_email_recipients() -> List[str]:
    raw_recipients = os.getenv("EMAIL_RECIPIENTS", "")
    return [
        email.strip()
        for email in raw_recipients.split(",")
        if email.strip()
    ]


def run_briefing_job() -> None:
    """뉴스/날씨 수집, OpenAI 요약, 이메일 단체 발송을 한 번 실행합니다."""
    location = os.getenv("BRIEFING_LOCATION", "서울")
    recipients = parse_email_recipients()
    subject = os.getenv("EMAIL_SUBJECT", "오늘의 아침 브리핑")

    logger.info("아침 브리핑 작업 시작: location=%s", location)

    try:
        from morning_briefing_data import (
            generate_briefing,
            get_naver_news,
            get_weather_info,
            send_briefing_email,
        )
    except Exception as exc:
        logger.exception("브리핑 모듈 불러오기 실패: %s", exc)
        return

    try:
        news_list = get_naver_news()
        logger.info("뉴스 수집 완료: %s개", len(news_list))
    except Exception as exc:
        logger.exception("뉴스 수집 단계 실패. 빈 뉴스 목록으로 계속 진행합니다: %s", exc)
        news_list = []

    try:
        weather_data = get_weather_info(location)
        if weather_data:
            logger.info("날씨 수집 완료: %s", weather_data.get("location", location))
        else:
            logger.warning("날씨 수집 결과가 없습니다.")
    except Exception as exc:
        logger.exception("날씨 수집 단계 실패. 날씨 정보 없이 계속 진행합니다: %s", exc)
        weather_data = None

    try:
        briefing_text = generate_briefing(news_list, weather_data)
        if not briefing_text:
            logger.error("브리핑 문장 생성 실패로 이메일 발송을 건너뜁니다.")
            return
        logger.info("OpenAI 브리핑 생성 완료")
    except Exception as exc:
        logger.exception("OpenAI 브리핑 생성 단계 실패: %s", exc)
        return

    if not recipients:
        logger.error("EMAIL_RECIPIENTS가 비어 있어 이메일 발송을 건너뜁니다.")
        return

    try:
        results = send_briefing_email(recipients, subject, briefing_text)
        success_count = sum(1 for sent in results.values() if sent)
        fail_count = len(results) - success_count
        logger.info("이메일 발송 완료: 성공=%s 실패=%s", success_count, fail_count)
    except Exception as exc:
        logger.exception("이메일 발송 단계 실패: %s", exc)


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
    configure_timezone()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    if "--once" in sys.argv:
        run_briefing_job()
        return

    run_time = os.getenv("BRIEFING_RUN_TIME", "07:30")
    schedule.every().day.at(run_time).do(run_briefing_job)
    logger.info("아침 브리핑 스케줄러 시작: 매일 %s", run_time)
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
