import axios, { AxiosError, type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

import type {
  ApiResponse,
  AiMapWorkbenchResult,
  AmapClientConfig,
  AuthResult,
  AuthSession,
  AuthState,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  ConversationUpdatePayload,
  GuestSessionImportPayload,
  GuestSessionImportResult,
  GuideDetail,
  GuideRoutePreviewResult,
  GuideImportRecordItem,
  GuideImportTaskItem,
  GuideLinkImportResult,
  GuideLinkPreviewResult,
  GuideUpdatePayload,
  GuideUpdateResult,
  GuideItem,
  GuideLibraryResult,
  GuideSourceItem,
  LocalUser,
  PlanExportResult,
  PlanVersion,
  PlanVersionCompare,
  PreferenceBehaviorEventPayload,
  PreferenceAuditResult,
  PreferenceFeedbackPayload,
  PreferenceProfile,
  PreferenceTimelineResult,
  PreferenceTimelineUndoPayload,
  PreferenceTimelineUndoResult,
  RenderPlan,
  SharedPlan,
  StreamStage,
  StructuredTravelPlan,
  TravelPlanView,
  ToolStatus,
  RailwayQueryResult,
  UserProfileUpdatePayload,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";
const ACCESS_TOKEN_KEY = "tripsage_access_token";
const REFRESH_TOKEN_KEY = "tripsage_refresh_token";
const CLIENT_NAME = "TripSage Web";
const CHAT_TIMEOUT_MS = 180000;
const GUIDE_IMPORT_TIMEOUT_MS = 240000;

type ApiConfig = InternalAxiosRequestConfig & {
  _authRetry?: boolean;
  _skipAuthRefresh?: boolean;
};

class ApiCodeError extends Error {
  code: number;
  data: unknown;
  traceId?: string;

  constructor(message: string, code: number, data: unknown, traceId?: string) {
    super(message);
    this.name = "ApiCodeError";
    this.code = code;
    this.data = data;
    this.traceId = traceId;
  }
}

const rawApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

let accessToken = readStoredValue(ACCESS_TOKEN_KEY);
let refreshToken = readStoredValue(REFRESH_TOKEN_KEY);
let refreshPromise: Promise<AuthResult> | null = null;

api.interceptors.request.use((config) => {
  const nextConfig = config as ApiConfig;
  nextConfig.headers = nextConfig.headers || {};
  nextConfig.headers["X-Client-Name"] = CLIENT_NAME;
  if (accessToken) {
    nextConfig.headers.Authorization = `Bearer ${accessToken}`;
  }
  return nextConfig;
});

api.interceptors.response.use(async (response) => {
  const body = response.data as ApiResponse<unknown> | undefined;
  if (!body || typeof body.code !== "number") return response;
  if (body.code === 0) return response;

  const config = response.config as ApiConfig;
  const canRefresh = body.code === 4011
    && !config._authRetry
    && !config._skipAuthRefresh
    && Boolean(refreshToken)
    && !(config.url || "").startsWith("/auth/");

  if (canRefresh) {
    config._authRetry = true;
    await ensureFreshAccessToken();
    config.headers = config.headers || {};
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    config.headers["X-Client-Name"] = CLIENT_NAME;
    return api.request(config);
  }

  throw buildApiCodeError(response);
});

function readStoredValue(key: string): string | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(key);
  return value && value.trim() ? value : null;
}

function persistAuthTokens(nextAccessToken: string | null, nextRefreshToken: string | null) {
  accessToken = nextAccessToken;
  refreshToken = nextRefreshToken;
  if (typeof window === "undefined") return;
  if (nextAccessToken) {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, nextAccessToken);
  } else {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  }
  if (nextRefreshToken) {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, nextRefreshToken);
  } else {
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  }
}

function applyAuthResult(result: AuthResult) {
  persistAuthTokens(result.access_token, result.refresh_token);
}

function buildApiCodeError<T>(response: AxiosResponse<ApiResponse<T>>) {
  const body = response.data;
  return new ApiCodeError(body.message || "请求失败", body.code, body.data, body.trace_id);
}

async function unwrapRaw<T>(request: Promise<AxiosResponse<ApiResponse<T>>>): Promise<T> {
  const response = await request;
  if (response.data.code !== 0) {
    throw buildApiCodeError(response);
  }
  return response.data.data;
}

async function ensureFreshAccessToken(): Promise<AuthResult> {
  if (!refreshToken) {
    throw new ApiCodeError("当前没有可用的刷新令牌", 4011, null);
  }
  if (!refreshPromise) {
    refreshPromise = unwrapRaw(
      rawApi.post<ApiResponse<AuthResult>>(
        "/auth/refresh",
        { refresh_token: refreshToken },
        { headers: { "X-Client-Name": CLIENT_NAME } },
      ),
    )
      .then((result) => {
        applyAuthResult(result);
        return result;
      })
      .catch((error) => {
        clearAuthSession();
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function withAuthStreamRetry<T>(runner: () => Promise<T>, allowRefresh: boolean): Promise<T> {
  try {
    return await runner();
  } catch (error) {
    if (allowRefresh && refreshToken && isAuthExpiredError(error)) {
      await ensureFreshAccessToken();
      return runner();
    }
    throw error;
  }
}

function isAuthExpiredError(error: unknown) {
  return error instanceof ApiCodeError && error.code === 4011;
}

export function clearAuthSession() {
  persistAuthTokens(null, null);
}

export function hasStoredAuthSession() {
  return Boolean(accessToken || refreshToken);
}

export function getAccessToken() {
  return accessToken;
}

export async function restoreAuthState(): Promise<AuthState | null> {
  if (!accessToken && !refreshToken) {
    return null;
  }
  try {
    return await fetchCurrentUser();
  } catch (error) {
    if (refreshToken) {
      try {
        await ensureFreshAccessToken();
        return await fetchCurrentUser();
      } catch {
        clearAuthSession();
        return null;
      }
    }
    clearAuthSession();
    return null;
  }
}

export async function fetchToolStatus(): Promise<ToolStatus> {
  const response = await api.get<ApiResponse<ToolStatus>>("/tools/status");
  return response.data.data;
}

export async function streamChat(
  message: string,
  conversationId: string | undefined,
  searchMode: "local_only" | "web_enhanced" | "auto",
  context: Record<string, unknown>,
  handlers: {
    onStart?: (conversationId: string) => void;
    onStage?: (stage: StreamStage) => void;
    onResult: (response: ChatResponse) => void;
    onError: (message: string) => void;
  },
): Promise<void> {
  const runStream = async () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-Client-Name": CLIENT_NAME,
    };
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
    }

    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        conversation_id: conversationId,
        message,
        search_mode: searchMode,
        context,
      }),
    });

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const body = await response.json() as ApiResponse<unknown>;
      throw new ApiCodeError(body.message || "流式请求失败", body.code, body.data, body.trace_id);
    }
    if (!response.ok || !response.body) {
      throw new Error(`stream failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const event = parseSseChunk(chunk);
        if (!event) continue;
        if (event.event === "start") handlers.onStart?.(String(event.data.conversation_id || ""));
        if (event.event === "stage") handlers.onStage?.(event.data as unknown as StreamStage);
        if (event.event === "result") handlers.onResult(event.data as unknown as ChatResponse);
        if (event.event === "error") handlers.onError(String(event.data.message || "智能体流式处理失败"));
      }
    }
  };

  await withAuthStreamRetry(runStream, Boolean(context.persist_session));
}

function parseSseChunk(chunk: string): { event: string; data: Record<string, unknown> } | null {
  const eventLine = chunk.split("\n").find((line) => line.startsWith("event:"));
  const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) return null;
  try {
    return {
      event: eventLine.replace("event:", "").trim(),
      data: JSON.parse(dataLine.replace("data:", "").trim()),
    };
  } catch {
    return null;
  }
}

export async function addGuide(payload: {
  title: string;
  content: string;
  source_url?: string;
  source_type?: string;
}): Promise<Record<string, unknown>> {
  return unwrapRaw(
    api.post<ApiResponse<Record<string, unknown>>>("/guides", {
      source_type: "manual",
      ...payload,
    }),
  );
}

export async function importGuideLink(payload: {
  url: string;
  category?: string;
  force_reimport?: boolean;
}): Promise<GuideLinkImportResult> {
  return unwrapRaw(
    api.post<ApiResponse<GuideLinkImportResult>>("/guides/import-link", payload, {
      timeout: GUIDE_IMPORT_TIMEOUT_MS,
    }),
  );
}

export async function previewGuideLink(payload: {
  url: string;
  category?: string;
  force_reimport?: boolean;
}): Promise<GuideLinkPreviewResult> {
  return unwrapRaw(
    api.post<ApiResponse<GuideLinkPreviewResult>>("/guides/import-link/preview", payload, {
      timeout: GUIDE_IMPORT_TIMEOUT_MS,
    }),
  );
}

export async function createGuideImportTask(payload: {
  url: string;
  category?: string;
  force_reimport?: boolean;
}): Promise<GuideImportTaskItem> {
  return unwrapRaw(api.post<ApiResponse<GuideImportTaskItem>>("/guides/import-link/tasks", payload));
}

export async function fetchGuideImportTask(taskId: string): Promise<GuideImportTaskItem> {
  return unwrapRaw(api.get<ApiResponse<GuideImportTaskItem>>(`/guides/import-link/tasks/${taskId}`));
}

export async function fetchGuideImportTasks(): Promise<GuideImportTaskItem[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: GuideImportTaskItem[]; total: number }>>("/guides/import-link/tasks", {
      params: { limit: 30 },
    }),
  ).then((data) => data.items);
}

export async function confirmGuideLink(payload: {
  url: string;
  title: string;
  content: string;
  category?: string;
  source_type?: string;
  resolved_url?: string;
  author?: string | null;
  structured?: Record<string, unknown> | null;
  force_reimport?: boolean;
}): Promise<GuideLinkImportResult> {
  return unwrapRaw(
    api.post<ApiResponse<GuideLinkImportResult>>("/guides/import-link/confirm", payload, {
      timeout: GUIDE_IMPORT_TIMEOUT_MS,
    }),
  );
}

export async function fetchGuides(): Promise<GuideItem[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: GuideItem[]; total: number }>>("/guides"),
  ).then((data) => data.items);
}

export async function fetchGuideLibrary(params?: {
  keyword?: string;
  city?: string;
  category?: string;
  source_type?: string;
  sort_by?: "latest" | "oldest" | "city_hot" | "source_priority";
  limit?: number;
  offset?: number;
}): Promise<GuideLibraryResult> {
  return unwrapRaw(
    api.get<ApiResponse<GuideLibraryResult>>("/guides", {
      params,
    }),
  );
}

export async function fetchGuideDetail(guideId: number): Promise<GuideDetail> {
  return unwrapRaw(api.get<ApiResponse<GuideDetail>>(`/guides/${guideId}`));
}

export async function fetchGuideRoutePreview(guideId: number, mode = "driving"): Promise<GuideRoutePreviewResult> {
  return unwrapRaw(
    api.get<ApiResponse<GuideRoutePreviewResult>>(`/guides/${guideId}/mobility/route-preview`, {
      params: { mode },
    }),
  );
}

export async function updateGuide(guideId: number, payload: GuideUpdatePayload): Promise<GuideUpdateResult> {
  return unwrapRaw(api.put<ApiResponse<GuideUpdateResult>>(`/guides/${guideId}`, payload));
}

export async function fetchGuideSources(status?: string): Promise<GuideSourceItem[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: GuideSourceItem[]; total: number }>>("/guides/sources", {
      params: {
        limit: 500,
        ...(status ? { status } : {}),
      },
    }),
  ).then((data) => data.items);
}

export async function fetchGuideImportRecords(): Promise<GuideImportRecordItem[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: GuideImportRecordItem[]; total: number }>>("/guides/import-records", {
      params: { limit: 50 },
    }),
  ).then((data) => data.items);
}

export async function deleteGuideImportRecord(recordId: number): Promise<GuideImportRecordItem & { deleted: boolean }> {
  return unwrapRaw(api.delete<ApiResponse<GuideImportRecordItem & { deleted: boolean }>>(`/guides/import-records/${recordId}`));
}

export async function queryRailway(payload: {
  origin: string;
  destination: string;
  date: string;
}): Promise<RailwayQueryResult> {
  return unwrapRaw(api.post<ApiResponse<RailwayQueryResult>>("/tools/railway", payload, { timeout: 60000 }));
}

export async function fetchAmapClientConfig(): Promise<AmapClientConfig> {
  return unwrapRaw(api.get<ApiResponse<AmapClientConfig>>("/tools/amap/client-config"));
}

export async function buildAiMapWorkbench(payload: {
  city?: string | null;
  answer: string;
  itinerary?: Array<{
    day: number;
    title: string;
    items: Array<{ time?: string; title: string; detail: string }>;
  }> | null;
  structured_plan?: StructuredTravelPlan | null;
  render_plan?: RenderPlan | null;
  travel_plan_view?: TravelPlanView | null;
  mode?: string;
}): Promise<AiMapWorkbenchResult> {
  return unwrapRaw(api.post<ApiResponse<AiMapWorkbenchResult>>("/tools/map/ai-workbench", payload, { timeout: 90000 }));
}

export async function crawlWeiboGuides(): Promise<Record<string, unknown>> {
  return unwrapRaw(api.post<ApiResponse<Record<string, unknown>>>("/guides/crawl/weibo"));
}

export async function savePlanVersion(version: PlanVersion, conversationId: string): Promise<PlanVersion> {
  return unwrapRaw(
    api.post<ApiResponse<PlanVersion>>("/plan-versions", {
      id: version.id,
      conversation_id: conversationId,
      name: version.name,
      reason: version.reason,
      created_at: version.createdAt,
      response: version.response,
    }),
  );
}

export async function fetchPlanVersions(conversationId: string): Promise<PlanVersion[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: PlanVersion[]; total: number }>>("/plan-versions", {
      params: { conversation_id: conversationId },
    }),
  ).then((data) => data.items);
}

export async function comparePlanVersions(baseId: string, targetId: string): Promise<PlanVersionCompare> {
  return unwrapRaw(
    api.get<ApiResponse<PlanVersionCompare>>("/plan-versions/compare", {
      params: { base_id: baseId, target_id: targetId },
    }),
  );
}

export async function exportPlanVersion(versionId: string, format: "markdown" | "html"): Promise<PlanExportResult> {
  return unwrapRaw(
    api.post<ApiResponse<PlanExportResult>>("/plan-versions/export", {
      version_id: versionId,
      format,
    }),
  );
}

export async function createSharedPlan(versionId: string): Promise<SharedPlan> {
  return unwrapRaw(
    api.post<ApiResponse<SharedPlan>>("/shared-plans", {
      version_id: versionId,
    }),
  );
}

export async function fetchSharedPlan(shareId: string): Promise<SharedPlan> {
  return unwrapRaw(api.get<ApiResponse<SharedPlan>>(`/shared-plans/${shareId}`));
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: ConversationSummary[]; total: number }>>("/conversations"),
  ).then((data) => data.items);
}

export async function fetchConversationDetail(conversationId: string): Promise<ConversationDetail> {
  return unwrapRaw(api.get<ApiResponse<ConversationDetail>>(`/conversations/${conversationId}`));
}

export async function updateConversation(
  conversationId: string,
  payload: ConversationUpdatePayload,
): Promise<ConversationSummary> {
  return unwrapRaw(api.patch<ApiResponse<ConversationSummary>>(`/conversations/${conversationId}`, payload));
}

export async function deleteConversation(conversationId: string): Promise<{ id: string; deleted: boolean }> {
  return unwrapRaw(api.delete<ApiResponse<{ id: string; deleted: boolean }>>(`/conversations/${conversationId}`));
}

export async function importGuestSession(payload: GuestSessionImportPayload): Promise<GuestSessionImportResult> {
  return unwrapRaw(api.post<ApiResponse<GuestSessionImportResult>>("/conversations/import-guest-session", payload));
}

export async function fetchPreferenceProfile(conversationId?: string | null): Promise<PreferenceProfile> {
  return unwrapRaw(
    api.get<ApiResponse<PreferenceProfile>>("/preference-profile", {
      params: conversationId ? { conversation_id: conversationId } : undefined,
    }),
  );
}

export async function submitPreferenceFeedback(payload: PreferenceFeedbackPayload): Promise<PreferenceProfile> {
  return unwrapRaw(api.post<ApiResponse<PreferenceProfile>>("/preference-profile/feedback", payload));
}

export async function trackPreferenceBehaviorEvent(payload: PreferenceBehaviorEventPayload): Promise<PreferenceProfile> {
  return unwrapRaw(api.post<ApiResponse<PreferenceProfile>>("/preference-profile/events", payload));
}

export async function fetchPreferenceTimeline(
  conversationId?: string | null,
  limit = 40,
): Promise<PreferenceTimelineResult> {
  return unwrapRaw(
    api.get<ApiResponse<PreferenceTimelineResult>>("/preference-profile/timeline", {
      params: {
        limit,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      },
    }),
  );
}

export async function fetchPreferenceAudit(
  conversationId?: string | null,
  limitPerGroup = 12,
): Promise<PreferenceAuditResult> {
  return unwrapRaw(
    api.get<ApiResponse<PreferenceAuditResult>>("/preference-profile/audit", {
      params: {
        limit_per_group: limitPerGroup,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      },
    }),
  );
}

export async function undoPreferenceTimelineEvent(
  payload: PreferenceTimelineUndoPayload,
): Promise<PreferenceTimelineUndoResult> {
  return unwrapRaw(api.post<ApiResponse<PreferenceTimelineUndoResult>>("/preference-profile/timeline/undo", payload));
}

export async function fetchUsers(): Promise<LocalUser[]> {
  return unwrapRaw(api.get<ApiResponse<{ items: LocalUser[]; total: number }>>("/users")).then((data) => data.items);
}

export async function createUser(payload: {
  display_name: string;
  username?: string;
  password?: string;
  home_city?: string;
  travel_style?: string;
}): Promise<LocalUser> {
  return unwrapRaw(rawApi.post<ApiResponse<LocalUser>>("/users", payload, {
    headers: { "X-Client-Name": CLIENT_NAME },
  }));
}

export async function registerUser(payload: {
  display_name: string;
  username?: string;
  password?: string;
  home_city?: string;
  travel_style?: string;
}): Promise<AuthResult> {
  const result = await unwrapRaw(
    rawApi.post<ApiResponse<AuthResult>>("/auth/register", payload, {
      headers: { "X-Client-Name": CLIENT_NAME },
    }),
  );
  applyAuthResult(result);
  return result;
}

export async function loginUser(payload: { username: string; password: string }): Promise<AuthResult> {
  const result = await unwrapRaw(
    rawApi.post<ApiResponse<AuthResult>>("/auth/login", payload, {
      headers: { "X-Client-Name": CLIENT_NAME },
    }),
  );
  applyAuthResult(result);
  return result;
}

export async function logoutUser(): Promise<void> {
  if (!refreshToken) {
    clearAuthSession();
    return;
  }
  try {
    await unwrapRaw(
      rawApi.post<ApiResponse<{ success: boolean }>>(
        "/auth/logout",
        { refresh_token: refreshToken },
        { headers: { "X-Client-Name": CLIENT_NAME } },
      ),
    );
  } finally {
    clearAuthSession();
  }
}

export async function fetchCurrentUser(): Promise<AuthState> {
  return unwrapRaw(api.get<ApiResponse<AuthState>>("/auth/me"));
}

export async function updateMyProfile(payload: UserProfileUpdatePayload): Promise<LocalUser> {
  return unwrapRaw(api.patch<ApiResponse<LocalUser>>("/users/me", payload));
}

export async function fetchAuthSessions(): Promise<AuthSession[]> {
  return unwrapRaw(
    api.get<ApiResponse<{ items: AuthSession[]; total: number }>>("/auth/sessions"),
  ).then((data) => data.items);
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  await unwrapRaw(api.delete<ApiResponse<{ success: boolean; session_id: string }>>(`/auth/sessions/${sessionId}`));
}

export { ApiCodeError };
