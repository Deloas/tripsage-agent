import { CalendarDays, CircleDollarSign, Compass, MapPin, Route, SendHorizonal, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

interface PlannerSidebarProps {
  onPrompt: (prompt: string) => void;
  searchMode: "local_only" | "web_enhanced" | "auto";
  onSearchModeChange: (mode: "local_only" | "web_enhanced" | "auto") => void;
}

const quickPrompts = [
  "上海出发，两天一夜，预算800，想轻松一点，去哪比较好？",
  "南京三天两夜怎么玩？我喜欢历史和美食。",
  "明天杭州到南京有哪些高铁？",
  "这个周末苏州如果下雨，还适合去吗？",
];

const preferenceTags = ["轻松", "美食", "历史", "园林", "高铁友好", "雨天备选"];

export function PlannerSidebar({ onPrompt, searchMode, onSearchModeChange }: PlannerSidebarProps) {
  const [origin, setOrigin] = useState("上海");
  const [destination, setDestination] = useState("苏州");
  const [date, setDate] = useState("周末");
  const [days, setDays] = useState("2");
  const [budget, setBudget] = useState("800");
  const [activePrefs, setActivePrefs] = useState<string[]>(["轻松", "高铁友好"]);

  const composedPrompt = useMemo(() => {
    // 左侧条件直接生成自然语言问题，保证表单输入能进入智能体链路。
    const destinationPart = destination.trim() ? `想去${destination.trim()}，` : "还没定目的地，";
    const dayPart = days.trim() ? `${days.trim()}天，` : "";
    const budgetPart = budget.trim() ? `预算${budget.trim()}元，` : "";
    const prefPart = activePrefs.length ? `偏好${activePrefs.join("、")}，` : "";
    return `${origin.trim() || "上海"}出发，${date.trim() || "近期"}，${destinationPart}${dayPart}${budgetPart}${prefPart}请结合攻略、铁路、天气和地图给我一份可执行方案。`;
  }, [activePrefs, budget, date, days, destination, origin]);

  function togglePreference(tag: string) {
    setActivePrefs((current) =>
      current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag],
    );
  }

  return (
    <aside className="planner-sidebar" aria-label="旅行规划条件">
      <div className="china-visual-card planner-visual">
        <div className="visual-label">中国城市旅行</div>
        <strong>江南街巷 · 高铁周末 · 雨天备选</strong>
        <span className="visual-caption">攻略库 / 12306 / 天气 / 地图</span>
      </div>

      <section className="route-dossier" aria-label="当前路线档案">
        <div>
          <span>出发</span>
          <strong>{origin || "未定"}</strong>
        </div>
        <Route size={18} />
        <div>
          <span>目的地</span>
          <strong>{destination || "待推荐"}</strong>
        </div>
      </section>

      <section className="panel-section">
        <div className="section-kicker">
          <Compass size={16} />
          旅行条件
        </div>
        <div className="field-grid">
          <label>
            <span>出发地</span>
            <div className="input-shell">
              <MapPin size={15} />
              <input value={origin} onChange={(event) => setOrigin(event.target.value)} />
            </div>
          </label>
          <label>
            <span>目的地</span>
            <div className="input-shell">
              <Route size={15} />
              <input value={destination} onChange={(event) => setDestination(event.target.value)} />
            </div>
          </label>
          <div className="compact-fields">
            <label>
              <span>日期</span>
              <div className="input-shell">
                <CalendarDays size={15} />
                <input value={date} onChange={(event) => setDate(event.target.value)} />
              </div>
            </label>
            <label>
              <span>天数</span>
              <div className="input-shell">
                <input value={days} onChange={(event) => setDays(event.target.value)} />
              </div>
            </label>
          </div>
          <label>
            <span>预算</span>
            <div className="input-shell">
              <CircleDollarSign size={15} />
              <input value={budget} onChange={(event) => setBudget(event.target.value)} />
            </div>
          </label>
        </div>
      </section>

      <section className="panel-section">
        <div className="section-kicker">
          <Sparkles size={16} />
          偏好
        </div>
        <div className="tag-cloud">
          {preferenceTags.map((tag) => (
            <button
              className={activePrefs.includes(tag) ? "active" : ""}
              key={tag}
              type="button"
              onClick={() => togglePreference(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      </section>

      <section className="panel-section">
        <div className="section-kicker">信息来源</div>
        <div className="mode-switch" role="group" aria-label="检索模式">
          {[
            { value: "auto", label: "自动" },
            { value: "local_only", label: "攻略库" },
            { value: "web_enhanced", label: "联网增强" },
          ].map((mode) => (
            <button
              className={searchMode === mode.value ? "active" : ""}
              key={mode.value}
              type="button"
              onClick={() => onSearchModeChange(mode.value as "local_only" | "web_enhanced" | "auto")}
            >
              {mode.label}
            </button>
          ))}
        </div>
        <p className="mode-note">
          {searchMode === "local_only"
            ? "只使用本地攻略库，适合答辩和可控回答。"
            : searchMode === "web_enhanced"
              ? "补充公开联网资料，并在回答中区分来源。"
              : "先查攻略库，命中不足再考虑联网增强。"}
        </p>
      </section>

      <section className="panel-section prompt-section">
        <div className="section-kicker">
          <SendHorizonal size={15} />
          智能生成
        </div>
        <div className="prompt-preview">
          <span>将发送给智能体</span>
          <strong>{composedPrompt}</strong>
        </div>
        <button className="primary-action wide" type="button" onClick={() => onPrompt(composedPrompt)}>
          <SendHorizonal size={16} />
          生成规划
        </button>
      </section>

      <section className="panel-section prompt-section">
        <div className="section-kicker">演示问题</div>
        <div className="prompt-list">
          {quickPrompts.map((prompt) => (
            <button key={prompt} type="button" onClick={() => onPrompt(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}
