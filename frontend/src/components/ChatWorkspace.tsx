import {
  AlertTriangle,
  BadgeDollarSign,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CloudRain,
  Clock3,
  DatabaseZap,
  Download,
  Filter,
  GaugeCircle,
  GitBranch,
  GitCompareArrows,
  Layers3,
  Link2,
  ListChecks,
  LogIn,
  MapPinned,
  PencilLine,
  Plus,
  RefreshCw,
  SendHorizonal,
  ShieldAlert,
  ShieldCheck,
  Star,
  TrainFront,
  WandSparkles,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type {
  ChatResponse,
  DecisionModule,
  ItineraryBlock,
  PlanVersion,
  PlanVersionCompare,
  RailwayTrain,
  StreamStage,
} from "../lib/types";

interface ChatWorkspaceProps {
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  latest: ChatResponse | null;
  loading: boolean;
  guestMode: boolean;
  guestCarryoverReady: boolean;
  searchMode: "local_only" | "web_enhanced" | "auto";
  streamStages: StreamStage[];
  planVersions: PlanVersion[];
  activeVersionId: string | null;
  versionCompare: PlanVersionCompare | null;
  shareUrl: string | null;
  canShareVersion: boolean;
  decisionModuleStates: Record<string, "accepted" | "ignored">;
  onOpenUserCenter: () => void;
  onSubmit: (message: string) => void;
  onOptimizeItinerary: (editedPlan: Record<string, unknown>) => void;
  onDecisionModuleAction: (module: DecisionModule, action: "accept" | "ignore" | "regenerate") => void;
  onVersionSelect: (versionId: string) => void;
  onExportVersion: (versionId: string, format: "markdown" | "html") => void;
  onShareVersion: (versionId: string) => void;
}

type RailwaySortMode = "recommended" | "earliest" | "fastest";
type TrainTypeFilter = "all" | "high_speed" | "normal";
type SeatFilter = "all" | "available";
type PrimaryWorkbenchTab = "messages" | "itinerary" | "decision";
type SecondaryWorkbenchTab = "railway" | "versions";

const modeLabel: Record<ChatWorkspaceProps["searchMode"], string> = {
  auto: "自动检索",
  local_only: "仅攻略库",
  web_enhanced: "联网增强",
};

const moduleIcons: Record<string, typeof TrainFront> = {
  transport: TrainFront,
  rainy_day: CloudRain,
  intensity: GaugeCircle,
  budget: BadgeDollarSign,
  risk: ShieldAlert,
};

function buildDecisionModuleKey(module: DecisionModule) {
  return `${module.type}::${module.title}`;
}

function getDecisionStateLabel(state?: "accepted" | "ignored") {
  if (state === "accepted") return "已采纳";
  if (state === "ignored") return "已忽略";
  return "待处理";
}

function asTrains(value: unknown): RailwayTrain[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is RailwayTrain => typeof item === "object" && item !== null);
}

function seatSummary(train: RailwayTrain) {
  const seats = train.seats || {};
  const preferred: Array<[string, string]> = [
    ["second_class", "二等"],
    ["first_class", "一等"],
    ["business_class", "商务"],
    ["hard_seat", "硬座"],
    ["no_seat", "无座"],
  ];
  const parts = preferred
    .map(([key, label]) => (seats[key] ? `${label}${seats[key]}` : null))
    .filter(Boolean);
  return parts.slice(0, 3).join(" / ") || "余票请以 12306 为准";
}

function toMinutesFromTime(value?: string) {
  if (!value || !value.includes(":")) return Number.POSITIVE_INFINITY;
  const [hours, minutes] = value.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return Number.POSITIVE_INFINITY;
  return hours * 60 + minutes;
}

function toDurationMinutes(value?: string) {
  if (!value) return Number.POSITIVE_INFINITY;
  const match = value.match(/(?:(\d+)\s*小时)?(?:(\d+)\s*分)?/);
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

export function ChatWorkspace({
  messages,
  latest,
  loading,
  guestMode,
  guestCarryoverReady,
  searchMode,
  streamStages,
  planVersions,
  activeVersionId,
  versionCompare,
  shareUrl,
  canShareVersion,
  decisionModuleStates,
  onOpenUserCenter,
  onSubmit,
  onOptimizeItinerary,
  onDecisionModuleAction,
  onVersionSelect,
  onExportVersion,
  onShareVersion,
}: ChatWorkspaceProps) {
  const [value, setValue] = useState("");
  const [railwayExpanded, setRailwayExpanded] = useState(false);
  const [railwaySortMode, setRailwaySortMode] = useState<RailwaySortMode>("recommended");
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [primaryTab, setPrimaryTab] = useState<PrimaryWorkbenchTab>("messages");
  const [secondaryTab, setSecondaryTab] = useState<SecondaryWorkbenchTab>("railway");

  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLFormElement | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);

  const cards = latest?.cards || [];
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || null;
  const toolCount = latest?.tool_calls?.length || 0;
  const sourceCount = latest?.sources?.length || 0;
  const dayCount = latest?.itinerary?.length || 0;
  const railwayCard = cards.find((card) => card.type === "railway") || null;
  const railwayTrains = useMemo(() => asTrains(railwayCard?.meta?.trains), [railwayCard]);
  const sortedRailwayTrains = useMemo(() => {
    if (railwaySortMode === "earliest") {
      return [...railwayTrains].sort((left, right) => toMinutesFromTime(left.start_time) - toMinutesFromTime(right.start_time));
    }
    if (railwaySortMode === "fastest") {
      return [...railwayTrains].sort((left, right) => toDurationMinutes(left.duration) - toDurationMinutes(right.duration));
    }
    return railwayTrains;
  }, [railwaySortMode, railwayTrains]);
  const earliestTrain = useMemo(() => findEarliestTrain(railwayTrains), [railwayTrains]);
  const fastestTrain = useMemo(() => findFastestTrain(railwayTrains), [railwayTrains]);
  const digestCards = cards.filter((card) => card.type !== "railway").slice(0, 4);

  function submitCurrent() {
    const text = value.trim();
    if (!text || loading) return;
    setValue("");
    onSubmit(text);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submitCurrent();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 中文输入保留换行，仅在快捷键触发时发送。
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submitCurrent();
    }
  }

  function scrollToLatest() {
    setPrimaryTab("messages");
    window.requestAnimationFrame(() => {
      const element = messageScrollRef.current;
      if (!element) return;
      element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    });
  }

  function scrollToTop() {
    setPrimaryTab("messages");
    window.requestAnimationFrame(() => {
      messageScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function scrollToComposer() {
    composerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    composerRef.current?.querySelector("textarea")?.focus();
  }

  useEffect(() => {
    if (primaryTab !== "messages") return;
    const element = messageScrollRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, [messages.length, loading, primaryTab]);

  useEffect(() => {
    const element = messageScrollRef.current;
    if (!element) return;

    const handleScroll = () => {
      const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
      setShowJumpToLatest(distanceToBottom > 220);
    };

    handleScroll();
    element.addEventListener("scroll", handleScroll);
    return () => element.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (!railwayCard && planVersions.length) {
      setSecondaryTab("versions");
      return;
    }
    if (railwayCard) {
      setSecondaryTab((current) => (current === "versions" && !planVersions.length ? "railway" : current));
    }
  }, [planVersions.length, railwayCard]);

  return (
    <main className="chat-workspace tripsage-workbench">
      <section className="workspace-top-strip" aria-label="旅行决策工作台概览">
        <div className="workspace-top-copy">
          <div className="section-kicker">
            <WandSparkles size={16} />
            智能体工作台
          </div>
          <h1>对话、车次与证据</h1>
        </div>

        <div className="workspace-top-actions">
          <div className="header-chips">
            <span className="intent-chip">{latest?.intent || "ready"}</span>
            <span className="mode-chip">{modeLabel[searchMode]}</span>
          </div>
          <div className="workspace-anchor-actions">
            <button type="button" className="dock-button" onClick={scrollToTop}>
              <ChevronUp size={14} />
              对话顶部
            </button>
            <button type="button" className="dock-button" onClick={scrollToLatest}>
              <ChevronDown size={14} />
              最新消息
            </button>
            <button type="button" className="dock-button strong" onClick={scrollToComposer}>
              <SendHorizonal size={14} />
              立即提问
            </button>
          </div>
        </div>

        <div className="workspace-metrics-grid">
          <MetricBlock icon={Layers3} label="方案版本" value={String(planVersions.length)} />
          <MetricBlock icon={DatabaseZap} label="引用来源" value={String(sourceCount)} />
          <MetricBlock icon={TrainFront} label="工具调用" value={String(toolCount)} />
          <MetricBlock icon={MapPinned} label="行程天数" value={dayCount ? `${dayCount} 天` : "待生成"} />
        </div>

        <div className="workspace-session-banner">
          <div>
            <span>当前方案</span>
            <strong>{activeVersion?.name || "尚未生成"}</strong>
            <p>
              {guestMode
                ? "游客模式下不会保存历史与偏好画像，登录后可把当前规划写入历史中心。"
                : activeVersion?.reason || "开始提问后，这里会持续记录当前版本的生成理由。"}
            </p>
          </div>
          {guestMode && guestCarryoverReady ? (
            <button type="button" className="secondary-action" onClick={onOpenUserCenter}>
              <LogIn size={15} />
              登录保存本次方案
            </button>
          ) : (
            <div className="workspace-session-note">
              <ShieldCheck size={15} />
              <span>{guestMode ? "当前为游客会话" : "已启用历史与版本管理"}</span>
            </div>
          )}
        </div>

        <section className="top-stage-strip" aria-label="实时调度">
          <div className="top-stage-head">
            <ListChecks size={15} />
            <strong>实时调度</strong>
          </div>
          {(loading || streamStages.length > 0) ? (
            <div className="top-stage-list">
              {streamStages.slice(0, 6).map((stage) => (
                <div className={`top-stage-item ${stage.status}`} key={stage.name}>
                  <span />
                  <strong>{stage.label}</strong>
                  <em>{stage.summary || (stage.status === "running" ? "执行中" : "完成")}</em>
                </div>
              ))}
              {loading && !streamStages.length ? (
                <div className="top-stage-item running">
                  <span />
                  <strong>建立连接</strong>
                  <em>准备调度工具</em>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="top-stage-idle">
              <ShieldCheck size={14} />
              <span>等待新的旅行问题</span>
            </div>
          )}
        </section>
      </section>

      <div className="chat-workspace-main">
        <section className="chat-primary-column">
          <section className="primary-workbench-shell workbench-panel" aria-label="核心旅行决策区">
            <div className="primary-workbench-topbar">
              <div>
                <div className="section-kicker">
                  <ListChecks size={16} />
                  核心工作区
                </div>
                <h2>{primaryTab === "messages" ? "消息主线" : primaryTab === "itinerary" ? "可编辑行程" : "决策模块"}</h2>
              </div>
              <div className="primary-workbench-tabs" role="tablist" aria-label="切换核心工作区">
                <button
                  type="button"
                  className={`primary-tab-button ${primaryTab === "messages" ? "active" : ""}`}
                  onClick={() => setPrimaryTab("messages")}
                  role="tab"
                  aria-selected={primaryTab === "messages"}
                >
                  <ListChecks size={15} />
                  消息
                  <span>{messages.length}</span>
                </button>
                <button
                  type="button"
                  className={`primary-tab-button ${primaryTab === "itinerary" ? "active" : ""}`}
                  onClick={() => setPrimaryTab("itinerary")}
                  role="tab"
                  aria-selected={primaryTab === "itinerary"}
                >
                  <PencilLine size={15} />
                  行程
                  <span>{dayCount || 0}</span>
                </button>
                <button
                  type="button"
                  className={`primary-tab-button ${primaryTab === "decision" ? "active" : ""}`}
                  onClick={() => setPrimaryTab("decision")}
                  role="tab"
                  aria-selected={primaryTab === "decision"}
                >
                  <WandSparkles size={15} />
                  决策
                  <span>{latest?.decision_modules?.length || 0}</span>
                </button>
              </div>
            </div>

              <div className="primary-tab-panel">
              {primaryTab === "messages" ? (
                <section
                  className={`message-stream-shell ${latest?.warnings?.length ? "has-warnings" : "no-warnings"}`}
                  aria-label="对话与规划过程"
                >
                  <div className="message-stream-head">
                    <div>
                      <div className="section-kicker">
                        <ListChecks size={16} />
                        对话主线
                      </div>
                      <h2>输入固定在底部，消息区独立滚动</h2>
                    </div>
                    <div className="message-stream-meta">
                      <span>{messages.length} 条消息</span>
                      {showJumpToLatest ? (
                        <button type="button" className="dock-button" onClick={scrollToLatest}>
                          <ChevronDown size={14} />
                          回到底部
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {latest?.warnings?.length ? (
                    <section className="warning-strip" aria-label="风险提示">
                      <AlertTriangle size={16} />
                      <div>
                        {latest.warnings.map((warning) => (
                          <span key={warning}>{warning}</span>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  <div className="message-scroll-panel" ref={messageScrollRef}>
                    <div className="message-stream">
                      {!cards.length && !loading ? (
                        <section className="empty-workbench in-stream" aria-label="启动提示">
                          <ShieldCheck size={18} />
                          <span>输入出发地、目的地、日期、预算或偏好，工作台会先检索，再给出可执行方案。</span>
                        </section>
                      ) : null}

                      {messages.map((message, index) => (
                        <article className={`message-block ${message.role}`} key={`${message.role}-${index}`}>
                          <div className="message-role">{message.role === "user" ? "你" : "TripSage"}</div>
                          {message.role === "assistant" ? <AnswerRenderer content={message.content} /> : <p>{message.content}</p>}
                        </article>
                      ))}
                      {loading ? (
                        <article className="message-block assistant loading-block">
                          <div className="message-role">TripSage</div>
                          <p>正在调度攻略库、铁路、天气和地图工具...</p>
                        </article>
                      ) : null}
                      <div ref={messageEndRef} />
                    </div>
                  </div>
                </section>
              ) : null}

              {primaryTab === "itinerary" ? (
                latest?.itinerary ? (
                  <EditableItinerary itinerary={latest.itinerary} loading={loading} onOptimize={onOptimizeItinerary} />
                ) : (
                  <PrimaryEmptyState
                    icon={PencilLine}
                    title="还没有可编辑行程"
                    description="先在消息里提出旅行需求，生成方案后可以在这里调整每天的景点、交通和预算，再交给智能体二次优化。"
                  />
                )
              ) : null}

              {primaryTab === "decision" ? (
                latest?.decision_modules?.length ? (
                  <ActionableDecisionWorkbench
                    modules={latest.decision_modules}
                    loading={loading}
                    states={decisionModuleStates}
                    onAction={onDecisionModuleAction}
                  />
                ) : (
                  <PrimaryEmptyState
                    icon={WandSparkles}
                    title="决策模块等待生成"
                    description="当方案生成后，交通建议、雨天备选、行程强度、预算提示和风险提醒会集中放在这里，不再挤占对话空间。"
                  />
                )
              ) : null}
            </div>
          </section>
        </section>

        <aside className="chat-secondary-column" aria-label="结构化结果与铁路结果">
          <section className="secondary-workbench-shell workbench-panel" aria-label="右侧工作台">
            <div className="secondary-workbench-topbar">
              <div>
                <div className="section-kicker">
                  <DatabaseZap size={16} />
                  证据与比选
                </div>
                <h2>{secondaryTab === "railway" ? "铁路比选" : "版本回看"}</h2>
              </div>
              <div className="secondary-workbench-tabs" role="tablist" aria-label="切换右侧工作台">
                <button
                  type="button"
                  className={`secondary-tab-button ${secondaryTab === "railway" ? "active" : ""}`}
                  onClick={() => setSecondaryTab("railway")}
                  role="tab"
                  aria-selected={secondaryTab === "railway"}
                  disabled={!railwayCard}
                >
                  <TrainFront size={15} />
                  车次
                  <span>{railwayTrains.length}</span>
                </button>
                <button
                  type="button"
                  className={`secondary-tab-button ${secondaryTab === "versions" ? "active" : ""}`}
                  onClick={() => setSecondaryTab("versions")}
                  role="tab"
                  aria-selected={secondaryTab === "versions"}
                  disabled={!planVersions.length}
                >
                  <GitBranch size={15} />
                  版本
                  <span>{planVersions.length}</span>
                </button>
              </div>
            </div>

            {digestCards.length ? (
              <div className="secondary-summary-strip" aria-label="调度摘要">
                {digestCards.map((card) => (
                  <article className={`secondary-summary-card ${card.type}`} key={`${card.type}-${card.title}`}>
                    <DatabaseZap size={14} />
                    <div>
                      <span>{card.title}</span>
                      <strong>{card.summary}</strong>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="secondary-workbench-empty compact">铁路、天气、路线和引用证据会在这里汇总。</div>
            )}

            <div className="secondary-tab-panel">
              {secondaryTab === "railway" ? (
                railwayCard ? (
                  <RailwayWorkbench
                    railwayCard={railwayCard}
                    trains={sortedRailwayTrains}
                    totalTrains={railwayTrains.length}
                    earliestTrain={earliestTrain}
                    fastestTrain={fastestTrain}
                    expanded={railwayExpanded}
                    sortMode={railwaySortMode}
                    onSortChange={setRailwaySortMode}
                    onToggleExpanded={() => setRailwayExpanded((current) => !current)}
                    onUseTrain={(train) => onSubmit(buildTrainAdoptionPrompt(train))}
                  />
                ) : (
                  <div className="secondary-workbench-empty">当前还没有可比较车次，触发铁路查询后会在这里连续展示。</div>
                )
              ) : null}

              {secondaryTab === "versions" ? (
                planVersions.length ? (
                  <PlanVersionRail
                    versions={planVersions}
                    activeVersionId={activeVersionId}
                    compare={versionCompare}
                    shareUrl={shareUrl}
                    canShareVersion={canShareVersion}
                    guestMode={guestMode}
                    onRequireLogin={onOpenUserCenter}
                    onSelect={onVersionSelect}
                    onExport={onExportVersion}
                    onShare={onShareVersion}
                  />
                ) : (
                  <div className="secondary-workbench-empty">方案生成后，每一次决策产物都会在这里沉淀成版本记录。</div>
                )
              ) : null}
            </div>
          </section>
        </aside>
      </div>

      <form className="composer sticky-composer workspace-bottom-composer" onSubmit={handleSubmit} ref={composerRef}>
        <div className="composer-label">
          <span>Ask TripSage</span>
          <strong>Ctrl + Enter 发送</strong>
        </div>
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="例如：杭州出发，五一去南京两天一夜，优先高铁，预算 1800 元，请给我可执行方案。"
          rows={2}
        />
        <button type="submit" aria-label="发送问题" disabled={loading || !value.trim()} title="发送">
          <SendHorizonal size={19} />
        </button>
      </form>
    </main>
  );
}

function MetricBlock({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Layers3;
  label: string;
  value: string;
}) {
  return (
    <div className="workspace-metric-block">
      <Icon size={17} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function trainKey(train: RailwayTrain, index = 0) {
  return `${train.train_no || "train"}-${train.start_time || "start"}-${train.arrive_time || "arrive"}-${index}`;
}

function isHighSpeedTrain(train: RailwayTrain) {
  return /^[GDC]/i.test(train.train_no || "");
}

function hasAvailableSeat(train: RailwayTrain) {
  const seats = Object.values(train.seats || {});
  if (!seats.length) return false;
  return seats.some((value) => {
    const text = String(value || "").trim();
    return Boolean(text && !["0", "--", "无", "候补", "无票"].includes(text));
  });
}

function trainDecisionTags(train: RailwayTrain, earliestTrain?: RailwayTrain, fastestTrain?: RailwayTrain) {
  const tags: string[] = [];
  if (train.train_no && train.train_no === earliestTrain?.train_no) tags.push("最早出发");
  if (train.train_no && train.train_no === fastestTrain?.train_no) tags.push("耗时最短");
  if (isHighSpeedTrain(train)) tags.push("高铁优先");
  if (hasAvailableSeat(train)) tags.push("余票较稳");
  const start = toMinutesFromTime(train.start_time);
  if (start >= 8 * 60 && start <= 18 * 60) tags.push("时间友好");
  return tags.slice(0, 4);
}

function buildTrainAdoptionPrompt(train: RailwayTrain) {
  const route = `${train.from_station || "出发站"} 到 ${train.to_station || "到达站"}`;
  return [
    `请把 ${train.train_no || "这趟车"} 纳入当前旅行方案继续优化。`,
    `车次信息：${route}，${train.start_time || "--:--"} 出发，${train.arrive_time || "--:--"} 到达，耗时 ${train.duration || "待确认"}。`,
    `座席情况：${seatSummary(train)}。`,
    "请重新评估当天景点顺序、出站后的地图通勤、预算和行程强度，并输出更新后的可执行方案。",
  ].join("\n");
}

function RailwayWorkbench({
  railwayCard,
  trains,
  totalTrains,
  earliestTrain,
  fastestTrain,
  expanded,
  sortMode,
  onSortChange,
  onToggleExpanded,
  onUseTrain,
}: {
  railwayCard: NonNullable<ChatResponse["cards"][number]>;
  trains: RailwayTrain[];
  totalTrains: number;
  earliestTrain?: RailwayTrain;
  fastestTrain?: RailwayTrain;
  expanded: boolean;
  sortMode: RailwaySortMode;
  onSortChange: (mode: RailwaySortMode) => void;
  onToggleExpanded: () => void;
  onUseTrain: (train: RailwayTrain) => void;
}) {
  const dateText = typeof railwayCard.meta?.date === "string" ? railwayCard.meta.date : "日期待确认";
  const [trainTypeFilter, setTrainTypeFilter] = useState<TrainTypeFilter>("all");
  const [seatFilter, setSeatFilter] = useState<SeatFilter>("all");
  const [selectedTrainKey, setSelectedTrainKey] = useState<string | null>(null);
  const [pinnedKeys, setPinnedKeys] = useState<string[]>([]);

  const filteredTrains = useMemo(() => {
    return trains.filter((train) => {
      const typeMatched =
        trainTypeFilter === "all"
        || (trainTypeFilter === "high_speed" && isHighSpeedTrain(train))
        || (trainTypeFilter === "normal" && !isHighSpeedTrain(train));
      const seatMatched = seatFilter === "all" || hasAvailableSeat(train);
      return typeMatched && seatMatched;
    });
  }, [seatFilter, trainTypeFilter, trains]);

  const selectedTrain = useMemo(() => {
    if (!selectedTrainKey) return null;
    return filteredTrains.find((train, index) => trainKey(train, index) === selectedTrainKey) || null;
  }, [filteredTrains, selectedTrainKey]);

  function togglePinned(key: string) {
    setPinnedKeys((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  return (
    <section className="railway-panel workbench-panel" aria-label="铁路结果工作台">
      <div className="railway-panel-head">
        <div>
          <div className="section-kicker">
            <TrainFront size={16} />
            铁路结果
          </div>
          <h2>{railwayCard.summary || "可用车次列表"}</h2>
          <p>完整车次列表放在右侧独立滚动区，20 条结果可以直接连续查看，不再被对话区挤掉。</p>
        </div>
        <div className="railway-panel-meta">
          <span>{totalTrains} 条车次</span>
          <strong>
            {sortMode === "recommended"
              ? "当前按推荐顺序"
              : sortMode === "earliest"
                ? "当前按最早出发"
                : "当前按最短耗时"}
          </strong>
        </div>
      </div>

      <div className="railway-overview-grid">
        <div className="railway-overview-card">
          <span>最早出发</span>
          <strong>{earliestTrain?.start_time || "--:--"}</strong>
          <p>{earliestTrain ? `${earliestTrain.train_no || "车次"} · ${earliestTrain.from_station || "出发"} → ${earliestTrain.to_station || "到达"}` : "等待铁路结果"}</p>
        </div>
        <div className="railway-overview-card">
          <span>最快车程</span>
          <strong>{fastestTrain?.duration || "--"}</strong>
          <p>{fastestTrain ? `${fastestTrain.train_no || "车次"} · ${fastestTrain.start_time || "--:--"} 出发` : "等待铁路结果"}</p>
        </div>
        <div className="railway-overview-card">
          <span>当前日期</span>
          <strong>{dateText}</strong>
          <p>余票、停运和临时变更仍以 12306 官方结果为准。</p>
        </div>
      </div>

      <div className="railway-toolbar">
        <div className="railway-sort-switch" role="tablist" aria-label="铁路排序方式">
          <button type="button" className={sortMode === "recommended" ? "active" : ""} onClick={() => onSortChange("recommended")}>
            推荐顺序
          </button>
          <button type="button" className={sortMode === "earliest" ? "active" : ""} onClick={() => onSortChange("earliest")}>
            最早出发
          </button>
          <button type="button" className={sortMode === "fastest" ? "active" : ""} onClick={() => onSortChange("fastest")}>
            最短耗时
          </button>
        </div>
        <button type="button" className="railway-expand-button" onClick={onToggleExpanded}>
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          {expanded ? "恢复紧凑高度" : `展开全部 ${totalTrains} 条`}
        </button>
      </div>

      <div className="train-decision-controls" aria-label="车次筛选与决策操作">
        <div className="train-filter-group">
          <Filter size={15} />
          <button type="button" className={trainTypeFilter === "all" ? "active" : ""} onClick={() => setTrainTypeFilter("all")}>
            全部
          </button>
          <button type="button" className={trainTypeFilter === "high_speed" ? "active" : ""} onClick={() => setTrainTypeFilter("high_speed")}>
            高铁动车
          </button>
          <button type="button" className={trainTypeFilter === "normal" ? "active" : ""} onClick={() => setTrainTypeFilter("normal")}>
            普速
          </button>
        </div>
        <div className="train-filter-group">
          <CheckCircle2 size={15} />
          <button type="button" className={seatFilter === "all" ? "active" : ""} onClick={() => setSeatFilter("all")}>
            不限余票
          </button>
          <button type="button" className={seatFilter === "available" ? "active" : ""} onClick={() => setSeatFilter("available")}>
            只看有票
          </button>
        </div>
        <div className="train-result-count">
          <strong>{filteredTrains.length}</strong>
          <span>/ {totalTrains} 条可见</span>
        </div>
      </div>

      {selectedTrain ? (
        <div className="selected-train-decision">
          <div>
            <span>已选车次</span>
            <strong>
              {selectedTrain.train_no || "车次"} · {selectedTrain.start_time || "--:--"} 出发 · {selectedTrain.duration || "待确认"}
            </strong>
            <p>{selectedTrain.from_station || "出发站"} → {selectedTrain.to_station || "到达站"}，{seatSummary(selectedTrain)}</p>
          </div>
          <button type="button" className="primary-action" onClick={() => onUseTrain(selectedTrain)}>
            <SendHorizonal size={15} />
            纳入方案
          </button>
        </div>
      ) : null}

      <div className={`railway-list-shell ${expanded ? "expanded" : ""}`}>
        <div className="railway-list">
          {filteredTrains.map((train, index) => {
            const key = trainKey(train, index);
            const tags = trainDecisionTags(train, earliestTrain, fastestTrain);
            const isSelected = selectedTrainKey === key;
            const isPinned = pinnedKeys.includes(key);
            return (
            <article className={`train-card-expanded decision-ready ${isSelected ? "selected" : ""}`} key={key}>
              <div className="train-card-head">
                <div className="train-code-badge">{train.train_no || "车次"}</div>
                <div className="train-route-main">
                  <strong>{train.from_station || "出发站"}</strong>
                  <span>→</span>
                  <strong>{train.to_station || "到达站"}</strong>
                </div>
                <div className="train-duration-pill">{train.duration || "待确认"}</div>
              </div>

              <div className="train-recommendation-row">
                <div className="train-tags">
                  {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>待进一步比较</span>}
                </div>
                <button
                  type="button"
                  className={`train-pin-button ${isPinned ? "active" : ""}`}
                  onClick={() => togglePinned(key)}
                  title={isPinned ? "取消重点关注" : "重点关注"}
                  aria-label={isPinned ? "取消重点关注" : "重点关注"}
                >
                  <Star size={14} />
                </button>
              </div>

              <div className="train-card-grid">
                <div>
                  <span>出发</span>
                  <strong>{train.start_time || "--:--"}</strong>
                </div>
                <div>
                  <span>到达</span>
                  <strong>{train.arrive_time || "--:--"}</strong>
                </div>
                <div>
                  <span>座席</span>
                  <strong>{seatSummary(train)}</strong>
                </div>
              </div>

              <div className="train-card-actions">
                <button type="button" className="secondary-action" onClick={() => setSelectedTrainKey(isSelected ? null : key)}>
                  <CheckCircle2 size={14} />
                  {isSelected ? "取消选择" : "选为候选"}
                </button>
                <button type="button" className="primary-action" onClick={() => onUseTrain(train)}>
                  <SendHorizonal size={14} />
                  加入行程
                </button>
              </div>
            </article>
          );
          })}
          {!filteredTrains.length ? (
            <div className="railway-empty-state">
              <ShieldAlert size={16} />
              <span>当前筛选条件下没有车次，放宽车次类型或余票条件后再查看。</span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ActionableDecisionWorkbench({
  modules,
  loading,
  states,
  onAction,
}: {
  modules: DecisionModule[];
  loading: boolean;
  states: Record<string, "accepted" | "ignored">;
  onAction: (module: DecisionModule, action: "accept" | "ignore" | "regenerate") => void;
}) {
  const acceptedCount = modules.filter((module) => states[buildDecisionModuleKey(module)] === "accepted").length;
  const ignoredCount = modules.filter((module) => states[buildDecisionModuleKey(module)] === "ignored").length;

  return (
    <section className="decision-workbench workbench-panel" aria-label="结构化旅行决策">
      <div className="decision-workbench-head">
        <div>
          <div className="section-kicker">
            <WandSparkles size={16} />
            决策面板
          </div>
          <h3>把建议从“可看”变成“可操作”</h3>
        </div>
        <div className="decision-workbench-stats" aria-label="决策模块处理统计">
          <span>总计 {modules.length}</span>
          <span>已采纳 {acceptedCount}</span>
          <span>已忽略 {ignoredCount}</span>
        </div>
      </div>

      <div className="decision-module-grid">
        {modules.map((module) => {
          const Icon = moduleIcons[module.type] || DatabaseZap;
          const moduleKey = buildDecisionModuleKey(module);
          const state = states[moduleKey];

          return (
            <article
              className={`decision-module ${module.level} ${state ? `is-${state}` : "is-pending"}`}
              key={`${module.type}-${module.title}`}
            >
              <div className="decision-module-head">
                <div className="module-title">
                  <Icon size={17} />
                  <span>{module.title}</span>
                </div>
                <span className={`decision-state-badge ${state ? `is-${state}` : "is-pending"}`}>
                  {getDecisionStateLabel(state)}
                </span>
              </div>

              <strong>{module.summary}</strong>

              <ul>
                {module.points.slice(0, 3).map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>

              <div className="decision-module-actions">
                <button
                  type="button"
                  disabled={loading}
                  className={state === "accepted" ? "active" : ""}
                  onClick={() => onAction(module, "accept")}
                >
                  <CheckCircle2 size={14} />
                  采纳
                </button>
                <button
                  type="button"
                  disabled={loading}
                  className={state === "ignored" ? "active" : ""}
                  onClick={() => onAction(module, "ignore")}
                >
                  <ShieldAlert size={14} />
                  忽略
                </button>
                <button
                  type="button"
                  disabled={loading}
                  className="regenerate"
                  onClick={() => onAction(module, "regenerate")}
                >
                  <RefreshCw size={14} />
                  重生成
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PlanVersionRail({
  versions,
  activeVersionId,
  compare,
  shareUrl,
  canShareVersion,
  guestMode,
  onRequireLogin,
  onSelect,
  onExport,
  onShare,
}: {
  versions: PlanVersion[];
  activeVersionId: string | null;
  compare: PlanVersionCompare | null;
  shareUrl: string | null;
  canShareVersion: boolean;
  guestMode: boolean;
  onRequireLogin: () => void;
  onSelect: (versionId: string) => void;
  onExport: (versionId: string, format: "markdown" | "html") => void;
  onShare: (versionId: string) => void;
}) {
  return (
    <section className="plan-version-rail workbench-panel" aria-label="方案版本管理">
      <div className="version-head">
        <div>
          <div className="section-kicker">
            <GitBranch size={16} />
            方案版本
          </div>
          <h2>保留每一次决策产物，随时回切继续优化</h2>
        </div>
        <div className="version-summary">
          <Layers3 size={15} />
          <span>{versions.length} 个版本</span>
        </div>
      </div>

      <div className="version-track">
        {versions.map((version, index) => {
          const isActive = version.id === activeVersionId;
          const sourceCount = version.response.sources?.length || 0;
          const toolCount = version.response.tool_calls?.length || 0;
          return (
            <button
              type="button"
              className={`version-tab ${isActive ? "active" : ""}`}
              onClick={() => onSelect(version.id)}
              key={version.id}
            >
              <span className="version-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="version-main">
                <strong>{version.name}</strong>
                <em>{version.reason}</em>
              </span>
              <span className="version-meta">
                <span>
                  <Clock3 size={12} />
                  {formatVersionTime(version.createdAt)}
                </span>
                <span>{toolCount} 工具</span>
                <span>{sourceCount} 来源</span>
              </span>
              {isActive ? <small>当前</small> : null}
              {isActive ? (
                <span className="version-actions">
                  <button
                    type="button"
                    title="导出 Markdown"
                    onClick={(event) => {
                      event.stopPropagation();
                      onExport(version.id, "markdown");
                    }}
                  >
                    <Download size={13} />
                    MD
                  </button>
                  <button
                    type="button"
                    title="导出 HTML"
                    onClick={(event) => {
                      event.stopPropagation();
                      onExport(version.id, "html");
                    }}
                  >
                    <Download size={13} />
                    HTML
                  </button>
                  <button
                    type="button"
                    title={canShareVersion ? "创建分享页" : "登录后分享"}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!canShareVersion) {
                        onRequireLogin();
                        return;
                      }
                      onShare(version.id);
                    }}
                  >
                    {canShareVersion ? <Link2 size={13} /> : <LogIn size={13} />}
                    {canShareVersion ? "分享" : "登录后分享"}
                  </button>
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {guestMode ? <div className="version-login-hint">游客模式下版本仅保留在本页，登录后可写入历史中心。</div> : null}

      {shareUrl ? (
        <a className="share-url-strip" href={shareUrl}>
          <Link2 size={15} />
          <span>{shareUrl}</span>
          <strong>已复制</strong>
        </a>
      ) : null}

      {compare ? <VersionComparePanel compare={compare} /> : null}
    </section>
  );
}

function VersionComparePanel({ compare }: { compare: PlanVersionCompare }) {
  const metrics = [
    ["来源", compare.metrics.source_delta],
    ["工具", compare.metrics.tool_delta],
    ["风险", compare.metrics.warning_delta],
    ["天数", compare.metrics.itinerary_day_delta],
    ["模块", compare.metrics.module_delta],
  ];

  return (
    <div className="version-compare-panel" aria-label="方案版本差异">
      <div className="compare-title">
        <GitCompareArrows size={16} />
        <div>
          <strong>{compare.title}</strong>
          <span>{compare.summary}</span>
        </div>
      </div>
      <div className="compare-metrics">
        {metrics.map(([label, value]) => (
          <div className={Number(value) >= 0 ? "positive" : "negative"} key={label}>
            <span>{label}</span>
            <strong>{Number(value) > 0 ? `+${value}` : value}</strong>
          </div>
        ))}
      </div>
      <ul>
        {compare.highlights.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function formatVersionTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function AnswerRenderer({ content }: { content: string }) {
  const blocks = useMemo(
    () => content.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean),
    [content],
  );

  return (
    <div className="answer-renderer">
      {blocks.map((block, index) => {
        if (/^#{1,4}\s+/.test(block)) {
          return <h3 key={index}>{block.replace(/^#{1,4}\s+/, "")}</h3>;
        }
        if (block.startsWith("|") || block.includes("\n|")) {
          return (
            <pre className="answer-table" key={index}>
              {block}
            </pre>
          );
        }
        if (/^[-*]\s+/m.test(block)) {
          return (
            <ul key={index}>
              {block
                .split("\n")
                .map((line) => line.replace(/^[-*]\s+/, "").trim())
                .filter(Boolean)
                .map((line) => (
                  <li key={line}>{line.replace(/\*\*/g, "")}</li>
                ))}
            </ul>
          );
        }
        return <p key={index}>{block.replace(/\*\*/g, "")}</p>;
      })}
    </div>
  );
}

function EditableItinerary({
  itinerary,
  loading,
  onOptimize,
}: {
  itinerary: ItineraryBlock[];
  loading: boolean;
  onOptimize: (editedPlan: Record<string, unknown>) => void;
}) {
  const [draft, setDraft] = useState<ItineraryBlock[]>(itinerary);
  const [editing, setEditing] = useState(false);
  const [transportNote, setTransportNote] = useState("优先高铁与地铁衔接，尽量减少折返。");
  const [budgetNote, setBudgetNote] = useState("控制住宿与交通成本，餐饮保留一定弹性。");

  useEffect(() => {
    setDraft(itinerary);
  }, [itinerary]);

  function updateDayTitle(dayIndex: number, title: string) {
    setDraft((current) => current.map((day, index) => (index === dayIndex ? { ...day, title } : day)));
  }

  function updateItem(dayIndex: number, itemIndex: number, key: "time" | "title" | "detail", value: string) {
    setDraft((current) =>
      current.map((day, index) =>
        index === dayIndex
          ? {
              ...day,
              items: day.items.map((item, innerIndex) =>
                innerIndex === itemIndex ? { ...item, [key]: value } : item,
              ),
            }
          : day,
      ),
    );
  }

  function addItem(dayIndex: number) {
    setDraft((current) =>
      current.map((day, index) =>
        index === dayIndex
          ? {
              ...day,
              items: [...day.items, { time: "弹性", title: "新增安排", detail: "请填写想加入的景点、交通或用餐安排。" }],
            }
          : day,
      ),
    );
  }

  function optimize() {
    onOptimize({
      itinerary: draft,
      transport_note: transportNote,
      budget_note: budgetNote,
      user_goal: "基于用户手动修改后的草稿继续优化交通衔接、雨天备选、预算控制与行程强度。",
    });
    setEditing(false);
  }

  return (
    <section className={`editable-plan ${editing ? "editing" : ""}`} aria-label="可编辑行程方案">
      <div className="editable-plan-header">
        <div>
          <div className="section-kicker">
            <PencilLine size={16} />
            可编辑方案
          </div>
          <h2>你先改，智能体再根据修改后的版本继续二次优化</h2>
        </div>
        <div className="plan-actions">
          <button type="button" className="secondary-action" onClick={() => setEditing((current) => !current)}>
            <PencilLine size={15} />
            {editing ? "预览" : "编辑"}
          </button>
          <button type="button" className="primary-action" disabled={loading} onClick={optimize}>
            <RefreshCw size={15} />
            二次优化
          </button>
        </div>
      </div>

      <div className="plan-notes">
        <label>
          <span>交通偏好</span>
          <input disabled={!editing} value={transportNote} onChange={(event) => setTransportNote(event.target.value)} />
        </label>
        <label>
          <span>预算策略</span>
          <input disabled={!editing} value={budgetNote} onChange={(event) => setBudgetNote(event.target.value)} />
        </label>
      </div>

      <div className="timeline-band editable" aria-label="行程时间线">
        {draft.map((day, dayIndex) => (
          <div className="day-column" key={day.day}>
            <div className="day-title">DAY {day.day}</div>
            {editing ? (
              <input className="day-title-input" value={day.title} onChange={(event) => updateDayTitle(dayIndex, event.target.value)} />
            ) : (
              <h3>{day.title}</h3>
            )}
            {day.items.map((item, itemIndex) => (
              <div className="timeline-item editable-item" key={`${day.day}-${itemIndex}`}>
                {editing ? (
                  <>
                    <input value={item.time} onChange={(event) => updateItem(dayIndex, itemIndex, "time", event.target.value)} />
                    <input value={item.title} onChange={(event) => updateItem(dayIndex, itemIndex, "title", event.target.value)} />
                    <textarea value={item.detail} onChange={(event) => updateItem(dayIndex, itemIndex, "detail", event.target.value)} rows={2} />
                  </>
                ) : (
                  <>
                    <span>{item.time}</span>
                    <strong>{item.title}</strong>
                    <p>{item.detail}</p>
                  </>
                )}
              </div>
            ))}
            {editing ? (
              <button type="button" className="add-plan-item" onClick={() => addItem(dayIndex)}>
                <Plus size={14} />
                新增安排
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function PrimaryEmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof PencilLine;
  title: string;
  description: string;
}) {
  return (
    <section className="primary-empty-state" aria-label={title}>
      <Icon size={24} />
      <strong>{title}</strong>
      <p>{description}</p>
    </section>
  );
}

function DecisionWorkbench({ modules }: { modules: DecisionModule[] }) {
  return (
    <section className="decision-workbench workbench-panel" aria-label="结构化旅行决策">
      <div className="section-kicker">
        <WandSparkles size={16} />
        决策面板
      </div>
      <div className="decision-module-grid">
        {modules.map((module) => {
          const Icon = moduleIcons[module.type] || DatabaseZap;
          return (
            <article className={`decision-module ${module.level}`} key={`${module.type}-${module.title}`}>
              <div className="module-title">
                <Icon size={17} />
                <span>{module.title}</span>
              </div>
              <strong>{module.summary}</strong>
              <ul>
                {module.points.slice(0, 3).map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </section>
  );
}
