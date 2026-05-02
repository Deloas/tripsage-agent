import {
  BrainCircuit,
  Clock3,
  LogIn,
  Sparkles,
  TrainFront,
  Wallet,
} from "lucide-react";

import type { LocalUser, PreferenceProfile } from "../lib/types";
import type { PlanningPromptCard } from "../lib/personalization";
import {
  buildPlanningHighlights,
  resolveProfileStrengthMeta,
} from "../lib/personalization";

interface PlanningPreferenceDeckProps {
  guestMode: boolean;
  currentUser: LocalUser | null;
  profile: PreferenceProfile | null;
  prompts: PlanningPromptCard[];
  onUsePrompt: (prompt: string) => void;
  onOpenUserCenter: () => void;
}

export function PlanningPreferenceDeck({
  guestMode,
  currentUser,
  profile,
  prompts,
  onUsePrompt,
  onOpenUserCenter,
}: PlanningPreferenceDeckProps) {
  // 规划页的个性化启动区：先解释系统“懂你什么”，再给可直接触发的起手动作。
  const highlights = buildPlanningHighlights(profile, 8);
  const strength = resolveProfileStrengthMeta(profile);
  const userName = currentUser?.display_name || currentUser?.username || "当前用户";

  return (
    <section className="page-band planning-persona-band">
      <div className="band-head planning-persona-head">
        <div className="section-kicker">
          <BrainCircuit size={15} />
          画像驱动规划
        </div>
        <span>长期偏好可直接接入本轮规划。</span>
      </div>

      <div className="planning-persona-grid">
        <article className="planning-profile-brief-card">
          <div className="planning-profile-brief-top">
            <div>
              <strong>{guestMode ? "游客会话不沉淀长期画像" : `${userName} 的规划偏好已就位`}</strong>
              <p>
                {guestMode
                  ? "登录后会从真实对话、铁路选择和行程编辑中持续学习偏好。"
                  : profile?.recommendation_hint || "系统会继续从真实规划行为中学习更稳定的偏好。"}
              </p>
            </div>
            <span className={`planning-profile-strength ${strength.key}`}>{strength.label}</span>
          </div>

          <div className="planning-profile-metric-grid">
            <div>
              <span>常用预算</span>
              <strong>{profile?.budget_range || "待学习"}</strong>
            </div>
            <div>
              <span>交通偏好</span>
              <strong>{profile?.transport_modes[0] || "待学习"}</strong>
            </div>
            <div>
              <span>旅行节奏</span>
              <strong>{profile?.pace_tags[0] || "待学习"}</strong>
            </div>
            <div>
              <span>最近证据</span>
              <strong>{profile?.recent_evidence.length || 0} 条</strong>
            </div>
          </div>

          {highlights.length ? (
            <div className="planning-profile-chip-row">
              {highlights.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          ) : null}

          {profile?.negative_preferences.length ? (
            <div className="planning-profile-avoid-row">
              {profile.negative_preferences.slice(0, 3).map((item) => (
                <em key={item}>避免 {item}</em>
              ))}
            </div>
          ) : null}

          {guestMode ? (
            <button type="button" className="secondary-action" onClick={onOpenUserCenter}>
              <LogIn size={15} />
              登录后保存画像
            </button>
          ) : null}
        </article>

        <div className="planning-launcher-grid">
          {prompts.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`planning-launcher-card tone-${item.tone}`}
              onClick={() => onUsePrompt(item.prompt)}
            >
              <div className="planning-launcher-card-head">
                <strong>{item.title}</strong>
                <span>{item.tone === "jade" ? <Sparkles size={14} /> : item.tone === "rail" ? <TrainFront size={14} /> : item.tone === "rust" ? <Wallet size={14} /> : <Clock3 size={14} />}</span>
              </div>
              <p>{item.summary}</p>
              <em>一键带入</em>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
