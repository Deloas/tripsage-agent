import { AlertTriangle, LocateFixed, MapPinned, RefreshCw, Route, SendHorizonal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiCodeError, buildAiMapWorkbench, fetchAmapClientConfig } from "../lib/api";
import type { AiMapPoint, AiMapWorkbenchResult, AmapClientConfig, ChatResponse, StructuredTravelPlan } from "../lib/types";

declare global {
  interface Window {
    AMap?: any;
    _AMapSecurityConfig?: { securityJsCode?: string };
  }
}

interface AiMapWorkbenchProps {
  latest: ChatResponse | null;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  onPrompt: (prompt: string) => void;
}

const MAX_ANSWER_LENGTH = 12000;
const MAX_ITINERARY_TITLE_LENGTH = 180;
const MAX_ITINERARY_DETAIL_LENGTH = 1800;
const AI_MAP_STORAGE_PREFIX = "tripsage_ai_map_result:";
const aiMapCache = new Map<string, AiMapWorkbenchResult>();

export function AiMapWorkbench({ latest, messages, onPrompt }: AiMapWorkbenchProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const [config, setConfig] = useState<AmapClientConfig | null>(null);
  const [mapData, setMapData] = useState<AiMapWorkbenchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [runtimeWarning, setRuntimeWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<number | "all">("all");

  const structuredPlan = useMemo(() => buildStructuredPlanPayload(latest?.structured_plan || null), [latest?.structured_plan]);
  const city = useMemo(() => inferDestinationCity(latest), [latest]);
  const answerText = useMemo(() => buildAnswerText(latest, messages), [latest, messages]);
  const itineraryPayload = useMemo(() => buildItineraryPayload(latest), [latest]);
  const structuredPlanFingerprint = useMemo(() => JSON.stringify(structuredPlan || {}), [structuredPlan]);
  const itineraryFingerprint = useMemo(() => JSON.stringify(itineraryPayload), [itineraryPayload]);
  const cacheKey = useMemo(
    () => buildMapCacheKey(latest?.conversation_id, city, answerText, itineraryFingerprint, structuredPlanFingerprint),
    [answerText, city, itineraryFingerprint, latest?.conversation_id, structuredPlanFingerprint],
  );
  const hasPlanData = Boolean((structuredPlan?.days?.length || 0) > 0 || answerText || itineraryPayload.length);
  const visiblePoints = useMemo(
    () => (selectedDay === "all" ? mapData?.points || [] : (mapData?.points || []).filter((point) => point.day === selectedDay)),
    [mapData, selectedDay],
  );
  const displayPoints = visiblePoints.length ? visiblePoints : mapData?.points || [];
  const days = useMemo(
    () => Array.from(new Set((mapData?.points || []).map((point) => point.day).filter((day): day is number => typeof day === "number"))),
    [mapData],
  );
  const useRealAmap = Boolean(config?.js_api_key && mapReady && !runtimeWarning);

  useEffect(() => {
    void fetchAmapClientConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    return () => {
      destroyAmapInstance(mapInstanceRef.current);
      mapInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!hasPlanData) {
      setMapData(null);
      setError(null);
      return;
    }

    const cached = readCachedMapData(cacheKey);
    if (cached) {
      setMapData(cached);
      setError(null);
      return;
    }

    void rebuildMap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey, hasPlanData]);

  useEffect(() => {
    if (!config?.js_api_key) {
      setMapReady(false);
      setRuntimeWarning(null);
      return;
    }

    let cancelled = false;
    setRuntimeWarning(null);
    void loadAmap(config)
      .then(() => {
        if (!cancelled) {
          setMapReady(Boolean(window.AMap));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMapReady(false);
          setRuntimeWarning("高德底图加载失败，已切换为坐标预览。请检查 Web 端 Key 的域名白名单和安全密钥。");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [config]);

  useEffect(() => {
    if (!useRealAmap || !mapRef.current || !mapData?.points.length || !window.AMap) return;
    renderAmap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useRealAmap, mapData, selectedDay]);

  async function rebuildMap(options?: { force?: boolean }) {
    if (!latest) {
      setMapData(null);
      setError(null);
      return;
    }

    if (!answerText && !itineraryPayload.length) {
      setMapData(null);
      setError("当前方案还没有足够的地点信息，先在规划页生成一版更完整的行程。");
      return;
    }

    if (!options?.force) {
      const cached = readCachedMapData(cacheKey);
      if (cached) {
        setMapData(cached);
        setError(null);
        return;
      }
    }

    setLoading(true);
    setError(null);
    try {
      const result = await buildAiMapWorkbench({
        city,
        answer: answerText,
        itinerary: itineraryPayload,
        structured_plan: structuredPlan,
        mode: "driving",
      });
      writeCachedMapData(cacheKey, result);
      setMapData(result);
      if (!result.points.length) {
        setError("地图工作台已完成解析，但这版方案里还没有识别出足够的真实地点。可以补充更明确的景点、商圈、车站或酒店名称后重试。");
      }
    } catch (nextError) {
      setMapData(null);
      setError(resolveMapWorkbenchError(nextError));
    } finally {
      setLoading(false);
    }
  }

  function renderAmap() {
    try {
      if (!mapRef.current || !window.AMap || !mapData) return;
      const points = displayPoints.filter((point) => typeof point.lng === "number" && typeof point.lat === "number");
      if (!points.length) return;

      if (!mapInstanceRef.current) {
        mapInstanceRef.current = new window.AMap.Map(mapRef.current, {
          zoom: 12,
          viewMode: "2D",
          mapStyle: "amap://styles/normal",
        });
      }

      const map = mapInstanceRef.current;
      const overlays: any[] = [];
      map.clearMap();

      const lngLats = points.map((point) => [point.lng, point.lat]);
      points.forEach((point, index) => {
        const marker = new window.AMap.Marker({
          position: [point.lng, point.lat],
          title: point.name,
          label: {
            content: `<div class="amap-poi-label"><b>${index + 1}</b>${escapeHtml(point.name)}</div>`,
            direction: "top",
          },
        });
        overlays.push(marker);
      });

      if (lngLats.length > 1) {
        const polyline = new window.AMap.Polyline({
          path: lngLats,
          strokeColor: "#1f7a67",
          strokeWeight: 6,
          strokeOpacity: 0.86,
          lineJoin: "round",
        });
        overlays.push(polyline);
      }

      if (overlays.length) {
        map.add(overlays);
        map.setFitView(overlays, false, [76, 76, 76, 76]);
      }
    } catch {
      destroyAmapInstance(mapInstanceRef.current);
      mapInstanceRef.current = null;
      setMapReady(false);
      setRuntimeWarning("高德底图已返回，但地图渲染异常，当前已切换为坐标预览。");
    }
  }

  function sendToAgent() {
    if (!mapData?.points.length) return;
    const route = (displayPoints.length ? displayPoints : mapData.points)
      .map((point, index) => `${index + 1}. ${point.name}${point.address ? `（${point.address}）` : ""}`)
      .join("\n");
    onPrompt([
      "请基于地图工作台已经解析出的真实地点和路线，继续优化当前旅行方案。",
      `目的地：${mapData.city || city || "待确认"}`,
      `总通勤参考：${formatMeters(mapData.total_distance_meters)} / ${mapData.total_duration_minutes} 分钟`,
      "地点顺序：",
      route,
      "请重点检查：路线是否绕路、每天地点是否过密、是否需要调整顺序、雨天备选和交通方式。",
    ].join("\n"));
  }

  return (
    <div className="view-frame ai-map-page">
      <section className="page-band ai-map-hero">
        <div>
          <div className="section-kicker">
            <MapPinned size={16} />
            AI 地图工作台
          </div>
          <h2>把智能体输出变成真实地图路线</h2>
          <p>自动抽取当前 AI 方案里的景点、街区、车站与餐饮线索，使用高德 POI 坐标在独立地图中展示。</p>
        </div>
        <div className="ai-map-hero-actions">
          <button type="button" className="secondary-action" onClick={() => void rebuildMap({ force: true })} disabled={loading || !hasPlanData}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            重新生成地图
          </button>
          <button type="button" className="primary-action" onClick={sendToAgent} disabled={!mapData?.points.length}>
            <SendHorizonal size={15} />
            让智能体优化路线
          </button>
        </div>
      </section>

      <section className="ai-map-shell">
        <div className="ai-map-main-panel">
          <div className="ai-map-toolbar">
            <div>
              <strong>{city || mapData?.city || "目的地待识别"}</strong>
              <span>{mapData ? `${mapData.points.length} 个地点 · ${mapData.routes.length} 段路线` : "先在规划页生成方案后再打开地图"}</span>
            </div>
            <div className="ai-map-day-tabs" role="tablist" aria-label="按天筛选地图地点">
              <button type="button" className={selectedDay === "all" ? "active" : ""} onClick={() => setSelectedDay("all")}>全部</button>
              {days.map((day) => (
                <button type="button" className={selectedDay === day ? "active" : ""} onClick={() => setSelectedDay(day)} key={day}>
                  Day {day}
                </button>
              ))}
            </div>
          </div>

          <div className="ai-real-map-frame">
            {useRealAmap ? <div ref={mapRef} className="ai-real-map-canvas" /> : <FallbackCoordinateMap points={displayPoints} />}
            {!config?.js_api_key ? (
              <div className="ai-map-config-warning">
                <AlertTriangle size={15} />
                未配置 `AMAP_JS_API_KEY`，当前展示坐标预览；配置后会自动启用真实高德底图。
              </div>
            ) : null}
            {runtimeWarning ? (
              <div className="ai-map-config-warning">
                <AlertTriangle size={15} />
                {runtimeWarning}
              </div>
            ) : null}
            {loading ? <div className="ai-map-loading">正在解析 AI 输出中的地点与路线...</div> : null}
          </div>

          {error ? <div className="ai-map-error">{error}</div> : null}
          {!hasPlanData && !loading ? (
            <div className="ai-map-error">当前还没有可用于地图解析的规划结果。先回到规划页生成方案；如果你刚刷新页面，未保存的临时方案不会自动恢复。</div>
          ) : null}
        </div>

        <aside className="ai-map-side-panel">
          <div className="ai-map-stat-grid">
            <MapStat label="地点" value={String(mapData?.points.length || 0)} />
            <MapStat label="路线" value={String(mapData?.routes.length || 0)} />
            <MapStat label="通勤" value={formatMeters(mapData?.total_distance_meters || 0)} />
            <MapStat label="耗时" value={`${mapData?.total_duration_minutes || 0}分`} />
          </div>

          <section className="ai-map-poi-list" aria-label="地图地点列表">
            <div className="ai-map-section-head">
              <LocateFixed size={15} />
              <strong>真实 POI</strong>
            </div>
            {displayPoints.map((point, index) => (
              <article className="ai-map-poi-card" key={`${point.name}-${index}`}>
                <span>{index + 1}</span>
                <div>
                  <strong>{point.name}</strong>
                  <p>{point.address || point.district || point.city || "地址待确认"}</p>
                  <em>{point.type || point.source || "AI 地点"}</em>
                </div>
              </article>
            ))}
            {!displayPoints.length && !loading ? <div className="ai-map-empty">当前还没有可展示地点，先在规划页生成一版旅行方案。</div> : null}
          </section>

          <section className="ai-map-route-list" aria-label="路线段列表">
            <div className="ai-map-section-head">
              <Route size={15} />
              <strong>路线段</strong>
            </div>
            {(mapData?.routes || []).map((leg) => (
              <article className="ai-map-route-card" key={leg.index}>
                <strong>{leg.origin.name} → {leg.destination.name}</strong>
                <span>{formatMeters(leg.distance_meters)} / {leg.duration_minutes} 分钟</span>
              </article>
            ))}
            {!mapData?.routes.length && !loading ? <div className="ai-map-empty">地点解析完成后，这里会展示每一段路线的通勤距离与耗时。</div> : null}
          </section>
        </aside>
      </section>
    </div>
  );
}

function FallbackCoordinateMap({ points }: { points: AiMapPoint[] }) {
  return (
    <div className="ai-coordinate-map" aria-label="坐标预览地图">
      {points.map((point, index) => (
        <div
          className="ai-coordinate-pin"
          style={{
            left: `${10 + (index % 4) * 24}%`,
            top: `${18 + Math.floor(index / 4) * 22 + (index % 2) * 8}%`,
          }}
          key={`${point.name}-${index}`}
        >
          <span>{index + 1}</span>
          <strong>{point.name}</strong>
        </div>
      ))}
    </div>
  );
}

function MapStat({ label, value }: { label: string; value: string }) {
  return (
    <article>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function loadAmap(config: AmapClientConfig) {
  if (window.AMap) return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    if (!config.js_api_key) {
      reject(new Error("missing amap key"));
      return;
    }

    if (config.security_js_code) {
      window._AMapSecurityConfig = { securityJsCode: config.security_js_code };
    }

    const existing = document.querySelector<HTMLScriptElement>("script[data-amap-js]");
    if (existing) {
      const state = existing.getAttribute("data-state");
      if (state === "loaded" && window.AMap) {
        resolve();
        return;
      }
      if (state === "error") {
        existing.remove();
      } else {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error("amap script load failed")), { once: true });
        return;
      }
    }

    const script = document.createElement("script");
    script.dataset.amapJs = "true";
    script.setAttribute("data-state", "loading");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.js_api_key)}&plugin=AMap.Scale,AMap.ToolBar`;
    script.async = true;
    script.onload = () => {
      script.setAttribute("data-state", "loaded");
      if (window.AMap) {
        resolve();
        return;
      }
      reject(new Error("amap loaded without window.AMap"));
    };
    script.onerror = () => {
      script.setAttribute("data-state", "error");
      reject(new Error("amap script load failed"));
    };
    document.head.appendChild(script);
  });
}

function buildAnswerText(latest: ChatResponse | null, messages: AiMapWorkbenchProps["messages"]) {
  if (!latest) return "";
  const primary = sanitizeAnswerText(latest.answer || "");
  const lastAssistant = sanitizeAnswerText([...messages].reverse().find((item) => item.role === "assistant")?.content || "");

  if (!primary) return lastAssistant.slice(0, MAX_ANSWER_LENGTH);
  if (!lastAssistant) return primary.slice(0, MAX_ANSWER_LENGTH);

  const normalizedPrimary = normalizeCompareText(primary);
  const normalizedAssistant = normalizeCompareText(lastAssistant);
  if (
    normalizedPrimary === normalizedAssistant
    || normalizedPrimary.includes(normalizedAssistant)
    || normalizedAssistant.includes(normalizedPrimary)
  ) {
    return (primary.length >= lastAssistant.length ? primary : lastAssistant).slice(0, MAX_ANSWER_LENGTH);
  }

  return `${primary}\n\n${lastAssistant}`.slice(0, MAX_ANSWER_LENGTH);
}

function buildItineraryPayload(latest: ChatResponse | null) {
  return (latest?.itinerary || []).map((day) => ({
    day: day.day,
    title: String(day.title || "").slice(0, MAX_ITINERARY_TITLE_LENGTH),
    items: (day.items || []).map((item) => ({
      time: item.time || "",
      title: String(item.title || "").slice(0, MAX_ITINERARY_TITLE_LENGTH),
      detail: String(item.detail || "").slice(0, MAX_ITINERARY_DETAIL_LENGTH),
    })),
  }));
}

function buildStructuredPlanPayload(plan: StructuredTravelPlan | null) {
  if (!plan?.days?.length) return null;
  return {
    city: plan.city || null,
    trip_summary: String(plan.trip_summary || "").slice(0, 400),
    planning_style: String(plan.planning_style || "").slice(0, 120),
    budget_hint: String(plan.budget_hint || "").slice(0, 200),
    transport_hint: String(plan.transport_hint || "").slice(0, 200),
    rainy_day_hint: String(plan.rainy_day_hint || "").slice(0, 200),
    risk_hint: String(plan.risk_hint || "").slice(0, 200),
    days: (plan.days || []).map((day) => ({
      day: day.day,
      title: String(day.title || "").slice(0, 120),
      summary: String(day.summary || "").slice(0, 240),
      route_digest: String(day.route_digest || "").slice(0, 240),
      agenda: (day.agenda || []).map((item) => ({
        time: String(item.time || "").slice(0, 40),
        title: String(item.title || "").slice(0, 120),
        detail: String(item.detail || "").slice(0, 600),
        place_name: String(item.place_name || "").slice(0, 80) || null,
        transport_hint: String(item.transport_hint || "").slice(0, 120) || null,
      })),
      places: (day.places || []).map((place, index) => ({
        name: String(place.name || "").slice(0, 80),
        aliases: (place.aliases || []).map((alias) => String(alias || "").slice(0, 80)).filter(Boolean).slice(0, 4),
        intro: String(place.intro || "").slice(0, 240),
        category: String(place.category || "").slice(0, 40) || null,
        stay_minutes: typeof place.stay_minutes === "number" ? place.stay_minutes : null,
        transport_hint: String(place.transport_hint || "").slice(0, 120) || null,
        order: place.order || index + 1,
      })),
    })),
  };
}

function inferDestinationCity(latest: ChatResponse | null) {
  if (latest?.structured_plan?.city) return latest.structured_plan.city;
  const destination = latest?.cards.find((card) => card.type === "destination")?.title;
  return destination || latest?.itinerary?.[0]?.title?.match(/[\u4e00-\u9fa5]{2,6}/)?.[0] || null;
}

function resolveMapWorkbenchError(error: unknown) {
  if (error instanceof ApiCodeError) {
    if (error.code === 422) {
      return "地图工作台请求过长或结构不合法，前端已做裁剪。请重新点击一次“重新生成地图”。";
    }
    const detail = typeof error.data === "object" && error.data && "error" in error.data
      ? String((error.data as { error?: unknown }).error || "")
      : "";
    return detail ? `${error.message}：${detail}` : error.message;
  }

  if (error instanceof Error && /timeout/i.test(error.message)) {
    return "地图工作台请求超时，通常是地点较多或高德接口响应慢。请稍后重试，或先缩小一天内的地点数量。";
  }

  return "地图工作台生成失败，请确认后端和高德地图配置可用。";
}

function destroyAmapInstance(instance: any) {
  if (!instance) return;
  try {
    instance.destroy?.();
  } catch {
    // 中文注释：高德实例销毁失败时不再向上抛错，避免影响页面切换。
  }
}

function sanitizeAnswerText(value: string) {
  return value.replace(/\n{3,}/g, "\n\n").trim();
}

function normalizeCompareText(value: string) {
  return value.replace(/\s+/g, "");
}

function formatMeters(value: number) {
  if (!value) return "0m";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}km`;
  return `${value}m`;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function buildMapCacheKey(
  conversationId: string | undefined,
  city: string | null,
  answer: string,
  itineraryFingerprint: string,
  structuredPlanFingerprint: string,
) {
  if (!conversationId && !answer && !itineraryFingerprint && !structuredPlanFingerprint) return "";
  return `map:${conversationId || "guest"}:${city || "unknown"}:${hashText(`${structuredPlanFingerprint}::${answer}::${itineraryFingerprint}`)}`;
}

function hashText(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function readCachedMapData(cacheKey: string) {
  if (!cacheKey) return null;
  const memoryCached = aiMapCache.get(cacheKey);
  if (memoryCached) return memoryCached;

  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(`${AI_MAP_STORAGE_PREFIX}${cacheKey}`);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as AiMapWorkbenchResult;
    aiMapCache.set(cacheKey, parsed);
    return parsed;
  } catch {
    window.sessionStorage.removeItem(`${AI_MAP_STORAGE_PREFIX}${cacheKey}`);
    return null;
  }
}

function writeCachedMapData(cacheKey: string, value: AiMapWorkbenchResult) {
  if (!cacheKey) return;
  aiMapCache.set(cacheKey, value);
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(`${AI_MAP_STORAGE_PREFIX}${cacheKey}`, JSON.stringify(value));
}
