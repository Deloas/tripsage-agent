import { useEffect, useMemo, useState, type ReactNode } from "react";
import axios from "axios";
import {
  Activity,
  Clock3,
  DatabaseZap,
  GitBranch,
  Layers3,
  Link2,
  ListChecks,
  PanelLeftOpen,
  PanelRightOpen,
  Route,
  ShieldCheck,
  SlidersHorizontal,
  TrainFront,
  WandSparkles,
  X,
} from "lucide-react";

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
import { buildStressPreviewState } from "./lib/demoScenarios";
import type {
  AuthSession,
  ChatResponse,
  ConversationSummary,
  ConversationUpdatePayload,
  DecisionModule,
  GuestCarryoverSummary,
  GuestSessionImportPayload,
  GuideSourceItem,
  LocalUser,
  PlanVersion,
  PlanVersionCompare,
  PreferenceProfile,
  RailwayTrain,
  StreamStage,
  ToolStatus,
  UserProfileUpdatePayload,
} from "./lib/types";
import { AddGuideModal } from "./components/AddGuideModal";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { HistoryCenter } from "./components/HistoryCenter";
import { InsightPanel } from "./components/InsightPanel";
import { PlannerSidebar } from "./components/PlannerSidebar";
import { PreferenceProfileWorkbench } from "./components/PreferenceProfileWorkbench";
import { SharedPlanPage } from "./components/SharedPlanPage";
import { TopNav } from "./components/TopNav";
import { UserCenter } from "./components/UserCenter";

type Message = { role: "user" | "assistant"; content: string };
type SearchMode = "local_only" | "web_enhanced" | "auto";
type GuestCarryoverDraft = Omit<GuestSessionImportPayload, "user_id">;
type WorkspaceView = "overview" | "planning" | "railway" | "evidence" | "versions" | "memory";
type DecisionModuleState = "accepted" | "ignored";
type RailwayWorkspaceDraft = {
  compare_trains: RailwayTrain[];
  candidate_trains: RailwayTrain[];
  generated_at: string;
  summary: string;
};

const DEFAULT_READY_MESSAGE = "我已经准备好帮你把攻略、铁路、天气和地图放在一起做旅行判断。";

const WORKSPACE_VIEWS: WorkspaceView[] = ["overview", "planning", "railway", "evidence", "versions", "memory"];

function isWorkspaceView(value: string | null): value is WorkspaceView {
  return Boolean(value && WORKSPACE_VIEWS.includes(value as WorkspaceView));
}

function getInitialWorkspaceView() {
  const view = new URLSearchParams(window.location.search).get("view");
  return isWorkspaceView(view) ? view : "overview";
}

export default function App() {
  const shareId = window.location.hash.startsWith("#/share/")
    ? window.location.hash.replace("#/share/", "")
    : "";
  const previewMode = new URLSearchParams(window.location.search).get("preview");
  const previewState = useMemo(
    () => (previewMode === "stress" ? buildStressPreviewState() : null),
    [previewMode],
  );

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
  const [plannerOpen, setPlannerOpen] = useState(false);
  const [insightOpen, setInsightOpen] = useState(false);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>(getInitialWorkspaceView);
  const [railwayWorkspaceDraft, setRailwayWorkspaceDraft] = useState<RailwayWorkspaceDraft | null>(null);
  const [decisionModuleStates, setDecisionModuleStates] = useState<Record<string, DecisionModuleState>>({});

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
    if (previewState) {
      applyPreviewState(previewState);
      return;
    }
    void bootstrapApp();
  }, [previewState]);

  useEffect(() => {
    if (previewState) return;
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
  }, [authReady, currentUser?.id, previewState]);

  useEffect(() => {
    if (previewState) return;
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
  }, [conversationId, currentUser, previewState]);

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

  useEffect(() => {
    if (shareId) return;
    // 让工作页支持刷新恢复与链接直达，便于真实使用和多页面演示。
    const url = new URL(window.location.href);
    if (workspaceView === "overview") {
      url.searchParams.delete("view");
    } else {
      url.searchParams.set("view", workspaceView);
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }, [shareId, workspaceView]);

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

  function applyPreviewState(state: ReturnType<typeof buildStressPreviewState>) {
    setStatus(state.status);
    setGuideSources(state.guideSources);
    setMessages(state.messages);
    setLatest(state.latest);
    setPlanVersions(state.planVersions);
    setActiveVersionId(state.activeVersionId);
    setVersionCompare(buildLocalCompare(state.planVersions[0], state.planVersions[state.planVersions.length - 1]));
    setSearchMode(state.searchMode);
    setStreamStages([
      { name: "intent", label: "识别意图", status: "done", summary: "已识别为周末短途旅行规划" },
      { name: "guide_rag", label: "检索攻略库", status: "done", summary: "命中 4 条高相关攻略来源" },
      { name: "live_tools", label: "实时工具", status: "done", summary: "铁路、地图、天气结果已回填" },
      { name: "synthesis", label: "方案综合", status: "done", summary: "已生成可编辑方案与决策模块" },
    ]);
    setConversationId(state.latest.conversation_id);
    setConversations(state.history);
    setPreferenceProfile(state.profile);
    setCurrentUser(null);
    setCurrentSession(null);
    setAuthSessions([]);
    setLoading(false);
    setRailwayWorkspaceDraft(null);
    setDecisionModuleStates({});
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
            if (!context.decision_module_action) {
              setDecisionModuleStates({});
            }
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
    setRailwayWorkspaceDraft(null);
    setDecisionModuleStates({});
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
    setRailwayWorkspaceDraft(null);
    setDecisionModuleStates({});

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
    setRailwayWorkspaceDraft(null);
    setDecisionModuleStates({});
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

  function handleRailwayWorkspaceSync(draft: RailwayWorkspaceDraft | null) {
    setRailwayWorkspaceDraft(draft);
  }

  function handleApplyRailwayWorkspaceDraft() {
    if (!railwayWorkspaceDraft) return;
    setWorkspaceView("planning");
    void handlePrompt(buildAppRailwayWorkspacePrompt(railwayWorkspaceDraft), {
      railway_workspace_draft: railwayWorkspaceDraft,
    });
  }

  function handleDecisionModuleAction(module: DecisionModule, action: "accept" | "ignore" | "regenerate") {
    const key = buildAppDecisionModuleKey(module);
    setDecisionModuleStates((current) => {
      if (action === "regenerate") {
        const { [key]: _, ...rest } = current;
        return rest;
      }
      return {
        ...current,
        [key]: action === "accept" ? "accepted" : "ignored",
      };
    });
    void handlePrompt(buildAppDecisionModulePrompt(module, action), {
      decision_module_action: action,
      decision_module: {
        type: module.type,
        title: module.title,
        summary: module.summary,
        points: module.points,
      },
    });
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

      <ProductWorkspaceNav
        currentView={workspaceView}
        latest={latest}
        guestMode={guestMode}
        planVersions={planVersions}
        guideSources={guideSources}
        onChange={setWorkspaceView}
      />

      <section className="product-view-stage" aria-label="旅行决策多工作页">
        {workspaceView === "overview" ? (
          <OverviewWorkbench
            latest={latest}
            streamStages={streamStages}
            searchMode={searchMode}
            planVersions={planVersions}
            guideSources={guideSources}
            guestMode={guestMode}
            onJump={setWorkspaceView}
          />
        ) : null}

        {workspaceView === "planning" ? (
          <PlanningWorkbench
            latest={latest}
            searchMode={searchMode}
            loading={loading}
            streamStages={streamStages}
            messages={messages}
            planVersions={planVersions}
            guestMode={guestMode}
            activeVersionId={activeVersionId}
            versionCompare={versionCompare}
            shareUrl={shareUrl}
            guestCarryoverReady={Boolean(guestCarryoverDraft)}
            canShareVersion={Boolean(currentUser)}
            railwayWorkspaceDraft={railwayWorkspaceDraft}
            decisionModuleStates={decisionModuleStates}
            onOpenPlanner={() => setPlannerOpen(true)}
            onOpenEvidence={() => setInsightOpen(true)}
            onOpenUserCenter={() => setUserOpen(true)}
            onJump={setWorkspaceView}
            onApplyRailwayDraft={handleApplyRailwayWorkspaceDraft}
            onSubmit={handlePrompt}
            onOptimizeItinerary={handleOptimizeItinerary}
            onDecisionModuleAction={handleDecisionModuleAction}
            onVersionSelect={handleSelectVersion}
            onExportVersion={handleExportVersion}
            onShareVersion={handleShareVersion}
          />
        ) : null}

        {false ? (
          <div className="product-workbench-shell">
            <div className="workbench-side-dock" aria-label="工作台侧栏操作">
              <button
                type="button"
                className="rail-toggle-button"
                onClick={() => setPlannerOpen(true)}
                title="打开规划条件"
                aria-label="打开规划条件"
              >
                <PanelLeftOpen size={18} />
                <span>条件</span>
              </button>
              <button
                type="button"
                className="rail-toggle-button"
                onClick={() => setInsightOpen(true)}
                title="打开工具与证据"
                aria-label="打开工具与证据"
              >
                <PanelRightOpen size={18} />
                <span>证据</span>
              </button>
            </div>

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
              decisionModuleStates={decisionModuleStates}
              onOpenUserCenter={() => setUserOpen(true)}
              onSubmit={handlePrompt}
              onOptimizeItinerary={handleOptimizeItinerary}
              onDecisionModuleAction={handleDecisionModuleAction}
              onVersionSelect={handleSelectVersion}
              onExportVersion={handleExportVersion}
              onShareVersion={handleShareVersion}
            />
          </div>
        ) : null}

        {workspaceView === "railway" ? (
          <RailwayDecisionPage
            latest={latest}
            onAdoptTrain={(prompt) => void handlePrompt(prompt)}
            onWorkspaceSync={handleRailwayWorkspaceSync}
            onSyncToPlanning={handleApplyRailwayWorkspaceDraft}
          />
        ) : null}

        {workspaceView === "evidence" ? (
          <EvidenceWorkbench
            latest={latest}
            guideSources={guideSources}
            searchMode={searchMode}
            onSearchModeChange={setSearchMode}
            onPrompt={(prompt) => void handlePrompt(prompt)}
          />
        ) : null}

        {workspaceView === "versions" ? (
          <VersionWorkbench
            planVersions={planVersions}
            activeVersionId={activeVersionId}
            versionCompare={versionCompare}
            shareUrl={shareUrl}
            guestMode={guestMode}
            canShareVersion={Boolean(currentUser)}
            onSelectVersion={handleSelectVersion}
            onExportVersion={handleExportVersion}
            onShareVersion={handleShareVersion}
            onOpenUserCenter={() => setUserOpen(true)}
          />
        ) : null}

        {workspaceView === "memory" ? (
          <MemoryWorkbench
            guestMode={guestMode}
            currentUser={currentUser}
            conversations={conversations}
            profile={preferenceProfile}
            onOpenHistory={() => {
              if (currentUser) {
                void refreshWorkspaceMemory();
              }
              setHistoryOpen(true);
            }}
            onOpenUserCenter={() => {
              if (currentUser) {
                void refreshSessionList();
              }
              setUserOpen(true);
            }}
          />
        ) : null}
      </section>

      <WorkspaceDrawer
        side="left"
        open={plannerOpen}
        title="规划条件"
        subtitle="路线、日期、预算与检索模式"
        icon={<SlidersHorizontal size={17} />}
        onClose={() => setPlannerOpen(false)}
      >
        <PlannerSidebar
          onPrompt={(prompt) => {
            setPlannerOpen(false);
            handlePrompt(prompt);
          }}
          searchMode={searchMode}
          onSearchModeChange={setSearchMode}
        />
      </WorkspaceDrawer>

      <WorkspaceDrawer
        side="right"
        open={insightOpen}
        title="工具与证据"
        subtitle="12306、天气、地图、来源与调用链"
        icon={<Activity size={17} />}
        onClose={() => setInsightOpen(false)}
      >
        <InsightPanel latest={latest} guideSources={guideSources} />
      </WorkspaceDrawer>

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

function WorkspaceDrawer({
  side,
  open,
  title,
  subtitle,
  icon,
  onClose,
  children,
}: {
  side: "left" | "right";
  open: boolean;
  title: string;
  subtitle: string;
  icon: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;

  return (
    <div className={`workspace-drawer-layer ${side}`} role="presentation">
      <button className="workspace-drawer-scrim" type="button" aria-label="关闭侧边栏" onClick={onClose} />
      <aside className={`workspace-drawer ${side}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="workspace-drawer-header">
          <div className="workspace-drawer-title">
            {icon}
            <div>
              <strong>{title}</strong>
              <span>{subtitle}</span>
            </div>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="鍏抽棴">
            <X size={18} />
          </button>
        </header>
        <div className="workspace-drawer-body">{children}</div>
      </aside>
    </div>
  );
}

function ProductWorkspaceNav({
  currentView,
  latest,
  guestMode,
  planVersions,
  guideSources,
  onChange,
}: {
  currentView: WorkspaceView;
  latest: ChatResponse | null;
  guestMode: boolean;
  planVersions: PlanVersion[];
  guideSources: GuideSourceItem[];
  onChange: (view: WorkspaceView) => void;
}) {
  const tabs: Array<{ id: WorkspaceView; label: string; icon: ReactNode; count?: number }> = [
    { id: "overview", label: "总览", icon: <Layers3 size={15} /> },
    { id: "planning", label: "规划", icon: <ListChecks size={15} />, count: latest?.itinerary?.length || 0 },
    { id: "railway", label: "铁路", icon: <TrainFront size={15} />, count: getRailwayTrains(latest).length },
    { id: "evidence", label: "证据", icon: <DatabaseZap size={15} />, count: latest?.sources.length || guideSources.length },
    { id: "versions", label: "版本", icon: <GitBranch size={15} />, count: planVersions.length },
    { id: "memory", label: "我的", icon: <ShieldCheck size={15} /> },
  ];

  return (
    <section className="product-nav-shell" aria-label="产品工作页导航">
      <div className="product-nav-copy">
        <div className="section-kicker">
          <WandSparkles size={15} />
          行迹智策
        </div>
        <h1>中国旅行决策工作台</h1>
        <p>把规划、车次、证据、版本和用户记忆拆成多个工作页，给高密度决策留出真正舒适的空间。</p>
      </div>
      <div className="product-nav-tabs" role="tablist" aria-label="切换工作页">
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab.id}
            role="tab"
            aria-selected={currentView === tab.id}
            className={`product-nav-tab ${currentView === tab.id ? "active" : ""}`}
            onClick={() => onChange(tab.id)}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count ? <strong>{tab.count}</strong> : null}
          </button>
        ))}
      </div>
      <div className="product-nav-signal">
        <div>
          <span>当前模式</span>
          <strong>{latest?.intent || "ready"}</strong>
        </div>
        <div>
          <span>本地来源</span>
          <strong>{guideSources.length}</strong>
        </div>
        <div>
          <span>会话身份</span>
          <strong>{guestMode ? "游客模式" : "已登录"}</strong>
        </div>
      </div>
    </section>
  );
}

function SignalCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <article className="signal-card">
      <div className="signal-card-head">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function PlanningWorkbench({
  latest,
  searchMode,
  loading,
  streamStages,
  messages,
  planVersions,
  guestMode,
  activeVersionId,
  versionCompare,
  shareUrl,
  guestCarryoverReady,
  canShareVersion,
  railwayWorkspaceDraft,
  decisionModuleStates,
  onOpenPlanner,
  onOpenEvidence,
  onOpenUserCenter,
  onJump,
  onApplyRailwayDraft,
  onSubmit,
  onOptimizeItinerary,
  onDecisionModuleAction,
  onVersionSelect,
  onExportVersion,
  onShareVersion,
}: {
  latest: ChatResponse | null;
  searchMode: SearchMode;
  loading: boolean;
  streamStages: StreamStage[];
  messages: Message[];
  planVersions: PlanVersion[];
  guestMode: boolean;
  activeVersionId: string | null;
  versionCompare: PlanVersionCompare | null;
  shareUrl: string | null;
  guestCarryoverReady: boolean;
  canShareVersion: boolean;
  railwayWorkspaceDraft: RailwayWorkspaceDraft | null;
  decisionModuleStates: Record<string, DecisionModuleState>;
  onOpenPlanner: () => void;
  onOpenEvidence: () => void;
  onOpenUserCenter: () => void;
  onJump: (view: WorkspaceView) => void;
  onApplyRailwayDraft: () => void;
  onSubmit: (message: string) => void;
  onOptimizeItinerary: (editedPlan: Record<string, unknown>) => void;
  onDecisionModuleAction: (module: DecisionModule, action: "accept" | "ignore" | "regenerate") => void;
  onVersionSelect: (versionId: string) => void;
  onExportVersion: (versionId: string, format: "markdown" | "html") => void;
  onShareVersion: (versionId: string) => void;
}) {
  const trains = getRailwayTrains(latest);
  const latestStage = streamStages[streamStages.length - 1];
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || null;
  const modeLabel =
    searchMode === "auto" ? "自动检索" : searchMode === "local_only" ? "仅攻略库" : "联网增强";

  return (
    <div className="view-frame planning-page">
      <section className="page-band planning-hero-band">
        <div className="planning-hero-copy">
          <div className="section-kicker">
            <ListChecks size={16} />
            规划工作页
          </div>
          <h2>把对话、可编辑行程和实时工具调度放进同一条规划主线</h2>
          <p>这里保留深度交互能力，但把铁路、证据、版本和用户记忆拆到了独立工作页，规划本身终于有了完整而舒适的主舞台。</p>
          <div className="overview-action-row planning-hero-actions">
            <button type="button" className="primary-action" onClick={onOpenPlanner}>
              <PanelLeftOpen size={15} />
              打开条件面板
            </button>
            <button type="button" className="secondary-action" onClick={onOpenEvidence}>
              <PanelRightOpen size={15} />
              打开证据抽屉
            </button>
            <button type="button" className="secondary-action" onClick={() => onJump("railway")}>
              <TrainFront size={15} />
              前往铁路页
            </button>
          </div>
        </div>

        <div className="planning-quick-grid">
          <SignalCard icon={<Layers3 size={16} />} label="当前版本" value={activeVersion?.name || "尚未生成"} />
          <SignalCard icon={<Route size={16} />} label="检索模式" value={modeLabel} />
          <SignalCard icon={<TrainFront size={16} />} label="列车候选" value={`${trains.length}`} />
          <SignalCard icon={<DatabaseZap size={16} />} label="证据与工具" value={`${latest?.sources.length || 0} / ${latest?.tool_calls.length || 0}`} />
        </div>
      </section>

      <section className="page-band planning-command-strip">
        <div className="planning-command-pill">
          <Clock3 size={14} />
          <div>
            <span>实时调度</span>
            <strong>
              {loading
                ? "智能体正在调用工具"
                : latestStage?.summary || "等待新的规划任务"}
            </strong>
          </div>
        </div>
        <div className="planning-command-pill">
          <GitBranch size={14} />
          <div>
            <span>版本对比</span>
            <strong>{versionCompare?.title || `已累计 ${planVersions.length} 个版本`}</strong>
          </div>
        </div>
        <div className="planning-command-pill">
          <ShieldCheck size={14} />
          <div>
            <span>会话状态</span>
            <strong>{guestMode ? "游客模式，默认不保存历史" : "已登录，可沉淀偏好与历史"}</strong>
          </div>
        </div>
        <div className="planning-command-pill actionable">
          <button type="button" className="quiet-link-button" onClick={() => onJump("versions")}>
            打开版本页
          </button>
          <button type="button" className="quiet-link-button" onClick={onOpenUserCenter}>
            {guestMode && guestCarryoverReady ? "登录保存本次方案" : "打开用户中心"}
          </button>
        </div>
      </section>

      {railwayWorkspaceDraft ? (
        <section className="page-band planning-rail-sync-band">
          <div className="planning-rail-sync-copy">
            <div className="section-kicker">
              <TrainFront size={15} />
              铁路工作台回写
            </div>
            <h3>铁路页已整理出可直接回写到规划页的交通决策结果</h3>
            <p>{railwayWorkspaceDraft.summary}</p>
            <div className="planning-rail-chip-row">
              {railwayWorkspaceDraft.compare_trains.map((train) => (
                <span key={`compare-${train.train_no}-${train.start_time}`}>对比 {train.train_no || "车次"}</span>
              ))}
              {railwayWorkspaceDraft.candidate_trains.map((train) => (
                <span key={`candidate-${train.train_no}-${train.start_time}`}>候选 {train.train_no || "车次"}</span>
              ))}
            </div>
          </div>
          <div className="planning-rail-sync-actions">
            <button type="button" className="primary-action" onClick={onApplyRailwayDraft}>
              <WandSparkles size={15} />
              写回并继续优化
            </button>
            <button type="button" className="secondary-action" onClick={() => onJump("railway")}>
              <TrainFront size={15} />
              回铁路页调整
            </button>
          </div>
        </section>
      ) : null}

      <div className="product-workbench-shell product-planning-shell">
        <div className="workbench-side-dock" aria-label="规划工作页侧栏快捷操作">
          <button
            type="button"
            className="rail-toggle-button"
            onClick={onOpenPlanner}
            title="打开规划条件"
            aria-label="打开规划条件"
          >
            <PanelLeftOpen size={18} />
            <span>条件</span>
          </button>
          <button
            type="button"
            className="rail-toggle-button"
            onClick={onOpenEvidence}
            title="打开工具与证据"
            aria-label="打开工具与证据"
          >
            <PanelRightOpen size={18} />
            <span>证据</span>
          </button>
        </div>

        <ChatWorkspace
          messages={messages}
          latest={latest}
          loading={loading}
          guestMode={guestMode}
          guestCarryoverReady={guestCarryoverReady}
          searchMode={searchMode}
          streamStages={streamStages}
          planVersions={planVersions}
          activeVersionId={activeVersionId}
          versionCompare={versionCompare}
          shareUrl={shareUrl}
          canShareVersion={canShareVersion}
          decisionModuleStates={decisionModuleStates}
          onOpenUserCenter={onOpenUserCenter}
          onSubmit={onSubmit}
          onOptimizeItinerary={onOptimizeItinerary}
          onDecisionModuleAction={onDecisionModuleAction}
          onVersionSelect={onVersionSelect}
          onExportVersion={onExportVersion}
          onShareVersion={onShareVersion}
        />
      </div>
    </div>
  );
}

function OverviewWorkbench({
  latest,
  streamStages,
  searchMode,
  planVersions,
  guideSources,
  guestMode,
  onJump,
}: {
  latest: ChatResponse | null;
  streamStages: StreamStage[];
  searchMode: SearchMode;
  planVersions: PlanVersion[];
  guideSources: GuideSourceItem[];
  guestMode: boolean;
  onJump: (view: WorkspaceView) => void;
}) {
  const trains = getRailwayTrains(latest);
  const cards = latest?.cards || [];

  return (
    <div className="view-frame overview-page">
      <section className="overview-hero-band">
        <div className="overview-hero-copy">
          <div className="section-kicker">
            <ShieldCheck size={16} />
            决策总览
          </div>
          <h2>{cards.find((item) => item.type === "destination")?.title || "等待本次旅行目的地"}</h2>
          <p>{latest?.answer?.split("\n").find((item) => item.trim()) || "开始一次新规划后，这里会先提炼最关键的旅行结论。"}</p>
          <div className="overview-action-row">
            <button type="button" className="primary-action" onClick={() => onJump("planning")}>
              <ListChecks size={15} />
              进入规划
            </button>
            <button type="button" className="secondary-action" onClick={() => onJump("railway")}>
              <TrainFront size={15} />
              查看车次
            </button>
            <button type="button" className="secondary-action" onClick={() => onJump("evidence")}>
              <DatabaseZap size={15} />
              查看证据
            </button>
          </div>
        </div>
        <div className="overview-signal-grid">
          <SignalCard icon={<Route size={16} />} label="检索模式" value={searchMode === "auto" ? "自动检索" : searchMode === "local_only" ? "仅攻略库" : "联网增强"} />
          <SignalCard icon={<TrainFront size={16} />} label="车次候选" value={`${trains.length}`} />
          <SignalCard icon={<GitBranch size={16} />} label="方案版本" value={`${planVersions.length}`} />
          <SignalCard icon={<Link2 size={16} />} label="本地来源" value={`${guideSources.length}`} />
        </div>
      </section>

      <section className="page-band">
        <div className="band-head">
          <div className="section-kicker">
            <ListChecks size={15} />
            调度进度
          </div>
          <span>{streamStages.length ? `${streamStages.length} 个步骤` : "等待执行"}</span>
        </div>
        <div className="stage-pill-row">
          {(streamStages.length ? streamStages : [
            { name: "idle", label: "等待新问题", status: "done" as const, summary: "尚未开始本轮调度" },
          ]).map((stage) => (
            <div className={`stage-pill-card ${stage.status}`} key={stage.name}>
              <strong>{stage.label}</strong>
              <span>{stage.summary || "已完成"}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="overview-grid">
        <article className="page-band">
          <div className="band-head">
            <div className="section-kicker">
              <TrainFront size={15} />
              铁路摘要
            </div>
            <button type="button" className="quiet-link-button" onClick={() => onJump("railway")}>进入铁路页</button>
          </div>
          <div className="summary-stat-grid">
            <div>
              <span>最早出发</span>
              <strong>{findEarliestAppTrain(trains)?.start_time || "--:--"}</strong>
            </div>
            <div>
              <span>最短耗时</span>
              <strong>{findFastestAppTrain(trains)?.duration || "--"}</strong>
            </div>
            <div>
              <span>候选数</span>
              <strong>{trains.length}</strong>
            </div>
          </div>
        </article>

        <article className="page-band">
          <div className="band-head">
            <div className="section-kicker">
              <DatabaseZap size={15} />
              证据摘要
            </div>
            <button type="button" className="quiet-link-button" onClick={() => onJump("evidence")}>进入证据页</button>
          </div>
          <div className="summary-list">
            {(latest?.sources || []).slice(0, 4).map((source) => (
              <div className="summary-list-item" key={`${source.title}-${source.url}`}>
                <strong>{source.title}</strong>
                <span>{source.source_type || "local"}</span>
              </div>
            ))}
            {!latest?.sources?.length ? <div className="summary-list-empty">暂无来源摘要</div> : null}
          </div>
        </article>

        <article className="page-band">
          <div className="band-head">
            <div className="section-kicker">
              <GitBranch size={15} />
              版本摘要
            </div>
            <button type="button" className="quiet-link-button" onClick={() => onJump("versions")}>进入版本页</button>
          </div>
          <div className="summary-list">
            {planVersions.slice(-3).reverse().map((version) => (
              <div className="summary-list-item" key={version.id}>
                <strong>{version.name}</strong>
                <span>{version.reason}</span>
              </div>
            ))}
            {!planVersions.length ? <div className="summary-list-empty">尚未生成版本</div> : null}
          </div>
        </article>

        <article className="page-band">
          <div className="band-head">
            <div className="section-kicker">
              <ShieldCheck size={15} />
              会话状态
            </div>
            <button type="button" className="quiet-link-button" onClick={() => onJump("memory")}>进入我的页</button>
          </div>
          <div className="summary-stat-grid">
            <div>
              <span>身份</span>
              <strong>{guestMode ? "游客模式" : "登录用户"}</strong>
            </div>
            <div>
              <span>风险提醒</span>
              <strong>{latest?.warnings.length || 0}</strong>
            </div>
            <div>
              <span>决策模块</span>
              <strong>{latest?.decision_modules.length || 0}</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}

function RailwayDecisionPage({
  latest,
  onAdoptTrain,
  onWorkspaceSync,
  onSyncToPlanning,
}: {
  latest: ChatResponse | null;
  onAdoptTrain: (prompt: string) => void;
  onWorkspaceSync: (draft: RailwayWorkspaceDraft | null) => void;
  onSyncToPlanning: () => void;
}) {
  const trains = getRailwayTrains(latest);
  const fastest = findFastestAppTrain(trains);
  const earliest = findEarliestAppTrain(trains);
  const [sortMode, setSortMode] = useState<"departure" | "duration" | "train_no">("departure");
  const [trainTypeFilter, setTrainTypeFilter] = useState<"all" | "high_speed" | "normal">("all");
  const [seatFilter, setSeatFilter] = useState<"all" | "available">("all");
  const [compareKeys, setCompareKeys] = useState<string[]>([]);
  const [candidateKeys, setCandidateKeys] = useState<string[]>([]);

  const filteredTrains = useMemo(() => {
    return trains.filter((train) => {
      const typeMatched =
        trainTypeFilter === "all"
        || (trainTypeFilter === "high_speed" && isAppHighSpeedTrain(train))
        || (trainTypeFilter === "normal" && !isAppHighSpeedTrain(train));
      const seatMatched = seatFilter === "all" || appHasAvailableSeat(train);
      return typeMatched && seatMatched;
    });
  }, [seatFilter, trainTypeFilter, trains]);

  const sorted = useMemo(() => {
    const items = [...filteredTrains];
    if (sortMode === "duration") {
      return items.sort((left, right) => toAppDuration(left.duration) - toAppDuration(right.duration));
    }
    if (sortMode === "train_no") {
      return items.sort((left, right) => String(left.train_no || "").localeCompare(String(right.train_no || ""), "zh-CN"));
    }
    return items.sort((left, right) => toAppMinutes(left.start_time) - toAppMinutes(right.start_time));
  }, [filteredTrains, sortMode]);

  const compareTrains = useMemo(
    () => compareKeys.map((key) => trains.find((train, index) => getAppTrainKey(train, index) === key)).filter(Boolean) as RailwayTrain[],
    [compareKeys, trains],
  );
  const candidateTrains = useMemo(
    () => candidateKeys.map((key) => trains.find((train, index) => getAppTrainKey(train, index) === key)).filter(Boolean) as RailwayTrain[],
    [candidateKeys, trains],
  );

  useEffect(() => {
    if (!compareTrains.length && !candidateTrains.length) {
      onWorkspaceSync(null);
      return;
    }
    onWorkspaceSync({
      compare_trains: compareTrains,
      candidate_trains: candidateTrains,
      generated_at: new Date().toISOString(),
      summary: buildAppRailwayWorkspaceSummary(compareTrains, candidateTrains),
    });
  }, [candidateTrains, compareTrains, onWorkspaceSync]);

  function toggleCompare(train: RailwayTrain, index: number) {
    const key = getAppTrainKey(train, index);
    setCompareKeys((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      return [...current.slice(-2), key];
    });
  }

  function toggleCandidate(train: RailwayTrain, index: number) {
    const key = getAppTrainKey(train, index);
    setCandidateKeys((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      return [...current, key];
    });
  }

  return (
    <div className="view-frame railway-page">
      <section className="page-band railway-page-hero">
        <div>
          <div className="section-kicker">
            <TrainFront size={16} />
            铁路比选页
          </div>
          <h2>{latest?.cards.find((item) => item.type === "railway")?.title || "等待铁路查询"}</h2>
          <p>把全部候选车次放在一个独立工作页，不再让聊天、版本和证据与它争抢首屏空间。</p>
        </div>
        <div className="summary-stat-grid">
          <div>
            <span>总车次</span>
            <strong>{trains.length}</strong>
          </div>
          <div>
            <span>最早出发</span>
            <strong>{earliest?.start_time || "--:--"}</strong>
          </div>
          <div>
            <span>最短耗时</span>
            <strong>{fastest?.duration || "--"}</strong>
          </div>
        </div>
      </section>

      <section className="page-band railway-control-band">
        <div className="railway-filter-group">
          <div className="section-kicker">
            <SlidersHorizontal size={15} />
            高级筛选
          </div>
          <div className="railway-filter-row">
            <div className="railway-chip-group" role="group" aria-label="列车类型筛选">
              {[
                { value: "all", label: "全部" },
                { value: "high_speed", label: "高铁优先" },
                { value: "normal", label: "普速" },
              ].map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={`railway-filter-chip ${trainTypeFilter === item.value ? "active" : ""}`}
                  onClick={() => setTrainTypeFilter(item.value as "all" | "high_speed" | "normal")}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="railway-chip-group" role="group" aria-label="余票筛选">
              {[
                { value: "all", label: "全部余票" },
                { value: "available", label: "仅看有票" },
              ].map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={`railway-filter-chip ${seatFilter === item.value ? "active" : ""}`}
                  onClick={() => setSeatFilter(item.value as "all" | "available")}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="railway-filter-group">
          <div className="section-kicker">
            <Clock3 size={15} />
            排序方式
          </div>
          <div className="railway-chip-group" role="group" aria-label="车次排序">
            {[
              { value: "departure", label: "按出发" },
              { value: "duration", label: "按耗时" },
              { value: "train_no", label: "按车次" },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                className={`railway-filter-chip ${sortMode === item.value ? "active" : ""}`}
                onClick={() => setSortMode(item.value as "departure" | "duration" | "train_no")}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="railway-decision-signals">
          <SignalCard icon={<TrainFront size={16} />} label="筛选后车次" value={`${sorted.length}`} />
          <SignalCard icon={<Layers3 size={16} />} label="候选方案池" value={`${candidateTrains.length}`} />
          <SignalCard icon={<Route size={16} />} label="对比栏" value={`${compareTrains.length} / 3`} />
        </div>
      </section>

      <div className="railway-decision-grid">
        <section className="railway-ledger-shell">
          <div className="railway-ledger-head">
            <strong>车次总表</strong>
            <span>{sorted.length ? "支持比较、加入候选池并直接纳入方案" : "暂无符合筛选条件的车次"}</span>
          </div>
          <div className="railway-ledger-table">
            {sorted.map((train, index) => {
              const key = getAppTrainKey(train, index);
              const compared = compareKeys.includes(key);
              const candidate = candidateKeys.includes(key);
              return (
                <article className={`railway-ledger-row advanced ${compared ? "compared" : ""} ${candidate ? "candidate" : ""}`} key={key}>
                  <div className="railway-ledger-main">
                    <strong>{train.train_no || "车次"}</strong>
                    <span>{train.from_station || "出发站"} → {train.to_station || "到达站"}</span>
                    <div className="railway-tag-row">
                      {getAppTrainTags(train, earliest, fastest).map((tag) => (
                        <em key={tag}>{tag}</em>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span>出发</span>
                    <strong>{train.start_time || "--:--"}</strong>
                  </div>
                  <div>
                    <span>到达</span>
                    <strong>{train.arrive_time || "--:--"}</strong>
                  </div>
                  <div>
                    <span>耗时</span>
                    <strong>{train.duration || "--"}</strong>
                  </div>
                  <div className="railway-seat-cell">
                    <span>座席</span>
                    <strong>{appSeatSummary(train)}</strong>
                  </div>
                  <div className="railway-ledger-actions">
                    <button type="button" className={`railway-mini-action ${compared ? "active" : ""}`} onClick={() => toggleCompare(train, index)}>
                      {compared ? "取消对比" : "加入对比"}
                    </button>
                    <button type="button" className={`railway-mini-action ${candidate ? "active" : ""}`} onClick={() => toggleCandidate(train, index)}>
                      {candidate ? "移出候选" : "加入候选池"}
                    </button>
                    <button type="button" className="primary-action" onClick={() => onAdoptTrain(buildAppTrainPrompt(train))}>
                      <TrainFront size={14} />
                      纳入方案
                    </button>
                  </div>
                </article>
              );
            })}
            {!trains.length ? <div className="summary-list-empty">当前还没有铁路结果，先去规划页提问或触发车次查询。</div> : null}
            {trains.length && !sorted.length ? <div className="summary-list-empty">当前筛选条件下没有可显示车次，调整筛选后再看。</div> : null}
          </div>
        </section>

        <aside className="railway-side-console">
          <section className="page-band railway-console-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Route size={15} />
                多车次对比
              </div>
              <span>最多保留 3 条</span>
            </div>
            <div className="railway-compare-stack">
              {compareTrains.map((train, index) => (
                <article className="railway-compare-card" key={`${train.train_no}-${index}`}>
                  <strong>{train.train_no || "车次"}</strong>
                  <span>{train.from_station || "出发站"} → {train.to_station || "到达站"}</span>
                  <div className="railway-compare-metrics">
                    <div><span>出发</span><strong>{train.start_time || "--:--"}</strong></div>
                    <div><span>耗时</span><strong>{train.duration || "--"}</strong></div>
                    <div><span>余票</span><strong>{appHasAvailableSeat(train) ? "较稳" : "待确认"}</strong></div>
                  </div>
                  <p>{appSeatSummary(train)}</p>
                </article>
              ))}
              {!compareTrains.length ? <div className="summary-list-empty compact-empty">从左侧账本里挑 2 到 3 条车次加入对比。</div> : null}
            </div>
            {compareTrains.length >= 2 ? (
              <div className="railway-console-action-row">
                <button type="button" className="primary-action wide" onClick={() => onAdoptTrain(buildAppComparePrompt(compareTrains))}>
                  <WandSparkles size={15} />
                  基于对比生成建议
                </button>
                <button type="button" className="secondary-action wide" onClick={onSyncToPlanning}>
                  <ListChecks size={15} />
                  回写到规划页
                </button>
              </div>
            ) : null}
          </section>

          <section className="page-band railway-console-panel">
            <div className="band-head">
              <div className="section-kicker">
                <Layers3 size={15} />
                候选方案池
              </div>
              <span>把备选路线集中收纳</span>
            </div>
            <div className="railway-candidate-pool">
              {candidateTrains.map((train, index) => (
                <article className="railway-pool-item" key={`${train.train_no}-${index}`}>
                  <div>
                    <strong>{train.train_no || "车次"}</strong>
                    <span>{train.start_time || "--:--"} 出发 · {train.duration || "--"}</span>
                  </div>
                  <button
                    type="button"
                    className="railway-mini-action active"
                    onClick={() =>
                      setCandidateKeys((current) =>
                        current.filter((item) => item !== getAppTrainKey(train, trains.findIndex((candidateTrain) => candidateTrain === train))),
                      )
                    }
                  >
                    移出
                  </button>
                </article>
              ))}
              {!candidateTrains.length ? <div className="summary-list-empty compact-empty">还没有加入候选池的车次，适合把“不错但未最终确认”的方案先放这里。</div> : null}
            </div>
            {candidateTrains.length ? (
              <div className="railway-console-action-row">
                <button type="button" className="primary-action wide" onClick={() => onAdoptTrain(buildAppCandidatePoolPrompt(candidateTrains))}>
                  <TrainFront size={15} />
                  一键生成候选池方案
                </button>
                <button type="button" className="secondary-action wide" onClick={onSyncToPlanning}>
                  <ListChecks size={15} />
                  写回当前规划
                </button>
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}

function EvidenceWorkbench({
  latest,
  guideSources,
  searchMode,
  onSearchModeChange,
  onPrompt,
}: {
  latest: ChatResponse | null;
  guideSources: GuideSourceItem[];
  searchMode: SearchMode;
  onSearchModeChange: (mode: SearchMode) => void;
  onPrompt: (prompt: string) => void;
}) {
  const modeLabel =
    searchMode === "auto" ? "自动检索" : searchMode === "local_only" ? "仅攻略库" : "联网增强";
  const localSources = (latest?.sources || []).filter((item) => item.source_type !== "web_search");
  const webSources = (latest?.sources || []).filter((item) => item.source_type === "web_search");
  const indexedGuideCount = guideSources.filter((item) => item.crawl_status === "indexed").length;
  const failedGuideCount = guideSources.filter((item) => item.crawl_status === "failed" || item.crawl_status === "blocked").length;
  const toolCalls = latest?.tool_calls || [];
  const auditPrompts = [
    "只用本地攻略库重新给我一版可复核方案。",
    "请联网补充最新天气和交通变化，并区分联网来源与本地来源。",
    "把当前推荐方案的来源依据、工具调用和风险提醒列成审计清单。",
  ];

  return (
    <div className="view-frame evidence-page">
      <section className="page-band evidence-page-hero">
        <div>
          <div className="section-kicker">
            <DatabaseZap size={16} />
            证据工作页
          </div>
          <h2>来源、工具链与条件配置拆开看</h2>
          <p>把“怎么查”和“为什么这样推荐”单独拿出来，既更适合答辩展示，也更利于用户复核。</p>
        </div>
        <div className="overview-signal-grid evidence-hero-signals">
          <SignalCard icon={<Route size={16} />} label="当前模式" value={modeLabel} />
          <SignalCard icon={<Link2 size={16} />} label="引用来源" value={`${latest?.sources.length || 0}`} />
          <SignalCard icon={<DatabaseZap size={16} />} label="本地攻略源" value={`${indexedGuideCount} / ${guideSources.length}`} />
          <SignalCard icon={<Activity size={16} />} label="工具调用" value={`${toolCalls.length}`} />
        </div>
      </section>

      <div className="evidence-grid">
        <section className="page-band evidence-left-stack">
          <div className="band-head">
            <div className="section-kicker">
              <SlidersHorizontal size={15} />
              检索策略
            </div>
            <span>先定边界，再发起规划</span>
          </div>

          <div className="evidence-mode-strip" role="group" aria-label="切换检索策略">
            {[
              { value: "auto", label: "自动" },
              { value: "local_only", label: "攻略库" },
              { value: "web_enhanced", label: "联网增强" },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                className={`evidence-mode-pill ${searchMode === item.value ? "active" : ""}`}
                onClick={() => onSearchModeChange(item.value as SearchMode)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="embedded-sidebar-shell">
            <PlannerSidebar onPrompt={onPrompt} searchMode={searchMode} onSearchModeChange={onSearchModeChange} />
          </div>

          <div className="band-head evidence-subhead">
            <div className="section-kicker">
              <ListChecks size={15} />
              审计快捷问题
            </div>
          </div>
          <div className="evidence-prompt-grid">
            {auditPrompts.map((prompt) => (
              <button key={prompt} type="button" className="evidence-prompt-card" onClick={() => onPrompt(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        </section>

        <section className="page-band evidence-right-stack">
          <div className="band-head">
            <div className="section-kicker">
              <Activity size={15} />
              调度与证据审计
            </div>
            <span>本地来源、联网来源、工具链路拆开看</span>
          </div>

          <div className="embedded-insight-shell">
            <InsightPanel latest={latest} guideSources={guideSources} />
          </div>

          <div className="evidence-audit-grid">
            <article className="evidence-audit-card">
              <div className="band-head evidence-card-head">
                <strong>来源对照</strong>
                <span>{latest?.sources.length || 0} 条</span>
              </div>
              <div className="evidence-source-columns">
                <div>
                  <span className="evidence-column-title">本地攻略</span>
                  <div className="summary-list compact">
                    {localSources.slice(0, 6).map((source) => (
                      <div className="summary-list-item evidence-source-item" key={`${source.title}-${source.url}`}>
                        <strong>{source.title}</strong>
                        <span>{source.url || "本地知识库条目"}</span>
                      </div>
                    ))}
                    {!localSources.length ? <div className="summary-list-empty compact-empty">当前没有本地引用</div> : null}
                  </div>
                </div>
                <div>
                  <span className="evidence-column-title">联网来源</span>
                  <div className="summary-list compact">
                    {webSources.slice(0, 6).map((source) => (
                      <div className="summary-list-item evidence-source-item" key={`${source.title}-${source.url}`}>
                        <strong>{source.title}</strong>
                        <span>{source.url || "联网检索结果"}</span>
                      </div>
                    ))}
                    {!webSources.length ? <div className="summary-list-empty compact-empty">当前没有联网引用</div> : null}
                  </div>
                </div>
              </div>
            </article>

            <article className="evidence-audit-card">
              <div className="band-head evidence-card-head">
                <strong>工具调用账本</strong>
                <span>{toolCalls.length} 次</span>
              </div>
              <div className="evidence-tool-ledger">
                {toolCalls.map((call, index) => (
                  <div className={`evidence-tool-row ${call.status}`} key={`${call.tool_name}-${index}`}>
                    <strong>{call.tool_name}</strong>
                    <span>{call.output_summary || "已调用"}</span>
                    <em>{call.status}</em>
                  </div>
                ))}
                {!toolCalls.length ? <div className="summary-list-empty compact-empty">当前还没有工具调用记录</div> : null}
              </div>
            </article>

            <article className="evidence-audit-card">
              <div className="band-head evidence-card-head">
                <strong>攻略库健康度</strong>
                <span>{guideSources.length} 个源</span>
              </div>
              <div className="summary-stat-grid evidence-health-grid">
                <div>
                  <span>已入库</span>
                  <strong>{indexedGuideCount}</strong>
                </div>
                <div>
                  <span>异常源</span>
                  <strong>{failedGuideCount}</strong>
                </div>
                <div>
                  <span>候选覆盖</span>
                  <strong>{guideSources.length ? `${Math.round((indexedGuideCount / guideSources.length) * 100)}%` : "0%"}</strong>
                </div>
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>
  );
}

function VersionWorkbench({
  planVersions,
  activeVersionId,
  versionCompare,
  shareUrl,
  guestMode,
  canShareVersion,
  onSelectVersion,
  onExportVersion,
  onShareVersion,
  onOpenUserCenter,
}: {
  planVersions: PlanVersion[];
  activeVersionId: string | null;
  versionCompare: PlanVersionCompare | null;
  shareUrl: string | null;
  guestMode: boolean;
  canShareVersion: boolean;
  onSelectVersion: (versionId: string) => void;
  onExportVersion: (versionId: string, format: "markdown" | "html") => void;
  onShareVersion: (versionId: string) => void;
  onOpenUserCenter: () => void;
}) {
  const [pendingRollbackId, setPendingRollbackId] = useState<string | null>(null);
  const activeVersion = planVersions.find((item) => item.id === activeVersionId) || null;
  const pendingRollbackVersion = planVersions.find((item) => item.id === pendingRollbackId) || null;
  const versionTimeline = [...planVersions].sort((left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime());

  return (
    <div className="view-frame version-page">
      <section className="page-band version-page-hero">
        <div>
          <div className="section-kicker">
            <GitBranch size={16} />
            版本工作页
          </div>
          <h2>把每一次规划都保留下来，像产品版本一样回看</h2>
          <p>不再把版本管理挤在聊天旁边，而是给它一个完整工作页承载差异、导出和分享。</p>
        </div>
        <div className="overview-signal-grid version-hero-signals">
          <SignalCard icon={<GitBranch size={16} />} label="累计版本" value={`${planVersions.length}`} />
          <SignalCard icon={<Clock3 size={16} />} label="当前版本" value={activeVersion?.name || "尚未生成"} />
          <SignalCard icon={<Link2 size={16} />} label="当前来源" value={`${activeVersion?.response.sources.length || 0}`} />
          <SignalCard icon={<DatabaseZap size={16} />} label="当前工具" value={`${activeVersion?.response.tool_calls.length || 0}`} />
        </div>
      </section>

      <section className="page-band version-page-band">
        <div className="band-head">
          <div className="section-kicker">
            <Clock3 size={15} />
            版本时间线
          </div>
          <span>从初版到最近优化，完整回看每次决策演化</span>
        </div>

        <div className="version-timeline-strip">
          {versionTimeline.map((version, index) => {
            const active = version.id === activeVersionId;
            return (
              <button
                type="button"
                key={version.id}
                className={`version-timeline-node ${active ? "active" : ""}`}
                onClick={() => onSelectVersion(version.id)}
              >
                <span>{index + 1}</span>
                <strong>{version.name}</strong>
                <em>{formatVersionTime(version.createdAt)}</em>
              </button>
            );
          })}
        </div>

        <div className="version-page-grid">
          {planVersions.map((version) => {
            const active = version.id === activeVersionId;
            return (
              <article className={`version-gallery-card ${active ? "active" : ""}`} key={version.id}>
                <div className="version-gallery-top">
                  <strong>{version.name}</strong>
                  <span>{version.reason}</span>
                </div>
                <div className="version-gallery-meta">
                  <em><Clock3 size={12} />{formatVersionTime(version.createdAt)}</em>
                  <em><Link2 size={12} />{version.response.sources.length} 来源</em>
                  <em><DatabaseZap size={12} />{version.response.tool_calls.length} 工具</em>
                </div>
                <div className="version-gallery-actions">
                  <button type="button" className="secondary-action" onClick={() => onSelectVersion(version.id)}>设为当前</button>
                  <button
                    type="button"
                    className="secondary-action"
                    onClick={() => setPendingRollbackId((current) => (current === version.id ? null : version.id))}
                  >
                    回切确认
                  </button>
                  <button type="button" className="secondary-action" onClick={() => onExportVersion(version.id, "markdown")}>导出 MD</button>
                  <button type="button" className="secondary-action" onClick={() => onExportVersion(version.id, "html")}>导出 HTML</button>
                  <button
                    type="button"
                    className="primary-action"
                    onClick={() => {
                      if (!canShareVersion) {
                        onOpenUserCenter();
                        return;
                      }
                      onShareVersion(version.id);
                    }}
                  >
                    {canShareVersion ? "分享版本" : "登录后分享"}
                  </button>
                </div>

                {pendingRollbackId === version.id ? (
                  <div className="version-rollback-panel">
                    <span>准备回切</span>
                    <strong>将当前方案切换到「{version.name}」并继续围绕该版本优化。</strong>
                    <div className="version-rollback-actions">
                      <button
                        type="button"
                        className="primary-action"
                        onClick={() => {
                          onSelectVersion(version.id);
                          setPendingRollbackId(null);
                        }}
                      >
                        确认回切
                      </button>
                      <button type="button" className="secondary-action" onClick={() => setPendingRollbackId(null)}>
                        取消
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
          {!planVersions.length ? <div className="summary-list-empty">还没有任何版本，先在规划页生成方案。</div> : null}
        </div>
        {guestMode ? <div className="version-login-hint">游客模式下版本仅保留在当前浏览器页面，登录后可保存到历史中心。</div> : null}
        {shareUrl ? <div className="share-url-strip"><Link2 size={14} /><span>{shareUrl}</span><strong>已复制</strong></div> : null}
        {versionCompare ? (
          <div className="version-compare-wide">
            <strong>{versionCompare.title}</strong>
            <span>{versionCompare.summary}</span>
            <div className="summary-stat-grid">
              <div><span>来源变化</span><strong>{versionCompare.metrics.source_delta}</strong></div>
              <div><span>工具变化</span><strong>{versionCompare.metrics.tool_delta}</strong></div>
              <div><span>模块变化</span><strong>{versionCompare.metrics.module_delta}</strong></div>
            </div>
            {versionCompare.highlights?.length ? (
              <div className="version-highlight-list">
                {versionCompare.highlights.map((item) => (
                  <div key={item} className="version-highlight-item">{item}</div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {pendingRollbackVersion ? (
          <div className="version-rollback-banner">
            <div>
              <span>待确认回切版本</span>
              <strong>{pendingRollbackVersion.name}</strong>
            </div>
            <div className="version-rollback-actions">
              <button
                type="button"
                className="primary-action"
                onClick={() => {
                  onSelectVersion(pendingRollbackVersion.id);
                  setPendingRollbackId(null);
                }}
              >
                立即回切
              </button>
              <button type="button" className="secondary-action" onClick={() => setPendingRollbackId(null)}>
                取消
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function MemoryWorkbench({
  guestMode,
  currentUser,
  conversations,
  profile,
  onOpenHistory,
  onOpenUserCenter,
}: {
  guestMode: boolean;
  currentUser: LocalUser | null;
  conversations: ConversationSummary[];
  profile: PreferenceProfile | null;
  onOpenHistory: () => void;
  onOpenUserCenter: () => void;
}) {
  return (
    <PreferenceProfileWorkbench
      guestMode={guestMode}
      currentUser={currentUser}
      conversations={conversations}
      profile={profile}
      onOpenHistory={onOpenHistory}
      onOpenUserCenter={onOpenUserCenter}
    />
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

function getRailwayTrains(latest: ChatResponse | null): RailwayTrain[] {
  const value = latest?.cards.find((item) => item.type === "railway")?.meta?.trains;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is RailwayTrain => typeof item === "object" && item !== null);
}

function appSeatSummary(train: RailwayTrain) {
  const seats = train.seats || {};
  const parts = [
    seats.second_class ? `二等${seats.second_class}` : null,
    seats.first_class ? `一等${seats.first_class}` : null,
    seats.business_class ? `商务${seats.business_class}` : null,
  ].filter(Boolean);
  return parts.join(" / ") || "余票请以 12306 为准";
}

function toAppMinutes(value?: string) {
  if (!value || !value.includes(":")) return Number.POSITIVE_INFINITY;
  const [hours, minutes] = value.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return Number.POSITIVE_INFINITY;
  return hours * 60 + minutes;
}

function toAppDuration(value?: string) {
  if (!value) return Number.POSITIVE_INFINITY;
  const matched = value.match(/(?:(\d+)\s*小时)?(?:(\d+)\s*分)?/);
  if (!matched) return Number.POSITIVE_INFINITY;
  return Number(matched[1] || 0) * 60 + Number(matched[2] || 0);
}

function findEarliestAppTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toAppMinutes(left.start_time) - toAppMinutes(right.start_time))[0];
}

function findFastestAppTrain(trains: RailwayTrain[]) {
  return [...trains].sort((left, right) => toAppDuration(left.duration) - toAppDuration(right.duration))[0];
}

function buildAppTrainPrompt(train: RailwayTrain) {
  return [
    `请把 ${train.train_no || "这趟车"} 纳入当前旅行方案继续优化。`,
    `车次信息：${train.from_station || "出发站"} 到 ${train.to_station || "到达站"}，${train.start_time || "--:--"} 出发，${train.arrive_time || "--:--"} 到达，耗时 ${train.duration || "待确认"}。`,
    `座席情况：${appSeatSummary(train)}。`,
    "请重新评估当天景点顺序、地图通勤、预算和行程强度，并输出新的可执行方案。",
  ].join("\n");
}

// 铁路决策台会复用这些判定函数，保持筛选、对比和候选池口径一致。
function getAppTrainKey(train: RailwayTrain, index = 0) {
  return `${train.train_no || "train"}-${train.start_time || "start"}-${train.arrive_time || "arrive"}-${index}`;
}

function isAppHighSpeedTrain(train: RailwayTrain) {
  return /^[GDC]/i.test(train.train_no || "");
}

function appHasAvailableSeat(train: RailwayTrain) {
  const seats = Object.values(train.seats || {});
  if (!seats.length) return false;
  return seats.some((value) => {
    const text = String(value || "").trim();
    return Boolean(text && !["0", "--", "无", "候补", "无票"].includes(text));
  });
}

function getAppTrainTags(train: RailwayTrain, earliestTrain?: RailwayTrain, fastestTrain?: RailwayTrain) {
  const tags: string[] = [];
  if (train.train_no && train.train_no === earliestTrain?.train_no) tags.push("最早出发");
  if (train.train_no && train.train_no === fastestTrain?.train_no) tags.push("耗时最短");
  if (isAppHighSpeedTrain(train)) tags.push("高铁优先");
  if (appHasAvailableSeat(train)) tags.push("余票较稳");
  return tags.length ? tags : ["常规候选"];
}

function buildAppComparePrompt(trains: RailwayTrain[]) {
  return [
    "请基于以下多条铁路候选车次，给出明确比选建议，并指出推荐理由、适合人群和可能风险。",
    ...trains.map((train, index) =>
      `${index + 1}. ${train.train_no || "车次"}：${train.from_station || "出发站"} 到 ${train.to_station || "到达站"}，${train.start_time || "--:--"} 出发，${train.arrive_time || "--:--"} 到达，耗时 ${train.duration || "待确认"}，座席 ${appSeatSummary(train)}。`,
    ),
    "请同时结合行程强度、到达后衔接、预算和当天景点顺序，输出最推荐方案与备选方案。",
  ].join("\n");
}

function buildAppCandidatePoolPrompt(trains: RailwayTrain[]) {
  return [
    "请把以下候选池中的车次作为备选交通方案，一次性重整当前旅行规划。",
    ...trains.map((train, index) =>
      `${index + 1}. ${train.train_no || "车次"}：${train.from_station || "出发站"} 到 ${train.to_station || "到达站"}，${train.start_time || "--:--"} 出发，${train.arrive_time || "--:--"} 到达，耗时 ${train.duration || "待确认"}，座席 ${appSeatSummary(train)}。`,
    ),
    "请输出一个主推荐方案，并保留 1 到 2 个备选交通分支，说明何时应切换备选方案。",
  ].join("\n");
}

function buildAppRailwayWorkspaceSummary(compareTrains: RailwayTrain[], candidateTrains: RailwayTrain[]) {
  const compareNames = compareTrains.map((train) => train.train_no || "车次").join("、");
  const candidateNames = candidateTrains.map((train) => train.train_no || "车次").join("、");
  const parts = [];
  if (compareTrains.length) {
    parts.push(`已在铁路页完成 ${compareTrains.length} 条车次对比：${compareNames}`);
  }
  if (candidateTrains.length) {
    parts.push(`已加入候选方案池 ${candidateTrains.length} 条：${candidateNames}`);
  }
  return parts.join("；") || "铁路工作台尚未形成可回写的选择结果。";
}

function buildAppRailwayWorkspacePrompt(draft: RailwayWorkspaceDraft) {
  return [
    "请基于我在铁路工作台里已经筛选好的结果，重新优化当前旅行规划。",
    draft.summary,
    draft.compare_trains.length
      ? `重点比较车次：${draft.compare_trains.map((train) => `${train.train_no || "车次"}（${train.start_time || "--:--"} 出发，${train.duration || "待确认"}）`).join("；")}`
      : "当前没有重点对比车次。",
    draft.candidate_trains.length
      ? `候选方案池：${draft.candidate_trains.map((train) => `${train.train_no || "车次"}（${train.start_time || "--:--"} 出发，${appSeatSummary(train)}）`).join("；")}`
      : "当前没有候选方案池车次。",
    "请结合景点顺序、城市内交通衔接、预算和行程强度，给出主推荐铁路方案，并保留必要备选。",
  ].join("\n");
}

function buildAppDecisionModuleKey(module: DecisionModule) {
  return `${module.type}::${module.title}`;
}

function buildAppDecisionModulePrompt(
  module: DecisionModule,
  action: "accept" | "ignore" | "regenerate",
) {
  const points = module.points.length ? module.points.map((point) => `- ${point}`).join("\n") : "- 无";
  const actionPromptMap = {
    accept: "请把这条建议作为当前方案的明确约束继续优化，并说明它会如何影响交通、节奏、预算或风险。",
    ignore: "请在后续规划中弱化或移除这条建议，并给出替代思路，避免继续沿用这一判断。",
    regenerate: "请只重算这个决策维度，保持其他已成立的行程背景不变，并输出新的建议与理由。",
  } satisfies Record<"accept" | "ignore" | "regenerate", string>;

  return [
    `当前要处理的决策模块：${module.title}`,
    `模块类型：${module.type}`,
    `当前摘要：${module.summary}`,
    "关键要点：",
    points,
    actionPromptMap[action],
  ].join("\n");
}

function formatVersionTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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
