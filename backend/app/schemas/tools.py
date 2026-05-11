from pydantic import BaseModel, Field

from app.schemas.chat import RenderPlan, StructuredTravelPlan, TravelPlanView


class WeatherRequest(BaseModel):
    """天气查询请求。"""

    city: str = Field(min_length=1, max_length=80)
    date: str | None = None


class PoiRequest(BaseModel):
    """地点搜索请求。"""

    keyword: str = Field(min_length=1, max_length=120)
    city: str | None = None


class GeocodeRequest(BaseModel):
    """地理编码请求。"""

    address: str = Field(min_length=1, max_length=120)
    city: str | None = None


class RouteRequest(BaseModel):
    """路线查询请求。"""

    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    city: str | None = None
    mode: str = "transit"


class AiMapItineraryItem(BaseModel):
    """AI 行程中的单个安排，用于从回答结果里抽取地图地点。"""

    time: str | None = None
    title: str = Field(default="", max_length=240)
    detail: str = Field(default="", max_length=4000)


class AiMapItineraryDay(BaseModel):
    """AI 行程中的一天，用于生成地图按天分组。"""

    day: int = 1
    title: str = Field(default="", max_length=240)
    items: list[AiMapItineraryItem] = Field(default_factory=list)


class AiMapWorkbenchRequest(BaseModel):
    """把智能体输出转换为地图工作台的请求。"""

    city: str | None = Field(default=None, max_length=80)
    answer: str = Field(default="", max_length=50000)
    itinerary: list[AiMapItineraryDay] = Field(default_factory=list)
    structured_plan: StructuredTravelPlan | None = None
    render_plan: RenderPlan | None = None
    # 中文注释：页面渲染层的结构化攻略会比长文本更稳定，地图工作台优先消费它。
    travel_plan_view: TravelPlanView | None = None
    mode: str = "driving"


class RailwayRequest(BaseModel):
    """铁路查询请求。"""

    origin: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=80)
    date: str = Field(min_length=1, max_length=20)


class WebSearchRequest(BaseModel):
    """联网搜索请求。"""

    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=5, ge=1, le=10)
