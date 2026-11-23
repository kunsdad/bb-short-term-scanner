import json
from pathlib import Path
import pandas as pd
import streamlit as st
st.set_page_config(page_title='BB 단기전략 스캐너',layout='wide')
st.title('BB 단기전략 | KOSPI · KOSDAQ')
st.caption('정규장 종가 기준 · 무료 시세 데이터 · 실거래 주문 기능 없음')
base=Path(__file__).parent/'data'
if not (base/'latest.csv').exists():
    st.info('아직 분석 결과가 없습니다. 먼저 python scanner.py를 실행하세요.')
    st.stop()
df=pd.read_csv(base/'latest.csv',dtype={'code':str})
status=json.loads((base/'status.json').read_text(encoding='utf-8'))
a,b,c,d=st.columns(4)
a.metric('수집 완료',f"{status['processed']:,} / {status['universe']:,}")
b.metric('7점 이상 신규 후보',status['eligible'])
c.metric('수집 오류',status['errors'])
d.metric('최종 업데이트',status['updated_at'][5:16].replace('T',' '))
if status['errors']: st.warning('수집 오류가 있습니다. data/errors.json을 확인하세요.')
st.warning('업종 상대강도는 현재 미측정으로 0점 처리합니다. 총점 최대 9점이며, 완전한 10점 평가가 아닙니다. 데이터 갱신 시각과 수집 성공률을 검증하기 전에는 실제 매매 판단에 사용하지 마세요.')
only=st.toggle('7점 이상 신규 후보만 보기',value=True)
market=st.multiselect('시장', ['KOSPI','KOSDAQ'],default=['KOSPI','KOSDAQ'])
query=st.text_input('종목명 또는 종목코드 검색')
view=df[df.market.isin(market)]
if only:view=view[view.eligible]
if query:view=view[view.name.str.contains(query,case=False,na=False,regex=False)|view.code.str.contains(query,regex=False)]
cols=['date','market','code','name','close','score','rsi','volume_ratio','turnover_20d','entry','target1','target2','stop','risk_reward','bandwalk','reentry','sector_strength']
st.dataframe(view[cols],use_container_width=True,hide_index=True)
st.download_button('결과 CSV 다운로드',view.to_csv(index=False).encode('utf-8-sig'),'bb_candidates.csv','text/csv')
st.caption('점수와 가격은 실험적 규칙 기반 계산값입니다. 목표가가 현재가 이하이거나 손익비가 낮으면 매수 보류가 적절합니다.')
