import hashlib
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings


class AmapService:
    """高德 Web 服务封装。

    产品级策略：
    1. 有 Key 时优先调用真实高德天气、地理编码、POI 和路线接口。
    2. 无 Key、演示模式、网络异常或高德返回异常时，返回结构一致的兜底数据。
    3. 对外永远不暴露 API Key，只暴露配置状态和调用结果。
    """

    BASE_URL = "https://restapi.amap.com"

    def __init__(self) -> None:
        self.api_key = settings.amap_api_key
        # 高德工具在智能体链路里会连续调用多次，单次请求控制在 5 秒内，避免前端长时间等待。
        self.timeout = min(settings.request_timeout_seconds, 5.0)

    def configured(self) -> bool:
        """判断高德服务是否具备真实调用条件。"""
        return bool(self.api_key and not settings.demo_mode)

    def config_status(self) -> dict[str, Any]:
        """返回可公开展示的高德配置状态。"""
        return {
            "provider": "amap",
            "base_url": self.BASE_URL,
            "configured": self.configured(),
            "has_api_key": bool(self.api_key),
            "timeout_seconds": self.timeout,
            "supports": ["weather", "geocode", "poi_search", "walking_route", "driving_route"],
        }

    async def ping(self) -> dict[str, Any]:
        """主动检查高德 Web 服务连通性。"""
        if not self.configured():
            return {
                **self.config_status(),
                "ok": False,
                "message": "未配置 AMAP_API_KEY，当前会使用本地演示地图和天气数据。",
            }

        result = await self.geocode("北京市")
        return {
            **self.config_status(),
            "ok": not result.get("fallback"),
            "message": "高德连接正常" if not result.get("fallback") else result.get("reason"),
            "sample": result,
        }

    async def get_weather(self, city: str, date: str | None = None) -> dict[str, Any]:
        """查询城市天气，优先返回实况，同时附带预报切片供智能体判断。"""
        if not self.configured():
            return self._demo_weather(city, date)

        city_info = await self.geocode(city)
        if city_info.get("fallback"):
            return self._demo_weather(city, date, reason=city_info.get("reason", "城市解析失败"))

        adcode = city_info.get("adcode") or city
        live_data = await self._safe_get(
            "/v3/weather/weatherInfo",
            {
                "city": adcode,
                "extensions": "base",
                "output": "json",
            },
            fallback_reason="高德实况天气接口调用失败",
        )
        if live_data.get("fallback"):
            return self._demo_weather(city, date, reason=live_data.get("reason", "天气接口失败"))

        lives = live_data.get("lives") or []
        if not lives:
            return self._demo_weather(city, date, reason="高德未返回实况天气数据")

        live = lives[0]
        forecast = await self._get_weather_forecast(adcode)
        risk_tags = self._risk_tags(live)
        forecast_casts = forecast.get("casts", []) if forecast else []
        risk_tags.extend(self._forecast_risk_tags(forecast_casts))

        return {
            "provider": "amap",
            "city": live.get("city") or city_info.get("formatted_address") or city,
            "adcode": adcode,
            "date": date,
            "weather": live.get("weather"),
            "temperature": live.get("temperature"),
            "winddirection": live.get("winddirection"),
            "windpower": live.get("windpower"),
            "humidity": live.get("humidity"),
            "reporttime": live.get("reporttime"),
            "forecasts": forecast_casts[:4],
            "risk_tags": sorted(set(risk_tags)),
            "fallback": False,
            "source": "amap_weather",
        }

    async def geocode(self, address: str, city: str | None = None) -> dict[str, Any]:
        """把中文地址解析成高德经纬度和行政区编码。"""
        if not self.configured():
            return self._demo_geocode(address, city)

        data = await self._safe_get(
            "/v3/geocode/geo",
            {
                "address": address,
                "city": city or "",
                "output": "json",
            },
            fallback_reason="高德地理编码接口调用失败",
        )
        if data.get("fallback"):
            return self._demo_geocode(address, city, reason=data.get("reason", "地理编码失败"))

        geocodes = data.get("geocodes") or []
        if not geocodes:
            return self._demo_geocode(address, city, reason="高德未返回地理编码结果")

        item = geocodes[0]
        return {
            "provider": "amap",
            "address": address,
            "city": item.get("city") or city,
            "district": item.get("district"),
            "adcode": item.get("adcode"),
            "formatted_address": item.get("formatted_address") or address,
            "location": item.get("location"),
            "level": item.get("level"),
            "fallback": False,
            "source": "amap_geocode",
        }

    async def search_poi(self, keyword: str, city: str | None = None) -> dict[str, Any]:
        """查询 POI，用于景点、车站、餐厅等地点候选。"""
        if not self.configured():
            return self._demo_poi(keyword, city)

        data = await self._safe_get(
            "/v3/place/text",
            {
                "keywords": keyword,
                "city": city or "",
                "citylimit": "true" if city else "false",
                "offset": 10,
                "page": 1,
                "output": "json",
            },
            fallback_reason="高德 POI 搜索接口调用失败",
        )
        if data.get("fallback"):
            return self._demo_poi(keyword, city, reason=data.get("reason", "POI 查询失败"))

        pois = [self._normalize_poi(item) for item in data.get("pois", [])]
        if not pois:
            return self._demo_poi(keyword, city, reason="高德未返回 POI 结果")

        return {
            "provider": "amap",
            "keyword": keyword,
            "city": city,
            "pois": pois,
            "fallback": False,
            "source": "amap_poi",
        }

    async def route(
        self,
        origin: str,
        destination: str,
        city: str | None = None,
        mode: str = "transit",
    ) -> dict[str, Any]:
        """查询两点之间路线，支持步行、驾车和公交兜底。

        高德公交接口对城市参数要求更严格，因此当前产品默认优先返回步行/驾车的
        稳定路线估算；公交模式无法可靠解析时会降级到驾车路线，并在 mode_used 标注。
        """
        if not self.configured():
            return self._demo_route(origin, destination, city, mode)

        origin_location = await self._resolve_location(origin, city)
        destination_location = await self._resolve_location(destination, city)
        if origin_location.get("fallback") or destination_location.get("fallback"):
            return self._demo_route(
                origin,
                destination,
                city,
                mode,
                reason="地点解析失败，使用演示路线",
            )

        normalized_mode = self._normalize_route_mode(mode)
        endpoint = "/v3/direction/walking" if normalized_mode == "walking" else "/v3/direction/driving"
        data = await self._safe_get(
            endpoint,
            {
                "origin": origin_location["location"],
                "destination": destination_location["location"],
                "city": city or "",
                "output": "json",
            },
            fallback_reason="高德路线规划接口调用失败",
        )
        if data.get("fallback"):
            return self._demo_route(origin, destination, city, mode, reason=data.get("reason", "路线规划失败"))

        route_data = data.get("route") or {}
        paths = route_data.get("paths") or []
        if not paths:
            return self._demo_route(origin, destination, city, mode, reason="高德未返回路线结果")

        path = paths[0]
        duration_seconds = self._to_int(path.get("duration"))
        distance_meters = self._to_int(path.get("distance"))
        steps = [
            {
                "instruction": step.get("instruction"),
                "road": step.get("road"),
                "distance_meters": self._to_int(step.get("distance")),
                "duration_seconds": self._to_int(step.get("duration")),
            }
            for step in path.get("steps", [])[:8]
        ]
        return {
            "provider": "amap",
            "origin": origin,
            "destination": destination,
            "city": city,
            "mode": mode,
            "mode_used": normalized_mode,
            "origin_location": origin_location,
            "destination_location": destination_location,
            "distance_meters": distance_meters,
            "duration_minutes": max(1, round(duration_seconds / 60)),
            "steps": steps,
            "fallback": False,
            "source": "amap_direction",
        }

    async def _get_weather_forecast(self, adcode: str) -> dict[str, Any] | None:
        """查询天气预报，失败时不影响实况天气返回。"""
        data = await self._safe_get(
            "/v3/weather/weatherInfo",
            {
                "city": adcode,
                "extensions": "all",
                "output": "json",
            },
            fallback_reason="高德预报天气接口调用失败",
        )
        if data.get("fallback"):
            return None
        forecasts = data.get("forecasts") or []
        if not forecasts:
            return None
        return forecasts[0]

    async def _resolve_location(self, keyword: str, city: str | None) -> dict[str, Any]:
        """优先地理编码，失败后用 POI 搜索补救。"""
        geocode = await self.geocode(keyword, city)
        if not geocode.get("fallback") and geocode.get("location"):
            return geocode

        poi = await self.search_poi(keyword, city)
        pois = poi.get("pois") or []
        if pois:
            first = pois[0]
            return {
                "provider": "amap",
                "address": keyword,
                "city": first.get("city") or city,
                "district": first.get("district"),
                "adcode": first.get("adcode"),
                "formatted_address": first.get("name") or keyword,
                "location": first.get("location"),
                "level": "poi",
                "fallback": False,
                "source": "amap_poi",
            }
        return geocode

    async def _safe_get(
        self,
        path: str,
        params: dict[str, Any],
        fallback_reason: str,
    ) -> dict[str, Any]:
        """统一高德 GET 请求，过滤 Key 并转换高德业务错误。"""
        request_params = {"key": self.api_key, **params}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.BASE_URL + path, params=request_params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("高德接口请求失败 {}：{}", path, exc)
            return {"fallback": True, "reason": fallback_reason, "error": str(exc)}

        if data.get("status") != "1":
            info = data.get("info") or data.get("infocode") or fallback_reason
            logger.warning("高德接口业务失败 {}：{}", path, info)
            return {"fallback": True, "reason": f"{fallback_reason}：{info}"}
        return data

    def _normalize_poi(self, item: dict[str, Any]) -> dict[str, Any]:
        """压缩高德 POI 字段，避免把大对象直接传给前端和大模型。"""
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "type": item.get("type"),
            "address": item.get("address"),
            "location": item.get("location"),
            "city": item.get("cityname"),
            "district": item.get("adname"),
            "adcode": item.get("adcode"),
            "tel": item.get("tel"),
        }

    def _risk_tags(self, live: dict[str, Any]) -> list[str]:
        """把天气文本转换为旅行风险标签。"""
        weather = live.get("weather") or ""
        tags: list[str] = []
        if any(word in weather for word in ["雨", "雪", "雷"]):
            tags.append("雨雪天气")
        try:
            temperature = int(live.get("temperature") or 0)
            if temperature >= 33:
                tags.append("高温")
            if temperature <= 5:
                tags.append("低温")
        except (TypeError, ValueError):
            pass
        windpower = str(live.get("windpower") or "")
        if any(level in windpower for level in ["5", "6", "7", "8", "9"]):
            tags.append("大风")
        return tags

    def _forecast_risk_tags(self, casts: list[dict[str, Any]]) -> list[str]:
        """根据预报补充未来几天风险标签。"""
        tags: list[str] = []
        for cast in casts[:4]:
            day_weather = cast.get("dayweather") or ""
            night_weather = cast.get("nightweather") or ""
            if any(word in f"{day_weather}{night_weather}" for word in ["雨", "雪", "雷"]):
                tags.append("未来有雨雪")
            day_temp = self._to_int(cast.get("daytemp"))
            night_temp = self._to_int(cast.get("nighttemp"))
            if day_temp >= 33:
                tags.append("未来高温")
            if night_temp and night_temp <= 5:
                tags.append("未来低温")
        return tags

    def _normalize_route_mode(self, mode: str) -> str:
        """把前端或智能体传入的模式映射为当前稳定支持的高德接口。"""
        if mode in {"walk", "walking", "步行"}:
            return "walking"
        return "driving"

    def _to_int(self, value: Any) -> int:
        """高德返回大量数字字符串，这里统一转为 int。"""
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _demo_weather(
        self,
        city: str,
        date: str | None,
        fallback: bool = True,
        reason: str = "未配置高德 Key，使用演示天气",
    ) -> dict[str, Any]:
        """根据城市名生成稳定的演示天气，避免每次展示结果跳变。"""
        options = [
            ("多云", "18-24", []),
            ("小雨", "17-22", ["雨雪天气"]),
            ("晴", "20-28", []),
            ("阴", "16-21", []),
        ]
        index = int(hashlib.sha1(city.encode("utf-8")).hexdigest(), 16) % len(options)
        weather, temperature, tags = options[index]
        return {
            "provider": "demo",
            "city": city,
            "date": date,
            "weather": weather,
            "temperature": temperature,
            "risk_tags": tags,
            "reporttime": "演示数据",
            "forecasts": [],
            "fallback": fallback,
            "reason": reason,
            "source": "demo_weather",
        }

    def _demo_geocode(
        self,
        address: str,
        city: str | None,
        fallback: bool = True,
        reason: str = "未配置高德 Key，使用演示地理编码",
    ) -> dict[str, Any]:
        """返回稳定演示坐标，结构与高德地理编码结果保持一致。"""
        seed = int(hashlib.sha1(f"{city or ''}{address}".encode("utf-8")).hexdigest(), 16)
        lng = 118.0 + (seed % 6000) / 1000
        lat = 28.0 + (seed % 4000) / 1000
        return {
            "provider": "demo",
            "address": address,
            "city": city,
            "district": None,
            "adcode": None,
            "formatted_address": f"{city or ''}{address}",
            "location": f"{lng:.6f},{lat:.6f}",
            "level": "demo",
            "fallback": fallback,
            "reason": reason,
            "source": "demo_geocode",
        }

    def _demo_poi(
        self,
        keyword: str,
        city: str | None,
        fallback: bool = True,
        reason: str = "未配置高德 Key，使用演示 POI",
    ) -> dict[str, Any]:
        """返回前端可展示的演示 POI。"""
        location = self._demo_geocode(keyword, city)["location"]
        return {
            "provider": "demo",
            "keyword": keyword,
            "city": city,
            "pois": [
                {
                    "name": keyword,
                    "type": "风景名胜",
                    "address": f"{city or '目的地'}核心游览区",
                    "location": location,
                    "city": city,
                    "district": None,
                    "adcode": None,
                }
            ],
            "fallback": fallback,
            "reason": reason,
            "source": "demo_poi",
        }

    def _demo_route(
        self,
        origin: str,
        destination: str,
        city: str | None,
        mode: str,
        fallback: bool = True,
        reason: str = "未配置高德 Key，使用演示路线",
    ) -> dict[str, Any]:
        """返回稳定路线摘要，便于前端和智能体完成闭环。"""
        distance = 4200 + (len(origin) + len(destination)) * 180
        duration = max(12, distance // 260)
        return {
            "provider": "demo",
            "origin": origin,
            "destination": destination,
            "city": city,
            "mode": mode,
            "mode_used": self._normalize_route_mode(mode),
            "distance_meters": distance,
            "duration_minutes": duration,
            "steps": [],
            "fallback": fallback,
            "reason": reason,
            "source": "demo_route",
        }
