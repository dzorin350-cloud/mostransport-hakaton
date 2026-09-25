import sys, json, time
from tg import get, parse
ch=sys.argv[1]
def page(before=None):
    return parse(get(f"https://t.me/s/{ch}"+(f"?before={before}" if before else "")))
top=page(); mx=max(int(m['id'].split('/')[1]) for m in top); print(ch,"max id",mx,top[-1]['t'])
def date_at(i):
    ms=page(i)
    return min(m['t'] for m in ms) if ms else None
def find(target):
    lo,hi=1,mx
    while hi-lo>20:
        mid=(lo+hi)//2; d=date_at(mid)
        if d is None or d<target: lo=mid
        else: hi=mid
    return lo
a=find('2025-01-01'); b=find('2025-11-01'); print("ids",a,b,flush=True)
res={}; cur=b+20
while cur>a:
    ms=page(cur)
    if not ms: cur-=20; continue
    for m in ms: res[m['id']]=m
    cur=min(int(m['id'].split('/')[1]) for m in ms); time.sleep(0.2)
r=[m for m in res.values() if '2025-01-01'<=m['t']<'2025-11-01']
json.dump(r,open(f'tg_{ch}_2025.json','w'),ensure_ascii=False)
tr=[m for m in r if 'трамва' in m['text'].lower()]
print(ch,"постов янв–окт 2025:",len(r),"| про трамваи:",len(tr))
