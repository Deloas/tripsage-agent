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
  Route,
  ShieldCheck,
  Sparkles,
  TrainFront,
  Wallet,
} from "lucide-react";

import type { ConversationSummary, LocalUser, PreferenceProfile } from "../lib/types";

interface PreferenceProfileWorkbenchProps {
  guestMode: boolean;
  currentUser: LocalUser | null;
  conversations: ConversationSummary[];
  profile: PreferenceProfile | null;
  onOpenHistory: () => void;
  onOpenUserCenter: () => void;
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
  values: string[];
  tone: PreferenceTone;
  icon: ReactNode;
};

const STRENGTH_META = {
  new: {
    label: "初步学习",
    description: "画像刚开始形成，系统会继续从真实对话和决策行为中学习。",
    ratio: 0.34,
  },
  growing: {
    label: "持续收敛",
    description: "画像已经出现稳定方向，后续会更主动给出贴合你习惯的建议。",
    ratio: 0.68,
  },
  strong: {
    label: "稳定画像",
    description: "系统已经掌握较稳定的旅行口味，可作为长期个性化基础。",
    ratio: 1,
  },
} as const;

const SOURCE_LABELS: Record<string, string> = {
  user_message: "显式表达",
  trip_slots: "结构化槽位",
  decision_module: "决策采纳",
  edited_plan: "行程编辑",
  railway_workspace: "铁路行为",
  user_profile: "用户资料",
  legacy_profile: "历史画像",
};

const DIMENSION_LABELS: Record<string, string> = {
  destination: "目的地",
  transport: "交通方式",
  pace: "旅行节奏",
  interest: "兴趣偏好",
  budget: "预算区间",
  budget_style: "预算风格",
};

export function PreferenceProfileWorkbench({
  guestMode,
  currentUser,
  conversations,
  profile,
  onOpenHistory,
  onOpenUserCenter,
}: PreferenceProfileWorkbenchProps) {
  const strength = resolveStrengthMeta(profile);
  const favoriteCount = conversations.filter((item) => item.is_favorite).length;
  const cityCount = new Set(conversations.map((item) => item.destination_city).filter(Boolean)).size;
  const latestUpdatedAt = profile?.updated_at ? formatDateTime(profile.updated_at) : "尚未形成";
  const archivePreview = conversations.slice(0, 5);
  const clusters = buildClusters(profile);

  return (
    <div className="view-frame memory-page">
      <section className="page-band memory-hero-band preference-hero-band">
        <div>
          <div className="section-kicker">
            <ShieldCheck size={16} />
            偏好画像中心
          </div>
          <h2>
            {guestMode
              ? "游客模式不会沉淀长期记忆"
              : `${currentUser?.display_name || currentUser?.username || "当前用户"} 的旅行偏好情报台`}
          </h2>
          <p>
            {guestMode
              ? "登录后系统才会把真实对话、行程修改、铁路选择和模块采纳行为沉淀为长期偏好画像。"
              : profile?.recommendation_hint || "系统会依据你的真实规划行为逐步建立更稳定、更可解释的个性化画像。"}
          </p>
          <div className="overview-action-row">
            <button type="button" className="primary-action" onClick={onOpenUserCenter}>
              {guestMode ? <LogIn size={15} /> : <ShieldCheck size={15} />}
              {guestMode ? "登录并保存" : "打开用户中心"}
            </button>
            <button type="button" className="secondary-action" onClick={onOpenHistory}>
              <Layers3 size={15} />
              打开历史中心
            </button>
          </div>
        </div>

        <div className="preference-hero-metrics">
          <article className="preference-metric-card">
            <span>画像强度</span>
            <strong>{strength.label}</strong>
            <em>{guestMode ? "游客不保存" : strength.description}</em>
          </article>
          <article className="preference-metric-card">
            <span>最近学习</span>
            <strong>{latestUpdatedAt}</strong>
            <em>{profile?.recent_evidence.length || 0} 条新证据</em>
          </article>
          <article className="preference-metric-card">
            <span>历史资产</span>
            <strong>{guestMode ? "未保存" : `${conversations.length} 个会话`}</strong>
            <em>{favoriteCount} 个收藏，覆盖 {cityCount} 座城市</em>
          </article>
        </div>
      </section>

      {guestMode ? (
        <section className="page-band preference-guest-lock">
          <div className="band-head">
            <div className="section-kicker">
              <Sparkles size={15} />
              记忆权限
            </div>
            <span>游客会话只保留在当前浏览器，不生成长期画像。</span>
          </div>
          <div className="preference-guest-lock-grid">
            <article className="preference-guest-lock-card">
              <strong>可体验</strong>
              <p>即时提问、生成行程、查看车次、使用联网增强与地图天气工具。</p>
            </article>
            <article className="preference-guest-lock-card">
              <strong>不会保存</strong>
              <p>历史会话、版本回溯、用户偏好画像、长期预算模型与行为证据。</p>
            </article>
            <article className="preference-guest-lock-card emphasis">
              <strong>登录后解锁</strong>
              <p>系统会自动学习你的城市倾向、预算区间、节奏偏好、交通习惯与负向偏好。</p>
            </article>
          </div>
        </section>
      ) : null}

      <div className="preference-workbench-grid">
        <div className="preference-column">
          <section className="page-band">
            <div className="band-head">
              <div className="section-kicker">
                <Compass size={15} />
                核心偏好簇
              </div>
              <span>把城市、交通、节奏与兴趣拆成可读的长期偏好结构。</span>
            </div>
            <div className="preference-cluster-grid">
              {clusters.map((cluster) => (
                <PreferenceClusterCard key={cluster.id} cluster={cluster} />
              ))}
            </div>
          </section>

          <section className="page-band preference-intelligence-band">
            <div className="band-head">
              <div className="section-kicker">
                <BrainCircuit size={15} />
                学习来源
              </div>
              <span>把系统“为什么这样判断”清楚地摊开。</span>
            </div>
            <div className="preference-signal-board">
              <PreferenceSignalColumn
                title="显式表达"
                subtitle="用户在对话里直接说出的偏好"
                values={profile?.explicit_preferences || []}
                tone="jade"
              />
              <PreferenceSignalColumn
                title="推断偏好"
                subtitle="从历史规划与上下文稳定归纳出的倾向"
                values={profile?.inferred_preferences || []}
                tone="rail"
              />
              <PreferenceSignalColumn
                title="行为信号"
                subtitle="来自编辑、采纳与铁路选择的真实动作"
                values={profile?.behavior_signals || []}
                tone="sun"
              />
            </div>
            <div className="preference-negative-board">
              <div className="band-head compact">
                <div className="section-kicker">
                  <Route size={15} />
                  负向偏好
                </div>
                <span>这些内容会被系统优先避让。</span>
              </div>
              <div className="preference-negative-list">
                {(profile?.negative_preferences || []).length ? (
                  profile?.negative_preferences.map((item) => (
                    <div key={item} className="preference-negative-item">
                      <span>避免</span>
                      <strong>{item}</strong>
                    </div>
                  ))
                ) : (
                  <div className="preference-empty-state">当前还没有形成明确的避让偏好。</div>
                )}
              </div>
            </div>
          </section>

          <section className="page-band preference-evidence-band">
            <div className="band-head">
              <div className="section-kicker">
                <DatabaseZap size={15} />
                最近证据
              </div>
              <span>最近几次真实交互是如何推动画像收敛的。</span>
            </div>
            <div className="preference-evidence-list">
              {profile?.recent_evidence?.length ? (
                profile.recent_evidence.map((item, index) => (
                  <article
                    key={`${item.dimension}-${item.value}-${item.created_at}-${index}`}
                    className={`preference-evidence-item ${item.polarity === "negative" ? "negative" : ""}`}
                  >
                    <div className="preference-evidence-top">
                      <strong>{renderEvidenceHeadline(item.dimension, item.value, item.polarity)}</strong>
                      <span>{formatDateTime(item.created_at)}</span>
                    </div>
                    <p>{resolveDimensionLabel(item.dimension)} · {resolveSourceLabel(item.source_type)}</p>
                    <div className="preference-evidence-meta">
                      <em>置信 {Math.round(item.confidence * 100)}%</em>
                      <em>权重 {item.weight.toFixed(2)}</em>
                    </div>
                  </article>
                ))
              ) : (
                <div className="preference-empty-state">
                  还没有可展示的近期证据，继续对话、编辑行程或采纳决策模块后会自动出现。
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="preference-column">
          <section className="page-band preference-strength-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Activity size={15} />
                画像状态
              </div>
              <span>当前画像成熟度与长期个性化准备度。</span>
            </div>
            <div className="preference-strength-badge-row">
              <strong>{strength.label}</strong>
              <span>{guestMode ? "登录后开始累计" : strength.description}</span>
            </div>
            <div className="preference-strength-track">
              <div className="preference-strength-progress" style={{ width: `${strength.ratio * 100}%` }} />
              {(["new", "growing", "strong"] as const).map((item) => (
                <div key={item} className={`preference-strength-step ${strengthKey(profile) === item ? "active" : ""}`}>
                  <span />
                  <strong>{STRENGTH_META[item].label}</strong>
                </div>
              ))}
            </div>
            <div className="preference-strength-foot">
              系统会把“说过什么”和“实际怎么选”同时纳入画像，这让个性化建议不再只靠一句自述。
            </div>
          </section>

          <section className="page-band preference-budget-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Wallet size={15} />
                预算模型
              </div>
              <span>预算不是一行标签，而是可持续更新的区间判断。</span>
            </div>
            <div className="preference-budget-grid">
              <div className="preference-budget-stat">
                <span>常用预算</span>
                <strong>{profile?.budget_range || "待学习"}</strong>
              </div>
              <div className="preference-budget-stat">
                <span>中位预算</span>
                <strong>{profile?.budget_profile?.median ? `¥${profile.budget_profile.median}` : "待学习"}</strong>
              </div>
              <div className="preference-budget-stat">
                <span>波动区间</span>
                <strong>
                  {profile?.budget_profile?.lower_bound && profile?.budget_profile?.upper_bound
                    ? `¥${profile.budget_profile.lower_bound} - ¥${profile.budget_profile.upper_bound}`
                    : "待学习"}
                </strong>
              </div>
              <div className="preference-budget-stat">
                <span>敏感度</span>
                <strong>{profile?.budget_profile?.sensitivity || "待学习"}</strong>
              </div>
            </div>
          </section>

          <section className="page-band preference-archive-panel">
            <div className="band-head">
              <div className="section-kicker">
                <CalendarClock size={15} />
                最近档案
              </div>
              <span>这些历史会话会继续反哺偏好学习与下次规划。</span>
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
                <div className="preference-empty-state">当前还没有可回溯的历史会话。</div>
              )}
            </div>
          </section>

          <PreferenceProfileSnapshot
            profile={profile}
            title="画像摘要"
            subtitle="给用户中心、历史中心和后续多端复用的轻量摘要视图。"
            emptyText="暂未形成稳定画像，继续规划几次后会自动出现。"
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
        <span>{subtitle || "把系统当前理解到的偏好收束成一个简明可读的摘要。"}</span>
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
        {highlights.length ? (
          highlights.map((item) => <span key={item}>{item}</span>)
        ) : (
          <span className="is-empty">等待更多交互</span>
        )}
      </div>

      {profile?.negative_preferences.length ? (
        <div className="profile-snapshot-negative">
          {profile.negative_preferences.slice(0, compact ? 2 : 4).map((item) => (
            <em key={item}>避免 {item}</em>
          ))}
        </div>
      ) : null}

      {showEvidence && profile?.recent_evidence.length ? (
        <div className="profile-snapshot-evidence">
          {profile.recent_evidence.slice(0, compact ? 2 : 3).map((item, index) => (
            <div key={`${item.dimension}-${item.value}-${index}`} className="profile-snapshot-evidence-item">
              <strong>{renderEvidenceHeadline(item.dimension, item.value, item.polarity)}</strong>
              <span>{resolveSourceLabel(item.source_type)} · {formatDateTime(item.created_at)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function PreferenceClusterCard({ cluster }: { cluster: ClusterConfig }) {
  return (
    <article className={`preference-cluster-card tone-${cluster.tone}`}>
      <div className="preference-cluster-head">
        <div className="preference-cluster-icon">{cluster.icon}</div>
        <div>
          <strong>{cluster.title}</strong>
          <span>{cluster.subtitle}</span>
        </div>
      </div>
      <div className="preference-pill-row">
        {cluster.values.length ? (
          cluster.values.map((item) => (
            <span key={item} className="preference-pill">
              {item}
            </span>
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

function buildClusters(profile: PreferenceProfile | null): ClusterConfig[] {
  // 把分散的偏好字段组织成稳定的产品信息架构，便于前端多端复用。
  return [
    {
      id: "cities",
      title: "目的地偏好",
      subtitle: "更常被你反复选择或回访的城市",
      values: profile?.preferred_cities || [],
      tone: "jade",
      icon: <MapPinned size={16} />,
    },
    {
      id: "transport",
      title: "交通方式",
      subtitle: "出行方式与换乘习惯",
      values: profile?.transport_modes || [],
      tone: "rail",
      icon: <TrainFront size={16} />,
    },
    {
      id: "pace",
      title: "旅行节奏",
      subtitle: "偏轻松、紧凑或错峰的行程节奏",
      values: profile?.pace_tags || [],
      tone: "sun",
      icon: <Activity size={16} />,
    },
    {
      id: "interest",
      title: "兴趣主题",
      subtitle: "你更愿意为哪些体验留出时间",
      values: profile?.interest_tags || [],
      tone: "rust",
      icon: <HeartHandshake size={16} />,
    },
  ];
}

function collectHighlights(profile: PreferenceProfile | null, limit: number): string[] {
  // 摘要视图只保留最有辨识度的一组偏好，避免信息噪音。
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
  return {
    key,
    ...STRENGTH_META[key],
  };
}

function strengthKey(profile: PreferenceProfile | null): keyof typeof STRENGTH_META {
  const key = profile?.profile_strength;
  if (key === "strong" || key === "growing" || key === "new") {
    return key;
  }
  return "new";
}

function resolveSourceLabel(sourceType: string) {
  return SOURCE_LABELS[sourceType] || sourceType;
}

function resolveDimensionLabel(dimension: string) {
  return DIMENSION_LABELS[dimension] || dimension;
}

function renderEvidenceHeadline(dimension: string, value: string, polarity: string) {
  if (polarity === "negative") {
    return `避免 ${value}`;
  }
  return `${resolveDimensionLabel(dimension)}：${value}`;
}

function formatDateTime(value: string) {
  // 统一把时间压缩成适合工作台阅读的短格式。
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
