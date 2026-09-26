"""Валидация v7 с календарём isdayoff (как в новом движке) против ручного календаря v7. Код v7 только читается."""
import sys, datetime as dt
sys.path.insert(0,'/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
sys.path.insert(0,'/private/tmp/claude-501/-Users-denis-Documents-----------------------------/010cb3cc-d4d5-4cc0-bfa4-a45169a45c88/scratchpad/repo')
import model
from clean import *
from service.engine.sources import fetch_calendar
from service.engine.core import Calendar
from pathlib import Path
codes,st=fetch_calendar([2024,2025,2026],Path('cache')); print('календарь isdayoff:',st['years'])
cal=Calendar(codes)
V7=set(model.DAYOFF); ISD={pd.Timestamp(d) for d in cal.holidays if d.year==2025}
print('праздничные дни v7 (ручной список):',len(V7),'| isdayoff:',len(ISD))
print('есть только в v7:',sorted(d.strftime('%m-%d') for d in V7-ISD),'| только в isdayoff:',sorted(d.strftime('%m-%d') for d in ISD-V7))
def run(dayoff):
    model.DAYOFF.clear(); model.DAYOFF.update(dayoff)          # тот же объект используется в cal(), build(), dtype()
    rows={}
    for fold in ['F1','F4','F2','F3']:
        o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
        fac=seas(o,sorted(te.date.dt.month.unique())); b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
        c=clean_grid(tr,1.5,protect_weeks=0)[0]; _,cb,pf=forecast(c,fr,best,seeds=5,fac=fac); p=np.where(hol,cb,w*cb+(1-w)*pf)
        rows[fold]=round(1-wape(y,p),5)
    return rows
a=run(V7); b=run(ISD)
print("\nВАЛИДАЦИЯ (обучение до даты → прогноз вперёд), 5 моделей как в финале v7")
print(f"{'период':28s} {'v7 (ручной календарь)':>22s} {'v7 + isdayoff (движок)':>24s}")
for k,lab in [('F1','сен–окт (test, основная)'),('F4','май–июнь'),('F2','июль–август'),('F3','март–апрель')]: print(f"{lab:28s} {a[k]:22.5f} {b[k]:24.5f}")
print(f"{'среднее':28s} {np.mean(list(a.values())):22.5f} {np.mean(list(b.values())):24.5f}")
model.DAYOFF.clear(); model.DAYOFF.update(V7)
