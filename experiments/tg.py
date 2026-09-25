import subprocess, re, html, json, sys, time, urllib.parse
def get(url):
    return subprocess.run(['curl','-s','-m','30','-A','Mozilla/5.0',url],capture_output=True,text=True).stdout
def parse(h):
    out=[]
    for m in re.finditer(r'data-post="([^"]+)".*?<time datetime="([^"]+)"',h,re.S): pass
    blocks=h.split('tgme_widget_message_wrap')[1:]
    for b in blocks:
        pid=re.search(r'data-post="([^"]+)"',b); t=re.search(r'<time datetime="([^"]+)"',b); tx=re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>',b,re.S)
        if pid and t:
            txt=html.unescape(re.sub(r'<br\s*/?>','\n',tx.group(1))) if tx else ''; txt=re.sub(r'<[^>]+>','',txt)
            out.append(dict(id=pid.group(1),t=t.group(1),text=txt))
    return out
def search(ch,q,pages=30):
    res={}; url=f"https://t.me/s/{ch}?q={urllib.parse.quote(q)}"
    for i in range(pages):
        h=get(url); ms=parse(h)
        if not ms: break
        for m in ms: res[m['id']]=m
        mn=min(int(m['id'].split('/')[1]) for m in ms)
        if min(m['t'] for m in ms)<'2024-12-01': break
        url=f"https://t.me/s/{ch}?q={urllib.parse.quote(q)}&before={mn}"; time.sleep(0.5)
    return list(res.values())
if __name__=='__main__':
    ch=sys.argv[1]; q=sys.argv[2]; r=search(ch,q); json.dump(r,open(f'tg_{ch}_{q}.json','w'),ensure_ascii=False)
    r=[m for m in r if '2025-01-01'<=m['t']<'2025-11-01']; print(ch,q,"постов 2025 (до 1 нояб):",len(r))
