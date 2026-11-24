from pathlib import Path
import json
import sqlite3
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
st.set_page_config(page_title='BB 단기전략 대시보드', page_icon='📈', layout='wide')
st.title('📈 BB 단기전략 | 국내 주식 대시보드')
st.caption('종가 기반 관찰 도구 · 실시간 시세가 아니며 매수 권유가 아닙니다. 업종 상대강도는 아직 미측정입니다.')

@st.cache_data(ttl=300)
def load_data(path, stamp):
    return pd.read_csv(path, dtype={'code': str}, encoding='utf-8-sig')

csv_path = DATA / 'latest.csv'
if not csv_path.exists():
    st.error('data/latest.csv 파일이 없습니다. GitHub Actions 스캔 결과가 저장됐는지 확인하세요.')
    st.stop()
try:
    df = load_data(str(csv_path), csv_path.stat().st_mtime)
except Exception as exc:
    st.error(f'CSV 읽기 실패: {exc}')
    st.stop()
if df.empty:
    st.warning('분석 결과가 비어 있습니다.')
    st.stop()

for col in ['score','rsi','close','volume_ratio','turnover_20d','entry','target1','target2','stop','risk_reward','ma5','ma20']:
    if col in df:
        df[col] = pd.to_numeric(df[col], errors='coerce')
for col in ['eligible','reentry','bandwalk']:
    if col in df:
        df[col] = df[col].astype(str).str.lower().eq('true')
for col in ['exclusion_reason','data_quality','name','market','code']:
    if col in df:
        df[col] = df[col].fillna('').astype(str)

status = {}
status_path = DATA / 'status.json'
if status_path.exists():
    try:
        status = json.loads(status_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        pass

eligible = df['eligible'] if 'eligible' in df else pd.Series(False, index=df.index)
score = df['score'] if 'score' in df else pd.Series(float('nan'), index=df.index)
latest = str(df['date'].max()) if 'date' in df else '미확인'
cols = st.columns(5)
cols[0].metric('기준일', latest)
cols[1].metric('분석 종목', f'{len(df):,}')
cols[2].metric('신규 후보', f'{int(eligible.sum()):,}')
cols[3].metric('7점 이상', f'{int((score >= 7).sum()):,}')
cols[4].metric('6~7점 관찰', f'{int(((score >= 6) & (score < 7)).sum()):,}')
if status:
    st.caption(f"스캐너 v{status.get('version','?')} · 전체 {status.get('universe','?')}종목 · 제외 {status.get('skipped','?')}종목 · 오류 {status.get('errors','?')}건 · 업데이트 {status.get('updated_at','미확인')}")

st.subheader('검색 및 필터')
f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
search = f1.text_input('종목명 / 종목코드', placeholder='예: 삼성전자 또는 005930')
markets = sorted(df['market'].dropna().unique().tolist()) if 'market' in df else []
selected = f2.multiselect('시장', markets, default=markets)
min_turnover = f3.number_input('최소 20일 평균 거래대금 (억원)', min_value=0.0, value=0.0, step=1.0)
max_rsi = f4.number_input('RSI 상한', min_value=0, max_value=100, value=100)

filtered = df.copy()
if markets:
    filtered = filtered[filtered['market'].isin(selected)]
if search:
    filtered = filtered[filtered['name'].str.contains(search, case=False, regex=False, na=False) | filtered['code'].str.contains(search, regex=False, na=False)]
if 'turnover_20d' in filtered:
    filtered = filtered[filtered['turnover_20d'] >= min_turnover * 100_000_000]
if 'rsi' in filtered:
    filtered = filtered[filtered['rsi'] <= max_rsi]

filtered = filtered.copy()
filtered['구분'] = '기타'
filtered.loc[filtered['score'] >= 6, '구분'] = '관찰 후보 (6점 이상)'
filtered.loc[filtered['score'] >= 7, '구분'] = '관심 후보 (7점 이상)'
filtered.loc[filtered['eligible'], '구분'] = '신규 후보'

labels = ['신규 후보', '관심 후보 (7점 이상)', '관찰 후보 (6점 이상)', '전체 종목']
tabs = st.tabs([f'{labels[0]} ({(filtered["구분"] == labels[0]).sum()})', f'{labels[1]} ({(filtered["구분"] == labels[1]).sum()})', f'{labels[2]} ({(filtered["구분"] == labels[2]).sum()})', f'{labels[3]} ({len(filtered)})'])

def show_table(frame, key):
    if frame.empty:
        st.info('현재 조건에 해당하는 종목이 없습니다. 필터를 완화하거나 전체 종목 탭을 확인하세요.')
        return
    frame = frame.sort_values(['score','turnover_20d'], ascending=[False, False], na_position='last')
    mapping = {'code':'종목코드','name':'종목명','market':'시장','date':'기준일','close':'종가','score':'점수','rsi':'RSI','volume_ratio':'거래량 배수','turnover_20d':'20일 평균 거래대금(원)','reentry':'밴드 재진입','bandwalk':'밴드워크','entry':'진입 기준가','target1':'1차 목표가','target2':'2차 목표가','stop':'손절 기준가','risk_reward':'손익비','exclusion_reason':'제외 사유','data_quality':'데이터 품질','sector_strength':'업종 상대강도'}
    available = [c for c in mapping if c in frame]
    st.dataframe(frame[available].rename(columns=mapping), use_container_width=True, hide_index=True, height=460)
    st.download_button('현재 목록 CSV 다운로드', frame.to_csv(index=False).encode('utf-8-sig'), file_name=f'bb_{key}_{latest}.csv', mime='text/csv', key=f'download_{key}')

with tabs[0]:
    show_table(filtered[filtered['구분'] == labels[0]], 'new')
with tabs[1]:
    show_table(filtered[filtered['구분'] == labels[1]], 'watch7')
with tabs[2]:
    show_table(filtered[filtered['구분'] == labels[2]], 'watch6')
with tabs[3]:
    show_table(filtered, 'all')

st.divider()
st.subheader('종목 상세 보기')
if not filtered.empty:
    choices = filtered.sort_values('score', ascending=False).copy()
    choices['선택'] = choices['name'] + ' (' + choices['code'] + ')'
    chosen = st.selectbox('종목 선택', choices['선택'].tolist())
    item = choices.loc[choices['선택'] == chosen].iloc[0]
    a,b,c,d = st.columns(4)
    a.metric('종가', f"{item['close']:,.0f}원" if pd.notna(item.get('close')) else '-')
    b.metric('BB 점수', f"{item['score']:.1f} / 10" if pd.notna(item.get('score')) else '-')
    c.metric('RSI(14)', f"{item['rsi']:.1f}" if pd.notna(item.get('rsi')) else '-')
    d.metric('거래량 배수', f"{item['volume_ratio']:.2f}배" if pd.notna(item.get('volume_ratio')) else '-')
    x,y,z = st.columns(3)
    for col, name, container in [('target1','1차 목표가',x),('target2','2차 목표가',y),('stop','손절 기준가',z)]:
        val = item.get(col)
        container.metric(name, f'{val:,.0f}원' if pd.notna(val) else '산출 불가')
    st.write('**분류:**', item['구분'])
    st.write('**제외 사유:**', item.get('exclusion_reason') or '없음')
    st.write('**데이터 품질:**', item.get('data_quality') or '미표시')
    st.write('**업종 상대강도:**', item.get('sector_strength') or '미측정')

    st.markdown('### 📊 가격·기술지표 차트')
    db_path = DATA / 'history.sqlite'
    if not db_path.exists():
        st.warning('data/history.sqlite 파일이 없습니다. GitHub 저장소에 저장되어 있는지 확인하세요.')
    else:
        @st.cache_data(ttl=300, show_spinner=False)
        def load_price_history(db_file, db_stamp, code):
            with sqlite3.connect(db_file) as conn:
                return pd.read_sql_query(
                    'SELECT date, open, high, low, close, volume FROM '
                    '(SELECT date, open, high, low, close, volume FROM prices '
                    'WHERE code = ? ORDER BY date DESC LIMIT 300) ORDER BY date ASC',
                    conn, params=(str(code).zfill(6),)
                )

        try:
            hist = load_price_history(str(db_path), db_path.stat().st_mtime, item['code'])
        except (sqlite3.Error, OSError, ValueError) as exc:
            st.error(f'과거 가격 데이터 조회 실패: {exc}')
            hist = pd.DataFrame()
        if hist.empty:
            st.info('선택한 종목의 과거 가격 기록이 없습니다.')
        else:
            hist['date'] = pd.to_datetime(hist['date'], errors='coerce')
            for pcol in ['open', 'high', 'low', 'close', 'volume']:
                hist[pcol] = pd.to_numeric(hist[pcol], errors='coerce')
            hist = hist.dropna(subset=['date']).sort_values('date').drop_duplicates('date')
            # Invalid OHLC is not treated as a real traded session.
            valid = (hist[['open','high','low','close']] > 0).all(axis=1) & (hist['volume'] > 0)
            invalid_count = int((~valid).sum())
            clean = hist.loc[valid].copy()
            if invalid_count:
                st.caption(f'비정상 OHLC 또는 거래량 0 기록 {invalid_count}개를 지표 계산에서 제외했습니다. 거래정지·비거래 여부는 별도 확인이 필요합니다.')
            if len(clean) < 20:
                st.warning('정상 가격 기록이 20개 미만이므로 기술지표 차트를 표시할 수 없습니다.')
            else:
                clean = clean.set_index('date')
                for n in [5,20,60,120]:
                    clean[f'MA{n}'] = clean['close'].rolling(n, min_periods=n).mean()
                std = clean['close'].rolling(20, min_periods=20).std(ddof=0)
                clean['BB 상단'] = clean['MA20'] + 2 * std
                clean['BB 하단'] = clean['MA20'] - 2 * std
                diff = clean['close'].diff()
                gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
                loss = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
                rs = gain / loss.replace(0, float('nan'))
                clean['RSI(14)'] = (100 - 100/(1+rs)).where(loss.ne(0), 100)
                clean.loc[gain.eq(0) & loss.eq(0), 'RSI(14)'] = 50
                window = st.select_slider('차트 표시 기간 (정상 거래 기록)', options=[40,60,120,200], value=120, key='chart_window')
                view = clean.tail(window)
                price_cols = ['close','BB 상단','BB 하단','MA5','MA20','MA60','MA120']
                chart = view[price_cols].rename(columns={'close':'종가'})
                st.line_chart(chart, height=380, use_container_width=True)
                st.caption('볼린저밴드: 20기간, 표준편차 2배 · 이동평균선: 정상 가격 기록 기준. 가격 조정·거래정지 이후 데이터는 별도 확인 필요.')
                st.markdown('**RSI(14)**')
                st.line_chart(view[['RSI(14)']], height=190, use_container_width=True)
                st.markdown('**거래량**')
                st.bar_chart(view[['volume']].rename(columns={'volume':'거래량'}), height=190, use_container_width=True)
                st.caption('목표가와 손절 기준가는 위 종목 상세 지표에 표시된 스캐너 계산값을 사용합니다. 차트의 재계산 지표와 스캐너 값은 데이터 정제 방식에 따라 다를 수 있습니다.')


with st.expander('판정 기준과 한계'):
    st.markdown('''- **신규 후보**: 스캐너에서 `eligible=True`로 판정된 종목만 표시합니다.\n- **관심 후보**: 7점 이상이지만 신규 후보가 아닌 종목입니다. 거래대금 부족 등 제외 사유를 반드시 확인하세요.\n- **관찰 후보**: 6점 이상 7점 미만 종목입니다. 매수 신호를 뜻하지 않습니다.\n- **목표가/손절가**: 스캐너 계산값을 그대로 표시합니다. 값이 없으면 임의로 만들지 않습니다.\n- **미구현**: 업종 상대강도, 공식 거래일 검증, 자동 수동 입력 동기화, 매물대 계산.\n- **시세**: GitHub Actions 마지막 실행 기준 종가 데이터이며 실시간이 아닙니다.''')
