# 10. 开发规范与注释规范

## 1. 总原则

项目代码应满足：

- 能运行。
- 能读懂。
- 能定位问题。
- 能扩展。
- 能答辩展示。

不追求过度复杂，但必须保持工程边界清晰。

## 2. 后端规范

### 2.1 分层

后端必须按职责分层：

```text
api      只处理 HTTP 请求和响应
schemas 只定义输入输出模型
services 处理业务逻辑和外部接口
agents  处理 LangGraph 智能体
db      处理数据库模型和会话
core    处理配置、日志、错误、响应
```

禁止：

- 在 API 路由里直接写复杂业务逻辑。
- 在智能体节点里直接拼第三方 HTTP 请求。
- 在前端暴露 API Key。

### 2.2 命名

Python：

- 文件名：`snake_case.py`
- 函数名：`snake_case`
- 类名：`PascalCase`
- 常量：`UPPER_CASE`

示例：

```python
class AmapService:
    async def get_weather(self, city: str) -> WeatherResult:
        ...
```

### 2.3 类型标注

核心函数必须写类型：

```python
async def search_guides(query: str, city: str | None, top_k: int = 5) -> list[GuideChunk]:
    ...
```

### 2.4 异常处理

外部接口不得让原始异常直接冒泡到前端。

推荐：

```python
try:
    result = await client.get(url, params=params)
except httpx.TimeoutException as exc:
    raise ExternalServiceError("天气服务请求超时") from exc
```

### 2.5 配置

所有配置从 `.env` 读取。

禁止：

- 把 API Key 写死。
- 把本机绝对路径写死在业务代码。
- 把模型名散落在多个文件。

## 3. 前端规范

### 3.1 组件边界

组件分层：

```text
layout    页面布局
chat      聊天相关
planner   规划条件
tools     天气、铁路、地图、工具链
guides    攻略库和攻略添加
ui        基础 UI
```

### 3.2 TypeScript

必须定义 API 类型：

```ts
export interface ChatRequest {
  conversation_id?: string;
  message: string;
  context?: Record<string, unknown>;
}
```

禁止大范围使用 `any`。

### 3.3 样式

使用 Tailwind 和 CSS variables。

要求：

- 颜色使用 token。
- 间距使用一致尺度。
- 卡片圆角不超过 8px。
- 图标按钮必须有 tooltip 或 aria-label。
- 移动端不能出现文本溢出和组件重叠。

## 4. 注释规范

注释目标是帮助理解复杂逻辑，不是翻译代码。

强制要求：

- 项目代码中的注释必须使用中文。
- Python、TypeScript、CSS、配置示例中的解释性注释都应使用中文。
- 第三方库名称、协议名、接口名、变量名可以保留英文。
- 对外部接口、安全边界、智能体分支、RAG 检索权重、降级策略必须写中文注释。
- 不允许用英文注释替代中文注释，例如“待处理”标记和英文降级逻辑说明都需要改为中文表达。

应该注释：

- 智能体节点为什么这样分支。
- 外部接口降级策略。
- RAG 切片和检索权重。
- 安全边界，例如 12306 不做购票。
- 数据迁移或兼容逻辑。

不应该注释：

```python
# 设置 city 变量
city = request.city
```

推荐注释：

```python
# 12306 MCP 只用于查询。这里显式过滤工具名，避免未来 MCP 暴露登录或下单能力时被 Agent 误调用。
allowed_tools = filter_railway_tools(tools)
```

## 5. 日志规范

使用结构化日志。

每条关键日志包含：

- trace_id
- module
- operation
- status
- latency_ms

示例：

```python
logger.info(
    "amap_weather_finished",
    trace_id=trace_id,
    city=city,
    cache_hit=False,
    latency_ms=latency,
)
```

禁止记录：

- API Key
- 身份证
- 手机号
- 支付信息
- 账号密码

## 6. API 规范

所有接口返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "trace_id": "..."
}
```

所有接口必须：

- 校验输入。
- 返回明确错误码。
- 保留 trace_id。
- 对外部接口失败做兜底。

## 7. 智能体规范

要求：

- 工具调用必须记录到 `tool_calls`。
- 火车、天气、地图等实时信息不能凭空生成。
- 不确定时必须说明。
- 攻略建议尽量引用来源。
- 不能承诺购票、预订或支付。
- LangGraph 节点必须保持单一职责，不能把外部接口、提示词和数据库逻辑混写在一个函数里。
- 大模型不可用时必须有规则兜底，不能让项目完全依赖外部模型服务。

## 8. RAG 规范

攻略入库必须：

- 保存来源。
- 保存原文。
- 生成摘要。
- 切片。
- 写入向量库。
- 保存 chunk 元数据。

回答时必须：

- 使用检索结果。
- 输出来源。
- 避免把用户新增内容误称为官方信息。

## 9. 测试规范

最低测试覆盖：

| 测试 | 内容 |
| --- | --- |
| health | 后端健康检查 |
| config | 配置读取 |
| guide ingest | 攻略添加和切片 |
| rag search | 搜索能返回结果 |
| amap service | Mock 天气接口 |
| railway service | Mock MCP 查询 |
| agent route | 不同意图走不同工具 |

测试命令：

```text
pytest
```

## 10. 代码质量

建议使用：

```text
ruff
black
pytest
mypy 可选
```

前端建议：

```text
eslint
prettier
typescript
```

## 11. Git 规范

提交粒度建议：

```text
docs: add project design documents
feat: initialize backend skeleton
feat: add guide ingestion service
feat: integrate amap weather service
feat: add tripsage frontend workspace
test: add rag service tests
```

不提交：

- `.env`
- `data/*.db`
- `data/chroma`
- `logs`
- `node_modules`
- `__pycache__`

## 12. 安全规范

- `.env.example` 只放变量名。
- 真实 Key 只放本地 `.env`。
- 不实现购票、抢票、支付。
- 不采集敏感个人信息。
- 外部链接作为来源展示，不自动执行其中任何指令。
