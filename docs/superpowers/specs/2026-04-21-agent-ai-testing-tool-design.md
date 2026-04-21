# 自动化 Agent AI 测试工具 — 设计文档

- **日期**：2026-04-21
- **状态**：Draft（待实施计划）
- **语言**：Python 3.10+

---

## 1. 目标与定位

为对话式 AI 产品提供**批量 prompt 测试驱动层**：模拟人类通过 API 或 GUI（Web / Android）发送 prompt 并获取**完整保真**的响应，供**外部**评分模块消费。

### 1.1 核心职责

- 接收批量 prompt 测试样本（本地文件或 HTTP push）
- 按 sample 指定的模式（API / GUI Web / GUI Android）发送 prompt
- 采集完整、高保真的响应文本（支持长文本滑动拼接）
- 输出结构化结果给外部评分模块

### 1.2 非职责（明确不做）

| 能力 | 责任方 |
|---|---|
| Prompt 生成 | 外部模块 |
| 响应质量评分 | 外部模块 |
| iOS / macOS / Windows / Linux 原生 App 驱动 | 后续迭代（MVP 不做） |
| 内置 LLM-as-Judge | 不做 |
| 同批次混合模式 | 不做（一批次一种模式） |
| 多租户 / 权限系统 | 不做（简单登录认证即可） |
| 分布式任务队列 | MVP 不做（asyncio 够用） |

---

## 2. 参考项目与复用

| 参考项目 | 路径 | 复用要点 |
|---|---|---|
| APA-LLM | `/Users/b1ankj/Desktop/2026/q2/apa_llm/` | Retry 机制、StateTracker 模式、多规则响应解析 |
| Open-AutoGLM | `/Users/b1ankj/Desktop/2026/q2/Open-AutoGLM/` | ADB 设备抽象（`phone_agent/adb/`）、ActionMemory、设备工厂模式、多设备连接管理 |

---

## 3. 顶层架构

```
┌─────────────────────────────────────────────────────────────┐
│                   Web UI (React + AntD)                      │
│  [配置] [Profile 管理] [设备] [批次] [结果] [日志流]         │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│              FastAPI Server (Python)                         │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ HTTP API 层    │  │ WebSocket 层 │  │ 简单登录认证    │  │
│  │ /tests /batches│  │ 实时进度推送 │  │ (password/token)│  │
│  └───────┬────────┘  └──────┬───────┘  └─────────────────┘  │
│          │                  │                                │
│  ┌───────▼──────────────────▼────────────────────────────┐  │
│  │              Batch Scheduler / Task Queue              │  │
│  │            (asyncio.Queue + 并发控制)                  │  │
│  └───┬──────────────┬──────────────┬──────────────────────┘  │
│      │              │              │                          │
│  ┌───▼────┐   ┌────▼─────┐   ┌────▼────────┐               │
│  │  API   │   │  Web     │   │  Android    │   执行器       │
│  │ Driver │   │  Driver  │   │  Driver     │               │
│  │(OpenAI │   │(Playwrt) │   │(adb+u2)     │               │
│  │ compat)│   │          │   │             │               │
│  └───┬────┘   └────┬─────┘   └────┬────────┘               │
│      │             │               │                          │
│      └─────────────┴───────────────┘                          │
│                    │                                          │
│  ┌─────────────────▼──────────────────────────────────────┐  │
│  │     Response Extractor (DOM / UI tree / OCR / VLM)     │  │
│  │     Complete Detector (DOM stable / pixel stable)      │  │
│  │     Scroll Stitcher (长文本滑动拼接)                   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Device Pool (Android ADB) │ Profile Registry │ Logger │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Storage: SQLite (metadata) + FS (screenshots/logs)    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 模块边界

| 模块 | 职责 | 接口 |
|---|---|---|
| **API Server** | 暴露 HTTP/WebSocket 接口，处理鉴权、批次管理 | FastAPI router |
| **Scheduler** | 批次调度、并发控制、设备锁分配 | `run_batch(batch)` / `run_sample(sample)` |
| **Executor (API / Web / Android)** | 按 mode 驱动一次 sample 的完整流程 | `execute(sample, profile) -> SampleResult` |
| **Response Extractor** | 从目标 surface 抽取响应文本（多策略） | `extract(context) -> str` |
| **Complete Detector** | 判定"生成是否完成" | `wait_complete(context, timeout) -> bool` |
| **Scroll Stitcher** | Android 长文本滑动 + OCR 拼接 | `stitch(device, region) -> str` |
| **Device Pool** | Android 设备生命周期 | `acquire()` / `release()` |
| **Profile Registry** | Target profile 加载 / 校验 / 热更新 | `get(name)` / `reload()` |
| **Action Runner** | 执行 recovery_path / new_session_action 等脚本 | `run_actions(steps, context)` |
| **VLM Client** | OpenAI 兼容 VLM 调用（供 Action Runner 的 vlm_task step 和 GUI 驱动用） | `chat(messages) -> str` |

---

## 4. 数据模型

### 4.1 测试样本（Sample）

```json
{
  "id": "t_001",
  "prompts": ["帮我写一首关于春天的诗"],
  "mode": "gui_pc_web",
  "target_profile": "chatgpt_web",
  "new_session": true,
  "timeout_sec": 180,
  "retry": 2,
  "dry_run": false,
  "metadata": {"tag": "creative_writing"}
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | ✓ | – | 批次内唯一 |
| `prompts` | string[] | ✓ | – | 多轮就多个；单轮 1 个 |
| `mode` | `"api"` / `"gui_pc_web"` / `"gui_android"` | ✓ | – | 执行模式 |
| `target_profile` | string | ✓ | – | 引用预定义 profile 名字 |
| `new_session` | bool | – | `true` | false 表示接续上一个 sample 的会话 |
| `timeout_sec` | int | – | API=60 / GUI=180 | 单个 sample 超时 |
| `retry` | int | – | 2 | 失败重试次数（共尝试 retry+1 次） |
| `dry_run` | bool | – | `false` | true 只走流程不真发送 prompt |
| `metadata` | object | – | `{}` | 透传给结果，外部评分模块可用 |

### 4.2 批量文件格式

- **JSONL**：每行一个 sample（推荐，流式友好）
- **JSON**：`{"batch_name": "...", "samples": [...]}`
- **CSV**：字段扁平化；`prompts` 用 `\u241f` (Unit Separator) 分隔多轮；`metadata` 存 JSON 字符串

### 4.3 Target Profile Schema

Profile 存在独立 YAML 配置文件（Web UI 可编辑），按 `platform` 分三种：

#### 4.3.1 API 型

```yaml
chatgpt_api:
  platform: api
  api:
    base_url: "https://api.openai.com/v1"
    model: "gpt-4o"
    api_key_env: "OPENAI_KEY"   # 从环境变量读，不写死
    extra_headers: {}
    temperature: 0.7            # 可选
    max_tokens: 4096            # 可选
  multi_turn_mode: "history"    # history | single（多轮时是否携带历史）— 仅 API 型有效；GUI 型由 new_session 控制
```

#### 4.3.2 Web 型

```yaml
chatgpt_web:
  platform: web
  url: "https://chat.openai.com"
  browser:
    headless: false
    user_data_dir: "/path/to/chrome-profile"  # 持久化登录态
  ready_check:                  # 验证"当前是否在对话页"
    type: dom_selector
    selector: 'textarea[data-id="root"]'
    timeout_sec: 5
  recovery_path:                # 异常时恢复步骤（见 §4.4）
    - { action: goto, url: "https://chat.openai.com" }
    - { action: wait_for, selector: 'textarea[data-id="root"]', timeout_sec: 30 }
  input_selector: 'textarea[data-id="root"]'
  send_method:                  # 发送方式
    type: "keyboard"            # keyboard(按Enter) | click_button
    key: "Enter"
    # 或 type: "click_button", selector: 'button[data-testid="send-button"]'
  response_container_selector: 'div[data-message-author-role="assistant"]:last-child'
  new_session_action:           # new_session=true 时执行
    - { action: click, selector: 'button[aria-label="New chat"]' }
  complete_detection:           # 判定"生成完毕"
    type: dom_stable            # DOM 在 response_container 上稳定 N 秒
    stable_sec: 2
    max_wait_sec: 120
```

#### 4.3.3 Android 型

```yaml
wechat_bot_x:
  platform: android
  package: "com.tencent.mm"
  activity: ".ui.LauncherUI"    # 可选
  ready_check:
    type: ui_tree_contains
    text: "某某助手"             # 当前 UI 树里能找到这个文本就算就位
    timeout_sec: 5
  recovery_path:
    - { action: launch_app, package: "com.tencent.mm" }
    - { action: wait_sec, seconds: 2 }
    - { action: vlm_task, task: "找到并进入'某某助手'的对话界面" }
  input_locator:
    type: resource_id
    value: "com.tencent.mm:id/edit_text"
  send_button_locator:
    type: text
    value: "发送"
  response_extraction:
    method: ui_tree_then_ocr    # ui_tree_only | ocr_only | ui_tree_then_ocr
    response_container_locator:
      type: resource_id
      value: "com.tencent.mm:id/message_list"
    scroll_container_locator:   # 长文本时滑动这个容器
      type: resource_id
      value: "com.tencent.mm:id/message_list"
    latest_bubble_match:        # 如何识别"最新的 bot 回复气泡"
      type: last_child_with_class
      value: "android.widget.TextView"
  new_session_action:
    - { action: vlm_task, task: "点击右上角菜单，选择'清空聊天记录'" }
  complete_detection:
    type: pixel_stable          # 屏幕响应区域像素连续 N 秒不变
    stable_sec: 3
    max_wait_sec: 180
    # 或 type: ui_tree_stable, stable_sec: 2
```

### 4.4 Action 脚本（recovery_path / new_session_action 的通用表达）

Action script 是一串 step，按顺序执行。支持的 action 类型：

| Action | 参数 | 适用平台 | 说明 |
|---|---|---|---|
| `goto` | `url` | web | 跳转 URL |
| `click` | `selector` 或 `locator` | web/android | 点击元素 |
| `input` | `selector`/`locator`, `text` | web/android | 输入文本 |
| `wait_for` | `selector`/`locator`, `timeout_sec` | web/android | 等元素出现 |
| `wait_sec` | `seconds` | all | 固定等待 |
| `launch_app` | `package` | android | 启动 App |
| `kill_app` | `package` | android | 结束 App |
| `press_key` | `key`（HOME/BACK/ENTER） | android | 按键 |
| `swipe` | `from`, `to`, `duration` | android | 滑动 |
| `vlm_task` | `task`（自然语言） | web/android | VLM 自主执行任务（降级兜底） |

**原则**：脚本优先，`vlm_task` 作为降级兜底（当静态选择器/定位器失效时，用自然语言描述让 VLM 完成）。

### 4.5 结果（SampleResult）

```json
{
  "id": "t_001",
  "status": "done",
  "prompts_sent": ["帮我写一首关于春天的诗"],
  "responses": ["春风拂柳绿，..."],
  "duration_ms": 45230,
  "attempt_count": 1,
  "mode": "gui_pc_web",
  "target_profile": "chatgpt_web",
  "metadata": {"tag": "creative_writing"},
  "logs_dir": "logs/b_20260421_001/t_001/",
  "error": null
}
```

| `status` 值 | 含义 |
|---|---|
| `done` | 成功采集响应 |
| `failed` | 所有 retry 都失败 |
| `timeout` | 超时（也算一种失败，但单独标识） |
| `extraction_failed` | 发送成功但响应提取失败 |

### 4.6 批次 Summary

```json
{
  "batch_id": "b_20260421_001",
  "name": "chatgpt-creative-v1",
  "mode": "gui_pc_web",
  "total": 10,
  "done": 9,
  "failed": 1,
  "avg_duration_ms": 38420,
  "total_duration_ms": 412300,
  "started_at": "2026-04-21T10:00:00Z",
  "ended_at": "2026-04-21T10:06:52Z"
}
```

---

## 5. HTTP API 契约

所有 API 路径前缀 `/api/v1`。鉴权方式：`Authorization: Bearer <token>`（token 在 Web UI 登录后获取；支持 HTTP Basic 用户名密码作为兜底）。

### 5.1 单次测试（同步）

```
POST /api/v1/tests/sync
Authorization: Bearer <token>

Req:  { id, prompts[], mode, target_profile, new_session?, timeout_sec?, retry?, dry_run?, metadata? }
Resp 200: { ...SampleResult }
Resp 5xx: { error: "...", code: "..." }
```

### 5.2 单次测试（异步，推荐 GUI 长任务）

```
POST /api/v1/tests
Req:  { ...同上..., callback_url? }
Resp: { task_id, status: "queued" }

GET  /api/v1/tests/{task_id}
Resp: { task_id, status: "queued"|"running"|"done"|"failed", ...SampleResult fields }

Webhook:  POST {callback_url}  Body = SampleResult
```

### 5.3 批次

```
POST /api/v1/batches
Req (JSON):   { name, mode, concurrency?, target_profile_default?, samples: [...] }
Req (file):   multipart/form-data，file 为 JSONL/JSON/CSV，可带 form field: name, mode, concurrency, target_profile_default
Resp: { batch_id }

# target_profile_default: 若某 sample 未显式提供 target_profile，使用此默认值
# mode（批次级）：用于校验所有 sample 的 mode 必须一致；不一致则 400
# concurrency: 批次最大并发数，默认 1

GET  /api/v1/batches                   # 列表，分页
GET  /api/v1/batches/{batch_id}        # 含 summary + per-sample 状态
GET  /api/v1/batches/{batch_id}/results # 下载结果 JSONL 文件
POST /api/v1/batches/{batch_id}/cancel # 取消
```

### 5.4 Profile / 设备 / 配置

```
GET    /api/v1/profiles              # 列表
GET    /api/v1/profiles/{name}
POST   /api/v1/profiles              # 新建
PUT    /api/v1/profiles/{name}       # 更新
DELETE /api/v1/profiles/{name}
POST   /api/v1/profiles/{name}/validate  # 校验 YAML schema

GET    /api/v1/devices               # Android 设备列表
POST   /api/v1/devices/{serial}/connect
POST   /api/v1/devices/{serial}/disconnect

GET    /api/v1/config/vlm            # VLM 驱动模型配置
PUT    /api/v1/config/vlm
GET    /api/v1/config/defaults       # 全局默认值（超时/重试）
PUT    /api/v1/config/defaults
```

### 5.5 实时进度（WebSocket）

```
WS /api/v1/ws/batches/{batch_id}
推送消息类型：
  { type: "sample_start", sample_id, ... }
  { type: "sample_progress", sample_id, step, screenshot_url?, ... }
  { type: "sample_done", sample_id, result }
  { type: "batch_done", summary }
```

### 5.6 认证

```
POST /api/v1/auth/login   # { username, password } -> { token, expires_at }
POST /api/v1/auth/logout
```

---

## 6. 执行流程

### 6.1 批次执行

```
1. Scheduler 收到 batch:
   - 校验所有 sample 的 mode 一致
   - 校验所有 target_profile 存在且合法
   - 按 batch.concurrency（默认 1）决定并发数

2. GUI 模式：
   - 向 Device Pool 申请设备；无可用则排队
   - 每个设备上串行跑分配到它的 sample

3. API 模式：
   - 按 concurrency 并发起多个协程跑 sample

4. 每个 sample 跑完：
   - 写 SampleResult 到 SQLite 和 JSONL 文件
   - WebSocket 广播进度
   - 调用 webhook（如有）

5. 批次跑完：
   - 计算 summary
   - 广播 batch_done
   - 保留结果文件（永久，下见 §8.3）
```

### 6.2 单 sample 执行（GUI）

```
对每个 sample:
  attempts_left = retry + 1
  while attempts_left > 0:
    try:
      1. [new_session=true] 执行 profile.new_session_action
      2. 执行 profile.ready_check
      3. 失败 → 执行 profile.recovery_path → 再 ready_check → 仍失败则 raise
      4. 对每个 prompt in prompts:
         if dry_run:
           responses.append("[DRY RUN] would send: " + prompt)
           continue
         a. VLM/选择器 定位输入框 → 输入 prompt
         b. 按 send_method 发送
         c. Complete Detector 等响应生成完毕
         d. Response Extractor 抽取响应（可能涉及滚动拼接）
         e. responses.append(response)
      return SampleResult(status=done, ...)
    except TimeoutError:
      attempts_left -= 1
      if attempts_left > 0: 执行 recovery_path 重置状态
    except Exception as e:
      attempts_left -= 1
      if attempts_left > 0: 执行 recovery_path 重置状态
  return SampleResult(status=failed/timeout/extraction_failed, ...)
```

### 6.3 单 sample 执行（API）

```
1. 构造 OpenAI 兼容请求
2. 多轮：按 profile.multi_turn_mode 组织 messages 列表
3. 发起请求，超时按 timeout_sec
4. 记录响应到 responses[]
```

---

## 7. 响应读取策略（§核心保真度方案）

### 7.1 Web（DOM）
- Playwright 定位 `response_container_selector`
- 取 `.innerText` 或 `.textContent`
- 原文完美，无需滚动

### 7.2 Android（混合）
按 `response_extraction.method` 分支：

- **`ui_tree_only`**：`uiautomator dump` → 定位最新 bot 气泡节点 → 读 `text`。如果节点为空（WebView/自绘）→ 报错。
- **`ocr_only`**：滑动容器到最新位置 → 截图 `response_region` → PaddleOCR → 返回拼接文本。
- **`ui_tree_then_ocr`**（推荐）：先尝试 `ui_tree_only`，text 为空或明显不完整则降级 `ocr_only`。

### 7.3 长文本滚动拼接（Scroll Stitcher）
适用 Android OCR 场景：

```
1. 记录初始视口内容（OCR 得到 lines_0）
2. 向下滑动一屏（保留 overlap 行用于去重）
3. OCR 新视口得到 lines_i
4. 和上一视口的 lines 做字符串匹配，去除重叠部分
5. 继续滑动直到 complete_detector 说"底部不再变化"或触达 max_scroll
6. 拼接所有 lines，去重后返回
```

### 7.4 Complete Detection（生成完毕判定）

| 策略 | 适用 | 实现 |
|---|---|---|
| `dom_stable` | Web | MutationObserver 或轮询 `innerText`，稳定 N 秒 |
| `ui_tree_stable` | Android | 周期 dump UI 树，hash 稳定 N 秒 |
| `pixel_stable` | Android（兜底） | 截图 hash 稳定 N 秒 |
| `send_button_reenable` | Web（辅助） | 发送按钮由 disabled 变 enabled 表示完成 |

可组合，例：Web 用 `dom_stable + send_button_reenable` 双条件。

---

## 8. 存储与日志

### 8.1 SQLite 表结构（MVP）

```sql
-- 批次
CREATE TABLE batches (
  id TEXT PRIMARY KEY,
  name TEXT,
  mode TEXT,
  status TEXT,
  concurrency INT,
  total INT, done INT, failed INT,
  avg_duration_ms INT,
  started_at TEXT, ended_at TEXT,
  created_at TEXT
);

-- 样本结果
CREATE TABLE samples (
  id TEXT,
  batch_id TEXT,
  status TEXT,
  prompts_sent_json TEXT,
  responses_json TEXT,
  duration_ms INT,
  attempt_count INT,
  mode TEXT,
  target_profile TEXT,
  metadata_json TEXT,
  error TEXT,
  logs_dir TEXT,
  started_at TEXT, ended_at TEXT,
  PRIMARY KEY (batch_id, id)
);

-- Profiles
CREATE TABLE profiles (
  name TEXT PRIMARY KEY,
  platform TEXT,
  yaml_content TEXT,
  updated_at TEXT
);

-- 配置
CREATE TABLE configs (key TEXT PRIMARY KEY, value_json TEXT);

-- 用户（登录）
CREATE TABLE users (
  username TEXT PRIMARY KEY,
  password_hash TEXT,
  created_at TEXT
);
```

### 8.2 文件系统布局

```
<data_root>/
  db.sqlite
  profiles/           # YAML profile 文件（SQLite 是缓存/索引）
  logs/
    <batch_id>/
      <sample_id>/
        screenshots/  001.png, 002.png, ...
        actions.jsonl
        ui_tree_dumps/  (Android) *.xml
        meta.json
  results/
    <batch_id>.jsonl  # 批次聚合结果
  backups/
    2026-04-monthly.tar.gz
    ...
```

### 8.3 历史保留策略

- **SampleResult / Batch**：默认**永久保留**
- **详细日志（logs/）**：每 sample 可配开关；默认开
- **自动备份**：每月 1 号凌晨打包一次：`tar -czf backups/YYYY-MM-monthly.tar.gz db.sqlite results/ profiles/`（日志不进备份，太大；可手动备）
- **备份保留**：本地保留最近 12 份；超出手动处理

---

## 9. Web UI 设计

### 9.1 页面

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录 | 用户名 + 密码 |
| `/` | Dashboard | 最近批次、设备状态、配置概览 |
| `/batches` | 批次列表 | 分页、过滤（mode/status/date） |
| `/batches/new` | 新建批次 | 上传文件 or 填表；选 profile、concurrency |
| `/batches/:id` | 批次详情 | summary + sample 列表 + 实时进度（WS） |
| `/batches/:id/samples/:sid` | Sample 详情 | prompt/响应/耗时/截图序列/action 日志 |
| `/profiles` | Profile 列表 | 按 platform 分组 |
| `/profiles/:name` | Profile 编辑器 | YAML 编辑 + 校验 + 测试连通性按钮 |
| `/devices` | 设备管理 | Android 设备列表、连接/断开、标签 |
| `/config` | 配置中心 | VLM 模型配置、全局默认值 |

### 9.2 登录认证

- 单用户密码（初次启动通过环境变量 `ADMIN_USER` / `ADMIN_PASSWORD` 设置；不设则启动失败）
- 后续可多用户：登录后 token（JWT，24h 过期）
- 所有 `/api/v1/*` 除 `/auth/*` 外均需 token

### 9.3 关键交互

- **实时进度**：批次详情页通过 WebSocket 推送，每步骤更新当前截图预览
- **Profile 测试**：编辑页提供"发送一条测试 prompt"按钮，验证连通性
- **Dry run**：新建批次时勾选，整批走 dry_run

---

## 10. 技术栈选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.10+ | 两个参考项目都是 Python，复用最大 |
| Web 框架 | FastAPI | 原生 async、WebSocket、自动 OpenAPI |
| Web 自动化 | Playwright | DOM 抓取强，Chrome/Firefox/WebKit 都支持 |
| Android 自动化 | `uiautomator2` + `adb` | 复用 Open-AutoGLM 的设备抽象 |
| OCR | PaddleOCR | 中英文兼顾，本地部署 |
| VLM 客户端 | OpenAI SDK（兼容其他 API） | 标准化 |
| 前端 | React + Ant Design | 组件齐全，快速开发 |
| 打包 | Vite | 前端；Python 侧 `uv` / `poetry` |
| 任务队列 | `asyncio.Queue` + semaphore | MVP 规模（10 samples/批）够用 |
| 存储 | SQLite | 单文件、零运维、MVP 规模足够 |
| 容器化 | Docker（可选） | 便于服务器部署 |

---

## 11. 默认值（全局配置）

| 配置项 | 默认 |
|---|---|
| API 超时 | 60s |
| GUI 超时 | 180s |
| 重试次数 | 2（共 3 次尝试） |
| 并发数 | 1 |
| 详细日志 | 开 |
| DOM/UI 树稳定判定 | 2s |
| 像素稳定判定 | 3s |
| 截图保留 | 永久（随 logs） |
| JWT 过期 | 24h |

---

## 12. 错误处理

| 错误 | 策略 |
|---|---|
| 设备离线（执行中） | 标记该 sample failed，设备从池中移除，后续 sample 走其他设备或排队 |
| Profile 不存在 | 批次创建时就校验，不让进入执行 |
| `ready_check` 失败 → `recovery_path` 也失败 | sample failed，error 写明"recovery_path 执行失败在第 X 步" |
| VLM 调用失败（网络/超时） | 按驱动的重试策略（指数退避，最多 3 次） |
| 响应提取返回空 | 状态 `extraction_failed`，记录截图/UI 树快照供人工排查 |
| 批次中途中断（进程崩溃） | 重启时 SQLite 里 `running` 状态的 sample 标记为 failed + `error="server_restart"` |

---

## 13. 测试策略（工具本身的测试）

| 类型 | 内容 |
|---|---|
| 单元测试 | Scheduler 并发、Scroll Stitcher 去重逻辑、Profile Schema 校验、Action Runner |
| 集成测试 | 用 mock LLM server 和本地 HTML 页面跑 Web Executor 全流程；用 Android emulator 跑 Android Executor |
| E2E 测试 | 真实 OpenAI API 跑一个 sample；真实 Chrome + demo 聊天页跑一个 Web sample |
| 回归 | 提供一组 fixture 批次，每次发版前跑一遍，核对 summary |

---

## 14. 实施优先级（供实施计划参考）

**P0 — MVP 核心（第一版能用）**
1. 项目骨架（FastAPI + React 空壳）
2. API 模式 Executor（最简单，先跑通）
3. 批次调度器 + SQLite 存储
4. 本地 JSONL 批量文件加载
5. 简单登录认证
6. Web UI 最小界面（登录/新建批次/查看结果）

**P1 — 扩展能力**
7. Web GUI Executor（Playwright + DOM 抽取 + 完成检测）
8. Target Profile 系统 + YAML 校验 + UI 编辑器
9. HTTP API 的同步/异步双模式 + webhook
10. 实时 WebSocket 进度
11. Dry-run 模式

**P2 — Android 支持（工作量最大）**
12. Device Pool + 多设备管理
13. Android Executor（uiautomator2）
14. UI 树抽取 + OCR 兜底
15. Scroll Stitcher（长文本拼接）
16. Android Recovery Path + vlm_task step

**P3 — 运维增强**
17. 月度自动备份
18. Profile 测试连通性按钮
19. 日志开关与清理
20. Docker 打包

---

## 15. 风险与未决项

### 15.1 风险

| 风险 | 缓解 |
|---|---|
| Android 应用自绘文本（UI 树拿不到） | 降级 OCR；profile 里显式声明 `ocr_only` |
| 长响应滑动拼接去重不准 | 多版本策略（N-gram 重叠、最长公共子串），可配 |
| Web 目标有 Cloudflare / 验证码 | `user_data_dir` 持久化登录态；必要时人工介入；`vlm_task` 提示人工 |
| VLM 调用费用 / 速率限制 | 缓存 + 速率限制；profile 里可切用哪个 VLM |
| 并发 GUI 导致设备干扰 | 设备池严格锁，每 sample 独占 |

### 15.2 后续可做（明确不放 MVP）

- iOS / macOS / Windows / Linux 原生 App 支持
- 可视化录制 Profile（录一遍生成 action 脚本）
- 分布式调度（Celery + Redis）
- 多租户 / 细粒度权限
- Profile market / 社区分享
- AI 辅助 profile 推断（看截图自动生成选择器）

---

## 16. 验收标准（MVP 完成的定义）

1. 用户可通过 Web UI 登录
2. 可上传 JSONL 文件创建批次（mode=api），全部跑通并下载结果
3. 可通过 HTTP API 同步 / 异步发起单 sample 测试
4. 可创建 Web 模式 target profile，跑 ChatGPT 网页 demo 能拿到完整回复
5. 可连接一台 Android 设备，跑一个简单微信对话 profile，拿到回复（含滑动拼接长文本）
6. 失败自动重试，超时标记失败，不中断整批次
7. 批次 summary 正确，JSONL 结果文件完整

---

**文档结束**
