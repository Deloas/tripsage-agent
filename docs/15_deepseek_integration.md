# DeepSeek 大模型接入说明

## 接入目标

本项目使用 DeepSeek 作为默认大模型供应商，后端通过 OpenAI-compatible Chat Completions 协议调用模型。智能体中的意图识别、槽位抽取和最终规划生成会优先调用 DeepSeek；如果没有配置 Key、网络异常或接口失败，系统会自动回退到规则识别和模板规划，保证课程演示不中断。

## 官方兼容方式

DeepSeek 提供与 OpenAI SDK/协议兼容的聊天补全接口：

- Base URL：`https://api.deepseek.com`
- Chat Completions 路径：`/chat/completions`
- 推荐通用模型：`deepseek-v4-flash`
- 可选增强模型：`deepseek-v4-pro`
- 兼容旧模型：`deepseek-chat`

项目不在代码中保存 API Key，只从本地 `backend/.env` 读取。

## 本地配置

打开 `backend/.env`，填写：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_API_KEY=你的 DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOKENS=1600
```

注意：

- 不要把真实 `LLM_API_KEY` 写入文档或提交到公开仓库。
- 没有 Key 时项目仍可运行，但顶部状态会显示 LLM 为“演示”。
- Key 配置正确后，顶部状态会显示 LLM 为“已连接”。
- 如果账号暂未开放新模型，可以把 `LLM_MODEL` 改为 `deepseek-chat`。

## 连通性检查

后端启动后可以访问：

```text
GET http://127.0.0.1:8000/api/llm/ping
```

也可以在命令行执行：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_deepseek
```

返回 `ok: true` 表示 DeepSeek 已经能被项目调用。返回 `ok: false` 时，优先检查：

- `LLM_API_KEY` 是否填写。
- `LLM_BASE_URL` 是否为 `https://api.deepseek.com`。
- DeepSeek 账户余额和 Key 权限是否正常。
- 当前网络是否能访问 DeepSeek API。

## 智能体中的使用位置

DeepSeek 当前参与两个关键节点：

- 意图识别与槽位抽取：把用户自然语言转为 `intent`、`slots`、`missing_slots`。
- 规划生成：综合本地攻略、联网结果、天气、铁路和地图工具结果，生成最终中文回答。

如果 DeepSeek 不可用：

- 意图识别会切到本地规则。
- 行程规划会切到稳定模板。
- RAG、天气、地图、12306 MCP 和攻略入库能力仍然可用。

## 答辩说明建议

答辩时可以这样描述：

> 项目将 DeepSeek 封装为 OpenAI-compatible LLM 服务，接入 LangGraph 智能体节点，用于意图识别、槽位抽取和最终规划生成。为了保证课堂演示稳定，系统实现了无 Key 和接口异常时的规则兜底，外部大模型失败不会导致应用不可用。
