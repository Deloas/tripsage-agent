import { FormEvent, useEffect, useState } from "react";
import {
  Fingerprint,
  KeyRound,
  Layers3,
  LogIn,
  LogOut,
  MapPinned,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";

import type {
  AuthSession,
  GuestCarryoverSummary,
  LocalUser,
  PreferenceProfile,
  UserProfileUpdatePayload,
} from "../lib/types";
import { PreferenceProfileSnapshot } from "./PreferenceProfileWorkbench";

interface UserCenterProps {
  open: boolean;
  currentUser: LocalUser | null;
  currentSession: AuthSession | null;
  sessions: AuthSession[];
  sessionsLoading: boolean;
  guestCarryover: GuestCarryoverSummary | null;
  preferenceProfile: PreferenceProfile | null;
  onClose: () => void;
  onEnterGuest: () => void;
  onLogin: (
    payload: { username: string; password: string },
    options?: { preserveGuestSession?: boolean },
  ) => Promise<void>;
  onRegister: (
    payload: {
      display_name: string;
      username?: string;
      password?: string;
      home_city?: string;
      travel_style?: string;
    },
    options?: { preserveGuestSession?: boolean },
  ) => Promise<void>;
  onLogout: () => Promise<void>;
  onUpdateProfile: (payload: UserProfileUpdatePayload) => Promise<void>;
  onRefreshSessions: () => Promise<void>;
  onRevokeSession: (sessionId: string) => Promise<void>;
}

type Notice = { type: "error" | "success"; text: string } | null;

function resolveAuthNotice(error: unknown, fallback: string) {
  if (error && typeof error === "object") {
    const maybeError = error as { message?: unknown; data?: { error?: unknown } };
    if (typeof maybeError.data?.error === "string" && maybeError.data.error.trim()) {
      return maybeError.data.error.trim();
    }
    if (typeof maybeError.message === "string" && maybeError.message.trim()) {
      return maybeError.message.trim();
    }
  }
  return fallback;
}

export function UserCenter({
  open,
  currentUser,
  currentSession,
  sessions,
  sessionsLoading,
  guestCarryover,
  preferenceProfile,
  onClose,
  onEnterGuest,
  onLogin,
  onRegister,
  onLogout,
  onUpdateProfile,
  onRefreshSessions,
  onRevokeSession,
}: UserCenterProps) {
  const [view, setView] = useState<"login" | "register" | "profile" | "security">("login");
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [preserveGuestSession, setPreserveGuestSession] = useState(false);

  const [loginName, setLoginName] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [homeCity, setHomeCity] = useState("");
  const [travelStyle, setTravelStyle] = useState("");

  const [profileDisplayName, setProfileDisplayName] = useState("");
  const [profileHomeCity, setProfileHomeCity] = useState("");
  const [profileTravelStyle, setProfileTravelStyle] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const canLogin = loginName.trim().length > 0;
  const canRegister = displayName.trim().length > 0 && (!password || password.length >= 6);
  const canSaveProfile = profileDisplayName.trim().length > 0
    && (!newPassword || (newPassword.length >= 6 && newPassword === confirmPassword));

  useEffect(() => {
    if (!open) return;
    setNotice(null);
    setPreserveGuestSession(Boolean(guestCarryover && !currentUser));
    if (currentUser) {
      setView("profile");
      setProfileDisplayName(currentUser.display_name || "");
      setProfileHomeCity(currentUser.home_city || "");
      setProfileTravelStyle(currentUser.travel_style || "");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } else {
      setView("login");
    }
  }, [currentUser, guestCarryover, open]);

  if (!open) return null;

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    if (!canLogin) return;
    setBusy(true);
    setNotice(null);
    try {
      await onLogin(
        { username: loginName.trim(), password: loginPassword },
        { preserveGuestSession },
      );
      setLoginPassword("");
    } catch (error) {
      setNotice({
        type: "error",
        text: resolveAuthNotice(error, "登录失败，请检查账号名、显示名称或密码后重试。"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleRegister(event: FormEvent) {
    event.preventDefault();
    if (!canRegister) return;
    setBusy(true);
    setNotice(null);
    try {
      await onRegister(
        {
          display_name: displayName.trim(),
          username: username.trim() || undefined,
          password: password || undefined,
          home_city: homeCity.trim() || undefined,
          travel_style: travelStyle.trim() || undefined,
        },
        { preserveGuestSession },
      );
      setDisplayName("");
      setUsername("");
      setPassword("");
      setHomeCity("");
      setTravelStyle("");
    } catch {
      setNotice({ type: "error", text: "注册失败，可能是本地账号已存在或资料不完整。" });
    } finally {
      setBusy(false);
    }
  }

  async function handleProfileSave(event: FormEvent) {
    event.preventDefault();
    if (!canSaveProfile) return;
    setBusy(true);
    setNotice(null);
    try {
      await onUpdateProfile({
        display_name: profileDisplayName.trim(),
        home_city: profileHomeCity.trim() || undefined,
        travel_style: profileTravelStyle.trim() || undefined,
        current_password: currentPassword || undefined,
        new_password: newPassword || undefined,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice({ type: "success", text: "账号资料已更新。" });
    } catch {
      setNotice({ type: "error", text: "保存失败，请检查当前密码或字段内容。" });
    } finally {
      setBusy(false);
    }
  }

  async function handleLogoutClick() {
    setBusy(true);
    try {
      await onLogout();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="user-center user-center-pro" role="dialog" aria-modal="true" aria-label="账号中心">
        <div className="modal-header">
          <div>
            <div className="section-kicker">
              <ShieldCheck size={16} />
              账号与安全中心
            </div>
            <h2>{currentUser ? "管理资料、密码和登录设备" : "登录后保存历史、偏好画像与可编辑行程"}</h2>
            <p className="user-current">
              {currentUser
                ? `当前账号：${currentUser.display_name || currentUser.username || "未命名用户"}`
                : "当前为游客会话，登录后可写入历史中心继续优化。"}
            </p>
          </div>
          <div className="user-header-actions">
            {!currentUser ? (
              <button className="secondary-action" type="button" onClick={onEnterGuest}>
                <UserRound size={15} />
                继续以游客使用
              </button>
            ) : (
              <button className="secondary-action" type="button" onClick={() => void handleLogoutClick()} disabled={busy}>
                <LogOut size={15} />
                退出登录
              </button>
            )}
            <button className="icon-button" onClick={onClose} aria-label="关闭">
              <X size={18} />
            </button>
          </div>
        </div>

        {!currentUser && guestCarryover ? (
          <section className="guest-session-card">
            <div className="section-kicker">
              <Layers3 size={15} />
              游客方案承接
            </div>
            <strong>登录后可将当前游客会话写入历史中心，继续优化、分享，并自动沉淀用户偏好。</strong>
            <div className="guest-session-stats">
              <span>
                <MapPinned size={14} />
                {guestCarryover.destination || guestCarryover.title}
              </span>
              <span>{guestCarryover.message_count} 条消息</span>
              <span>{guestCarryover.version_count} 个版本</span>
            </div>
            <div className="guest-session-switch" role="group" aria-label="游客方案承接模式">
              <button
                className={preserveGuestSession ? "active" : ""}
                onClick={() => setPreserveGuestSession(true)}
                type="button"
              >
                保存当前方案
              </button>
              <button
                className={!preserveGuestSession ? "active" : ""}
                onClick={() => setPreserveGuestSession(false)}
                type="button"
              >
                从新对话开始
              </button>
            </div>
          </section>
        ) : null}

        {!currentUser ? (
          <>
            <div className="user-mode-switch" role="tablist" aria-label="账号入口">
              <button className={view === "login" ? "active" : ""} onClick={() => setView("login")} type="button">
                <LogIn size={15} />
                登录
              </button>
              <button className={view === "register" ? "active" : ""} onClick={() => setView("register")} type="button">
                <Plus size={15} />
                注册
              </button>
            </div>

            {view === "login" ? (
              <form className="user-form compact" onSubmit={handleLogin}>
                <label>
                  <span>账号名或显示名称</span>
                  <input
                    value={loginName}
                    onChange={(event) => setLoginName(event.target.value)}
                    placeholder="例如：wu、葡萄不过季、default"
                  />
                </label>
                <label>
                  <span>密码</span>
                  <input
                    type="password"
                    value={loginPassword}
                    onChange={(event) => setLoginPassword(event.target.value)}
                    placeholder="演示账号可留空"
                  />
                </label>
                <p className="user-form-note">
                  支持使用账号名或显示名称登录；如果存在同名显示名称，请使用账号名登录。
                </p>
                <button className="primary-action wide" disabled={!canLogin || busy}>登录并进入工作台</button>
              </form>
            ) : (
              <form className="user-form" onSubmit={handleRegister}>
                <label>
                  <span>显示名称</span>
                  <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：小林" />
                </label>
                <label>
                  <span>账号名（可选）</span>
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="例如：xiaolin；留空会自动生成"
                  />
                </label>
                <label>
                  <span>密码</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="至少 6 位"
                  />
                </label>
                <label>
                  <span>常住城市</span>
                  <input value={homeCity} onChange={(event) => setHomeCity(event.target.value)} placeholder="例如：上海" />
                </label>
                <label>
                  <span>旅行风格</span>
                  <input value={travelStyle} onChange={(event) => setTravelStyle(event.target.value)} placeholder="例如：高铁友好、松弛、注重美食" />
                </label>
                <button className="primary-action wide" disabled={!canRegister || busy}>注册并进入工作台</button>
              </form>
            )}
          </>
        ) : (
          <>
            <section className="account-hero-panel">
              <div className="account-hero-main">
                <span>本地账号</span>
                <strong>{currentUser.display_name || currentUser.username || "未命名用户"}</strong>
                <p>{preferenceProfile?.recommendation_hint || "完成几次规划后，这里会逐步沉淀你的预算、节奏和交通偏好。"}</p>
              </div>
              <div className="account-hero-meta">
                <div>
                  <span>账号名</span>
                  <strong>@{currentUser.username || "local"}</strong>
                </div>
                <div>
                  <span>当前设备</span>
                  <strong>{currentSession?.client_name || "TripSage Web"}</strong>
                </div>
              </div>
            </section>

            <div className="user-mode-switch user-mode-switch-wide" role="tablist" aria-label="账号设置视图">
              <button className={view === "profile" ? "active" : ""} onClick={() => setView("profile")} type="button">
                <Sparkles size={15} />
                资料与偏好
              </button>
              <button className={view === "security" ? "active" : ""} onClick={() => setView("security")} type="button">
                <Fingerprint size={15} />
                安全与会话
              </button>
            </div>

            {view === "profile" ? (
              <form className="user-form user-form-profile" onSubmit={handleProfileSave}>
                <PreferenceProfileSnapshot
                  profile={preferenceProfile}
                  compact
                  showEvidence
                  title="偏好画像摘要"
                  subtitle="这里会同步展示系统当前学到的长期偏好和最近证据。"
                  emptyText="当前还没有足够多的历史规划来沉淀稳定偏好。"
                />

                <div className="account-form-grid">
                  <label>
                    <span>显示名称</span>
                    <input value={profileDisplayName} onChange={(event) => setProfileDisplayName(event.target.value)} />
                  </label>
                  <label>
                    <span>常住城市</span>
                    <input value={profileHomeCity} onChange={(event) => setProfileHomeCity(event.target.value)} />
                  </label>
                </div>
                <label>
                  <span>旅行风格</span>
                  <input value={profileTravelStyle} onChange={(event) => setProfileTravelStyle(event.target.value)} placeholder="例如：高铁优先、预算平衡、摄影向" />
                </label>
                <div className="account-form-grid">
                  <label>
                    <span>当前密码</span>
                    <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} placeholder="仅修改密码时填写" />
                  </label>
                  <label>
                    <span>新密码</span>
                    <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="至少 6 位" />
                  </label>
                </div>
                <label>
                  <span>确认新密码</span>
                  <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="再次输入新密码" />
                </label>
                <button className="primary-action wide" disabled={!canSaveProfile || busy}>保存资料</button>
              </form>
            ) : (
              <section className="security-panel">
                <div className="security-head">
                  <div>
                    <div className="section-kicker">
                      <KeyRound size={15} />
                      活跃会话
                    </div>
                    <strong>查看当前账号在哪些本地会话中保持登录。</strong>
                  </div>
                  <button className="secondary-action" type="button" onClick={() => void onRefreshSessions()} disabled={sessionsLoading}>
                    <RefreshCw size={15} />
                    刷新列表
                  </button>
                </div>

                <div className="session-list">
                  {sessionsLoading ? (
                    <div className="session-empty">正在读取本地登录会话...</div>
                  ) : sessions.length ? (
                    sessions.map((session) => (
                      <article className={`session-card ${session.is_current ? "current" : ""}`} key={session.id}>
                        <div className="session-main">
                          <strong>{session.client_name || "TripSage Web"}</strong>
                          <span>{session.user_agent || "本地浏览器会话"}</span>
                          <em>最近使用：{formatDateTime(session.last_used_at || session.created_at)}</em>
                        </div>
                        <div className="session-side">
                          <span>{session.is_current ? "当前设备" : session.is_active ? "有效" : "已失效"}</span>
                          <small>到期：{formatDateTime(session.expires_at)}</small>
                          {!session.is_current ? (
                            <button className="danger-ghost" type="button" onClick={() => void onRevokeSession(session.id)}>
                              注销此设备
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="session-empty">当前还没有可展示的登录会话。</div>
                  )}
                </div>
              </section>
            )}
          </>
        )}

        {notice ? <p className={`user-notice ${notice.type}`}>{notice.text}</p> : null}
      </section>
    </div>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
