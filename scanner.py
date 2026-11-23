import os, json, time, sqlite3, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

OUT = Path(__file__).parent / 'data'
OUT.mkdir(exist_ok=True)
CACHE = OUT / 'history.sqlite'
WORKERS = max(1, min(int(os.getenv('BB_WORKERS', '4')), 6))
MIN_TURNOVER = 2_000_000_000


def universe():
    stocks = fdr.StockListing('KRX')
    code = 'Code' if 'Code' in stocks.columns else 'Symbol'
    market = 'Market'
    stocks = stocks[stocks[market].isin(['KOSPI','KOSDAQ'])].copy()
    stocks[code] = stocks[code].astype(str).str.zfill(6)
    return stocks.rename(columns={code:'Code'})[['Code','Name','Market']].drop_duplicates('Code')

def validate_history(df):
    """Return (reason, details). Do not silently loosen trading-data checks."""
    if df is None or df.empty:
        return '시세 데이터 없음', {'rows': 0}
    d = df.sort_index()
    details = {'rows': len(d), 'first_date': str(d.index[0].date()),
               'last_date': str(d.index[-1].date())}
    if len(d) < 125:
        return '125거래일 미만', details
    cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing = [x for x in cols if x not in d.columns]
    if missing:
        details['columns'] = missing
        return '필수 시세 열 누락', details
    recent = d[cols].tail(125).apply(pd.to_numeric, errors='coerce')
    nan_counts = recent.isna().sum()
    if nan_counts.any():
        details['nan_counts'] = {k: int(v) for k, v in nan_counts.items() if v}
        return '가격/거래량 결측치', details
    if (recent[['Open','High','Low','Close']] <= 0).any().any():
        details['bad_price_days'] = int((recent[['Open','High','Low','Close']] <= 0).any(axis=1).sum())
        return '0 이하 가격 존재', details
    if (recent['High'] < recent[['Open','Close','Low']].max(axis=1)).any():
        return '고가 OHLC 불일치', details
    if (recent['Low'] > recent[['Open','Close','High']].min(axis=1)).any():
        return '저가 OHLC 불일치', details
    if (recent['Volume'] < 0).any():
        return '음수 거래량', details
    if recent['Volume'].iloc[-1] == 0:
        details['zero_volume_days_125'] = int((recent['Volume'] == 0).sum())
        return '마지막 시세일 거래량 0', details
    return None, details


def score(df):
    if len(df) < 125: return None
    d = df.copy().sort_index()
    for c in ['Open','High','Low','Close','Volume']:
        d[c] = pd.to_numeric(d[c],errors='coerce')
    if d[['Open','High','Low','Close','Volume']].tail(125).isna().any().any(): return None
    if (d[['Open','High','Low','Close']].tail(125) <= 0).any().any(): return None
    if (d['High'].tail(125) < d[['Open','Close','Low']].tail(125).max(axis=1)).any(): return None
    if (d['Low'].tail(125) > d[['Open','Close','High']].tail(125).min(axis=1)).any(): return None
    if (d['Volume'].tail(125) < 0).any(): return None
    if d['Volume'].iloc[-1] == 0: return None
    c,h,l,o,v = (d[x] for x in ['Close','High','Low','Open','Volume'])
    mid=c.rolling(20).mean(); std=c.rolling(20).std(ddof=0); lower=mid-2*std
    delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    rsi = rsi.where(loss.ne(0), np.where(gain.gt(0), 100.0, 50.0))
    rsi = rsi.fillna(50.0)
    ma5=c.rolling(5).mean(); ma60=c.rolling(60).mean(); ma120=c.rolling(120).mean()
    amount=(c*v).rolling(20).mean().iloc[-1]
    touched=(l.iloc[-5:]<=lower.iloc[-5:]).any()
    reentered=bool(c.iloc[-1]>lower.iloc[-1] and c.iloc[-2]<=lower.iloc[-2])
    recent_reentry=bool(any(c.iloc[i]>lower.iloc[i] and c.iloc[i-1]<=lower.iloc[i-1] for i in range(len(c)-3,len(c))))
    rsi_recover=bool(30<=rsi.iloc[-1]<=45 and rsi.iloc[-1]>rsi.iloc[-2])
    candle_range=max(h.iloc[-1]-l.iloc[-1],0.01)
    lower_wick=(min(o.iloc[-1],c.iloc[-1])-l.iloc[-1])/candle_range
    candle=bool(lower_wick>=0.35 and c.iloc[-1]>o.iloc[-1])
    volratio=float(v.iloc[-1]/max(v.iloc[-21:-1].mean(),1))
    support=bool(abs(c.iloc[-1]/ma60.iloc[-1]-1)<0.03 or abs(c.iloc[-1]/ma120.iloc[-1]-1)<0.03 or l.iloc[-1]>=l.iloc[-21:-1].min()*0.99)
    bandwalk=bool((c.iloc[-4:]<lower.iloc[-4:]).sum()>=3)
    liquid=bool(amount>=MIN_TURNOVER)
    # Relative sector strength unavailable without reliable sector mapping: no unearned points.
    points=(2 if reentered else 1 if recent_reentry else 0)+(1.5 if rsi_recover else 0)+(1.5 if candle else 0)+(1.5 if volratio>=1.5 else .75 if volratio>=1.15 else 0)+(1 if support else 0)+(1 if liquid else 0)+(.5 if not bandwalk else 0)
    points=round(float(points),1)
    prev_low=float(l.iloc[-2]); stop=prev_low*(1-0.002)
    entry=float(c.iloc[-1])
    # Moving averages below entry are not valid upside targets. Do not invent a 3% target.
    resistances=sorted({round(float(x), 4) for x in [ma5.iloc[-1],mid.iloc[-1]] if np.isfinite(x) and entry < x <= entry*1.05})
    target1=resistances[0] if resistances else np.nan
    target2=resistances[1] if len(resistances)>1 else np.nan
    reasons=[]
    if points<7: reasons.append('점수 미달')
    if not liquid: reasons.append('거래대금 부족')
    if bandwalk: reasons.append('밴드워크')
    if not reentered: reasons.append('당일 재진입 미확인')
    if stop<=0 or stop>=entry: reasons.append('손절선 부적합')
    if not resistances: reasons.append('상방 목표가 없음')
    eligible=not reasons
    return dict(date=str(d.index[-1].date()),close=round(entry,2),rsi=round(float(rsi.iloc[-1]),1),volume_ratio=round(volratio,2),turnover_20d=round(float(amount)),score=points,eligible=eligible,bandwalk=bandwalk,reentry=reentered,entry=round(entry,2),target1=round(target1,2),target2=round(target2,2),stop=round(stop,2),risk_reward=round((target1-entry)/(entry-stop),2) if 0<stop<entry and np.isfinite(target1) else None,exclusion_reason='; '.join(reasons),ma5=round(float(ma5.iloc[-1]),2),ma20=round(float(mid.iloc[-1]),2),sector_strength='미측정',target1_basis='MA5/MA20 상방 저항',data_quality='정상')

def open_cache():
    conn = sqlite3.connect(CACHE)
    conn.execute('CREATE TABLE IF NOT EXISTS prices (code TEXT NOT NULL, date TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(code,date))')
    conn.execute('CREATE INDEX IF NOT EXISTS prices_by_code ON prices(code,date)')
    conn.commit()
    return conn


def cached_frame(conn, code):
    rows = conn.execute('SELECT date,open,high,low,close,volume FROM prices WHERE code=? ORDER BY date', (code,)).fetchall()
    if not rows:
        return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])
    d = pd.DataFrame(rows, columns=['Date','Open','High','Low','Close','Volume'])
    d['Date'] = pd.to_datetime(d['Date'])
    return d.set_index('Date')


def fetch_one(code, start):
    # Each thread fetches independently; SQLite reads/writes remain in the main thread.
    last_error = None
    for attempt in range(2):
        try:
            return fdr.DataReader(code, start)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)
    raise last_error


def save_prices(conn, code, df):
    if df is None or df.empty:
        return
    d = df.copy()
    d.index = pd.to_datetime(d.index)
    values = []
    for day, row in d.iterrows():
        try:
            values.append((code, day.strftime('%Y-%m-%d'), *[float(row[k]) for k in ['Open','High','Low','Close','Volume']]))
        except (ValueError, TypeError, KeyError):
            continue
    conn.executemany('INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)', values)


def run():
    print('BB scan v0.4 started', flush=True)
    stocks = universe()
    print(f'Universe: {len(stocks)} | workers={WORKERS}', flush=True)
    now = pd.Timestamp.now(tz='Asia/Seoul')
    start_full = (now - pd.Timedelta(days=340)).strftime('%Y-%m-%d')
    conn = open_cache()
    tasks = {}
    for stock in stocks.itertuples(index=False):
        old = cached_frame(conn, stock.Code)
        # Re-fetch recent 14 calendar days to capture corrections and late updates.
        start = (old.index[-1] - pd.Timedelta(days=14)).strftime('%Y-%m-%d') if len(old) >= 125 else start_full
        tasks[stock.Code] = (stock, start)
    rows, errors, skipped = [], [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, code, start): code for code, (_, start) in tasks.items()}
        for idx, future in enumerate(as_completed(futures), 1):
            code = futures[future]
            stock, _ = tasks[code]
            try:
                fresh = future.result()
                save_prices(conn, code, fresh)
                conn.commit()
                d = cached_frame(conn, code)
                # Keep only recent 200 trading days per symbol.
                if len(d) > 200:
                    cutoff = d.index[-200].strftime('%Y-%m-%d')
                    conn.execute('DELETE FROM prices WHERE code=? AND date<?', (code, cutoff))
                    conn.commit()
                    d = d.tail(200)
                skip_reason, details = validate_history(d)
                result = score(d) if skip_reason is None else None
                if result:
                    rows.append(dict(code=code, name=stock.Name, market=stock.Market, **result))
                else:
                    skipped.append({'code':code,'name':stock.Name,'reason':skip_reason or '점수 계산 불가', **details})
            except Exception as exc:
                errors.append({'code':code,'name':stock.Name,'error':str(exc)[:200]})
            if idx % 50 == 0 or idx == len(stocks):
                print(f'Progress {idx}/{len(stocks)} | scored={len(rows)} skipped={len(skipped)} errors={len(errors)}', flush=True)
    conn.close()
    data = pd.DataFrame(rows)
    if data.empty:
        raise RuntimeError('분석 결과 0건: 이전 latest.csv는 덮어쓰지 않았습니다.')
    dates = data['date'].value_counts().to_dict()
    latest_day = max(dates)
    # Historical or stale rows are for observation only, never fresh buy signals.
    stale = data['date'] != latest_day
    data.loc[stale, 'eligible'] = False
    data.loc[stale, 'exclusion_reason'] = data.loc[stale, 'exclusion_reason'].fillna('').apply(lambda x: (x+'; ' if x else '')+'최신 데이터 날짜 불일치')
    data = data.sort_values(['eligible','score','turnover_20d'],ascending=[False,False,False])
    data.to_csv(OUT/'latest.csv',index=False,encoding='utf-8-sig')
    reason_counts = pd.Series([x['reason'] for x in skipped]).value_counts().to_dict() if skipped else {}
    (OUT/'status.json').write_text(json.dumps({
        'version':'0.4', 'updated_at':now.isoformat(), 'universe':len(stocks),
        'processed':len(rows), 'errors':len(errors), 'skipped':len(skipped),
        'skip_reason_counts':reason_counts,
        'date_counts':dates, 'latest_data_date':latest_day,
        'eligible':int(data['eligible'].sum()), 'workers':WORKERS,
        'note':'최신 날짜는 종목 데이터 중 최대 날짜 기준이며 공식 거래일 검증은 별도 필요. 업종 상대강도 미측정.'
    },ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'skipped.json').write_text(json.dumps(skipped,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Skip reasons: {reason_counts}', flush=True)
    print(f'Completed | scored={len(rows)} skipped={len(skipped)} errors={len(errors)} eligible={int(data.eligible.sum())} | latest={latest_day}', flush=True)


if __name__ == '__main__':
    run()
