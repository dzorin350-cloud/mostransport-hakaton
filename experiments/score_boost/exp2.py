from harness import *
import harness
print('--- разложение ошибки (оракулы)')
def oracle_level(tr,b):   # истинный средний уровень маршрута на тестовом периоде / сезонный множитель — чтобы после ×f получить истину
    return None
# 1) истинный уровень маршрута за период (без сезонности): post_fn перемасштабирует прогноз по маршруту к истинной сумме
def post_route_total(pred,b,tr):
    s=b.assign(p=pred).groupby('route').apply(lambda g:g.boardings.sum()/g.p.sum()); return pred*b.route.map(s).values
evaluate('ОРАКУЛ: истинная сумма маршрута за 2 мес.',post_fn=post_route_total)
def post_route_month(pred,b,tr):
    k=[b.route,b.date.dt.month]; s=b.assign(p=pred).groupby(k).boardings.transform('sum')/b.assign(p=pred).groupby(k).p.transform('sum'); return pred*s.values
evaluate('ОРАКУЛ: истинная сумма маршрут×месяц',post_fn=post_route_month)
def post_route_day(pred,b,tr):
    k=[b.route,b.date]; s=b.assign(p=pred).groupby(k).boardings.transform('sum')/b.assign(p=pred).groupby(k).p.transform('sum').replace(0,np.nan); return pred*s.fillna(1).values
evaluate('ОРАКУЛ: истинная сумма маршрут×день (ошибка только формы)',post_fn=post_route_day)
print('--- уровень: окно')
for lvl in [28,42,70,84,112]: evaluate(f'lvl={lvl}',lvl=lvl)
print('--- профиль и смесь')
for wk in [1,3,4,6]: evaluate(f'профиль {wk} нед.',weeks=wk)
evaluate('профиль медиана 2 нед.',prof_agg='median'); evaluate('профиль медиана 4 нед.',weeks=4,prof_agg='median')
for a,bb in [(0.5,0.8),(0.7,0.8),(0.8,0.8),(0.6,0.6),(0.6,0.9),(0.6,1.0),(1.0,1.0),(0.0,0.0)]: evaluate(f'смесь будни {a} / выходные {bb}',w_wd=a,w_we=bb)
