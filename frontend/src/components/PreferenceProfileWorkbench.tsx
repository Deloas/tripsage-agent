import {
  Activity,
  BrainCircuit,
  CalendarClock,
  Compass,
  DatabaseZap,
  HeartHandshake,
  History,
  Layers3,
  LockKeyhole,
  LogIn,
  MapPinned,
  Radar,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrainFront,
  UnlockKeyhole,
  Wallet,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { fetchPreferenceAudit, fetchPreferenceTimeline, undoPreferenceTimelineEvent } from "../lib/api";
import type {
  ConversationSummary,
  LocalUser,
  PreferenceAuditGroup,
  PreferenceAuditItem,
  PreferenceAuditResult,
  PreferenceBehaviorEventPayload,
  PreferenceFeedbackPayload,
  PreferenceGovernanceItem,
  PreferenceLayer,
  PreferenceProfile,
  PreferenceTimelineItem,
} from "../lib/types";
import { WorkspaceHero } from "./WorkspaceHero";

interface PreferenceProfileWorkbenchProps {
  guestMode: boolean;
  currentUser: LocalUser | null;
  conversations: ConversationSummary[];
  profile: PreferenceProfile | null;
  activeConversationId?: string | null;
  feedbackLoading: boolean;
  onOpenHistory: () => void;
  onOpenUserCenter: () => void;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
  onBehaviorEvent: (payload: PreferenceBehaviorEventPayload) => Promise<void>;
  onProfileReplace: (profile: PreferenceProfile) => void;
}

interface PreferenceProfileSnapshotProps {
  profile: PreferenceProfileLike;
  title?: string;
  subtitle?: string;
  emptyText?: string;
  showEvidence?: boolean;
  compact?: boolean;
}

type PreferenceTone = "jade" | "rail" | "rust" | "sun";
type PreferenceProfileLike = PreferenceProfile | PreferenceLayer | null;
type TimelineFilter = "all" | "undoable" | "undone";
type AuditGroupBy = "dimension" | "source" | "scope";
type MemorySectionKey = "overview" | "governance" | "audit" | "timeline";

type ClusterConfig = {
  id: string;
  title: string;
  subtitle: string;
  dimension: PreferenceFeedbackPayload["dimension"];
  values: string[];
  tone: PreferenceTone;
  icon: ReactNode;
};

type PreferenceActionDefinition<T> = {
  label: string;
  tone?: "default" | "negative";
  onClick: (item: T) => void;
};

type EvidenceActionItem = {
  key: string;
  title: string;
  meta: string;
  dimension: string;
  value: string;
  polarity: string;
};

type PreferenceActionFeedback = {
  tone: PreferenceTone;
  title: string;
  detail: string;
  badge: string;
  created_at: string;
};

const STRENGTH_META = {
  new: {
    label: "初步学习",
    description: "系统刚开始学习你的旅行习惯，后续多聊几轮会更准。",
    ratio: 0.34,
  },
  growing: {
    label: "持续收敛",
    description: "偏好方向已经开始稳定，后续规划会越来越贴近你的真实习惯。",
    ratio: 0.68,
  },
  strong: {
    label: "稳定画像",
    description: "系统已经形成可复用的长期偏好，可直接作为下一次规划底座。",
    ratio: 1,
  },
} as const;

const SOURCE_LABELS: Record<string, string> = {
  user_message: "对话直述",
  profile_setting: "资料设定",
  manual_prefer: "设为常用",
  manual_avoid: "不再推荐",
  manual_session: "仅本次生效",
  manual_demote: "移出长期偏好",
  manual_allow: "恢复推荐",
  manual_lock: "锁定长期偏好",
  manual_unlock: "解除长期锁定",
  trip_signal: "规划学习",
  destination_inferred: "目的地推断",
  decision_accept: "采纳模块建议",
  decision_ignore: "忽略模块建议",
  itinerary_edit: "手动编辑行程",
  railway_selection: "列车选择",
  version_select: "查看版本",
  version_rollback: "版本回退",
  favorite_on: "收藏方案",
  favorite_off: "取消收藏",
  share_plan: "分享方案",
  history_open: "打开历史",
  continue_optimize: "继续优化",
  legacy_profile: "历史画像",
};

const DIMENSION_LABELS: Record<string, string> = {
  destination: "目的地偏好",
  transport: "交通方式",
  pace: "旅行节奏",
  interest: "兴趣主题",
  avoidance: "避让偏好",
  budget: "预算偏好",
  budget_style: "预算风格",
  behavior: "行为信号",
  risk: "风险偏好",
};

const MEMORY_SECTION_META: Record<MemorySectionKey, { label: string; icon: ReactNode }> = {
  overview: {
    label: "画像总览",
    icon: <Compass size={14} />,
  },
  governance: {
    label: "治理台",
    icon: <ShieldCheck size={14} />,
  },
  audit: {
    label: "审计区",
    icon: <Radar size={14} />,
  },
  timeline: {
    label: "时间线",
    icon: <History size={14} />,
  },
};

export function PreferenceProfileWorkbench({
  guestMode,
  currentUser,
  conversations,
  profile,
  activeConversationId,
  feedbackLoading,
  onOpenHistory,
  onOpenUserCenter,
  onPreferenceFeedback,
  onBehaviorEvent,
  onProfileReplace,
}: PreferenceProfileWorkbenchProps) {
  const [timeline, setTimeline] = useState<PreferenceTimelineItem[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [auditGroups, setAuditGroups] = useState<Record<AuditGroupBy, PreferenceAuditGroup[]>>({
    dimension: [],
    source: [],
    scope: [],
  });
  const [auditSummary, setAuditSummary] = useState<PreferenceAuditResult["summary"] | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditGroupBy, setAuditGroupBy] = useState<AuditGroupBy>("dimension");
  const [undoingEventId, setUndoingEventId] = useState<number | null>(null);
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all");
  const [actionFeedback, setActionFeedback] = useState<PreferenceActionFeedback | null>(null);
  const [activeSection, setActiveSection] = useState<MemorySectionKey>("overview");

  const overviewRef = useRef<HTMLElement | null>(null);
  const governanceRef = useRef<HTMLElement | null>(null);
  const auditRef = useRef<HTMLElement | null>(null);
  const timelineRef = useRef<HTMLElement | null>(null);
  const memoryTrackedRef = useRef(false);
  const auditTrackedRef = useRef(false);
  const governanceTrackedRef = useRef(false);

  const strength = resolveStrengthMeta(profile);
  const longTermProfile = profile?.long_term_profile || null;
  const sessionProfile = profile?.session_profile || null;
  const blacklistItems = profile?.blacklist_items || [];
  const lockedItems = profile?.locked_items || [];
  const favoriteCount = conversations.filter((item) => item.is_favorite).length;
  const cityCount = new Set(conversations.map((item) => item.destination_city).filter(Boolean)).size;
  const archivePreview = conversations.slice(0, 5);
  const lastUpdated = longTermProfile?.updated_at || profile?.updated_at || null;
  const latestUpdatedAt = lastUpdated ? formatDateTime(lastUpdated) : "尚未形成";
  const highlights = collectHighlights(longTermProfile || profile, 12);
  const longTermClusters = buildClusters(longTermProfile || profile);
  const sessionClusters = buildClusters(sessionProfile);
  const activeAuditGroups = auditGroups[auditGroupBy];

  const filteredTimeline = useMemo(() => {
    if (timelineFilter === "undoable") {
      return timeline.filter((item) => item.can_undo && !item.is_undone);
    }
    if (timelineFilter === "undone") {
      return timeline.filter((item) => item.is_undone);
    }
    return timeline;
  }, [timeline, timelineFilter]);

  const blacklistActionItems = useMemo(
    () => blacklistItems.map((item) => buildGovernanceActionItem(item, "negative")),
    [blacklistItems],
  );
  const lockedActionItems = useMemo(
    () => lockedItems.map((item) => buildGovernanceActionItem(item, "positive")),
    [lockedItems],
  );
  const governanceCandidateItems = useMemo(
    () => buildGovernanceCandidates(longTermProfile || profile, lockedItems, blacklistItems),
    [blacklistItems, lockedItems, longTermProfile, profile],
  );
  const lockedLookup = useMemo(
    () => new Set(lockedItems.map((item) => `${item.dimension}:${item.value}`)),
    [lockedItems],
  );
  const blacklistLookup = useMemo(
    () => new Set(blacklistItems.map((item) => `${item.dimension}:${item.value}`)),
    [blacklistItems],
  );

  useEffect(() => {
    memoryTrackedRef.current = false;
    auditTrackedRef.current = false;
    governanceTrackedRef.current = false;
  }, [activeConversationId, guestMode]);

  useEffect(() => {
    if (guestMode) {
      setTimeline([]);
      setTimelineError(null);
      setAuditGroups({ dimension: [], source: [], scope: [] });
      setAuditSummary(null);
      setAuditError(null);
      return;
    }
    void loadTimeline();
    void loadAudit();
  }, [guestMode, activeConversationId]);

  useEffect(() => {
    if (guestMode || memoryTrackedRef.current) return;
    memoryTrackedRef.current = true;
    void onBehaviorEvent({
      action: "memory_open",
      conversation_id: activeConversationId ?? null,
      payload: {
        title: "画像中心",
        summary: "用户打开画像中心查看长期偏好与历史沉淀。",
      },
    }).catch(() => undefined);
  }, [activeConversationId, guestMode, onBehaviorEvent]);

  useEffect(() => {
    if (guestMode || !auditSummary || auditTrackedRef.current) return;
    auditTrackedRef.current = true;
    void onBehaviorEvent({
      action: "audit_open",
      conversation_id: activeConversationId ?? null,
      payload: {
        title: "画像审计",
        summary: "用户打开审计视角复核偏好证据来源。",
        group_by: auditGroupBy,
      },
    }).catch(() => undefined);
  }, [activeConversationId, auditGroupBy, auditSummary, guestMode, onBehaviorEvent]);

  async function loadTimeline() {
    if (guestMode) return;
    setTimelineLoading(true);
    setTimelineError(null);
    try {
      const result = await fetchPreferenceTimeline(activeConversationId ?? null, 40);
      setTimeline(result.items);
    } catch {
      setTimelineError("画像时间线暂时无法加载。");
    } finally {
      setTimelineLoading(false);
    }
  }

  async function loadAudit() {
    if (guestMode) return;
    setAuditLoading(true);
    setAuditError(null);
    try {
      const result = await fetchPreferenceAudit(activeConversationId ?? null, 12);
      setAuditSummary(result.summary);
      setAuditGroups({
        dimension: result.by_dimension,
        source: result.by_source,
        scope: result.by_scope,
      });
    } catch {
      setAuditError("画像审计暂时无法加载。");
    } finally {
      setAuditLoading(false);
    }
  }

  async function handlePreferenceAction(payload: PreferenceFeedbackPayload) {
    await onPreferenceFeedback(payload);
    setActionFeedback(buildPreferenceFeedback(payload));
    await Promise.all([loadTimeline(), loadAudit()]);
    await maybeTrackGovernanceEvent(payload);
  }

  async function handleUndoTimelineItem(item: PreferenceTimelineItem) {
    setUndoingEventId(item.id);
    setTimelineError(null);
    try {
      const result = await undoPreferenceTimelineEvent({
        event_id: item.id,
        conversation_id: activeConversationId ?? null,
      });
      onProfileReplace(result.profile);
      setTimeline(result.timeline.items);
      await loadAudit();
      setActionFeedback({
        tone: "sun",
        title: "已撤销画像动作",
        detail: `${item.title} 已从画像学习链路中撤回，后续推荐会按新的状态重新校正。`,
        badge: "撤销完成",
        created_at: new Date().toISOString(),
      });
      await onBehaviorEvent({
        action: "timeline_undo",
        conversation_id: activeConversationId ?? null,
        payload: {
          title: item.title,
          summary: item.description,
          dimension: item.dimension,
          value: item.value,
          source_type: item.source_type,
        },
      }).catch(() => undefined);
    } catch {
      setTimelineError("撤销失败，请稍后重试。");
    } finally {
      setUndoingEventId(null);
    }
  }

  async function maybeTrackGovernanceEvent(payload: PreferenceFeedbackPayload) {
    if (guestMode) return;
    if (!governanceTrackedRef.current) {
      governanceTrackedRef.current = true;
      await onBehaviorEvent({
        action: "governance_open",
        conversation_id: activeConversationId ?? null,
        payload: {
          title: "偏好治理",
          summary: "用户开始进行显式的偏好治理操作。",
        },
      }).catch(() => undefined);
    }

    if (payload.action === "lock_long_term") {
      await onBehaviorEvent({
        action: "profile_lock",
        conversation_id: activeConversationId ?? null,
        payload: {
          title: payload.value,
          summary: "用户将该偏好锁定为长期偏好。",
          dimension: payload.dimension,
          value: payload.value,
        },
      }).catch(() => undefined);
    }

    if (payload.action === "unlock_long_term") {
      await onBehaviorEvent({
        action: "profile_unlock",
        conversation_id: activeConversationId ?? null,
        payload: {
          title: payload.value,
          summary: "用户解除了该长期偏好的锁定。",
          dimension: payload.dimension,
          value: payload.value,
        },
      }).catch(() => undefined);
    }

    if (payload.action === "remove_avoid") {
      await onBehaviorEvent({
        action: "blacklist_remove",
        conversation_id: activeConversationId ?? null,
        payload: {
          title: payload.value,
          summary: "用户将该项从黑名单中移除。",
          dimension: payload.dimension,
          value: payload.value,
        },
      }).catch(() => undefined);
    }
  }

  function jumpToSection(section: MemorySectionKey) {
    setActiveSection(section);
    const element = {
      overview: overviewRef.current,
      governance: governanceRef.current,
      audit: auditRef.current,
      timeline: timelineRef.current,
    }[section];
    element?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handleOpenGovernanceSection() {
    jumpToSection("governance");
    await maybeTrackGovernanceEvent({ action: "set_common", dimension: "destination", value: "治理入口" }).catch(() => undefined);
  }

  async function handleOpenAuditSection() {
    jumpToSection("audit");
    if (guestMode || auditTrackedRef.current) return;
    auditTrackedRef.current = true;
    await onBehaviorEvent({
      action: "audit_open",
      conversation_id: activeConversationId ?? null,
      payload: {
        title: "画像审计",
        summary: "用户从导航进入画像审计区。",
        group_by: auditGroupBy,
      },
    }).catch(() => undefined);
  }

  return (
    <div className="view-frame memory-page">
      <WorkspaceHero
        tone="memory"
        icon={<ShieldCheck size={16} />}
        kicker="旅行偏好画像中心"
        title={guestMode ? "游客会话不保存长期画像" : `${resolveUserName(currentUser)} 的旅行画像工作台`}
        description={
          guestMode
            ? "你仍然可以完成规划，但系统不会保存历史与长期偏好。"
            : profile?.recommendation_hint || "系统会把真实对话、方案编辑与决策动作沉淀成可复用的长期偏好。"
        }
        badges={highlights.length ? highlights.slice(0, 6) : ["等待更多交互", guestMode ? "游客模式" : "长期记忆在线"]}
        actions={(
          <>
            <button type="button" className="primary-action" onClick={onOpenUserCenter}>
              {guestMode ? <LogIn size={15} /> : <ShieldCheck size={15} />}
              {guestMode ? "登录并开启长期记忆" : "打开用户中心"}
            </button>
            <button type="button" className="secondary-action" onClick={onOpenHistory}>
              <Layers3 size={15} />
              打开历史中心
            </button>
          </>
        )}
        signals={(
          <div className="preference-studio-metrics">
            <MetricCard
              label="画像强度"
              value={strength.label}
              detail={guestMode ? "登录后开始沉淀" : strength.description}
              tone={strength.key === "strong" ? "rust" : strength.key === "growing" ? "rail" : "jade"}
            />
            <MetricCard
              label="最近更新"
              value={latestUpdatedAt}
              detail={`${profile?.recent_evidence.length || 0} 条近期证据`}
              tone="rail"
            />
            <MetricCard
              label="历史资产"
              value={guestMode ? "未保存" : `${conversations.length} 个会话`}
              detail={`${favoriteCount} 个收藏，覆盖 ${cityCount} 座城市`}
              tone="sun"
            />
          </div>
        )}
        visualEyebrow="偏好镜像"
        visualTitle={strength.label}
        visualDetail={
          guestMode
            ? "登录后系统会持续记录目的地、预算、交通与节奏偏好。"
            : `${timeline.length} 条时间线记录与 ${profile?.recent_evidence.length || 0} 条近期证据正在共同校正画像。`
        }
        visualMetrics={[
          { label: "收藏", value: String(favoriteCount) },
          { label: "覆盖城市", value: String(cityCount) },
          { label: "节奏偏好", value: longTermProfile?.pace_tags?.[0] || profile?.pace_tags?.[0] || "待学习" },
          { label: "兴趣主题", value: longTermProfile?.interest_tags?.[0] || profile?.interest_tags?.[0] || "待学习" },
        ]}
      />

      {actionFeedback && !guestMode ? (
        <section className={`page-band preference-live-band tone-${actionFeedback.tone}`}>
          <div className="preference-live-feedback">
            <div className="preference-live-feedback-head">
              <div className={`preference-live-dot tone-${actionFeedback.tone}`} />
              <strong>{actionFeedback.title}</strong>
              <span>{actionFeedback.badge}</span>
            </div>
            <p>{actionFeedback.detail}</p>
            <em>{formatDateTime(actionFeedback.created_at)}</em>
          </div>
          <div className="preference-live-actions">
            <button type="button" className="quiet-link-button" onClick={() => void loadTimeline()}>
              <RefreshCw size={14} />
              刷新时间线
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={() => setActionFeedback(null)}
              aria-label="关闭反馈卡片"
            >
              <X size={16} />
            </button>
          </div>
        </section>
      ) : null}

      {guestMode ? (
        <section className="page-band preference-guest-banner">
          <div className="band-head">
            <div className="section-kicker">
              <Sparkles size={15} />
              记忆权限
            </div>
            <span>游客会话只保留在当前浏览器。</span>
          </div>
          <div className="preference-guest-banner-grid">
            <article className="preference-guest-banner-card">
              <strong>现在可用</strong>
              <p>对话规划、列车查询、地图天气联动、攻略检索与联网增强搜索。</p>
            </article>
            <article className="preference-guest-banner-card">
              <strong>当前不保存</strong>
              <p>历史会话、方案版本、偏好画像、预算区间与行为学习证据。</p>
            </article>
            <article className="preference-guest-banner-card emphasis">
              <strong>登录后解锁</strong>
              <p>自动记住常去城市、交通偏好、旅行节奏、兴趣主题和明确避让项。</p>
            </article>
          </div>
        </section>
      ) : null}

      <section className="page-band memory-section-rail">
        <div className="band-head compact">
          <div className="section-kicker">
            <Compass size={15} />
            工作区导航
          </div>
          <span>把画像总览、治理、审计与时间线拆成明确层次，方便快速定位。</span>
        </div>
        <div className="memory-section-buttons" role="tablist" aria-label="画像中心分区导航">
          {(
            Object.entries(MEMORY_SECTION_META) as Array<[MemorySectionKey, { label: string; icon: ReactNode }]>
          ).map(([key, item]) => (
            <button
              type="button"
              key={key}
              className={`memory-section-button ${activeSection === key ? "active" : ""}`}
              onClick={() => {
                if (key === "governance") {
                  void handleOpenGovernanceSection();
                  return;
                }
                if (key === "audit") {
                  void handleOpenAuditSection();
                  return;
                }
                jumpToSection(key);
              }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <section ref={overviewRef} className="page-band preference-panel memory-overview-panel">
        <div className="band-head">
          <div className="section-kicker">
            <Compass size={15} />
            画像总览
          </div>
          <span>把长期偏好、本次偏好、黑名单和锁定项拆成四个独立层，避免混看。</span>
        </div>

        <div className="memory-overview-grid">
          <OverviewLayerCard
            title="长期偏好"
            subtitle="跨会话复用的稳定画像"
            emptyText="继续规划几次后，这里会形成稳定的长期偏好。"
            profile={longTermProfile}
            tone="jade"
            icon={<BrainCircuit size={16} />}
            mode="long_term"
            disabled={guestMode || feedbackLoading}
            lockedLookup={lockedLookup}
            blacklistLookup={blacklistLookup}
            onPreferenceFeedback={handlePreferenceAction}
          />
          <OverviewLayerCard
            title="本次偏好"
            subtitle="只对当前会话生效的临时约束"
            emptyText="当前会话还没有形成明确的本次偏好。"
            profile={sessionProfile}
            tone="rail"
            icon={<Compass size={16} />}
            mode="session"
            disabled={guestMode || feedbackLoading}
            lockedLookup={lockedLookup}
            blacklistLookup={blacklistLookup}
            onPreferenceFeedback={handlePreferenceAction}
          />
          <GovernanceBucketCard
            title="黑名单"
            subtitle="后续规划会主动降低这些选项的出现概率"
            tone="rust"
            icon={<ShieldAlert size={16} />}
            emptyText="目前没有明确的黑名单项。"
            items={blacklistActionItems}
            disabled={guestMode || feedbackLoading}
            actions={[
              {
                label: "恢复推荐",
                onClick: (item) => void handlePreferenceAction({
                  dimension: item.dimension,
                  value: item.value,
                  action: "remove_avoid",
                }),
              },
              {
                label: "仅本次",
                onClick: (item) => void handlePreferenceAction({
                  dimension: item.dimension,
                  value: item.value,
                  action: "session_only",
                  polarity: "negative",
                }),
              },
            ]}
          />
          <GovernanceBucketCard
            title="锁定项"
            subtitle="系统会优先保留这些长期偏好，不轻易被新信号稀释"
            tone="sun"
            icon={<LockKeyhole size={16} />}
            emptyText="目前还没有被锁定的长期偏好。"
            items={lockedActionItems}
            disabled={guestMode || feedbackLoading}
            actions={[
              {
                label: "解除锁定",
                onClick: (item) => void handlePreferenceAction({
                  dimension: item.dimension,
                  value: item.value,
                  action: "unlock_long_term",
                }),
              },
              {
                label: "移出长期",
                onClick: (item) => void handlePreferenceAction({
                  dimension: item.dimension,
                  value: item.value,
                  action: "remove_long_term",
                }),
              },
            ]}
          />
        </div>
      </section>

      {!guestMode ? (
        <>
          <section ref={governanceRef} className="page-band preference-panel preference-governance-panel">
            <div className="band-head">
              <div className="section-kicker">
                <ShieldCheck size={15} />
                治理台
              </div>
              <span>这里专门做显式治理，把候选偏好、黑名单与锁定项分开维护。</span>
            </div>

            <div className="preference-governance-strip">
              {governanceCandidateItems.length ? (
                governanceCandidateItems.map((item) => (
                  <article key={item.key} className="preference-governance-chip">
                    <div>
                      <strong>{item.title}</strong>
                      <span>{item.meta}</span>
                    </div>
                    <div className="preference-governance-chip-actions">
                      <button
                        type="button"
                        className="preference-governance-action"
                        disabled={feedbackLoading}
                        onClick={() => void handlePreferenceAction({
                          dimension: item.dimension,
                          value: item.value,
                          action: "set_common",
                        })}
                      >
                        设为常用
                      </button>
                      {item.dimension !== "avoidance" ? (
                        <button
                          type="button"
                          className="preference-governance-action"
                          disabled={feedbackLoading}
                          onClick={() => void handlePreferenceAction({
                            dimension: item.dimension,
                            value: item.value,
                            action: "lock_long_term",
                          })}
                        >
                          锁定
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="preference-governance-action negative"
                        disabled={feedbackLoading}
                        onClick={() => void handlePreferenceAction({
                          dimension: item.dimension,
                          value: item.value,
                          action: "avoid",
                        })}
                      >
                        不再推荐
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <div className="preference-empty-state">
                  当前没有新的治理候选项，系统已经把明显信号沉淀到四个画像层中。
                </div>
              )}
            </div>

            <div className="preference-correction-grid governance">
              <PreferenceActionField<EvidenceActionItem>
                title="锁定池"
                subtitle="适合长期保留、优先保护的稳定偏好"
                icon={<LockKeyhole size={16} />}
                emptyText="暂时没有锁定项。"
                items={lockedActionItems}
                tone="sun"
                disabled={feedbackLoading}
                actions={[
                  {
                    label: "解除锁定",
                    onClick: (item) => void handlePreferenceAction({
                      dimension: item.dimension,
                      value: item.value,
                      action: "unlock_long_term",
                    }),
                  },
                  {
                    label: "移出长期",
                    onClick: (item) => void handlePreferenceAction({
                      dimension: item.dimension,
                      value: item.value,
                      action: "remove_long_term",
                    }),
                  },
                ]}
              />
              <PreferenceActionField<EvidenceActionItem>
                title="黑名单池"
                subtitle="系统会主动避开这些内容或降低出现频次"
                icon={<ShieldAlert size={16} />}
                emptyText="暂时没有黑名单项。"
                items={blacklistActionItems}
                tone="rust"
                disabled={feedbackLoading}
                actions={[
                  {
                    label: "恢复推荐",
                    onClick: (item) => void handlePreferenceAction({
                      dimension: item.dimension,
                      value: item.value,
                      action: "remove_avoid",
                    }),
                  },
                  {
                    label: "仅本次",
                    onClick: (item) => void handlePreferenceAction({
                      dimension: item.dimension,
                      value: item.value,
                      action: "session_only",
                      polarity: "negative",
                    }),
                  },
                ]}
              />
            </div>
          </section>

          <section ref={auditRef} className="page-band preference-panel preference-audit-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Radar size={15} />
                审计区
              </div>
              <span>把每条偏好信号拆开检查，并直接在证据旁完成纠偏。</span>
            </div>

            <div className="preference-audit-summary-grid">
              <AuditSummaryCard label="总事件" value={String(auditSummary?.total_events || 0)} tone="jade" />
              <AuditSummaryCard label="长期信号" value={String(auditSummary?.long_term_total || 0)} tone="rail" />
              <AuditSummaryCard label="锁定项" value={String(auditSummary?.locked_total || 0)} tone="sun" />
              <AuditSummaryCard label="黑名单" value={String(auditSummary?.blacklist_total || 0)} tone="rust" />
            </div>

            <div className="preference-filter-row">
              <button
                type="button"
                className={`timeline-filter-button ${auditGroupBy === "dimension" ? "active" : ""}`}
                onClick={() => setAuditGroupBy("dimension")}
              >
                按维度
              </button>
              <button
                type="button"
                className={`timeline-filter-button ${auditGroupBy === "source" ? "active" : ""}`}
                onClick={() => setAuditGroupBy("source")}
              >
                按来源
              </button>
              <button
                type="button"
                className={`timeline-filter-button ${auditGroupBy === "scope" ? "active" : ""}`}
                onClick={() => setAuditGroupBy("scope")}
              >
                按作用域
              </button>
            </div>

            {auditError ? <div className="preference-timeline-error">{auditError}</div> : null}

            <div className="preference-audit-groups">
              {auditLoading ? (
                <div className="preference-empty-state">正在加载画像审计数据...</div>
              ) : activeAuditGroups.length ? (
                activeAuditGroups.map((group) => (
                  <AuditGroupCard
                    key={group.key}
                    group={group}
                    disabled={feedbackLoading}
                    onPreferenceFeedback={handlePreferenceAction}
                  />
                ))
              ) : (
                <div className="preference-empty-state">当前还没有可审计的偏好证据。</div>
              )}
            </div>
          </section>

          <section ref={timelineRef} className="page-band preference-panel preference-timeline-panel">
            <div className="band-head">
              <div className="section-kicker">
                <History size={15} />
                时间线
              </div>
              <span>记录每一次画像学习、治理与撤销，支持按需回看与回退。</span>
            </div>

            <div className="preference-timeline-toolbar">
              <div className="preference-filter-row">
                <button
                  type="button"
                  className={`timeline-filter-button ${timelineFilter === "all" ? "active" : ""}`}
                  onClick={() => setTimelineFilter("all")}
                >
                  全部
                </button>
                <button
                  type="button"
                  className={`timeline-filter-button ${timelineFilter === "undoable" ? "active" : ""}`}
                  onClick={() => setTimelineFilter("undoable")}
                >
                  可撤销
                </button>
                <button
                  type="button"
                  className={`timeline-filter-button ${timelineFilter === "undone" ? "active" : ""}`}
                  onClick={() => setTimelineFilter("undone")}
                >
                  已撤销
                </button>
              </div>
              <button type="button" className="quiet-link-button" onClick={() => void loadTimeline()}>
                <RefreshCw size={14} />
                刷新
              </button>
            </div>

            {timelineError ? <div className="preference-timeline-error">{timelineError}</div> : null}

            <div className="preference-timeline-list">
              {timelineLoading ? (
                <div className="preference-empty-state">正在加载时间线...</div>
              ) : filteredTimeline.length ? (
                filteredTimeline.map((item) => (
                  <article className={`preference-timeline-item ${item.is_undone ? "is-undone" : ""}`} key={item.id}>
                    <div className="preference-timeline-main">
                      <div className="preference-timeline-meta">
                        <div className={`preference-scope-pill scope-${item.scope}`}>{resolveScopeLabel(item.scope)}</div>
                        <em>{resolveDimensionLabel(item.dimension)}</em>
                        <span>{resolveSourceLabel(item.source_type)}</span>
                        <span>{formatDateTime(item.created_at)}</span>
                      </div>
                      <strong>{item.title}</strong>
                      <p>{item.description}</p>
                      <div className="preference-timeline-badges">
                        <span>{item.signal_count} 次信号累计</span>
                        {item.conversation_id ? <span className="is-muted">会话内记录</span> : null}
                      </div>
                    </div>
                    <div className="preference-timeline-actions">
                      {item.can_undo && !item.is_undone ? (
                        <button
                          type="button"
                          className="timeline-undo-button"
                          disabled={undoingEventId === item.id}
                          onClick={() => void handleUndoTimelineItem(item)}
                        >
                          <RotateCcw size={14} />
                          {undoingEventId === item.id ? "撤销中" : "撤销"}
                        </button>
                      ) : (
                        <div className="timeline-readonly-badge">
                          {item.is_undone ? "已撤销" : "只读"}
                        </div>
                      )}
                    </div>
                  </article>
                ))
              ) : (
                <div className="preference-empty-state">当前筛选条件下还没有时间线记录。</div>
              )}
            </div>
          </section>

          <section className="page-band preference-panel preference-budget-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Wallet size={15} />
                预算模型
              </div>
              <span>预算不是静态标签，而是随每次规划持续修正的区间判断。</span>
            </div>

            <div className="preference-budget-grid">
              <BudgetStat label="常用预算" value={profile?.budget_range || "待学习"} />
              <BudgetStat
                label="中位预算"
                value={longTermProfile?.budget_profile?.median ? `${longTermProfile.budget_profile.median} 元` : "待学习"}
              />
              <BudgetStat
                label="波动区间"
                value={
                  longTermProfile?.budget_profile?.lower_bound != null && longTermProfile?.budget_profile?.upper_bound != null
                    ? `${longTermProfile.budget_profile.lower_bound} - ${longTermProfile.budget_profile.upper_bound} 元`
                    : "待学习"
                }
              />
              <BudgetStat label="敏感度" value={longTermProfile?.budget_profile?.sensitivity || "待学习"} />
            </div>
          </section>

          <section className="page-band preference-panel">
            <div className="band-head">
              <div className="section-kicker">
                <CalendarClock size={15} />
                最近档案
              </div>
              <span>这些历史方案会持续反馈给后续推荐与画像收敛。</span>
            </div>

            <div className="preference-archive-list">
              {archivePreview.length ? (
                archivePreview.map((conversation) => (
                  <article key={conversation.id} className="preference-archive-item">
                    <div>
                      <strong>{conversation.title || "未命名会话"}</strong>
                      <span>{conversation.destination_city || "待定目的地"}</span>
                    </div>
                    <em>{conversation.version_count} 个版本</em>
                  </article>
                ))
              ) : (
                <div className="preference-empty-state">当前还没有可回放的历史规划。</div>
              )}
            </div>
          </section>
        </>
      ) : null}

      <PreferenceProfileSnapshot
        profile={profile}
        title="画像摘要"
        subtitle="给历史中心、用户中心和其他工作页复用的轻量概览。"
        emptyText="继续规划几次之后，这里会形成更完整的长期偏好摘要。"
        showEvidence
      />
    </div>
  );
}

function OverviewLayerCard({
  title,
  subtitle,
  emptyText,
  profile,
  tone,
  icon,
  mode,
  disabled,
  lockedLookup,
  blacklistLookup,
  onPreferenceFeedback,
}: {
  title: string;
  subtitle: string;
  emptyText: string;
  profile: PreferenceProfileLike;
  tone: PreferenceTone;
  icon: ReactNode;
  mode: "long_term" | "session";
  disabled: boolean;
  lockedLookup: Set<string>;
  blacklistLookup: Set<string>;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
}) {
  const strength = resolveStrengthMeta(profile);
  const clusters = mode === "long_term" ? buildClusters(profile) : buildClusters(profile).filter((item) => item.values.length);

  return (
    <article className={`page-band profile-layer-card tone-${tone}`}>
      <div className="profile-layer-head">
        <div className="profile-layer-title">
          <div className={`profile-layer-icon tone-${tone}`}>{icon}</div>
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
        <div className={`preference-strength-pill ${strength.key}`}>{strength.label}</div>
      </div>

      <p className="profile-layer-summary">{profile?.recommendation_hint || emptyText}</p>

      <div className="profile-layer-meta">
        <div>
          <span>预算</span>
          <strong>{profile?.budget_range || "待学习"}</strong>
        </div>
        <div>
          <span>证据</span>
          <strong>{profile?.recent_evidence.length || 0} 条</strong>
        </div>
        <div>
          <span>显式信号</span>
          <strong>{profile?.explicit_preferences.length || 0} 项</strong>
        </div>
      </div>

      <div className="preference-cluster-grid premium">
        {clusters.map((cluster) => (
          <PreferenceClusterCard
            key={cluster.id}
            cluster={cluster}
            disabled={disabled}
            mode={mode}
            lockedLookup={lockedLookup}
            blacklistLookup={blacklistLookup}
            onPreferenceFeedback={onPreferenceFeedback}
          />
        ))}
      </div>
    </article>
  );
}

function GovernanceBucketCard({
  title,
  subtitle,
  tone,
  icon,
  emptyText,
  items,
  disabled,
  actions,
}: {
  title: string;
  subtitle: string;
  tone: PreferenceTone;
  icon: ReactNode;
  emptyText: string;
  items: EvidenceActionItem[];
  disabled: boolean;
  actions: PreferenceActionDefinition<EvidenceActionItem>[];
}) {
  return (
    <article className={`page-band profile-layer-card tone-${tone}`}>
      <div className="profile-layer-head">
        <div className="profile-layer-title">
          <div className={`profile-layer-icon tone-${tone}`}>{icon}</div>
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
      </div>

      <PreferenceActionField
        title={title}
        subtitle={subtitle}
        icon={icon}
        emptyText={emptyText}
        items={items}
        tone={tone}
        disabled={disabled}
        actions={actions}
      />
    </article>
  );
}

export function PreferenceProfileSnapshot({
  profile,
  title = "偏好画像摘要",
  subtitle,
  emptyText = "当前还没有足够多的历史规划来沉淀稳定偏好。",
  showEvidence = false,
  compact = false,
}: PreferenceProfileSnapshotProps) {
  const strength = resolveStrengthMeta(profile);
  const highlights = collectHighlights(profile, compact ? 6 : 10);

  return (
    <section className={`page-band profile-snapshot ${compact ? "compact" : ""}`}>
      <div className="band-head">
        <div className="section-kicker">
          <Sparkles size={15} />
          {title}
        </div>
        <span>{subtitle || "把系统当前理解到的旅行偏好收束成一段简明摘要。"}</span>
      </div>

      <div className="profile-snapshot-header">
        <div>
          <strong>{profile?.recommendation_hint || emptyText}</strong>
          <p>{strength.description}</p>
        </div>
        <span className={`preference-strength-pill ${strength.key}`}>{strength.label}</span>
      </div>

      <div className="profile-snapshot-metrics">
        <div>
          <span>预算</span>
          <strong>{profile?.budget_range || "待学习"}</strong>
        </div>
        <div>
          <span>负向偏好</span>
          <strong>{profile?.negative_preferences.length || 0} 项</strong>
        </div>
        <div>
          <span>近期证据</span>
          <strong>{profile?.recent_evidence.length || 0} 条</strong>
        </div>
      </div>

      <div className="profile-snapshot-tags">
        {highlights.length ? highlights.map((item) => <span key={item}>{item}</span>) : <span className="is-empty">等待更多交互</span>}
      </div>

      {profile?.negative_preferences.length ? (
        <div className="profile-snapshot-negative">
          {profile.negative_preferences.slice(0, compact ? 2 : 4).map((item) => (
            <em key={item}>避免 {stripAvoidPrefix(item)}</em>
          ))}
        </div>
      ) : null}

      {showEvidence && profile?.recent_evidence.length ? (
        <div className="profile-snapshot-evidence">
          {profile.recent_evidence.slice(0, compact ? 2 : 3).map((item, index) => (
            <div key={`${item.dimension}-${item.value}-${index}`} className="profile-snapshot-evidence-item">
              <strong>{renderEvidenceHeadline(item.dimension, item.value, item.polarity)}</strong>
              <span>
                {resolveSourceLabel(item.source_type)} · {formatDateTime(item.created_at)}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: PreferenceTone;
}) {
  return (
    <article className={`preference-pulse-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </article>
  );
}

function BudgetStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="preference-budget-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AuditSummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: PreferenceTone;
}) {
  return (
    <article className={`audit-summary-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function PreferenceClusterCard({
  cluster,
  disabled,
  mode,
  lockedLookup,
  blacklistLookup,
  onPreferenceFeedback,
}: {
  cluster: ClusterConfig;
  disabled: boolean;
  mode: "long_term" | "session";
  lockedLookup: Set<string>;
  blacklistLookup: Set<string>;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
}) {
  const buildActions = (value: string): PreferenceActionDefinition<string>[] => {
    const lookupKey = `${cluster.dimension}:${value}`;
    const isLocked = lockedLookup.has(lookupKey);
    const isBlacklisted = blacklistLookup.has(lookupKey);
    const actions: PreferenceActionDefinition<string>[] = [];

    if (cluster.dimension !== "avoidance") {
      actions.push({
        label: "设为常用",
        onClick: (item) => void onPreferenceFeedback({ dimension: cluster.dimension, value: item, action: "set_common" }),
      });
    }

    actions.push({
      label: "仅本次",
      onClick: (item) => void onPreferenceFeedback({
        dimension: cluster.dimension,
        value: item,
        action: "session_only",
        polarity: cluster.dimension === "avoidance" ? "negative" : "positive",
      }),
    });

    if (mode === "long_term") {
      actions.push({
        label: "移出长期",
        onClick: (item) => void onPreferenceFeedback({ dimension: cluster.dimension, value: item, action: "remove_long_term" }),
      });
    }

    if (cluster.dimension !== "avoidance" && mode === "long_term") {
      actions.push({
        label: isLocked ? "解除锁定" : "锁定",
        onClick: (item) => void onPreferenceFeedback({
          dimension: cluster.dimension,
          value: item,
          action: isLocked ? "unlock_long_term" : "lock_long_term",
        }),
      });
    }

    actions.push({
      label: isBlacklisted ? "恢复推荐" : "不再推荐",
      tone: "negative",
      onClick: (item) => void onPreferenceFeedback({
        dimension: cluster.dimension,
        value: item,
        action: isBlacklisted ? "remove_avoid" : "avoid",
      }),
    });

    return actions;
  };

  return (
    <article className={`preference-cluster-card tone-${cluster.tone}`}>
      <div className="preference-cluster-head">
        <div className="preference-cluster-icon">{cluster.icon}</div>
        <div>
          <strong>{cluster.title}</strong>
          <span>{cluster.subtitle}</span>
        </div>
      </div>

      <div className="preference-chip-cloud">
        {cluster.values.length ? (
          cluster.values.map((item) => {
            const lookupKey = `${cluster.dimension}:${item}`;
            const isLocked = lockedLookup.has(lookupKey);
            const isBlacklisted = blacklistLookup.has(lookupKey);

            return (
              <div key={item} className="preference-chip">
                <div className="preference-chip-main">
                  <span>{item}</span>
                  <div className="preference-chip-state-row">
                    {isLocked ? <em className="state-lock">已锁定</em> : null}
                    {isBlacklisted ? <em className="state-avoid">黑名单</em> : null}
                  </div>
                </div>
                <div className="preference-chip-actions">
                  {buildActions(item).map((action) => (
                    <button
                      type="button"
                      key={`${item}-${action.label}`}
                      className={`preference-chip-btn ${action.tone === "negative" ? "negative" : ""}`}
                      disabled={disabled}
                      onClick={() => action.onClick(item)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })
        ) : (
          <div className="preference-empty-state">还在持续学习中</div>
        )}
      </div>
    </article>
  );
}

function PreferenceActionField<T extends string | EvidenceActionItem>({
  title,
  subtitle,
  icon,
  emptyText,
  items,
  tone,
  disabled,
  actions,
}: {
  title: string;
  subtitle: string;
  icon: ReactNode;
  emptyText: string;
  items: T[];
  tone: PreferenceTone;
  disabled: boolean;
  actions: PreferenceActionDefinition<T>[];
}) {
  return (
    <article className={`preference-action-field tone-${tone}`}>
      <div className="preference-action-head">
        <div className="preference-action-icon">{icon}</div>
        <div>
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>
      </div>

      <div className="preference-action-list">
        {items.length ? (
          items.map((item) => {
            const key = typeof item === "string" ? item : item.key;
            const titleText = typeof item === "string" ? item : item.title;
            const metaText = typeof item === "string" ? null : item.meta;
            return (
              <div key={key} className="preference-action-item">
                <div className="preference-action-copy">
                  <strong>{titleText}</strong>
                  {metaText ? <span>{metaText}</span> : null}
                </div>
                <div className="preference-action-buttons">
                  {actions.map((action) => (
                    <button
                      type="button"
                      key={action.label}
                      className={action.tone === "negative" ? "negative" : ""}
                      disabled={disabled}
                      onClick={() => action.onClick(item)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })
        ) : (
          <div className="preference-empty-state">{emptyText}</div>
        )}
      </div>
    </article>
  );
}

function AuditGroupCard({
  group,
  disabled,
  onPreferenceFeedback,
}: {
  group: PreferenceAuditGroup;
  disabled: boolean;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
}) {
  return (
    <article className="preference-audit-group-card">
      <div className="preference-audit-group-head">
        <strong>{group.label}</strong>
        <span>{group.total} 条信号</span>
      </div>
      <div className="preference-audit-item-stack">
        {group.items.map((item, index) => (
          <div key={`${group.key}-${item.dimension}-${item.value}-${index}`} className="preference-audit-item">
            <div className="preference-audit-item-main">
              <strong>{item.display_value || item.value}</strong>
              <span>
                {item.dimension_label} · {item.source_label} · {resolveScopeLabel(item.scope)} · {formatDateTime(item.created_at)}
              </span>
              {item.note ? <p>{item.note}</p> : null}
            </div>
            <div className="preference-audit-side">
              <div className="preference-audit-badges">
                <em>{item.polarity === "negative" ? "负向信号" : "正向信号"}</em>
                {item.is_locked ? <em className="lock">已锁定</em> : null}
                {item.is_blacklisted ? <em className="blacklist">黑名单</em> : null}
                {item.is_undone ? <em>已撤销</em> : null}
              </div>
              <div className="preference-audit-actions">
                {buildAuditQuickActions(item, onPreferenceFeedback).map((action) => (
                  <button
                    type="button"
                    key={`${item.dimension}-${item.value}-${action.label}`}
                    className={action.tone === "negative" ? "negative" : ""}
                    disabled={disabled || item.is_undone}
                    onClick={() => action.onClick(item)}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}

function buildAuditQuickActions(
  item: PreferenceAuditItem,
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>,
): PreferenceActionDefinition<PreferenceAuditItem>[] {
  const actions: PreferenceActionDefinition<PreferenceAuditItem>[] = [];

  if (item.dimension !== "avoidance") {
    actions.push({
      label: "设为常用",
      onClick: (target) => void onPreferenceFeedback({
        dimension: target.dimension,
        value: target.value,
        action: "set_common",
      }),
    });
  }

  actions.push({
    label: "仅本次",
    onClick: (target) => void onPreferenceFeedback({
      dimension: target.dimension,
      value: target.value,
      action: "session_only",
      polarity: target.polarity === "negative" ? "negative" : "positive",
    }),
  });

  actions.push({
    label: item.is_blacklisted ? "恢复推荐" : "不再推荐",
    tone: "negative",
    onClick: (target) => void onPreferenceFeedback({
      dimension: target.dimension,
      value: target.value,
      action: target.is_blacklisted ? "remove_avoid" : "avoid",
    }),
  });

  if (item.dimension !== "avoidance") {
    actions.push({
      label: item.is_locked ? "解除锁定" : "锁定",
      onClick: (target) => void onPreferenceFeedback({
        dimension: target.dimension,
        value: target.value,
        action: target.is_locked ? "unlock_long_term" : "lock_long_term",
      }),
    });
  }

  return actions;
}

function buildGovernanceActionItem(
  item: PreferenceGovernanceItem,
  polarity: "positive" | "negative",
): EvidenceActionItem {
  return {
    key: `${item.dimension}-${item.value}-${item.source_type}`,
    title: item.label,
    meta: `${resolveDimensionLabel(item.dimension)} · ${formatDateTime(item.created_at)}`,
    dimension: item.dimension,
    value: item.value,
    polarity,
  };
}

function buildGovernanceCandidates(
  profile: PreferenceProfileLike,
  lockedItems: PreferenceGovernanceItem[],
  blacklistItems: PreferenceGovernanceItem[],
): EvidenceActionItem[] {
  if (!profile) return [];

  const lockedSet = new Set(lockedItems.map((item) => `${item.dimension}:${item.value}`));
  const blacklistSet = new Set(blacklistItems.map((item) => `${item.dimension}:${item.value}`));

  const candidates: EvidenceActionItem[] = [
    ...profile.preferred_cities.map((value) => ({
      key: `destination:${value}`,
      title: value,
      meta: "目的地偏好",
      dimension: "destination",
      value,
      polarity: "positive",
    })),
    ...profile.transport_modes.map((value) => ({
      key: `transport:${value}`,
      title: value,
      meta: "交通方式",
      dimension: "transport",
      value,
      polarity: "positive",
    })),
    ...profile.pace_tags.map((value) => ({
      key: `pace:${value}`,
      title: value,
      meta: "旅行节奏",
      dimension: "pace",
      value,
      polarity: "positive",
    })),
    ...profile.interest_tags.map((value) => ({
      key: `interest:${value}`,
      title: value,
      meta: "兴趣主题",
      dimension: "interest",
      value,
      polarity: "positive",
    })),
  ];

  return candidates
    .filter((item) => !lockedSet.has(`${item.dimension}:${item.value}`) && !blacklistSet.has(`${item.dimension}:${item.value}`))
    .slice(0, 8);
}

function buildClusters(profile: PreferenceProfileLike): ClusterConfig[] {
  // 把分散字段整理成稳定的工作台分区，方便多页面复用。
  return [
    {
      id: "cities",
      title: "目的地偏好",
      subtitle: "你反复选择或更容易被打动的城市",
      dimension: "destination",
      values: profile?.preferred_cities || [],
      tone: "jade",
      icon: <MapPinned size={16} />,
    },
    {
      id: "transport",
      title: "交通方式",
      subtitle: "更偏爱的出行方式与换乘习惯",
      dimension: "transport",
      values: profile?.transport_modes || [],
      tone: "rail",
      icon: <TrainFront size={16} />,
    },
    {
      id: "pace",
      title: "旅行节奏",
      subtitle: "可接受的行程密度、强度与时间安排",
      dimension: "pace",
      values: profile?.pace_tags || [],
      tone: "sun",
      icon: <Activity size={16} />,
    },
    {
      id: "interest",
      title: "兴趣主题",
      subtitle: "更愿意为之投入预算与时间的体验方向",
      dimension: "interest",
      values: profile?.interest_tags || [],
      tone: "rust",
      icon: <HeartHandshake size={16} />,
    },
  ];
}

function collectHighlights(profile: PreferenceProfileLike, limit: number): string[] {
  // 只保留最有辨识度的一组特征，避免摘要面板变成信息墙。
  if (!profile) return [];

  const merged = [
    ...profile.preferred_cities,
    ...profile.transport_modes,
    ...profile.pace_tags,
    ...profile.interest_tags,
    ...profile.explicit_preferences,
    ...profile.inferred_preferences,
  ];

  return Array.from(new Set(merged.filter(Boolean))).slice(0, limit);
}

function resolveStrengthMeta(profile: PreferenceProfileLike) {
  const key = strengthKey(profile);
  return { key, ...STRENGTH_META[key] };
}

function strengthKey(profile: PreferenceProfileLike): keyof typeof STRENGTH_META {
  const key = profile?.profile_strength;
  if (key === "strong" || key === "growing" || key === "new") return key;
  return "new";
}

function resolveUserName(user: LocalUser | null) {
  return user?.display_name || user?.username || "当前用户";
}

function resolveSourceLabel(sourceType: string) {
  return SOURCE_LABELS[sourceType] || sourceType;
}

function resolveDimensionLabel(dimension: string) {
  return DIMENSION_LABELS[dimension] || dimension;
}

function resolveScopeLabel(scope: string) {
  if (scope === "session") return "本次";
  if (scope === "behavior") return "行为";
  return "长期";
}

function renderEvidenceHeadline(dimension: string, value: string, polarity: string) {
  if (polarity === "negative") {
    return `避免 ${stripAvoidPrefix(value)}`;
  }
  if (polarity === "neutral") {
    return `移出长期偏好 · ${value}`;
  }
  return `${resolveDimensionLabel(dimension)} · ${value}`;
}

function stripAvoidPrefix(value: string) {
  return value.replace(/^避免/, "").trim();
}

function formatDateTime(value: string) {
  // 统一压缩成适合工作台阅读的短时间格式。
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function buildPreferenceFeedback(payload: PreferenceFeedbackPayload): PreferenceActionFeedback {
  const value = payload.dimension === "avoidance" ? stripAvoidPrefix(payload.value) : payload.value;

  if (payload.action === "session_only") {
    return {
      tone: "rail",
      title: payload.polarity === "negative" ? "已设为本次避让" : "已设为本次偏好",
      detail: `${value} 只会作用于当前这次规划，不会直接沉淀成长期画像。`,
      badge: "本次生效",
      created_at: new Date().toISOString(),
    };
  }

  if (payload.action === "avoid") {
    return {
      tone: "rust",
      title: "已加入不再推荐",
      detail: `${value} 会被优先视为避让项，后续方案会主动减少相关推荐。`,
      badge: "负向纠偏",
      created_at: new Date().toISOString(),
    };
  }

  if (payload.action === "remove_avoid") {
    return {
      tone: "sun",
      title: "已恢复推荐",
      detail: `${value} 已从黑名单中移除，系统会重新把它纳入候选池。`,
      badge: "治理回退",
      created_at: new Date().toISOString(),
    };
  }

  if (payload.action === "remove_long_term") {
    return {
      tone: "sun",
      title: "已移出长期偏好",
      detail: `${value} 不再作为稳定长期偏好参与后续个性化推荐。`,
      badge: "长期降权",
      created_at: new Date().toISOString(),
    };
  }

  if (payload.action === "lock_long_term") {
    return {
      tone: "sun",
      title: "已锁定长期偏好",
      detail: `${value} 会被优先保护，系统不会轻易被短期信号带偏。`,
      badge: "长期锁定",
      created_at: new Date().toISOString(),
    };
  }

  if (payload.action === "unlock_long_term") {
    return {
      tone: "rail",
      title: "已解除锁定",
      detail: `${value} 将重新参与正常的画像收敛逻辑。`,
      badge: "解除锁定",
      created_at: new Date().toISOString(),
    };
  }

  return {
    tone: "jade",
    title: "已设为常用偏好",
    detail: `${value} 会被系统视为更稳定的长期偏好，在后续规划中优先参考。`,
    badge: "长期生效",
    created_at: new Date().toISOString(),
  };
}
