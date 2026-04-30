import {
  AlertTriangle,
  BadgeDollarSign,
  CloudRain,
  Clock3,
  DatabaseZap,
  Download,
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
  TrainFront,
  WandSparkles,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from "react";

import type {
  ChatResponse,
  DecisionModule,
  ItineraryBlock,
  PlanVersion,
  PlanVersionCompare,
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
  onOpenUserCenter: () => void;
  onSubmit: (message: string) => void;
  onOptimizeItinerary: (editedPlan: Record<string, unknown>) => void;
  onVersionSelect: (versionId: string) => void;
  onExportVersion: (versionId: string, format: "markdown" | "html") => void;
  onShareVersion: (versionId: string) => void;
}

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
  onOpenUserCenter,
  onSubmit,
  onOptimizeItinerary,
  onVersionSelect,
  onExportVersion,
  onShareVersion,
}: ChatWorkspaceProps) {
  const [value, setValue] = useState("");
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || null;
  const toolCount = latest?.tool_calls?.length || 0;
  const sourceCount = latest?.sources?.length || 0;
  const dayCount = latest?.itinerary?.length || 0;

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
    // 中文输入场景保留换行，只在 Ctrl/Cmd + Enter 时提交。
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submitCurrent();
    }
  }

  return (
    <main className="chat-workspace">
      <section className="workspace-command-deck" aria-label="旅行决策总览">
        <div className="workspace-header">
          <div>
            <div className="section-kicker">
              <WandSparkles size={16} />
              智能体工作台
            </div>
            <h1>把攻略、车次、天气和地图放进同一条旅行决策链路</h1>
            <p>面向真实出行的中国旅行智能体：先收集证据，再给方案，再允许你手动改写后继续二次优化。</p>
          </div>
          <div className="header-chips">
            <span className="intent-chip">{latest?.intent || "ready"}</span>
            <span className="mode-chip">{modeLabel[searchMode]}</span>
          </div>
        </div>

        <div className="command-metrics">
          <div>
            <Layers3 size={17} />
            <span>版本</span>
            <strong>{planVersions.length}</strong>
          </div>
          <div>
            <DatabaseZap size={17} />
            <span>来源</span>
            <strong>{sourceCount}</strong>
          </div>
          <div>
            <TrainFront size={17} />
            <span>工具</span>
            <strong>{toolCount}</strong>
          </div>
          <div>
            <MapPinned size={17} />
            <span>行程</span>
            <strong>{dayCount ? `${dayCount}天` : "待定"}</strong>
          </div>
        </div>

        <div className="active-version-banner">
          <span>当前方案</span>
          <strong>{activeVersion?.name || "尚未生成"}</strong>
          <em>
            {guestMode
              ? "当前为游客模式，方案版本仅保留在本页，历史记录与偏好画像不会保存。"
              : activeVersion?.reason || "输入旅行问题后，智能体会生成可编辑方案。"}
          </em>
        </div>

        {guestMode && guestCarryoverReady ? (
          <div className="guest-carryover-banner">
            <div>
              <span>游客临时成果</span>
              <strong>当前页已有可承接的聊天与方案版本，登录后可直接写入历史中心继续优化。</strong>
              <p>登录后可保存历史、沉淀偏好画像，并解锁分享页能力。</p>
            </div>
            <button type="button" className="primary-action" onClick={onOpenUserCenter}>
              <LogIn size={15} />
              登录保存本次方案
            </button>
          </div>
        ) : null}
      </section>

      {latest?.cards?.length ? (
        <section className="decision-strip" aria-label="智能体结果摘要">
          {latest.cards.slice(0, 3).map((card) => (
            <div className={`decision-card ${card.type}`} key={`${card.type}-${card.title}`}>
              {card.type === "railway" ? <TrainFront size={15} /> : <DatabaseZap size={15} />}
              <span>{card.title}</span>
              <strong>{card.summary}</strong>
              {card.type === "railway" && card.meta?.date ? <small>{String(card.meta.date)}</small> : null}
            </div>
          ))}
        </section>
      ) : (
        <section className="empty-workbench" aria-label="启动提示">
          <ShieldCheck size={18} />
          <span>选择检索模式并输入旅行问题，智能体会依次完成意图识别、攻略检索、工具调用和行程生成。</span>
        </section>
      )}

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

      {(loading || streamStages.length > 0) && (
        <section className="stream-progress" aria-label="智能体执行进度">
          <div className="section-kicker">
            <ListChecks size={16} />
            实时调度
          </div>
          <div className="stage-rail">
            {streamStages.map((stage) => (
              <div className={`stage-step ${stage.status}`} key={stage.name}>
                <span />
                <strong>{stage.label}</strong>
                <small>{stage.summary || (stage.status === "running" ? "执行中..." : "已完成")}</small>
              </div>
            ))}
            {loading && !streamStages.length ? (
              <div className="stage-step running">
                <span />
                <strong>建立智能体连接</strong>
                <small>准备读取攻略、铁路、天气和地图工具。</small>
              </div>
            ) : null}
          </div>
        </section>
      )}

      {planVersions.length ? (
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
      ) : null}

      {latest?.decision_modules?.length ? <DecisionWorkbench modules={latest.decision_modules} /> : null}

      <div className="message-stream">
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
      </div>

      {latest?.itinerary ? (
        <EditableItinerary itinerary={latest.itinerary} loading={loading} onOptimize={onOptimizeItinerary} />
      ) : null}

      <form className="composer" onSubmit={handleSubmit}>
        <div className="composer-label">
          <span>Ask TripSage</span>
          <strong>Ctrl + Enter 发送</strong>
        </div>
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="例如：南京三天两夜怎么玩？"
          rows={2}
        />
        <button aria-label="发送问题" disabled={loading || !value.trim()} title="发送">
          <SendHorizonal size={19} />
        </button>
      </form>
    </main>
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
    <section className="plan-version-rail" aria-label="方案版本管理">
      <div className="version-head">
        <div>
          <div className="section-kicker">
            <GitBranch size={16} />
            方案版本
          </div>
          <h2>保留每次智能体决策，随时回到任一版继续调整</h2>
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
                  <button type="button" title="导出 Markdown" onClick={(event) => {
                    event.stopPropagation();
                    onExport(version.id, "markdown");
                  }}>
                    <Download size={13} />
                    MD
                  </button>
                  <button type="button" title="导出 HTML" onClick={(event) => {
                    event.stopPropagation();
                    onExport(version.id, "html");
                  }}>
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
          return <pre className="answer-table" key={index}>{block}</pre>;
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
  const [transportNote, setTransportNote] = useState("优先高铁/地铁衔接，尽量减少打车。");
  const [budgetNote, setBudgetNote] = useState("控制住宿与交通成本，餐饮保留弹性。");

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
              items: [...day.items, { time: "弹性", title: "新增安排", detail: "请填写想加入的景点、交通或餐饮安排。" }],
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
      user_goal: "在用户手动编辑的基础上继续二次优化，不要丢失用户新增或修改的安排。",
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
          <h2>把这份行程改成你的版本，再交给智能体继续优化</h2>
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

function DecisionWorkbench({ modules }: { modules: DecisionModule[] }) {
  return (
    <section className="decision-workbench" aria-label="结构化旅行决策">
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
