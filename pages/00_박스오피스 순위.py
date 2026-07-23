# -*- coding: utf-8 -*-
"""
날짜별 박스오피스 대시보드
--------------------------------
KOBIS(영화진흥위원회) 공식 API에서 원하는 날짜의 일별 박스오피스 데이터를 가져와
표와 그래프로 보여주는 스트림릿(Streamlit) 앱입니다.

* 달력에서 날짜를 골라 그날의 박스오피스를 조회할 수 있습니다.
* 오늘 데이터는 아직 집계가 끝나지 않았기 때문에, 고를 수 있는 가장 늦은 날짜는 '어제'까지입니다.
* '어제'는 서버가 어느 나라에 있든 항상 한국 시간(Asia/Seoul) 기준으로 계산합니다.
* 인증키는 코드에 직접 쓰지 않고, 스트림릿 클라우드의 Secrets(비밀 금고)에서 불러옵니다.
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 내장 시간대 라이브러리 (별도 설치 불필요)

# ----------------------------------------------------------------------
# 1) 기본 화면 설정
# ----------------------------------------------------------------------
st.set_page_config(page_title="날짜별 박스오피스", page_icon="🎬", layout="wide")
st.title("🎬 날짜별 박스오피스 대시보드")

# ----------------------------------------------------------------------
# 2) 한국 시간(Asia/Seoul) 기준으로 '어제' 날짜 계산하고, 달력 위젯으로 날짜 선택받기
#    - 배포 서버가 미국이나 다른 나라 시간대를 쓰고 있어도,
#      아래처럼 시간대를 명시해서 계산하면 항상 한국 기준 '어제'가 나옵니다.
#    - 오늘 데이터는 아직 집계 전이므로, 선택 가능한 가장 늦은 날짜를 '어제'로 제한합니다.
# ----------------------------------------------------------------------
kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
yesterday_kst = (kst_now - timedelta(days=1)).date()

selected_date = st.date_input(
    "조회할 날짜를 선택하세요 (오늘 데이터는 아직 집계 전이라 선택할 수 없어요)",
    value=yesterday_kst,       # 기본값: 어제
    max_value=yesterday_kst,   # 어제까지만 선택 가능
)

target_dt = selected_date.strftime("%Y%m%d")  # KOBIS가 요구하는 형식: yyyymmdd (8자리)

st.caption(f"조회 기준일: **{target_dt}**")

# ----------------------------------------------------------------------
# 3) 인증키 불러오기
#    - st.secrets는 스트림릿 클라우드의 Settings > Secrets 에 등록한 값을 읽어옵니다.
#    - 코드에는 절대로 실제 키 값을 적지 않습니다.
# ----------------------------------------------------------------------
try:
    KOBIS_KEY = st.secrets["KOBIS_KEY"]
except Exception:
    st.error(
        "🔑 인증키(KOBIS_KEY)를 찾을 수 없어요.\n\n"
        "스트림릿 클라우드의 **Settings > Secrets**에서 아래처럼 등록해주세요.\n\n"
        "```\nKOBIS_KEY = \"발급받은_인증키\"\n```"
    )
    st.stop()  # 키가 없으면 더 이상 진행하지 않고 앱을 멈춥니다.

# ----------------------------------------------------------------------
# 4) KOBIS API 호출하기
# ----------------------------------------------------------------------
API_URL = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

params = {
    "key": KOBIS_KEY,
    "targetDt": target_dt,
}

try:
    response = requests.get(API_URL, params=params, timeout=10)
    response.raise_for_status()  # 200 OK가 아니면 예외를 발생시킴
    data = response.json()
except requests.exceptions.RequestException as e:
    st.error(
        "🚫 박스오피스 정보를 불러오는 데 실패했어요.\n\n"
        "인터넷 연결 상태나 KOBIS 서버 상태를 확인한 뒤 잠시 후 다시 시도해주세요.\n\n"
        f"(자세한 오류: {e})"
    )
    st.stop()
except ValueError:
    # response.json() 파싱이 실패한 경우 (응답이 JSON 형식이 아닌 경우)
    st.error("🚫 서버 응답을 해석할 수 없었어요. 잠시 후 다시 시도해주세요.")
    st.stop()

# ----------------------------------------------------------------------
# 5) 응답 안에 faultInfo(오류 정보)가 있는지 확인하기
#    - 인증키가 잘못되었거나, 날짜 형식이 잘못되었을 때 KOBIS는 200 OK를 주면서도
#      본문에 faultInfo를 담아 보냅니다. 이 경우도 반드시 확인해야 합니다.
# ----------------------------------------------------------------------
if "faultInfo" in data:
    fault_msg = data["faultInfo"].get("message", "알 수 없는 오류")
    st.error(
        "🚫 KOBIS 서버가 오류를 반환했어요.\n\n"
        f"오류 내용: {fault_msg}\n\n"
        "인증키가 올바른지, 하루 요청 한도를 넘기지 않았는지 확인해보세요."
    )
    st.stop()

# ----------------------------------------------------------------------
# 6) 필요한 데이터 꺼내기 (boxOfficeResult -> dailyBoxOfficeList)
# ----------------------------------------------------------------------
try:
    movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]
except KeyError:
    st.error("🚫 예상한 형식의 데이터가 아니에요. KOBIS 서버 응답 구조를 확인해주세요.")
    st.stop()

if not movie_list:
    st.warning("😅 해당 날짜의 박스오피스 데이터가 아직 없어요. 잠시 후 다시 시도해주세요.")
    st.stop()

# ----------------------------------------------------------------------
# 7) 데이터프레임으로 변환하고, 숫자로 와야 할 값들을 진짜 숫자로 바꾸기
#    - API 응답에서는 순위, 관객수 등이 전부 "문자열"로 옵니다.
#    - 정렬이나 그래프에 쓰려면 반드시 숫자(int)로 바꿔줘야 합니다.
# ----------------------------------------------------------------------
df = pd.DataFrame(movie_list)

numeric_cols = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt", "rankInten"]
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")  # 변환 실패 시 NaN 처리

# 혹시 모를 NaN(변환 실패) 값은 0으로 채워서 안전하게 처리
df[numeric_cols] = df[numeric_cols].fillna(0)
df["rank"] = df["rank"].astype(int)
df["rankInten"] = df["rankInten"].astype(int)

# 순위 기준으로 정렬 (원래도 순위순으로 오지만 명확하게 한 번 더 정렬)
df = df.sort_values("rank").reset_index(drop=True)

# ----------------------------------------------------------------------
# 8) 1위 영화를 큰 지표 카드(metric)로 보여주기
# ----------------------------------------------------------------------
top_movie = df.iloc[0]

st.subheader("🥇 1위 영화")
col1, col2, col3 = st.columns(3)
col1.metric("영화명", top_movie["movieNm"])
col2.metric("해당일 관객수", f'{int(top_movie["audiCnt"]):,} 명')
col3.metric("누적 관객수", f'{int(top_movie["audiAcc"]):,} 명')

st.divider()

# ----------------------------------------------------------------------
# 9) 전체 순위표 보여주기
#    - 화면에 보여줄 컬럼명을 한글로 바꿔서 표시합니다.
#    - rankInten(전날 대비 순위 증감): 양수면 순위 상승(예: 5위→3위), 음수면 순위 하락.
#      => 상승은 빨간 위쪽 화살표(🔺), 하락은 파란 아래쪽 화살표(🔽)를 순위 옆에 붙입니다.
#    - 누적관객수가 100만 명을 넘은 영화는 영화명 옆에 🏆를 붙여줍니다.
# ----------------------------------------------------------------------
st.subheader("📋 박스오피스 순위표")


def rank_change_arrow(rank_inten: int) -> str:
    """전날 대비 순위 증감(rankInten)을 화살표 문자열로 바꿔줍니다."""
    if rank_inten > 0:
        return f"🔺{rank_inten}"   # 순위가 오름 (예: 5위 -> 3위, rankInten=2)
    elif rank_inten < 0:
        return f"🔽{abs(rank_inten)}"  # 순위가 내림
    else:
        return "-"  # 변동 없음


table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt", "rankInten"]].copy()

# 순위 변동 화살표 컬럼 추가
table_df["변동"] = table_df["rankInten"].apply(rank_change_arrow)

# 누적관객 100만 돌파 영화는 영화명 옆에 🏆 이모지 붙이기
table_df["movieNm"] = table_df.apply(
    lambda row: f'{row["movieNm"]} 🏆' if row["audiAcc"] >= 1_000_000 else row["movieNm"],
    axis=1,
)

# 화면에는 rankInten 원본 대신 '변동' 화살표 컬럼을 보여줍니다.
table_df = table_df[["rank", "변동", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]]
table_df.columns = ["순위", "전일대비", "영화명", "개봉일", "관객수", "누적관객수", "스크린수"]

st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
)

st.caption("🏆 = 누적관객수 100만 명 돌파 · 🔺 순위 상승 · 🔽 순위 하락")

st.divider()

# ----------------------------------------------------------------------
# 10) 관객수 상위 5편 막대그래프
# ----------------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

top5_df = df.sort_values("audiCnt", ascending=False).head(5)

chart_df = top5_df.set_index("movieNm")[["audiCnt"]]
chart_df.columns = ["관객수"]

st.bar_chart(chart_df)

st.caption("데이터 출처: 영화진흥위원회(KOBIS) 공식 API")
