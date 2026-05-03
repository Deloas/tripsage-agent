import { useEffect, useMemo, useState } from "react";
import {
  CalendarRange,
  Clock3,
  Filter,
  Heart,
  History,
  Layers3,
  MapPinned,
  Save,
  Search,
  ShieldCheck,
  Star,
  Tags,
  Trash2,
  Wallet,
  X,
} from "lucide-react";

import type { ConversationSummary, ConversationUpdatePayload, PreferenceProfile } from "../lib/types";
import { PreferenceProfileSnapshot } from "./PreferenceProfileWorkbench";

interface HistoryCenterProps {
  open: boolean;
  conversations: ConversationSummary[];
  profile: PreferenceProfile | null;
  guestMode: boolean;
  onClose: () => void;
  onOpenUserCenter: () => void;
  onOpenConversation: (conversationId: string) => void;
  onUpdateConversation: (conversationId: string, payload: ConversationUpdatePayload) => Promise<void>;
  onDeleteConversation: (conversationId: string) => Promise<void>;
}

type BudgetFilter = "all" | "light" | "balanced" | "comfort" | "premium";
type TimeFilter = "all" | "near" | "weekend" | "holiday" | "dated";
type ArchiveView = "all" | "recent" | "favorites" | "cities";

interface ArchiveDraft {
  title: string;
  destination_city: string;
  budget: string;
  start_date: string;
  tags: string;
}

interface CityTopic {
  city: string;
  count: number;
  favoriteCount: number;
  latestAt: string;
}

const EMPTY_DRAFT: ArchiveDraft = {
  title: "",
  destination_city: "",
  budget: "",
  start_date: "",
  tags: "",
};

export function HistoryCenter({
  open,
  conversations,
  profile,
  guestMode,
  onClose,
  onOpenUserCenter,
  onOpenConversation,
  onUpdateConversation,
  onDeleteConversation,
}: HistoryCenterProps) {
  const [keyword, setKeyword] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [cityFilter, setCityFilter] = useState("all");
  const [budgetFilter, setBudgetFilter] = useState<BudgetFilter>("all");
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all");
  const [activeTag, setActiveTag] = useState("all");
  const [viewMode, setViewMode] = useState<ArchiveView>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [topicCity, setTopicCity] = useState("all");
  const [draft, setDraft] = useState<ArchiveDraft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const cityTopics = useMemo(() => buildCityTopics(conversations), [conversations]);
  const cityOptions = useMemo(
    () => Array.from(new Set(conversations.map((item) => item.destination_city || "").filter(Boolean))),
    [conversations],
  );
  const profileTags = useMemo(
    () => [
      ...(profile?.preferred_cities || []),
      ...(profile?.transport_modes || []),
      ...(profile?.pace_tags || []),
      ...(profile?.interest_tags || []),
      ...(profile?.budget_range ? [profile.budget_range] : []),
    ],
    [profile],
  );
  const tagOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [
            ...conversations.flatMap((item) => item.tags || []),
            ...profileTags,
          ].filter(Boolean),
        ),
      ).slice(0, 18),
    [conversations, profileTags],
  );
  const recentConversations = conversations.slice(0, 8);
  const favoriteConversations = conversations.filter((item) => item.is_favorite);

  const filteredConversations = conversations.filter((item) => {
    if (favoritesOnly && !item.is_favorite) return false;
    if (cityFilter !== "all" && item.destination_city !== cityFilter) return false;
    if (activeTag !== "all" && !(item.tags || []).includes(activeTag)) return false;
    if (!matchesBudgetFilter(item.budget, budgetFilter)) return false;
    if (!matchesTimeFilter(item.start_date, timeFilter)) return false;

    if (!keyword.trim()) return true;
    const haystack = [
      item.title || "",
      item.latest_message || "",
      item.destination_city || "",
      item.start_date || "",
      ...(item.tags || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(keyword.trim().toLowerCase());
  });

  const scopedConversations = scopeByView(filteredConversations, viewMode, topicCity);
  const selectedConversation =
    scopedConversations.find((item) => item.id === selectedId)
    || filteredConversations.find((item) => item.id === selectedId)
    || conversations.find((item) => item.id === selectedId)
    || null;

  useEffect(() => {
    if (!open) return;
    setSelectedId((current) => {
      if (current && conversations.some((item) => item.id === current)) {
        return current;
      }
      return conversations[0]?.id || null;
    });
  }, [conversations, open]);

  useEffect(() => {
    if (!cityTopics.length) {
      setTopicCity("all");
      return;
    }
    setTopicCity((current) => {
      if (current !== "all" && cityTopics.some((item) => item.city === current)) {
        return current;
      }
      return cityTopics[0].city;
    });
  }, [cityTopics]);

  useEffect(() => {
    if (!selectedConversation) {
      setDraft(EMPTY_DRAFT);
      setConfirmDelete(false);
      return;
    }
    setDraft({
      title: selectedConversation.title || "",
      destination_city: selectedConversation.destination_city || "",
      budget: selectedConversation.budget != null ? String(selectedConversation.budget) : "",
      start_date: selectedConversation.start_date || "",
      tags: (selectedConversation.tags || []).join("，"),
    });
    setConfirmDelete(false);
  }, [selectedConversation]);

  useEffect(() => {
    if (!scopedConversations.length) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !scopedConversations.some((item) => item.id === selectedId)) {
      setSelectedId(scopedConversations[0].id);
    }
  }, [scopedConversations, selectedId]);

  if (!open) return null;

  async function handleSave() {
    if (!selectedConversation) return;
    setSaving(true);
    try {
      await onUpdateConversation(selectedConversation.id, {
        title: draft.title.trim() || selectedConversation.title || "未命名规划",
        destination_city: draft.destination_city.trim() || null,
        budget: draft.budget.trim() ? Number(draft.budget.trim()) : null,
        start_date: draft.start_date.trim() || null,
        tags: parseTags(draft.tags),
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleFavorite(item: ConversationSummary) {
    await onUpdateConversation(item.id, { is_favorite: !item.is_favorite });
  }

  async function handleDelete() {
    if (!selectedConversation) return;
    setDeleting(true);
    try {
      await onDeleteConversation(selectedConversation.id);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  function handleChangeCityFilter(value: string) {
    setCityFilter(value);
    if (viewMode === "cities") {
      setTopicCity(value === "all" ? cityTopics[0]?.city || "all" : value);
    }
  }

  if (guestMode) {
    return (
      <div className="modal-backdrop">
        <section className="history-center history-center-expanded archive-hub-shell" role="dialog" aria-modal="true" aria-label="历史规划中心">
          <div className="modal-header">
            <div>
              <div className="section-kicker">
                <History size={16} />
                历史规划中心
              </div>
              <h2>游客模式不会保存历史方案与画像沉淀</h2>
            </div>
            <button className="icon-button" onClick={onClose} aria-label="关闭">
              <X size={18} />
            </button>
          </div>

          <section className="archive-guest-lock">
            <div className="archive-guest-lock-copy">
              <div className="section-kicker">
                <ShieldCheck size={15} />
                历史资产权限
              </div>
              <strong>登录后自动保存会话、收藏、城市专题与后续可编辑版本。</strong>
              <p>当前会话仍可正常规划，但刷新后不会留下历史档案，也不会进入画像学习。</p>
            </div>
            <div className="archive-guest-lock-actions">
              <button type="button" className="primary-action" onClick={onOpenUserCenter}>
                登录并保存本次规划
              </button>
              <button type="button" className="secondary-action" onClick={onClose}>
                先继续体验
              </button>
            </div>
          </section>
        </section>
      </div>
    );
  }

  return (
    <div className="modal-backdrop">
      <section className="history-center history-center-expanded archive-hub-shell" role="dialog" aria-modal="true" aria-label="历史规划中心">
        <div className="modal-header">
          <div>
            <div className="section-kicker">
              <History size={16} />
              历史规划中心
            </div>
            <h2>把会话、收藏、城市专题和可编辑档案统一收纳在一个产品级历史中枢</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        <section className="archive-hub-hero">
          <div className="archive-hub-hero-main">
            <div className="section-kicker">
              <Layers3 size={15} />
              旅行档案库
            </div>
            <strong>{favoriteConversations.length ? "重点方案、长期偏好与最近主题都已经沉淀在这里" : "从第一条有效规划开始，系统会逐渐形成你的旅行档案库"}</strong>
            <p>左侧做检索与筛选，右侧做档案编辑与继续规划，城市专题会自动按真实历史聚合。</p>
          </div>
          <PreferenceProfileSnapshot
            profile={profile}
            compact
            title="偏好摘要"
            subtitle="历史中心会同步参考当前长期偏好。"
            emptyText="继续规划几次之后，这里会形成稳定的偏好摘要。"
          />
        </section>

        <section className="archive-hub-stats">
          <div>
            <span>总会话</span>
            <strong>{conversations.length}</strong>
          </div>
          <div>
            <span>已收藏</span>
            <strong>{favoriteConversations.length}</strong>
          </div>
          <div>
            <span>覆盖城市</span>
            <strong>{cityTopics.length}</strong>
          </div>
          <div>
            <span>可筛标签</span>
            <strong>{tagOptions.length}</strong>
          </div>
        </section>

        <div className="archive-hub-switch" role="tablist" aria-label="历史视图">
          <button type="button" className={viewMode === "all" ? "active" : ""} onClick={() => setViewMode("all")}>
            <Layers3 size={15} />
            全部档案
          </button>
          <button type="button" className={viewMode === "recent" ? "active" : ""} onClick={() => setViewMode("recent")}>
            <Clock3 size={15} />
            最近更新
          </button>
          <button type="button" className={viewMode === "favorites" ? "active" : ""} onClick={() => setViewMode("favorites")}>
            <Heart size={15} />
            收藏夹
          </button>
          <button type="button" className={viewMode === "cities" ? "active" : ""} onClick={() => setViewMode("cities")}>
            <MapPinned size={15} />
            城市专题
          </button>
        </div>

        <div className="archive-hub-layout">
          <section className="archive-hub-browser">
            <div className="archive-hub-overview-grid">
              <button type="button" className="archive-hub-overview-card" onClick={() => setViewMode("recent")}>
                <span>最近更新</span>
                <strong>{recentConversations.length}</strong>
                <p>{recentConversations[0]?.title || "最近还没有新规划"}</p>
              </button>
              <button type="button" className="archive-hub-overview-card" onClick={() => setViewMode("favorites")}>
                <span>收藏方案</span>
                <strong>{favoriteConversations.length}</strong>
                <p>{favoriteConversations[0]?.title || "优先保留重点方案"}</p>
              </button>
              <button type="button" className="archive-hub-overview-card" onClick={() => setViewMode("cities")}>
                <span>城市专题</span>
                <strong>{cityTopics.length}</strong>
                <p>{cityTopics[0]?.city ? `${cityTopics[0].city} 等城市已经形成专题` : "等待更多目的地积累"}</p>
              </button>
            </div>

            <div className="history-toolbar">
              <label className="history-search">
                <Search size={16} />
                <input
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  placeholder="搜索城市、标题、标签或摘要"
                />
              </label>
              <button
                type="button"
                className={`history-toggle ${favoritesOnly ? "active" : ""}`}
                onClick={() => setFavoritesOnly((current) => !current)}
              >
                <Star size={15} />
                只看收藏
              </button>
            </div>

            <div className="history-filter-row">
              <label className="history-select">
                <Filter size={15} />
                <select value={cityFilter} onChange={(event) => handleChangeCityFilter(event.target.value)}>
                  <option value="all">全部城市</option>
                  {cityOptions.map((city) => (
                    <option key={city} value={city}>{city}</option>
                  ))}
                </select>
              </label>
              <label className="history-select">
                <Wallet size={15} />
                <select value={budgetFilter} onChange={(event) => setBudgetFilter(event.target.value as BudgetFilter)}>
                  <option value="all">全部预算</option>
                  <option value="light">1000 以下</option>
                  <option value="balanced">1000 - 2999</option>
                  <option value="comfort">3000 - 5999</option>
                  <option value="premium">6000 以上</option>
                </select>
              </label>
              <label className="history-select">
                <CalendarRange size={15} />
                <select value={timeFilter} onChange={(event) => setTimeFilter(event.target.value as TimeFilter)}>
                  <option value="all">全部时间</option>
                  <option value="near">近期出行</option>
                  <option value="weekend">周末出行</option>
                  <option value="holiday">假期出行</option>
                  <option value="dated">已定日期</option>
                </select>
              </label>
            </div>

            <div className="archive-tag-strip">
              <button
                type="button"
                className={`archive-tag-chip ${activeTag === "all" ? "active" : ""}`}
                onClick={() => setActiveTag("all")}
              >
                全部标签
              </button>
              {tagOptions.map((tag) => (
                <button
                  type="button"
                  className={`archive-tag-chip ${activeTag === tag ? "active" : ""}`}
                  onClick={() => setActiveTag((current) => (current === tag ? "all" : tag))}
                  key={tag}
                >
                  {tag}
                </button>
              ))}
            </div>

            {viewMode === "cities" ? (
              <div className="city-topic-grid">
                {cityTopics.map((topic) => (
                  <button
                    type="button"
                    className={`city-topic-card ${topicCity === topic.city ? "active" : ""}`}
                    onClick={() => {
                      setTopicCity(topic.city);
                      setCityFilter(topic.city);
                    }}
                    key={topic.city}
                  >
                    <strong>{topic.city}</strong>
                    <span>{topic.count} 条规划</span>
                    <em>{topic.favoriteCount} 条收藏</em>
                    <small>最近更新 {formatTime(topic.latestAt)}</small>
                  </button>
                ))}
              </div>
            ) : null}

            <div className="archive-list-head">
              <strong>{buildListTitle(viewMode, topicCity)}</strong>
              <span>{scopedConversations.length} 条结果</span>
            </div>

            <div className="history-list history-list-advanced">
              {scopedConversations.length ? (
                scopedConversations.map((item) => (
                  <article
                    className={`history-item history-item-advanced ${selectedId === item.id ? "selected" : ""}`}
                    key={item.id}
                  >
                    <button type="button" className="history-main" onClick={() => setSelectedId(item.id)}>
                      <div className="history-title-row">
                        <strong>{item.title || "未命名规划"}</strong>
                        <span className="history-time-pill">
                          <Clock3 size={13} />
                          {formatTime(item.updated_at)}
                        </span>
                      </div>
                      <p>{item.latest_message || "暂无消息摘要"}</p>
                      <div className="history-meta-row">
                        {item.destination_city ? <span>{item.destination_city}</span> : null}
                        {item.start_date ? <span>{item.start_date}</span> : null}
                        {item.budget ? <span>{formatBudget(item.budget)}</span> : null}
                        <span>{item.message_count} 消息</span>
                        <span>{item.version_count} 版本</span>
                      </div>
                      <div className="history-tag-row">
                        {(item.tags || []).slice(0, 5).map((tag) => (
                          <em key={tag}>{tag}</em>
                        ))}
                      </div>
                    </button>
                    <button
                      type="button"
                      className={`history-favorite-button ${item.is_favorite ? "active" : ""}`}
                      onClick={() => void handleToggleFavorite(item)}
                      aria-label={item.is_favorite ? "取消收藏" : "收藏会话"}
                    >
                      <Star size={16} fill={item.is_favorite ? "currentColor" : "none"} />
                    </button>
                  </article>
                ))
              ) : (
                <div className="empty-line">当前视图和筛选条件下没有历史规划，换个条件或继续创建新的旅行方案。</div>
              )}
            </div>
          </section>

          <aside className="archive-hub-inspector">
            {selectedConversation ? (
              <>
                <div className="archive-editor-header">
                  <div className="section-kicker">
                    <Tags size={15} />
                    档案详情
                  </div>
                  <button
                    type="button"
                    className="primary-action"
                    onClick={() => onOpenConversation(selectedConversation.id)}
                  >
                    继续对话
                  </button>
                </div>

                <section className="archive-detail-card">
                  <strong>{selectedConversation.title || "未命名规划"}</strong>
                  <p>{selectedConversation.latest_message || "暂无摘要内容"}</p>
                  <div className="archive-detail-meta">
                    {selectedConversation.destination_city ? <span>{selectedConversation.destination_city}</span> : null}
                    {selectedConversation.start_date ? <span>{selectedConversation.start_date}</span> : null}
                    {selectedConversation.budget ? <span>{formatBudget(selectedConversation.budget)}</span> : null}
                    <span>{selectedConversation.version_count} 个版本</span>
                  </div>
                </section>

                <div className="archive-editor-form">
                  <label>
                    <span>规划标题</span>
                    <input
                      value={draft.title}
                      onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                      placeholder="例如：杭州周末慢游"
                    />
                  </label>
                  <label>
                    <span>目的地城市</span>
                    <input
                      value={draft.destination_city}
                      onChange={(event) => setDraft((current) => ({ ...current, destination_city: event.target.value }))}
                      placeholder="例如：杭州"
                    />
                  </label>
                  <div className="archive-editor-split archive-editor-split-dual">
                    <label>
                      <span>预算</span>
                      <input
                        value={draft.budget}
                        onChange={(event) => setDraft((current) => ({ ...current, budget: event.target.value.replace(/[^\d]/g, "") }))}
                        placeholder="例如：1800"
                      />
                    </label>
                    <label>
                      <span>出发时间</span>
                      <input
                        value={draft.start_date}
                        onChange={(event) => setDraft((current) => ({ ...current, start_date: event.target.value }))}
                        placeholder="例如：2026-05-12 / 周末"
                      />
                    </label>
                  </div>
                  <label>
                    <span>标签</span>
                    <input
                      value={draft.tags}
                      onChange={(event) => setDraft((current) => ({ ...current, tags: event.target.value }))}
                      placeholder="使用逗号分隔，例如：江南，美食，高铁"
                    />
                  </label>
                </div>

                <div className="archive-editor-actions">
                  <button
                    type="button"
                    className={`history-toggle ${selectedConversation.is_favorite ? "active" : ""}`}
                    onClick={() => void handleToggleFavorite(selectedConversation)}
                  >
                    <Star size={15} fill={selectedConversation.is_favorite ? "currentColor" : "none"} />
                    {selectedConversation.is_favorite ? "已收藏" : "加入收藏"}
                  </button>
                  <button
                    type="button"
                    className="primary-action"
                    onClick={() => void handleSave()}
                    disabled={saving}
                  >
                    <Save size={15} />
                    {saving ? "保存中..." : "保存档案"}
                  </button>
                </div>

                <div className={`archive-danger-zone ${confirmDelete ? "active" : ""}`}>
                  <div>
                    <span>删除会话</span>
                    <p>删除后会同步清理该会话的消息、版本、分享页与工作台记录。</p>
                  </div>
                  {confirmDelete ? (
                    <div className="archive-danger-actions">
                      <button type="button" className="secondary-action" onClick={() => setConfirmDelete(false)}>
                        取消
                      </button>
                      <button type="button" className="danger-action" onClick={() => void handleDelete()} disabled={deleting}>
                        <Trash2 size={15} />
                        {deleting ? "删除中..." : "确认删除"}
                      </button>
                    </div>
                  ) : (
                    <button type="button" className="danger-ghost" onClick={() => setConfirmDelete(true)}>
                      <Trash2 size={15} />
                      删除这段历史
                    </button>
                  )}
                </div>
              </>
            ) : (
              <div className="archive-empty">
                <strong>暂无可编辑会话</strong>
                <p>先取消筛选，或继续创建一个新的旅行方案，这里会自动形成可管理的历史档案。</p>
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
}

function parseTags(value: string): string[] {
  return value
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatBudget(value: number) {
  return `预算 ${value} 元`;
}

function matchesBudgetFilter(value: number | null | undefined, filter: BudgetFilter) {
  if (filter === "all") return true;
  if (value == null) return false;
  if (filter === "light") return value < 1000;
  if (filter === "balanced") return value >= 1000 && value < 3000;
  if (filter === "comfort") return value >= 3000 && value < 6000;
  return value >= 6000;
}

function matchesTimeFilter(value: string | null | undefined, filter: TimeFilter) {
  if (filter === "all") return true;
  if (!value) return false;
  if (filter === "weekend") return /周末|周六|周日/.test(value);
  if (filter === "holiday") return /五一|十一|国庆|端午|中秋|春节|暑假|寒假|假期/.test(value);
  if (filter === "near") return /明天|后天|本周|下周|近期|最近/.test(value);
  return /\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日/.test(value);
}

function scopeByView(conversations: ConversationSummary[], viewMode: ArchiveView, topicCity: string) {
  if (viewMode === "recent") return conversations.slice(0, 12);
  if (viewMode === "favorites") return conversations.filter((item) => item.is_favorite);
  if (viewMode === "cities") {
    if (topicCity === "all") return conversations;
    return conversations.filter((item) => item.destination_city === topicCity);
  }
  return conversations;
}

function buildCityTopics(conversations: ConversationSummary[]): CityTopic[] {
  const groups = new Map<string, CityTopic>();
  for (const item of conversations) {
    const city = item.destination_city?.trim();
    if (!city) continue;
    const current = groups.get(city);
    if (!current) {
      groups.set(city, {
        city,
        count: 1,
        favoriteCount: item.is_favorite ? 1 : 0,
        latestAt: item.updated_at,
      });
      continue;
    }
    current.count += 1;
    current.favoriteCount += item.is_favorite ? 1 : 0;
    if (new Date(item.updated_at).getTime() > new Date(current.latestAt).getTime()) {
      current.latestAt = item.updated_at;
    }
  }
  return Array.from(groups.values()).sort((left, right) => {
    if (right.count !== left.count) return right.count - left.count;
    return new Date(right.latestAt).getTime() - new Date(left.latestAt).getTime();
  });
}

function buildListTitle(viewMode: ArchiveView, topicCity: string) {
  if (viewMode === "recent") return "最近更新";
  if (viewMode === "favorites") return "收藏夹";
  if (viewMode === "cities") return topicCity === "all" ? "城市专题" : `${topicCity} 专题`;
  return "全部档案";
}
