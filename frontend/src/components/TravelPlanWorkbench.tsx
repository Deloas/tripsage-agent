import {
  BadgeDollarSign,
  CheckCircle2,
  CloudRain,
  Compass,
  Gauge,
  MapPinned,
  Route,
  ShieldAlert,
  Sparkles,
  Target,
  TrainFront,
  Utensils,
  WalletCards,
} from "lucide-react";

import type { RenderPlan, TravelPlanSupplement, TravelPlanView } from "../lib/types";

type MapActionPayload = {
  day?: number;
  pointName?: string | null;
};

type RailwayActionPayload = {
  destination?: string | null;
  date?: string | null;
  hint?: string | null;
};

interface TravelPlanWorkbenchProps {
  view: TravelPlanView;
  renderPlan?: RenderPlan | null;
  onOpenMap?: (payload: MapActionPayload) => void;
  onOpenRailway?: (payload: RailwayActionPayload) => void;
}

function supplementIcon(title: string) {
  if (title.includes("雨") || title.includes("天气")) return CloudRain;
  if (title.includes("交通") || title.includes("铁路")) return TrainFront;
  return Sparkles;
}

function supplementToneClass(tone?: string) {
  if (tone === "warn") return "warn";
  if (tone === "good") return "good";
  return "info";
}

function markerDigest(view: TravelPlanView) {
  const markers = view.map_schedule?.markers || [];
  const countByDay = new Map<number, number>();
  markers.forEach((marker) => {
    countByDay.set(marker.day, (countByDay.get(marker.day) || 0) + 1);
  });
  return Array.from(countByDay.entries())
    .map(([day, count]) => `Day ${day} · ${count} 个地点`)
    .join(" / ");
}

function inferRailwayDate(view: TravelPlanView, renderPlan?: RenderPlan | null) {
  const joined = [
    view.overview.summary,
    ...view.days.flatMap((day) => [day.summary, day.strategy, day.route_digest]),
    ...(renderPlan?.days.flatMap((day) => [day.summary, day.route_reason]) || []),
    ...(renderPlan?.closing_tips || []),
    ...view.action_hints,
  ]
    .join(" ")
    .trim();
  const matched = joined.match(/\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日|五一|十一|国庆|端午|中秋|周末/);
  return matched?.[0] || null;
}

function compactItems(items: Array<string | undefined | null>) {
  return items.map((item) => String(item || "").trim()).filter(Boolean);
}

function findGuideDay(renderPlan: RenderPlan | null | undefined, day: number) {
  return renderPlan?.days.find((item) => item.day === day) || null;
}

export function TravelPlanWorkbench({
  view,
  renderPlan,
  onOpenMap,
  onOpenRailway,
}: TravelPlanWorkbenchProps) {
  const markerSummary = markerDigest(view);
  const destination = view.map_schedule?.city || view.overview.title || null;
  const railwayDate = inferRailwayDate(view, renderPlan);
  const guideOverview = renderPlan?.overview || null;
  const guideClosingTips = renderPlan?.closing_tips || [];

  return (
    <section className="travel-plan-workbench" aria-label="本轮旅行规划结果">
      <header className="travel-plan-hero">
        <div className="travel-plan-hero-copy">
          <div className="section-kicker">
            <Sparkles size={15} />
            旅行方案
          </div>
          <h3>{guideOverview?.title || view.overview.title}</h3>
          <p>{guideOverview?.summary || view.overview.summary}</p>
          <div className="travel-plan-command-row">
            <button
              type="button"
              className="travel-plan-command primary"
              onClick={() => onOpenMap?.({ day: undefined, pointName: null })}
              disabled={!onOpenMap}
            >
              <MapPinned size={15} />
              查看总路线
            </button>
            <button
              type="button"
              className="travel-plan-command"
              onClick={() => onOpenRailway?.({ destination, date: railwayDate, hint: guideOverview?.summary || view.overview.summary })}
              disabled={!onOpenRailway}
            >
              <TrainFront size={15} />
              带入铁路工作台
            </button>
          </div>
        </div>

        <div className="travel-plan-hero-stats">
          <article>
            <Route size={15} />
            <strong>{view.days.length}</strong>
            <span>行程天数</span>
          </article>
          <article>
            <MapPinned size={15} />
            <strong>{view.map_schedule?.markers.length || 0}</strong>
            <span>地图节点</span>
          </article>
          <article>
            <BadgeDollarSign size={15} />
            <strong>{view.budget?.total_hint || "待补充"}</strong>
            <span>预算范围</span>
          </article>
        </div>
      </header>

      {(guideOverview?.best_for?.length || view.overview.highlights.length) ? (
        <div className="travel-plan-highlight-row">
          {(guideOverview?.best_for?.length ? guideOverview.best_for : view.overview.highlights).map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}

      <div className="travel-plan-grid">
        <section className="travel-plan-main-band">
          {guideOverview ? (
            <article className="travel-day-card travel-reading-overview">
              <div className="travel-day-head">
                <div className="travel-day-badge">GUIDE</div>
                <div className="travel-day-head-copy">
                  <h4>{guideOverview.positioning || "行程定位"}</h4>
                  <p>{guideOverview.route_strategy || guideOverview.summary}</p>
                </div>
              </div>
              {guideClosingTips.length ? (
                <div className="travel-route-strip">
                  {guideClosingTips.map((tip) => (
                    <button type="button" key={tip} disabled>
                      {tip}
                    </button>
                  ))}
                </div>
              ) : null}
            </article>
          ) : null}

          {view.days.map((day) => {
            const guideDay = findGuideDay(renderPlan, day.day);
            const guideBlocks = guideDay?.blocks || [];
            return (
              <article className="travel-day-card" key={day.day}>
                <div className="travel-day-head">
                  <div className="travel-day-badge">DAY {day.day}</div>
                  <div className="travel-day-head-copy">
                    <h4>{day.title}</h4>
                    <p>{guideDay?.summary || day.strategy || day.summary}</p>
                  </div>
                  <div className="travel-day-actions">
                    <button type="button" className="travel-inline-action" onClick={() => onOpenMap?.({ day: day.day })}>
                      <MapPinned size={14} />
                      查看 Day 地图
                    </button>
                  </div>
                </div>

                {day.route_points.length ? (
                  <div className="travel-route-strip">
                    {day.route_points.map((point) => (
                      <button
                        type="button"
                        key={`${day.day}-${point}`}
                        onClick={() => onOpenMap?.({ day: day.day, pointName: point })}
                        disabled={!onOpenMap}
                      >
                        {point}
                      </button>
                    ))}
                  </div>
                ) : null}

                {day.transit_hint ? (
                  <div className="travel-inline-note">
                    <TrainFront size={14} />
                    <span>{day.transit_hint}</span>
                  </div>
                ) : null}

                <div className="travel-day-intel-grid" aria-label={`Day ${day.day} 决策信息`}>
                  <article>
                    <div>
                      <Utensils size={14} />
                      <strong>美食</strong>
                    </div>
                    <p>
                      {guideDay?.food_story ||
                        compactItems([
                          day.food_plan?.lunch,
                          day.food_plan?.dinner,
                          ...(day.food_plan?.recommendations || []).slice(0, 2),
                        ]).join(" / ") ||
                        "结合当天路线就近安排本地餐饮。"}
                    </p>
                  </article>
                  <article>
                    <div>
                      <TrainFront size={14} />
                      <strong>交通</strong>
                    </div>
                    <p>
                      {day.transport_plan?.city_transport ||
                        day.transport_plan?.segments?.[0]?.hint ||
                        day.transit_hint ||
                        "以地图工作台实时路线为准。"}
                    </p>
                  </article>
                  <article>
                    <div>
                      <WalletCards size={14} />
                      <strong>预算</strong>
                    </div>
                    <p>{day.budget_plan?.summary || "待结合住宿、门票与餐饮继续细化。"}</p>
                  </article>
                  <article>
                    <div>
                      <Gauge size={14} />
                      <strong>强度</strong>
                    </div>
                    <p>{guideDay?.positioning || day.pace_level || "适中"}</p>
                  </article>
                  <article>
                    <div>
                      <CloudRain size={14} />
                      <strong>雨天备选</strong>
                    </div>
                    <p>{guideDay?.fallback_plan || (day.weather_backup || []).slice(0, 2).join(" / ") || "优先切换室内馆区或商圈。"}</p>
                  </article>
                  <article>
                    <div>
                      <ShieldAlert size={14} />
                      <strong>风险提醒</strong>
                    </div>
                    <p>{guideDay?.avoidance_tip || guideDay?.reservation_tip || (day.risk_notes || []).slice(0, 2).join(" / ") || "提前预约并错峰出行。"}</p>
                  </article>
                </div>

                <div className="travel-map-health">
                  <CheckCircle2 size={14} />
                  <span>{day.map_completeness || `地图节点 ${day.map_node_count || day.route_points.length} 个`}</span>
                </div>

                {day.transport_plan?.segments?.length ? (
                  <div className="travel-segment-strip" aria-label={`Day ${day.day} 地图交通段`}>
                    {day.transport_plan.segments.slice(0, 8).map((segment, index) => {
                      const origin = segment.origin || day.route_points[index] || "";
                      const destinationPoint = segment.destination || day.route_points[index + 1] || "";
                      return (
                        <button
                          type="button"
                          key={`${day.day}-${origin}-${destinationPoint}-${index}`}
                          onClick={() => onOpenMap?.({ day: day.day, pointName: destinationPoint || origin })}
                          disabled={!onOpenMap || (!origin && !destinationPoint)}
                        >
                          <Route size={13} />
                          <span>{origin && destinationPoint ? `${origin} -> ${destinationPoint}` : origin || destinationPoint}</span>
                          {segment.mode ? <em>{segment.mode}</em> : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}

                <div className="travel-day-layout">
                  {guideBlocks.length ? (
                    <div className="travel-agenda-column travel-reading-column">
                      <strong>攻略正文</strong>
                      <div className="travel-reading-list">
                        {guideBlocks.map((block, index) => (
                          <article className="travel-reading-card" key={`${day.day}-${block.title}-${index}`}>
                            <div className="travel-reading-topline">
                              <span>{block.period || `时段 ${index + 1}`}</span>
                              <b>{block.title}</b>
                            </div>
                            <p>{block.description}</p>
                            <div className="travel-reading-meta">
                              {block.why_here ? <em>{block.why_here}</em> : null}
                              {block.transport_hint ? <span>{block.transport_hint}</span> : null}
                              {block.food_hint ? <span>{block.food_hint}</span> : null}
                            </div>
                          </article>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="travel-agenda-column">
                    <strong>当天日程</strong>
                    <div className="travel-agenda-list">
                      {day.agenda.map((item, index) => (
                        <div className="travel-agenda-item" key={`${day.day}-${item.title}-${index}`}>
                          <span>{item.time || "弹性时段"}</span>
                          <div>
                            <b>{item.title}</b>
                            <p>{item.detail}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="travel-poi-column">
                    <strong>地点卡片</strong>
                    <div className="travel-poi-list">
                      {day.pois.map((poi) => (
                        <article className="travel-poi-card" key={`${day.day}-${poi.name}`}>
                          <div className="travel-poi-topline">
                            <div>
                              <b>{poi.name}</b>
                              <div className="travel-poi-tags">
                                {poi.tags.map((tag) => (
                                  <span key={`${poi.name}-${tag}`}>{tag}</span>
                                ))}
                              </div>
                            </div>
                            <button
                              type="button"
                              className="travel-inline-action subtle"
                              onClick={() => onOpenMap?.({ day: day.day, pointName: poi.name })}
                            >
                              <Target size={14} />
                              定位
                            </button>
                          </div>
                          <p>{poi.intro}</p>
                          {poi.transport_hint ? <em>{poi.transport_hint}</em> : null}
                        </article>
                      ))}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </section>

        <aside className="travel-plan-side-band">
          <section className="travel-side-card emphasis">
            <div className="travel-side-title">
              <MapPinned size={15} />
              <strong>地图主线</strong>
            </div>
            <p>{view.map_schedule?.title || "待生成地图主线"}</p>
            <span>{markerSummary || "地图工作台会根据结构化地点串联总路线和分日路线。"}</span>
            <div className="travel-side-actions">
              <button type="button" className="travel-inline-action" onClick={() => onOpenMap?.({})}>
                <Compass size={14} />
                打开地图
              </button>
            </div>
          </section>

          {view.budget ? (
            <section className="travel-side-card budget">
              <div className="travel-side-title">
                <BadgeDollarSign size={15} />
                <strong>预算提示</strong>
              </div>
              <p>{view.budget.summary}</p>
              <div className="travel-budget-list">
                {view.budget.items.map((item) => (
                  <div className="travel-budget-item" key={item.name}>
                    <div>
                      <b>{item.name}</b>
                      <span>{item.note}</span>
                    </div>
                    <strong>{item.amount}</strong>
                    <i style={{ width: `${Math.max(12, Math.round((item.ratio || 0.18) * 100))}%` }} />
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {view.action_hints.length ? (
            <section className="travel-side-card">
              <div className="travel-side-title">
                <Route size={15} />
                <strong>下一步动作</strong>
              </div>
              <ul className="travel-action-list">
                {view.action_hints.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>

      {view.supplements.length ? (
        <section className="travel-supplement-grid" aria-label="补充信息">
          {view.supplements.map((item) => (
            <SupplementCard item={item} key={`${item.title}-${item.summary}`} />
          ))}
        </section>
      ) : null}
    </section>
  );
}

function SupplementCard({ item }: { item: TravelPlanSupplement }) {
  const Icon = supplementIcon(item.title);
  return (
    <article className={`travel-supplement-card ${supplementToneClass(item.tone)}`}>
      <div className="travel-side-title">
        <Icon size={15} />
        <strong>{item.title}</strong>
      </div>
      <p>{item.summary}</p>
      <ul>
        {item.bullets.map((bullet) => (
          <li key={bullet}>{bullet}</li>
        ))}
      </ul>
    </article>
  );
}
