import React, { useCallback, useEffect, useId, useRef, useState } from "react";

const API_BASE = ["localhost", "127.0.0.1"].includes(window.location.hostname) && window.location.port === "5173"
  ? "http://127.0.0.1:8123"
  : "/api";
const ROUTE_COLORS = {
  1: "#8b9cff",
  5: "#acb9d4",
  7: "#a6a0eb",
  11: "#66d5a7",
  12: "#f2d06c",
  17: "#dcb37c",
  25: "#8dc7ff",
  26: "#66c9cb",
  28: "#f3ad6a",
  50: "#8faeff"
};
const ALL_ROUTES = Object.keys(ROUTE_COLORS).map(Number);
const LOAD_COLORS = { low: "#4ade80", medium: "#facc15", high: "#a78bfa", unknown: "#94a3b8" };

function loadLevel(value, values) {
  const sorted = Object.values(values || {}).filter(Number.isFinite).sort((a, b) => a - b);
  if (!Number.isFinite(value) || !sorted.length) return "unknown";
  const low = sorted[Math.floor((sorted.length - 1) * 0.45)];
  const high = sorted[Math.floor((sorted.length - 1) * 0.8)];
  return value >= high ? "high" : value >= low ? "medium" : "low";
}
const SCENARIOS = [
  { id: "base", label: "База", coef: 1, tone: "stable", text: "плановый прогноз" },
  { id: "rain", label: "Непогода", coef: 0.94, tone: "soft", text: "меньше поездок" },
  { id: "event", label: "Мероприятие", coef: 1.16, tone: "hot", text: "локальный всплеск" },
  { id: "repair", label: "Сбой сети", coef: 1.28, tone: "alert", text: "стресс-нагрузка" }
];
const TIME_PRESETS = [
  { id: "all", label: "Сутки", from: 0, to: 23 },
  { id: "am", label: "Утро", from: 6, to: 10 },
  { id: "day", label: "День", from: 11, to: 16 },
  { id: "pm", label: "Вечер", from: 17, to: 21 }
];

function fmtNum(n) {
  return Math.round(n || 0).toLocaleString("ru-RU");
}

function fmtDate(s) {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
}

function fmtDateShort(s) {
  if (!s) return "—";
  const [, m, d] = s.split("-");
  return `${d}.${m}`;
}

function moscowToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
}

function monthEnd(s) {
  const d = new Date(s + "T00:00:00Z");
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).toISOString().slice(0, 10);
}

function useClock() {
  const [clock, setClock] = useState("--:--:--");
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" }));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);
  return clock;
}

function AuthOverlay({ onAuth }) {
  const [mode, setMode] = useState("login");
  const [msg, setMsg] = useState("");

  async function submit(ev) {
    ev.preventDefault();
    const form = new FormData(ev.currentTarget);
    const username = String(form.get("username") || "");
    const password = String(form.get("password") || "");
    try {
      if (mode === "register") {
        if (password !== String(form.get("password2") || "")) throw new Error("пароли не совпадают");
        const r = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password })
        });
        const d = await r.json();
        if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "ошибка регистрации");
      }
      const r = await fetch(`${API_BASE}/auth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password })
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "не удалось войти");
      localStorage.setItem("edc_token", d.access_token);
      localStorage.setItem("edc_user", username.trim().toLowerCase());
      onAuth(d.access_token, username.trim().toLowerCase());
    } catch (e) {
      setMsg(e.message);
    }
  }

  return (
    <div className="auth-overlay">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand"><img className="auth-logo" src="/mt-symbol.svg" alt="" /> МосТранспорт</div><h2>Город в движении.<br />Всё под контролем.</h2>
        <div className="sub">Рабочее место диспетчера · вход в систему</div>
        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Вход</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>Регистрация</button>
        </div>
        <label className="auth-label">Логин</label><input aria-label="Логин" name="username" autoComplete="username" placeholder="Логин (латиница, от 3 символов)" required />
        <label className="auth-label">Пароль</label><input aria-label="Пароль" name="password" type="password" autoComplete="current-password" placeholder="Пароль (от 6 символов)" required />
        {mode === "register" && <input name="password2" type="password" autoComplete="new-password" placeholder="Повторите пароль" required />}
        <button className="submit" type="submit">{mode === "register" ? "Зарегистрироваться и войти" : "Войти"}</button>
        <div className="auth-msg">{msg}</div>
      </form>
    </div>
  );
}

function NoticeDrawer({ open, notices, onClose }) {
  const dialogRef = useDialog(open, onClose);
  return (
    <>
      <div className={"drawer-backdrop " + (open ? "open" : "")} onClick={onClose} />
      <aside ref={dialogRef} className={"drawer " + (open ? "open" : "")} role="dialog" aria-modal={open || undefined} aria-hidden={!open} inert={!open} aria-label="Уведомления">
        <div className="drawer-head">
          <h3>Уведомления</h3>
          <button className="icon-btn" type="button" aria-label="Закрыть уведомления" onClick={onClose}>×</button>
        </div>
        <div className="notice-center">
          {notices.map((n, i) => (
            <div className={"notice " + (n.type || "info")} key={i}>
              <strong>{n.title}</strong>
              <p>{n.text}</p>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

export function App() {
  const [token, setToken] = useState(localStorage.getItem("edc_token") || "");
  const [user, setUser] = useState(localStorage.getItem("edc_user") || "");
  const [view, setView] = useState("overview");
  const [navExpanded, setNavExpanded] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [apiOk, setApiOk] = useState(false);
  const [horizon, setHorizon] = useState({ start: "2025-11-01", end: "2026-10-31" });
  const [dateFrom, setDateFrom] = useState("2025-11-01");
  const [dateTo, setDateTo] = useState("2025-11-01");
  const [selectedRoutes, setSelectedRoutes] = useState(ALL_ROUTES.filter((route) => route !== 5));
  const [hourFrom, setHourFrom] = useState(0);
  const [hourTo, setHourTo] = useState(23);
  const [coef, setCoef] = useState(1);
  const [lastData, setLastData] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [demoDate, setDemoDate] = useState("");
  const [nowData, setNowData] = useState(null);
  const [alertsData, setAlertsData] = useState({ alerts: [] });
  const [fleetData, setFleetData] = useState(null);
  const [planData, setPlanData] = useState(null);
  const [accuracyData, setAccuracyData] = useState(null);
  const [decisionsData, setDecisionsData] = useState(null);
  const [stopsData, setStopsData] = useState(null);
  const [mapReady, setMapReady] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("—");
  const [notices, setNotices] = useState([
    { type: "info", title: "Ожидание данных", text: "После входа система загрузит горизонт модели и построит прогноз." }
  ]);
  const [toasts, setToasts] = useState([]);

  const mapNodeRef = useRef(null);
  const mapRef = useRef(null);
  const mapLoadRef = useRef({});
  const popupRef = useRef(null);
  const routesGeoRef = useRef(null);
  const hourCanvasRef = useRef(null);
  const routeCanvasRef = useRef(null);
  const hourChartRef = useRef(null);
  const routeChartRef = useRef(null);

  const periodLabel = dateFrom === dateTo ? fmtDate(dateFrom) : `${fmtDate(dateFrom)} - ${fmtDate(dateTo)}`;
  const scenarioKind = coef === 1 ? "норма" : coef < 1 ? "снижение" : "рост";

  const toast = useCallback((title, text, type = "info") => {
    const id = crypto.randomUUID();
    setToasts((items) => [{ id, title, text, type }, ...items].slice(0, 4));
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5200);
  }, []);

  const apiFetch = useCallback(async (url, opts = {}) => {
    const headers = { ...(opts.headers || {}), ...(token ? { Authorization: "Bearer " + token } : {}) };
    const r = await fetch(url, { ...opts, headers });
    if (r.status === 401) {
      localStorage.removeItem("edc_token");
      setToken("");
      toast("Сессия завершена", "нужно войти заново", "warn");
      throw new Error("401");
    }
    return r;
  }, [token, toast]);

  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch(`${API_BASE}/health`);
        setApiOk(r.ok);
        if (!r.ok) throw new Error();
      } catch {
        setApiOk(false);
        setNotices((items) => [{ type: "danger", title: "API недоступен", text: "Прогноз и экспорт временно не обновляются." }, ...items].slice(0, 6));
      }
    };
    check();
    const timer = setInterval(check, 10000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const r = await apiFetch(`${API_BASE}/model/info`);
        const info = await r.json();
        setHorizon(info.horizon);
        setModelInfo(info);
        const today = moscowToday();
        const currentDate = info.now_mode === "demo"
          ? (info.demo_today || info.horizon.start)
          : (today < info.horizon.start ? info.horizon.start : today > info.horizon.end ? info.horizon.end : today);
        setDemoDate(currentDate);
        setDateFrom(currentDate);
        setDateTo(currentDate);
      } catch {}
    })();
  }, [token, apiFetch]);

  useEffect(() => {
    if (!hourCanvasRef.current || !routeCanvasRef.current || !window.Chart) return;
    window.Chart.defaults.color = "#a9b6d0";
    window.Chart.defaults.font.family = "-apple-system,sans-serif";
    window.Chart.defaults.font.size = 10;
    hourChartRef.current = new window.Chart(hourCanvasRef.current, {
      type: "line",
      data: { labels: [], datasets: [
        { label: "Нижняя граница", data: [], borderColor: "transparent", pointRadius: 0 },
        { label: "Коридор 80 %", data: [], borderColor: "transparent", backgroundColor: "rgba(255,255,255,.12)", pointRadius: 0, fill: "-1" },
        { label: "Прогноз", data: [], borderColor: "#ffffff", borderWidth: 2, tension: .35, pointRadius: 0 }
      ] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: "rgba(181,198,237,.09)" } }, y: { grid: { color: "rgba(181,198,237,.09)" }, beginAtZero: true } } }
    });
    routeChartRef.current = new window.Chart(routeCanvasRef.current, {
      type: "bar",
      data: { labels: [], datasets: [{ label: "Посадки", data: [], backgroundColor: [] }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: "rgba(181,198,237,.09)" }, beginAtZero: true } } }
    });
    return () => {
      hourChartRef.current?.destroy();
      routeChartRef.current?.destroy();
    };
  }, []);

  const recolorRoutes = useCallback((byRoute) => {
    const map = mapRef.current;
    if (!map?.getLayer("routes-line") || !byRoute) return;
    mapLoadRef.current = byRoute;
    const maxVal = Math.max(...Object.values(byRoute), 1);
    const colors = Object.entries(byRoute).flatMap(([route, value]) => [String(route), LOAD_COLORS[loadLevel(value, byRoute)]]);
    const widthExpr = ["interpolate", ["linear"], ["zoom"],
      9, ["match", ["get", "route"], ...Object.entries(byRoute).flatMap(([r, v]) => [String(r), 1.75 + 1.5 * (v / maxVal)]), 2],
      15, ["match", ["get", "route"], ...Object.entries(byRoute).flatMap(([r, v]) => [String(r), 4 + 3 * (v / maxVal)]), 5]
    ];
    map.setPaintProperty("routes-line", "line-width", widthExpr);
    map.setPaintProperty("routes-line", "line-color", ["match", ["get", "route"], ...colors, LOAD_COLORS.unknown]);
  }, []);

  useEffect(() => {
    if (!token || !mapNodeRef.current || mapRef.current || !window.maplibregl) return;
    const map = new window.maplibregl.Map({
      container: mapNodeRef.current,
      style: {
        version: 8,
        sources: { "osm-tiles": { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#101a32" } },
          { id: "osm", type: "raster", source: "osm-tiles", paint: { "raster-opacity": .8, "raster-saturation": -1, "raster-contrast": .1, "raster-brightness-min": .6, "raster-brightness-max": .08 } }
        ]
      },
      center: [37.62, 55.75],
      zoom: 9.5,
      attributionControl: false
    });
    mapRef.current = map;
    map.addControl(new window.maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.addControl(new window.maplibregl.NavigationControl(), "top-right");
    const resize = () => map.resize();
    window.addEventListener("resize", resize);
    const ro = new ResizeObserver(resize);
    ro.observe(mapNodeRef.current);
    let cancelled = false;
    (async () => {
      while (!cancelled && !map.isStyleLoaded()) await new Promise((r) => setTimeout(r, 100));
      if (cancelled) return;
      const resp = await apiFetch(`${API_BASE}/routes/geometry`);
      if (!resp.ok) throw new Error("Не удалось получить геометрию маршрутов");
      const routesGeo = await resp.json();
      if (cancelled) return;
      routesGeoRef.current = routesGeo;
      map.addSource("routes", { type: "geojson", data: routesGeo });
      const colorExpr = LOAD_COLORS.unknown;
      map.addLayer({ id: "routes-casing", type: "line", source: "routes", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 9, 4.5, 12, 7, 15, 10.5], "line-color": "#10203a", "line-opacity": .92 } });
      map.addLayer({ id: "routes-line", type: "line", source: "routes", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 12, 4, 15, 6.5], "line-color": colorExpr } });
      // Resolve overlapping features once: the stop takes precedence over its route.
      map.on("click", (event) => {
        const layers = ["stops-load", "routes-line"].filter(id => map.getLayer(id));
        const features = map.queryRenderedFeatures(event.point, { layers });
        const feature = features.find(item => item.layer.id === "stops-load") || features[0];
        popupRef.current?.remove();
        if (!feature) return;
        popupRef.current = new window.maplibregl.Popup({ maxWidth: "320px", className: "transport-popup", offset: 16, closeOnClick: false })
          .setLngLat(event.lngLat).setDOMContent(mapPopupContent(feature, mapLoadRef.current)).addTo(map);
        popupRef.current.getElement().querySelector(".maplibregl-popup-close-button")?.setAttribute("aria-label", "Закрыть карточку карты");
      });
      map.on("mousemove", (event) => {
        const layers = ["stops-load", "routes-line"].filter(id => map.getLayer(id));
        map.getCanvas().style.cursor = map.queryRenderedFeatures(event.point, { layers }).length ? "pointer" : "";
      });
      setMapReady(true);
    })().catch(e => { if (!cancelled) toast("Карта не обновилась", e.message, "warn"); });
    return () => {
      cancelled = true;
      popupRef.current?.remove();
      popupRef.current = null;
      window.removeEventListener("resize", resize);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, [token, apiFetch, toast]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const spanDays = (new Date(dateTo) - new Date(dateFrom)) / 86400000;
    const granularity = spanDays > 3 ? "day" : "hour";
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, granularity, coefficient: coef, hour_from: hourFrom, hour_to: hourTo });
    for (const r of selectedRoutes) params.append("route", r);
    try {
      const resp = await apiFetch(`${API_BASE}/forecast?${params}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "API вернул ошибку при расчёте");
      setLastData(data);
      setUpdatedAt(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }));
      const byRoute = {};
      for (const row of data.rows) byRoute[row.route] = (byRoute[row.route] || 0) + row.prediction;
      const rSorted = Object.entries(byRoute).sort((a, b) => b[1] - a[1]);
      if (routeChartRef.current) {
      routeChartRef.current.data.labels = rSorted.map(([r]) => r);
      routeChartRef.current.data.datasets[0].data = rSorted.map(([, v]) => v);
      routeChartRef.current.data.datasets[0].backgroundColor = rSorted.map(([r]) => ROUTE_COLORS[r] || "#888");
      routeChartRef.current.update();
      }
      let peak = "—";
      if (granularity === "hour") {
        const byHour = {}, byHourLo = {}, byHourHi = {};
        for (const row of data.rows) {
          byHour[row.hour] = (byHour[row.hour] || 0) + row.prediction;
          byHourLo[row.hour] = (byHourLo[row.hour] || 0) + row.lo;
          byHourHi[row.hour] = (byHourHi[row.hour] || 0) + row.hi;
        }
        const hours = Array.from({ length: 24 }, (_, i) => i);
        if (hourChartRef.current) hourChartRef.current.data.labels = hours.map((h) => h + ":00");
        if (hourChartRef.current) hourChartRef.current.data.datasets[0].data = hours.map((h) => byHourLo[h] || 0);
        if (hourChartRef.current) hourChartRef.current.data.datasets[1].data = hours.map((h) => byHourHi[h] || 0);
        if (hourChartRef.current) hourChartRef.current.data.datasets[2].data = hours.map((h) => byHour[h] || 0);
        peak = hours.reduce((a, b) => (byHour[a] || 0) > (byHour[b] || 0) ? a : b) + ":00";
      } else {
        const byDate = {}, byDateLo = {}, byDateHi = {};
        for (const row of data.rows) {
          byDate[row.date] = (byDate[row.date] || 0) + row.prediction;
          byDateLo[row.date] = (byDateLo[row.date] || 0) + row.lo;
          byDateHi[row.date] = (byDateHi[row.date] || 0) + row.hi;
        }
        const dates = Object.keys(byDate).sort();
        if (hourChartRef.current) hourChartRef.current.data.labels = dates.map(fmtDateShort);
        if (hourChartRef.current) hourChartRef.current.data.datasets[0].data = dates.map((d) => byDateLo[d]);
        if (hourChartRef.current) hourChartRef.current.data.datasets[1].data = dates.map((d) => byDateHi[d]);
        if (hourChartRef.current) hourChartRef.current.data.datasets[2].data = dates.map((d) => byDate[d]);
        const peakDate = dates.reduce((a, b) => byDate[a] > byDate[b] ? a : b, dates[0]);
        peak = peakDate ? fmtDateShort(peakDate) : "—";
      }
      hourChartRef.current?.update();
      recolorRoutes(byRoute);
      const topRoute = rSorted[0];
      const routeLabel = selectedRoutes.length === ALL_ROUTES.length ? "вся сеть" : `${selectedRoutes.length} маршр.`;
      setNotices([
        { type: "ok", title: "Прогноз обновлён", text: `${fmtNum(data.total_prediction)} посадок за выбранный период.` },
        { type: "info", title: "Пиковая нагрузка", text: `Пик текущего периода: ${peak}.` },
        { type: "info", title: "Фильтр сети", text: `${routeLabel}, часы ${String(hourFrom).padStart(2, "0")}:00-${String(hourTo).padStart(2, "0")}:00.` },
        { type: "info", title: "Распределение по сети", text: topRoute ? `Максимум у маршрута ${topRoute[0]}: ${fmtNum(topRoute[1])}.` : "Данных по маршрутам нет." },
        ...(coef !== 1 ? [{ type: "info", title: "Сценарная поправка активна", text: `Значения пересчитаны с коэффициентом ×${coef.toFixed(2)}.` }] : [])
      ]);
    } catch (e) {
      setNotices((items) => [{ type: "danger", title: "Прогноз не обновился", text: e.message || "Не удалось получить данные с API." }, ...items].slice(0, 6));
    }
  }, [token, dateFrom, dateTo, selectedRoutes, hourFrom, hourTo, coef, apiFetch, recolorRoutes]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!token || !["overview", "now", "fleet", "plan", "accuracy", "decisions", "map"].includes(view)) return;
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, coefficient: coef, hour_from: hourFrom, hour_to: hourTo });
    selectedRoutes.forEach((route) => params.append("route", route));
    const load = async (path, setter) => {
      try { const r = await apiFetch(`${API_BASE}${path}`); const d = await r.json(); if (!r.ok) throw new Error(d.detail); setter(d); }
      catch (e) { toast("Не удалось загрузить раздел", e.message || "Повторите запрос", "warn"); }
    };
    if (view === "now" || view === "overview") {
      const q = new URLSearchParams({ hour: String(new Date().getHours()), date: demoDate || horizon.start, coefficient: coef });
      selectedRoutes.forEach((route) => q.append("route", route));
      load(`/now?${q}`, setNowData); load(`/alerts?hour=${new Date().getHours()}&date=${demoDate || horizon.start}&coefficient=${coef}`, setAlertsData);
    }
    if (view === "fleet") load(`/fleet?${params}`, setFleetData);
    if (view === "plan") { const end = new Date(Math.min(new Date(dateFrom).getTime() + 6 * 86400000, new Date(horizon.end).getTime())).toISOString().slice(0, 10); load(`/plan?date_from=${dateFrom}&date_to=${end}&coefficient=${coef}${selectedRoutes.map((r) => `&route=${r}`).join("")}`, setPlanData); }
    if (view === "accuracy") load("/monitor/accuracy", setAccuracyData);
    if (view === "decisions") load("/decisions/report", setDecisionsData);
    if (view === "map") load(`/forecast/stops?${params}`, setStopsData);
  }, [token, view, dateFrom, dateTo, hourFrom, hourTo, coef, selectedRoutes, demoDate, horizon.start, horizon.end, apiFetch, toast]);

  useEffect(() => {
    popupRef.current?.remove();
    if (view === "map") setTimeout(() => mapRef.current?.resize(), 80);
  }, [view]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !stopsData?.rows || view !== "map" || !map.getLayer("routes-casing")) return;
    popupRef.current?.remove();
    const geojson = { type: "FeatureCollection", features: stopsData.rows.map((s) => ({ type: "Feature", properties: { name: s.stop_name, prediction: s.prediction, routes: s.routes.join(", ") }, geometry: { type: "Point", coordinates: [s.lon, s.lat] } })) };
    if (map.getSource("stops-load")) map.getSource("stops-load").setData(geojson);
    else {
      map.addSource("stops-load", { type: "geojson", data: geojson });
      map.addLayer({ id: "stops-load", type: "circle", source: "stops-load", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2, 13, 3, 16, 4],
        "circle-color": "#123b70",
        "circle-opacity": 1,
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 9, .75, 16, 1.25],
        "circle-stroke-color": "#b8d4ff"
      } });

    }
  }, [stopsData, view, mapReady]);

  async function doExport(fmt) {
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, fmt, coefficient: coef, hour_from: hourFrom, hour_to: hourTo });
    for (const r of selectedRoutes) params.append("route", r);
    try {
      const r = await apiFetch(`${API_BASE}/forecast/export?${params}`);
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.detail || "ошибка выгрузки");
      }
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `forecast_${dateFrom}_${dateTo}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Файл подготовлен", a.download, "ok");
    } catch (e) {
      toast("Экспорт не выполнен", e.message, "danger");
    }
  }

  async function decide(alert, decision) {
    const r = await apiFetch(`${API_BASE}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ alert_id: alert.id, alert_date: alertsData.today, route: alert.route || null, decision }) });
    if (!r.ok) throw new Error((await r.json()).detail);
    toast("Решение записано", decision === "accepted" ? "Рекомендация принята" : "Решение сохранено", "ok");
    setView("decisions");
  }

  const setPreset = (preset) => {
    if (preset === "day") setDateTo(horizon.start);
    if (preset === "month") setDateTo(monthEnd(horizon.start));
    if (preset === "year") setDateTo(horizon.end);
    setDateFrom(horizon.start);
  };

  const total = lastData ? fmtNum(lastData.total_prediction) : "—";
  const peak = notices.find((n) => n.title === "Пиковая нагрузка")?.text.replace("Пик текущего периода: ", "").replace(".", "") || "—";
  const applyScenario = useCallback((nextCoef, label = "Ручной сценарий") => {
    setCoef(nextCoef);
    toast("Сценарий применён", `${label}: коэффициент ×${nextCoef.toFixed(2)}`, "info");
  }, [toast]);
  const toggleRoute = useCallback((route) => {
    setSelectedRoutes((routes) => {
      if (routes.includes(route)) return routes.length === 1 ? routes : routes.filter((item) => item !== route);
      return [...routes, route].sort((a, b) => a - b);
    });
  }, []);
  const setAllRoutes = useCallback(() => setSelectedRoutes(ALL_ROUTES), []);
  const setCoreRoutes = useCallback(() => setSelectedRoutes(ALL_ROUTES.filter((route) => route !== 5)), []);
  const setTimePreset = useCallback((preset) => {
    setHourFrom(preset.from);
    setHourTo(preset.to);
  }, []);
  const applyFilters = useCallback((next) => {
    setDateFrom(next.dateFrom);
    setDateTo(next.dateTo);
    setSelectedRoutes(next.selectedRoutes);
    setHourFrom(next.hourFrom);
    setHourTo(next.hourTo);
    setCoef(next.coef);
    toast("Параметры применены", "Прогноз пересчитывается по выбранным условиям.", "info");
  }, [toast]);

  return (
    <>
      {!token && <AuthOverlay onAuth={(nextToken, nextUser) => { setToken(nextToken); setUser(nextUser); toast("Вход выполнен", "Рабочее место загружает прогноз и геометрию маршрутов.", "ok"); }} />}
      <div className="app-shell" inert={!token}>
        <div className={"workspace " + (navExpanded ? "nav-expanded" : "")}>
          <nav className={"rail " + (navExpanded ? "expanded" : "collapsed")}>
            <div className="rail-head">
              <div className="rail-logo" title="МосТранспорт">
                <img className="rail-logo-mark" src="/mt-symbol.svg" alt="Московский транспорт" /><b>МосТранспорт<small>Диспетчерская платформа</small></b>
              </div>
              <button className="rail-back" type="button" aria-label={navExpanded ? "Скрыть названия разделов" : "Показать названия разделов"} onClick={() => setNavExpanded((v) => !v)}>
                <SidebarToggleIcon expanded={navExpanded} />
              </button>
            </div>
            <div className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
            {[
              ["overview", <OverviewIcon key="overview-icon" />, "Обзор"],
              ["now", <UiIcon name="activity" />, "Оперативная ситуация"],
              ["map", <MapIcon key="map-icon" />, "Карта и остановки"],
              ["fleet", <UiIcon name="bus" />, "Загрузка вагонов"],
              ["plan", <UiIcon name="calendar" />, "План выпуска"],
              ["accuracy", <UiIcon name="chart" />, "Качество прогноза"],
              ["decisions", <UiIcon name="file" />, "Журнал решений"]
            ].map(([id, icon, label]) => (
              <button key={id} className={"nav-btn " + (view === id ? "active" : "")} type="button" onClick={() => setView(id)} aria-label={label} title={label}><span className="nav-ico">{icon}</span><span>{label}</span></button>
            ))}
            <div className="rail-account">
              <div className="account-btn" title={user || "Диспетчер"}>
                <span>{(user || "ЛК").slice(0, 2).toUpperCase()}</span>
                <b>{user || "Диспетчер"}<small>Рабочее место оператора</small></b>
              </div>
              {token && (
                <button className="logout-btn" type="button" title="Выйти" aria-label="Выйти" onClick={() => { localStorage.removeItem("edc_token"); setToken(""); }}>
                  <LogoutIcon />
                  <span>Выйти</span>
                </button>
              )}
            </div>
          </nav>

          <main className="main-stage">
            <header className="topbar"><div className="breadcrumb">Рабочее пространство <span>/</span> <b>{({ overview: "Обзор", now: "Оперативная ситуация", map: "Карта сети", fleet: "Загрузка вагонов", plan: "План выпуска", accuracy: "Качество прогноза", decisions: "Журнал решений" })[view]}</b></div><div className="topbar-right"><span>Москва</span><DashboardClock /><span className="timezone">МСК</span></div></header>
            <div className="command-strip">
              <div className="page-title">
                <h2>{({ overview: "Обзор движения", now: "Оперативная ситуация", map: "Карта сети и остановки", fleet: "Загрузка вагонов", plan: "План выпуска", accuracy: "Качество прогноза", decisions: "Журнал решений" })[view]}</h2>
                <p>{({ overview: "Вся транспортная сеть. Данные для решений на опережение.", now: "Оперативная ситуация, ближайшие часы и предупреждения.", map: "Оценочная загрузка остановок за выбранный период.", fleet: "Фактический типовой выпуск и рекомендуемое число вагонов.", plan: "Операционный план на семь ближайших дней.", accuracy: "Сопоставление факта и прогноза после поступления данных.", decisions: "Принятые, отклонённые и отложенные рекомендации." })[view]}</p>
              </div>
              <div className="status-strip">
                {modelInfo && <div className="status-item" title={modelInfo.now_mode === "demo" ? "Дата виртуальная, время — браузера" : "Текущее время Москвы"}><span className="dot" style={{ background: modelInfo.now_mode === "demo" ? "#facc15" : "#1aa36f" }} />{modelInfo.now_mode === "demo" ? `Демо: ${fmtDate(demoDate)}` : "Реальное время"}</div>}
                {modelInfo?.data_until && <div className="status-item">Данные до {fmtDate(modelInfo.data_until)}</div>}
                <button className="icon-btn" type="button" onClick={() => setDrawerOpen(true)} aria-label="Уведомления"><BellIcon /><span className="count">{notices.length}</span></button>
              </div>
            </div>

            <section className="view" style={{ display: view === "overview" ? "" : "none" }}>
                <FilterBar dateFrom={dateFrom} dateTo={dateTo} coef={coef} selectedRoutes={selectedRoutes} hourFrom={hourFrom} hourTo={hourTo} onOpen={() => setFiltersOpen(true)} />
                <div className="section-kicker"><span><i className="dot online" /> ОБЗОР СЕТИ</span><span>Обновлено {updatedAt}</span></div>
                <div className="metric-grid">
                  <Metric label="Прогноз пассажиропотока" value={total} text="Посадок за выбранный период" icon="bus" />
                  <Metric label="Маршрутов с риском" value={nowData?.network?.routes_at_risk_now?.length ?? "—"} text="Риск перегрузки в текущем часу" icon="activity" tone="risk" />
                  <Metric label="Пиковая нагрузка" value={peak} text="Самый нагруженный час / день" icon="clock" />
                  <Metric label="Активные маршруты" value={selectedRoutes.length} text={`Из ${ALL_ROUTES.length} маршрутов сети`} icon="route" />
                </div>
                <div className="analytics-grid">
                  <div className="hero-metric trend-card"><div className="card-head"><div><h3>Динамика пассажиропотока</h3><p>Прогноз посадок за выбранный период</p></div><ForecastExport onExport={doExport} disabled={!lastData} /></div><div className="chart-box"><canvas ref={hourCanvasRef} aria-label="Динамика прогнозируемого пассажиропотока" role="img" /></div><div className="chart-footer"><span><i className="legend-dot" /> Прогноз</span><span><i className="legend-dot pale" /> Интервал неопределённости</span></div></div>
                  <div className="hero-metric"><div className="card-head"><div><h3>Нагрузка по маршрутам</h3><p>Распределение прогнозируемых посадок</p></div><UiIcon name="chart" /></div><div className="chart-box"><canvas ref={routeCanvasRef} aria-label="Посадки по маршрутам" role="img" /></div><div className="chart-footer">Сценарий: {SCENARIOS.find(x => x.coef === coef)?.label || "Ручной"} · ×{coef.toFixed(2)}</div></div>
                </div>
                <div className="operations-grid">
                  <div className="data-card route-overview"><div className="card-head"><div><h3>Состояние маршрутов <span className="number-badge">{nowData?.routes?.length ?? "—"}</span></h3><p>{nowData ? `${fmtDate(nowData.today)}, ${String(nowData.hour).padStart(2, "0")}:00` : "Текущий час"} · прогноз и рекомендуемый выпуск</p></div><button className="text-button" onClick={() => setView("map")}>На карте <span>↗</span></button></div>
                    {nowData ? <Table name="Состояние маршрутов" exportName="routes" heads={["Маршрут", "Посадки / час", "Выпуск вагонов", "Статус"]} rows={nowData.routes.slice().sort((a, b) => Number(nowData.network.routes_at_risk_now.includes(b.route)) - Number(nowData.network.routes_at_risk_now.includes(a.route))).map(x => [<span className="route-number"><UiIcon name="bus" />{x.route}</span>, fmtNum(x.now?.prediction), <span>{x.now?.veh_typ ?? "—"}<span className="muted-arrow"> → </span><b>{x.now?.veh_recommended ?? "—"}</b></span>, <Status value={x.now?.status} />])} /> : <Empty text={apiOk ? "Загружаем состояние маршрутов…" : "Нет подключения. Данные появятся после восстановления связи."} />}
                  </div>
                  <div className="data-card attention-card"><div className="card-head"><div><h3>Требуют внимания</h3><p>Предупреждения системы</p></div><span className="number-badge">{alertsData.alerts.length}</span></div><div className="attention-list">{alertsData.alerts.length ? alertsData.alerts.slice(0, 3).map(a => <div className="attention-item" key={a.id}><span className="attention-icon"><UiIcon name="activity" /></span><div><b>{a.route ? `Маршрут ${a.route}` : "Транспортная сеть"}</b><p>{a.text}</p><button className="text-button" onClick={() => setView("now")}>Посмотреть рекомендацию →</button></div></div>) : <div className="calm-state"><span>✓</span><b>{nowData ? "Нет активных предупреждений" : "Ожидаем данные"}</b><p>{nowData ? "Новые события появятся здесь" : "Предупреждения появятся после загрузки"}</p></div>}</div><button className="attention-footer" onClick={() => setView("now")}>Оперативная ситуация <span>→</span></button></div>
                </div>
                <div className="workspace-note"><span>МосТранспорт · Аналитика движения</span><span>{modelInfo?.data_until ? `История до ${fmtDate(modelInfo.data_until)} · ` : ""}Данные о пассажиропотоке и загрузке</span></div>
            </section>

            <section className="view" style={{ display: view === "map" ? "" : "none" }}>
                <div className="map-layout">
                  <FilterBar dateFrom={dateFrom} dateTo={dateTo} coef={coef} selectedRoutes={selectedRoutes} hourFrom={hourFrom} hourTo={hourTo} onOpen={() => setFiltersOpen(true)} />
                  <MapCard mapNodeRef={mapNodeRef} periodLabel={periodLabel} stopsData={stopsData} />
                </div>
            </section>

            <section className="view" style={{ display: view === "now" ? "" : "none" }}>
              <NowView data={nowData} alerts={alertsData.alerts} onDecide={(alert, decision) => decide(alert, decision).catch(e => toast("Решение не сохранено", e.message, "danger"))} />
            </section>
            <section className="view" style={{ display: view === "fleet" ? "" : "none" }}><FleetView data={fleetData} /></section>
            <section className="view" style={{ display: view === "plan" ? "" : "none" }}><PlanView data={planData} /></section>
            <section className="view" style={{ display: view === "accuracy" ? "" : "none" }}><AccuracyView data={accuracyData} /></section>
            <section className="view" style={{ display: view === "decisions" ? "" : "none" }}><DecisionsView data={decisionsData} /></section>

          </main>
        </div>
      </div>
      <NoticeDrawer open={drawerOpen} notices={notices} onClose={() => setDrawerOpen(false)} />
      <FilterModal
        open={filtersOpen}
        horizon={horizon}
        dateFrom={dateFrom}
        dateTo={dateTo}
        coef={coef}
        selectedRoutes={selectedRoutes}
        hourFrom={hourFrom}
        hourTo={hourTo}
        total={total}
        onClose={() => setFiltersOpen(false)}
        onApply={applyFilters}
      />
      <div className="toast-stack">{toasts.map((t) => <div className={"toast " + t.type} key={t.id}><b>{t.title}</b><span>{t.text}</span></div>)}</div>
    </>
  );
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 21h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function OverviewIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="2" />
      <rect x="13" y="4" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="2" />
      <rect x="4" y="13" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="2" />
      <rect x="13" y="13" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function MapIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M9 18 3 20V6l6-2 6 2 6-2v14l-6 2-6-2Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 4v14M15 6v14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function SidebarToggleIcon({ expanded }) {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M10 7V5.8A1.8 1.8 0 0 1 11.8 4H18a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6.2a1.8 1.8 0 0 1-1.8-1.8V17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M14 12H4m0 0 3.5-3.5M4 12l3.5 3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Metric({ label, value, text, wide, icon = "chart", tone = "" }) {
  const longText = typeof text === "string" && text.length > 120;
  return <div className={"hero-metric metric " + tone + (wide ? " wide" : "")}><div className="metric-label"><small>{label}</small><UiIcon name={icon} /></div><strong>{value}</strong>{longText ? <InfoTooltip text={text} /> : <p>{text}</p>}</div>;
}

function InfoTooltip({ text }) {
  const id = useId();
  return <div className="info-tooltip">
    <button type="button" aria-describedby={id}><span aria-hidden="true">i</span> Методика расчёта</button>
    <div id={id} className="info-tooltip-content" role="tooltip">{text}</div>
  </div>;
}

function ScenarioControl({ coef, onApply, mode = "panel", total, scenarioKind }) {
  const active = SCENARIOS.find((item) => Math.abs(item.coef - coef) < 0.005);
  const [draft, setDraft] = useState(coef);

  useEffect(() => {
    setDraft(coef);
  }, [coef]);

  return (
    <div className={"scenario-card " + (mode === "overview" ? "hero-metric wide scenario-hero" : "")}>
      <div className="scenario-head">
        <div>
          <small>Сценарий</small>
          <h3>{active ? active.label : "Ручная поправка"}</h3>
        </div>
        <div className="scenario-badge">×{coef.toFixed(2)}</div>
      </div>
      <div className="scenario-tabs">
        {SCENARIOS.map((item) => (
          <button
            className={`${Math.abs(item.coef - coef) < 0.005 ? "active" : ""} ${item.tone}`}
            key={item.id}
            type="button"
            onClick={() => onApply(item.coef, item.label)}
          >
            <b>{item.label}</b>
            <span>{item.text}</span>
          </button>
        ))}
      </div>
      <div className="scenario-range">
        <div className="range-scale"><span>−40%</span><span>норма</span><span>+40%</span></div>
        <input className="range" type="range" min="0.6" max="1.4" step="0.01" value={draft} onChange={(e) => setDraft(parseFloat(e.target.value))} onMouseUp={() => onApply(draft)} onTouchEnd={() => onApply(draft)} />
      </div>
      <div className="scenario-values">
        <div><span>Коэффициент</span><b>×{draft.toFixed(2)}</b></div>
        <div><span>Режим</span><b>{draft === 1 ? "норма" : draft < 1 ? "снижение" : "рост"}</b></div>
      </div>
      {mode === "overview" && (
        <p className="scenario-note">Итог по текущему периоду: <b>{total}</b>. {coef === 1 ? "Поправка не применяется." : `Активна поправка: ${scenarioKind}.`}</p>
      )}
    </div>
  );
}

function FilterModal({ open, horizon, dateFrom, dateTo, coef, selectedRoutes, hourFrom, hourTo, total, onClose, onApply }) {
  const dialogRef = useDialog(open, onClose);
  const [draft, setDraft] = useState({ dateFrom, dateTo, selectedRoutes, hourFrom, hourTo, coef });

  useEffect(() => {
    if (open) setDraft({ dateFrom, dateTo, selectedRoutes, hourFrom, hourTo, coef });
  }, [open, dateFrom, dateTo, selectedRoutes, hourFrom, hourTo, coef]);

  if (!open) return null;

  const activeScenario = SCENARIOS.find((item) => Math.abs(item.coef - draft.coef) < 0.005);
  const activeTimePreset = TIME_PRESETS.find((item) => item.from === draft.hourFrom && item.to === draft.hourTo)?.id;
  const draftKind = draft.coef === 1 ? "норма" : draft.coef < 1 ? "снижение" : "рост";
  const routeSummary = draft.selectedRoutes.length === ALL_ROUTES.length ? "вся сеть" : `${draft.selectedRoutes.length} из ${ALL_ROUTES.length}`;

  const patchDraft = (next) => setDraft((current) => ({ ...current, ...next }));
  const setPreset = (preset) => {
    if (preset === "day") patchDraft({ dateFrom: horizon.start, dateTo: horizon.start });
    if (preset === "month") patchDraft({ dateFrom: horizon.start, dateTo: monthEnd(horizon.start) });
    if (preset === "year") patchDraft({ dateFrom: horizon.start, dateTo: horizon.end });
  };
  const toggleRoute = (route) => {
    patchDraft({
      selectedRoutes: draft.selectedRoutes.includes(route)
        ? (draft.selectedRoutes.length === 1 ? draft.selectedRoutes : draft.selectedRoutes.filter((item) => item !== route))
        : [...draft.selectedRoutes, route].sort((a, b) => a - b)
    });
  };
  const apply = () => {
    if (!draft.dateFrom || !draft.dateTo || draft.dateFrom > draft.dateTo || draft.dateFrom < horizon.start || draft.dateTo > horizon.end) return;
    onApply(draft);
    onClose();
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section ref={dialogRef} className="filter-modal" role="dialog" aria-modal="true" aria-label="Параметры прогноза">
        <div className="modal-head">
          <div>
            <small>Параметры прогноза</small>
            <h3>{draft.dateFrom === draft.dateTo ? fmtDate(draft.dateFrom) : `${fmtDate(draft.dateFrom)} - ${fmtDate(draft.dateTo)}`}</h3>
          </div>
          <button className="modal-close" type="button" aria-label="Закрыть" onClick={onClose}>×</button>
        </div>

        <div className="modal-grid">
          <div className="filter-card filter-period">
            <div className="filter-title"><span>Горизонт</span><b>{fmtDate(draft.dateFrom)} - {fmtDate(draft.dateTo)}</b></div>
            <div className="filter-presets">
              <button type="button" onClick={() => setPreset("day")}>День</button>
              <button type="button" onClick={() => setPreset("month")}>Месяц</button>
              <button type="button" onClick={() => setPreset("year")}>Год</button>
            </div>
            <div className="filter-dates">
              <label><span>С</span><input aria-label="Дата начала" type="date" value={draft.dateFrom} min={horizon.start} max={horizon.end} onChange={(e) => patchDraft({ dateFrom: e.target.value })} /></label>
              <label><span>По</span><input aria-label="Дата окончания" type="date" value={draft.dateTo} min={horizon.start} max={horizon.end} onChange={(e) => patchDraft({ dateTo: e.target.value })} /></label>
            </div>
          </div>

          <div className="filter-card route-filter">
            <div className="filter-title compact"><span>Маршруты</span><b>{routeSummary}</b></div>
            <div className="route-actions">
              <button type="button" onClick={() => patchDraft({ selectedRoutes: ALL_ROUTES.filter((route) => route !== 5) })}>Рабочий набор</button>
              <button type="button" onClick={() => patchDraft({ selectedRoutes: ALL_ROUTES })}>Все</button>
            </div>
            <div className="route-chip-grid">
              {ALL_ROUTES.map((route) => (
                <button key={route} className={draft.selectedRoutes.includes(route) ? "active" : ""} type="button" onClick={() => toggleRoute(route)} style={{ "--route-color": ROUTE_COLORS[route] }}>
                  {route}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-card time-filter">
            <div className="filter-title compact"><span>Часы</span><b>{String(draft.hourFrom).padStart(2, "0")}:00-{String(draft.hourTo).padStart(2, "0")}:00</b></div>
            <div className="time-presets">
              {TIME_PRESETS.map((item) => (
                <button key={item.id} className={activeTimePreset === item.id ? "active" : ""} type="button" onClick={() => patchDraft({ hourFrom: item.from, hourTo: item.to })}>{item.label}</button>
              ))}
            </div>
            <div className="time-sliders">
              <label><span>с {draft.hourFrom}:00</span><input className="range" type="range" min="0" max="23" step="1" value={draft.hourFrom} onChange={(e) => patchDraft({ hourFrom: Math.min(Number(e.target.value), draft.hourTo) })} /></label>
              <label><span>до {draft.hourTo}:00</span><input className="range" type="range" min="0" max="23" step="1" value={draft.hourTo} onChange={(e) => patchDraft({ hourTo: Math.max(Number(e.target.value), draft.hourFrom) })} /></label>
            </div>
          </div>
        </div>

        <div className="scenario-section">
          <div className="filter-title compact"><span>Сценарии</span><b>{activeScenario ? activeScenario.label : "ручная поправка"}</b></div>
          <div className="scenario-tabs modal-tabs">
            {SCENARIOS.map((item) => (
              <button className={`${Math.abs(item.coef - draft.coef) < 0.005 ? "active" : ""} ${item.tone}`} key={item.id} type="button" onClick={() => patchDraft({ coef: item.coef })}>
                <b>{item.label}</b>
                <span>{item.text}</span>
              </button>
            ))}
          </div>
          <div className="scenario-range modal-range">
            <div className="range-scale"><span>-40%</span><span>норма</span><span>+40%</span></div>
            <input className="range" type="range" min="0.6" max="1.4" step="0.01" value={draft.coef} onChange={(e) => patchDraft({ coef: parseFloat(e.target.value) })} />
          </div>
        </div>

        <div className="modal-scenario-summary">
          <div><span>Коэффициент</span><b>×{draft.coef.toFixed(2)}</b></div>
          <div><span>Режим</span><b>{draftKind}</b></div>
          <div><span>Маршруты</span><b>{routeSummary}</b></div>
          <div><span>Текущий итог</span><b>{total}</b></div>
        </div>

        <div className="modal-actions">
          <button className="secondary" type="button" onClick={onClose}>Закрыть</button>
          <button className="primary" type="button" disabled={!draft.dateFrom || !draft.dateTo || draft.dateFrom > draft.dateTo || draft.dateFrom < horizon.start || draft.dateTo > horizon.end} onClick={apply}>Применить</button>
        </div>
      </section>
    </div>
  );
}

function FilterBar({ dateFrom, dateTo, coef, selectedRoutes, hourFrom, hourTo, onOpen }) {
  const activeScenario = SCENARIOS.find((item) => Math.abs(item.coef - coef) < 0.005);
  const routeSummary = selectedRoutes.length === ALL_ROUTES.length ? "вся сеть" : `${selectedRoutes.length} маршрутов`;
  const period = dateFrom === dateTo ? fmtDate(dateFrom) : `${fmtDate(dateFrom)} - ${fmtDate(dateTo)}`;

  return (
    <section className="filter-bar compact">
      <div className="factor-panel">
        <div className="factor-title">
          <span>Период прогноза</span>
          <b>{period}</b>
        </div>
        <div className="factor-list">
          <div className="factor-chip"><span>Маршруты</span><b>{routeSummary}</b></div>
          <div className="factor-chip"><span>Часы</span><b>{String(hourFrom).padStart(2, "0")}:00-{String(hourTo).padStart(2, "0")}:00</b></div>
          <div className="factor-chip"><span>Поправка</span><b>×{coef.toFixed(2)}</b></div>
        </div>
      </div>
      <button className="scenario-launch" type="button" onClick={onOpen}>
        <UiIcon name="filter" /> Параметры
      </button>
    </section>
  );
}

function MapCard({ mapNodeRef, periodLabel, stopsData }) {
  return (
    <div className="map-canvas-card">
      <div id="map" ref={mapNodeRef} />
      <div className="map-title-bar"><div className="badge">Москва · трамвайная сеть · <b>{periodLabel}</b></div></div>
      <div className="map-legend">
        <div className="legend-title">Загрузка маршрутов</div>
        <div className="lg-row"><span className="lg-line low" />низкая</div>
        <div className="lg-row"><span className="lg-line medium" />средняя</div>
        <div className="lg-row"><span className="lg-line high" />высокая</div>
        <div className="lg-row stops"><span className="lg-stop" />остановка</div>
        <div className="legend-note">Цвет рассчитан по прогнозу за период</div>
      </div>
      <div className="stops-summary"><b>Остановки</b><span>{stopsData ? `${stopsData.count} · ${fmtNum(stopsData.total_prediction)} посадок` : "загрузка…"}</span><small>{stopsData?.note}</small></div>
    </div>
  );
}

function Status({ value }) { return <span className={`status-tag ${value?.includes("риск") ? "danger" : value === "повышенная" ? "warn" : "ok"}`}>{value || "—"}</span>; }
function Empty({ text = "Данные загружаются или пока отсутствуют." }) { return <div className="empty-state">{text}</div>; }
function NowView({ data, alerts, onDecide }) {
  const [tab, setTab] = useState("hours");
  if (!data) return <Empty />;
  return <>
    <div className="view-subtabs" role="tablist" aria-label="Оперативная ситуация">
      <button type="button" role="tab" aria-selected={tab === "hours"} className={tab === "hours" ? "active" : ""} onClick={() => setTab("hours")}>Ближайшие часы</button>
      <button type="button" role="tab" aria-selected={tab === "recommendations"} className={tab === "recommendations" ? "active" : ""} onClick={() => setTab("recommendations")}>Рекомендации{alerts?.length ? <span>{alerts.length}</span> : null}</button>
    </div>
    {tab === "hours" ? <div className="ops-grid">
      <Metric label="В текущем часу" value={fmtNum(data.network.now)} text={`Коридор 80 %: ${fmtNum(data.network.now_lo)}–${fmtNum(data.network.now_hi)}.`} />
      <Metric label="Ожидается за день" value={fmtNum(data.network.day_total)} text={`Уже прошло: ${fmtNum(data.network.day_passed)}.`} />
      <Metric label="Маршрутов с риском" value={data.network.routes_at_risk_now.length} text="Нужно проверить выпуск в текущем часу." />
      <div className="data-card wide"><h3>Ближайшие часы по маршрутам</h3><Table name="Оперативная ситуация" exportName="current_routes" heads={["Маршрут", "Сейчас", "Следующие 3 ч.", "Выпуск", "Статус"]} rows={data.routes.map((x) => [x.route, fmtNum(x.now?.prediction), x.next.map((n) => `${n.hour}:00 ${fmtNum(n.prediction)}`).join(" · "), `${x.now?.veh_typ || "—"} → ${x.now?.veh_recommended || "—"}`, <Status value={x.now?.status} />])} /></div>
    </div> : <div className="data-card recommendations-panel"><div className="card-head"><div><h3>Рекомендации</h3><p>{fmtDate(data.today)}, {String(data.hour).padStart(2, "0")}:00 · {data.day_kind || "обычный день"}</p></div><span className="number-badge">{alerts?.length || 0}</span></div>{alerts?.length ? alerts.map((a) => <div className={`alert-row ${a.level}`} key={a.id}><div><b>{a.level} · {a.type}</b><p>{a.text}</p></div><div className="alert-actions"><button className="accept" onClick={() => onDecide(a, "accepted")}>Принять</button><button className="postpone" onClick={() => onDecide(a, "postponed")}>Позже</button><button className="reject" onClick={() => onDecide(a, "rejected")}>Отклонить</button></div></div>) : <Empty text="Активных рекомендаций нет." />}</div>}
  </>;
}
function FleetView({ data }) {
  const [tab, setTab] = useState("recommendations");
  if (!data) return <Empty />;
  return <>
    <div className="view-subtabs" role="tablist" aria-label="Загрузка вагонов">
      <button type="button" role="tab" aria-selected={tab === "recommendations"} className={tab === "recommendations" ? "active" : ""} onClick={() => setTab("recommendations")}>Рекомендации по маршрутам</button>
      <button type="button" role="tab" aria-selected={tab === "hourly"} className={tab === "hourly" ? "active" : ""} onClick={() => setTab("hourly")}>Почасовая загрузка</button>
    </div>
    <div className="ops-grid">
      <Metric label="Вагоно-часов обычно" value={fmtNum(data.total.vehicle_hours_typical)} text="Типовой выпуск." />
      <Metric label="Рекомендуется" value={fmtNum(data.total.vehicle_hours_recommended)} text="С учётом прогноза спроса." />
      <Metric label="Часов риска" value={data.total.hours_overload_risk} text={data.note} />
      {tab === "recommendations"
        ? <div className="data-card wide"><h3>Рекомендации по маршрутам</h3><Table name="Рекомендации по выпуску" exportName="fleet_summary" heads={["Маршрут", "Обычно", "Рекомендуется", "Риск, ч."]} rows={data.summary.map((x) => [x.route, x.vehicle_hours_typical, x.vehicle_hours_recommended, x.hours_overload_risk])} /></div>
        : <div className="data-card wide"><h3>Почасовая загрузка</h3><Table name="Почасовая загрузка" exportName="fleet_hourly" heads={["Маршрут", "Дата", "Час", "Посадки", "Вагоны", "Индекс", "Статус", "Рекомендация"]} rows={data.rows.map((x) => [x.route, fmtDate(x.date), `${x.hour}:00`, fmtNum(x.prediction), x.veh_typ, x.load_index, <Status value={x.status} />, `${x.veh_recommended} (${x.veh_delta >= 0 ? "+" : ""}${x.veh_delta})`])} /></div>}
    </div>
  </>;
}
function PlanView({ data }) { if (!data) return <Empty />; return <div className="ops-grid"><div className="data-card wide"><div className="card-head"><div><h3>План выпуска</h3><p>{data.note}</p></div></div><Table name="План выпуска" exportName="plan" heads={["Маршрут", "Дата", "Час", "Прогноз / коридор", "Выпуск", "Причина"]} rows={data.rows.map((x) => [x.route, fmtDate(x.date), `${x.hour}:00`, `${fmtNum(x.prediction)} (${fmtNum(x.lo)}–${fmtNum(x.hi)})`, `${x.veh_typ} → ${x.veh_recommended}`, x.reason])} /></div></div>; }
function AccuracyView({ data }) { if (!data) return <Empty text="Загружаем историю качества прогноза…" />; if (!data.by_day?.length) return <Empty text={data.detail || "Оценка появится после поступления новых фактических данных и сравнения с ранее сохранённым прогнозом."} />; return <div className="ops-grid"><Metric label="WAPE-score" value={data.wape_score?.toFixed(3) || "—"} text={data.note} /><Metric label="Дней с фактами" value={data.days || 0} text={`Проверено часов: ${data.hours || 0}.`} /><Metric label="Средний горизонт" value={`${data.mean_days_ahead || "—"} дн.`} text="Прогноз опубликован до поступления факта." /><div className="data-card wide"><h3>По дням</h3><Table name="Качество по дням" exportName="accuracy_days" heads={["Дата", "Факт", "Прогноз", "WAPE-score"]} rows={data.by_day.map((x) => [fmtDate(x.date), fmtNum(x.fact), fmtNum(x.forecast), x.wape_score])} /></div><div className="data-card wide"><h3>По маршрутам</h3><Table name="Качество по маршрутам" exportName="accuracy_routes" heads={["Маршрут", "WAPE-score", "Смещение"]} rows={(data.by_route || []).map((x) => [x.route, x.wape_score, `${x.bias > 0 ? "+" : ""}${(x.bias * 100).toFixed(1)}%`])} /></div></div>; }
function DecisionsView({ data }) { if (!data) return <Empty text="Загружаем журнал решений…" />; return <div className="ops-grid"><Metric label="Принято" value={data.summary.accepted} text="Рекомендаций принято." /><Metric label="Отложено" value={data.summary.postponed} text="Требуют дальнейшей проверки." /><Metric label="Отклонено" value={data.summary.rejected} text={data.note} /><div className="data-card wide"><h3>История решений</h3>{data.rows.length ? <Table name="История решений" exportName="decisions" heads={["Дата", "Маршрут", "Решение", "Комментарий", "Факт посадок", "Создано"]} rows={data.rows.map((x) => [fmtDate(x.alert_date), x.route || "сеть", ({ accepted: "Принято", postponed: "Отложено", rejected: "Отклонено" })[x.decision] || x.decision, x.comment || "—", x.factual_boardings == null ? "ещё нет" : fmtNum(x.factual_boardings), x.created_at || "—"])} /> : <Empty text="Решений пока нет. Они появятся здесь после принятия, отклонения или переноса рекомендации в разделе «Оперативная ситуация»." />}</div></div>; }
function cellText(cell) {
  if (cell == null || typeof cell === "boolean") return "";
  if (typeof cell === "string" || typeof cell === "number") return String(cell);
  if (Array.isArray(cell)) return cell.map(cellText).join("");
  if (React.isValidElement(cell)) return cell.type === Status ? (cell.props.value || "—") : cellText(cell.props.children);
  return "";
}

function Table({ heads, rows, name = "Таблица данных", exportName = "table" }) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({});
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sort, setSort] = useState({ column: -1, direction: 1 });
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const dateColumn = heads.indexOf("Дата");
  const filterColumns = heads.map((title, index) => ({ title, index })).filter(x => ["Маршрут", "Статус", "Решение", "Час"].includes(x.title));
  const records = rows.map(cells => ({ cells, values: cells.map(cellText) }));
  const isoDate = text => /^\d{2}\.\d{2}\.\d{4}$/.test(text) ? text.split(".").reverse().join("-") : text;
  const filtered = records.filter(({ values }) => {
    if (query.trim() && !values.join(" ").toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru"))) return false;
    if (Object.entries(filters).some(([index, value]) => value && values[index] !== value)) return false;
    const date = dateColumn >= 0 ? isoDate(values[dateColumn]) : "";
    return dateColumn < 0 || ((!dateFrom || date >= dateFrom) && (!dateTo || date <= dateTo));
  });
  if (sort.column >= 0) filtered.sort((a, b) => {
    const index = sort.column;
    const left = a.values[index], right = b.values[index];
    if (index === dateColumn) return isoDate(left).localeCompare(isoDate(right)) * sort.direction;
    const numeric = text => /^[-+−]?[\d\s.,]+%?$/.test(text) ? Number(text.replace(/[\s%]/g, "").replace(",", ".").replace("−", "-")) : NaN;
    const x = numeric(left), y = numeric(right);
    return (Number.isFinite(x) && Number.isFinite(y) ? x - y : left.localeCompare(right, "ru", { numeric: true })) * sort.direction;
  });
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages - 1);
  const active = query || dateFrom || dateTo || Object.values(filters).some(Boolean);
  const updateFilter = (index, value) => { setFilters(previous => ({ ...previous, [index]: value })); setPage(0); };
  const reset = () => { setQuery(""); setFilters({}); setDateFrom(""); setDateTo(""); setPage(0); };
  function download(format) {
    const quote = value => '"' + (/^[=+@-]/.test(value) ? "'" + value : value).replaceAll('"', '""') + '"';
    const content = [heads, ...filtered.map(record => record.values)].map(row => row.map(quote).join(";")).join("\r\n");
    const excel = `<html><head><meta charset="utf-8"></head><body><table>${[heads, ...filtered.map(record => record.values)].map(row => `<tr>${row.map(value => `<td>${String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</td>`).join("")}</tr>`).join("")}</table></body></html>`;
    const isExcel = format === "excel";
    const url = URL.createObjectURL(new Blob([isExcel ? excel : "\uFEFF" + content], { type: isExcel ? "application/vnd.ms-excel;charset=utf-8" : "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${exportName}_filtered.${isExcel ? "xls" : "csv"}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="table-component" role="region" aria-label={name}>
    <div className="table-toolbar">
      <label className="search-field"><UiIcon name="search" /><input aria-label="Поиск в таблице" placeholder="Поиск в таблице…" value={query} onChange={e => { setQuery(e.target.value); setPage(0); }} /></label>
      <div className="table-column-filters">
        {filterColumns.map(({ title, index }) => <FilterSelect key={title} label={title} value={filters[index] || ""} options={[...new Set(records.map(row => row.values[index]))].sort((a, b) => a.localeCompare(b, "ru", { numeric: true }))} onChange={value => updateFilter(index, value)} />)}
        {dateColumn >= 0 && <div className="table-date-range"><label><span>Дата с</span><input aria-label="Фильтр: дата с" inputMode="numeric" placeholder="гггг-мм-дд" type="text" value={dateFrom} onChange={e => { setDateFrom(e.target.value.replace(/[^\d-]/g, "").slice(0, 10)); setPage(0); }} /></label><label><span>Дата по</span><input aria-label="Фильтр: дата по" inputMode="numeric" placeholder="гггг-мм-дд" type="text" value={dateTo} onChange={e => { setDateTo(e.target.value.replace(/[^\d-]/g, "").slice(0, 10)); setPage(0); }} /></label></div>}
      </div>
      {active && <button className="text-button reset-filters" onClick={reset}>Сбросить</button>}
      <TableExport disabled={!filtered.length} onDownload={download} />
    </div>
    {filtered.length ? <div className="data-table"><table><thead><tr>{heads.map((head, index) => <th key={head} aria-sort={sort.column === index ? (sort.direction === 1 ? "ascending" : "descending") : "none"}><button className="table-sort" onClick={() => { setSort({ column: index, direction: sort.column === index ? -sort.direction : 1 }); setPage(0); }}>{head}<span>{sort.column === index ? (sort.direction === 1 ? "↑" : "↓") : "↕"}</span></button></th>)}</tr></thead><tbody>{filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map((record, index) => <tr key={index}>{record.cells.map((cell, column) => <td key={column}>{cell}</td>)}</tr>)}</tbody></table></div> : <Empty text={active ? "По выбранным фильтрам строк нет. Измените условия или сбросьте фильтры." : "Данных пока нет."} />}
    <div className="table-pagination"><span aria-live="polite">{filtered.length ? `${currentPage * pageSize + 1}–${Math.min((currentPage + 1) * pageSize, filtered.length)} из ${filtered.length}` : "0 строк"}{active ? ` · всего ${rows.length}` : ""}</span><span className="pagination-actions"><button aria-label="Предыдущая страница" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>←</button><span>{currentPage + 1} / {pages}</span><button aria-label="Следующая страница" disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>→</button></span></div>
  </div>;
}

function FilterSelect({ label, value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    const escape = event => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="filter-select" ref={ref}><span>{label}</span><button type="button" aria-label={`Фильтр: ${label}`} aria-expanded={open} onClick={() => setOpen(!open)}>{value || "Все"}<span className="filter-chevron"><SidebarToggleIcon /></span></button>{open && <div className="filter-select-menu" role="listbox" aria-label={`Варианты: ${label}`}><button className={!value ? "selected" : ""} role="option" aria-selected={!value} onClick={() => { onChange(""); setOpen(false); }}>Все</button>{options.map(option => <button key={option} role="option" aria-selected={value === option} className={value === option ? "selected" : ""} onClick={() => { onChange(option); setOpen(false); }}>{option}</button>)}</div>}</div>;
}

function TableExport({ disabled, onDownload }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    const escape = event => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="table-export-menu" ref={ref}><button className="table-export" disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)} title="Скачать строки с учётом фильтров"><UiIcon name="download" /> Экспорт <span className="filter-chevron"><SidebarToggleIcon /></span></button>{open && <div className="export-format-menu"><small>С учётом фильтров</small><button onClick={() => { onDownload("excel"); setOpen(false); }}><b>Excel</b><span>.xls</span></button><button onClick={() => { onDownload("csv"); setOpen(false); }}><b>CSV</b><span>.csv</span></button></div>}</div>;
}

function ForecastExport({ onExport, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    const escape = event => { if (event.key === "Escape") { setOpen(false); ref.current?.querySelector("button")?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="export-menu" ref={ref}><button className="header-action" disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)}><UiIcon name="download" /> Прогноз <span className="filter-chevron"><SidebarToggleIcon /></span></button><div className="export-dropdown" hidden={!open}><small>За выбранный период</small>{["csv", "xlsx"].map(format => <button key={format} onClick={() => { setOpen(false); onExport(format); }}>{format.toUpperCase()}</button>)}</div></div>;
}

function mapPopupContent(feature, loads = {}) {
  const data = feature.properties;
  const isStop = feature.layer.id === "stops-load";
  const content = document.createElement("div"); content.className = "map-feature-card";
  const add = (tag, className, text, parent = content) => { const node = document.createElement(tag); node.className = className; node.textContent = text; parent.appendChild(node); return node; };
  add("div", "map-feature-type", isStop ? "ОСТАНОВКА" : "ТРАМВАЙНЫЙ МАРШРУТ");
  add("h3", "map-feature-title", isStop ? data.name : `Маршрут ${data.route}`);
  if (isStop) {
    const metric = add("div", "map-feature-metric", "");
    add("strong", "", fmtNum(Number(data.prediction)), metric);
    add("span", "", "прогноз посадок", metric);
    add("div", "map-feature-label", "Маршруты на остановке");
    const badges = add("div", "map-route-badges", "");
    String(data.routes || "—").split(",").forEach(route => add("span", "map-route-badge", route.trim(), badges));
    add("p", "map-feature-note", "Оценка за выбранный период");
  } else {
    const level = loadLevel(loads[data.route], loads);
    const labels = { low: "Низкая загрузка", medium: "Средняя загрузка", high: "Высокая загрузка", unknown: "Нет данных" };
    const indicator = add("div", `map-load-status ${level}`, "");
    add("span", "", "", indicator);
    add("b", "", labels[level], indicator);
    add("p", "map-feature-description", data.name || "Трамвайная сеть Москвы");
    add("p", "map-feature-note", "Цвет линии показывает уровень загрузки за выбранный период");
  }
  return content;
}

function UiIcon({ name }) {
  const paths = {
    activity: "M3 12h4l3-8 4 16 3-8h4", bus: "M5 17V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v12H5Zm0-8h14M8 20v-3m8 3v-3M8 13h1m6 0h1", calendar: "M4 5h16v16H4V5Zm0 5h16M8 3v4m8-4v4", chart: "M4 3v17h17M8 15v-4m5 4V7m5 8V5", file: "M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8m-8 4h6", clock: "M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", route: "M7 5h10a4 4 0 0 1 0 8H7a3 3 0 0 0 0 6h10M4 5h0m16 14h0", search: "m16 16 5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0", filter: "M4 7h16M7 12h10m-7 5h4", download: "M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"
  };
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.chart} /></svg>;
}

function useDialog(open, onClose) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    const elements = () => [...(ref.current?.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]') || [])];
    elements()[0]?.focus();
    const keydown = event => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key === "Tab") {
        const items = elements();
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", keydown);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", keydown); document.body.style.overflow = overflow; previous?.focus(); };
  }, [open]);
  return ref;
}

function DashboardClock() {
  const clock = useClock();
  return <b>{clock}</b>;
}
