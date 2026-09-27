from boost3 import *
print('F3 мар–апр, F4 май–июн, F2 июл–авг, F1 сен–окт; «ср.3» — без мар–апр (там β не считается)')
run('ИТОГОВАЯ МОДЕЛЬ C1 (0,6/0,8, 4 нед. медиана, λ=0,5)')
print('=== 1а. веса смеси (будни / выходные)')
res=[]
for a,bw in itertools.product([0.4,0.5,0.6,0.7,0.8],[0.6,0.7,0.8,0.9,1.0]):
    r,m4,m3=run(f'   будни {a} / выходные {bw}',w_wd=a,w_we=bw); res.append((m4,m3,a,bw,r))
print('   лучшие по ср.4:',[(round(x[0],4),x[2],x[3]) for x in sorted(res,reverse=True)[:4]])
print('=== 1б. праздничные будни: доля CatBoost')
for h in [0.8,0.6]: run(f'   праздничные будни CatBoost {h}',w_hol=h)
print('=== 1в. профиль: окно и агрегат')
for wk,ag in [(3,'median'),(5,'median'),(6,'median'),(4,'mean'),(8,'median')]: run(f'   профиль {wk} нед. {ag}',weeks=wk,agg=ag)
print('=== 2а. сжатие β')
for lam in [0.0,0.3,0.4,0.6,0.7,1.0]: run(f'   λ={lam}',lam=lam)
print('=== 2б. способ оценки β')
for bm,nm in [((True,False),'только будни'),((False,True),'без января'),((True,True),'будни, без января')]:
    for lam in [0.5,0.7]: run(f'   β: {nm}, λ={lam}',bmode=bm,lam=lam)
print('=== 3. число seed CatBoost (в каждом из двух наборов)')
for s in [5,10]: run(f'   seed = {s}',seeds=s)
