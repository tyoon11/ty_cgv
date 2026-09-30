# ty_cgv — CGV 예매 오픈 텔레그램 알림봇

CGV **왕십리** · **10/5** · **치이카와** · **일반관** 회차가 예매 오픈되면 텔레그램으로 알려줍니다.
GitHub Actions에서 돌아가서 서버가 필요 없습니다.

## 동작

- 5분마다 워크플로가 뜨고, 한 번 뜰 때 약 4.5분 동안 60초 간격으로 체크
- `searchSiteScnscYmdListBySite`로 10/5가 열렸는지 확인 → 열리면 `searchMovScnInfo`로 시간표 조회
- 제목에 `치이카와`가 들어간 회차 중 IMAX·4DX·SCREENX·스위트박스 등 특별관을 제외한 회차를 알림 (자막/더빙 모두)
- 이미 알린 회차는 다시 알리지 않고, 나중에 추가된 회차만 "회차 추가"로 알림
- CGV 조회가 연속 실패(Cloudflare 차단 등)하면 경고를 한 번 보냄 — 봇이 조용히 죽는 걸 방지
- 10/5가 지나면 자동으로 아무것도 안 함 (워크플로는 Actions 탭에서 Disable 하세요)

## 설정 (한 번만)

1. **봇 만들기**: 텔레그램 `@BotFather` → `/newbot` → 토큰 받기
2. **chat id 확인**: 만든 봇에게 아무 메시지 전송 → 브라우저에서
   `https://api.telegram.org/bot<토큰>/getUpdates` 열어서 `"chat":{"id": ...}` 값 복사
3. **GitHub Secrets**: 저장소 Settings → Secrets and variables → Actions → New repository secret
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. **기본 브랜치(main)에 머지**: GitHub 스케줄(cron)은 기본 브랜치의 워크플로만 실행합니다.
5. **테스트**: Actions → "CGV 예매 오픈 감시" → Run workflow → `test` 체크 → 실행.
   텔레그램으로 CGV 조회 결과(열린 날짜, 관 등급명 목록)가 오면 정상입니다.

## 변경하고 싶을 때 (Settings → Variables → Actions)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `CGV_SITE_NO` | `0074` | 지점 코드 (0074 = 왕십리) |
| `CGV_SITE_NAME` | `왕십리` | 알림 표시용 |
| `CGV_DATE` | `20261005` | 감시 날짜 |
| `CGV_MOVIE_KEYWORD` | `치이카와` | 제목 부분일치 |
| `CGV_EXCLUDE` | (코드 내 목록) | 특별관 키워드, 콤마 구분 |

## 한계

- GitHub cron은 부하에 따라 수 분~십수 분 늦게 뜰 수 있습니다. 실행 중에는 1분 간격이지만 실행 사이 공백이 생길 수 있습니다.
- CGV 비공식 내부 API라 예고 없이 바뀔 수 있습니다. 그 경우 경고 메시지가 옵니다.

## 로컬 실행

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python check.py --test
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... LOOP_SECONDS=86400 python check.py   # 하루 동안 1분 간격 감시
```
