import type { ReactNode } from "react";

interface WorkspaceHeroMetric {
  label: string;
  value: string;
}

interface WorkspaceHeroProps {
  tone: "overview" | "railway" | "memory";
  icon: ReactNode;
  kicker: string;
  title: string;
  description: string;
  badges?: string[];
  actions?: ReactNode;
  signals?: ReactNode;
  visualEyebrow: string;
  visualTitle: string;
  visualDetail: string;
  visualMetrics: WorkspaceHeroMetric[];
}

export function WorkspaceHero({
  tone,
  icon,
  kicker,
  title,
  description,
  badges = [],
  actions,
  signals,
  visualEyebrow,
  visualTitle,
  visualDetail,
  visualMetrics,
}: WorkspaceHeroProps) {
  // 统一三个核心工作页的首屏结构，确保信息层级与交互入口保持一致。
  return (
    <section className={`page-band workspace-hero-shell tone-${tone}`}>
      <div className="workspace-hero-main">
        <div className="section-kicker workspace-hero-kicker">
          {icon}
          {kicker}
        </div>
        <h2>{title}</h2>
        <p>{description}</p>

        {badges.length ? (
          <div className="workspace-hero-chipline" aria-label="首屏要点">
            {badges.map((badge) => (
              <span key={badge}>{badge}</span>
            ))}
          </div>
        ) : null}

        {actions ? <div className="workspace-hero-actions">{actions}</div> : null}
        {signals ? <div className="workspace-hero-signal-shell">{signals}</div> : null}
      </div>

      <aside className={`workspace-hero-visual visual-${tone}`} aria-label={`${kicker}视觉概览`}>
        <div className="workspace-hero-visual-scrim" />
        <div className="workspace-hero-visual-copy">
          <span>{visualEyebrow}</span>
          <strong>{visualTitle}</strong>
          <em>{visualDetail}</em>
        </div>
        <div className="workspace-hero-visual-grid">
          {visualMetrics.map((metric) => (
            <article key={`${metric.label}-${metric.value}`} className="workspace-hero-visual-card">
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </article>
          ))}
        </div>
      </aside>
    </section>
  );
}
