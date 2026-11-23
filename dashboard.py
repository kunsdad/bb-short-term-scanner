from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title='BB 단기전략', layout='wide')
st.title('BB 단기전략 | 국내 주식 스캐너')
st.caption('관찰용 분석 도구입니다. 실시간 시세나 매수 권유가 아닙니다.')
path = Path(__file__).parent / 'data' / 'latest.csv'
if not path.exists():
    st.warning('data/latest.csv가 없습니다. GitHub Actions 스캐너를 먼저 실행하세요.')
    st.stop()
df = pd.read_csv(path, dtype={'code':str}).fillna({'exclusion_reason':''})
if df.empty:
    st.warning('분석 결과가 비어 있습니다.')
    st.stop()
latest = df['date'].max()
a,b,c,d = st.columns(4)
a.metric('최신 데이터 날짜', latest)
b.metric('분석 종목', f'{len(df):,}')
c.metric('7점 이상', f'{(df.score >= 7).sum():,}')
d.metric('신규 후보', f'{df.eligible.astype(str).str.lower().eq("true").sum():,}')
market = st.multiselect('시장', sorted(df.market.dropna().unique()), default=sorted(df.market.dropna().unique()))
search = st.text_input('종목명 또는 종목코드 검색')
mode = st.radio('표시 범위', ['신규 후보', '7점 이상 관찰', '전체'], horizontal=True)
filtered = df[df.market.isin(market)].copy()
if search:
    filtered = filtered[filtered['name'].str.contains(search,case=False,na=False,regex=False) | filtered['code'].str.contains(search,regex=False,na=False)]
if mode == '신규 후보':
    filtered = filtered[filtered.eligible.astype(str).str.lower().eq('true')]
elif mode == '7점 이상 관찰':
    filtered = filtered[filtered.score >= 7]
columns = [x for x in ['code','name','market','date','close','score','rsi','volume_ratio','turnover_20d','reentry','bandwalk','eligible','exclusion_reason','target1','target2','stop','risk_reward'] if x in filtered.columns]
st.dataframe(filtered[columns], use_container_width=True, hide_index=True)
st.download_button('표시된 결과 CSV 다운로드', filtered.to_csv(index=False).encode('utf-8-sig'), 'bb_filtered.csv', 'text/csv')
st.info('점수는 기존 v0.2 규칙을 기반으로 하며 업종 상대강도는 아직 미측정입니다. 목표가가 비어 있으면 임의 목표가를 만들지 않습니다.')
