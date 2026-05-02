import type { ReactNode } from "react";
import {
  Activity,
  BrainCircuit,
  CalendarClock,
  Compass,
  DatabaseZap,
  HeartHandshake,
  Layers3,
  LogIn,
  MapPinned,
  Radar,
  Route,
  ShieldCheck,
  Sparkles,
  TrainFront,
  Wallet,
} from "lucide-react";

import type {
  ConversationSummary,
  LocalUser,
  PreferenceFeedbackPayload,
  PreferenceProfile,
} from "../lib/types";
import { WorkspaceHero } from "./WorkspaceHero";

interface PreferenceProfileWorkbenchProps {
  guestMode: boolean;
  currentUser: LocalUser | null;
  conversations: ConversationSummary[];
  profile: PreferenceProfile | null;
  feedbackLoading: boolean;
  onOpenHistory: () => void;
  onOpenUserCenter: () => void;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
}

interface PreferenceProfileSnapshotProps {
  profile: PreferenceProfile | null;
  title?: string;
  subtitle?: string;
  emptyText?: string;
  showEvidence?: boolean;
  compact?: boolean;
}

type PreferenceTone = "jade" | "rail" | "rust" | "sun";

type ClusterConfig = {
  id: string;
  title: string;
  subtitle: string;
  dimension: PreferenceFeedbackPayload["dimension"];
  values: string[];
  tone: PreferenceTone;
  icon: ReactNode;
};

const STRENGTH_META = {
  new: {
    label: "初步学习",
    description: "画像刚开始形成，系统会继续从真实对话、方案调整和工具选择里学习。",
    ratio: 0.34,
  },
  growing: {
    label: "持续收敛",
    description: "已经出现稳定方向，后续推荐会明显更贴近你的路线、节奏和预算习惯。",
    ratio: 0.68,
  },
  strong: {
    label: "稳定画像",
    description: "系统已经掌握较稳定的长期偏好，可作为下一次自动规划的个性化基础。",
    ratio: 1,
  },
} as const;

const SOURCE_LABELS: Record<string, string> = {
  user_message: "对话直述",
  profile_setting: "资料设定",
  manual_prefer: "人工确认",
  manual_avoid: "人工避让",
  trip_signal: "结构化行程",
  decision_accept: "模块采纳",
  decision_ignore: "模块忽略",
  itinerary_edit: "行程编辑",
  railway_selection: "铁路选择",
  legacy_profile: "历史画像",
};

const DIMENSION_LABELS: Record<string, string> = {
  destination: "目的地",
  transport: "交通方式",
  pace: "旅行节奏",
  interest: "兴趣主题",
  avoidance: "避让偏好",
  budget: "预算",
  budget_style: "预算风格",
  behavior: "行为信号",
  risk: "风险偏好",
};

export function PreferenceProfileWorkbench({
  guestMode,
  currentUser,
  conversations,
  profile,
  feedbackLoading,
  onOpenHistory,
  onOpenUserCenter,
  onPreferenceFeedback,
}: PreferenceProfileWorkbenchProps) {
  const strength = resolveStrengthMeta(profile);
  const favoriteCount = conversations.filter((item) => item.is_favorite).length;
  const cityCount = new Set(conversations.map((item) => item.destination_city).filter(Boolean)).size;
  const archivePreview = conversations.slice(0, 5);
  const latestUpdatedAt = profile?.updated_at ? formatDateTime(profile.updated_at) : "尚未形成";
  const clusters = buildClusters(profile);
  const highlights = collectHighlights(profile, 12);

  return (
    <div className="view-frame memory-page">
      <WorkspaceHero
        tone="memory"
        icon={<ShieldCheck size={16} />}
        kicker="旅行偏好画像中心"
        title={guestMode ? "游客会话不沉淀长期记忆" : `${resolveUserName(currentUser)} 的偏好画像中心`}
        description={guestMode ? "当前仍可完整规划，但系统不会保存历史与长期偏好。" : profile?.recommendation_hint || "系统会把真实选择沉淀成可持续学习的长期偏好。"}
        badges={highlights.length ? highlights.slice(0, 6) : ["等待更多交互", guestMode ? "游客会话" : "长期记忆在线"]}
        actions={(
          <>
            <button type="button" className="primary-action" onClick={onOpenUserCenter}>
              {guestMode ? <LogIn size={15} /> : <ShieldCheck size={15} />}
              {guestMode ? "登录并开启长期记忆" : "打开用户中心"}
            </button>
            <button type="button" className="secondary-action" onClick={onOpenHistory}>
              <Layers3 size={15} />
              打开历史规划中心
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
              label="最近学习"
              value={latestUpdatedAt}
              detail={`${profile?.recent_evidence.length || 0} 条近端证据`}
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
        visualDetail={guestMode ? "登录后会持续记录目的地、预算、交通与节奏偏好。" : `${profile?.recent_evidence.length || 0} 条近端证据正在持续校正画像。`}
        visualMetrics={[
          { label: "收藏", value: String(favoriteCount) },
          { label: "覆盖城市", value: String(cityCount) },
          { label: "节奏偏好", value: profile?.pace_tags?.[0] || "待学习" },
          { label: "兴趣主题", value: profile?.interest_tags?.[0] || "待学习" },
        ]}
      />

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
              <p>对话规划、列车查询、地图天气联动、攻略检索、联网增强搜索。</p>
            </article>
            <article className="preference-guest-banner-card">
              <strong>本次不保存</strong>
              <p>历史会话、方案版本、偏好画像、预算区间和行为学习证据。</p>
            </article>
            <article className="preference-guest-banner-card emphasis">
              <strong>登录后解锁</strong>
              <p>自动记住常去城市、交通偏好、旅行节奏、兴趣主题和明确避让项。</p>
            </article>
          </div>
        </section>
      ) : null}

      <div className="preference-studio-grid">
        <div className="preference-studio-column main">
          <section className="page-band preference-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Compass size={15} />
                核心偏好簇
              </div>
                <span>画像字段可直接确认或纠偏。</span>
            </div>

            <div className="preference-cluster-grid premium">
              {clusters.map((cluster) => (
                <PreferenceClusterCard
                  key={cluster.id}
                  cluster={cluster}
                  disabled={guestMode || feedbackLoading}
                  onPreferenceFeedback={onPreferenceFeedback}
                />
              ))}
            </div>
          </section>

          <section className="page-band preference-panel">
            <div className="band-head">
              <div className="section-kicker">
                <BrainCircuit size={15} />
                纠偏控制台
              </div>
              <span>
                {feedbackLoading
                  ? "正在回写新的偏好权重，稍等片刻。"
                  : "点击“长期偏好”或“标记避让”后会立即更新画像。"}
              </span>
            </div>

            <div className="preference-correction-grid">
              <PreferenceActionField
                title="明确避让"
                subtitle="这些内容会在后续规划里优先回避。"
                icon={<Route size={16} />}
                emptyText="还没有形成明确的避让项。"
                items={profile?.negative_preferences || []}
                tone="rust"
                disabled={guestMode || feedbackLoading}
                onPromote={(value) => onPreferenceFeedback({ dimension: "avoidance", value: stripAvoidPrefix(value), polarity: "negative" })}
                onInvert={(value) => onPreferenceFeedback({ dimension: "avoidance", value: stripAvoidPrefix(value), polarity: "positive" })}
                promoteLabel="保持避让"
                invertLabel="改成接受"
              />

              <PreferenceActionField
                title="最近证据"
                subtitle="最近几次真实交互是怎么影响画像的，一眼就能看见。"
                icon={<DatabaseZap size={16} />}
                emptyText="继续对话、编辑行程或采纳模块建议后，这里会自动出现。"
                items={(profile?.recent_evidence || []).map((item, index) => ({
                  key: `${item.dimension}-${item.value}-${item.created_at}-${index}`,
                  title: renderEvidenceHeadline(item.dimension, item.value, item.polarity),
                  meta: `${resolveSourceLabel(item.source_type)} · ${formatDateTime(item.created_at)}`,
                  dimension: item.dimension,
                  value: item.value,
                  polarity: item.polarity,
                }))}
                tone="rail"
                disabled={guestMode || feedbackLoading}
                promoteLabel="设为长期偏好"
                invertLabel="标记为避让"
                onPromote={(item) =>
                  onPreferenceFeedback({
                    dimension: item.dimension,
                    value: item.value,
                    polarity: "positive",
                  })
                }
                onInvert={(item) =>
                  onPreferenceFeedback({
                    dimension: item.dimension,
                    value: item.value,
                    polarity: "negative",
                  })
                }
              />
            </div>
          </section>

          <section className="page-band preference-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Radar size={15} />
                学习来源
              </div>
              <span>告诉你系统为何会形成当前判断，减少黑盒感。</span>
            </div>

            <div className="preference-signal-board">
              <PreferenceSignalColumn
                title="显式表达"
                subtitle="你在对话里直接说出来的偏好。"
                values={profile?.explicit_preferences || []}
                tone="jade"
              />
              <PreferenceSignalColumn
                title="推断偏好"
                subtitle="从历史规划和上下文持续归纳出的倾向。"
                values={profile?.inferred_preferences || []}
                tone="rail"
              />
              <PreferenceSignalColumn
                title="行为信号"
                subtitle="来自行程编辑、模块采纳与列车选择的真实动作。"
                values={profile?.behavior_signals || []}
                tone="sun"
              />
            </div>
          </section>
        </div>

        <div className="preference-studio-column side">
          <section className="page-band preference-panel preference-strength-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Activity size={15} />
                画像状态
              </div>
              <span>当前画像的成熟度，以及它对后续规划的影响范围。</span>
            </div>

            <div className="preference-strength-hero">
              <strong>{strength.label}</strong>
              <p>{guestMode ? "登录后系统才会开始沉淀并积累可复用偏好。" : strength.description}</p>
            </div>

            <div className="preference-strength-track">
              <div className="preference-strength-progress" style={{ width: `${strength.ratio * 100}%` }} />
              {(["new", "growing", "strong"] as const).map((item) => (
                <div key={item} className={`preference-strength-step ${strength.key === item ? "active" : ""}`}>
                  <span />
                  <strong>{STRENGTH_META[item].label}</strong>
                </div>
              ))}
            </div>

            <div className="preference-strength-note">
              系统会同时吸收“你说了什么”和“你最后怎么选”，这比只靠一轮聊天更适合做长期个性化推荐。
            </div>
          </section>

          <section className="page-band preference-panel preference-budget-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Wallet size={15} />
                预算模型
              </div>
              <span>预算不是一条死标签，而是会随着新行程持续更新的区间判断。</span>
            </div>

            <div className="preference-budget-grid">
              <BudgetStat label="常用预算" value={profile?.budget_range || "待学习"} />
              <BudgetStat
                label="中位预算"
                value={profile?.budget_profile?.median ? `${profile.budget_profile.median} 元` : "待学习"}
              />
              <BudgetStat
                label="波动区间"
                value={
                  profile?.budget_profile?.lower_bound && profile?.budget_profile?.upper_bound
                    ? `${profile.budget_profile.lower_bound} - ${profile.budget_profile.upper_bound} 元`
                    : "待学习"
                }
              />
              <BudgetStat label="敏感度" value={profile?.budget_profile?.sensitivity || "待学习"} />
            </div>
          </section>

          <section className="page-band preference-panel">
            <div className="band-head">
              <div className="section-kicker">
                <CalendarClock size={15} />
                最近档案
              </div>
              <span>这些历史会持续反哺后续推荐和画像收敛。</span>
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
                <div className="preference-empty-state">当前还没有可回溯的历史规划。</div>
              )}
            </div>
          </section>

          <PreferenceProfileSnapshot
            profile={profile}
            title="画像摘要"
            subtitle="给用户中心、历史中心和其他工作页复用的轻量概览。"
            emptyText="继续规划几次之后，这里会形成更稳定的长期偏好摘要。"
            showEvidence
          />
        </div>
      </div>
    </div>
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
        <span>{subtitle || "把系统当前理解到的旅行偏好收束成一段简明摘要。"} </span>
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

function PreferenceClusterCard({
  cluster,
  disabled,
  onPreferenceFeedback,
}: {
  cluster: ClusterConfig;
  disabled: boolean;
  onPreferenceFeedback: (payload: PreferenceFeedbackPayload) => Promise<void>;
}) {
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
          cluster.values.map((item) => (
            <div key={item} className="preference-chip">
              <div className="preference-chip-main">
                <span>{item}</span>
              </div>
              <div className="preference-chip-actions">
                <button
                  type="button"
                  className="preference-chip-btn"
                  disabled={disabled}
                  onClick={() =>
                    void onPreferenceFeedback({
                      dimension: cluster.dimension,
                      value: item,
                      polarity: "positive",
                    })
                  }
                >
                  长期偏好
                </button>
                <button
                  type="button"
                  className="preference-chip-btn negative"
                  disabled={disabled}
                  onClick={() =>
                    void onPreferenceFeedback({
                      dimension: cluster.dimension,
                      value: item,
                      polarity: "negative",
                    })
                  }
                >
                  标记避让
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="preference-empty-state">还在持续学习中</div>
        )}
      </div>
    </article>
  );
}

function PreferenceSignalColumn({
  title,
  subtitle,
  values,
  tone,
}: {
  title: string;
  subtitle: string;
  values: string[];
  tone: PreferenceTone;
}) {
  return (
    <article className={`preference-signal-column tone-${tone}`}>
      <div className="preference-signal-head">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <div className="preference-signal-stack">
        {values.length ? (
          values.map((item) => (
            <div key={item} className="preference-signal-card">
              {item}
            </div>
          ))
        ) : (
          <div className="preference-empty-state">尚未积累到足够信号</div>
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
  promoteLabel,
  invertLabel,
  onPromote,
  onInvert,
}: {
  title: string;
  subtitle: string;
  icon: ReactNode;
  emptyText: string;
  items: T[];
  tone: PreferenceTone;
  disabled: boolean;
  promoteLabel: string;
  invertLabel: string;
  onPromote: (item: T) => void;
  onInvert: (item: T) => void;
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
                  <button type="button" disabled={disabled} onClick={() => onPromote(item)}>
                    {promoteLabel}
                  </button>
                  <button type="button" className="negative" disabled={disabled} onClick={() => onInvert(item)}>
                    {invertLabel}
                  </button>
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

type EvidenceActionItem = {
  key: string;
  title: string;
  meta: string;
  dimension: string;
  value: string;
  polarity: string;
};

function buildClusters(profile: PreferenceProfile | null): ClusterConfig[] {
  // 把零散字段整理成稳定的信息架构，方便前端多工作页复用。
  return [
    {
      id: "cities",
      title: "目的地偏好",
      subtitle: "你反复选择或更容易被打动的城市。",
      dimension: "destination",
      values: profile?.preferred_cities || [],
      tone: "jade",
      icon: <MapPinned size={16} />,
    },
    {
      id: "transport",
      title: "交通方式",
      subtitle: "你更偏爱的出行方式与换乘习惯。",
      dimension: "transport",
      values: profile?.transport_modes || [],
      tone: "rail",
      icon: <TrainFront size={16} />,
    },
    {
      id: "pace",
      title: "旅行节奏",
      subtitle: "你能接受怎样的密度、强度与时间安排。",
      dimension: "pace",
      values: profile?.pace_tags || [],
      tone: "sun",
      icon: <Activity size={16} />,
    },
    {
      id: "interest",
      title: "兴趣主题",
      subtitle: "你更愿意为哪些体验留出预算和时间。",
      dimension: "interest",
      values: profile?.interest_tags || [],
      tone: "rust",
      icon: <HeartHandshake size={16} />,
    },
  ];
}

function collectHighlights(profile: PreferenceProfile | null, limit: number): string[] {
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

function resolveStrengthMeta(profile: PreferenceProfile | null) {
  const key = strengthKey(profile);
  return { key, ...STRENGTH_META[key] };
}

function strengthKey(profile: PreferenceProfile | null): keyof typeof STRENGTH_META {
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

function renderEvidenceHeadline(dimension: string, value: string, polarity: string) {
  if (polarity === "negative") {
    return `避免 ${stripAvoidPrefix(value)}`;
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
