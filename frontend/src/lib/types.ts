export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  trace_id: string;
}

export interface ToolCall {
  tool_name: string;
  status: "success" | "failed" | "fallback";
  latency_ms?: number;
  output_summary?: string;
}

export interface SourceRef {
  title: string;
  url?: string;
  source_type?: string;
}

export interface ResultCard {
  type: string;
  title: string;
  summary: string;
  meta?: Record<string, unknown>;
}

export interface RailwayTrain {
  train_no?: string;
  from_station?: string;
  to_station?: string;
  start_time?: string;
  arrive_time?: string;
  duration?: string;
  seats?: Record<string, string>;
}

export interface ItineraryItem {
  time: string;
  title: string;
  detail: string;
}

export interface ItineraryBlock {
  day: number;
  title: string;
  items: ItineraryItem[];
}

export interface DecisionModule {
  type: "transport" | "rainy_day" | "intensity" | "budget" | "risk" | string;
  title: string;
  level: "good" | "warn" | "info" | string;
  summary: string;
  points: string[];
  meta?: Record<string, unknown>;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  intent: string;
  cards: ResultCard[];
  itinerary?: ItineraryBlock[] | null;
  tool_calls: ToolCall[];
  sources: SourceRef[];
  warnings: string[];
  decision_modules: DecisionModule[];
}

export interface PlanVersion {
  id: string;
  name: string;
  createdAt: string;
  reason: string;
  response: ChatResponse;
}

export interface PlanVersionCompare {
  base_id: string;
  target_id: string;
  title: string;
  summary: string;
  metrics: Record<string, number>;
  highlights: string[];
}

export interface PlanExportResult {
  filename: string;
  mime_type: string;
  content: string;
}

export interface SharedPlan {
  id: string;
  version_id: string;
  conversation_id: string;
  title: string;
  response: ChatResponse;
  createdAt: string;
}

export interface ConversationSummary {
  id: string;
  title?: string | null;
  status: string;
  message_count: number;
  version_count: number;
  updated_at: string;
  latest_message?: string | null;
  is_favorite: boolean;
  tags: string[];
  destination_city?: string | null;
  budget?: number | null;
  start_date?: string | null;
}

export interface ConversationDetail {
  id: string;
  title?: string | null;
  status: string;
  messages: Array<{ role: "user" | "assistant"; content: string; created_at: string }>;
  is_favorite: boolean;
  tags: string[];
  destination_city?: string | null;
  budget?: number | null;
  start_date?: string | null;
}

export interface ConversationUpdatePayload {
  title?: string | null;
  is_favorite?: boolean;
  tags?: string[];
  destination_city?: string | null;
  budget?: number | null;
  start_date?: string | null;
}

export interface PreferenceProfile {
  preferred_cities: string[];
  budget_range?: string | null;
  transport_modes: string[];
  pace_tags: string[];
  interest_tags: string[];
  recommendation_hint: string;
  updated_at?: string | null;
}

export interface LocalUser {
  id: number;
  username?: string | null;
  display_name?: string | null;
  home_city?: string | null;
  travel_style?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface AuthSession {
  id: string;
  client_name?: string | null;
  user_agent?: string | null;
  created_at: string;
  last_used_at?: string | null;
  expires_at: string;
  revoked_at?: string | null;
  is_current: boolean;
  is_active: boolean;
}

export interface AuthResult {
  user: LocalUser;
  access_token: string;
  refresh_token: string;
  access_expires_in_seconds: number;
  session: AuthSession;
}

export interface AuthState {
  user: LocalUser;
  session: AuthSession;
}

export interface UserProfileUpdatePayload {
  display_name?: string;
  home_city?: string;
  travel_style?: string;
  current_password?: string;
  new_password?: string;
}

export interface GuestSessionImportPayload {
  user_id: number;
  title?: string | null;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  plan_versions: Array<{
    id: string;
    name: string;
    reason: string;
    response: ChatResponse;
    created_at?: string | null;
  }>;
  active_version_id?: string | null;
  latest_response?: ChatResponse | null;
  destination_city?: string | null;
  budget?: number | null;
  start_date?: string | null;
  tags?: string[];
}

export interface GuestSessionImportResult {
  conversation_id: string;
  title?: string | null;
  active_version_id?: string | null;
  imported_message_count: number;
  imported_plan_version_count: number;
}

export interface GuestCarryoverSummary {
  title: string;
  destination?: string | null;
  message_count: number;
  version_count: number;
  active_version_name?: string | null;
}

export interface GuideItem {
  id: number;
  title: string;
  city: string;
  summary: string;
  source_url?: string;
  source_type?: string;
  category?: string;
  crawl_status?: string;
}

export interface GuideSourceItem {
  id: number;
  title: string;
  source_type: string;
  source_url?: string;
  raw_url?: string;
  category?: string;
  crawl_status: "indexed" | "pending" | "blocked" | "failed" | string;
}

export interface ToolStatus {
  llm: string;
  amap: string;
  mcp_12306: string;
  web_search: string;
  vector_store: string;
  demo_mode: boolean;
}

export interface StreamStage {
  name: string;
  label: string;
  status: "running" | "done" | "failed";
  summary?: string;
}
