import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User, UserSession, utc_now
from app.schemas.workspace import UserAuthStateView, UserAuthView, UserSessionView, UserView


@dataclass
class AuthContext:
    """当前请求解析出的鉴权上下文。"""

    user: User
    session: UserSession


class AuthService:
    """本地鉴权服务，负责访问令牌、刷新令牌与会话管理。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(
        self,
        user: User,
        client_name: str | None = None,
        user_agent: str | None = None,
    ) -> UserAuthView:
        """创建新的登录会话，并同时签发访问令牌与刷新令牌。"""
        refresh_token = secrets.token_urlsafe(48)
        session = UserSession(
            id=uuid4().hex,
            user_id=user.id,
            refresh_token_hash=self._hash_refresh_token(refresh_token),
            access_jti=uuid4().hex,
            client_name=self._clean_text(client_name, 120) or "TripSage Web",
            user_agent=self._clean_text(user_agent, 255),
            last_used_at=utc_now(),
            expires_at=utc_now() + timedelta(days=settings.auth_refresh_token_days),
        )
        self.db.add(session)
        user.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(session)
        return self._build_auth_view(user, session, refresh_token)

    def refresh_session(
        self,
        refresh_token: str,
        client_name: str | None = None,
        user_agent: str | None = None,
    ) -> UserAuthView:
        """使用刷新令牌续签，并执行刷新令牌轮换。"""
        session = self._get_session_by_refresh_token(refresh_token)
        if not self._is_session_active(session):
            raise ValueError("登录会话已失效，请重新登录")
        user = self.db.get(User, session.user_id)
        if not user:
            raise ValueError("登录用户不存在")

        next_refresh_token = secrets.token_urlsafe(48)
        session.refresh_token_hash = self._hash_refresh_token(next_refresh_token)
        session.access_jti = uuid4().hex
        session.last_used_at = utc_now()
        session.expires_at = utc_now() + timedelta(days=settings.auth_refresh_token_days)
        if client_name:
            session.client_name = self._clean_text(client_name, 120)
        if user_agent:
            session.user_agent = self._clean_text(user_agent, 255)
        user.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(session)
        return self._build_auth_view(user, session, next_refresh_token)

    def authenticate_access_token(self, access_token: str) -> AuthContext:
        """校验访问令牌，并返回对应的用户与会话。"""
        payload = self._decode_access_token(access_token)
        session_id = str(payload.get("sid") or "")
        user_id = int(payload.get("sub") or 0)
        access_jti = str(payload.get("jti") or "")
        if not session_id or not user_id or not access_jti:
            raise ValueError("访问令牌缺少必要字段")

        session = self.db.get(UserSession, session_id)
        if not session or session.user_id != user_id:
            raise ValueError("登录会话不存在")
        if not self._is_session_active(session):
            raise ValueError("登录会话已失效")
        if not hmac.compare_digest(session.access_jti, access_jti):
            raise ValueError("访问令牌已失效")

        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("登录用户不存在")

        session.last_used_at = utc_now()
        self.db.commit()
        return AuthContext(user=user, session=session)

    def get_auth_state(self, access_token: str) -> UserAuthStateView:
        """读取当前登录态。"""
        context = self.authenticate_access_token(access_token)
        return UserAuthStateView(
            user=self._to_user_view(context.user),
            session=self._to_session_view(context.session, current_session_id=context.session.id),
        )

    def revoke_session(self, refresh_token: str) -> None:
        """按刷新令牌注销当前会话。"""
        session = self._get_session_by_refresh_token(refresh_token)
        session.revoked_at = utc_now()
        session.last_used_at = utc_now()
        self.db.commit()

    def revoke_session_by_id(self, user_id: int, session_id: str, current_session_id: str | None = None) -> None:
        """按会话 ID 注销指定会话。"""
        session = self.db.get(UserSession, session_id)
        if not session or session.user_id != user_id:
            raise ValueError("目标会话不存在")
        if current_session_id and session.id == current_session_id:
            raise ValueError("请使用退出登录功能注销当前会话")
        session.revoked_at = utc_now()
        session.last_used_at = utc_now()
        self.db.commit()

    def list_sessions(self, user_id: int, current_session_id: str | None = None) -> list[UserSessionView]:
        """列出某个用户的全部登录会话。"""
        items = (
            self.db.query(UserSession)
            .filter(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .all()
        )
        return [self._to_session_view(item, current_session_id=current_session_id) for item in items]

    def _build_auth_view(self, user: User, session: UserSession, refresh_token: str) -> UserAuthView:
        access_token = self._encode_access_token(user_id=user.id, session_id=session.id, access_jti=session.access_jti)
        return UserAuthView(
            user=self._to_user_view(user),
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in_seconds=settings.auth_access_token_minutes * 60,
            session=self._to_session_view(session, current_session_id=session.id),
        )

    def _to_user_view(self, user: User) -> UserView:
        return UserView(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            home_city=user.home_city,
            travel_style=user.travel_style,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat() if user.updated_at else None,
        )

    def _to_session_view(self, session: UserSession, current_session_id: str | None = None) -> UserSessionView:
        return UserSessionView(
            id=session.id,
            client_name=session.client_name,
            user_agent=session.user_agent,
            created_at=session.created_at.isoformat(),
            last_used_at=session.last_used_at.isoformat() if session.last_used_at else None,
            expires_at=session.expires_at.isoformat(),
            revoked_at=session.revoked_at.isoformat() if session.revoked_at else None,
            is_current=bool(current_session_id and session.id == current_session_id),
            is_active=self._is_session_active(session),
        )

    def _get_session_by_refresh_token(self, refresh_token: str) -> UserSession:
        refresh_hash = self._hash_refresh_token(refresh_token)
        session = (
            self.db.query(UserSession)
            .filter(UserSession.refresh_token_hash == refresh_hash)
            .first()
        )
        if not session:
            raise ValueError("刷新令牌无效")
        return session

    def _is_session_active(self, session: UserSession) -> bool:
        if session.revoked_at is not None:
            return False
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at >= utc_now()

    def _hash_refresh_token(self, refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    def _encode_access_token(self, user_id: int, session_id: str, access_jti: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "sid": session_id,
            "jti": access_jti,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.auth_access_token_minutes)).timestamp()),
        }
        header = {"alg": "HS256", "typ": "JWT"}
        header_text = self._b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_text = self._b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_text}.{payload_text}".encode("utf-8")
        signature = hmac.new(
            settings.auth_secret_key.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        return f"{header_text}.{payload_text}.{self._b64url_encode(signature)}"

    def _decode_access_token(self, access_token: str) -> dict:
        try:
            header_text, payload_text, signature_text = access_token.split(".")
        except ValueError as exc:
            raise ValueError("访问令牌格式无效") from exc

        signing_input = f"{header_text}.{payload_text}".encode("utf-8")
        expected_signature = hmac.new(
            settings.auth_secret_key.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_signature = self._b64url_decode(signature_text)
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("访问令牌签名校验失败")

        payload = json.loads(self._b64url_decode(payload_text).decode("utf-8"))
        if payload.get("typ") != "access":
            raise ValueError("访问令牌类型不正确")
        if int(payload.get("exp") or 0) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("访问令牌已过期")
        return payload

    def _b64url_encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    def _b64url_decode(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))

    def _clean_text(self, value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:max_length] if text else None
