import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from app.db.models import User, utc_now
from app.schemas.workspace import (
    UserAuthView,
    UserCreateRequest,
    UserLoginRequest,
    UserProfileUpdateRequest,
    UserView,
)
from app.services.auth_service import AuthService


class UserService:
    """本地多用户服务，负责用户资料、密码与登录流程。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_default_user(self) -> UserView:
        """保证首次运行时至少存在一个默认用户。"""
        user = self.db.query(User).order_by(User.id.asc()).first()
        if user:
            return self._to_view(user)
        user = User(
            username="default",
            display_name="默认用户",
            home_city="上海",
            travel_style="轻松、高铁友好、美食优先",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return self._to_view(user)

    def list_users(self) -> list[UserView]:
        """读取本地用户列表。"""
        self.ensure_default_user()
        users = self.db.query(User).order_by(User.created_at.asc()).all()
        return [self._to_view(user) for user in users]

    def create_user(self, payload: UserCreateRequest) -> UserView:
        """创建本地用户。"""
        base = self._slug(payload.username or payload.display_name)
        username = base
        index = 1
        while self.db.query(User).filter(User.username == username).first():
            index += 1
            username = f"{base}-{index}"
        salt, password_hash = self._build_password_hash(payload.password) if payload.password else (None, None)
        user = User(
            username=username,
            password_salt=salt,
            password_hash=password_hash,
            display_name=payload.display_name.strip(),
            home_city=self._clean_text(payload.home_city, 50),
            travel_style=self._clean_text(payload.travel_style, 200),
            updated_at=utc_now(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return self._to_view(user)

    def register(
        self,
        payload: UserCreateRequest,
        client_name: str | None = None,
        user_agent: str | None = None,
    ) -> UserAuthView:
        """注册并直接签发登录态。"""
        user_view = self.create_user(payload)
        user = self.db.get(User, user_view.id)
        if not user:
            raise ValueError("注册用户不存在")
        return AuthService(self.db).create_session(user, client_name=client_name, user_agent=user_agent)

    def login(
        self,
        payload: UserLoginRequest,
        client_name: str | None = None,
        user_agent: str | None = None,
    ) -> UserAuthView:
        """校验本地账号密码，并签发正式登录会话。"""
        user = self.db.query(User).filter(User.username == payload.username.strip()).first()
        if not user:
            raise ValueError("用户不存在")
        if user.password_hash and user.password_salt:
            expected = self._hash_password(payload.password, user.password_salt)
            if not hmac.compare_digest(expected, user.password_hash):
                raise ValueError("密码错误")
        elif payload.password:
            raise ValueError("该演示用户未设置密码，请留空密码登录")

        user.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(user)
        return AuthService(self.db).create_session(user, client_name=client_name, user_agent=user_agent)

    def update_profile(self, user_id: int, payload: UserProfileUpdateRequest) -> UserView:
        """更新用户资料，必要时同步修改密码。"""
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")

        if payload.display_name is not None:
            user.display_name = payload.display_name.strip()
        if payload.home_city is not None:
            user.home_city = self._clean_text(payload.home_city, 50)
        if payload.travel_style is not None:
            user.travel_style = self._clean_text(payload.travel_style, 200)
        if payload.new_password is not None:
            self._change_password(user, payload.current_password or "", payload.new_password)

        user.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(user)
        return self._to_view(user)

    def get_user(self, user_id: int) -> UserView:
        """按 ID 读取用户信息。"""
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")
        return self._to_view(user)

    def _change_password(self, user: User, current_password: str, new_password: str) -> None:
        """修改用户密码。"""
        if user.password_hash and user.password_salt:
            expected = self._hash_password(current_password, user.password_salt)
            if not hmac.compare_digest(expected, user.password_hash):
                raise ValueError("当前密码不正确")
        elif current_password:
            raise ValueError("当前账号尚未设置密码，无需填写当前密码")

        salt, password_hash = self._build_password_hash(new_password)
        user.password_salt = salt
        user.password_hash = password_hash

    def _to_view(self, user: User) -> UserView:
        return UserView(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            home_city=user.home_city,
            travel_style=user.travel_style,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat() if user.updated_at else None,
        )

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
        normalized = "-".join(part for part in normalized.split("-") if part)
        return normalized[:40] or "user"

    def _build_password_hash(self, password: str) -> tuple[str, str]:
        """生成密码盐值和哈希，避免保存明文密码。"""
        salt = secrets.token_hex(16)
        return salt, self._hash_password(password, salt)

    def _hash_password(self, password: str, salt: str) -> str:
        """使用 PBKDF2 进行本地密码哈希。"""
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()

    def _clean_text(self, value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:max_length] if text else None
