import {
  AlertTriangle,
  GitBranch,
  Layers3,
  LocateFixed,
  MapPinned,
  Milestone,
  RefreshCw,
  Route,
  SendHorizonal,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiCodeError, buildAiMapWorkbench, fetchAmapClientConfig } from "../lib/api";
import type {
  AiMapPoint,
  AiMapRouteLeg,
  AiMapWorkbenchResult,
  AmapClientConfig,
  ChatResponse,
  StructuredTravelPlan,
  TravelPlanView,
} from "../lib/types";

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
  focus?: {
    day?: number;
    pointName?: string | null;
    nonce: number;
  } | null;
}

type RouteDayCard = {
  day: number;
  points: string[];
  totalDistance: number;
  totalDuration: number;
  legCount: number;
};

const MAX_ANSWER_LENGTH = 12000;
const MAX_ITINERARY_TITLE_LENGTH = 180;
const MAX_ITINERARY_DETAIL_LENGTH = 1800;
const AI_MAP_STORAGE_PREFIX = "tripsage_ai_map_result:";
const aiMapCache = new Map<string, AiMapWorkbenchResult>();

export function AiMapWorkbench({ latest, messages, onPrompt, focus }: AiMapWorkbenchProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const poiCardRefs = useRef<Record<string, HTMLElement | null>>({});

  const [config, setConfig] = useState<AmapClientConfig | null>(null);
  const [mapData, setMapData] = useState<AiMapWorkbenchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [runtimeWarning, setRuntimeWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDay, setSelectedDay] = useState<number | "all">("all");
  const [pointMode, setPointMode] = useState<"main" | "raw">("main");
  const [selectedRouteIndex, setSelectedRouteIndex] = useState<number | null>(null);

  const structuredPlan = useMemo(() => buildStructuredPlanPayload(latest?.structured_plan || null), [latest?.structured_plan]);
  const travelPlanView = useMemo(() => buildTravelPlanViewPayload(latest?.travel_plan_view || null), [latest?.travel_plan_view]);
  const city = useMemo(() => inferDestinationCity(latest), [latest]);
  const answerText = useMemo(() => buildAnswerText(latest, messages), [latest, messages]);
  const itineraryPayload = useMemo(() => buildItineraryPayload(latest), [latest]);
  const structuredPlanFingerprint = useMemo(() => JSON.stringify(structuredPlan || {}), [structuredPlan]);
  const travelPlanViewFingerprint = useMemo(() => JSON.stringify(travelPlanView || {}), [travelPlanView]);
  const itineraryFingerprint = useMemo(() => JSON.stringify(itineraryPayload), [itineraryPayload]);
  const normalizedFocusName = useMemo(() => normalizePointText(focus?.pointName || ""), [focus?.pointName]);

  const cacheKey = useMemo(
    () =>
      buildMapCacheKey(
        latest?.conversation_id,
        city,
        answerText,
        itineraryFingerprint,
        structuredPlanFingerprint,
        travelPlanViewFingerprint,
      ),
    [answerText, city, itineraryFingerprint, latest?.conversation_id, structuredPlanFingerprint, travelPlanViewFingerprint],
  );

  const hasPlanData = Boolean(
    (structuredPlan?.days?.length || 0) > 0
    || (travelPlanView?.days?.length || 0) > 0
    || (travelPlanView?.map_schedule?.markers?.length || 0) > 0
    || answerText
    || itineraryPayload.length,
  );

  const sourcePoints = useMemo(
    () => (pointMode === "raw" ? mapData?.raw_points || mapData?.points || [] : mapData?.points || []),
    [mapData, pointMode],
  );

  const days = useMemo(
    () => Array.from(new Set(sourcePoints.map((point) => point.day).filter((day): day is number => typeof day === "number"))).sort((a, b) => a - b),
    [sourcePoints],
  );

  const visiblePoints = useMemo(
    () => (selectedDay === "all" ? sourcePoints : sourcePoints.filter((point) => point.day === selectedDay)),
    [selectedDay, sourcePoints],
  );

  const displayPoints = visiblePoints.length ? visiblePoints : sourcePoints;

  const displayRoutes = useMemo(() => {
    const routes = mapData?.routes || [];
    if (selectedDay === "all") return routes;
    return routes.filter((leg) => leg.origin.day === selectedDay || leg.destination.day === selectedDay);
  }, [mapData, selectedDay]);

  const routeDayCards = useMemo(() => buildRouteDayCards(mapData?.routes || [], mapData?.points || []), [mapData]);

  const selectedRouteLeg = useMemo(
    () => displayRoutes.find((leg) => leg.index === selectedRouteIndex) || displayRoutes[0] || null,
    [displayRoutes, selectedRouteIndex],
  );

  const focusedDisplayPoint = useMemo(
    () => displayPoints.find((point) => pointMatchesFocus(point, normalizedFocusName)) || null,
    [displayPoints, normalizedFocusName],
  );

  const mergedPoiCount = useMemo(
    () => (mapData?.points || []).reduce((total, point) => total + Math.max((point.group_size || 1) - 1, 0), 0),
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
        if (!cancelled) setMapReady(Boolean(window.AMap));
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
    if (!focus?.nonce) return;
    setPointMode("main");
    if (typeof focus.day === "number") {
      setSelectedDay(focus.day);
      return;
    }
    if (normalizedFocusName) {
      const matched = sourcePoints.find((point) => pointMatchesFocus(point, normalizedFocusName));
      setSelectedDay(typeof matched?.day === "number" ? matched.day : "all");
      return;
    }
    setSelectedDay("all");
  }, [focus?.day, focus?.nonce, normalizedFocusName, sourcePoints]);

  useEffect(() => {
    if (!displayRoutes.length) {
      setSelectedRouteIndex(null);
      return;
    }
    setSelectedRouteIndex((current) => (
      current && displayRoutes.some((leg) => leg.index === current) ? current : displayRoutes[0].index
    ));
  }, [displayRoutes]);

  useEffect(() => {
    if (!focusedDisplayPoint) return;
    poiCardRefs.current[buildPointDomKey(focusedDisplayPoint)]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusedDisplayPoint]);

  useEffect(() => {
    if (!useRealAmap || !mapRef.current || !mapData?.points.length || !window.AMap) return;
    renderAmap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useRealAmap, mapData, normalizedFocusName, selectedDay]);

  async function rebuildMap(options?: { force?: boolean }) {
    if (!latest) {
      setMapData(null);
      setError(null);
      return;
    }

    if (!hasPlanData) {
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
        travel_plan_view: travelPlanView,
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
      const lngLats = points.map((point) => [point.lng, point.lat]);
      const targetPoint = points.find((point) => pointMatchesFocus(point, normalizedFocusName)) || null;

      map.clearMap();

      points.forEach((point, index) => {
        const isFocused = pointMatchesFocus(point, normalizedFocusName);
        const marker = new window.AMap.Marker({
          position: [point.lng, point.lat],
          title: point.name,
          zIndex: isFocused ? 160 : 100,
          label: {
            content: `<div class="amap-poi-label${isFocused ? " focused" : ""}"><b>${index + 1}</b>${escapeHtml(point.name)}</div>`,
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

      map.add(overlays);
      map.setFitView(overlays, false, [76, 76, 76, 76]);
      if (targetPoint?.lng && targetPoint?.lat) {
        map.setCenter([targetPoint.lng, targetPoint.lat]);
        map.setZoom(Math.max(map.getZoom?.() || 12, 13));
      }
    } catch {
      destroyAmapInstance(mapInstanceRef.current);
      mapInstanceRef.current = null;
      setMapReady(false);
      setRuntimeWarning("高德底图已返回，但地图渲染异常，当前已切换为坐标预览。");
    }
  }

  function sendToAgent() {
    if (!mapData || !displayPoints.length) return;
    const route = displayPoints
      .map((point, index) => {
        const mergedHint = point.group_size && point.group_size > 1 ? `，已合并 ${point.group_size} 个子点` : "";
        return `${index + 1}. ${point.name}${point.address ? `（${point.address}）` : ""}${mergedHint}`;
      })
      .join("\n");
    onPrompt([
      "请基于地图工作台已经解析出的真实地点和路线，继续优化当前旅行方案。",
      `目的地：${mapData.city || city || "待确认"}`,
      `总通勤参考：${formatMeters(mapData.total_distance_meters)} / ${formatMinutes(mapData.total_duration_minutes)}`,
      `当前地图视图：${pointMode === "main" ? "主线景点模式" : "原始解析模式"}`,
      "地点顺序：",
      route,
      "请重点检查：路线是否绕路、每天地点是否过密、是否需要调整顺序、雨天备选和交通方式。",
    ].join("\n"));
  }

  function sendDayRouteToAgent(day: number) {
    const dayCard = routeDayCards.find((item) => item.day === day);
    if (!dayCard) return;
    onPrompt([
      `请基于 Day ${day} 的地图路线继续优化当前旅行方案。`,
      `当天地点顺序：${dayCard.points.join(" -> ") || "待补充"}`,
      `当天总通勤：${formatMeters(dayCard.totalDistance)} / ${formatMinutes(dayCard.totalDuration)}`,
      "请重点检查：是否绕路、通勤是否过长、景点顺序是否合理、是否适合当前节奏。",
    ].join("\n"));
  }

  function sendLegToAgent(leg: AiMapRouteLeg) {
    onPrompt([
      "请针对当前地图路线中的单段通勤做精细优化。",
      `通勤段：${leg.origin.name} -> ${leg.destination.name}`,
      `距离与耗时：${formatMeters(leg.distance_meters)} / ${formatMinutes(leg.duration_minutes)}`,
      `模式：${leg.mode_used || leg.mode || "driving"}`,
      `路线步骤：${(leg.steps || []).slice(0, 8).map((step, index) => `${index + 1}. ${step.instruction || step.road || "继续前往下一段"}`).join("\n") || "暂无详细步骤"}`,
      "请判断这段是否值得换顺序、压缩、拆分或替换交通方式，并给出改法。",
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
              <span>
                {mapData
                  ? `${mapData.points.length} 个主线地点 / ${mapData.raw_points?.length || mapData.points.length} 个解析点 / ${displayRoutes.length} 段路线`
                  : "先在规划页生成方案后再打开地图"}
              </span>
            </div>
            <div className="ai-map-toolbar-controls">
              <div className="ai-map-mode-tabs" role="tablist" aria-label="切换地图点位模式">
                <button type="button" className={pointMode === "main" ? "active" : ""} onClick={() => setPointMode("main")}>
                  <GitBranch size={14} />
                  主线
                </button>
                <button type="button" className={pointMode === "raw" ? "active" : ""} onClick={() => setPointMode("raw")}>
                  <Layers3 size={14} />
                  原始点
                </button>
              </div>
              <div className="ai-map-day-tabs" role="tablist" aria-label="按天筛选地图地点">
                <button type="button" className={selectedDay === "all" ? "active" : ""} onClick={() => setSelectedDay("all")}>
                  全部
                </button>
                {days.map((day) => (
                  <button type="button" className={selectedDay === day ? "active" : ""} onClick={() => setSelectedDay(day)} key={day}>
                    Day {day}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="ai-real-map-frame">
            {useRealAmap ? (
              <div ref={mapRef} className="ai-real-map-canvas" />
            ) : (
              <FallbackCoordinateMap points={displayPoints} focusedName={normalizedFocusName} />
            )}
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

          {routeDayCards.length ? (
            <section className="ai-map-day-route-strip" aria-label="分日路线概览">
              {routeDayCards.map((item) => (
                <article className={`ai-map-day-route-card ${selectedDay === item.day ? "is-active" : ""}`} key={`route-day-${item.day}`}>
                  <div className="ai-map-day-route-copy">
                    <strong>Day {item.day}</strong>
                    <span>{item.points.join(" -> ")}</span>
                  </div>
                  <div className="ai-map-day-route-meta">
                    <label>{formatMeters(item.totalDistance)}</label>
                    <label>{formatMinutes(item.totalDuration)}</label>
                    <button type="button" className="travel-inline-action subtle" onClick={() => setSelectedDay(item.day)}>
                      查看当天
                    </button>
                    <button type="button" className="travel-inline-action subtle" onClick={() => sendDayRouteToAgent(item.day)}>
                      优化这一天
                    </button>
                  </div>
                </article>
              ))}
            </section>
          ) : null}

          {error ? <div className="ai-map-error">{error}</div> : null}
          {!hasPlanData && !loading ? (
            <div className="ai-map-error">当前还没有可用于地图解析的规划结果。先回到规划页生成方案；如果你刚刷新页面，未保存的临时方案不会自动恢复。</div>
          ) : null}
        </div>

        <aside className="ai-map-side-panel">
          <div className="ai-map-stat-grid">
            <MapStat label="主线" value={String(mapData?.points.length || 0)} />
            <MapStat label="解析点" value={String(mapData?.raw_points?.length || mapData?.points.length || 0)} />
            <MapStat label="归并" value={String(mergedPoiCount)} />
            <MapStat label="路线" value={String(displayRoutes.length || 0)} />
            <MapStat label="通勤" value={formatMeters(mapData?.total_distance_meters || 0)} />
            <MapStat label="耗时" value={formatMinutes(mapData?.total_duration_minutes || 0)} />
          </div>

          <section className="ai-map-poi-list" aria-label="地图地点列表">
            <div className="ai-map-section-head">
              <LocateFixed size={15} />
              <strong>{pointMode === "main" ? "主线 POI" : "原始解析点"}</strong>
            </div>
            {displayPoints.map((point, index) => (
              <article
                className={`ai-map-poi-card ${pointMatchesFocus(point, normalizedFocusName) ? "is-focused" : ""}`}
                key={`${point.name}-${index}`}
                ref={(element) => {
                  poiCardRefs.current[buildPointDomKey(point)] = element;
                }}
              >
                <span>{index + 1}</span>
                <div>
                  <strong>{point.name}</strong>
                  <p>{point.address || point.district || point.city || "地址待确认"}</p>
                  <em>{point.type || point.source || "AI 地点"}</em>
                  {point.group_size && point.group_size > 1 ? (
                    <div className="ai-map-merge-meta">
                      <label>已归并 {point.group_size} 个相邻子点</label>
                      <div className="ai-map-merge-tags">
                        {(point.merged_names || []).slice(0, 4).map((name) => (
                          <span key={name}>{name}</span>
                        ))}
                      </div>
                    </div>
                  ) : null}
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
            {displayRoutes.map((leg) => (
              <article className={`ai-map-route-card ${selectedRouteLeg?.index === leg.index ? "is-focused" : ""}`} key={leg.index}>
                <button type="button" className="ai-map-route-hitbox" onClick={() => setSelectedRouteIndex(leg.index)}>
                  <strong>{leg.origin.name} {"->"} {leg.destination.name}</strong>
                  <span>{formatMeters(leg.distance_meters)} / {formatMinutes(leg.duration_minutes)}</span>
                </button>
                <div className="ai-map-route-actions">
                  <button type="button" className="travel-inline-action subtle" onClick={() => sendLegToAgent(leg)}>
                    <Milestone size={14} />
                    优化这一段
                  </button>
                </div>
              </article>
            ))}
            {!displayRoutes.length && !loading ? <div className="ai-map-empty">地点解析完成后，这里会展示每一段路线的通勤距离与耗时。</div> : null}
          </section>

          {selectedRouteLeg ? (
            <section className="ai-map-step-panel" aria-label="路线步骤详情">
              <div className="ai-map-section-head">
                <Milestone size={15} />
                <strong>步骤详情</strong>
              </div>
              <div className="ai-map-step-head">
                <div>
                  <strong>{selectedRouteLeg.origin.name} {"->"} {selectedRouteLeg.destination.name}</strong>
                  <span>
                    {formatMeters(selectedRouteLeg.distance_meters)} / {formatMinutes(selectedRouteLeg.duration_minutes)} / {selectedRouteLeg.mode_used || selectedRouteLeg.mode || "driving"}
                  </span>
                </div>
                <button type="button" className="travel-inline-action subtle" onClick={() => sendLegToAgent(selectedRouteLeg)}>
                  <SendHorizonal size={14} />
                  回写智能体
                </button>
              </div>
              <div className="ai-map-step-list">
                {(selectedRouteLeg.steps || []).length ? (
                  selectedRouteLeg.steps.slice(0, 10).map((step, index) => (
                    <article className="ai-map-step-item" key={`${selectedRouteLeg.index}-${index}`}>
                      <span>{index + 1}</span>
                      <div>
                        <strong>{step.instruction || step.road || "继续前往下一段"}</strong>
                        <p>
                          {[step.road, step.distance_meters ? formatMeters(step.distance_meters) : "", step.duration_seconds ? formatSeconds(step.duration_seconds) : ""]
                            .filter(Boolean)
                            .join(" / ")}
                        </p>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="ai-map-empty">当前路线没有返回更细的步骤明细。</div>
                )}
              </div>
            </section>
          ) : null}
        </aside>
      </section>
    </div>
  );
}

function FallbackCoordinateMap({ points, focusedName }: { points: AiMapPoint[]; focusedName: string }) {
  return (
    <div className="ai-coordinate-map" aria-label="坐标预览地图">
      {points.map((point, index) => (
        <div
          className={`ai-coordinate-pin ${pointMatchesFocus(point, focusedName) ? "focused" : ""}`}
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

function buildTravelPlanViewPayload(view: TravelPlanView | null) {
  if (!view) return null;
  return {
    overview: {
      title: String(view.overview?.title || "").slice(0, 120),
      summary: String(view.overview?.summary || "").slice(0, 400),
      highlights: (view.overview?.highlights || []).map((item) => String(item || "").slice(0, 80)).filter(Boolean).slice(0, 10),
    },
    map_schedule: view.map_schedule
      ? {
          city: view.map_schedule.city || null,
          title: String(view.map_schedule.title || "").slice(0, 120),
          markers: (view.map_schedule.markers || []).map((marker) => ({
            day: marker.day,
            order: marker.order || null,
            title: String(marker.title || "").slice(0, 80),
            address: String(marker.address || "").slice(0, 160),
            intro: String(marker.intro || "").slice(0, 240),
          })),
        }
      : null,
    days: (view.days || []).map((day) => ({
      day: day.day,
      title: String(day.title || "").slice(0, 120),
      summary: String(day.summary || "").slice(0, 240),
      strategy: String(day.strategy || "").slice(0, 240),
      route_digest: String(day.route_digest || "").slice(0, 240),
      route_points: (day.route_points || []).map((point) => String(point || "").slice(0, 80)).filter(Boolean).slice(0, 12),
      transit_hint: String(day.transit_hint || "").slice(0, 160),
      agenda: [],
      pois: (day.pois || []).map((poi) => ({
        name: String(poi.name || "").slice(0, 80),
        intro: String(poi.intro || "").slice(0, 240),
        category: poi.category || null,
        stay_text: String(poi.stay_text || "").slice(0, 60),
        transport_hint: String(poi.transport_hint || "").slice(0, 120),
        tags: (poi.tags || []).map((tag) => String(tag || "").slice(0, 30)).filter(Boolean).slice(0, 6),
        order: poi.order || null,
      })),
    })),
    action_hints: (view.action_hints || []).map((item) => String(item || "").slice(0, 120)).filter(Boolean).slice(0, 8),
    supplements: [],
    budget: null,
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
    // 中文注释：地图实例销毁失败时不再向上抛错，避免影响页面切换。
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

function formatMinutes(value: number) {
  if (!value) return "0分钟";
  if (value >= 60) {
    const hours = Math.floor(value / 60);
    const minutes = value % 60;
    return minutes ? `${hours}小时${minutes}分钟` : `${hours}小时`;
  }
  return `${value}分钟`;
}

function formatSeconds(value: number) {
  if (!value) return "0分钟";
  return formatMinutes(Math.max(1, Math.round(value / 60)));
}

function escapeHtml(value: string) {
  return value.replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function normalizePointText(value: string) {
  return String(value || "").replace(/\s+/g, "").toLowerCase();
}

function pointMatchesFocus(point: AiMapPoint, normalizedFocusName: string) {
  if (!normalizedFocusName) return false;
  const names = [point.name, point.query, ...(point.merged_names || [])]
    .map((item) => normalizePointText(item || ""))
    .filter(Boolean);
  return names.some((name) => name === normalizedFocusName || name.includes(normalizedFocusName) || normalizedFocusName.includes(name));
}

function buildPointDomKey(point: AiMapPoint) {
  return `${point.day || 0}:${normalizePointText(point.name || point.query || "")}`;
}

function buildRouteDayCards(routes: AiMapRouteLeg[], points: AiMapPoint[]): RouteDayCard[] {
  const grouped = new Map<number, RouteDayCard>();

  points.forEach((point) => {
    if (typeof point.day !== "number") return;
    if (!grouped.has(point.day)) {
      grouped.set(point.day, { day: point.day, points: [], totalDistance: 0, totalDuration: 0, legCount: 0 });
    }
    const bucket = grouped.get(point.day)!;
    if (!bucket.points.includes(point.name)) {
      bucket.points.push(point.name);
    }
  });

  routes.forEach((leg) => {
    const day = typeof leg.origin.day === "number" ? leg.origin.day : leg.destination.day;
    if (typeof day !== "number") return;
    if (!grouped.has(day)) {
      grouped.set(day, { day, points: [], totalDistance: 0, totalDuration: 0, legCount: 0 });
    }
    const bucket = grouped.get(day)!;
    bucket.totalDistance += leg.distance_meters || 0;
    bucket.totalDuration += leg.duration_minutes || 0;
    bucket.legCount += 1;
  });

  return Array.from(grouped.values())
    .sort((left, right) => left.day - right.day)
    .filter((item) => item.points.length || item.legCount);
}

function buildMapCacheKey(
  conversationId: string | undefined,
  city: string | null,
  answer: string,
  itineraryFingerprint: string,
  structuredPlanFingerprint: string,
  travelPlanViewFingerprint: string,
) {
  if (!conversationId && !answer && !itineraryFingerprint && !structuredPlanFingerprint && !travelPlanViewFingerprint) return "";
  return `map:${conversationId || "guest"}:${city || "unknown"}:${hashText(`${travelPlanViewFingerprint}::${structuredPlanFingerprint}::${answer}::${itineraryFingerprint}`)}`;
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
