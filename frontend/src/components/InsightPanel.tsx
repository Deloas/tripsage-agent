import { AlertTriangle, CloudSun, Link2, MapPinned, Route, TrainFront } from "lucide-react";

import type { ChatResponse, GuideSourceItem, RailwayTrain } from "../lib/types";

interface InsightPanelProps {
  latest: ChatResponse | null;
  guideSources: GuideSourceItem[];
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    indexed: "已入库",
    pending: "待处理",
    blocked: "受限",
    failed: "失败",
  };
  return map[status] || status;
}

function statusClass(status: string) {
  // 来源状态与后端 crawl_status 保持一致，便于前后端协同排查。
  if (status === "indexed") return "indexed";
  if (status === "pending") return "pending";
  if (status === "blocked" || status === "failed") return "failed";
  return "neutral";
}

function asTrains(value: unknown): RailwayTrain[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is RailwayTrain => typeof item === "object" && item !== null);
}

function toMinutesFromTime(value?: string) {
  if (!value || !value.includes(":")) return Number.POSITIVE_INFINITY;
  const [hours, minutes] = value.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return Number.POSITIVE_INFINITY;
  return hours * 60 + minutes;
}

function toDurationMinutes(value?: string) {
  if (!value) return Number.POSITIVE_INFINITY;
  const match = value.match(/(?:(\d+)\s*时)?(?:(\d+)\s*分)?/);
  if (!match) return Number.POSITIVE_INFINITY;
  const hours = Number(match[1] || 0);
  const minutes = Number(match[2] || 0);
  return hours * 60 + minutes;
}

function findEarliestTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toMinutesFromTime(left.start_time) - toMinutesFromTime(right.start_time))[0];
}

function findFastestTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toDurationMinutes(left.duration) - toDurationMinutes(right.duration))[0];
}

export function InsightPanel({ latest, guideSources }: InsightPanelProps) {
  const cards = latest?.cards || [];
  const weather = cards.find((card) => card.type === "weather");
  const railway = cards.find((card) => card.type === "railway");
  const destination = cards.find((card) => card.type === "destination");
  const trains = asTrains(railway?.meta?.trains);
  const earliestTrain = findEarliestTrain(trains);
  const fastestTrain = findFastestTrain(trains);
  const routeCall = latest?.tool_calls.find((call) => call.tool_name === "amap_route");
  const indexedCount = guideSources.filter((source) => source.crawl_status === "indexed").length;
  const pendingCount = guideSources.filter((source) => source.crawl_status === "pending").length;

  return (
    <aside className="insight-panel" aria-label="工具与来源洞察">
      <div className="rail-visual-card insight-visual">
        <span>中国高铁旅行视角</span>
        <strong>{destination?.title || "目的地待确认"}</strong>
        <em>{trains.length ? `${trains.length} 条铁路候选已进入主工作台` : "等待智能体调度铁路结果"}</em>
      </div>

      <section className="insight-summary" aria-label="实时洞察摘要">
        <div>
          <strong>{latest?.tool_calls.length || 0}</strong>
          <span>工具调用</span>
        </div>
        <div>
          <strong>{latest?.sources.length || 0}</strong>
          <span>引用来源</span>
        </div>
        <div>
          <strong>{latest?.warnings.length || 0}</strong>
          <span>风险提醒</span>
        </div>
      </section>

      <section className="insight-section">
        <div className="section-kicker">
          <CloudSun size={16} />
          天气
        </div>
        <div className="metric-card">
          <strong>{weather?.summary || "等待查询"}</strong>
          <span>{latest?.warnings.find((item) => item.includes("天气")) || "实时结果会在这里出现"}</span>
        </div>
      </section>

      <section className="insight-section">
        <div className="section-kicker">
          <TrainFront size={16} />
          铁路摘要
        </div>
        <div className="metric-card rail">
          <strong>{railway?.summary || "等待查询"}</strong>
          <span>
            {railway?.meta?.date ? `${railway.meta.date} / ` : ""}
            完整车次列表已放到中间主工作台，可滚动查看全部结果。
          </span>
        </div>
        <div className="rail-quick-stats">
          <div>
            <span>候选车次</span>
            <strong>{trains.length || 0}</strong>
          </div>
          <div>
            <span>最早出发</span>
            <strong>{earliestTrain?.start_time || "--:--"}</strong>
          </div>
          <div>
            <span>最快耗时</span>
            <strong>{fastestTrain?.duration || "--"}</strong>
          </div>
        </div>
      </section>

      <section className="insight-section">
        <div className="section-kicker">
          <MapPinned size={16} />
          地图
        </div>
        <div className="metric-card route">
          <strong>{routeCall?.output_summary || "等待路线估算"}</strong>
          <span>地图工具用于通勤时间和路线判断，真实出行前仍建议复核。</span>
        </div>
      </section>

      {latest?.warnings?.length ? (
        <section className="insight-section">
          <div className="section-kicker">
            <AlertTriangle size={16} />
            注意
          </div>
          <div className="warning-list">
            {latest.warnings.map((warning) => (
              <span key={warning}>{warning}</span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="insight-section">
        <div className="section-kicker">
          <Route size={16} />
          工具链
        </div>
        <div className="tool-trace">
          {(latest?.tool_calls || []).map((call, index) => (
            <div className={`tool-row ${call.status}`} key={`${call.tool_name}-${call.output_summary}-${index}`}>
              <span>{call.tool_name}</span>
              <strong>{call.status}</strong>
              <small>{call.output_summary}</small>
            </div>
          ))}
          {!latest?.tool_calls?.length && <div className="empty-line">等待智能体调度</div>}
        </div>
      </section>

      <section className="insight-section">
        <div className="section-kicker">
          <Link2 size={16} />
          本地来源
        </div>
        <div className="source-stats">
          <div>
            <strong>{guideSources.length}</strong>
            <span>总来源</span>
          </div>
          <div>
            <strong>{indexedCount}</strong>
            <span>已入库</span>
          </div>
          <div>
            <strong>{pendingCount}</strong>
            <span>待处理</span>
          </div>
        </div>
        <div className="local-source-list">
          {guideSources.slice(0, 6).map((source) => (
            <a href={source.source_url || source.raw_url || "#"} target="_blank" rel="noreferrer" key={source.id}>
              <span>{source.title}</span>
              <strong className={statusClass(source.crawl_status)}>{statusLabel(source.crawl_status)}</strong>
            </a>
          ))}
          {!guideSources.length && <div className="empty-line">还没有本地来源，添加或采集攻略后会显示在这里</div>}
        </div>
      </section>

      <section className="insight-section">
        <div className="section-kicker">
          <Link2 size={16} />
          引用来源
        </div>
        <div className="source-list">
          {(latest?.sources || []).map((source) => (
            <a
              className={source.source_type === "web_search" ? "web-source" : "local-source"}
              href={source.url || "#"}
              target="_blank"
              rel="noreferrer"
              key={`${source.title}-${source.url}`}
            >
              <span>{source.title}</span>
              <strong>{source.source_type === "web_search" ? "联网" : "本地"}</strong>
            </a>
          ))}
          {!latest?.sources?.length && <div className="empty-line">暂无引用</div>}
        </div>
      </section>
    </aside>
  );
}
