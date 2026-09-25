from pipe3 import *
print("r_pre (выходной/будень до сентября):",r_pre(G[G.date<='2025-10-31']).round(3)[[7,50]].to_dict())
rows=[]
for nm,(o,s,e,fm) in {'Окт (5–31)':('2025-10-04','2025-10-05','2025-10-31','none'),'F1 сен–окт':(*FOLDS['F1'],'seas'),'F4 май–июнь':(*FOLDS['F4'],'seas'),'F2 июл–авг':(*FOLDS['F2'],'seas'),'F3 мар–апр':(*FOLDS['F3'],'seas')}.items():
    o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; mo=sorted(te.date.dt.month.unique()); fac=seas(o,mo) if fm=='seas' else {m:1.0 for m in mo}
    frb=add_reg2(build(te[['route','date','hour']])); p0,_,_=forecast2(tr,add_reg(build(te[['route','date','hour']])),best,fac,seeds=2,use_reg=False,wd=False); p3,_,_=forecast3(tr,frb,best,fac,seeds=2)
    m57=np.isin(te.route.values,CUT)
    rows.append((nm,round(1-wape(y,p0),4),round(1-wape(y,p3),4),round(p0.sum()/y.sum()-1,4),round(p3.sum()/y.sum()-1,4),round(np.abs(y-p0)[m57].sum()/1000,1),round(np.abs(y-p3)[m57].sum()/1000,1))); print(rows[-1],flush=True)
df=pd.DataFrame(rows,columns=['период','скор v4-схема','скор v6-схема','смещение v4','смещение v6','ошибка 7+50 v4 (тыс.)','ошибка 7+50 v6 (тыс.)']); print(df.to_string(index=False)); print("среднее скор:",df[['скор v4-схема','скор v6-схема']].mean().round(4).to_dict())
