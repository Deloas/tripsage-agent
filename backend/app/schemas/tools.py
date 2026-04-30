from pydantic import BaseModel, Field


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


class RailwayRequest(BaseModel):
    """铁路查询请求。"""

    origin: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=80)
    date: str = Field(min_length=1, max_length=20)


class WebSearchRequest(BaseModel):
    """联网搜索请求。"""

    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=5, ge=1, le=10)
