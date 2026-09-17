import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ────────────────────────────────────────────────
# 기본 화면 설정
# ────────────────────────────────────────────────
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

# KOBIS 일별 박스오피스 조회 API 주소 (공식 문서 기준)
KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst() -> str:
    """
    한국 시간(Asia/Seoul) 기준으로 '어제' 날짜를 yyyymmdd 형식 문자열로 계산합니다.
    배포 서버의 시계가 한국 시간이 아니어도 항상 한국 기준 '어제'가 나오도록
    ZoneInfo("Asia/Seoul")로 시간대를 명시했습니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


@st.cache_data(ttl=3600)  # 같은 날짜로 다시 요청하면 1시간 동안은 이 결과를 재사용합니다 (API 재호출 방지)
def fetch_box_office(target_dt: str):
    """
    KOBIS API를 호출해서 target_dt(yyyymmdd) 날짜의 일별 박스오피스 목록을 가져옵니다.

    반환값:
      (True, 영화 목록)      -> 성공
      (False, 안내 메시지)   -> 실패 (네트워크 오류 / 인증 오류 / 빈 목록 등)
    """
    # secrets.toml(또는 Streamlit Cloud의 Secrets 설정)에 등록해 둔 인증키를 불러옵니다.
    # 코드 안에는 절대 실제 키 값을 적지 않습니다.
    try:
        api_key = st.secrets["KOBIS_KEY"]
    except Exception:
        return False, (
            "인증키(KOBIS_KEY)를 찾을 수 없습니다.\n"
            "▶ Streamlit Cloud의 [Settings > Secrets]에 KOBIS_KEY 값을 등록했는지 확인해 주세요."
        )

    params = {"key": api_key, "targetDt": target_dt}

    # 1) 네트워크 요청 자체가 실패하는 경우 (인터넷 문제, 타임아웃 등)
    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, (
            "KOBIS 서버에 요청을 보내지 못했습니다.\n"
            f"▶ 인터넷 연결 상태 또는 서버 상태를 확인해 주세요. (오류 내용: {e})"
        )

    # 2) 상태 코드가 200이 아닌 경우 (서버 자체 오류)
    if response.status_code != 200:
        return False, (
            f"KOBIS 서버가 정상적으로 응답하지 않았습니다. (상태 코드: {response.status_code})\n"
            "▶ 잠시 후 다시 시도해 주세요."
        )

    # 3) 응답이 JSON 형식이 아닌 경우
    try:
        data = response.json()
    except ValueError:
        return False, "API 응답 형식을 해석할 수 없습니다.\n▶ 잠시 후 다시 시도해 주세요."

    # 4) 인증키가 틀렸을 때: 상태 코드는 200이지만 faultInfo 상자가 대신 옵니다.
    if "faultInfo" in data:
        fault_message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, (
            f"API에서 오류를 반환했습니다: {fault_message}\n"
            "▶ Secrets에 등록한 KOBIS_KEY 값이 올바른지 다시 확인해 주세요."
        )

    # 5) boxOfficeResult 자체가 없는 경우
    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return False, (
            "응답에 boxOfficeResult가 없습니다.\n"
            "▶ 요청 날짜(targetDt) 형식이나 KOBIS 서버 상태를 확인해 주세요."
        )

    # 6) 영화 목록이 비어 있는 경우 (예: 너무 이른 날짜, 자료 미집계 등)
    movie_list = box_office_result.get("dailyBoxOfficeList")
    if not movie_list:
        return False, (
            "해당 날짜의 박스오피스 정보가 비어 있습니다.\n"
            "▶ 아직 집계되지 않았거나, 날짜(targetDt)가 잘못되었을 수 있습니다."
        )

    return True, movie_list


def to_int(value) -> int:
    """API에서 문자열("1,234" 아닌 "1234" 형태)로 오는 숫자를 정수로 안전하게 변환합니다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main():
    st.title("🎬 어제의 박스오피스")

    # 조회할 날짜(어제, 한국 시간 기준)를 계산합니다.
    target_dt = get_yesterday_kst()
    pretty_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"기준일: {pretty_date} (한국 시간 기준 '어제')")

    # API 호출 (같은 날짜면 1시간 동안 캐시된 결과를 재사용합니다)
    success, result = fetch_box_office(target_dt)

    # 실패했을 때는 빈 화면 대신 안내 메시지를 보여주고 여기서 멈춥니다.
    if not success:
        st.error(result)
        st.stop()

    movie_list = result

    # ────────────────────────────────────────────
    # 문자열로 온 숫자들을 정수로 바꿔서 표/그래프에 쓸 표로 정리합니다.
    # ────────────────────────────────────────────
    rows = []
    for movie in movie_list:
        rows.append({
            "순위": to_int(movie.get("rank")),
            "영화명": movie.get("movieNm", ""),
            "개봉일": movie.get("openDt", ""),
            "관객수": to_int(movie.get("audiCnt")),
            "누적관객": to_int(movie.get("audiAcc")),
            "스크린수": to_int(movie.get("scrnCnt")),
        })

    df = pd.DataFrame(rows).sort_values("순위").reset_index(drop=True)

    # ────────────────────────────────────────────
    # 1위 영화 지표 카드 3장
    # ────────────────────────────────────────────
    st.subheader("오늘의 1위")
    top_movie = df.iloc[0]
    col1, col2, col3 = st.columns(3)
    col1.metric("영화명", top_movie["영화명"])
    col2.metric("어제 관객수", f"{top_movie['관객수']:,}명")
    col3.metric("누적 관객수", f"{top_movie['누적관객']:,}명")

    # ────────────────────────────────────────────
    # 전체 순위표 (숫자는 천 단위 구분 기호로 보기 좋게 표시)
    # ────────────────────────────────────────────
    st.subheader("전체 순위표")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn("관객수", format="%,d"),
            "누적관객": st.column_config.NumberColumn("누적관객", format="%,d"),
            "스크린수": st.column_config.NumberColumn("스크린수", format="%,d"),
        },
    )

    # ────────────────────────────────────────────
    # 관객수 상위 5편 막대그래프
    # ────────────────────────────────────────────
    st.subheader("관객수 상위 5편")
    top5 = df.sort_values("관객수", ascending=False).head(5)
    chart_df = top5.set_index("영화명")[["관객수"]]
    st.bar_chart(chart_df)


if __name__ == "__main__":
    main()
