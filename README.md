# TripSage Agent

TripSage 是一个面向中国旅行场景的旅游攻略智能体。它不是单纯的聊天机器人，而是一个可运行的旅行决策工作台：支持本地攻略知识库检索、联网搜索增强、天气与地图工具调用、12306 车次查询、可编辑行程、多版本规划、历史中心和用户偏好画像。

## 当前完成度

项目已经具备完整 MVP 主链路：

- DeepSeek 大模型接入
- LangGraph 智能体编排
- 本地攻略知识库与 RAG 检索
- 微博公开攻略采集与本地导入
- 联网搜索增强
- 高德天气、POI、路线规划
- 12306 MCP 车次查询
- 流式输出与结构化决策模块
- 可编辑行程与方案版本管理
- 登录用户、游客模式、历史中心
- 用户偏好画像、纠偏、审计、时间线撤销
- 导出与本地分享页

## 技术栈

- 前端：React + TypeScript + Vite
- 后端：FastAPI + SQLAlchemy
- 智能体：LangGraph
- 大模型：DeepSeek
- 数据层：SQLite + Chroma
- 外部能力：高德地图 / 天气、12306 MCP、联网搜索

## 目录结构

```text
TripSage Agent
├─ backend/                  FastAPI 后端与智能体
├─ frontend/                 React 前端工作台
├─ docs/                     项目设计、集成、答辩文档
├─ data/                     SQLite 与向量索引
├─ logs/                     巡检与运行日志
├─ start.bat                 一键启动
├─ check_all.bat             一键交付巡检
├─ mcp_servers.example.json  12306 MCP 配置示例
└─ preflight.py              启动前环境自检
```

## 快速启动

先确认本机具备：

- Python 3.11+
- Node.js 20+
- Windows 10/11

启动前可先运行：

```bat
python preflight.py
```

正式启动：

```bat
start.bat
```

启动完成后默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 环境配置

首次启动会自动创建：

- `backend/.env`
- `frontend/.env`
- `mcp_servers.json`

建议重点填写：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=

AMAP_API_KEY=

WEB_SEARCH_ENABLED=true
WEB_SEARCH_PROVIDER=duckduckgo

MCP_12306_ALLOW_LIVE=false
```

说明：

- 未配置 `LLM_API_KEY` 时，系统会退回本地规则兜底，保证主流程仍可演示。
- 未配置 `AMAP_API_KEY` 时，天气和地图工具会使用演示数据。
- 未开启 `MCP_12306_ALLOW_LIVE=true` 时，12306 查询会走安全演示兜底。

## 核心接口

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/guides`
- `POST /api/guides/search`
- `POST /api/guides`
- `POST /api/tools/weather`
- `POST /api/tools/map/poi`
- `POST /api/tools/map/route`
- `POST /api/tools/railway`
- `POST /api/tools/web-search`
- `GET /api/conversations`
- `GET /api/preference-profile`
- `GET /api/preference-profile/audit`
- `GET /api/preference-profile/timeline`

## 一键巡检

项目根目录提供交付巡检脚本：

```bat
check_all.bat
```

它会检查：

- 后端测试
- 前端构建
- 后端健康启动
- 核心烟测
- 登录态历史中心与画像全链路烟测
- DeepSeek / 高德 / 联网搜索 / 12306 MCP 的可选 live 检查

未配置外部 Key 或未开启 live 的项目不会直接失败，而会标记为 `SKIP`。

## 常用检查命令

```bat
cd backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m app.scripts.smoke_test
.venv\Scripts\python.exe -m app.scripts.smoke_workspace_user_flow
.venv\Scripts\python.exe -m app.scripts.check_deepseek
.venv\Scripts\python.exe -m app.scripts.check_amap
.venv\Scripts\python.exe -m app.scripts.check_railway_mcp
.venv\Scripts\python.exe -m app.scripts.check_web_search
```

## 产品行为说明

- 默认进入新对话，不会自动回到上一次聊天
- 游客模式可直接体验聊天与规划，但不保存历史和画像
- 登录用户可使用历史中心、偏好画像、方案持久化、分享页
- 用户画像支持长期偏好、本次偏好、黑名单、锁定项、人工纠偏与撤销

## 文档入口

建议优先阅读：

- [总体架构](docs/03_architecture_design.md)
- [智能体设计](docs/04_agent_design.md)
- [数据库设计](docs/05_database_design.md)
- [接口契约](docs/06_api_contract.md)
- [部署与演示](docs/11_deployment_and_demo.md)
- [最终交付与答辩说明](docs/21_final_delivery_and_defense.md)

## 说明

这是一个课程项目，但实现目标按产品化标准推进。当前版本已经可运行、可演示、可继续扩展；如果继续向更完整产品演进，优先方向会是前端最终级打磨、工具失败降级体验、攻略数据管理后台和更完整的交付自动化。
