import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import {
  addGuide,
  ApiCodeError,
  clearAuthSession,
  comparePlanVersions,
  createSharedPlan,
  crawlWeiboGuides,
  deleteConversation,
  exportPlanVersion,
  fetchAuthSessions,
  fetchConversationDetail,
  fetchConversations,
  fetchCurrentUser,
  fetchGuideSources,
  fetchPlanVersions,
  fetchPreferenceProfile,
  fetchToolStatus,
  importGuestSession,
  loginUser,
  logoutUser,
  registerUser,
  restoreAuthState,
  revokeAuthSession,
  savePlanVersion,
  streamChat,
  updateConversation,
  updateMyProfile,
} from "./lib/api";
import type {
  AuthSession,
  ChatResponse,
  ConversationSummary,
  ConversationUpdatePayload,
  GuestCarryoverSummary,
  GuestSessionImportPayload,
  GuideSourceItem,
  LocalUser,
  PlanVersion,
  PlanVersionCompare,
  PreferenceProfile,
  StreamStage,
  ToolStatus,
  UserProfileUpdatePayload,
} from "./lib/types";
import { AddGuideModal } from "./components/AddGuideModal";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { HistoryCenter } from "./components/HistoryCenter";
import { InsightPanel } from "./components/InsightPanel";
import { PlannerSidebar } from "./components/PlannerSidebar";
import { SharedPlanPage } from "./components/SharedPlanPage";
import { TopNav } from "./components/TopNav";
import { UserCenter } from "./components/UserCenter";

type Message = { role: "user" | "assistant"; content: string };
type SearchMode = "local_only" | "web_enhanced" | "auto";
type GuestCarryoverDraft = Omit<GuestSessionImportPayload, "user_id">;

const DEFAULT_READY_MESSAGE = "我已经准备好帮你把攻略、铁路、天气和地图放在一起做旅行判断。";

export default function App() {
  const shareId = window.location.hash.startsWith("#/share/")
    ? window.location.hash.replace("#/share/", "")
    : "";

  const [status, setStatus] = useState<ToolStatus | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Message[]>(buildWelcomeMessages(null, null));
  const [latest, setLatest] = useState<ChatResponse | null>(null);
  const [guideSources, setGuideSources] = useState<GuideSourceItem[]>([]);
  const [planVersions, setPlanVersions] = useState<PlanVersion[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [versionCompare, setVersionCompare] = useState<PlanVersionCompare | null>(null);
  const [searchMode, setSearchMode] = useState<SearchMode>("auto");
  const [streamStages, setStreamStages] = useState<StreamStage[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [guideLoading, setGuideLoading] = useState(false);
  const [crawlLoading, setCrawlLoading] = useState(false);
  const [guideResult, setGuideResult] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [preferenceProfile, setPreferenceProfile] = useState<PreferenceProfile | null>(null);
  const [currentUser, setCurrentUser] = useState<LocalUser | null>(null);
  const [currentSession, setCurrentSession] = useState<AuthSession | null>(null);
  const [authSessions, setAuthSessions] = useState<AuthSession[]>([]);
  const [authSessionsLoading, setAuthSessionsLoading] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [authReady, setAuthReady] = useState(false);

  const guestMode = !currentUser;

  const guestCarryoverDraft = useMemo(
    () => (guestMode ? buildGuestCarryoverDraft(messages, planVersions, activeVersionId, latest) : null),
    [activeVersionId, guestMode, latest, messages, planVersions],
  );
  const guestCarryoverSummary = useMemo<GuestCarryoverSummary | null>(
    () => (guestCarryoverDraft ? buildGuestCarryoverSummary(guestCarryoverDraft) : null),
    [guestCarryoverDraft],
  );

  if (shareId) {
    return <SharedPlanPage shareId={shareId} />;
  }

  useEffect(() => {
    void bootstrapApp();
  }, []);

  useEffect(() => {
    if (!authReady) return;
    if (currentUser) {
      setConversations([]);
      setPreferenceProfile(null);
      handleNewConversation(currentUser, null);
      void refreshWorkspaceMemory();
      return;
    }

    setConversations([]);
    setPreferenceProfile(null);
    setAuthSessions([]);
    handleNewConversation(null);
  }, [authReady, currentUser?.id]);

  useEffect(() => {
    if (!conversationId || !currentUser) return;
    void fetchPlanVersions(conversationId)
      .then((items) => {
        if (!items.length) return;
        setPlanVersions(items);
        const latestVersion = items[items.length - 1];
        setActiveVersionId(latestVersion.id);
        setLatest(latestVersion.response);
      })
      .catch(() => undefined);
  }, [conversationId, currentUser]);

  useEffect(() => {
    const active = planVersions.find((item) => item.id === activeVersionId);
    const base = planVersions[0];
    if (!active || !base || active.id === base.id) {
      setVersionCompare(null);
      return;
    }

    if (!currentUser) {
      setVersionCompare(buildLocalCompare(base, active));
      return;
    }

    void comparePlanVersions(base.id, active.id)
      .then(setVersionCompare)
      .catch(() => setVersionCompare(buildLocalCompare(base, active)));
  }, [activeVersionId, currentUser, planVersions]);

  async function bootstrapApp() {
    await Promise.allSettled([
      fetchToolStatus()
        .then(setStatus)
        .catch(() =>
          setStatus({
            llm: "offline",
            amap: "offline",
            mcp_12306: "offline",
            web_search: "offline",
            vector_store: "offline",
            demo_mode: true,
          }),
        ),
      refreshGuideSources(),
    ]);

    const authState = await restoreAuthState().catch(() => null);
    if (authState) {
      setCurrentUser(authState.user);
      setCurrentSession(authState.session);
    } else {
      clearAuthSession();
      setCurrentUser(null);
      setCurrentSession(null);
    }
    setAuthReady(true);
  }

  async function refreshGuideSources() {
    try {
      const sources = await fetchGuideSources();
      setGuideSources(sources);
    } catch {
      setGuideSources([]);
    }
  }

  async function refreshWorkspaceMemory(force = false) {
    if (!force && !currentUser) {
      setConversations([]);
      setPreferenceProfile(null);
      return;
    }
    const [history, profile, authState] = await Promise.all([
      fetchConversations().catch(() => []),
      fetchPreferenceProfile().catch(() => null),
      fetchCurrentUser().catch(() => null),
    ]);
    setConversations(history);
    setPreferenceProfile(profile);
    if (authState) {
      setCurrentUser(authState.user);
      setCurrentSession(authState.session);
    } else {
      setCurrentUser(null);
      setCurrentSession(null);
    }
  }

  async function refreshSessionList() {
    if (!currentUser) {
      setAuthSessions([]);
      return;
    }
    setAuthSessionsLoading(true);
    try {
      const items = await fetchAuthSessions();
      setAuthSessions(items);
    } finally {
      setAuthSessionsLoading(false);
    }
  }

  async function handlePrompt(prompt: string, context: Record<string, unknown> = {}) {
    setMessages((current) => [...current, { role: "user", content: prompt }]);
    setStreamStages([]);
    setLoading(true);

    try {
      await streamChat(
        prompt,
        conversationId,
        searchMode,
        {
          ...context,
          persist_session: Boolean(currentUser),
        },
        {
          onStart: (id) => setConversationId(id),
          onStage: (stage) =>
            setStreamStages((current) => {
              const index = current.findIndex((item) => item.name === stage.name);
              if (index === -1) return [...current, stage];
              return current.map((item, itemIndex) => (itemIndex === index ? stage : item));
            }),
          onResult: (response) => {
            setConversationId(response.conversation_id);
            setLatest(response);
            registerPlanVersion(response, context);
            setMessages((current) => [...current, { role: "assistant", content: response.answer }]);
            setStreamStages((current) => current.map((item) => ({ ...item, status: "done" })));
            if (currentUser) {
              void refreshWorkspaceMemory();
            }
          },
          onError: (message) => {
            setMessages((current) => [...current, { role: "assistant", content: message }]);
          },
        },
      );
    } catch (error) {
      if (error instanceof ApiCodeError && error.code === 4011) {
        clearAuthSession();
        setCurrentUser(null);
        setCurrentSession(null);
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            content: "你的登录态已经失效，我已切回游客模式。重新登录后可以继续保存历史和偏好画像。",
          },
        ]);
        setLoading(false);
        return;
      }

      const timeout = axios.isAxiosError(error) && error.code === "ECONNABORTED";
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: timeout
            ? "这次规划调用了多个实时工具，等待时间偏长。后端可能仍在处理中，请稍后重试，或先切换到“攻略库”模式做快速规划。"
            : "后端暂时没有响应，请确认 `start.bat` 或前后端服务已经启动。",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function handleAddGuide(payload: { title: string; content: string; source_url?: string }) {
    setGuideLoading(true);
    setGuideResult(null);
    try {
      const result = await addGuide(payload);
      setGuideResult(`已入库：${String(result.city || "未知城市")}，切片 ${String(result.chunks || 0)} 条`);
      await refreshGuideSources();
    } catch {
      setGuideResult("攻略入库失败，请确认后端服务已经启动。");
    } finally {
      setGuideLoading(false);
    }
  }

  async function handleCrawlWeibo() {
    setCrawlLoading(true);
    setGuideResult(null);
    try {
      const result = await crawlWeiboGuides();
      setGuideResult(
        `采集完成：发现 ${String(result.found || 0)} 条，正文入库 ${String(result.indexed || 0)} 条，待处理 ${String(result.pending || 0)} 条，跳过 ${String(result.skipped || 0)} 条。`,
      );
      await refreshGuideSources();
    } catch {
      setGuideResult("微博采集失败，可能是网络、平台限制或页面结构变化，请稍后重试。");
    } finally {
      setCrawlLoading(false);
    }
  }

  function handleNewConversation(
    user: LocalUser | null = currentUser,
    recommendationHint: string | null = preferenceProfile?.recommendation_hint ?? null,
  ) {
    setConversationId(undefined);
    setLatest(null);
    setPlanVersions([]);
    setActiveVersionId(null);
    setVersionCompare(null);
    setShareUrl(null);
    setStreamStages([]);
    setMessages(buildWelcomeMessages(user, recommendationHint));
  }

  async function handleOpenConversation(conversationIdToOpen: string) {
    const [detail, versions] = await Promise.all([
      fetchConversationDetail(conversationIdToOpen),
      fetchPlanVersions(conversationIdToOpen).catch(() => []),
    ]);

    setConversationId(detail.id);
    setMessages(
      detail.messages.map((message) => ({
        role: message.role,
        content: message.content,
      })),
    );
    setPlanVersions(versions);
    setShareUrl(null);
    setStreamStages([]);

    const latestVersion = versions[versions.length - 1];
    setActiveVersionId(latestVersion?.id || null);
    setLatest(latestVersion?.response || null);
    setHistoryOpen(false);
  }

  async function handleUpdateConversation(conversationIdToUpdate: string, payload: ConversationUpdatePayload) {
    if (!currentUser) return;
    const updated = await updateConversation(conversationIdToUpdate, payload);
    setConversations((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function handleDeleteConversation(conversationIdToDelete: string) {
    if (!currentUser) return;
    await deleteConversation(conversationIdToDelete);
    setConversations((current) => current.filter((item) => item.id !== conversationIdToDelete));
    if (conversationId === conversationIdToDelete) {
      handleNewConversation(currentUser, preferenceProfile?.recommendation_hint ?? null);
    }
  }

  function handleOptimizeItinerary(editedPlan: Record<string, unknown>) {
    const prompt = "请基于我刚刚手动修改后的行程草稿，重新优化交通衔接、雨天备选、预算控制和行程强度，并输出一版更稳妥的可执行方案。";
    void handlePrompt(prompt, { edited_plan: editedPlan });
  }

  function registerPlanVersion(response: ChatResponse, context: Record<string, unknown>) {
    // 每次智能体产出都保留为一个版本，方便用户在“原始方案”和“二次优化方案”之间切换回看。
    const versionId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const isEditedPlan = Boolean(context.edited_plan);
    const optimizedCount = planVersions.filter((item) => item.reason.includes("二次优化")).length;
    const version: PlanVersion = {
      id: versionId,
      name: isEditedPlan ? `优化版 ${optimizedCount + 1}` : planVersions.length ? `方案 ${planVersions.length + 1}` : "初版",
      createdAt: new Date().toISOString(),
      reason: isEditedPlan ? "基于手动编辑草稿二次优化" : "智能体首次生成方案",
      response,
    };

    setPlanVersions((current) => [...current, version]);
    setActiveVersionId(versionId);

    if (currentUser) {
      void savePlanVersion(version, response.conversation_id).catch(() => undefined);
    }
  }

  function handleSelectVersion(versionIdToSelect: string) {
    const version = planVersions.find((item) => item.id === versionIdToSelect);
    if (!version) return;
    setActiveVersionId(versionIdToSelect);
    setLatest(version.response);
  }

  async function handleExportVersion(versionIdToExport: string, format: "markdown" | "html") {
    if (!currentUser) {
      const version = planVersions.find((item) => item.id === versionIdToExport);
      if (!version) return;
      const result = buildLocalExport(version, format);
      downloadBlob(result.content, result.mime_type, result.filename);
      return;
    }
    const result = await exportPlanVersion(versionIdToExport, format);
    downloadBlob(result.content, result.mime_type, result.filename);
  }

  async function handleShareVersion(versionIdToShare: string) {
    if (!currentUser) return;
    const result = await createSharedPlan(versionIdToShare);
    const url = `${window.location.origin}${window.location.pathname}#/share/${result.id}`;
    setShareUrl(url);
    await navigator.clipboard?.writeText(url).catch(() => undefined);
  }

  async function applyUserSession(
    user: LocalUser,
    session: AuthSession,
    options?: { preserveGuestSession?: boolean },
  ) {
    const shouldCarryOver = Boolean(options?.preserveGuestSession && guestCarryoverDraft);
    const carryoverSnapshot = shouldCarryOver ? guestCarryoverDraft : null;

    setCurrentUser(user);
    setCurrentSession(session);
    setUserOpen(false);
    setHistoryOpen(false);

    if (!carryoverSnapshot) {
      await refreshWorkspaceMemory(true);
      return;
    }

    try {
      const imported = await importGuestSession({
        user_id: user.id,
        ...carryoverSnapshot,
      });
      await refreshWorkspaceMemory(true);
      await handleOpenConversation(imported.conversation_id);
    } catch {
      await refreshWorkspaceMemory(true);
    }
  }

  async function handleLoginUser(
    payload: { username: string; password: string },
    options?: { preserveGuestSession?: boolean },
  ) {
    const result = await loginUser(payload);
    await applyUserSession(result.user, result.session, options);
  }

  async function handleRegisterUser(
    payload: {
      display_name: string;
      username?: string;
      password?: string;
      home_city?: string;
      travel_style?: string;
    },
    options?: { preserveGuestSession?: boolean },
  ) {
    const result = await registerUser(payload);
    await applyUserSession(result.user, result.session, options);
  }

  async function handleLogout() {
    await logoutUser().catch(() => undefined);
    setCurrentUser(null);
    setCurrentSession(null);
    setAuthSessions([]);
    setUserOpen(false);
    setHistoryOpen(false);
  }

  async function handleProfileUpdate(payload: UserProfileUpdatePayload) {
    const updated = await updateMyProfile(payload);
    setCurrentUser(updated);
    await refreshSessionList();
  }

  async function handleRevokeSession(sessionId: string) {
    await revokeAuthSession(sessionId);
    await refreshSessionList();
  }

  return (
    <div className="app-shell">
      <TopNav
        status={status}
        currentUser={currentUser}
        guestMode={guestMode}
        onAddGuide={() => setModalOpen(true)}
        onNewConversation={() => handleNewConversation()}
        onHistoryOpen={() => {
          if (currentUser) {
            void refreshWorkspaceMemory();
          }
          setHistoryOpen(true);
        }}
        onUserOpen={() => {
          if (currentUser) {
            void refreshSessionList();
          }
          setUserOpen(true);
        }}
        onLogout={() => void handleLogout()}
      />

      <div className="workspace-grid">
        <PlannerSidebar
          onPrompt={handlePrompt}
          searchMode={searchMode}
          onSearchModeChange={setSearchMode}
        />

        <ChatWorkspace
          messages={messages}
          latest={latest}
          loading={loading}
          guestMode={guestMode}
          guestCarryoverReady={Boolean(guestCarryoverDraft)}
          searchMode={searchMode}
          streamStages={streamStages}
          planVersions={planVersions}
          activeVersionId={activeVersionId}
          versionCompare={versionCompare}
          shareUrl={shareUrl}
          canShareVersion={Boolean(currentUser)}
          onOpenUserCenter={() => setUserOpen(true)}
          onSubmit={handlePrompt}
          onOptimizeItinerary={handleOptimizeItinerary}
          onVersionSelect={handleSelectVersion}
          onExportVersion={handleExportVersion}
          onShareVersion={handleShareVersion}
        />

        <InsightPanel latest={latest} guideSources={guideSources} />
      </div>

      <AddGuideModal
        open={modalOpen}
        loading={guideLoading}
        crawlLoading={crawlLoading}
        result={guideResult}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAddGuide}
        onCrawlWeibo={handleCrawlWeibo}
      />

      <HistoryCenter
        open={historyOpen}
        conversations={conversations}
        profile={preferenceProfile}
        guestMode={guestMode}
        onClose={() => setHistoryOpen(false)}
        onOpenUserCenter={() => {
          setHistoryOpen(false);
          if (currentUser) {
            void refreshSessionList();
          }
          setUserOpen(true);
        }}
        onOpenConversation={handleOpenConversation}
        onUpdateConversation={handleUpdateConversation}
        onDeleteConversation={handleDeleteConversation}
      />

      <UserCenter
        open={userOpen}
        currentUser={currentUser}
        currentSession={currentSession}
        sessions={authSessions}
        sessionsLoading={authSessionsLoading}
        guestCarryover={guestCarryoverSummary}
        preferenceProfile={preferenceProfile}
        onClose={() => setUserOpen(false)}
        onEnterGuest={() => setUserOpen(false)}
        onLogin={handleLoginUser}
        onRegister={handleRegisterUser}
        onLogout={handleLogout}
        onUpdateProfile={handleProfileUpdate}
        onRefreshSessions={refreshSessionList}
        onRevokeSession={handleRevokeSession}
      />
    </div>
  );
}

function buildWelcomeMessages(user: LocalUser | null, recommendationHint: string | null): Message[] {
  if (!user) {
    return [
      {
        role: "assistant",
        content: "当前为游客模式。你可以直接开始旅行规划，但历史记录、偏好画像和分享页不会保存。",
      },
    ];
  }

  if (recommendationHint) {
    return [
      {
        role: "assistant",
        content: `${user.display_name || "当前用户"} 的新对话已打开。我会参考你的偏好：${recommendationHint}`,
      },
    ];
  }

  return [
    {
      role: "assistant",
      content: `${user.display_name || "当前用户"} 的新对话已打开。告诉我出发地、目的地、时间、预算或旅行偏好，即可开始规划。`,
    },
  ];
}

function buildGuestCarryoverDraft(
  messages: Message[],
  planVersions: PlanVersion[],
  activeVersionId: string | null,
  latest: ChatResponse | null,
): GuestCarryoverDraft | null {
  const meaningfulMessages = stripGuestWelcome(messages);
  const hasUserMessage = meaningfulMessages.some((item) => item.role === "user" && item.content.trim());
  const hasVersions = planVersions.length > 0;
  const latestResponse = planVersions.find((item) => item.id === activeVersionId)?.response || latest || null;

  if (!hasUserMessage && !hasVersions && !latestResponse) {
    return null;
  }

  const destination = extractDestination(latestResponse, planVersions);
  const startDate = extractStartDate(meaningfulMessages);
  const budget = extractBudget(meaningfulMessages, latestResponse);
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || planVersions[planVersions.length - 1] || null;
  const title = buildCarryoverTitle(destination, startDate, activeVersion?.name || null, meaningfulMessages);

  return {
    title,
    messages: meaningfulMessages,
    plan_versions: planVersions.map((item) => ({
      id: item.id,
      name: item.name,
      reason: item.reason,
      response: item.response,
      created_at: item.createdAt,
    })),
    active_version_id: activeVersion?.id || null,
    latest_response: latestResponse,
    destination_city: destination,
    budget,
    start_date: startDate,
    tags: destination ? [destination] : [],
  };
}

function buildGuestCarryoverSummary(draft: GuestCarryoverDraft): GuestCarryoverSummary {
  const activeVersion = draft.plan_versions.find((item) => item.id === draft.active_version_id);
  return {
    title: draft.title || "游客临时方案",
    destination: draft.destination_city || null,
    message_count: draft.messages.length,
    version_count: draft.plan_versions.length,
    active_version_name: activeVersion?.name || null,
  };
}

function stripGuestWelcome(messages: Message[]): Message[] {
  if (!messages.length) return [];
  const first = messages[0];
  const shouldDropFirst = first.role === "assistant" && messages.length > 1;
  const cleaned = shouldDropFirst ? messages.slice(1) : messages.slice();
  return cleaned
    .map((item) => ({ ...item, content: item.content.trim() }))
    .filter((item) => item.content);
}

function extractDestination(latest: ChatResponse | null, planVersions: PlanVersion[]): string | null {
  const candidates = [latest, ...planVersions.slice().reverse().map((item) => item.response)];
  for (const response of candidates) {
    const card = response?.cards?.find((item) => item.type === "destination");
    const title = card?.title?.trim();
    if (title) return title;
  }
  return null;
}

function extractStartDate(messages: Message[]): string | null {
  const patterns = [
    /\b\d{4}-\d{1,2}-\d{1,2}\b/,
    /\b\d{4}\/\d{1,2}\/\d{1,2}\b/,
    /\b\d{1,2}月\d{1,2}日\b/,
    /(五一|十一|国庆|端午|中秋|春节|暑假|寒假|周末|本周|下周|明天|后天)/,
  ];

  for (const message of messages.filter((item) => item.role === "user").slice().reverse()) {
    for (const pattern of patterns) {
      const matched = message.content.match(pattern);
      if (matched?.[0]) return matched[0];
    }
  }
  return null;
}

function extractBudget(messages: Message[], latest: ChatResponse | null): number | null {
  const budgetModule = latest?.decision_modules?.find((item) => item.type === "budget");
  const budgetTexts = [
    budgetModule?.summary || "",
    ...(budgetModule?.points || []),
    ...messages.filter((item) => item.role === "user").map((item) => item.content),
  ];

  for (const text of budgetTexts) {
    const matched = text.match(/([1-9]\d{2,5})/);
    if (matched?.[1]) return Number(matched[1]);
  }
  return null;
}

function buildCarryoverTitle(
  destination: string | null,
  startDate: string | null,
  activeVersionName: string | null,
  messages: Message[],
): string {
  if (destination && startDate) return `${startDate} ${destination}旅行规划`;
  if (destination) return `${destination}旅行规划`;
  if (activeVersionName) return `${activeVersionName} 行程方案`;
  const latestUserMessage = messages.slice().reverse().find((item) => item.role === "user")?.content?.trim();
  if (latestUserMessage) return latestUserMessage.slice(0, 40);
  return "游客临时方案";
}

function buildLocalCompare(base: PlanVersion, target: PlanVersion): PlanVersionCompare {
  // 后端版本对比接口不可用时，前端继续保留版本差异能力，保证工作台可用。
  const metric = (key: keyof ChatResponse) =>
    ((target.response[key] as unknown[]) || []).length - ((base.response[key] as unknown[]) || []).length;

  return {
    base_id: base.id,
    target_id: target.id,
    title: `${base.name} -> ${target.name}`,
    summary: "已使用前端兜底算法完成版本差异对比。",
    metrics: {
      source_delta: metric("sources"),
      tool_delta: metric("tool_calls"),
      warning_delta: metric("warnings"),
      itinerary_day_delta: metric("itinerary"),
      module_delta: metric("decision_modules"),
    },
    highlights: ["后端版本对比接口暂不可用，已使用本地结构差异保持工作台可用。"],
  };
}

function buildLocalExport(version: PlanVersion, format: "markdown" | "html") {
  const title = buildExportTitle(version);
  if (format === "html") {
    return {
      filename: `${safeFilename(title)}.html`,
      mime_type: "text/html;charset=utf-8",
      content: buildLocalHtml(title, version.response),
    };
  }

  return {
    filename: `${safeFilename(title)}.md`,
    mime_type: "text/markdown;charset=utf-8",
    content: buildLocalMarkdown(title, version.response),
  };
}

function buildExportTitle(version: PlanVersion) {
  const destination = version.response.cards.find((item) => item.type === "destination")?.title || "旅行方案";
  return `${destination} - ${version.name}`;
}

function safeFilename(value: string) {
  return value
    .trim()
    .replace(/[^\w\u4e00-\u9fa5-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "tripsage-plan";
}

function buildLocalMarkdown(title: string, response: ChatResponse) {
  const lines = [
    `# ${title}`,
    "",
    "## 智能体建议",
    "",
    response.answer || DEFAULT_READY_MESSAGE,
    "",
  ];

  if (response.itinerary?.length) {
    lines.push("## 行程安排", "");
    for (const day of response.itinerary) {
      lines.push(`### DAY ${day.day} ${day.title}`, "");
      for (const item of day.items) {
        lines.push(`- **${item.time} · ${item.title}**：${item.detail}`);
      }
      lines.push("");
    }
  }

  if (response.decision_modules?.length) {
    lines.push("## 决策提示", "");
    for (const module of response.decision_modules) {
      lines.push(`- **${module.title}**：${module.summary}`);
    }
    lines.push("");
  }

  if (response.sources?.length) {
    lines.push("## 引用来源", "");
    for (const source of response.sources) {
      lines.push(source.url ? `- [${source.title}](${source.url})` : `- ${source.title}`);
    }
  }

  return `${lines.join("\n").trim()}\n`;
}

function buildLocalHtml(title: string, response: ChatResponse) {
  const markdown = buildLocalMarkdown(title, response)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  const paragraphs = markdown
    .split("\n")
    .map((line) => (line ? `<p>${line}</p>` : ""))
    .join("");

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <style>
    body { margin: 0; background: #f4efe2; color: #18342c; font-family: "Microsoft YaHei", sans-serif; }
    main { max-width: 920px; margin: 40px auto; padding: 32px; background: #fffaf0; border: 1px solid #d7cdb9; }
    p { line-height: 1.8; white-space: pre-wrap; }
  </style>
</head>
<body><main>${paragraphs}</main></body>
</html>`;
}

function downloadBlob(content: string, mimeType: string, filename: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
