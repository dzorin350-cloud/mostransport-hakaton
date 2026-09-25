from clean import *
import calendar as _c
from year_city import S, fc
def fac_year(o):
    """множители суток месяца к месяцу origin (город, только данные <= origin), метод 'сезонность все годы'"""
    op=pd.Period(o,'M'); f=fc(op,h=12,method='seas'); return {p.month:float(f[p]/S[op]) for p in f.index}, f
rows=[]
for o in ['2025-02-28','2025-03-31','2025-04-30']:
    o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>o)&(G.date<='2025-10-31')].copy(); fr=te[['route','date','hour']]
    fac,_=fac_year(o); b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
    c=clean_grid(tr,1.5,protect_weeks=0)[0]
    for nm,ff in [('без сезонности',{m:1.0 for m in fac}),('12-мес. множители (город)',fac)]:
        _,cb,pf=forecast(c,fr,best,seeds=2,fac=ff); p=np.where(hol,cb,w*cb+(1-w)*pf); te[nm]=p
    for m,g in te.groupby(te.date.dt.month):
        rows.append((o.strftime('%Y-%m'),m,(m-o.month),round(1-wape(g.boardings.values,g['без сезонности'].values),4),round(1-wape(g.boardings.values,g['12-мес. множители (город)'].values),4)))
    y=te.boardings.values; print(o.date(),'весь период: без сезонности',round(1-wape(y,te['без сезонности'].values),4),'| с множителями',round(1-wape(y,te['12-мес. множители (город)'].values),4),flush=True)
df=pd.DataFrame(rows,columns=['обучение до','месяц','горизонт, мес','без сезонности','с 12-мес. множителями']); print(df.to_string(index=False))
print(df.groupby('горизонт, мес')[['без сезонности','с 12-мес. множителями']].mean().round(4).to_string())
df.to_csv('year_route_result.csv',index=False)
