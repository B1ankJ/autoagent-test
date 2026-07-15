# AutoAgent Test

批量测试对话式 AI 产品的自动化测试平台，支持 API、Web GUI、Android GUI 和 Agent 四种执行模式，内置 React + TypeScript 管理界面。

## 功能

- **多种执行模式**：API 调用、Playwright Web GUI、Android uiautomator2 GUI、AI Agent PC/Android 自主操作
- **批量测试**：JSONL/JSON/CSV 文件上传，并发调度，结果实时流式更新（SSE）
- **Profile 系统**：YAML 配置文件定义目标应用，支持 Android Profile Builder 向导
- **设备管理**：Android 设备池、ADB Keyboard 一键安装/切换、设备画面实时直播与远程操作
- **结果分析**：截图索引、动作日志、LLM 回复提取、JSONL 结果下载
- **告警通知**：钉钉机器人告警（设备离线、疑似卡死/同响应异常）
- **运维**：批次自动清理与归档、支持一键自更新（自托管场景可选开启）

## 快速开始

**前提**：git、curl、联网。其余依赖自动安装。

```bash
git clone <repo-url>
cd AutoAgentTest
bash install.sh
```

安装脚本将：

1. 安装 Python 3.11、Node.js、ADB、uv、pnpm（已安装则跳过）
2. 安装 Python 和前端依赖
3. 下载 Playwright Chromium
4. 交互式配置管理员密码，自动生成 `.env`

脚本结束时打印启动命令。

**支持平台**：macOS（Homebrew）、Ubuntu/Debian（apt + deadsnakes PPA）、RHEL/Fedora（dnf）

## 手动安装

```bash
# Python 依赖
uv sync --python 3.11

# 前端构建
cd web && pnpm install && pnpm build && cd ..

# Playwright（gui_pc_web 模式需要）
python3.11 -m playwright install --with-deps chromium

# 配置
cp .env.example .env  # 填写 ADMIN_PASSWORD 和 JWT_SECRET

# 可选：配置长期 Bearer key
# STATIC_API_KEY=your-long-lived-key
```

## 启动服务

```bash
source .venv/bin/activate
python3.11 -m uvicorn --app-dir src autoagent.main:app --host 0.0.0.0 --port 8000
```

管理员账号在首次启动时从 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 自动创建。

健康检查：`curl http://localhost:8000/health`

Web UI：`http://localhost:8000`

## 执行模式

| 模式 | 说明 | Profile 类型 |
|---|---|---|
| `api` | OpenAI-compatible API 调用 | `platform: api` |
| `gui_pc_web` | Playwright 浏览器 GUI | `platform: web` |
| `gui_android` | Android uiautomator2 GUI | `platform: android` |
| `agent_pc` | AI Agent 自主操作桌面 | `platform: agent_pc` |
| `agent_android` | AI Agent 自主操作 Android | `platform: agent_android` |

## Profile 配置

Profile 是 YAML 文件，存放在 `data/profiles/<name>.yaml`。

**API Profile 示例：**

```yaml
name: my_api
platform: api
base_url: https://api.openai.com/v1
model: gpt-4o
api_key: sk-...
```

**Android Profile 示例：**

```yaml
name: my_app
platform: android
package: com.example.app
activity: .MainActivity
input_locator:
  type: resource_id
  value: com.example.app:id/input
send_button_locator:
  type: resource_id
  value: com.example.app:id/send
response_extraction:
  method: ui_tree_only
  response_container_locator:
    type: resource_id
    value: com.example.app:id/messages
  scroll_container_locator:
    type: resource_id
    value: com.example.app:id/messages
  latest_bubble_match:
    type: last_child_with_class
    value: android.widget.TextView
  copy_button_text: "复制"   # 可选：若 AI 回复旁有复制按钮，填入按钮文字可提升提取准确率
complete_detection:
  type: ui_tree_stable
  stable_sec: 2
  max_wait_sec: 180
post_send_wait_sec: 10.0
new_session_wait_sec: 3.0
```

**Agent Profile 示例：**

```yaml
name: my_agent
platform: agent_pc
base_url: https://api.openai.com/v1
model: gpt-4o
api_key: sk-...
task_template: "在聊天框中输入「{prompt}」并发送，等待回复"
response_hint: "最新的 AI 回复内容"
max_steps: 20
```

Android Profile Builder（`Profiles → Build Profile`）可通过界面向导自动生成 Android profile。

## 批量测试

### 创建批次（Web UI）

1. 进入 `Batches → 新建批次`
2. 选择执行模式和 Profile
3. 填写 Samples 或上传文件

### 批量文件格式

**JSONL（推荐）：**

```jsonl
{"id": "t1", "prompts": ["你好"], "mode": "api", "target_profile": "my_api"}
{"id": "t2", "prompts": ["hi", "再问一个"], "mode": "api", "target_profile": "my_api", "new_session": false}
```

**JSON：** 同上 objects 的列表，或 `{"samples": [...]}`

**CSV：** 列名 `id,prompts,mode,target_profile,new_session`，多轮 prompts 用 `\u241f` 分隔

### API 直接调用

```bash
# 登录
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<密码>"}' | jq -r .token)

# 单次同步测试
curl -X POST http://localhost:8000/api/v1/tests/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["hello"],"mode":"api","target_profile":"my_api"}'

# 创建批次
curl -X POST http://localhost:8000/api/v1/batches \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"test","mode":"api","concurrency":2,"target_profile_default":"my_api","samples":[...]}'
```

如果配置了 `STATIC_API_KEY`，也可以直接使用长期 Bearer key，不必先登录：

```bash
curl -X POST http://localhost:8000/api/v1/tests/sync \
  -H "Authorization: Bearer $STATIC_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["你好，介绍一下自己"],"mode":"gui_android","target_profile":"nxb","new_session":false}'
```

## OpenAI-compatible single test

用户也可以通过 OpenAI-compatible 同步接口调用 AutoAgent：

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<密码>"}' | jq -r .token)
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key=TOKEN,
)

resp = client.chat.completions.create(
    model="my_profile",
    messages=[{"role": "user", "content": "你好"}],
    extra_body={          # SDK 会将 extra_body 展开到请求顶层
        "new_session": True,
        "timeout_sec": 120,
        "retry": 1,
        "dry_run": False,
    },
)

print(resp.choices[0].message.content)
```

> **注意**：`extra_body` 是 OpenAI Python SDK 的客户端参数，SDK 会自动将其展开到 HTTP 请求体的顶层。直接用 `curl` 时，应将这些字段写在 JSON 顶层，不要包含 `extra_body` 键：
>
> ```bash
> curl http://localhost:8000/v1/chat/completions \
>   -H "Content-Type: application/json" \
>   -H "Authorization: Bearer $TOKEN" \
>   -d '{"model":"my_profile","messages":[{"role":"user","content":"你好"}],"new_session":true,"timeout_sec":120}'
> ```

如果服务端配置了 `STATIC_API_KEY`，OpenAI SDK 也可以直接使用这个长期 key：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-long-lived-key",
)
```

注意：

- `model` 会映射到 AutoAgent 的 `target_profile`
- v1 仅使用最后一条 `user` 消息
- v1 不支持 `stream=true`
- 当 profile 启用了 LLM response extraction 时，AutoAgent 会优先使用 `llm_responses`，提取失败时回退到静态 `responses`
- `STATIC_API_KEY` 和 JWT 可以并存；静态 key 会以 `admin` 身份通过 Bearer 鉴权

## Android 使用

### 前提

```bash
# 确认设备在线
adb devices
```

Android 模式需要连接物理设备或模拟器。`install.sh` 已自动安装 ADB。

### ADB Keyboard

非 ASCII 输入需要 ADB Keyboard IME。进入 Web UI `Devices` 页面：

- 点击 **Install ADB Keyboard** 一键安装（APK 已内置于 `src/autoagent/fixtures/ADBKeyboard.apk`）
- 点击 **Enable IME** 启用

运行时自动切换到 ADB Keyboard 处理非 ASCII 输入，结束后恢复原 IME。

### Android Profile Builder

`Profiles → Build Profile` 提供向导式 profile 生成：

1. 选择设备和应用
2. 截取空闲状态（有 AI 回复可见，输入框未聚焦）
3. 截取编辑状态（输入框已聚焦）
4. 生成草稿，逐项 Review 候选
5. 连通性验证后保存

### 设备画面直播

`Devices` 页面点击设备行的**查看画面**可打开实时画面弹窗：后端通过 `adb exec-out screenrecord` 推流 H264，前端用浏览器原生 WebCodecs 解码渲染（需 Chrome 94+），支持点击、滑动、输入文本、系统按键（返回/Home/最近任务）远程操作设备，用于调试 profile 或直接排查设备状态，无需 `scrcpy` 等外部工具。

## 告警通知（钉钉）

`Config → 通知` 页面可配置钉钉自定义机器人 webhook，开启后有两条独立规则：

1. **设备离线告警**：设备从在线变为离线/丢失时报警，恢复在线时再报一次；计划内重启（如设备初始化流程触发的重启）不会误报。
2. **同响应异常告警**：同一 (device, profile) 连续 N 次返回完全相同的响应时，调用全局 VLM 判断截图是否仍是正常的对话页面——不正常才报警（正常则加入白名单，避免固定文案反复误报）；可选在报警后自动对该设备重跑 profile 的初始化流程。

支持 @手机号 / @所有人，以及把报警中的 sample 引用变成可点击的 Web UI 链接（需配置 `app_base_url`）。白名单可在同一页面查看和移除。

## 批次维护

`Config → 默认值` 页面可配置：

- `log_retention_days`：后台任务每 24 小时清理超过该天数的截图/日志/Profile Builder 产物（0 = 关闭）
- `archive_retention_days`：批次被清理前先打包为 `data/archive/<batch>.zip`（结果 + 日志 + DB 快照），0 = 不归档、直接删除

等价的手动 CLI 见下方「日志清理」。

## Agent 模式

Agent 模式使用视觉 AI 模型（需 OpenAI-compatible 视觉 API）自主操控界面：

- **agent_pc**：截图 macOS/Windows 桌面，AI 决策点击/输入动作
- **agent_android**：截图 Android 屏幕（via ADB），AI 决策触控动作

每步截图保存在日志目录，可在 SampleDetail 页面逐步回放。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `admin123456` | 管理员密码（**生产必须修改**） |
| `JWT_SECRET` | `dev-secret-...` | JWT 签名密钥（**生产必须修改**，≥32字符） |
| `STATIC_API_KEY` | - | 可选的长期 Bearer key；配置后所有 Bearer 鉴权接口都接受它 |
| `DATA_ROOT` | `./data` | 数据库和 profile 存储路径 |
| `LOGS_ROOT` | `./logs` | 截图和执行日志路径 |
| `PORT` | `8000` | 服务端口 |

## API 参考

OpenAPI 文档：`http://localhost:8000/docs`

主要端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/login` | 登录获取 JWT |
| POST | `/api/v1/tests/sync` | 单次同步测试 |
| POST | `/api/v1/tests` | 单次异步测试 |
| GET | `/api/v1/tests/{task_id}` | 轮询异步结果 |
| POST | `/api/v1/batches` | 创建批次（JSON） |
| POST | `/api/v1/batches/upload` | 创建批次（文件） |
| GET | `/api/v1/batches/{id}` | 批次详情 |
| GET | `/api/v1/batches/{id}/events` | 批次进度 SSE 流 |
| GET | `/api/v1/batches/{id}/results` | 下载 JSONL 结果 |
| POST | `/api/v1/batches/{id}/cancel` | 取消批次 |
| POST | `/api/v1/batches/{id}/rerun` | 用默认配置重跑失败/全部样本 |
| POST | `/api/v1/batches/{id}/replay` | 用原始提交配置逐字重放 |
| GET | `/api/v1/profiles` | Profile 列表 |
| GET/PUT/DELETE | `/api/v1/profiles/{name}` | Profile CRUD |
| GET | `/api/v1/devices` | Android 设备列表 |
| GET | `/api/v1/devices/{serial}/stream` | 设备画面直播（WebSocket） |
| POST | `/api/v1/devices/{serial}/input` | 远程操作设备（点击/滑动/输入/按键） |
| GET/PUT | `/api/v1/config/vlm` | VLM 配置 |
| GET/PUT | `/api/v1/config/defaults` | 默认值 + 日志/归档保留策略 |
| GET/PUT | `/api/v1/config/notifications` | 钉钉告警配置 |
| GET | `/api/v1/config/notifications/whitelist` | 同响应白名单 |
| POST | `/api/v1/system/update/check` \| `/apply` | 检查/执行自更新（需先开启 `self_update_enabled`） |
| POST | `/v1/chat/completions` | OpenAI-compatible 单次测试（见上文） |

## 开发

```bash
# 测试
python3.11 -m pytest -q                                              # 全量
python3.11 -m pytest -q -m "not playwright and not android and not slow"  # 快速套件

# Lint / Format
python3.11 -m ruff check .
python3.11 -m ruff format .

# 前端
cd web && pnpm dev    # 开发服务器（:5173，代理 API 到 :8000）
cd web && pnpm test   # 前端测试
cd web && pnpm build  # 构建到 src/autoagent/static/
```

### 日志清理

```bash
python3.11 scripts/cleanup_runtime_artifacts.py --days 7          # 预览
python3.11 scripts/cleanup_runtime_artifacts.py --days 7 --apply  # 删除
python3.11 scripts/cleanup_runtime_artifacts.py --all --apply     # 全清
```

## 架构

```
src/autoagent/
  api/            FastAPI 路由（auth、profiles、tests、batches、config、devices、device_stream、
                  media、system、openai_compat、profile_builder）
  auth/           JWT + 密码哈希 + 长期 Bearer key（bearer.py）+ FastAPI deps
  config/         Pydantic Settings（env 配置）
  devices/        adb 封装、设备池（并发安全的设备占用/释放）、在线状态监控、设备初始化
  events/         进程内异步事件总线（批次 SSE 进度）
  executors/      执行器：API、Web、Android、Agent PC/Android，及配套的截图、OCR、回复提取、
                  Profile Builder 生成、agent_core 运行时等支撑模块
  loaders/        JSONL/JSON/CSV 批量文件加载
  maintenance/    定时运行时清理 + 批次自动保留/归档
  models/         Pydantic API schema + SQLAlchemy ORM
  notifications/  钉钉 webhook 发送 + 告警规则（同响应异常、设备离线）+ 白名单
  openai_compat/  `/v1/chat/completions` 的请求/响应模型与映射逻辑
  profiles/       Profile schema（discriminated union）+ YAML 注册表
  results/        每批次一个 JSONL 结果文件（线程安全追加写）
  scheduler/      BatchScheduler（异步，设备池）
  services/       内部接口与 OpenAI 兼容接口共用的业务逻辑
  storage/        SQLAlchemy CRUD（SQLite + aiosqlite）
  system/         自更新（git pull + uv sync + pnpm build + 平滑重启）
  utils/          环境变量展开、HTTP 重试、日志配置
  webhooks/       Webhook 回调（指数退避）
  main.py         FastAPI app + lifespan
tests/
  unit/           单元测试
  integration/    集成测试（httpx AsyncClient）
web/              React + TypeScript + AntD 5（Vite）
```

## 许可

内部使用。
