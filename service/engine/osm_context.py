"""Окружение остановок по OpenStreetMap (Overpass API): жилые дома и точки притяжения в радиусе 400 м.
Результат кэшируется в artifacts/osm_stop_context.csv — сборка разбивки по остановкам воспроизводима без сети.
Данные OSM © участники OpenStreetMap, лицензия ODbL."""
import json, math, ssl, sys, time, urllib.parse, urllib.request
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()
from pathlib import Path
import numpy as np, pandas as pd
ART = Path(__file__).resolve().parent / "artifacts"
URLS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"]
RES = 'way["building"~"^(apartments|residential|dormitory)$"]'
ATTR = ['nwr["office"]', 'nwr["amenity"~"^(university|college|school|hospital|clinic|theatre|cinema|marketplace)$"]',
        'nwr["shop"~"^(mall|supermarket|department_store)$"]', 'way["building"~"^(office|commercial|retail|university|college|school|hospital)$"]']
def overpass(q):
    for u in URLS:
        try:
            req = urllib.request.Request(u, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "tram-forecast/1.0 (hackathon)"})
            return json.loads(urllib.request.urlopen(req, timeout=200, context=CTX).read())["elements"]
        except Exception as exc:
            print("  overpass", u, exc, flush=True); time.sleep(3)
    raise RuntimeError("Overpass недоступен")
def _levels(v):
    """этажность из тега OSM: «9», «10-16», «5;7», «12,5» → число; нет тега — 5"""
    import re
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", str(v or ""))]
    return max(nums) if nums else 5.0
def fetch(stops, pad=0.006, n=3):
    la0, la1, lo0, lo1 = stops.lat.min() - pad, stops.lat.max() + pad, stops.lon.min() - pad, stops.lon.max() + pad
    res, attr = [], []
    for i in range(n):
        for j in range(n):
            b = f"({la0+(la1-la0)*i/n},{lo0+(lo1-lo0)*j/n},{la0+(la1-la0)*(i+1)/n},{lo0+(lo1-lo0)*(j+1)/n})"
            r = overpass(f'[out:json][timeout:180];{RES}{b};out tags center;')
            res += [(e["center"]["lat"], e["center"]["lon"], _levels(e.get("tags", {}).get("building:levels"))) for e in r if "center" in e]
            a = overpass(f'[out:json][timeout:180];({";".join(x + b for x in ATTR)};);out center;')
            attr += [((e.get("center") or e)["lat"], (e.get("center") or e)["lon"]) for e in a if "lat" in (e.get("center") or e)]
            print(f"  клетка {i},{j}: жилых {len(r)}, притяжения {len(a)}", flush=True)
    return np.array(res), np.array(attr)
def count_near(stops, pts, radius=400, weights=None):
    if len(pts) == 0: return np.zeros(len(stops))
    lat0 = math.radians(55.75); ky, kx = 111_320, 111_320 * math.cos(lat0)
    P = np.c_[pts[:, 0] * ky, pts[:, 1] * kx]; out = []
    for la, lo in zip(stops.lat, stops.lon):
        d2 = (P[:, 0] - la * ky) ** 2 + (P[:, 1] - lo * kx) ** 2; m = d2 <= radius ** 2
        out.append(weights[m].sum() if weights is not None else m.sum())
    return np.array(out, dtype=float)
def fetch_counts(stops, radius=400, batch=20, rounds=6):
    """Лёгкий режим: сервер Overpass считает объекты вокруг каждой остановки сам (out count), геометрия не выгружается.
    Загрузка с продолжением: уже полученные остановки хранятся в artifacts/osm_counts_partial.csv."""
    res_q = 'way(around:{r},{la},{lo})["building"~"^(apartments|residential|dormitory)$"];out count;'
    att_q = ('(nwr(around:{r},{la},{lo})["office"];nwr(around:{r},{la},{lo})["amenity"~"^(university|college|school|hospital|clinic|theatre|cinema|marketplace)$"];'
             'nwr(around:{r},{la},{lo})["shop"~"^(mall|supermarket|department_store)$"];'
             'way(around:{r},{la},{lo})["building"~"^(office|commercial|retail|university|college|school|hospital)$"];);out count;')
    part_f = ART / "osm_counts_partial.csv"
    done = pd.read_csv(part_f, dtype={"stop": str}) if part_f.exists() else pd.DataFrame(columns=["stop", "R", "A"])
    for rnd in range(rounds):
        todo = [x for x in stops.itertuples() if x.stop not in set(done.stop)]
        if not todo:
            break
        for k in range(0, len(todo), batch):
            part = todo[k:k + batch]
            q = "[out:json][timeout:170];" + "".join(res_q.format(r=radius, la=x.lat, lo=x.lon) + att_q.format(r=radius, la=x.lat, lo=x.lon) for x in part)
            try:
                el = overpass(q)
                cnt = [int(e["tags"]["total"]) for e in el if e.get("type") == "count"]
                if len(cnt) != 2 * len(part):
                    raise RuntimeError("неполный ответ")
            except Exception as exc:
                print("  пачка отложена:", exc, flush=True); time.sleep(30); continue
            done = pd.concat([done, pd.DataFrame({"stop": [x.stop for x in part], "R": cnt[0::2], "A": cnt[1::2]})], ignore_index=True)
            done.to_csv(part_f, index=False)
            print(f"  получено {len(done)} из {len(stops)}", flush=True); time.sleep(4)
    m = stops.merge(done, on="stop", how="left")
    if m.R.isna().any():
        raise RuntimeError(f"не получено {int(m.R.isna().sum())} остановок; перезапустите — продолжит с места остановки")
    return m.R.values.astype(float), m.A.values.astype(float)
if __name__ == "__main__":
    st = pd.read_csv(ART / "stops.csv", dtype={"stop": str}).drop_duplicates("stop")[["stop", "stop_name", "lat", "lon"]]
    R, A = fetch_counts(st)
    st["res_buildings_400m"] = R; st["attractors_400m"] = A
    st["res_floors_400m"] = R          # в лёгком режиме — число жилых домов (этажность не выгружается)
    st.to_csv(ART / "osm_stop_context.csv", index=False)
    print(st[["res_buildings_400m", "attractors_400m"]].describe().round(1).to_string())
    print("больше всего жилья:", st.nlargest(3, "res_buildings_400m")[["stop_name", "res_buildings_400m"]].values.tolist())
    print("больше всего притяжения:", st.nlargest(3, "attractors_400m")[["stop_name", "attractors_400m"]].values.tolist())
