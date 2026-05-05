import {
  AlertTriangle,
  BadgeDollarSign,
  BookOpenText,
  CheckCircle2,
  ChevronDown,
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
  PanelLeftOpen,
  PanelRightOpen,
  PencilLine,
  Plus,
  RefreshCw,
  SendHorizonal,
  ShieldAlert,
  ShieldCheck,
  Star,
  TrainFront,
  WandSparkles,
  X,
} from "lucide-react";
import { FormEvent, KeyboardEvent, forwardRef, useEffect, useMemo, useRef, useState } from "react";

import type {
  ChatResponse,
  DecisionModule,
  GuideDetail,
  ItineraryBlock,
  PlanVersion,
  PlanVersionCompare,
  RailwayTrain,
  StreamStage,
} from "../lib/types";
import type { PlanningPromptCard } from "../lib/personalization";

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
  starterPrompts: PlanningPromptCard[];
  profileHighlights: string[];
  profileDigest: string;
  decisionModuleStates: Record<string, "accepted" | "ignored">;
  referencedGuide: GuideDetail | null;
  onOpenPlanner: () => void;
  onOpenEvidence: () => void;
  onOpenEvidenceWorkspace: () => void;
  onOpenRailway: () => void;
  onOpenUserCenter: () => void;
  onClearReferencedGuide: () => void;
  onOpenReferencedGuide: (detailMode?: "preview" | "edit") => void;
  onSubmit: (message: string) => void;
  onOptimizeItinerary: (editedPlan: Record<string, unknown>) => void;
  onDecisionModuleAction: (module: DecisionModule, action: "accept" | "ignore" | "regenerate") => void;
  onVersionSelect: (versionId: string, reason?: "browse" | "rollback") => void;
  onExportVersion: (versionId: string, format: "markdown" | "html") => void;
  onShareVersion: (versionId: string) => void;
}

type PrimaryWorkbenchTab = "messages" | "itinerary" | "decision";
type SecondaryWorkbenchTab = "railway" | "versions";
type RailwaySortMode = "recommended" | "earliest" | "fastest";
type TrainTypeFilter = "all" | "high_speed" | "normal";
type SeatFilter = "all" | "available";

const searchModeLabel: Record<ChatWorkspaceProps["searchMode"], string> = {
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

function getRailwayTrains(card: ChatResponse["cards"][number] | null): RailwayTrain[] {
  const value = card?.meta?.trains;
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
  return parts.slice(0, 3).join(" / ") || "余票请以 12306 官方结果为准";
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
  return Number(match[1] || 0) * 60 + Number(match[2] || 0);
}

function findEarliestTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toMinutesFromTime(left.start_time) - toMinutesFromTime(right.start_time))[0];
}

function findFastestTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toDurationMinutes(left.duration) - toDurationMinutes(right.duration))[0];
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

function buildTrainDecisionTags(train: RailwayTrain, earliestTrain?: RailwayTrain, fastestTrain?: RailwayTrain) {
  const tags: string[] = [];
  if (train.train_no && train.train_no === earliestTrain?.train_no) tags.push("最早出发");
  if (train.train_no && train.train_no === fastestTrain?.train_no) tags.push("耗时最短");
  if (isHighSpeedTrain(train)) tags.push("高铁优先");
  if (hasAvailableSeat(train)) tags.push("余票较稳");
  const start = toMinutesFromTime(train.start_time);
  if (start >= 8 * 60 && start <= 18 * 60) tags.push("时段友好");
  return tags.slice(0, 4);
}

function buildTrainAdoptionPrompt(train: RailwayTrain) {
  return [
    `请把 ${train.train_no || "这趟车"} 纳入当前旅行方案继续优化。`,
    `车次信息：${train.from_station || "出发站"} 到 ${train.to_station || "到达站"}，${train.start_time || "--:--"} 出发，${train.arrive_time || "--:--"} 到达，耗时 ${train.duration || "待确认"}。`,
    `座席情况：${seatSummary(train)}。`,
    "请重新评估当天景点顺序、出站后的地图通勤、预算和行程强度，并输出更新后的可执行方案。",
  ].join("\n");
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
  starterPrompts,
  profileHighlights,
  profileDigest,
  decisionModuleStates,
  referencedGuide,
  onOpenPlanner,
  onOpenEvidence,
  onOpenEvidenceWorkspace,
  onOpenRailway,
  onOpenUserCenter,
  onClearReferencedGuide,
  onOpenReferencedGuide,
  onSubmit,
  onOptimizeItinerary,
  onDecisionModuleAction,
  onVersionSelect,
  onExportVersion,
  onShareVersion,
}: ChatWorkspaceProps) {
  const [value, setValue] = useState("");
  const [primaryTab, setPrimaryTab] = useState<PrimaryWorkbenchTab>("messages");
  const [secondaryTab, setSecondaryTab] = useState<SecondaryWorkbenchTab>("railway");
  const [railwaySortMode, setRailwaySortMode] = useState<RailwaySortMode>("recommended");
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [readerMessage, setReaderMessage] = useState<{ role: "assistant"; content: string; index: number } | null>(null);

  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const dispatchRailRef = useRef<HTMLElement | null>(null);

  const cards = latest?.cards || [];
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || null;
  const railwayCard = cards.find((card) => card.type === "railway") || null;
  const railwayTrains = useMemo(() => getRailwayTrains(railwayCard), [railwayCard]);
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
  const latestStage = streamStages[streamStages.length - 1];
  const itineraryCount = latest?.itinerary?.length || 0;
  const sourceCount = latest?.sources?.length || 0;
  const toolCount = latest?.tool_calls?.length || 0;
  const decisionCount = latest?.decision_modules?.length || 0;
  const destination = cards.find((card) => card.type === "destination")?.title || "准备开始新的旅行方案";

  function submitCurrent() {
    const text = value.trim();
    if (!text || loading) return;
    setPrimaryTab("messages");
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

  function focusComposer() {
    setPrimaryTab("messages");
    window.requestAnimationFrame(() => {
      // 聚焦输入框时禁止页面整体跳滚，避免把上方调度区挤出视口。
      composerTextareaRef.current?.focus({ preventScroll: true });
    });
  }

  function scrollToLatest() {
    setPrimaryTab("messages");
    window.requestAnimationFrame(() => {
      const element = messageScrollRef.current;
      if (!element) return;
      element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    });
  }

  function scrollToDispatch() {
    setPrimaryTab("messages");
    window.requestAnimationFrame(() => {
      dispatchRailRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  function primePrompt(prompt: string) {
    setPrimaryTab("messages");
    setValue(prompt);
    window.requestAnimationFrame(() => {
      // 预填提示词时同样保持页面稳定，只更新输入焦点与光标位置。
      composerTextareaRef.current?.focus({ preventScroll: true });
      composerTextareaRef.current?.setSelectionRange(prompt.length, prompt.length);
    });
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
      setShowJumpToLatest(distanceToBottom > 180);
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
    <main
      className={`planner-workstation ${primaryTab === "messages" ? "is-message-focus" : ""}`}
      aria-label="旅行规划主工作台"
    >
      <section className="planner-workstation-bar">
        <div className="planner-bar-copy">
          <div className="section-kicker">
            <WandSparkles size={16} />
            规划工作台
          </div>
          <h2>{activeVersion?.name || destination}</h2>
          <p>{loading ? latestStage?.summary || "正在调度攻略库、铁路、天气和地图工具" : profileDigest}</p>
        </div>

        <div className="planner-bar-side">
          <div className="planner-status-cluster">
            <PlannerStatusChip label="检索模式" value={searchModeLabel[searchMode]} tone="jade" />
            <PlannerStatusChip label="方案版本" value={String(planVersions.length)} tone="rail" />
            <PlannerStatusChip label="行程天数" value={itineraryCount ? `${itineraryCount} 天` : "待生成"} tone="ink" />
            <PlannerStatusChip label="铁路候选" value={String(railwayTrains.length)} tone="sun" />
          </div>
          <div className="planner-bar-actions">
            <button type="button" className="secondary-action" onClick={onOpenPlanner}>
              <PanelLeftOpen size={15} />
              条件
            </button>
            <button type="button" className="secondary-action" onClick={onOpenEvidence}>
              <PanelRightOpen size={15} />
              证据
            </button>
            <button type="button" className="secondary-action" onClick={onOpenRailway}>
              <TrainFront size={15} />
              铁路
            </button>
            {guestMode && guestCarryoverReady ? (
              <button type="button" className="secondary-action" onClick={onOpenUserCenter}>
                <LogIn size={15} />
                登录保存本次方案
              </button>
            ) : null}
            {showJumpToLatest ? (
              <button type="button" className="secondary-action" onClick={scrollToLatest}>
                <ChevronDown size={15} />
                回到底部
              </button>
            ) : null}
            <button type="button" className="primary-action" onClick={focusComposer}>
              <SendHorizonal size={15} />
              开始规划
            </button>
          </div>
        </div>
      </section>

      {referencedGuide ? (
        <GuideReferenceStrip
          guide={referencedGuide}
          onClear={onClearReferencedGuide}
          onBrowseGuides={onOpenEvidenceWorkspace}
          onOpenDetail={() => onOpenReferencedGuide("preview")}
          onOpenEditor={() => onOpenReferencedGuide("edit")}
        />
      ) : null}

      <section className="planner-workstation-grid">
        <section
          className={`planner-primary-surface ${primaryTab === "messages" ? "is-message-focus" : ""}`}
          aria-label="核心决策区"
        >
          <header className="planner-surface-head">
            <div>
              <div className="section-kicker">
                <ListChecks size={15} />
                核心决策区
              </div>
              <h3>{primaryTab === "messages" ? "对话主线" : primaryTab === "itinerary" ? "可编辑行程" : "决策模块"}</h3>
            </div>
            <div className="planner-tab-row" role="tablist" aria-label="切换核心工作区">
              <button
                type="button"
                className={`planner-tab-button ${primaryTab === "messages" ? "active" : ""}`}
                onClick={() => setPrimaryTab("messages")}
                role="tab"
                aria-selected={primaryTab === "messages"}
              >
                <ListChecks size={14} />
                消息
                <span>{messages.length}</span>
              </button>
              <button
                type="button"
                className={`planner-tab-button ${primaryTab === "itinerary" ? "active" : ""}`}
                onClick={() => setPrimaryTab("itinerary")}
                role="tab"
                aria-selected={primaryTab === "itinerary"}
              >
                <PencilLine size={14} />
                行程
                <span>{itineraryCount}</span>
              </button>
              <button
                type="button"
                className={`planner-tab-button ${primaryTab === "decision" ? "active" : ""}`}
                onClick={() => setPrimaryTab("decision")}
                role="tab"
                aria-selected={primaryTab === "decision"}
              >
                <WandSparkles size={14} />
                决策
                <span>{decisionCount}</span>
              </button>
            </div>
          </header>

          <DispatchRail ref={dispatchRailRef} stages={streamStages} loading={loading} />

          {latest?.warnings?.length ? (
            <section className="planner-warning-strip" aria-label="风险提醒">
              <AlertTriangle size={16} />
              <div>
                {latest.warnings.map((warning) => (
                  <span key={warning}>{warning}</span>
                ))}
              </div>
            </section>
          ) : null}

          <div className="planner-primary-content">
            {primaryTab === "messages" ? (
              <div className="planner-message-surface featured">
                <div className="planner-message-head">
                  <div>
                    <strong>会话记录</strong>
                    <span>当前轮次</span>
                  </div>
                  <div className="planner-inline-metrics">
                    <span>{sourceCount} 条来源</span>
                    <span>{toolCount} 次工具</span>
                    <span>{decisionCount} 个决策模块</span>
                  </div>
                </div>

                <div className="planner-message-scroll" ref={messageScrollRef}>
                  <div className="planner-message-list">
                    {messages.map((message, index) => {
                      const canOpenReader = message.role === "assistant" && message.content.trim().length > 0;
                      return (
                        <article className={`planner-message-bubble ${message.role}`} key={`${message.role}-${index}`}>
                          <div className="planner-message-role-row">
                            <div className="planner-message-role">{message.role === "user" ? "你" : "TripSage"}</div>
                            {canOpenReader ? (
                              <button
                                type="button"
                                className="planner-message-read-button"
                                onClick={() => setReaderMessage({ role: "assistant", content: message.content, index })}
                              >
                                <BookOpenText size={14} />
                                阅读全文
                              </button>
                            ) : null}
                          </div>
                          {message.role === "assistant" ? <AnswerRenderer content={message.content} /> : <p>{message.content}</p>}
                        </article>
                      );
                    })}
                    {loading ? (
                      <article className="planner-message-bubble assistant loading">
                        <div className="planner-message-role">TripSage</div>
                        <p>正在调度攻略库、铁路、天气和地图工具，请稍候...</p>
                      </article>
                    ) : null}
                  </div>
                </div>

                <div className="planner-message-footer">
                  <form className="planner-composer-shell message-embedded" onSubmit={handleSubmit}>
                    <div className="planner-composer-meta">
                      <div>
                        <span>规划输入</span>
                        <strong>{guestMode ? "游客会话" : "已连接长期记忆"}</strong>
                      </div>
                      <em>Ctrl + Enter 发送</em>
                    </div>
                    <div className="planner-composer">
                      <textarea
                        ref={composerTextareaRef}
                        value={value}
                        onChange={(event) => setValue(event.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="例如：杭州出发，五一去南京两天一夜，优先高铁，预算 1800 元，请给我可执行方案。"
                        rows={3}
                      />
                      <button type="submit" aria-label="发送问题" disabled={loading || !value.trim()} title="发送">
                        <SendHorizonal size={18} />
                      </button>
                    </div>
                  </form>

                  <div className="planner-message-float-stack" aria-label="会话快捷操作">
                    <button type="button" className="planner-float-button" onClick={scrollToDispatch}>
                      <Clock3 size={15} />
                      调度
                    </button>
                    {showJumpToLatest ? (
                      <button type="button" className="planner-float-button strong" onClick={scrollToLatest}>
                        <ChevronDown size={15} />
                        最新
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}

            {primaryTab === "itinerary" ? (
              latest?.itinerary ? (
                <div className="planner-scroll-stage">
                  <EditableItinerary itinerary={latest.itinerary} loading={loading} onOptimize={onOptimizeItinerary} />
                </div>
              ) : (
                <PrimaryEmptyState
                  icon={PencilLine}
                  title="还没有可编辑行程"
                  description="先生成方案，再在这里逐日调整并继续优化。"
                />
              )
            ) : null}

            {primaryTab === "decision" ? (
              latest?.decision_modules?.length ? (
                <div className="planner-scroll-stage">
                  <ActionableDecisionWorkbench
                    modules={latest.decision_modules}
                    loading={loading}
                    states={decisionModuleStates}
                    onAction={onDecisionModuleAction}
                  />
                </div>
              ) : (
                <PrimaryEmptyState
                  icon={WandSparkles}
                  title="决策模块等待生成"
                  description="等待决策结果。"
                />
              )
            ) : null}
          </div>

          <form
            className={`planner-composer-shell ${primaryTab === "messages" ? "message-mode is-hidden" : ""}`}
            onSubmit={handleSubmit}
          >
            <div className="planner-composer-meta">
              <div>
                <span>规划输入</span>
                <strong>{guestMode ? "游客会话" : "已连接长期记忆"}</strong>
              </div>
              <em>Ctrl + Enter 发送</em>
            </div>
            <div className="planner-composer">
              <textarea
                ref={composerTextareaRef}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="例如：杭州出发，五一去南京两天一夜，优先高铁，预算 1800 元，请给我可执行方案。"
                rows={3}
              />
              <button type="submit" aria-label="发送问题" disabled={loading || !value.trim()} title="发送">
                <SendHorizonal size={18} />
              </button>
            </div>
          </form>
        </section>

        <aside className="planner-secondary-surface" aria-label="铁路结果与版本区">
          <header className="planner-surface-head secondary">
            <div>
              <div className="section-kicker">
                <DatabaseZap size={15} />
                证据与比选
              </div>
              <h3>{secondaryTab === "railway" ? "铁路工作区" : "版本工作区"}</h3>
            </div>
            <div className="planner-tab-row" role="tablist" aria-label="切换右侧工作区">
              <button
                type="button"
                className={`planner-tab-button ${secondaryTab === "railway" ? "active" : ""}`}
                onClick={() => setSecondaryTab("railway")}
                role="tab"
                aria-selected={secondaryTab === "railway"}
                disabled={!railwayCard}
              >
                <TrainFront size={14} />
                车次
                <span>{railwayTrains.length}</span>
              </button>
              <button
                type="button"
                className={`planner-tab-button ${secondaryTab === "versions" ? "active" : ""}`}
                onClick={() => setSecondaryTab("versions")}
                role="tab"
                aria-selected={secondaryTab === "versions"}
                disabled={!planVersions.length}
              >
                <GitBranch size={14} />
                版本
                <span>{planVersions.length}</span>
              </button>
            </div>
          </header>

          <div className="planner-secondary-scroll">
            {secondaryTab === "railway" ? (
              railwayCard ? (
                <RailwayWorkbench
                  railwayCard={railwayCard}
                  trains={sortedRailwayTrains}
                  totalTrains={railwayTrains.length}
                  earliestTrain={earliestTrain}
                  fastestTrain={fastestTrain}
                  sortMode={railwaySortMode}
                  onSortChange={setRailwaySortMode}
                  onUseTrain={(train) => onSubmit(buildTrainAdoptionPrompt(train))}
                />
              ) : (
                <SecondaryEmptyState text="等待铁路查询结果。" />
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
                <SecondaryEmptyState text="等待方案版本生成。" />
              )
            ) : null}
          </div>
        </aside>
      </section>
      {readerMessage ? (
        <div className="planner-reader-overlay" role="dialog" aria-modal="true" aria-label="AI 回复全文">
          <button type="button" className="planner-reader-backdrop" onClick={() => setReaderMessage(null)} aria-label="关闭全文阅读" />
          <section className="planner-reader-panel">
            <header className="planner-reader-head">
              <div>
                <span>TripSage 回复</span>
                <strong>第 {readerMessage.index + 1} 条消息全文</strong>
              </div>
              <button type="button" className="icon-button" onClick={() => setReaderMessage(null)} aria-label="关闭全文阅读">
                <X size={16} />
              </button>
            </header>
            <div className="planner-reader-body">
              <AnswerRenderer content={readerMessage.content} />
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function PlannerStatusChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "jade" | "rail" | "sun" | "ink";
}) {
  return (
    <div className={`planner-status-chip ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function GuideReferenceStrip({
  guide,
  onClear,
  onBrowseGuides,
  onOpenDetail,
  onOpenEditor,
}: {
  guide: GuideDetail;
  onClear: () => void;
  onBrowseGuides: () => void;
  onOpenDetail: () => void;
  onOpenEditor: () => void;
}) {
  const structured = guide.structured;
  const budget = structured?.budget_range
    || (guide.budget_min != null && guide.budget_max != null
      ? `${guide.budget_min}-${guide.budget_max}元`
      : guide.budget_min != null
        ? `约${guide.budget_min}元`
        : null);
  const scenic = structured?.scenic_spots?.slice(0, 3) || [];
  const transport = structured?.transport_modes?.slice(0, 2) || [];

  return (
    <section className="planner-guide-reference-strip" aria-label="当前参考攻略">
      <div className="planner-guide-reference-copy">
        <div className="planner-guide-reference-kicker">
          <DatabaseZap size={15} />
          当前参考攻略
        </div>
        <strong>{guide.title}</strong>
        <p>{structured?.summary || guide.summary || "当前对话会持续参考这篇攻略的结构化信息与正文线索。"}</p>
        <div className="planner-guide-reference-chips">
          <span>{guide.city || "未知城市"}</span>
          {guide.days ? <span>{guide.days} 天</span> : null}
          {budget ? <span>{budget}</span> : null}
          {transport.map((item) => <span key={item}>{item}</span>)}
          {scenic.map((item) => <span key={item}>{item}</span>)}
        </div>
      </div>

      <div className="planner-guide-reference-actions">
        <button type="button" className="secondary-action" onClick={onBrowseGuides}>
          <PanelRightOpen size={14} />
          更换攻略
        </button>
        <button type="button" className="secondary-action" onClick={onOpenDetail}>
          <Link2 size={14} />
          查看详情
        </button>
        <button type="button" className="secondary-action" onClick={onOpenEditor}>
          <PencilLine size={14} />
          编辑攻略
        </button>
        {guide.source_url ? (
          <a className="planner-guide-reference-link" href={guide.source_url} target="_blank" rel="noreferrer">
            <Link2 size={14} />
            查看来源
          </a>
        ) : null}
        <button type="button" className="planner-guide-reference-clear" onClick={onClear} aria-label="取消当前参考攻略">
          <X size={14} />
          取消引用
        </button>
      </div>
    </section>
  );
}

const DispatchRail = forwardRef<HTMLElement, { stages: StreamStage[]; loading: boolean }>(function DispatchRail(
  { stages, loading },
  ref,
) {
  const displayStages = stages.length
    ? stages.slice(-4)
    : [{ name: "idle", label: "待处理", status: "done" as const, summary: "等待输入" }];

  return (
    <section ref={ref} className="planner-dispatch-rail" aria-label="实时调度">
      <div className="planner-dispatch-title">
        <Clock3 size={15} />
        <strong>实时调度</strong>
        <span>{loading ? "执行中" : "空闲"}</span>
      </div>
      <div className="planner-dispatch-list">
        {displayStages.map((stage) => (
          <article className={`planner-dispatch-card ${stage.status}`} key={stage.name}>
            <strong>{stage.label}</strong>
            <span>{stage.summary || (stage.status === "running" ? "执行中" : "已完成")}</span>
          </article>
        ))}
      </div>
    </section>
  );
});

function SecondaryStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof TrainFront;
  label: string;
  value: string;
}) {
  return (
    <div className="planner-secondary-stat">
      <Icon size={15} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RailwayWorkbench({
  railwayCard,
  trains,
  totalTrains,
  earliestTrain,
  fastestTrain,
  sortMode,
  onSortChange,
  onUseTrain,
}: {
  railwayCard: ChatResponse["cards"][number];
  trains: RailwayTrain[];
  totalTrains: number;
  earliestTrain?: RailwayTrain;
  fastestTrain?: RailwayTrain;
  sortMode: RailwaySortMode;
  onSortChange: (mode: RailwaySortMode) => void;
  onUseTrain: (train: RailwayTrain) => void;
}) {
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
    setPinnedKeys((current) => (
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    ));
  }

  return (
    <section className="railway-desk" aria-label="铁路结果工作区">
      <div className="railway-desk-hero">
        <div>
          <div className="section-kicker">
            <TrainFront size={15} />
            铁路结果
          </div>
          <h4>{railwayCard.summary || "可用车次列表"}</h4>
          <p>完整车次池，支持筛选、比选与回写。</p>
        </div>
        <div className="railway-desk-topline">
          <span>{totalTrains} 条候选</span>
          <strong>{typeof railwayCard.meta?.date === "string" ? railwayCard.meta?.date : "日期待确认"}</strong>
        </div>
      </div>

      <div className="railway-snapshot-grid">
        <RailwaySnapshotCard
          label="最早出发"
          value={earliestTrain?.start_time || "--:--"}
          detail={earliestTrain ? `${earliestTrain.train_no || "车次"} · ${earliestTrain.from_station || "出发"} → ${earliestTrain.to_station || "到达"}` : "等待结果"}
        />
        <RailwaySnapshotCard
          label="最短耗时"
          value={fastestTrain?.duration || "--"}
          detail={fastestTrain ? `${fastestTrain.train_no || "车次"} · ${fastestTrain.start_time || "--:--"} 出发` : "等待结果"}
        />
        <RailwaySnapshotCard
          label="筛选结果"
          value={`${filteredTrains.length}/${totalTrains}`}
          detail="当前视图"
        />
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

        <div className="railway-filter-group">
          <Filter size={14} />
          <button type="button" className={trainTypeFilter === "all" ? "active" : ""} onClick={() => setTrainTypeFilter("all")}>
            全部
          </button>
          <button type="button" className={trainTypeFilter === "high_speed" ? "active" : ""} onClick={() => setTrainTypeFilter("high_speed")}>
            高铁动车
          </button>
          <button type="button" className={trainTypeFilter === "normal" ? "active" : ""} onClick={() => setTrainTypeFilter("normal")}>
            普通列车
          </button>
        </div>

        <div className="railway-filter-group">
          <CheckCircle2 size={14} />
          <button type="button" className={seatFilter === "all" ? "active" : ""} onClick={() => setSeatFilter("all")}>
            不限余票
          </button>
          <button type="button" className={seatFilter === "available" ? "active" : ""} onClick={() => setSeatFilter("available")}>
            只看有票
          </button>
        </div>
      </div>

      {selectedTrain ? (
        <div className="railway-selection-banner">
          <div>
            <span>当前选中车次</span>
            <strong>
              {selectedTrain.train_no || "车次"} · {selectedTrain.start_time || "--:--"} 出发 · {selectedTrain.duration || "待确认"}
            </strong>
            <p>
              {selectedTrain.from_station || "出发站"} → {selectedTrain.to_station || "到达站"} · {seatSummary(selectedTrain)}
            </p>
          </div>
          <button type="button" className="primary-action" onClick={() => onUseTrain(selectedTrain)}>
            <SendHorizonal size={15} />
            纳入当前方案
          </button>
        </div>
      ) : null}

      <div className="railway-result-scroll">
        {filteredTrains.map((train, index) => {
          const key = trainKey(train, index);
          const tags = buildTrainDecisionTags(train, earliestTrain, fastestTrain);
          const isSelected = selectedTrainKey === key;
          const isPinned = pinnedKeys.includes(key);

          return (
            <article className={`railway-train-card ${isSelected ? "selected" : ""}`} key={key}>
              <div className="railway-train-head">
                <div className="railway-train-code">{train.train_no || "车次"}</div>
                <div className="railway-train-route">
                  <strong>{train.from_station || "出发站"}</strong>
                  <span>→</span>
                  <strong>{train.to_station || "到达站"}</strong>
                </div>
                <div className="railway-train-duration">{train.duration || "待确认"}</div>
              </div>

              <div className="railway-train-tags">
                {(tags.length ? tags : ["候选"]).map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
                <button
                  type="button"
                  className={`railway-pin-button ${isPinned ? "active" : ""}`}
                  onClick={() => togglePinned(key)}
                  title={isPinned ? "取消重点关注" : "重点关注"}
                  aria-label={isPinned ? "取消重点关注" : "重点关注"}
                >
                  <Star size={14} />
                </button>
              </div>

              <div className="railway-train-metrics">
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

              <div className="railway-train-actions">
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
            <span>当前筛选条件下没有车次，放宽列车类型或余票条件后再查看。</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function RailwaySnapshotCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="railway-snapshot-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
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
    <section className="decision-workbench-studio" aria-label="结构化旅行决策">
      <div className="decision-workbench-head">
        <div>
          <div className="section-kicker">
            <WandSparkles size={15} />
            决策模块
          </div>
          <h4>交通、预算、雨天与风险建议在这里集中处理</h4>
        </div>
        <div className="decision-workbench-stats">
          <span>总计 {modules.length}</span>
          <span>已采纳 {acceptedCount}</span>
          <span>已忽略 {ignoredCount}</span>
        </div>
      </div>

      <div className="decision-module-grid premium">
        {modules.map((module) => {
          const Icon = moduleIcons[module.type] || DatabaseZap;
          const state = states[buildDecisionModuleKey(module)];

          return (
            <article className={`decision-module-card ${module.level} ${state ? `is-${state}` : "is-pending"}`} key={`${module.type}-${module.title}`}>
              <div className="decision-module-head">
                <div className="decision-module-title">
                  <Icon size={16} />
                  <span>{module.title}</span>
                </div>
                <em>{getDecisionStateLabel(state)}</em>
              </div>

              <strong>{module.summary}</strong>

              <ul>
                {module.points.slice(0, 4).map((point) => (
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
                <button type="button" disabled={loading} onClick={() => onAction(module, "regenerate")}>
                  <RefreshCw size={14} />
                  重新生成
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
  onSelect: (versionId: string, reason?: "browse" | "rollback") => void;
  onExport: (versionId: string, format: "markdown" | "html") => void;
  onShare: (versionId: string) => void;
}) {
  return (
    <section className="version-workbench-studio" aria-label="方案版本管理">
      <div className="version-workbench-head">
        <div>
          <div className="section-kicker">
            <GitBranch size={15} />
            方案版本
          </div>
          <h4>保留方案演进轨迹，随时回切继续优化</h4>
        </div>
        <span>{versions.length} 个版本</span>
      </div>

      <div className="version-track-rail">
        {versions.map((version, index) => {
          const isActive = version.id === activeVersionId;
          const toolCount = version.response.tool_calls?.length || 0;
          const sourceCount = version.response.sources?.length || 0;

          return (
            <button type="button" className={`version-track-card ${isActive ? "active" : ""}`} onClick={() => onSelect(version.id)} key={version.id}>
              <div className="version-track-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="version-track-main">
                <strong>{version.name}</strong>
                <span>{version.reason}</span>
                <em>{formatVersionTime(version.createdAt)} · {toolCount} 工具 · {sourceCount} 来源</em>
              </div>
              {isActive ? <small>当前</small> : null}
              {isActive ? (
                <div className="version-track-actions">
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
                    title={canShareVersion ? "创建分享页" : "登录后可分享"}
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
                    {canShareVersion ? "分享" : "登录分享"}
                  </button>
                </div>
              ) : null}
            </button>
          );
        })}
      </div>

      {guestMode ? <div className="version-login-hint">游客会话不写入历史中心。</div> : null}

      {shareUrl ? (
        <a className="version-share-strip" href={shareUrl}>
          <Link2 size={15} />
          <span>{shareUrl}</span>
          <strong>已生成分享页</strong>
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
    <div className="version-compare-panel premium" aria-label="方案版本差异">
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

function SecondaryEmptyState({ text }: { text: string }) {
  return (
    <div className="planner-secondary-empty">
      <ShieldCheck size={16} />
      <span>{text}</span>
    </div>
  );
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
              items: day.items.map((item, innerIndex) => (innerIndex === itemIndex ? { ...item, [key]: value } : item)),
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
    <section className={`editable-plan-studio ${editing ? "editing" : ""}`} aria-label="可编辑行程方案">
      <div className="editable-plan-head">
        <div>
          <div className="section-kicker">
            <PencilLine size={15} />
            可编辑方案
          </div>
          <h4>先编辑，再基于新版本继续优化</h4>
        </div>
        <div className="editable-plan-actions">
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

      <div className="editable-plan-notes">
        <label>
          <span>交通偏好</span>
          <input disabled={!editing} value={transportNote} onChange={(event) => setTransportNote(event.target.value)} />
        </label>
        <label>
          <span>预算策略</span>
          <input disabled={!editing} value={budgetNote} onChange={(event) => setBudgetNote(event.target.value)} />
        </label>
      </div>

      <div className="editable-plan-grid">
        {draft.map((day, dayIndex) => (
          <article className="editable-day-card" key={day.day}>
            <div className="editable-day-kicker">DAY {day.day}</div>
            {editing ? (
              <input className="editable-day-title-input" value={day.title} onChange={(event) => updateDayTitle(dayIndex, event.target.value)} />
            ) : (
              <h5>{day.title}</h5>
            )}

            <div className="editable-day-items">
              {day.items.map((item, itemIndex) => (
                <div className="editable-day-item" key={`${day.day}-${itemIndex}`}>
                  {editing ? (
                    <>
                      <input value={item.time} onChange={(event) => updateItem(dayIndex, itemIndex, "time", event.target.value)} />
                      <input value={item.title} onChange={(event) => updateItem(dayIndex, itemIndex, "title", event.target.value)} />
                      <textarea value={item.detail} onChange={(event) => updateItem(dayIndex, itemIndex, "detail", event.target.value)} rows={3} />
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
            </div>

            {editing ? (
              <button type="button" className="add-plan-item" onClick={() => addItem(dayIndex)}>
                <Plus size={14} />
                新增安排
              </button>
            ) : null}
          </article>
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
    <section className="planner-primary-empty" aria-label={title}>
      <Icon size={24} />
      <strong>{title}</strong>
      <p>{description}</p>
    </section>
  );
}
