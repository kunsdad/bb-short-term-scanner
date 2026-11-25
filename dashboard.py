from pathlib import Path
import json
import sqlite3
import io
import urllib.request
import pandas as pd
import altair as alt
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
st.set_page_config(page_title='BB 단기전략 대시보드', page_icon='📈', layout='wide')
st.title('📈 BB 단기전략 | 국내 주식 대시보드')
st.caption('종가 기반 관찰 도구 · 실시간 시세가 아니며 매수 권유가 아닙니다. 업종 상대강도는 아직 미측정입니다.')

# GitHub의 main 브랜치에서 최신 스캔 결과를 직접 읽습니다.
# 로컬 파일은 네트워크 장애 시에만 사용하며, 이때 화면에 경고를 표시합니다.
RAW_BASE = 'https://raw.githubusercontent.com/kunsdad/bb-short-term-scanner/main/data/'

@st.cache_data(ttl=300, show_spinner=False)
def fetch_remote(filename):
    request = urllib.request.Request(RAW_BASE + filename,
        headers={'User-Agent': 'BB-Dashboard/4.0', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()

@st.cache_data(ttl=300, show_spinner=False)
def load_local_csv(path, stamp):
    return pd.read_csv(path, dtype={'code': str}, encoding='utf-8-sig')

csv_path = DATA / 'latest.csv'
status_path = DATA / 'status.json'
remote_ok = False
try:
    df = pd.read_csv(io.BytesIO(fetch_remote('latest.csv')),
                     dtype={'code': str}, encoding='utf-8-sig')
    status = json.loads(fetch_remote('status.json').decode('utf-8-sig'))
    remote_ok = True
except Exception as exc:
    st.warning(f'GitHub 최신 데이터 조회 실패: {exc}. 로컬 파일로 대체합니다. 최신 데이터가 아닐 수 있습니다.')
    if not csv_path.exists():
        st.error('원격 조회에 실패했고 data/latest.csv도 없습니다.')
        st.stop()
    try:
        df = load_local_csv(str(csv_path), csv_path.stat().st_mtime)
    except Exception as local_exc:
        st.error(f'CSV 읽기 실패: {local_exc}')
        st.stop()
    try:
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    except (ValueError, OSError):
        status = {}

# Historical snapshots are actual archived scanner outputs, not back-calculations.
# A missing date is never substituted with another day's scores.
archive_dates = []
try:
    archive_index = json.loads(fetch_remote('snapshots/index.json').decode('utf-8-sig'))
    archive_dates = sorted({d for d in archive_index.get('dates', [])
                            if isinstance(d, str) and d >= '2026-11-23'})
except Exception:
    local_index = DATA / 'snapshots' / 'index.json'
    if local_index.exists():
        try:
            archive_dates = sorted(set(json.loads(local_index.read_text(encoding='utf-8')).get('dates', [])))
        except (ValueError, OSError):
            pass

current_day = str(df['date'].max()) if 'date' in df and not df.empty else ''
known_days = sorted(set(archive_dates + ([current_day] if current_day >= '2026-11-23' else [])))
if not known_days:
    st.error('조회할 수 있는 스캔 날짜가 없습니다.')
    st.stop()

st.subheader('📅 과거 날짜 조회')
selected_day = st.selectbox('조회 기준일 (저장된 스캔 결과가 있는 날만 선택 가능)',
                            options=list(reversed(known_days)), index=0,
                            key='historical_scan_day')
if selected_day != current_day:
    try:
        df = pd.read_csv(io.BytesIO(fetch_remote(f'snapshots/{selected_day}.csv')),
                         dtype={'code': str}, encoding='utf-8-sig')
        snapshot_source = 'GitHub 보관 스캔 결과'
    except Exception as exc:
        local_snapshot = DATA / 'snapshots' / f'{selected_day}.csv'
        if not local_snapshot.exists():
            st.error(f'{selected_day} 스캔 원본을 가져오지 못했습니다: {exc}. 다른 날짜를 선택해 주세요.')
            st.stop()
        df = load_local_csv(str(local_snapshot), local_snapshot.stat().st_mtime)
        snapshot_source = '로컬 보관 스캔 결과 (원격 조회 실패)'
else:
    snapshot_source = '최신 스캔 결과' if remote_ok else '로컬 최신 스캔 결과'

if df.empty or 'date' not in df or str(df['date'].max()) != selected_day:
    st.error('선택한 날짜와 보관 파일의 데이터 날짜가 일치하지 않습니다. 표시를 중단합니다.')
    st.stop()
st.caption(f'조회 기준일: {selected_day} · {snapshot_source} · 과거 점수/후보는 저장된 당시 스캔 결과입니다.')
if df.empty:
    st.warning('분석 결과가 비어 있습니다.')
    st.stop()

st.caption('데이터 갱신: GitHub 최신 파일 5분 캐시 · 과거 조회는 날짜별 보관 CSV 사용')
for col in ['score','rsi','close','volume_ratio','turnover_20d','entry','target1','target2','stop','risk_reward','ma5','ma20']:
    if col in df:
        df[col] = pd.to_numeric(df[col], errors='coerce')
for col in ['eligible','reentry','bandwalk']:
    if col in df:
        df[col] = df[col].astype(str).str.lower().eq('true')
for col in ['exclusion_reason','data_quality','name','market','code']:
    if col in df:
        df[col] = df[col].fillna('').astype(str)

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
    st.caption(f"최근 스캔 상태 (조회일과 별개) · 스캐너 v{status.get('version','?')} · 전체 {status.get('universe','?')}종목 · 제외 {status.get('skipped','?')}종목 · 오류 {status.get('errors','?')}건 · 업데이트 {status.get('updated_at','미확인')}")

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
    # 다운로드는 선택한 종목의 차트를 표시할 때만, 최신 DB가 필요할 때만 수행합니다.
    # GitHub raw의 대용량 파일 다운로드가 실패하면 로컬 DB를 사용하되 경고합니다.
    if remote_ok:
        try:
            with sqlite3.connect(str(db_path)) as check_conn:
                local_db_date = check_conn.execute('SELECT MAX(date) FROM prices').fetchone()[0]
        except sqlite3.Error:
            local_db_date = None
        csv_date = str(df['date'].max()) if 'date' in df else None
        if csv_date and (not local_db_date or str(local_db_date) < csv_date):
            @st.cache_resource(show_spinner=False)
            def remote_history_db(version):
                import tempfile
                import os
                request = urllib.request.Request(RAW_BASE + 'history.sqlite',
                    headers={'User-Agent':'BB-Dashboard/4.0'})
                fd, target = tempfile.mkstemp(suffix='.sqlite', prefix='bb_history_')
                try:
                    with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(request, timeout=120) as response:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    with sqlite3.connect(target) as conn:
                        conn.execute('SELECT 1 FROM prices LIMIT 1').fetchone()
                    return target
                except Exception:
                    if os.path.exists(target):
                        os.remove(target)
                    raise
            try:
                with st.spinner('최신 차트 데이터 다운로드 중 (첫 조회 시 약 60MB)...'):
                    db_path = Path(remote_history_db(csv_date))
            except Exception as exc:
                st.warning(f'최신 차트 DB 다운로드 실패: {exc}. 차트는 이전 날짜 데이터일 수 있습니다.')
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
        if not hist.empty:
            hist = hist.loc[hist['date'].astype(str) <= selected_day].copy()
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
                # Signals are chart annotations, not replacements for scanner eligibility.
                clean['하단 터치'] = (clean['low'] <= clean['BB 하단']) & clean['BB 하단'].notna()
                clean['밴드 재진입'] = ((clean['close'].shift(1) < clean['BB 하단'].shift(1)) &
                                      (clean['close'] >= clean['BB 하단']) & clean['BB 하단'].notna())
                window = st.select_slider('차트 표시 기간 (정상 거래 기록)', options=[20,60,120,200], value=120, key='chart_window')
                view = clean.tail(window).reset_index()
                view['상승'] = view['close'] >= view['open']
                view['캔들색'] = view['상승'].map({True:'상승', False:'하락'})
                # A single hover target for each day, shared by candle and overlays.
                tooltip = [alt.Tooltip('date:T', title='날짜', format='%Y-%m-%d'),
                           alt.Tooltip('open:Q', title='시가', format=',.0f'),
                           alt.Tooltip('high:Q', title='고가', format=',.0f'),
                           alt.Tooltip('low:Q', title='저가', format=',.0f'),
                           alt.Tooltip('close:Q', title='종가', format=',.0f'),
                           alt.Tooltip('volume:Q', title='거래량', format=',.0f')]
                base = alt.Chart(view).encode(x=alt.X('date:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=0)))
                colors = alt.Scale(domain=['상승','하락'], range=['#d94b4b','#3675c9'])
                wick = base.mark_rule(size=1.4).encode(y=alt.Y('low:Q', title='가격 (원)', scale=alt.Scale(zero=False)),
                                                        y2='high:Q', color=alt.Color('캔들색:N', scale=colors, legend=None), tooltip=tooltip)
                body = base.mark_bar(size=5).encode(y='open:Q', y2='close:Q',
                                                    color=alt.Color('캔들색:N', scale=colors, legend=None), tooltip=tooltip)
                layers = [wick, body]
                line_styles = [('BB 상단','#9c70cc'),('BB 하단','#9c70cc'),('MA5','#e3a321'),
                               ('MA20','#248b80'),('MA60','#687eaa'),('MA120','#777777')]
                line_selection = st.multiselect('차트 보조선', [x[0] for x in line_styles],
                                                default=[x[0] for x in line_styles], key='chart_lines')
                for name, color in line_styles:
                    if name in line_selection:
                        layers.append(base.mark_line(color=color, strokeWidth=1.5,
                                                     strokeDash=[5,3] if name.startswith('BB') else [1,0]).encode(
                            y=alt.Y(f'{name}:Q', title='가격 (원)'),
                            tooltip=[alt.Tooltip('date:T', title='날짜', format='%Y-%m-%d'),
                                     alt.Tooltip(f'{name}:Q', title=name, format=',.0f')]))
                levels = [('entry','진입 기준가','#c48a12'),('target1','1차 목표가','#248b80'),
                          ('target2','2차 목표가','#1673aa'),('stop','손절 기준가','#cc4646')]
                show_levels = st.checkbox('매매 기준선 표시 (스캐너 계산값)', value=True, key='chart_levels')
                if show_levels:
                    for key, label, color in levels:
                        value = pd.to_numeric(item.get(key), errors='coerce')
                        if pd.notna(value) and float(value)>0:
                            rule_df = pd.DataFrame({'level':[float(value)]})
                            layers.append(alt.Chart(rule_df).mark_rule(color=color, strokeWidth=1.7, strokeDash=[7,4]).encode(
                                y=alt.Y('level:Q', title='가격 (원)'),
                                tooltip=[alt.Tooltip('level:Q', title=label, format=',.0f')]))
                show_signals = st.checkbox('하단 밴드 터치·재진입 표시', value=True, key='chart_signals')
                if show_signals:
                    for flag, color, shape in [('하단 터치','#e4a12c','circle'),('밴드 재진입','#19a578','diamond')]:
                        events = view.loc[view[flag]].copy()
                        if not events.empty:
                            layers.append(alt.Chart(events).mark_point(shape=shape, size=115, filled=True, color=color).encode(
                                x='date:T', y='low:Q', tooltip=tooltip))
                price_chart = alt.layer(*layers).properties(height=440).interactive(bind_y=False)
                st.altair_chart(price_chart, use_container_width=True)
                st.caption(f'차트 종료일: {selected_day} · 빨강=양봉, 파랑=음봉 · 주황 원=하단 밴드 터치 · 초록 마름모=밴드 재진입. 수평선은 선택한 날짜의 보관 스캔 결과입니다.')
                st.markdown('**RSI(14)**')
                rsi_base = alt.Chart(view).encode(x=alt.X('date:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=0)))
                rsi_line = rsi_base.mark_line(color='#8a63c4', strokeWidth=2).encode(
                    y=alt.Y('RSI(14):Q', title='RSI', scale=alt.Scale(domain=[0,100])),
                    tooltip=[alt.Tooltip('date:T', title='날짜', format='%Y-%m-%d'),alt.Tooltip('RSI(14):Q', title='RSI', format='.1f')])
                rsi_rules = alt.Chart(pd.DataFrame({'level':[30,40,70]})).mark_rule(color='#999999',strokeDash=[4,4]).encode(y='level:Q')
                st.altair_chart((rsi_line+rsi_rules).properties(height=170),use_container_width=True)
                st.markdown('**거래량**')
                vol_chart = alt.Chart(view).mark_bar().encode(
                    x=alt.X('date:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=0)),
                    y=alt.Y('volume:Q', title='거래량'),
                    color=alt.Color('캔들색:N', scale=colors, legend=None),tooltip=tooltip).properties(height=170)
                st.altair_chart(vol_chart,use_container_width=True)
                st.caption('비정상 OHLC·거래량 0 기록은 제외했습니다. 종목별 재계산 지표는 스캐너 수치와 다를 수 있으며, 과거 신호는 매수 추천이 아닙니다.')


with st.expander('판정 기준과 한계'):
    st.markdown('''- **과거 조회**: 실제 저장된 일별 스캔 결과만 표시합니다. 기록이 없는 날짜는 선택할 수 없습니다.
- **신규 후보**: 스캐너에서 `eligible=True`로 판정된 종목만 표시합니다.\n- **관심 후보**: 7점 이상이지만 신규 후보가 아닌 종목입니다. 거래대금 부족 등 제외 사유를 반드시 확인하세요.\n- **관찰 후보**: 6점 이상 7점 미만 종목입니다. 매수 신호를 뜻하지 않습니다.\n- **목표가/손절가**: 스캐너 계산값을 그대로 표시합니다. 값이 없으면 임의로 만들지 않습니다.\n- **미구현**: 업종 상대강도, 공식 거래일 검증, 자동 수동 입력 동기화, 매물대 계산.\n- **시세**: GitHub Actions 마지막 실행 기준 종가 데이터이며 실시간이 아닙니다.''')
