# 流式输出与决策工作台设计

## 目标

TripSage Agent 不再只等待大模型一次性返回长文本，而是把智能体执行过程和最终规划结果拆成两层：

- 流式阶段进度：让用户看到智能体正在做什么。
- 结构化决策模块：把长文本规划拆成交通、雨天、强度、预算、风险等可视化判断。

## 后端流式接口

接口：

```text
POST /api/chat/stream
```

协议：

```text
text/event-stream
```

事件类型：

| event | 说明 |
| --- | --- |
| `start` | 会话已创建，返回 `conversation_id` |
| `stage` | 单个智能体节点开始或完成 |
| `result` | 最终完整 `ChatResponse` |
| `error` | 流式处理失败 |

阶段顺序：

```text
intent_slot
retrieval
web_search
weather
railway
route
planner
response
```

## 前端流式体验

前端使用 `fetch + ReadableStream` 消费 SSE，实时更新“实时调度”区域：

- 理解意图与抽取城市、日期、预算
- 检索本地攻略知识库
- 按检索模式补充联网资料
- 查询天气与出行风险
- 查询 12306 MCP 铁路候选
- 估算车站到核心景区通勤
- 调用 DeepSeek 生成规划表达
- 组装前端决策工作台

这样复杂问题即使需要几十秒，也不会让用户误以为后端无响应。

## 决策模块

`ChatResponse` 新增：

```json
{
  "decision_modules": [
    {
      "type": "transport",
      "title": "交通建议",
      "level": "good",
      "summary": "已查询到 20 条铁路候选",
      "points": ["优先选择白天到达、耗时短且二等座充足的车次。"],
      "meta": {
        "train_count": 20,
        "date": "2026-04-29"
      }
    }
  ]
}
```

当前模块：

| 类型 | 作用 |
| --- | --- |
| `transport` | 交通建议、铁路候选、站点通勤 |
| `rainy_day` | 雨天备选与室内外比例 |
| `intensity` | 行程强度和节奏 |
| `budget` | 预算提示和成本控制 |
| `risk` | 来源、实时性和出行风险 |

## 验证

已验证：

- `/api/chat/stream` 可推送阶段事件和最终结果。
- 前端构建通过。
- 后端测试覆盖决策模块结构。
- 复杂规划不会再因为前端 30 秒超时而误报“后端无响应”。
