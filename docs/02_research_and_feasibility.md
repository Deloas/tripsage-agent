# 02. 技术调研与可行性分析

## 1. 调研目标

本阶段调研四类关键技术：

1. 攻略数据来源是否适合构建知识库。
2. 12306 能否以稳定方式接入智能体。
3. 天气和地图接口是否适合国内旅行场景。
4. 技术栈是否能支撑课程项目、答辩演示和后续维护。

## 2. 攻略数据调研

初始攻略来源为微博攻略合集：

https://weibo.com/7896659368/QB5oxASNO

该页面包含按地区和主题整理的攻略入口，例如江浙沪、粤港澳、云南、川渝、北京、山东、江西、贵州、福建、新疆、东北、内蒙、湖北、河南、广西、出行住宿、solo trip、长途火车经验和旅行用品等。

适用性判断：

- 内容适合构建旅游攻略知识库。
- 数据具有真实用户经验价值。
- 链接型内容需要人工整理或半自动采集后入库。
- 需要记录来源，避免大模型无依据生成。

处理策略：

- 第一阶段手动整理核心城市攻略样本。
- 第二阶段支持用户粘贴攻略文本添加。
- 第三阶段再扩展链接解析能力。

## 3. 12306 接入调研

用户提供的可接入方案：

https://www.modelscope.cn/mcp/servers/A15570082312/12306

调研结论：

- 采用 ModelScope 12306 MCP 比直接适配 12306 网页接口更专业。
- MCP 能作为智能体工具暴露给 LangGraph。
- 项目中只使用查询类能力，不涉及登录、购票、抢票或验证码。
- 后端需要设计 MCP 连接配置、工具 allowlist、超时和降级。

建议接入方式：

```text
FastAPI
  ↓
LangGraph Agent
  ↓
langchain-mcp-adapters
  ↓
ModelScope 12306 MCP Server
```

降级策略：

- MCP 不可用时读取最近缓存。
- 缓存不存在时返回演示 Mock 数据，并明确标记为演示数据。
- 记录错误日志，不让智能体流程中断。

## 4. 天气与地图接口调研

推荐使用高德开放平台 Web 服务 API。

参考链接：

- 天气查询：https://lbs.amap.com/api/webservice/guide/api-advanced/weatherinfo
- 路径规划：https://lbs.amap.com/api/webservice/guide/api/direction
- POI 搜索：https://lbs.amap.com/api/webservice/guide/api-advanced/search

选择理由：

- 国内城市覆盖好。
- 一个 Key 可以覆盖天气、地点、路径等能力。
- Web 服务 API 适合后端调用。
- 响应结构稳定，便于封装。

主要用途：

| API | 项目用途 |
| --- | --- |
| 天气查询 | 判断目的地天气、雨天风险、温度建议 |
| POI 搜索 | 查询景点、餐厅、车站、酒店附近位置 |
| 地理编码 | 将城市或地点名称转为经纬度 |
| 路径规划 | 估算景点之间交通距离和耗时 |

风险：

- Key 配额限制。
- 网络不稳定。
- 用户输入地点可能不标准。

缓解策略：

- 使用 `api_cache` 表缓存结果。
- 设置请求超时。
- 对地点做标准化和重试。

## 5. 大模型与智能体框架调研

### 5.1 大模型

项目建议使用 OpenAI-compatible 调用方式，实际模型可配置为：

- DeepSeek
- 通义千问
- 智谱 GLM
- OpenAI
- 其他兼容 OpenAI API 的模型服务

这样可以通过 `.env` 切换模型，而不是把项目绑定到单一厂商。

### 5.2 智能体框架

推荐使用 LangGraph。

原因：

- 适合多节点流程编排。
- 适合把 RAG、MCP、天气、地图等工具组织成可控工作流。
- 比普通 ReAct Agent 更容易解释和调试。
- 可以在答辩中清晰展示状态图和工具调用链。

### 5.3 MCP 适配

建议使用：

- `langchain-mcp-adapters`
- `mcp` Python SDK

参考：

- https://docs.langchain.com/oss/python/langchain/mcp
- https://github.com/modelcontextprotocol/python-sdk

## 6. 数据库调研

课程项目推荐：

```text
SQLite + Chroma
```

原因：

- Windows 本地启动简单。
- 不依赖数据库服务安装。
- 方便答辩演示。
- 适合中小规模攻略知识库。

生产增强版：

```text
PostgreSQL + pgvector
```

可作为项目扩展方向写入报告，但本次落地优先使用 SQLite + Chroma。

## 7. 前端技术调研

推荐：

```text
React + TypeScript + Vite + Tailwind CSS + Framer Motion + lucide-react
```

选择理由：

- React 生态成熟。
- TypeScript 能提升组件和接口契约质量。
- Vite 启动快，适合课程项目。
- Tailwind 可快速搭建高质量响应式界面。
- Framer Motion 适合做精致但克制的动效。
- lucide-react 图标专业简洁。

设计方向：

- 旅行决策驾驶舱。
- 左侧条件与会话，中间行程和回答，右侧工具结果和来源。
- 不做普通营销首页。
- 首屏就是可用工作台。

## 8. 可行性结论

本项目技术上可行，且具备明显的课程项目价值。

| 维度 | 结论 |
| --- | --- |
| 数据来源 | 可行，需要整理和来源记录 |
| 12306 接入 | 可行，推荐 MCP 查询工具 |
| 天气地图 | 可行，高德接口覆盖需求 |
| 智能体 | 可行，LangGraph 能支撑多工具编排 |
| 前端 | 可行，React 技术栈适合精致工作台 |
| 演示稳定性 | 可行，需要缓存和 Mock 兜底 |

最终建议采用：

```text
FastAPI + LangGraph + MCP + 高德 API + SQLite + Chroma + React
```

