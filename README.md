# Morning Briefing Collector

Python을 사용해 매일 아침 브리핑에 필요한 뉴스와 날씨 데이터를 수집하고, OpenAI로 요약한 뒤 카카오톡 '나에게 보내기'로 발송하는 미니 자동화 프로젝트입니다.

## 주요 기능

- 네이버 뉴스 주요 기사 제목과 링크 상위 5개 수집
- OpenWeatherMap API를 활용한 지역별 현재 날씨 조회
- OpenAI API를 활용한 아침 브리핑 문장 생성
- 카카오톡 '나에게 보내기' API를 활용한 브리핑 발송
- GitHub Actions를 활용한 매일 오전 7시 30분 자동 실행
- requests와 BeautifulSoup을 활용한 HTML 파싱
- API 요청 및 크롤링 실패 시 예외 처리
- logging을 활용한 에러 메시지 기록

## 사용 기술

- Python
- requests
- BeautifulSoup
- OpenAI API
- OpenWeatherMap API
- Kakao Talk Message API
- GitHub Actions
- schedule
- logging

## 실행 방법

```bash
pip install -r requirements.txt
python main.py
```

한 번만 실행하려면 다음 명령을 사용합니다.

```bash
python main.py --once
```

## 환경 변수 설정

`.env.example` 파일을 참고해 프로젝트 루트에 `.env` 파일을 만들고 필요한 값을 입력합니다.

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

OPENWEATHERMAP_API_KEY=your_openweathermap_api_key
BRIEFING_LOCATION=서울

KAKAO_REST_API_KEY=your_kakao_rest_api_key
KAKAO_CLIENT_SECRET=
KAKAO_ACCESS_TOKEN=your_kakao_access_token
KAKAO_REFRESH_TOKEN=your_kakao_refresh_token
```

## GitHub Actions 자동 실행

`.github/workflows/morning-briefing.yml` 파일을 통해 매일 한국시간 오전 7시 30분에 자동 실행됩니다.

GitHub 저장소의 `Settings` → `Secrets and variables` → `Actions`에서 다음 값을 등록해야 합니다.

- `OPENAI_API_KEY`
- `OPENWEATHERMAP_API_KEY`
- `KAKAO_REST_API_KEY`
- `KAKAO_ACCESS_TOKEN`
- `KAKAO_REFRESH_TOKEN`
- `KAKAO_CLIENT_SECRET` optional

선택적으로 Variables에 아래 값을 등록할 수 있습니다.

- `OPENAI_MODEL`
- `BRIEFING_LOCATION`
