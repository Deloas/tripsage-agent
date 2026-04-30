# 14. 中国旅行图片资产计划

## 1. 目标

前端需要图片提升旅行项目的真实感和高级感，但图片必须服务于“旅行决策驾驶舱”，不能变成普通旅游营销页。

所有图片必须基于中国旅行语境：

- 中国城市街巷
- 中国高铁
- 江南雨天
- 中国地图与行程计划
- 西南山城或古城

## 2. 资产清单

| 文件名 | 用途 | 建议比例 |
| --- | --- | --- |
| `jiangnan-lane.jpg` | 左侧规划面板顶部视觉 | 16:9 |
| `china-rail-window.jpg` | 右侧铁路洞察面板 | 16:9 |
| `rainy-suzhou-street.jpg` | 天气风险和雨天备选 | 4:3 |
| `china-map-planning.jpg` | 工具链、空状态、规划说明 | 16:9 |
| `southwest-city-travel.jpg` | 目的地推荐卡片 | 4:3 |

保存目录：

```text
frontend/public/assets/
```

## 3. 统一风格

```text
高级旅行杂志摄影感，中国城市真实语境，柔和自然光，克制色彩，
无文字，无水印，无 Logo，无可识别真实人物，适合 Web UI 裁剪。
```

## 4. 生成提示词

### 4.1 江南水乡街巷

```text
Use case: photorealistic-natural
Asset type: web application visual card, 16:9
Primary request: A refined editorial travel photograph of a Jiangnan water-town lane in China, narrow stone path, white walls, dark tiled roofs, small canal edge, early morning soft light, calm local atmosphere.
Scene/backdrop: Chinese Jiangnan old-town street, subtle greenery, no tourist crowd.
Composition: wide horizontal crop, clean negative space on the left for UI overlay, cinematic but realistic.
Style: premium travel magazine photography, natural colors, gentle contrast.
Avoid: text, watermark, logo, foreign architecture, identifiable faces, fantasy elements.
```

### 4.2 中国高铁车窗

```text
Use case: photorealistic-natural
Asset type: web application insight card, 16:9
Primary request: A quiet Chinese high-speed rail travel scene seen from inside a modern train carriage, window view of Chinese countryside and city edge passing by, clean seat silhouette, calm morning light.
Scene/backdrop: China high-speed railway context, modern and realistic.
Composition: horizontal crop, window line creates a strong travel direction, right side suitable for UI overlay.
Style: refined documentary travel photography, polished but not commercial.
Avoid: text, ticket numbers, brand logos, identifiable passengers, foreign trains.
```

### 4.3 雨天苏州街区

```text
Use case: photorealistic-natural
Asset type: weather risk visual, 4:3
Primary request: A rainy street in Suzhou, China, wet stone pavement, traditional white wall and dark roof, soft reflections, umbrellas implied but no identifiable people.
Scene/backdrop: Jiangnan city street after rain, quiet and atmospheric.
Composition: medium-wide crop, foreground wet pavement, background lane depth.
Style: elegant travel editorial, muted jade, ink, warm lantern hints.
Avoid: text, watermark, neon cyberpunk, foreign street signs, visible faces.
```

### 4.4 中国地图与旅行计划桌面

```text
Use case: product-mockup
Asset type: planning workspace visual, 16:9
Primary request: A tasteful travel planning desk with a printed map of eastern China, high-speed rail route lines, notebook, pen, train ticket-like paper shapes without readable text, cup of tea.
Scene/backdrop: warm desk near window, Chinese travel planning mood.
Composition: top-down or slight angled view, organized and premium, enough quiet space for UI crop.
Style: refined product photography, natural paper texture, calm colors.
Avoid: readable text, real ticket details, logos, passports, payment cards.
```

### 4.5 西南山城或古城旅行氛围

```text
Use case: photorealistic-natural
Asset type: destination recommendation card, 4:3
Primary request: A Chinese southwest mountain city travel atmosphere, layered hillside streets, warm evening light, traditional roofs mixed with modern city texture, realistic and inviting.
Scene/backdrop: Chongqing or western China inspired urban hillside, no specific landmark branding.
Composition: medium-wide city view, depth and layers, suitable for card crop.
Style: premium travel magazine, warm but restrained, cinematic realism.
Avoid: text, watermark, fantasy skyline, foreign architecture, identifiable people.
```

## 5. 接入方式

生成后更新 CSS：

```css
:root {
  --asset-jiangnan-lane: url("/assets/jiangnan-lane.jpg");
  --asset-china-rail-window: url("/assets/china-rail-window.jpg");
}
```

## 6. 验收标准

- 图片背景明确是中国旅行场景。
- 无文字、水印、Logo。
- 不出现可识别真实人物。
- 裁剪到前端卡片后主体仍清楚。
- 不影响文字对比度和可读性。
