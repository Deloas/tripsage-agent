import type {
  ChatResponse,
  ConversationSummary,
  GuideSourceItem,
  PlanVersion,
  PreferenceProfile,
  ToolStatus,
} from "./types";

type Message = { role: "user" | "assistant"; content: string };
type SearchMode = "local_only" | "web_enhanced" | "auto";

export interface PreviewScenarioState {
  status: ToolStatus;
  messages: Message[];
  latest: ChatResponse;
  guideSources: GuideSourceItem[];
  planVersions: PlanVersion[];
  activeVersionId: string;
  searchMode: SearchMode;
  history: ConversationSummary[];
  profile: PreferenceProfile | null;
}

export function buildStressPreviewState(): PreviewScenarioState {
  const latest = buildResponse("v3", "优化版 2");
  const first = buildVersion("v1", "初版", "智能体首次生成方案", buildResponse("v1", "初版"));
  const second = buildVersion("v2", "优化版 1", "基于用户追加偏好继续优化", buildResponse("v2", "优化版 1"));
  const third = buildVersion("v3", "优化版 2", "基于车次选择与雨天条件二次优化", latest);

  return {
    status: {
      llm: "online",
      amap: "online",
      mcp_12306: "online",
      web_search: "online",
      vector_store: "online",
      demo_mode: false,
    },
    searchMode: "web_enhanced",
    messages: [
      {
        role: "assistant",
        content: "当前为压测预览场景。这里会模拟长对话、20 条车次、多版本方案和结构化决策结果，方便直接检查界面在高密度信息下的表现。",
      },
      {
        role: "user",
        content: "我想五一从杭州去南京两天一夜，预算 1800 元，优先高铁，不想太赶，最好能兼顾美食和夜景。",
      },
      {
        role: "assistant",
        content: [
          "### 初步判断",
          "- 南京适合两天一夜短途，铁路班次密集，城市内通勤稳定。",
          "- 预算 1800 元可以覆盖高铁往返、中档住宿和 2 到 3 个核心景点。",
          "- 如果担心节假日拥挤，建议把夫子庙和热门博物馆放到错峰时段。",
          "",
          "### 首版建议",
          "- DAY 1 以到达、城南步行和夜景为主。",
          "- DAY 2 以博物馆或园林线为主，傍晚返程。",
        ].join("\n"),
      },
      {
        role: "user",
        content: "我更在意不要淋雨，而且返程希望不要太晚。可以顺便看看有没有更稳妥的高铁吗？",
      },
      {
        role: "assistant",
        content: [
          "### 二次优化",
          "- 已把雨天备选切到室内比例更高的线路。",
          "- 返程会优先筛选 18:30 前后、余票更稳的高铁。",
          "- 右侧铁路结果里我会保留 20 条车次供你连续比较。",
        ].join("\n"),
      },
      {
        role: "user",
        content: "如果我最后选 15:12 出发、16:38 到的那班，也请继续帮我优化当天顺序和预算。",
      },
      {
        role: "assistant",
        content: latest.answer,
      },
    ],
    latest,
    guideSources: [
      { id: 1, title: "南京两天一夜城市漫游攻略", source_type: "weibo", crawl_status: "indexed", category: "city", source_url: "https://weibo.com/example-1" },
      { id: 2, title: "南京雨天备选博物馆路线", source_type: "manual", crawl_status: "indexed", category: "museum", source_url: "https://weibo.com/example-2" },
      { id: 3, title: "杭州到南京高铁出行经验帖", source_type: "weibo", crawl_status: "indexed", category: "transport", source_url: "https://weibo.com/example-3" },
      { id: 4, title: "夫子庙与老门东夜景步行线", source_type: "manual", crawl_status: "indexed", category: "walk", source_url: "https://weibo.com/example-4" },
    ],
    planVersions: [first, second, third],
    activeVersionId: third.id,
    history: [
      {
        id: "history-1",
        title: "五一南京两天一夜",
        status: "active",
        message_count: 7,
        version_count: 3,
        updated_at: new Date().toISOString(),
        latest_message: "已根据高铁选择和雨天条件优化返程方案。",
        is_favorite: true,
        tags: ["南京", "高铁", "五一"],
        destination_city: "南京",
        budget: 1800,
        start_date: "五一",
      },
    ],
    profile: {
      preferred_cities: ["南京", "苏州", "扬州"],
      budget_range: "1500-2200",
      transport_modes: ["高铁", "地铁"],
      pace_tags: ["轻松", "不折返"],
      interest_tags: ["美食", "夜景", "城市漫游"],
      negative_preferences: ["避免过度折返", "不想太赶"],
      explicit_preferences: ["高铁", "美食", "夜景"],
      inferred_preferences: ["城市漫游", "短途周末游"],
      behavior_signals: ["多次选择傍晚返程", "优先保留低强度方案"],
      profile_strength: "strong",
      budget_profile: {
        median: 1800,
        lower_bound: 1500,
        upper_bound: 2200,
        sensitivity: "中",
      },
      recent_evidence: [
        {
          dimension: "transport",
          value: "高铁",
          polarity: "positive",
          source_type: "user_message",
          confidence: 0.96,
          weight: 1.2,
          created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
        },
        {
          dimension: "pace",
          value: "轻松",
          polarity: "positive",
          source_type: "edited_plan",
          confidence: 0.88,
          weight: 1.05,
          created_at: new Date(Date.now() - 80 * 60 * 1000).toISOString(),
        },
        {
          dimension: "destination",
          value: "南京",
          polarity: "positive",
          source_type: "decision_module",
          confidence: 0.82,
          weight: 0.96,
          created_at: new Date(Date.now() - 35 * 60 * 1000).toISOString(),
        },
      ],
      recommendation_hint: "优先高铁、控制强度、喜欢美食与夜景。",
      updated_at: new Date().toISOString(),
      long_term_profile: {
        preferred_cities: ["南京", "苏州", "扬州"],
        budget_range: "1500-2200",
        transport_modes: ["高铁", "地铁"],
        pace_tags: ["轻松", "少折返"],
        interest_tags: ["美食", "夜景", "城市漫游"],
        negative_preferences: ["避免过度折返", "不想太赶"],
        explicit_preferences: ["高铁", "美食", "夜景"],
        inferred_preferences: ["城市漫游", "周末短途"],
        behavior_signals: ["多次选择傍晚返程", "优先保留低强度方案"],
        profile_strength: "strong",
        budget_profile: {
          median: 1800,
          lower_bound: 1500,
          upper_bound: 2200,
          sensitivity: "中",
        },
        recent_evidence: [
          {
            dimension: "transport",
            value: "高铁",
            polarity: "positive",
            source_type: "user_message",
            confidence: 0.96,
            weight: 1.2,
            created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
          },
        ],
        recommendation_hint: "长期偏好更偏向高铁、轻松节奏与城市漫游。",
        updated_at: new Date().toISOString(),
      },
      session_profile: {
        preferred_cities: ["南京"],
        budget_range: "1600-1900",
        transport_modes: ["高铁"],
        pace_tags: ["轻松"],
        interest_tags: ["雨天备选"],
        negative_preferences: ["避免返程过晚"],
        explicit_preferences: ["不想淋雨", "返程不要太晚"],
        inferred_preferences: ["更偏向室内备选路线"],
        behavior_signals: ["继续优化当前方案", "查看多个车次版本"],
        profile_strength: "growing",
        budget_profile: {
          median: 1800,
          lower_bound: 1600,
          upper_bound: 1900,
          sensitivity: "中",
        },
        recent_evidence: [
          {
            dimension: "avoidance",
            value: "返程过晚",
            polarity: "negative",
            source_type: "manual_session",
            confidence: 0.94,
            weight: 1.1,
            created_at: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
          },
        ],
        recommendation_hint: "本次更在意雨天切换能力和返程时间。",
        updated_at: new Date().toISOString(),
      },
    },
  };
}

function buildVersion(id: string, name: string, reason: string, response: ChatResponse): PlanVersion {
  return {
    id,
    name,
    reason,
    response,
    createdAt: new Date(Date.now() - (id === "v1" ? 40 : id === "v2" ? 20 : 5) * 60_000).toISOString(),
  };
}

function buildResponse(versionId: string, versionName: string): ChatResponse {
  const trains = Array.from({ length: 20 }, (_, index) => buildTrain(index));
  const selectedTrain = trains[6];

  return {
    conversation_id: `preview-${versionId}`,
    intent: "city_break_planning",
    answer: [
      "### 规划结论",
      `已按 ${versionName} 输出一版更稳妥的南京两天一夜方案，并把返程时段压到傍晚前后。`,
      "",
      "### 交通建议",
      `- 推荐优先考虑 ${selectedTrain.train_no}，出发 ${selectedTrain.start_time}，到达 ${selectedTrain.arrive_time}，兼顾时间和余票稳定性。`,
      "- 若担心节假日波动，可保留一班更早出发的备选车次，避免行程被压缩。",
      "",
      "### 雨天备选",
      "- 玄武湖和城墙段可与博物馆、先锋书店、德基艺术空间灵活互换。",
      "- 夜间核心活动保留在老门东和夫子庙一带，减少跨区通勤。",
      "",
      "### 预算提示",
      "- 往返高铁按二等座估算约 320 到 460 元。",
      "- 住宿建议锁定新街口或夫子庙外圈，控制在 420 到 560 元。",
      "- 两日餐饮和门票仍有较充足余量。",
      "",
      "### 风险提醒",
      "- 五一热门时段进站和出站会拥挤，建议提前 35 分钟到站。",
      "- 热门博物馆需提前预约，若满额直接切换室内备选。",
    ].join("\n"),
    cards: [
      {
        type: "destination",
        title: "南京",
        summary: "适合两天一夜，城市内铁路和地铁衔接稳定。",
        meta: { city: "南京" },
      },
      {
        type: "railway",
        title: "杭州东 → 南京南",
        summary: "共找到 20 条可比较车次，已按可执行性保留高密度候选。",
        meta: { date: "2026-05-02", trains },
      },
      {
        type: "weather",
        title: "天气判断",
        summary: "存在短时阵雨风险，建议室外活动可切换。",
        meta: { condition: "cloudy_with_showers" },
      },
      {
        type: "map",
        title: "地图通勤",
        summary: "住宿放在新街口到夫子庙之间更利于夜景与返程。",
        meta: { corridor: "新街口-夫子庙" },
      },
    ],
    itinerary: [
      {
        day: 1,
        title: "抵达南京，城南漫游与夜景",
        items: [
          { time: "09:20", title: "杭州东出发", detail: "高铁前往南京南，建议提前 35 分钟进站。" },
          { time: "11:05", title: "入住与午餐", detail: "新街口或夫子庙外圈办理寄存，午餐优先鸭血粉丝或盐水鸭。" },
          { time: "14:00", title: "室内核心景点", detail: "雨天切南京博物院，晴天可走城墙或玄武湖一段。" },
          { time: "18:10", title: "老门东夜游", detail: "控制步行强度，夜景、美食和返程动线更顺。" },
        ],
      },
      {
        day: 2,
        title: "博物馆或园林线，傍晚返程",
        items: [
          { time: "09:30", title: "弹性起步", detail: "根据天气决定去总统府周边还是继续室内馆线。" },
          { time: "12:00", title: "午餐与回收购物", detail: "避免跨城通勤，优先围绕地铁 1 号线收口。" },
          { time: "15:12", title: "候选返程车次", detail: "若采用推荐车次，可保留午后轻松行程，不必过早赶站。" },
          { time: "18:30", title: "预留更早返程备选", detail: "如遇天气或客流波动，可切换更早车次。" },
        ],
      },
    ],
    tool_calls: [
      { tool_name: "guide_rag", status: "success", latency_ms: 182, output_summary: "命中 4 条本地攻略切片" },
      { tool_name: "12306_mcp", status: "success", latency_ms: 428, output_summary: "返回 20 条杭州东到南京南车次" },
      { tool_name: "amap_route", status: "success", latency_ms: 209, output_summary: "生成站点到住宿区通勤建议" },
      { tool_name: "weather_api", status: "success", latency_ms: 133, output_summary: "识别短时阵雨风险" },
      { tool_name: "web_search", status: "fallback", latency_ms: 91, output_summary: "补充节假日客流提醒" },
    ],
    sources: [
      { title: "南京两天一夜城市漫游攻略", url: "https://weibo.com/example-1", source_type: "weibo" },
      { title: "南京雨天备选博物馆路线", url: "https://weibo.com/example-2", source_type: "manual" },
      { title: "杭州到南京高铁出行经验帖", url: "https://weibo.com/example-3", source_type: "weibo" },
      { title: "夫子庙与老门东夜景步行线", url: "https://weibo.com/example-4", source_type: "manual" },
      { title: "节假日返程高峰提醒", url: "https://weibo.com/example-5", source_type: "web" },
    ],
    warnings: ["五一返程高峰可能导致南京南进站排队变长，建议至少提前 35 分钟到站。"],
    decision_modules: [
      {
        type: "transport",
        title: "交通建议",
        level: "good",
        summary: "返程建议选择下午中段高铁，兼顾体验与稳妥。",
        points: ["优先 15:12 左右出发的高铁，不压缩白天行程。", "保留更早车次做天气和客流兜底。", "住宿尽量靠近 1 号线或 3 号线。"],
      },
      {
        type: "rainy_day",
        title: "雨天备选",
        level: "info",
        summary: "户外和室内线路都已留好替代关系。",
        points: ["玄武湖可替换成南京博物院。", "老门东夜游保留，白天景点机动处理。", "行李寄存后再决定首日下午线路。"],
      },
      {
        type: "intensity",
        title: "行程强度",
        level: "good",
        summary: "整体步行与换乘强度中等偏低。",
        points: ["两日主线围绕 2 个核心片区。", "避免一天内多次跨区折返。", "返程前留足休整时间。"],
      },
      {
        type: "budget",
        title: "预算提示",
        level: "info",
        summary: "总预算预计控制在 1450 到 1780 元之间。",
        points: ["高铁二等座是最稳妥的性价比选择。", "中档住宿建议控制在 420 到 560 元。", "热门景点预约成功后再锁定付费项目。"],
      },
      {
        type: "risk",
        title: "风险提醒",
        level: "warn",
        summary: "节假日拥挤和天气变化仍是主要不确定项。",
        points: ["热门馆提前预约。", "高铁进站时间提前。", "如遇中到大雨，立即切室内主线。"],
      },
    ],
  };
}

function buildTrain(index: number) {
  const hour = 6 + Math.floor(index / 2);
  const minute = index % 2 === 0 ? 12 : 42;
  const durationHour = 1 + (index % 4 === 0 ? 0 : 1);
  const durationMinute = [26, 38, 45, 52][index % 4];
  const arriveTotal = hour * 60 + minute + durationHour * 60 + durationMinute;
  const arriveHour = Math.floor(arriveTotal / 60);
  const arriveMinute = arriveTotal % 60;
  const type = index % 6 === 0 ? "D" : "G";
  return {
    train_no: `${type}${1200 + index}`,
    from_station: "杭州东",
    to_station: "南京南",
    start_time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`,
    arrive_time: `${String(arriveHour).padStart(2, "0")}:${String(arriveMinute).padStart(2, "0")}`,
    duration: `${durationHour}小时${String(durationMinute).padStart(2, "0")}分`,
    seats: {
      second_class: index % 5 === 0 ? "候补" : `${Math.max(3, 28 - index)}张`,
      first_class: `${Math.max(1, 10 - Math.floor(index / 2))}张`,
      business_class: index % 4 === 0 ? "2张" : "无",
      no_seat: index % 3 === 0 ? `${12 - Math.floor(index / 2)}张` : "无",
    },
  };
}
