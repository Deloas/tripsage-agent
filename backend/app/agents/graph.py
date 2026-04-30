from uuid import uuid4

from sqlalchemy.orm import Session

from app.agents.nodes import (
    intent_slot_node,
    planner_node,
    response_node,
    retrieval_node,
    route_node,
    railway_node,
    weather_node,
    web_search_node,
)
from app.agents.nodes import build_trip_graph
from app.db.models import Conversation, Message
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.conversation_service import ConversationService
from app.services.preference_service import PreferenceService


class TripAgent:
    """旅行智能体入口，负责会话持久化和 LangGraph 工作流运行。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph = build_trip_graph()

    async def run(self, request: ChatRequest) -> ChatResponse:
        """执行一次智能体对话，并返回前端可展示结构。"""
        conversation_id = request.conversation_id or uuid4().hex
        context = self._context_with_profile(request.context)
        if self._should_persist_session():
            self._ensure_conversation(conversation_id, request.message)
            self._save_message(conversation_id, "user", request.message)

        state = await self.graph.ainvoke(
            {
                "conversation_id": conversation_id,
                "user_message": request.message,
                "context": context,
                "search_mode": request.search_mode,
                "persist_session": self._should_persist_session(),
                "db": self.db,
            }
        )

        answer = state.get("final_answer", "我暂时无法完成规划，请稍后重试。")
        if self._should_persist_session():
            self._save_message(conversation_id, "assistant", answer)
        response = ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            intent=state.get("intent", "general_qa"),
            cards=state.get("cards", []),
            itinerary=state.get("itinerary"),
            tool_calls=state.get("tool_calls_view", []),
            sources=state.get("sources", []),
            warnings=state.get("warnings", []),
            decision_modules=state.get("decision_modules", []),
        )
        if self._should_persist_session():
            ConversationService(self.db).sync_archive_meta(
                conversation_id,
                request.message,
                response.model_dump(),
                state.get("slots", {}),
                user_id=self._current_user_id(),
            )
            self._learn_preferences(request.message, response)

        return response

    async def run_steps(self, request: ChatRequest):
        """按节点逐步执行智能体，供 SSE 流式接口推送阶段进度。"""
        conversation_id = request.conversation_id or uuid4().hex
        context = self._context_with_profile(request.context)
        if self._should_persist_session():
            self._ensure_conversation(conversation_id, request.message)
            self._save_message(conversation_id, "user", request.message)
        state = {
            "conversation_id": conversation_id,
            "user_message": request.message,
            "context": context,
            "search_mode": request.search_mode,
            "persist_session": self._should_persist_session(),
            "db": self.db,
        }
        steps = [
            ("intent_slot", "理解意图与抽取城市、日期、预算", intent_slot_node),
            ("retrieval", "检索本地攻略知识库", retrieval_node),
            ("web_search", "按检索模式补充联网资料", web_search_node),
            ("weather", "查询天气与出行风险", weather_node),
            ("railway", "查询 12306 MCP 铁路候选", railway_node),
            ("route", "估算车站到核心景区通勤", route_node),
            ("planner", "调用 DeepSeek 生成规划表达", planner_node),
            ("response", "组装前端决策工作台", response_node),
        ]
        yield "start", {"conversation_id": conversation_id, "message": "智能体已开始规划。"}
        for name, label, node in steps:
            yield "stage", {"name": name, "label": label, "status": "running"}
            state = await node(state)
            yield "stage", self._stage_payload(name, label, state)

        answer = state.get("final_answer", "我暂时无法完成规划，请稍后重试。")
        if self._should_persist_session():
            self._save_message(conversation_id, "assistant", answer)
        response = ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            intent=state.get("intent", "general_qa"),
            cards=state.get("cards", []),
            itinerary=state.get("itinerary"),
            tool_calls=state.get("tool_calls_view", []),
            sources=state.get("sources", []),
            warnings=state.get("warnings", []),
            decision_modules=state.get("decision_modules", []),
        )
        if self._should_persist_session():
            ConversationService(self.db).sync_archive_meta(
                conversation_id,
                request.message,
                response.model_dump(),
                state.get("slots", {}),
                user_id=self._current_user_id(),
            )
            self._learn_preferences(request.message, response)
        yield "result", response.model_dump()

    def _stage_payload(self, name: str, label: str, state: dict) -> dict:
        """生成可被前端直接显示的阶段摘要。"""
        summaries = {
            "intent_slot": f"识别为 {state.get('intent', 'general_qa')}。",
            "retrieval": f"命中 {len(state.get('retrieved_guides', []))} 条本地攻略片段。",
            "web_search": f"联网补充 {len(state.get('web_items', []))} 条来源。",
            "weather": "天气查询完成。" if state.get("weather_result") else "本轮无需天气查询。",
            "railway": (
                f"铁路返回 {len((state.get('railway_result') or {}).get('trains', []))} 条车次。"
                if state.get("railway_result")
                else "本轮无需铁路查询。"
            ),
            "route": "路线估算完成。" if state.get("route_result") else "本轮无需路线估算。",
            "planner": "规划文本已生成。",
            "response": "可视化决策模块已组装。",
        }
        return {
            "name": name,
            "label": label,
            "status": "done",
            "summary": summaries.get(name, "阶段完成。"),
        }

    def _ensure_conversation(self, conversation_id: str, first_message: str) -> None:
        """如果会话不存在则创建，标题用用户首句截断生成。"""
        conversation = self.db.get(Conversation, conversation_id)
        if conversation:
            conversation.updated_at = self._now()
            self.db.commit()
            return
        user_id = self._current_user_id()
        self.db.add(Conversation(id=conversation_id, user_id=user_id, title=first_message[:40]))
        self.db.commit()

    def _save_message(self, conversation_id: str, role: str, content: str) -> None:
        """保存聊天消息，便于后续实现会话回放。"""
        self.db.add(Message(conversation_id=conversation_id, role=role, content=content))
        conversation = self.db.get(Conversation, conversation_id)
        if conversation:
            conversation.updated_at = self._now()
        self.db.commit()

    def _context_with_profile(self, context: dict) -> dict:
        """把本地偏好画像注入智能体上下文。"""
        self._context_persist_session = bool(context.get("persist_session", True))
        self._context_user_id = context.get("user_id") if self._context_persist_session else None
        if not self._context_persist_session:
            return {**context, "preference_profile": None, "guest_mode": True}
        user_key = str(context.get("user_id") or "default")
        profile = PreferenceService(self.db, user_key=user_key).get_profile()
        return {**context, "preference_profile": profile.model_dump()}

    def _learn_preferences(self, message: str, response: ChatResponse) -> None:
        """智能体完成后沉淀用户旅行偏好。"""
        user_key = str(self._last_context_user_id or "default")
        PreferenceService(self.db, user_key=user_key).learn_from_interaction(message, response.model_dump())

    def _now(self):
        from app.db.models import utc_now

        return utc_now()

    @property
    def _last_context_user_id(self):
        return getattr(self, "_context_user_id", None)

    def _current_user_id(self) -> int | None:
        value = self._last_context_user_id
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _should_persist_session(self) -> bool:
        return getattr(self, "_context_persist_session", True)
