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
  if (value === "configured") return "已连接";
  if (value === "demo") return "演示";
  if (value === "sqlite_keyword_ready") return "就绪";
  return value;
}

function statusLevel(value?: string) {
  // 统一状态胶囊颜色映射，避免组件内部散落重复判断。
  if (!value || value === "offline") return "is-offline";
  if (value === "demo" || value === "sqlite_keyword_ready") return "is-demo";
  return "is-ready";
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
    { label: "DeepSeek", value: status?.llm, icon: GaugeCircle },
    { label: "12306", value: status?.mcp_12306, icon: TrainFront },
    { label: "天气", value: status?.amap, icon: Umbrella },
    { label: "地图", value: status?.amap, icon: Map },
    { label: "联网", value: status?.web_search, icon: Search },
    { label: "知识库", value: status?.vector_store, icon: Database },
  ];
  const readyCount = items.filter((item) => statusLevel(item.value) === "is-ready").length;

  return (
    <header className="top-nav">
      <div className="brand-block">
        <div className="brand-mark">TS</div>
        <div>
          <div className="brand-title">TripSage Agent</div>
          <div className="brand-subtitle">行迹智策 · 中国旅行决策工作台</div>
        </div>
      </div>

      <div className="status-rail" aria-label="工具状态">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <div className={`status-pill ${statusLevel(item.value)}`} key={item.label}>
              <Icon size={15} />
              <span>{item.label}</span>
              <strong>{statusText(item.value)}</strong>
            </div>
          );
        })}
      </div>

      <div className="nav-command-zone">
        <div className="nav-health">
          <ShieldCheck size={15} />
          <span>{readyCount}/{items.length} 在线</span>
        </div>
        {guestMode ? (
          <div className="guest-chip" title="游客模式不会保存历史和偏好画像">
            <UserRound size={15} />
            <span>游客模式</span>
          </div>
        ) : null}
        <button className="secondary-action" onClick={onUserOpen} title="打开账号中心">
          <UserRound size={16} />
          {currentUser?.display_name || currentUser?.username || "游客"}
        </button>
        {!guestMode ? (
          <button className="secondary-action" onClick={onLogout} title="退出登录">
            <LogOut size={16} />
            退出
          </button>
        ) : null}
        <button className="secondary-action" onClick={onNewConversation} title="打开新对话">
          <MessageSquarePlus size={16} />
          新对话
        </button>
        <button className="secondary-action" onClick={onHistoryOpen} title="历史规划中心">
          <History size={16} />
          {guestMode ? "登录保存" : "历史"}
        </button>
        <button className="primary-action" onClick={onAddGuide} title="添加或采集攻略">
          <BookOpen size={17} />
          添加攻略
        </button>
      </div>
    </header>
  );
}
