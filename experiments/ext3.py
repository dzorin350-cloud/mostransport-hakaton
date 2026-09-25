import sys, itertools
src=open('ext.py').read().split("CAL=['off'")[0]
src=src.replace("fr=build(te[['route','date','hour']]); trb=build(tr)","fr=build(te[['route','date','hour']]); trb=build(tr); trb=trb.merge(T,on='date',how='left'); fr=fr.merge(T,on='date',how='left')")
# T: справочник признаков по датам
exec(src)
dr=pd.date_range('2024-11-01','2026-02-28'); cc=cal(dr).set_index('date'); off=cc.off
T=pd.DataFrame(index=dr)
T['to_off']=[next((k for k in range(1,7) if off.get(d+pd.Timedelta(days=k),0)==1),7) for d in dr]
T['since_off']=[next((k for k in range(1,7) if off.get(d-pd.Timedelta(days=k),0)==1),7) for d in dr]
def blk(d):
    if off[d]==0: return 0
    a=b=0
    while off.get(d-pd.Timedelta(days=a+1),0)==1: a+=1
    while off.get(d+pd.Timedelta(days=b+1),0)==1: b+=1
    return min(a+b+1,12)
T['blk']=[blk(d) for d in dr]
SCH=[('2024-12-29','2025-01-08'),('2025-03-29','2025-04-06'),('2025-05-24','2025-08-31'),('2025-10-25','2025-11-02'),('2025-12-31','2026-01-11')]
T['school']=0
for a,b in SCH: T.loc[a:b,'school']=1
T['event']=0
for a,b in [('2025-04-19','2025-04-20'),('2025-09-06','2025-09-07')]: T.loc[a:b,'event']=1   # Пасха; День города
T.index.name='date'; T=T.reset_index()
G_CAL=['to_off','since_off','blk']; G_SCH=['school']; G_EV=['event']; G_W=['t','pr','sn']
combos=[('база',[]),('+календарь расш.',G_CAL),('+каникулы',G_SCH),('+события',G_EV),('+погода(норма)',G_W),
        ('+кал+каникулы',G_CAL+G_SCH),('+кал+кан+события',G_CAL+G_SCH+G_EV),('+кал+кан+погода',G_CAL+G_SCH+G_W),('всё',G_CAL+G_SCH+G_EV+G_W)]
folds=[('F3','мар–апр'),('F4','май–июнь'),('F2','июл–авг'),('F1','сен–окт')]
res=[]
for nm,ex in combos:
    r=[]
    for f,_ in folds:
        r.append(run(BASE+ex,'clim' if any(x in ex for x in G_W) else None,fold=f,seeds=1)[0])
    res.append((nm,)+tuple(round(x,4) for x in r)+(round(float(np.mean(r)),4),)); print(res[-1],flush=True)
df=pd.DataFrame(res,columns=['сочетание']+[l for _,l in folds]+['среднее']); df.to_csv('ablation3.csv',index=False)
print("\n",df.sort_values('среднее',ascending=False).to_string(index=False))
