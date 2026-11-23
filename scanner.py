import os, json, time
from pathlib import Path
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

OUT = Path(__file__).parent / 'data'
OUT.mkdir(exist_ok=True)

def universe():
    stocks = fdr.StockListing('KRX')
    code = 'Code' if 'Code' in stocks.columns else 'Symbol'
    market = 'Market'
    stocks = stocks[stocks[market].isin(['KOSPI','KOSDAQ'])].copy()
    stocks[code] = stocks[code].astype(str).str.zfill(6)
    return stocks.rename(columns={code:'Code'})[['Code','Name','Market']].drop_duplicates('Code')

def score(df):
    if len(df) < 125: return None
    d = df.copy().sort_index()
    for c in ['Open','High','Low','Close','Volume']:
        d[c] = pd.to_numeric(d[c],errors='coerce')
    if d[['Open','High','Low','Close','Volume']].tail(125).isna().any().any(): return None
    c,h,l,o,v = (d[x] for x in ['Close','High','Low','Open','Volume'])
    mid=c.rolling(20).mean(); std=c.rolling(20).std(ddof=0); lower=mid-2*std
    delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    rsi=rsi.fillna(100)
    ma5=c.rolling(5).mean(); ma60=c.rolling(60).mean(); ma120=c.rolling(120).mean()
    amount=(c*v).rolling(20).mean().iloc[-1]
    touched=(l.iloc[-5:]<=lower.iloc[-5:]).any()
    reentered=bool(c.iloc[-1]>lower.iloc[-1] and c.iloc[-2]<=lower.iloc[-2])
    recent_reentry=bool((c.iloc[-3:] > lower.iloc[-3:]).any() and touched)
    rsi_recover=bool(30<=rsi.iloc[-1]<=45 and rsi.iloc[-1]>rsi.iloc[-2])
    candle_range=max(h.iloc[-1]-l.iloc[-1],0.01)
    lower_wick=(min(o.iloc[-1],c.iloc[-1])-l.iloc[-1])/candle_range
    candle=bool(lower_wick>=0.35 and c.iloc[-1]>o.iloc[-1])
    volratio=float(v.iloc[-1]/max(v.iloc[-21:-1].mean(),1))
    support=bool(abs(c.iloc[-1]/ma60.iloc[-1]-1)<0.03 or abs(c.iloc[-1]/ma120.iloc[-1]-1)<0.03 or l.iloc[-1]>=l.iloc[-21:-1].min()*0.99)
    bandwalk=bool((c.iloc[-4:]<lower.iloc[-4:]).sum()>=3)
    liquid=bool(amount>=2_000_000_000)
    # Relative sector strength unavailable without reliable sector mapping: no unearned points.
    points=(2 if reentered else 1 if recent_reentry else 0)+(1.5 if rsi_recover else 0)+(1.5 if candle else 0)+(1.5 if volratio>=1.5 else .75 if volratio>=1.15 else 0)+(1 if support else 0)+(1 if liquid else 0)+(.5 if not bandwalk else 0)
    points=round(float(points),1)
    prev_low=float(l.iloc[-2]); stop=prev_low*(1-0.002)
    entry=float(c.iloc[-1]); target1=float(max(ma5.iloc[-1],entry*1.03)); target2=float(mid.iloc[-1]);
    # Targets are capped by a 5% tactical objective and flagged if resistance is below entry.
    target1=min(target1,entry*1.05)
    target2=min(max(target2,entry),entry*1.05)
    eligible=bool(points>=7 and liquid and not bandwalk and reentered and stop<entry)
    return dict(date=str(d.index[-1].date()),close=round(entry,2),rsi=round(float(rsi.iloc[-1]),1),volume_ratio=round(volratio,2),turnover_20d=round(float(amount)),score=points,eligible=eligible,bandwalk=bandwalk,reentry=reentered,entry=round(entry,2),target1=round(target1,2),target2=round(target2,2),stop=round(stop,2),risk_reward=round((target1-entry)/(entry-stop),2) if entry>stop else None,sector_strength='미측정')

def run():
    stocks=universe(); rows=[]; errors=[]
    for idx,stock in enumerate(stocks.itertuples(index=False),1):
        try:
            df=fdr.DataReader(stock.Code, (pd.Timestamp.now(tz='Asia/Seoul')-pd.Timedelta(days=260)).strftime('%Y-%m-%d'))
            result=score(df)
            if result: rows.append(dict(code=stock.Code,name=stock.Name,market=stock.Market,**result))
        except Exception as e:
            errors.append({'code':stock.Code,'error':str(e)[:120]})
        if idx%50==0: time.sleep(1)
    data=pd.DataFrame(rows)
    if not data.empty:
        data=data.sort_values(['eligible','score','turnover_20d'],ascending=[False,False,False])
        data.to_csv(OUT/'latest.csv',index=False,encoding='utf-8-sig')
    (OUT/'status.json').write_text(json.dumps({'updated_at':pd.Timestamp.now(tz='Asia/Seoul').isoformat(),'universe':len(stocks),'processed':len(rows),'errors':len(errors),'eligible':int(data.eligible.sum()) if not data.empty else 0,'note':'업종 상대강도 미측정: 점수 최대 9점. 무료 공급원 당일 갱신 시각 검증 필요.'},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': run()
