from __future__ import annotations

import asyncio
import math
from typing import Any

from sqlalchemy.orm import Session

from app.services.amap_service import AmapService
from app.services.rag_service import RagService


class GuideMobilityService:
    """攻略详情页的地图/铁路联动服务。

    中文注释：该服务只负责把已入库攻略转成可执行的出行上下文，不写入数据库，
    便于前端在详情页实时预览路线，并把铁路查询条件带入 12306 工作台。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    async def build_route_preview(self, guide_id: int, mode: str = "driving") -> dict[str, Any] | None:
        """基于攻略结构化地点生成地图路线预览。"""
        detail = RagService(self.db).get_guide_detail(guide_id)
        if not detail:
            return None

        city = detail.get("city") or ""
        nodes = self._build_route_nodes(detail)
        if len(nodes) < 2 and city:
            nodes = self._complete_minimum_nodes(nodes, city)

        amap = AmapService()
        # 中文注释：先并行解析所有地点坐标，再快速估算多段通勤，保证长攻略详情页响应稳定。
        nodes = await self._resolve_node_locations(amap, nodes, city)
        route_pairs = list(zip(nodes, nodes[1:]))[:6]
        routes: list[dict[str, Any]] = []
        for index, (origin, destination) in enumerate(route_pairs, start=1):
            distance = self._estimate_distance_meters(origin.get("location"), destination.get("location"))
            duration = self._estimate_duration_minutes(distance, mode)
            routes.append(
                {
                    "index": index,
                    "origin": origin,
                    "destination": destination,
                    "provider": origin.get("provider") or destination.get("provider") or "amap",
                    "mode": mode,
                    "mode_used": "walking" if mode in {"walking", "walk"} else "driving",
                    "distance_meters": distance,
                    "duration_minutes": duration,
                    "steps": [],
                    "fallback": bool(origin.get("fallback") or destination.get("fallback")),
                    "reason": "基于攻略地点坐标快速估算，正式出行前可再打开地图软件复核。",
                }
            )

        return {
            "guide_id": detail["id"],
            "title": detail["title"],
            "city": city,
            "mode": mode,
            "nodes": nodes,
            "routes": routes,
            "total_distance_meters": sum(int(item.get("distance_meters") or 0) for item in routes),
            "total_duration_minutes": sum(int(item.get("duration_minutes") or 0) for item in routes),
            "fallback": any(item.get("fallback") for item in routes),
            "railway_seed": self.build_railway_seed(detail),
        }

    def build_railway_seed(self, detail: dict[str, Any]) -> dict[str, Any]:
        """从攻略中推断铁路查询的目的地、到达站和建议日期占位。"""
        city = str(detail.get("city") or "").strip()
        nodes = self._build_route_nodes(detail)
        destination_station = self._guess_station(nodes, city)
        return {
            "origin": "",
            "destination": city,
            "destination_station": destination_station,
            "date": "",
            "guide_id": detail.get("id"),
            "guide_title": detail.get("title"),
            "hint": f"已从《{detail.get('title') or '攻略'}》带入目的地 {city}，补充出发城市和日期即可查询 12306。",
        }

    async def _resolve_node_locations(
        self,
        amap: AmapService,
        nodes: list[dict[str, Any]],
        city: str,
    ) -> list[dict[str, Any]]:
        """并行解析地点坐标，避免多节点详情页串行等待。"""
        results = await asyncio.gather(
            *(amap.geocode(node["name"], city) for node in nodes),
            return_exceptions=True,
        )
        resolved: list[dict[str, Any]] = []
        for node, result in zip(nodes, results):
            if isinstance(result, Exception):
                resolved.append({**node, "fallback": True, "reason": str(result)})
                continue
            resolved.append(
                {
                    **node,
                    "provider": result.get("provider"),
                    "location": result.get("location"),
                    "formatted_address": result.get("formatted_address"),
                    "fallback": bool(result.get("fallback")),
                    "reason": result.get("reason"),
                }
            )
        return resolved

    def _estimate_distance_meters(self, origin_location: str | None, destination_location: str | None) -> int:
        """用坐标估算城市内两点距离，叠加道路绕行系数。"""
        origin = self._parse_location(origin_location)
        destination = self._parse_location(destination_location)
        if not origin or not destination:
            return 4200
        lng1, lat1 = origin
        lng2, lat2 = destination
        radius = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)
        haversine = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        straight_distance = 2 * radius * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
        return max(600, round(straight_distance * 1.28))

    def _estimate_duration_minutes(self, distance_meters: int, mode: str) -> int:
        speed_meters_per_minute = 80 if mode in {"walking", "walk"} else 360
        return max(5, round(distance_meters / speed_meters_per_minute))

    def _parse_location(self, value: str | None) -> tuple[float, float] | None:
        if not value or "," not in value:
            return None
        try:
            lng, lat = value.split(",", 1)
            return float(lng), float(lat)
        except ValueError:
            return None

    def _build_route_nodes(self, detail: dict[str, Any]) -> list[dict[str, Any]]:
        """合并攻略结构化字段中的地点，保持路线节点优先。"""
        structured = detail.get("structured") or {}
        places = detail.get("places") or []
        ordered_sources: list[tuple[str, str, list[Any]]] = [
            ("route_nodes", "route", structured.get("route_nodes") or []),
            ("scenic_spots", "scenic", structured.get("scenic_spots") or []),
            ("food_spots", "food", structured.get("food_spots") or []),
            ("places", "poi", places),
        ]
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        city = str(detail.get("city") or "").strip()

        for source, place_type, values in ordered_sources:
            for raw in values:
                name = self._place_name(raw)
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "name": name,
                        "type": self._place_type(raw) or place_type,
                        "city": city,
                        "source": source,
                    }
                )
                if len(result) >= 8:
                    return result
        return result

    def _complete_minimum_nodes(self, nodes: list[dict[str, Any]], city: str) -> list[dict[str, Any]]:
        """地点不足时补一个城市车站锚点，让路线预览仍可用。"""
        station = {"name": f"{city}站", "type": "station", "city": city, "source": "fallback_station"}
        if not nodes:
            return [station, {"name": f"{city}核心景区", "type": "scenic", "city": city, "source": "fallback_core"}]
        if nodes[0]["name"] != station["name"]:
            return [station, *nodes]
        return nodes

    def _guess_station(self, nodes: list[dict[str, Any]], city: str) -> str:
        for node in nodes:
            name = node.get("name") or ""
            if "站" in name and len(name) <= 12:
                return name
        return f"{city}站" if city else ""

    def _place_name(self, raw: Any) -> str:
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            return str(raw.get("name") or raw.get("title") or "").strip()
        return ""

    def _place_type(self, raw: Any) -> str | None:
        if isinstance(raw, dict):
            value = raw.get("type") or raw.get("place_type")
            return str(value).strip() if value else None
        return None
