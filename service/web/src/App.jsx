import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = window.location.port === "8080" ? "/api" : "http://127.0.0.1:8123";
const ROUTE_COLORS = {
  1: "#e30613",
  5: "#44403c",
  7: "#78716c",
  11: "#1aa36f",
  12: "#ffcc00",
  17: "#a16207",
  25: "#b0005a",
  26: "#0f766e",
  28: "#f28c28",
  50: "#57534e"
};
const ALL_ROUTES = Object.keys(ROUTE_COLORS).map(Number);
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

function monthEnd(s) {
  const d = new Date(s + "T00:00:00Z");
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).toISOString().slice(0, 10);
}

function useClock() {
  const [clock, setClock] = useState("--:--:--");
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("ru-RU"));
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
        <h2>Единый диспетчерский центр</h2>
        <div className="sub">Прогноз пассажиропотока трамваев · вход в систему</div>
        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Вход</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>Регистрация</button>
        </div>
        <input name="username" autoComplete="username" placeholder="Логин (латиница, от 3 символов)" required />
        <input name="password" type="password" autoComplete="current-password" placeholder="Пароль (от 6 символов)" required />
        {mode === "register" && <input name="password2" type="password" autoComplete="new-password" placeholder="Повторите пароль" required />}
        <button className="submit" type="submit">{mode === "register" ? "Зарегистрироваться и войти" : "Войти"}</button>
        <div className="auth-msg">{msg}</div>
      </form>
    </div>
  );
}

function NoticeDrawer({ open, notices, onClose }) {
  return (
    <>
      <div className={"drawer-backdrop " + (open ? "open" : "")} onClick={onClose} />
      <aside className={"drawer " + (open ? "open" : "")} aria-label="Уведомления">
        <div className="drawer-head">
          <h3>Уведомления</h3>
          <button className="icon-btn" type="button" onClick={onClose}>×</button>
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
  const clock = useClock();
  const [token, setToken] = useState(localStorage.getItem("edc_token") || "");
  const [user, setUser] = useState(localStorage.getItem("edc_user") || "");
  const [view, setView] = useState("overview");
  const [navExpanded, setNavExpanded] = useState(false);
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
  const [updatedAt, setUpdatedAt] = useState("—");
  const [notices, setNotices] = useState([
    { type: "info", title: "Ожидание данных", text: "После входа система загрузит горизонт модели и построит прогноз." }
  ]);
  const [toasts, setToasts] = useState([]);

  const mapNodeRef = useRef(null);
  const mapRef = useRef(null);
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
        setDateFrom((v) => (v < info.horizon.start || v > info.horizon.end ? info.horizon.start : v));
        setDateTo((v) => (v < info.horizon.start || v > info.horizon.end ? info.horizon.start : v));
      } catch {}
    })();
  }, [token, apiFetch]);

  useEffect(() => {
    if (!hourCanvasRef.current || !routeCanvasRef.current || !window.Chart) return;
    window.Chart.defaults.color = "#54657d";
    window.Chart.defaults.font.family = "-apple-system,sans-serif";
    window.Chart.defaults.font.size = 10;
    hourChartRef.current = new window.Chart(hourCanvasRef.current, {
      type: "line",
      data: { labels: [], datasets: [{ label: "Посадки", data: [], borderColor: "#171717", backgroundColor: "rgba(23,23,23,.08)", fill: true, tension: .3, pointRadius: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: "rgba(23,23,23,.08)" } }, y: { grid: { color: "rgba(23,23,23,.08)" }, beginAtZero: true } } }
    });
    routeChartRef.current = new window.Chart(routeCanvasRef.current, {
      type: "bar",
      data: { labels: [], datasets: [{ label: "Посадки", data: [], backgroundColor: [] }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: "rgba(23,23,23,.08)" }, beginAtZero: true } } }
    });
    return () => {
      hourChartRef.current?.destroy();
      routeChartRef.current?.destroy();
    };
  }, []);

  const recolorRoutes = useCallback((byRoute) => {
    const map = mapRef.current;
    if (!map?.getLayer("routes-line") || !byRoute) return;
    const maxVal = Math.max(...Object.values(byRoute), 1);
    const widthExpr = ["interpolate", ["linear"], ["zoom"],
      9, ["match", ["get", "route"], ...Object.entries(byRoute).flatMap(([r, v]) => [String(r), 2 + 3 * (v / maxVal)]), 2.5],
      15, ["match", ["get", "route"], ...Object.entries(byRoute).flatMap(([r, v]) => [String(r), 5 + 6 * (v / maxVal)]), 6]
    ];
    map.setPaintProperty("routes-line", "line-width", widthExpr);
  }, []);

  useEffect(() => {
    if (!token || !mapNodeRef.current || mapRef.current || !window.maplibregl) return;
    const map = new window.maplibregl.Map({
      container: mapNodeRef.current,
      style: {
        version: 8,
        sources: { "osm-tiles": { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#f4f7fb" } },
          { id: "osm", type: "raster", source: "osm-tiles", paint: { "raster-opacity": .55, "raster-saturation": -.9, "raster-contrast": -.2, "raster-brightness-min": .35, "raster-brightness-max": 1 } }
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
    (async () => {
      while (!map.isStyleLoaded()) await new Promise((r) => setTimeout(r, 100));
      const resp = await apiFetch(`${API_BASE}/routes/geometry`);
      const routesGeo = await resp.json();
      routesGeoRef.current = routesGeo;
      map.addSource("routes", { type: "geojson", data: routesGeo });
      const colorExpr = ["match", ["get", "route"], ...ALL_ROUTES.flatMap((r) => [String(r), ROUTE_COLORS[r]]), "#5f6f89"];
      map.addLayer({ id: "routes-casing", type: "line", source: "routes", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 9, 5.5, 12, 8, 15, 12.5], "line-color": "#fff", "line-opacity": .95 } });
      map.addLayer({ id: "routes-line", type: "line", source: "routes", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 12, 5, 15, 8], "line-color": colorExpr } });
      const endpoints = { type: "FeatureCollection", features: routesGeo.features.flatMap((f) => {
        const coords = f.geometry.coordinates;
        return [
          { type: "Feature", properties: f.properties, geometry: { type: "Point", coordinates: coords[0] } },
          { type: "Feature", properties: f.properties, geometry: { type: "Point", coordinates: coords[coords.length - 1] } }
        ];
      }) };
      map.addSource("endpoints", { type: "geojson", data: endpoints });
      map.addLayer({ id: "endpoints-halo", type: "circle", source: "endpoints", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 5, 14, 9], "circle-color": "#fff", "circle-stroke-width": 2, "circle-stroke-color": colorExpr } });
      map.addLayer({ id: "endpoints-dot", type: "circle", source: "endpoints", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2, 14, 3.5], "circle-color": colorExpr } });
      map.on("click", "routes-line", (e) => {
        const p = e.features[0].properties;
        new window.maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<b>Маршрут ${p.route}</b><br>${p.name}`).addTo(map);
      });
    })();
    return () => {
      window.removeEventListener("resize", resize);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [token, apiFetch]);

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
      routeChartRef.current.data.labels = rSorted.map(([r]) => r);
      routeChartRef.current.data.datasets[0].data = rSorted.map(([, v]) => v);
      routeChartRef.current.data.datasets[0].backgroundColor = rSorted.map(([r]) => ROUTE_COLORS[r] || "#888");
      routeChartRef.current.update();
      let peak = "—";
      if (granularity === "hour") {
        const byHour = {};
        for (const row of data.rows) byHour[row.hour] = (byHour[row.hour] || 0) + row.prediction;
        const hours = Array.from({ length: 24 }, (_, i) => i);
        hourChartRef.current.data.labels = hours.map((h) => h + ":00");
        hourChartRef.current.data.datasets[0].data = hours.map((h) => byHour[h] || 0);
        peak = hours.reduce((a, b) => (byHour[a] || 0) > (byHour[b] || 0) ? a : b) + ":00";
      } else {
        const byDate = {};
        for (const row of data.rows) byDate[row.date] = (byDate[row.date] || 0) + row.prediction;
        const dates = Object.keys(byDate).sort();
        hourChartRef.current.data.labels = dates.map(fmtDateShort);
        hourChartRef.current.data.datasets[0].data = dates.map((d) => byDate[d]);
        const peakDate = dates.reduce((a, b) => byDate[a] > byDate[b] ? a : b, dates[0]);
        peak = peakDate ? fmtDateShort(peakDate) : "—";
      }
      hourChartRef.current.update();
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
    if (view === "map") setTimeout(() => mapRef.current?.resize(), 80);
  }, [view]);

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

  const setPreset = (preset) => {
    if (preset === "day") setDateTo(horizon.start);
    if (preset === "month") setDateTo(monthEnd(horizon.start));
    if (preset === "year") setDateTo(horizon.end);
    setDateFrom(horizon.start);
  };

  const total = fmtNum(lastData?.total_prediction || 0);
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
      <div className="app-shell">
        <div className={"workspace " + (navExpanded ? "nav-expanded" : "")}>
          <nav className={"rail " + (navExpanded ? "expanded" : "collapsed")}>
            <div className="rail-head">
              <div className="rail-logo" title="МосТранспорт">
                <span className="rail-logo-mark"><img src="https://static.tildacdn.com/tild3339-3333-4533-b165-653238633731/favicon.svg" alt="" /></span>
                <b>МосТранспорт</b>
              </div>
              <button className="rail-back" type="button" aria-label={navExpanded ? "Скрыть названия разделов" : "Показать названия разделов"} onClick={() => setNavExpanded((v) => !v)}>
                <SidebarToggleIcon expanded={navExpanded} />
              </button>
            </div>
            {[
              ["overview", <OverviewIcon key="overview-icon" />, "Обзор"],
              ["map", <MapIcon key="map-icon" />, "Карта"]
            ].map(([id, icon, label]) => (
              <button key={id} className={"nav-btn " + (view === id ? "active" : "")} type="button" onClick={() => setView(id)} aria-label={label} title={label}><span className="nav-ico">{icon}</span><span>{label}</span></button>
            ))}
            <div className="rail-account">
              <button className="account-btn" type="button" title={user || "Личный кабинет"}>
                <span>{(user || "ЛК").slice(0, 2).toUpperCase()}</span>
                <b>{user || "Личный кабинет"}</b>
              </button>
              {token && (
                <button className="logout-btn" type="button" title="Выйти" aria-label="Выйти" onClick={() => { localStorage.removeItem("edc_token"); setToken(""); }}>
                  <LogoutIcon />
                  <span>Выйти</span>
                </button>
              )}
            </div>
          </nav>

          <main className="main-stage">
            <div className="command-strip">
              <div className="page-title">
                <h2>{({ overview: "Сводка по прогнозу", map: "Карта сети" })[view]}</h2>
                <p>{({ overview: "Крупные виджеты с главным: спрос, пик, сценарий и распределение.", map: "Карта трамвайной сети с фильтрами периода и сценария." })[view]}</p>
              </div>
              <div className="status-strip">
                <div className="export-menu">
                  <button className="header-action" type="button">Экспорт</button>
                  <div className="export-dropdown">
                    <button type="button" onClick={() => doExport("csv")}>CSV</button>
                    <button type="button" onClick={() => doExport("xlsx")}>XLSX</button>
                  </div>
                </div>
                <button className="icon-btn" type="button" onClick={() => setDrawerOpen(true)} aria-label="Уведомления"><BellIcon /><span className="count">{notices.length}</span></button>
              </div>
            </div>

            <section className="view" style={{ display: view === "overview" ? "" : "none" }}>
                <FilterBar dateFrom={dateFrom} dateTo={dateTo} coef={coef} selectedRoutes={selectedRoutes} hourFrom={hourFrom} hourTo={hourTo} onOpen={() => setFiltersOpen(true)} />
                <div className="overview-grid">
                  <Metric wide label="Пассажиропоток" value={total} text="Суммарный прогноз посадок за выбранный горизонт." />
                  <Metric label="Пик" value={peak} text="Самый нагруженный час или день периода." />
                  <Metric label="Сценарий" value={`×${coef.toFixed(2)}`} text={coef === 1 ? "Нормальный режим без поправки." : `Активна поправка: ${scenarioKind}.`} />
                  <div className="hero-metric wide"><small>Динамика</small><div className="chart-box"><canvas ref={hourCanvasRef} /></div></div>
                  <div className="hero-metric wide"><small>Распределение по маршрутам</small><div className="chart-box"><canvas ref={routeCanvasRef} /></div></div>
                </div>
            </section>

            <section className="view" style={{ display: view === "map" ? "" : "none" }}>
                <div className="map-layout">
                  <FilterBar dateFrom={dateFrom} dateTo={dateTo} coef={coef} selectedRoutes={selectedRoutes} hourFrom={hourFrom} hourTo={hourTo} onOpen={() => setFiltersOpen(true)} />
                  <MapCard mapNodeRef={mapNodeRef} periodLabel={periodLabel} />
                </div>
            </section>

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

function Metric({ label, value, text, wide }) {
  return <div className={"hero-metric " + (wide ? "wide" : "")}><small>{label}</small><strong>{value}</strong><p>{text}</p></div>;
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
    onApply(draft);
    onClose();
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="filter-modal" role="dialog" aria-modal="true" aria-label="Параметры прогноза">
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
          <button className="primary" type="button" onClick={apply}>Применить</button>
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
          <span>Текущие факторы</span>
          <b>{period}</b>
        </div>
        <div className="factor-list">
          <div className="factor-chip"><span>Маршруты</span><b>{routeSummary}</b></div>
          <div className="factor-chip"><span>Часы</span><b>{String(hourFrom).padStart(2, "0")}:00-{String(hourTo).padStart(2, "0")}:00</b></div>
          <div className="factor-chip"><span>Поправка</span><b>×{coef.toFixed(2)}</b></div>
        </div>
      </div>
      <button className="scenario-launch" type="button" onClick={onOpen}>
        Изменить
      </button>
    </section>
  );
}

function MapCard({ mapNodeRef, periodLabel }) {
  return (
    <div className="map-canvas-card">
      <div id="map" ref={mapNodeRef} />
      <div className="map-title-bar"><div className="badge">Москва · трамвайная сеть · <b>{periodLabel}</b></div></div>
      <div className="map-legend">
        <div className="legend-title">Толщина линии = загрузка</div>
        <div className="lg-row"><span className="lg-bar" style={{ height: 2, background: "#171717" }} />низкая</div>
        <div className="lg-row"><span className="lg-bar" style={{ height: 4, background: "#171717" }} />средняя</div>
        <div className="lg-row"><span className="lg-bar" style={{ height: 6, background: "#171717" }} />высокая</div>
        <div className="legend-note">Цвет — номер маршрута</div>
      </div>
    </div>
  );
}
