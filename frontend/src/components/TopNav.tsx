import {
  BookOpen,
  Database,
  GaugeCircle,
  History,
  LogOut,
  Map,
  MessageSquarePlus,
  Search,
  ShieldCheck,
  TrainFront,
  Umbrella,
  UserRound,
} from "lucide-react";

import type { LocalUser, ToolStatus } from "../lib/types";

interface TopNavProps {
  status: ToolStatus | null;
  currentUser: LocalUser | null;
  guestMode: boolean;
  onAddGuide: () => void;
  onNewConversation: () => void;
  onHistoryOpen: () => void;
  onUserOpen: () => void;
  onLogout: () => void;
}

function statusText(value?: string) {
  if (!value || value === "offline") return "离线";
  if (value === "configured") return "在线";
  if (value === "demo") return "演示";
  if (value === "sqlite_keyword_ready") return "就绪";
  return value;
}

function statusTone(value?: string) {
  if (!value || value === "offline") return "offline";
  if (value === "demo" || value === "sqlite_keyword_ready") return "demo";
  return "ready";
}

export function TopNav({
  status,
  currentUser,
  guestMode,
  onAddGuide,
  onNewConversation,
  onHistoryOpen,
  onUserOpen,
  onLogout,
}: TopNavProps) {
  const items = [
    { label: "模型", value: status?.llm, icon: GaugeCircle },
    { label: "12306", value: status?.mcp_12306, icon: TrainFront },
    { label: "天气", value: status?.amap, icon: Umbrella },
    { label: "地图", value: status?.amap, icon: Map },
    { label: "联网", value: status?.web_search, icon: Search },
    { label: "攻略库", value: status?.vector_store, icon: Database },
  ];
  const readyCount = items.filter((item) => statusTone(item.value) === "ready").length;
  const userName = currentUser?.display_name || currentUser?.username || "游客";

  return (
    <header className="top-nav top-nav-refined">
      <div className="top-nav-brand">
        <div className="brand-mark">TS</div>
        <div className="top-nav-brand-copy">
          <strong>TripSage Agent</strong>
          <span>中国旅行决策平台</span>
        </div>
      </div>

      <div className="top-nav-status-strip" aria-label="系统状态">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className={`top-nav-status-chip ${statusTone(item.value)}`}>
              <Icon size={14} />
              <span>{item.label}</span>
              <strong>{statusText(item.value)}</strong>
            </div>
          );
        })}
      </div>

      <div className="top-nav-actions">
        <div className="top-nav-health">
          <ShieldCheck size={14} />
          <span>{readyCount}/{items.length} 在线</span>
        </div>

        <button type="button" className="top-nav-user-pill" onClick={onUserOpen} title="用户中心">
          <UserRound size={15} />
          <span>{userName}</span>
          {guestMode ? <em>游客</em> : null}
        </button>

        <button type="button" className="top-nav-icon-action" onClick={onNewConversation} title="新对话">
          <MessageSquarePlus size={16} />
        </button>

        <button
          type="button"
          className="top-nav-icon-action"
          onClick={onHistoryOpen}
          title={guestMode ? "登录后可查看历史" : "历史规划"}
        >
          <History size={16} />
        </button>

        <button type="button" className="top-nav-text-action" onClick={onAddGuide}>
          <BookOpen size={16} />
          <span>添加攻略</span>
        </button>

        {!guestMode ? (
          <button type="button" className="top-nav-icon-action danger" onClick={onLogout} title="退出登录">
            <LogOut size={16} />
          </button>
        ) : null}
      </div>
    </header>
  );
}
