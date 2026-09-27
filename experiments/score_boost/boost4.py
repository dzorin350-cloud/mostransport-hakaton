from boost3 import *
def predict2(fold, w_wd=0.6, w_we=0.6, lam=0.6, we_weeks=None, we_agg='median', peak_wd=None, night_w=None):
    b, tr = comp(fold, 2, 4, 'median')
    pf = b.pf.values.copy()
    if we_weeks:
        b2, _ = comp(fold, 2, we_weeks, we_agg); we = b.dow.values >= 5; pf[we] = b2.pf.values[we]
    w = np.where(b.dow.values >= 5, w_we, w_wd)
    if peak_wd is not None:
        pk = b.hour.isin([7,8,9,17,18,19]).values & (b.dow.values < 5); w = np.where(pk, peak_wd, w)
    if night_w is not None:
        nt = b.hour.isin([0,1,2,3,4,5,22,23]).values; w = np.where(nt, night_w, w)
    w = np.where(b.hol_wd.values == 1, 1.0, w)
    pred = w * b.cb.values + (1 - w) * pf
    bt = beta_v(tr); kr = b.f.values ** (lam * (b.route.map(bt).fillna(1.0).values - 1))
    return 1 - wape(b.boardings.values, pred * kr)
def run2(name, **kw):
    r = {f: predict2(f, **kw) for f in ORDER}; m4 = np.mean(list(r.values())); m3 = np.mean([r[f] for f in ['F4','F2','F1']])
    print(f"{name:<50} " + "  ".join(f"{f}:{r[f]:.4f}" for f in ORDER) + f" | ср.4 {m4:.4f} | ср.3 {m3:.4f}", flush=True); return r
run2('D2 (выходные 0,6, λ 0,6)')
run2('D1 (выходные 0,6, λ 0,5)',lam=0.5)
print('=== вес CatBoost в выходные ниже 0,6')
for we in [0.5,0.4,0.3,0.2,0.0]: run2(f'   выходные {we}',w_we=we)
print('=== профиль выходных — длиннее окно')
for wk,ag in [(6,'median'),(8,'median'),(8,'mean'),(12,'median')]:
    for we in [0.6,0.4]: run2(f'   профиль выходных {wk} нед. {ag}, вес {we}',we_weeks=wk,we_agg=ag,w_we=we)
print('=== вес по часам')
for pk in [0.5,0.7]: run2(f'   пиковые часы будней {pk}',peak_wd=pk)
for nt in [0.8,0.4]: run2(f'   ночные часы {nt}',night_w=nt)
