# 12306 ModelScope MCP 接入说明

## 接入目标

TripSage Agent 使用 ModelScope 12306 MCP 为智能体提供铁路查询能力，包括车次、余票、站点、票价、换乘、经停等信息。项目只做查询参考，不支持购票、抢票、登录、支付、订单和乘客信息操作。

## 默认安全策略

真实 MCP 调用会启动外部 MCP 服务进程，属于高风险运行边界。因此项目默认：

```env
MCP_12306_ALLOW_LIVE=false
```

默认状态下：

- 不启动 `mcp-server-12306`。
- 不执行任何第三方 MCP 工具。
- 铁路查询返回结构稳定的演示兜底数据。
- 智能体仍能完整运行。

当你确认本机已安装并信任该 MCP 服务后，再手动改为：

```env
MCP_12306_ALLOW_LIVE=true
```

## 本地配置

`mcp_servers.json` 示例：

```json
{
  "mcpServers": {
    "12306": {
      "transport": "stdio",
      "command": "mcp-server-12306",
      "args": [],
      "env": {}
    }
  }
}
```

说明：

- `mcp-server-12306` 已写入后端 `pyproject.toml`，执行 `pip install -e backend` 后会安装到 `backend/.venv\Scripts`。
- 如果你仍想使用 ModelScope 页面给出的 `uvx mcp-server-12306` 写法，也可以把 `command` 改为 `uvx`、`args` 改为 `["mcp-server-12306"]`。
- 后端会自动解析 PATH 和项目虚拟环境中的可执行文件，优先使用本地已安装命令，避免运行时反复下载。

`.env` 配置：

```env
MCP_12306_ENABLED=true
MCP_12306_CONFIG_PATH=../mcp_servers.json
MCP_12306_SERVER_NAME=12306
MCP_12306_ALLOW_LIVE=false
MCP_12306_TIMEOUT_SECONDS=20
```

如果 ModelScope 页面要求 token 或额外环境变量，只写入本地 `mcp_servers.json` 的 `env` 字段，不写入文档或公开仓库。

## 连通性检查

后端启动后访问：

```text
GET http://127.0.0.1:8000/api/railway/ping
```

也可以命令行执行：

```bat
cd backend
.venv\Scripts\python.exe -m app.scripts.check_railway_mcp
```

返回说明：

- `ok: false` 且提示 `ALLOW_LIVE=false`：配置已识别，但安全开关未打开。
- `ok: false` 且提示配置占位符：需要检查 `mcp_servers.json`。
- `ok: true`：发现至少一个安全查询工具。

本机当前验证结果：

- 已发现 6 个安全查询工具：`query-tickets`、`query-ticket-price`、`search-stations`、`query-transfer`、`get-train-route-stations`、`get-train-no-by-train-code`。
- 已完成一次真实查询：杭州 -> 南京，日期 `2026-04-29`，MCP 返回真实候选车次并由后端归一化为前端字段。

## 工具白名单

允许关键词：

```text
query, train, station, ticket, transfer, price, route, stop,
查询, 车次, 站点, 车站, 余票, 票价, 换乘, 经停
```

阻断关键词：

```text
login, order, pay, captcha, grab, passenger, submit, cancel,
登录, 下单, 订单, 支付, 抢票, 候补下单, 乘客, 验证码
```

只有工具名和描述通过白名单检查后，智能体才会尝试调用。

## 智能体中的使用方式

当前 LangGraph 工作流在以下情况调用铁路工具：

- 用户明确询问高铁、火车、车次、余票、12306。
- 行程规划中同时存在出发地和目的地。

返回结果会进入：

- 最终回答的交通建议。
- 前端右侧“铁路”卡片。
- 前端右侧“工具链”调用记录。

后端归一化字段：

```json
{
  "train_no": "G1862",
  "from_station": "杭州东",
  "to_station": "南京南",
  "start_time": "09:10",
  "arrive_time": "10:45",
  "duration": "01:35",
  "seats": {
    "second_class": "有"
  }
}
```

## 产品级降级策略

铁路查询失败不应该让整次旅行规划失败。当前策略：

- 未找到配置：返回演示车次。
- 配置仍是占位符：返回演示车次。
- `ALLOW_LIVE=false`：返回演示车次并说明原因。
- MCP 工具发现失败：返回演示车次。
- MCP 工具调用失败：返回演示车次。

所有兜底结果都带有：

```json
{
  "fallback": true,
  "notice": "仅提供查询参考，不支持购票、抢票、登录或支付。"
}
```

## 产品边界

本项目永远不做：

- 登录 12306。
- 提交订单。
- 抢票或候补下单。
- 支付。
- 保存乘客信息。
- 读取验证码或绕过验证码。

这既是安全边界，也是产品可信度的一部分。
