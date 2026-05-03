import type { LocalUser, PreferenceProfile } from "./types";

export type PlanningPromptTone = "jade" | "rail" | "rust" | "sun";

export interface PlanningPromptCard {
  id: string;
  title: string;
  summary: string;
  prompt: string;
  tone: PlanningPromptTone;
}

export function buildPlanningPromptCards(
  profile: PreferenceProfile | null,
  user: LocalUser | null,
): PlanningPromptCard[] {
  // 把长期画像转换成可以直接点击使用的规划起手动作。
  const baseProfile = resolveLongTermProfile(profile) || profile;
  const budget = baseProfile?.budget_range
    || (baseProfile?.budget_profile?.median ? `约 ${baseProfile.budget_profile.median} 元` : "预算平衡");
  const transport = baseProfile?.transport_modes[0] || "高铁";
  const pace = baseProfile?.pace_tags[0] || "轻松";
  const interest = baseProfile?.interest_tags.slice(0, 2).join("、") || "城市漫游、美食";
  const city = baseProfile?.preferred_cities[0] || user?.home_city || "一个国内城市";
  const negativeClause = baseProfile?.negative_preferences.length
    ? `并尽量避开 ${baseProfile.negative_preferences.slice(0, 2).join("、")}`
    : "并尽量减少折返与无效通勤";

  if (!profile) {
    return [
      {
        id: "starter-weekend",
        title: "周末两天一夜",
        summary: "先给我一版高可执行的国内短途模板",
        prompt: "请给我设计一版适合中国城市的周末两天一夜旅行模板，优先高铁可达、节奏轻松、预算平衡，并给出交通建议、雨天备选、预算提示和风险提醒。",
        tone: "jade",
      },
      {
        id: "starter-budget",
        title: "预算反推目的地",
        summary: "先按预算筛选目的地，再展开方案",
        prompt: "请先根据预算反推适合的中国旅行目的地，并分别说明高铁便利性、住宿成本、适合旅行时长，以及每个目的地的一版简要行程骨架。",
        tone: "rail",
      },
      {
        id: "starter-rail",
        title: "铁路优先规划",
        summary: "先看铁路便利性，再决定去哪里",
        prompt: "请从铁路便利性出发，推荐几个适合中国境内短途旅行的目的地，并给出高铁优先的一版首选方案和一个备选方案。",
        tone: "rust",
      },
      {
        id: "starter-light",
        title: "轻松不赶首版",
        summary: "降低强度，先做一版舒服的行程",
        prompt: "请先给我一版轻松不赶、交通衔接顺、适合普通周末节奏的国内旅行方案，并明确标出高强度风险点和低强度替代路线。",
        tone: "sun",
      },
    ];
  }

  return [
    {
      id: "profile-direct",
      title: "延续长期偏好",
      summary: `围绕 ${transport}、${pace}、${budget} 直接生成首版`,
      prompt: `请直接基于我的长期旅行偏好生成一版更贴合我的中国旅行首版方案：交通优先 ${transport}，节奏偏向 ${pace}，兴趣关注 ${interest}，预算控制在 ${budget}，${negativeClause}。如果我还没有给出目的地，请先推荐 3 个更适合我的国内目的地并说明理由。`,
      tone: "jade",
    },
    {
      id: "profile-weekend",
      title: "周末快反模板",
      summary: "做一版更像我风格的短途模板",
      prompt: `请结合我的偏好，为我设计一个更适合我的中国城市周末两天一夜模板方案，重点保留 ${interest} 体验，交通优先 ${transport}，整体节奏保持 ${pace}，${negativeClause}。`,
      tone: "rail",
    },
    {
      id: "profile-budget",
      title: "预算先行",
      summary: `从 ${budget} 出发筛选更合适的目的地`,
      prompt: `请先围绕 ${budget} 的旅行预算，推荐 3 个适合我的中国目的地，并分别给出高铁可达性、预算分配、雨天备选和行程强度判断。`,
      tone: "rust",
    },
    {
      id: "profile-city",
      title: "沿着熟悉偏好扩展",
      summary: `从 ${city} 这一类偏好城市继续外扩`,
      prompt: `我通常会喜欢像 ${city} 这种类型的目的地。请你据此推荐几个同样适合我的中国城市，并给出一版交通顺、强度稳、体验聚焦 ${interest} 的旅行方案。`,
      tone: "sun",
    },
  ];
}

export function buildPlanningHighlights(profile: PreferenceProfile | null, limit = 8): string[] {
  // 提取最有辨识度的偏好标签，供规划页和输入区复用。
  if (!profile) return [];
  const baseProfile = resolveLongTermProfile(profile) || profile;
  const merged = [
    ...baseProfile.preferred_cities,
    ...baseProfile.transport_modes,
    ...baseProfile.pace_tags,
    ...baseProfile.interest_tags,
    ...baseProfile.explicit_preferences,
  ];
  return Array.from(new Set(merged.filter(Boolean))).slice(0, limit);
}

export function buildPlanningDigest(profile: PreferenceProfile | null) {
  if (!profile) {
    return "还没有长期画像，先从一版明确的行程需求开始。";
  }
  return profile.recommendation_hint || "画像正在持续学习中。";
}

export function buildWelcomeMessageContent(
  user: LocalUser | null,
  recommendationHint: string | null,
  profile: PreferenceProfile | null,
) {
  // 新对话的欢迎语直接接入画像，减少用户重复表达成本。
  if (!user) {
    return "当前为游客会话，历史、偏好画像与分享页不会保存。";
  }

  const name = user.display_name || user.username || "当前用户";
  const highlights = buildPlanningHighlights(profile, 4);
  const longTerm = resolveLongTermProfile(profile) || profile;
  const session = profile?.session_profile || null;
  const negatives = longTerm?.negative_preferences.slice(0, 2) || [];

  if (profile && (highlights.length || negatives.length || profile.budget_range)) {
    const lines = [
      `${name} 的新对话已打开。我会先参考你的长期偏好继续规划。`,
      `- 画像摘要：${profile.recommendation_hint || buildPlanningDigest(profile)}`,
    ];

    if (highlights.length) {
      lines.push(`- 当前优先线索：${highlights.join("、")}`);
    }
    if (longTerm?.budget_range || profile.budget_range) {
      lines.push(`- 常用预算区间：${longTerm?.budget_range || profile.budget_range}`);
    }
    if (negatives.length) {
      lines.push(`- 需要优先避让：${negatives.join("、")}`);
    }
    if (session?.recent_evidence?.length) {
      lines.push(`- 本次偏好：${session.recommendation_hint}`);
    }

    lines.push("- 你现在可以直接说新的目的地、日期、预算，或使用下方个性化起手建议。");
    return lines.join("\n");
  }

  if (recommendationHint) {
    return `${name} 的新对话已打开。我会参考你的偏好：${recommendationHint}`;
  }

  return `${name} 的新对话已打开。告诉我出发地、目的地、时间、预算或旅行偏好，即可开始规划。`;
}

export function resolveProfileStrengthMeta(profile: PreferenceProfile | null) {
  const key = profile?.profile_strength;
  if (key === "strong") {
    return { label: "稳定画像", description: "系统已经掌握了较稳定的旅行偏好。", key };
  }
  if (key === "growing") {
    return { label: "持续收敛", description: "画像正在快速成形，建议已经开始带有明显个性。", key };
  }
  return { label: "初步学习", description: "系统刚开始学习你的真实偏好。", key: "new" };
}

function resolveLongTermProfile(profile: PreferenceProfile | null) {
  return profile?.long_term_profile || null;
}
