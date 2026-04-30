# 行迹智策 TripSage Agent 项目文档索引

本文档群用于指导“旅游攻略智能体”期末项目的完整开发、答辩和后续维护。项目目标是构建一个专业、稳定、可演示、可扩展的智能旅行规划应用：基于攻略知识库，结合 12306 MCP、天气接口和地图接口，为用户提供旅游攻略推荐、咨询、行程规划和攻略添加能力。

## 项目定位

项目名称：行迹智策 TripSage Agent

项目类型：大模型智能体应用

用户端：浏览器 Web 应用，提供 `start.bat` 一键启动

后端：Python + FastAPI

智能体框架：LangGraph

数据层：SQLite + Chroma

工具接口：

- 攻略 RAG 检索工具
- ModelScope 12306 MCP 工具
- 高德天气工具
- 高德地图、POI、路线规划工具
- 受控联网搜索增强工具
- 攻略添加和结构化抽取工具

## 文档目录

| 文件 | 作用 |
| --- | --- |
| [docs/00_project_overview.md](docs/00_project_overview.md) | 项目总览、目标、创新点、范围 |
| [docs/01_requirements_analysis.md](docs/01_requirements_analysis.md) | 需求分析、用户场景、功能与非功能需求 |
| [docs/02_research_and_feasibility.md](docs/02_research_and_feasibility.md) | 技术调研、接口可行性、风险结论 |
| [docs/03_architecture_design.md](docs/03_architecture_design.md) | 整体架构、模块边界、运行流程 |
| [docs/04_agent_design.md](docs/04_agent_design.md) | LangGraph 智能体设计、工具调用策略 |
| [docs/05_database_design.md](docs/05_database_design.md) | SQLite 结构化数据库与向量库设计 |
| [docs/06_api_contract.md](docs/06_api_contract.md) | 后端 REST API 契约和错误码 |
| [docs/07_frontend_design_spec.md](docs/07_frontend_design_spec.md) | 前端信息架构、视觉方向、组件规范 |
| [docs/08_data_and_rag_design.md](docs/08_data_and_rag_design.md) | 攻略数据、清洗、切片、检索和引用 |
| [docs/09_integration_design.md](docs/09_integration_design.md) | 12306 MCP、高德、大模型等外部集成 |
| [docs/10_development_standards.md](docs/10_development_standards.md) | 代码规范、注释规范、日志、测试 |
| [docs/11_deployment_and_demo.md](docs/11_deployment_and_demo.md) | 本地部署、启动脚本、答辩演示脚本 |
| [docs/12_project_plan_and_risks.md](docs/12_project_plan_and_risks.md) | 里程碑计划、风险和兜底方案 |
| [docs/13_acceptance_checklist.md](docs/13_acceptance_checklist.md) | 验收清单和交付检查表 |
| [docs/14_image_asset_plan.md](docs/14_image_asset_plan.md) | 中国旅行图片资产计划和生成提示词 |
| [docs/15_deepseek_integration.md](docs/15_deepseek_integration.md) | DeepSeek 大模型接入、配置和连通性检查 |
| [docs/16_amap_integration.md](docs/16_amap_integration.md) | 高德天气、地理编码、POI 和路线规划接入说明 |
| [docs/17_railway_mcp_integration.md](docs/17_railway_mcp_integration.md) | 12306 ModelScope MCP 接入、安全白名单和启用说明 |
| [docs/18_web_search_integration.md](docs/18_web_search_integration.md) | 联网搜索增强、双源降级、缓存和安全边界 |
| [docs/19_streaming_decision_workbench.md](docs/19_streaming_decision_workbench.md) | 流式输出、阶段进度和结构化决策工作台 |
| [docs/20_plan_version_management.md](docs/20_plan_version_management.md) | 方案版本管理、可切换优化结果和产品化前端优化 |

## 关键参考链接

- 微博攻略合集：https://weibo.com/7896659368/QB5oxASNO
- ModelScope 12306 MCP：https://www.modelscope.cn/mcp/servers/A15570082312/12306
- 高德天气 API：https://lbs.amap.com/api/webservice/guide/api-advanced/weatherinfo
- 高德路径规划 API：https://lbs.amap.com/api/webservice/guide/api/direction
- 高德搜索 API：https://lbs.amap.com/api/webservice/guide/api-advanced/search
- LangChain MCP 文档：https://docs.langchain.com/oss/python/langchain/mcp
- MCP Python SDK：https://github.com/modelcontextprotocol/python-sdk
- DeepSeek API 文档：https://api-docs.deepseek.com/

## 当前阶段

当前完成内容：

- 项目文档群。
- 后端 FastAPI 工程骨架。
- 前端 React 旅行决策工作台骨架。
- SQLite 数据模型、攻略入库、关键词检索和演示数据脚本。
- 天气、地图、12306 MCP 工具服务骨架和演示兜底。
- DeepSeek 大模型 OpenAI-compatible 接入、诊断接口和连通性检查脚本。
- 高德天气、地理编码、POI 搜索和路线规划真实接口封装。
- 12306 ModelScope MCP live 已接入：可发现安全查询工具，并完成真实车次查询。
- 联网搜索增强已接入：DuckDuckGo 优先，Bing 备用，支持 SQLite 缓存和来源标注。
- 智能体流式输出已接入：前端展示阶段进度，最终结果拆成交通、雨天、强度、预算、风险模块。
- 方案版本管理已接入：初版、二次优化版可在前端切换，并持久化到后端 SQLite，支持版本差异对比。
- 方案导出与分享页已接入：当前版本可导出 Markdown / HTML，并生成本地只读分享页面。
- 历史规划中心和用户偏好画像已接入：前端默认打开新对话，旧会话从历史中心恢复，系统自动沉淀城市、预算、交通、节奏和兴趣偏好。
- 本地多用户登录/切换已接入：可创建不同用户并设置登录密码，历史会话和偏好画像按用户隔离；默认演示用户仍可免密码进入。
- 历史规划中心增强已接入：支持搜索、收藏、标签编辑，并可按城市、预算和出发时间管理旅行档案。
- 历史规划中心专题视图已接入：支持最近更新、收藏夹、城市专题切换，并可直接删除无用历史。
- `start.bat` 一键启动脚本。

下一阶段：补充历史会话搜索、收藏和标签，让长期规划资料更容易管理。

## 当前工程结构

```text
大模型期末项目/
  backend/                  FastAPI 后端
  frontend/                 React 前端
  docs/                     项目文档群
  data/                     SQLite 与向量库数据目录
  logs/                     日志目录
  start.bat                 Windows 一键启动脚本
  mcp_servers.example.json  12306 MCP 配置示例
  README.md                 项目索引
```

## 快速启动

首次启动前，确认本机已安装 Python 3.11+ 和 Node.js 20+。

可先运行不安装依赖的运行前自检：

```bash
python preflight.py
```

Windows 下双击或在终端运行：

```bat
start.bat
```

脚本会自动完成：

- 创建 `backend/.env`、`frontend/.env` 和 `mcp_servers.json`。
- 创建后端虚拟环境。
- 安装后端依赖。
- 初始化 SQLite 数据库。
- 启动后端时自动导入内置初始攻略。
- 启动后端时自动补建本地 Chroma 向量索引。
- 安装前端依赖。
- 启动后端 `http://127.0.0.1:8000`。
- 启动前端 `http://127.0.0.1:5173`。

## 配置说明

真实密钥只写入本地文件，不提交到仓库：

```text
backend/.env
frontend/.env
mcp_servers.json
```

DeepSeek 默认配置已经写入 `backend/.env.example`：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
```

填写 Key 后可运行以下命令检查：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_deepseek
```

高德 Web 服务 Key 写入：

```env
AMAP_API_KEY=
```

填写后可运行：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_amap
```

12306 MCP 默认不会启动外部进程。确认本机 MCP 配置可用后，再改：

```env
MCP_12306_ALLOW_LIVE=true
```

检查命令：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_railway_mcp
```

联网搜索增强默认已开启，无需 API Key：

```env
WEB_SEARCH_ENABLED=true
WEB_SEARCH_PROVIDER=duckduckgo
WEB_SEARCH_TIMEOUT_SECONDS=10
WEB_SEARCH_CACHE_TTL_MINUTES=60
```

检查命令：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_web_search
```

重要配置：

```text
LLM_API_KEY=          大模型 API Key
LLM_BASE_URL=         OpenAI-compatible 服务地址
LLM_MODEL=            模型名称
AMAP_API_KEY=         高德开放平台 Key
MCP_12306_CONFIG_PATH=../mcp_servers.json
WEB_SEARCH_ENABLED=true
AUTO_SEED_GUIDES=true
AUTO_REBUILD_VECTOR_INDEX=true
AUTO_CRAWL_WEIBO_ON_STARTUP=false
```

未配置密钥时，后端会使用演示兜底数据，保证前端和智能体流程可以先跑通。

## 自动导入攻略数据

项目启动时会自动执行数据初始化：

- 自动创建数据库表。
- 自动导入内置初始攻略数据集。
- 自动跳过已导入的同标题攻略，避免重复写入。
- 自动补建 Chroma 向量索引。

内置初始攻略覆盖：

```text
南京、苏州、杭州、上海、北京、成都、重庆、广州、厦门、
青岛、长沙、武汉、西安、云南入门路线、长途火车经验
```

如果希望启动时自动尝试采集微博公开攻略入口，可以在 `backend/.env` 中开启：

```text
AUTO_CRAWL_WEIBO_ON_STARTUP=true
```

该功能默认关闭，因为它会在启动时联网访问公开微博页面；即使开启，也只采集公开可访问内容，不登录、不读 Cookie、不绕过验证码。

## 当前可用接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/health` | 后端健康检查 |
| `GET /api/tools/status` | 工具状态 |
| `GET /api/diagnostics` | 数据库、向量库、工具配置诊断 |
| `POST /api/chat` | 智能体聊天 |
| `POST /api/chat/stream` | 智能体流式聊天，返回阶段进度和最终结果 |
| `POST /api/plan-versions` | 保存智能体方案版本 |
| `GET /api/plan-versions` | 按会话读取方案版本 |
| `GET /api/plan-versions/compare` | 对比两个方案版本 |
| `POST /api/plan-versions/export` | 导出 Markdown / HTML 方案 |
| `POST /api/shared-plans` | 创建本地只读分享页 |
| `GET /api/shared-plans/{share_id}` | 读取分享页 |
| `GET /api/conversations` | 历史规划中心会话列表 |
| `GET /api/conversations/{conversation_id}` | 历史会话详情 |
| `PATCH /api/conversations/{conversation_id}` | 更新收藏、标签、城市、预算、出发时间 |
| `DELETE /api/conversations/{conversation_id}` | 删除会话及其关联版本、分享和工具记录 |
| `GET /api/preference-profile` | 用户旅行偏好画像 |
| `GET /api/users` | 本地用户列表 |
| `POST /api/users` | 创建本地用户 |
| `POST /api/auth/login` | 本地用户登录 |
| `GET /api/guides` | 攻略列表 |
| `GET /api/guides/sources` | 攻略来源列表 |
| `POST /api/guides` | 添加攻略 |
| `POST /api/guides/search` | 攻略检索 |
| `POST /api/guides/crawl/weibo` | 采集微博公开攻略入口 |
| `POST /api/tools/weather` | 天气工具 |
| `POST /api/tools/map/poi` | 地点工具 |
| `POST /api/tools/map/route` | 路线工具 |
| `POST /api/tools/railway` | 12306 MCP 铁路工具 |
| `GET /api/railway/ping` | 12306 MCP live 探活 |
| `GET /api/web-search/ping` | 联网搜索探活 |
| `POST /api/tools/web-search` | 受控联网搜索工具 |

## 已实现的前端工作台能力

- 三栏旅行决策工作台。
- 信息来源模式切换：自动、攻略库、联网增强。
- 添加攻略弹窗。
- 微博公开攻略采集入口。
- 本地攻略来源统计。
- 工具调用链展示。
- 中国旅行图片资产位预留。

## 智能体实现状态

当前后端已经采用 LangGraph 节点化工作流：

```text
意图识别与槽位抽取
  -> 本地攻略检索
  -> 联网增强判断
  -> 天气工具
  -> 12306 MCP 铁路工具
  -> 地图路线工具
  -> 规划生成
  -> 前端响应组装
```

未配置大模型时，系统会使用规则兜底，保证本地演示可运行；配置 OpenAI-compatible 大模型后，会优先使用大模型进行结构化理解和规划表达。

## 启动后验证

后端和前端启动后，可以运行后端冒烟测试：

```bash
cd backend
.venv\Scripts\python.exe -m app.scripts.smoke_test
```

冒烟测试会检查：

- `/api/health`
- `/api/tools/status`
- `/api/diagnostics`
- `/api/guides`
- `/api/chat`

如果全部通过，说明自动导入攻略、基础智能体、工具状态和聊天接口已经可用。

## 游客模式与登录

- 系统现在默认以“新对话 + 游客模式”进入，不会自动回到上一次聊天页面。
- 游客模式可以正常完成聊天规划、查看工具调用、生成可编辑方案、进行二次优化，也可以导出当前方案。
- 游客模式不会保存历史会话、不会沉淀用户偏好画像、不会保存持久化版本，也不能创建分享页。
- 只有注册或登录后的本地用户，才会启用历史规划中心、偏好画像、版本持久化和分享页能力。
- 从游客切换到登录用户时，不会迁移游客临时会话；系统会为当前账号自动开启一段全新的持久化对话。

## 当前产品行为

- 每次重新启动前端时，首页默认打开新对话。
- 想继续之前的聊天，需要进入“历史规划中心”主动恢复。
- 历史规划中心支持按城市、预算、时间、标签和收藏状态管理已保存方案。
- 用户偏好画像只对已登录用户生效，并会在后续规划时自动个性化推荐。
