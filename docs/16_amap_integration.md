# 高德天气与地图接入说明

## 接入目标

TripSage Agent 使用高德 Web 服务为智能体提供真实世界上下文：

- 天气：判断雨雪、高温、低温、大风等旅行风险。
- 地理编码：把中文城市、车站、景点名称解析为经纬度和 adcode。
- POI 搜索：解决景点、车站、餐厅等地点候选。
- 路线规划：估算车站到景点、景点之间的通勤距离和耗时。

所有调用都由后端 `AmapService` 封装，前端和大模型不会直接访问高德 API。

## 本地配置

打开 `backend/.env`，填写：

```env
AMAP_API_KEY=你的高德 Web 服务 Key
```

注意：

- 需要在高德开放平台创建 Web 服务 Key。
- 不要把真实 Key 写入文档或提交到公开仓库。
- 未配置 Key 时项目仍可完整运行，但天气、地图会显示为演示兜底数据。

## 连通性检查

后端启动后访问：

```text
GET http://127.0.0.1:8000/api/amap/ping
```

也可以命令行执行：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_amap
```

返回 `ok: true` 表示高德接口可用。返回 `ok: false` 时，优先检查：

- `AMAP_API_KEY` 是否填写。
- Key 类型是否为 Web 服务。
- 高德开放平台配额是否可用。
- 当前网络是否能访问 `https://restapi.amap.com`。

## 后端工具接口

项目提供以下内部工具接口：

```text
POST /api/tools/weather
POST /api/tools/map/geocode
POST /api/tools/map/poi
POST /api/tools/map/route
GET  /api/amap/ping
```

示例：天气查询

```json
{
  "city": "苏州",
  "date": "周末"
}
```

示例：路线查询

```json
{
  "origin": "苏州站",
  "destination": "拙政园",
  "city": "苏州",
  "mode": "walking"
}
```

## 智能体中的使用方式

当前 LangGraph 工作流会在以下场景调度高德：

- 用户规划行程时，查询目的地天气。
- 用户规划行程时，估算从车站到核心景区的通勤时间。
- 用户询问天气、下雨、高温、低温时，触发天气工具。

工具结果会写入 `tool_calls`，前端右侧“工具链”区域会展示调用状态。真实接口成功时状态为 `success`，无 Key 或异常时状态为 `fallback`。

## 产品级降级策略

高德接口失败不应该让智能体整体失败。当前策略：

- 无 Key：返回稳定演示天气、POI 和路线。
- 地点解析失败：路线工具返回演示路线，并标注 reason。
- 预报天气失败：保留实况天气，不中断回答。
- 高德业务错误：记录本地日志，前端只看到脱敏后的 reason。

## 产品价值

这部分不是为了展示接口数量，而是让智能体具备真实出行判断能力：

- 遇到雨雪天气时，规划会增加室内备选。
- 遇到高温或低温时，规划会提醒调整户外时间。
- 路线耗时过长时，后续可以让智能体压缩景点数量。
- 地理编码和 POI 搜索可支撑后续做地图可视化、路线重排和目的地歧义追问。
