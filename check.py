"""CGV 예매 오픈 감시 봇.

지정 지점 + 날짜의 상영시간표에 특정 영화(일반관)가 올라오면 텔레그램으로 알린다.

CGV 신사이트(cgv.co.kr)는 Cloudflare 가 앞단에 있어서 일반 HTTP 클라이언트는 403 을
받는다. curl_cffi 로 크롬 TLS 지문을 흉내내서 내부 JSON API 를 직접 호출한다.

환경변수
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (필수)
  CGV_SITE_NO        지점 코드 (기본 0074 = 왕십리)
  CGV_SITE_NAME      알림에 쓸 지점 이름 (기본 왕십리)
  CGV_DATE           감시 날짜 YYYYMMDD (기본 20261005)
  CGV_MOVIE_KEYWORD  영화 제목에 포함될 문자열 (기본 치이카와)
  CGV_EXCLUDE        특별관 판별 키워드, 콤마 구분 (기본값은 SPECIAL_KEYWORDS)
  STATE_FILE         이미 알린 회차 저장 파일 (기본 state.json)
  LOOP_SECONDS       이 시간 동안 반복 체크 (기본 0 = 한 번만)
  LOOP_INTERVAL      반복 간격 초 (기본 60)

사용법
  python check.py            # 감시 (새 회차가 있으면 알림)
  python check.py --test     # 텔레그램 테스트 메시지 + 해당 날짜 시간표 덤프
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from curl_cffi import requests

BASE = "https://cgv.co.kr/api/v1/booking"
CO_CD = "A420"
BOOK_URL = "https://cgv.co.kr/cnm/movieBook"
KST = dt.timezone(dt.timedelta(hours=9))

SITE_NO = (os.environ.get("CGV_SITE_NO") or "0074")
SITE_NAME = (os.environ.get("CGV_SITE_NAME") or "왕십리")
TARGET_DATE = (os.environ.get("CGV_DATE") or "20261005")
MOVIE_KEYWORD = (os.environ.get("CGV_MOVIE_KEYWORD") or "치이카와")
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

# 일반관이 아닌 상영관을 거르는 키워드. 관 등급명(tcscnsGradNm)과 관 이름에 대해
# 대소문자 무시하고 부분일치로 검사한다.
SPECIAL_KEYWORDS = [
    "아이맥스", "IMAX", "4DX", "스크린X", "SCREENX", "스피어X", "SPHEREX",
    "스위트박스", "SWEETBOX", "골드클래스", "GOLD CLASS", "템퍼", "TEMPUR",
    "씨네앤포레", "CINE&FORET", "씨네드쉐프", "CINE DE CHEF", "프라이빗",
    "PRIVATE", "리클라이너", "RECLINER", "ULTRA", "울트라", "4D", "SOUNDX",
    "사운드X", "샤롯데", "CHARLOTTE", "키즈", "KIDS", "시네키즈",
]
EXCLUDE = [
    k.strip().upper()
    for k in (os.environ.get("CGV_EXCLUDE") or ",".join(SPECIAL_KEYWORDS)).split(",")
    if k.strip()
]

SESSION = requests.Session(impersonate="chrome")
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BOOK_URL,
    "Origin": "https://cgv.co.kr",
}


class CgvError(RuntimeError):
    pass


def cgv_get(path: str, **params):
    params.setdefault("coCd", CO_CD)
    last = None
    for attempt in range(3):
        try:
            resp = SESSION.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 403:
                raise CgvError(f"403 Forbidden ({path}) - Cloudflare 차단")
            resp.raise_for_status()
            body = resp.json()
            if body.get("statusCode") not in (0, "0"):
                raise CgvError(f"{path}: statusCode={body.get('statusCode')} {body.get('statusMessage')}")
            return body.get("data") or []
        except Exception as exc:  # noqa: BLE001 - 재시도 후 마지막 에러를 올린다
            last = exc
            time.sleep(2 * (attempt + 1))
    raise CgvError(f"{path} 요청 실패: {last!r}")


def open_dates() -> list[str]:
    rows = cgv_get("searchSiteScnscYmdListBySite", siteNo=SITE_NO)
    return [r.get("scnYmd") for r in rows if r.get("scnYmd")]


def schedules(ymd: str) -> list[dict]:
    return cgv_get("searchMovScnInfo", rtctlScopCd="01", siteNo=SITE_NO, scnYmd=ymd)


def is_special(row: dict) -> bool:
    text = " ".join(
        str(row.get(k) or "")
        for k in ("tcscnsGradNm", "scnsNm", "expoScnsNm", "movkndDsplNm")
    ).upper()
    return any(k in text for k in EXCLUDE)


def fmt_time(hhmm: str) -> str:
    hhmm = (hhmm or "").zfill(4)
    h, m = int(hhmm[:2]), hhmm[2:]
    return f"{h - 24:02d}:{m}(+1)" if h >= 24 else f"{h:02d}:{m}"


def show_key(row: dict) -> str:
    return f"{row.get('scnYmd')}-{row.get('scnsNo')}-{row.get('scnsrtTm')}"


def describe(row: dict) -> str:
    screen = row.get("expoScnsNm") or row.get("scnsNm") or "?"
    grade = row.get("tcscnsGradNm") or ""
    kind = row.get("movkndDsplNm") or ""
    seats = f"{row.get('frSeatCnt', '?')}/{row.get('stcnt', '?')}석"
    extra = " ".join(x for x in (grade, kind) if x)
    return f"{fmt_time(row.get('scnsrtTm'))} {screen} {extra} · {seats}".replace("  ", " ")


# ---------------------------------------------------------------- telegram

def telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
        "reply_markup": json.dumps(
            {"inline_keyboard": [[{"text": "CGV 예매하러 가기", "url": BOOK_URL}]]}
        ),
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(payload).encode(),
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"telegram 전송 실패({attempt + 1}/3): {exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("텔레그램 전송 실패")


# ---------------------------------------------------------------- state

def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- main logic

def pretty_date(ymd: str) -> str:
    d = dt.datetime.strptime(ymd, "%Y%m%d")
    return f"{d.month}/{d.day}({'월화수목금토일'[d.weekday()]})"


def check_once(state: dict) -> None:
    notified = set(state.get("notified", []))

    dates = open_dates()
    if TARGET_DATE not in dates:
        print(f"[{now()}] {TARGET_DATE} 아직 미오픈 (열린 날짜: {', '.join(dates) or '-'})")
        return

    rows = schedules(TARGET_DATE)
    movie_rows = [r for r in rows if MOVIE_KEYWORD in (r.get("movNm") or "")]
    normal = [r for r in movie_rows if not is_special(r)]
    print(
        f"[{now()}] {TARGET_DATE} 오픈됨: 전체 {len(rows)}회차, "
        f"'{MOVIE_KEYWORD}' {len(movie_rows)}회차, 일반관 {len(normal)}회차"
    )
    for r in movie_rows:
        print(f"   {'  ' if r in normal else 'X '}{r.get('movNm')} | {describe(r)}")

    new = [r for r in normal if show_key(r) not in notified]
    if not new:
        return

    new.sort(key=lambda r: r.get("scnsrtTm") or "")
    first = not notified
    lines = [
        ("🎟️ 예매 오픈!" if first else "➕ 회차 추가!")
        + f" CGV {SITE_NAME} {pretty_date(TARGET_DATE)}",
        "",
    ]
    for title in sorted({r.get("movNm") for r in new}):
        lines.append(f"🎬 {title}")
        lines += [f"  • {describe(r)}" for r in new if r.get("movNm") == title]
        lines.append("")
    telegram("\n".join(lines).strip())

    notified.update(show_key(r) for r in new)
    state["notified"] = sorted(notified)
    save_state(state)
    print(f"[{now()}] 알림 전송: 신규 {len(new)}회차")


def now() -> str:
    return dt.datetime.now(KST).strftime("%m-%d %H:%M:%S")


def run_test() -> None:
    try:
        dates = open_dates()
        msg = [f"✅ CGV 알림봇 테스트 — {SITE_NAME}({SITE_NO}) 조회 성공", f"열린 날짜: {', '.join(dates) or '-'}"]
        ymd = TARGET_DATE if TARGET_DATE in dates else (dates[-1] if dates else None)
        if ymd:
            rows = schedules(ymd)
            grades = sorted({str(r.get("tcscnsGradNm")) for r in rows})
            msg.append(f"{ymd} 관 등급명: {', '.join(grades)}")
            hits = [r for r in rows if MOVIE_KEYWORD in (r.get("movNm") or "")]
            msg.append(f"{ymd} '{MOVIE_KEYWORD}' {len(hits)}회차")
            msg += [f"  {'X' if is_special(r) else '•'} {describe(r)}" for r in hits[:30]]
    except CgvError as exc:
        msg = [f"⚠️ CGV 알림봇 테스트 — CGV 조회 실패: {exc}"]
    text = "\n".join(msg)
    print(text)
    telegram(text)


def main() -> int:
    if "--test" in sys.argv:
        run_test()
        return 0

    today = dt.datetime.now(KST).strftime("%Y%m%d")
    if today > TARGET_DATE:
        print(f"감시 날짜({TARGET_DATE})가 지났습니다. 종료.")
        return 0

    state = load_state()
    loop_seconds = int(os.environ.get("LOOP_SECONDS", "0"))
    interval = int(os.environ.get("LOOP_INTERVAL", "60"))
    deadline = time.monotonic() + loop_seconds
    failures = 0

    while True:
        try:
            check_once(state)
            if state.get("error_alerted"):
                state.pop("error_alerted")
                save_state(state)
                telegram(f"✅ CGV 조회가 다시 정상 동작합니다 ({SITE_NAME})")
            failures = 0
        except CgvError as exc:
            failures += 1
            print(f"[{now()}] CGV 조회 실패: {exc}", file=sys.stderr)
            # 봇이 조용히 장님이 되는 걸 막기 위해, 연속 실패 시 한 번만 경고를 보낸다.
            if failures >= 3 and not state.get("error_alerted"):
                telegram(f"⚠️ CGV 조회가 계속 실패하고 있습니다. 직접 확인해주세요.\n{exc}")
                state["error_alerted"] = True
                save_state(state)
        if time.monotonic() + interval > deadline:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
