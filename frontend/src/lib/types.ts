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

export interface RailwayQueryResult {
  provider?: string;
  origin?: string;
  destination?: string;
  date?: string;
  trains: RailwayTrain[];
  fallback?: boolean;
  notice?: string;
  reason?: string;
  tool_name?: string;
}

export interface AmapClientConfig {
  provider: "amap" | string;
  js_api_key?: string;
  security_js_code?: string;
  configured: boolean;
  web_service_configured: boolean;
}

export interface AiMapPoint {
  name: string;
  query: string;
  day?: number | null;
  source?: string | null;
  city?: string | null;
  district?: string | null;
  address?: string | null;
  type?: string | null;
  location?: string | null;
  lng?: number | null;
  lat?: number | null;
  fallback?: boolean;
  confidence?: number;
  score?: number;
}

export interface AiMapRouteLeg {
  index: number;
  origin: AiMapPoint;
  destination: AiMapPoint;
  mode?: string | null;
  mode_used?: string | null;
  distance_meters: number;
  duration_minutes: number;
  steps: Array<{
    instruction?: string | null;
    road?: string | null;
    distance_meters?: number | null;
    duration_seconds?: number | null;
  }>;
  fallback?: boolean;
  reason?: string | null;
}

export interface AiMapWorkbenchResult {
  city?: string | null;
  mode: string;
  points: AiMapPoint[];
  routes: AiMapRouteLeg[];
  total_distance_meters: number;
  total_duration_minutes: number;
  fallback: boolean;
  source: string;
  diagnostics: {
    candidate_count: number;
    resolved_count: number;
    has_js_key: boolean;
    web_service_configured: boolean;
  };
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

export interface StructuredAgendaItem {
  time?: string;
  title: string;
  detail: string;
  place_name?: string | null;
  transport_hint?: string | null;
}

export interface StructuredPlaceBrief {
  name: string;
  aliases?: string[];
  intro?: string;
  category?: string | null;
  stay_minutes?: number | null;
  transport_hint?: string | null;
  order?: number | null;
}

export interface StructuredPlanDay {
  day: number;
  title: string;
  summary?: string;
  route_digest?: string;
  agenda: StructuredAgendaItem[];
  places: StructuredPlaceBrief[];
}

export interface StructuredTravelPlan {
  city?: string | null;
  trip_summary?: string;
  planning_style?: string;
  budget_hint?: string;
  transport_hint?: string;
  rainy_day_hint?: string;
  risk_hint?: string;
  days: StructuredPlanDay[];
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
  structured_plan?: StructuredTravelPlan | null;
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
  import_audit?: GuideImportAudit | null;
  structured?: GuideStructuredDraft | null;
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

export interface GuideRoutePreviewNode {
  name: string;
  type?: string | null;
  city?: string | null;
  source?: string | null;
}

export interface GuideRoutePreviewLeg {
  index: number;
  origin: GuideRoutePreviewNode;
  destination: GuideRoutePreviewNode;
  provider?: string | null;
  mode?: string | null;
  mode_used?: string | null;
  distance_meters?: number | null;
  duration_minutes?: number | null;
  steps: Array<{
    instruction?: string | null;
    road?: string | null;
    distance_meters?: number | null;
    duration_seconds?: number | null;
  }>;
  fallback?: boolean;
  reason?: string | null;
}

export interface GuideRoutePreviewResult {
  guide_id: number;
  title: string;
  city: string;
  mode: string;
  nodes: GuideRoutePreviewNode[];
  routes: GuideRoutePreviewLeg[];
  total_distance_meters: number;
  total_duration_minutes: number;
  fallback: boolean;
  railway_seed: {
    origin: string;
    destination: string;
    destination_station: string;
    date: string;
    guide_id?: number | null;
    guide_title?: string | null;
    hint?: string | null;
  };
}

export interface GuideUpdatePayload {
  title: string;
  content: string;
  category?: string | null;
  author?: string | null;
  source_url?: string | null;
  structured?: GuideStructuredDraft | null;
}

export interface GuideUpdateResult {
  result: {
    guide_id: number;
    city: string;
    chunks: number;
    indexed: boolean;
    old_vectors_deleted?: boolean;
    extracted: GuideStructuredDraft;
  };
  guide: GuideDetail;
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

export interface GuideLinkImportResult {
  status: "indexed" | "duplicate" | "pending" | string;
  reason?: string;
  guide_id?: number;
  source_id?: number;
  title?: string;
  city?: string;
  chunks?: number;
  indexed?: boolean;
  source_type?: string;
  resolved_url?: string;
  llm_enhanced?: boolean;
  message?: string;
  quality?: {
    score: number;
    grade: string;
    city_confidence?: string;
    paragraph_count?: number;
    travel_signal_count?: number;
    content_length?: number;
    resolved_url?: string;
  } | null;
  diagnostics?: {
    fetch_method?: string;
    issue_code?: string | null;
    attempt_count?: number;
    quality_grade?: string;
    image_count?: number;
    image_urls?: string[];
    html_text_length?: number;
    html_preview_lines?: string[];
    source_preview_lines?: string[];
    final_preview_lines?: string[];
    final_content_length?: number;
      content_sources?: string[];
      ocr_used?: boolean;
      ocr_text_length?: number;
      ocr_preview_lines?: string[];
      ocr_image_total?: number;
      ocr_target_count?: number;
      ocr_processed_count?: number;
      ocr_success_count?: number;
      ocr_cached_count?: number;
      ocr_coverage_ratio?: number;
      ocr_elapsed_seconds?: number;
      ocr_image_results?: Array<{
        index?: number;
        url?: string;
        cached?: boolean;
        text_length?: number;
        score?: number;
      }>;
      vision_used?: boolean;
    vision_text_length?: number;
    vision_preview_lines?: string[];
    attempts?: Array<{
      method?: string;
      requested_url?: string;
      resolved_url?: string;
      status_code?: number;
      content_type?: string;
      issue_code?: string | null;
      error?: string;
    }>;
  } | null;
  guide?: GuideDetail | null;
  record?: GuideImportRecordItem | null;
}

export interface GuideLinkPreviewResult {
  status: "preview_ready" | "pending" | string;
  reason?: string | null;
  title: string;
  content: string;
  category?: string | null;
  source_type?: string;
  resolved_url?: string;
  author?: string | null;
  message?: string;
  structured?: GuideStructuredDraft | null;
  quality?: GuideLinkImportResult["quality"];
  diagnostics?: GuideLinkImportResult["diagnostics"];
  record?: GuideImportRecordItem | null;
}

export interface GuideImportTaskItem {
  id: string;
  url: string;
  category?: string | null;
  force_reimport: boolean;
  mode: "preview" | "import" | string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  stage: string;
  progress: number;
  title?: string | null;
  message?: string | null;
  result?: GuideLinkPreviewResult | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
}

export interface GuideStructuredDraft {
  city?: string | null;
  days?: number | null;
  budget_min?: number | null;
  budget_max?: number | null;
  budget_range?: string | null;
  summary?: string | null;
  transport_modes?: string[];
  lodging_suggestions?: string[];
  travel_style_tags?: string[];
  scenic_spots?: string[];
  food_spots?: string[];
  route_nodes?: string[];
  ticket_hints?: string[];
  budget_tips?: string[];
  risk_notes?: string[];
  places?: Array<{
    name: string;
    type?: string | null;
  }>;
}

export interface GuideImportRecordItem {
  id: number;
  url: string;
  status: string;
  mode: string;
  title?: string | null;
  source_type?: string | null;
  guide_id?: number | null;
  source_id?: number | null;
  reason?: string | null;
  message?: string | null;
  quality?: GuideLinkImportResult["quality"];
  diagnostics?: GuideLinkImportResult["diagnostics"];
  content?: string | null;
  structured?: GuideStructuredDraft | null;
  category?: string | null;
  resolved_url?: string | null;
  author?: string | null;
  created_at?: string | null;
}

export interface GuideImportAudit {
  record_id: number;
  status: string;
  mode: string;
  reason?: string | null;
  created_at?: string | null;
  quality?: GuideLinkImportResult["quality"];
  diagnostics?: GuideLinkImportResult["diagnostics"];
  image_urls: string[];
  source_preview_lines: string[];
  imported_preview_lines: string[];
  diff_blocks: Array<{
    type: "shared" | "source_only" | "import_only" | string;
    source?: string | null;
    imported?: string | null;
  }>;
  confidence: {
    overall: number;
    extraction: number;
    structure: number;
    source_integrity: number;
  };
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
