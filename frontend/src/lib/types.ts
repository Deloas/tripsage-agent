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
  negative_preferences: string[];
  explicit_preferences: string[];
  inferred_preferences: string[];
  behavior_signals: string[];
  profile_strength: "new" | "growing" | "strong" | string;
  budget_profile?: {
    median?: number | null;
    lower_bound?: number | null;
    upper_bound?: number | null;
    sensitivity?: string | null;
  } | null;
  recent_evidence: Array<{
    dimension: string;
    value: string;
    polarity: string;
    source_type: string;
    confidence: number;
    weight: number;
    created_at: string;
  }>;
  recommendation_hint: string;
  long_term_profile: PreferenceLayer;
  session_profile: PreferenceLayer;
  blacklist_items?: PreferenceGovernanceItem[];
  locked_items?: PreferenceGovernanceItem[];
  updated_at?: string | null;
}

export interface PreferenceGovernanceItem {
  dimension: string;
  value: string;
  label: string;
  source_type: string;
  created_at: string;
  note?: string | null;
}

export interface PreferenceLayer {
  preferred_cities: string[];
  budget_range?: string | null;
  transport_modes: string[];
  pace_tags: string[];
  interest_tags: string[];
  negative_preferences: string[];
  explicit_preferences: string[];
  inferred_preferences: string[];
  behavior_signals: string[];
  profile_strength: "new" | "growing" | "strong" | string;
  budget_profile?: {
    median?: number | null;
    lower_bound?: number | null;
    upper_bound?: number | null;
    sensitivity?: string | null;
  } | null;
  recent_evidence: Array<{
    dimension: string;
    value: string;
    polarity: string;
    source_type: string;
    confidence: number;
    weight: number;
    created_at: string;
  }>;
  recommendation_hint: string;
  updated_at?: string | null;
}

export interface PreferenceFeedbackPayload {
  dimension: string;
  value: string;
  action?:
    | "set_common"
    | "session_only"
    | "avoid"
    | "remove_long_term"
    | "remove_avoid"
    | "lock_long_term"
    | "unlock_long_term";
  polarity?: "positive" | "negative";
  conversation_id?: string | null;
}

export interface PreferenceBehaviorEventPayload {
  action:
    | "version_select"
    | "version_rollback"
    | "favorite_on"
    | "favorite_off"
    | "share_plan"
    | "history_open"
    | "continue_optimize"
    | "memory_open"
    | "audit_open"
    | "governance_open"
    | "blacklist_remove"
    | "profile_lock"
    | "profile_unlock"
    | "timeline_undo";
  payload?: Record<string, unknown>;
  conversation_id?: string | null;
}

export interface PreferenceTimelineItem {
  id: number;
  title: string;
  description: string;
  dimension: string;
  value: string;
  polarity: string;
  source_type: string;
  source_label: string;
  scope: "long_term" | "session" | "behavior" | string;
  signal_count: number;
  conversation_id?: string | null;
  can_undo: boolean;
  is_undone: boolean;
  created_at: string;
  undone_at?: string | null;
}

export interface PreferenceTimelineResult {
  items: PreferenceTimelineItem[];
  total: number;
}

export interface PreferenceTimelineUndoPayload {
  event_id: number;
  conversation_id?: string | null;
}

export interface PreferenceTimelineUndoResult {
  profile: PreferenceProfile;
  timeline: PreferenceTimelineResult;
  undone_event_id: number;
}

export interface PreferenceAuditItem {
  id?: number | null;
  dimension: string;
  dimension_label: string;
  value: string;
  display_value: string;
  polarity: string;
  source_type: string;
  source_label: string;
  source_group: string;
  scope: string;
  score: number;
  confidence: number;
  weight: number;
  created_at: string;
  conversation_id?: string | null;
  is_locked: boolean;
  is_blacklisted: boolean;
  is_undone: boolean;
  note?: string | null;
}

export interface PreferenceAuditGroup {
  key: string;
  label: string;
  total: number;
  items: PreferenceAuditItem[];
}

export interface PreferenceAuditSummary {
  total_events: number;
  explicit_total: number;
  inferred_total: number;
  behavior_total: number;
  session_total: number;
  long_term_total: number;
  locked_total: number;
  blacklist_total: number;
}

export interface PreferenceAuditResult {
  summary: PreferenceAuditSummary;
  by_dimension: PreferenceAuditGroup[];
  by_source: PreferenceAuditGroup[];
  by_scope: PreferenceAuditGroup[];
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

export interface GuideFacetOption {
  value: string;
  label: string;
  count: number;
}

export interface GuideLibraryResult {
  items: GuideItem[];
  total: number;
  limit: number;
  offset: number;
  sort_by?: string;
  filters: {
    source_types: GuideFacetOption[];
    cities: GuideFacetOption[];
    categories: GuideFacetOption[];
  };
}

export interface GuideDetail {
  id: number;
  title: string;
  city: string;
  summary: string;
  days?: number | null;
  budget_min?: number | null;
  budget_max?: number | null;
  travel_style?: string | null;
  source_url?: string;
  source_type?: string;
  category?: string;
  crawl_status?: string;
  content: string;
  created_at?: string | null;
  chunk_count: number;
  structured?: {
    city?: string;
    days?: number | null;
    summary?: string;
    budget_min?: number | null;
    budget_max?: number | null;
    budget_range?: string | null;
    transport_modes?: string[];
    lodging_suggestions?: string[];
    travel_style_tags?: string[];
    scenic_spots?: string[];
    food_spots?: string[];
    places?: Array<{
      name: string;
      type?: string | null;
    }>;
  } | null;
  chunks: Array<{
    id: string;
    chunk_index: number;
    content: string;
  }>;
  places: Array<{
    name: string;
    city: string;
    place_type?: string | null;
    address?: string | null;
  }>;
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
