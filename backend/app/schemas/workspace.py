from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """本地用户创建请求。"""

    display_name: str = Field(min_length=1, max_length=80)
    username: str | None = Field(default=None, max_length=80)
    password: str | None = Field(default=None, min_length=6, max_length=80)
    home_city: str | None = Field(default=None, max_length=50)
    travel_style: str | None = Field(default=None, max_length=200)


class UserLoginRequest(BaseModel):
    """本地用户登录请求。"""

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(default="", max_length=80)


class AuthRefreshRequest(BaseModel):
    """刷新访问令牌请求。"""

    refresh_token: str = Field(min_length=20, max_length=400)


class AuthLogoutRequest(BaseModel):
    """退出当前登录会话请求。"""

    refresh_token: str = Field(min_length=20, max_length=400)


class UserProfileUpdateRequest(BaseModel):
    """用户资料与密码更新请求。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    home_city: str | None = Field(default=None, max_length=50)
    travel_style: str | None = Field(default=None, max_length=200)
    current_password: str | None = Field(default=None, max_length=80)
    new_password: str | None = Field(default=None, min_length=6, max_length=80)


class UserView(BaseModel):
    """前端用户视图。"""

    id: int
    username: str | None = None
    display_name: str | None = None
    home_city: str | None = None
    travel_style: str | None = None
    created_at: str
    updated_at: str | None = None


class UserSessionView(BaseModel):
    """登录会话视图。"""

    id: str
    client_name: str | None = None
    user_agent: str | None = None
    created_at: str
    last_used_at: str | None = None
    expires_at: str
    revoked_at: str | None = None
    is_current: bool = False
    is_active: bool = True


class UserAuthView(BaseModel):
    """登录或注册成功后的鉴权结果。"""

    user: UserView
    access_token: str
    refresh_token: str
    access_expires_in_seconds: int
    session: UserSessionView


class UserAuthStateView(BaseModel):
    """当前登录态视图。"""

    user: UserView
    session: UserSessionView


class MessageView(BaseModel):
    """历史会话消息视图。"""

    role: str
    content: str
    created_at: str


class ConversationSummary(BaseModel):
    """历史规划中心中的会话摘要。"""

    id: str
    title: str | None
    status: str
    message_count: int
    version_count: int
    updated_at: str
    latest_message: str | None = None
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    destination_city: str | None = None
    budget: int | None = None
    start_date: str | None = None


class ConversationDetail(BaseModel):
    """会话详情，用于恢复历史聊天。"""

    id: str
    title: str | None
    status: str
    messages: list[MessageView] = Field(default_factory=list)
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    destination_city: str | None = None
    budget: int | None = None
    start_date: str | None = None


class ConversationUpdateRequest(BaseModel):
    """历史会话元数据更新请求。"""

    title: str | None = Field(default=None, max_length=160)
    is_favorite: bool | None = None
    tags: list[str] | None = None
    destination_city: str | None = Field(default=None, max_length=60)
    budget: int | None = Field(default=None, ge=0, le=999999)
    start_date: str | None = Field(default=None, max_length=40)


class GuestSessionMessageInput(BaseModel):
    """游客临时会话中的消息片段。"""

    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class GuestSessionPlanVersionInput(BaseModel):
    """游客临时会话中的方案版本。"""

    id: str = Field(min_length=4, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=200)
    response: dict = Field(default_factory=dict)
    created_at: str | None = None


class GuestSessionImportRequest(BaseModel):
    """把游客会话导入某一个本地账号。"""

    user_id: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=160)
    messages: list[GuestSessionMessageInput] = Field(default_factory=list)
    plan_versions: list[GuestSessionPlanVersionInput] = Field(default_factory=list)
    active_version_id: str | None = Field(default=None, max_length=80)
    latest_response: dict | None = None
    destination_city: str | None = Field(default=None, max_length=60)
    budget: int | None = Field(default=None, ge=0, le=999999)
    start_date: str | None = Field(default=None, max_length=40)
    tags: list[str] = Field(default_factory=list)


class GuestSessionImportView(BaseModel):
    """游客会话导入结果。"""

    conversation_id: str
    title: str | None = None
    active_version_id: str | None = None
    imported_message_count: int
    imported_plan_version_count: int


class BudgetProfileView(BaseModel):
    """用户预算画像视图。"""

    median: int | None = None
    lower_bound: int | None = None
    upper_bound: int | None = None
    sensitivity: str | None = None


class PreferenceEvidenceView(BaseModel):
    """偏好证据视图。"""

    dimension: str
    value: str
    polarity: str
    source_type: str
    confidence: float
    weight: float
    created_at: str


class PreferenceProfileView(BaseModel):
    """用户旅行偏好画像。"""

    preferred_cities: list[str] = Field(default_factory=list)
    budget_range: str | None = None
    transport_modes: list[str] = Field(default_factory=list)
    pace_tags: list[str] = Field(default_factory=list)
    interest_tags: list[str] = Field(default_factory=list)
    negative_preferences: list[str] = Field(default_factory=list)
    explicit_preferences: list[str] = Field(default_factory=list)
    inferred_preferences: list[str] = Field(default_factory=list)
    behavior_signals: list[str] = Field(default_factory=list)
    profile_strength: str = "new"
    budget_profile: BudgetProfileView | None = None
    recent_evidence: list[PreferenceEvidenceView] = Field(default_factory=list)
    recommendation_hint: str
    updated_at: str | None = None
