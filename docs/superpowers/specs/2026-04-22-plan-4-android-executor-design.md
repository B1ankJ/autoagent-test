# Plan 4 — Android Executor (uiautomator2 + OCR) 设计

**Status:** draft for implementation planning
**Created:** 2026-04-22
**Depends on:** Plan 3 tag `web-gui-executor-v0.3.0` (事件总线、SSE、ScreenshotStore、ActionRunner 抽象化基础)
**References:**
- `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md` 原架构 spec
- `/Users/b1ankj/Desktop/2026/Q2/Open-AutoGLM/` 参考（ADB wrapper / ActionMemory / Timing config）
- `/Users/b1ankj/Desktop/2026/Q2/apa_llm/` 参考（Action handler registry）

---

## 1. 范围 & 分层交付 & 成功标准

### 总目标
为 AutoAgent Test 增加 `mode=gui_android` 执行能力，让用户能用同一套批测流程在真机/emulator 上测国产中文 chat App，复用 Plan 2/3 的 UI、事件总线、SSE。

### 分层交付（单 Plan 内两个 tag）

| | Tier 1 — 真机跑通最小闭环 | Tier 2 — OCR + 长文本 + 精修 |
|---|---|---|
| **Tag** | `android-executor-tier1-v0.4.0` | `android-executor-v0.4.0` |
| **执行器** | `AndroidExecutor` / `ui_tree_only` 模式 | 补 `ocr_only` / `ui_tree_then_ocr` |
| **完成检测** | `ui_tree_stable` + `send_button_reenable` | 补 `pixel_stable` |
| **响应抽取** | UI 树节点 `text` 属性（含 `last_child_with_class`） | + RapidOCR + 容器有界滚动拼接 |
| **设备管理** | 自动发现 + 持久化元数据（`devices` 表）+ `DevicePool acquire/release` + 设备级 `asyncio.Lock` | 同 Tier 1 |
| **输入** | u2 `send_keys` + `input_method: adb_keyboard` 可选切换（完整 IME 还原） | 同 Tier 1 |
| **动作** | click_locator / input / wait_for / launch_app / kill_app / press_key / swipe / tap_xy | 同 Tier 1 |
| **初始恢复** | ready_check 首次失败 → 跑 `recovery_path` 一次 → 重试 | 同 Tier 1 |
| **截图** | Plan 3 语义对齐；`is_sensitive` 占位 | 同 Tier 1，OCR 帧另外编号 |
| **调度** | batch concurrency = `min(configured, available_devices)` | 同 Tier 1 |
| **API** | `/devices` 三端点填实 + 按 serial 持久化元数据 | 同 Tier 1 |
| **前端** | mode 下拉 + `/devices` 页 + platform 过滤 + SampleDetail 复用 + `is_sensitive` 占位 | 同 Tier 1（Tier 2 无前端新增） |
| **事件 / SSE** | 完全复用 Plan 3 | 同 Tier 1 |
| **测试** | 单元 (mock u2/ADB) + `@pytest.mark.android` (fake_chat.apk) + 集成 (mock executor) | 补 OCR / scroll stitcher 单元测试 |
| **估算** | ~21 TDD 任务 | ~9 TDD 任务 |

### 成功标准（Plan 4 done when）
1. 后端全量 `-m "not android and not playwright"` 绿；真机环境 `-m android` 绿。
2. 前端 test / lint / format / build 绿。
3. **Tier 1 手动 smoke**：插 emulator/真机 → `/devices` 看到设备 → 启用 → 写最小 android profile → 跑 3-prompt dry_run batch → SSE 实时进度 → SampleDetail 能看到每轮截图 + ActionLog → 结果 JSONL 含完整响应。
4. **Tier 2 手动 smoke**：用 OCR 模式在自绘文本 App（真 chat App 可用时）测长响应（>1 屏），拿到完整拼接文本。
5. 掉线一台设备中途 → 其他 sample 不阻塞，掉线那条 sample 报错（含 screen + reason），设备记录标 offline。

### 关键决策（brainstorming 锁定）
Q1-B 分层 / Q2-C 自动发现+持久化 / Q3-B 设备池分配 / Q4-A 三层测试 / Q5-A Plan 3 截图语义对齐 / Q6-B Tier 1 够用前端 / Q7-B 首次 ready_check 给一次 recovery / Q8-B RapidOCR / Q9-A 容器有界滚动+OCR 去重。

---

## 2. 架构 & 模块布局

### 分层视图

```
┌──────────────────────────────────────────────────────────────────────┐
│ FastAPI 层                                                            │
│  /batches  /tests  /devices(填实)  /profiles                         │
│       │         │         │                                           │
│       └─────┬───┘         └──→ devices CRUD (新)                     │
│             ↓                                                         │
│  BatchScheduler (扩展)       DevicePool (新)                          │
│   effective concurrency      per-serial asyncio.Lock                 │
│   _acquire_if_android        acquire/release                         │
│             │                                                         │
│             ↓ _build_executor(profile)                                │
│  api/_deps.py dispatcher                                              │
│    api → ApiExecutor  (既有)                                          │
│    gui_pc_web → WebExecutor  (既有)                                   │
│    gui_android → AndroidExecutor  (新)                                │
└──────────────────────────────┼───────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────────┐
│ AndroidExecutor (新)                                                  │
│  AndroidInput        IME 切换 + base64 广播 + u2 fallback             │
│  AndroidActionRunner click_locator / input / swipe / tap_xy / ...    │
│  ResponseExtractor   ui_tree_only | ocr_only | ui_tree_then_ocr      │
│  CompleteDetector    ui_tree_stable + pixel_stable(T2) + btn_reenable│
│  ScreenshotStore     ScreenshotResult{path,is_sensitive,error}       │
│                                                                       │
│  驱动: uiautomator2.Device(serial) + subprocess(adb -s serial)        │
└──────────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────────┐
│ DeviceMonitor (新背景任务)                                             │
│   lifespan 启动 asyncio.create_task                                   │
│   每 5s adb devices -l → 同步到 devices 表                             │
│   离线自动标 offline；重新上线自动转 online；不覆盖 label/enabled       │
└──────────────────────────────────────────────────────────────────────┘
```

### 目录增量

```
src/autoagent/
  devices/                        ← 全新目录
    __init__.py
    adb.py                        ← adb CLI 封装（list/connect/disconnect）
    pool.py                       ← DevicePool: acquire/release + per-serial Lock
    monitor.py                    ← 后台 adb devices 同步任务
  executors/
    android_executor.py           ← 新
    android_input.py              ← 新（IME 切换 + adb_keyboard 广播 + u2 fallback）
    android_action_runner.py      ← 新（继承 ActionRunner 抽象基类）
    android_locator.py            ← 新（Locator schema → u2 selector 映射）
    response_extractor.py         ← 新（Tier 1 只 ui_tree_only；Tier 2 补全）
    ocr.py                        ← 新（Tier 2：RapidOCR 懒加载单例）
    scroll_stitcher.py            ← 新（Tier 2：容器有界滚动 + OCR 去重）
    action_runner.py              ← 改造：提取 ActionRunner 抽象基类 + WebActionRunner
    complete_detector.py          ← 扩展：ui_tree_stable + pixel_stable(T2)
    screenshot_store.py           ← 改造：ScreenshotResult{path,is_sensitive,error}
    base.py                       ← 小改：ExecutorContext 加 action_replay_path + device_serial
  api/
    _deps.py                      ← 改：gui_android 分支
    devices.py                    ← 填实 501；+refresh +PATCH
  storage/
    devices.py                    ← 新（CRUD：devices 表）
    database.py                   ← 加 Device ORM model
  scheduler/
    batch_scheduler.py            ← 改：effective_concurrency + _acquire_if_android
  profiles/
    schemas.py                    ← 改：AndroidProfile.input_method 字段
  main.py                         ← 改：lifespan 启动 DeviceMonitor
  utils/
    env_expand.py                 ← 新（从 action_runner 抽出 $ENV_VAR 展开）

tests/
  fixtures/
    fake_chat_apk/                ← 新（Tier 1 真机测试目标 APK 源码 + 构建产物）
    android_ui_samples/*.xml      ← 真机 dump 的 UI 树固件
    android_screenshots/*.png     ← 真机截图固件（OCR / pixel_stable 单元测试）
  unit/
    test_adb_wrapper.py           ← 新
    test_device_pool.py           ← 新
    test_device_monitor.py        ← 新
    test_android_locator.py       ← 新
    test_android_input.py         ← 新
    test_android_action_runner.py ← 新
    test_android_executor_unit.py ← 新
    test_response_extractor_ui_tree.py ← 新（Tier 1）
    test_response_extractor_ocr.py     ← 新（Tier 2，@pytest.mark.slow）
    test_scroll_stitcher.py       ← 新（Tier 2）
    test_complete_detector_android.py  ← 新
    test_scheduler_device_pool.py ← 新
  integration/
    test_android_executor_e2e.py  ← 新 @pytest.mark.android
    test_devices_endpoint.py      ← 新
    test_tests_sync_android.py    ← 新 @pytest.mark.android

web/src/
  pages/
    Devices/Index.tsx             ← 新
    Devices/DeviceRow.tsx         ← 新
  api/
    devices.ts                    ← 扩展/新建
  types/api.ts                    ← 加 Device + DeviceStatus 类型
  pages/Batches/New.tsx           ← 改：mode 下拉加 gui_android
  pages/Tests/Quick.tsx           ← 改：mode 下拉加 gui_android
  pages/Batches/SampleDetail.tsx  ← 改：device_serial 行 + 回放下载按钮
  components/ScreenshotStrip.tsx  ← 改：handle is_sensitive 占位
```

### 关键边界与职责

- **DevicePool 是应用级单例**，`main.py::lifespan` 创建，scheduler 和 executor 都通过依赖注入拿。
- **AndroidInput 有状态**（`_original_ime`），生命周期绑定单次 `execute()`，`try/finally` 保证还原。
- **AndroidActionRunner 继承 ActionRunner 抽象基类**（从当前单一类重构）；WebActionRunner 是重构后的原行为；测试保护零语义变更。
- **ResponseExtractor 是策略对象**，由 AndroidExecutor 持有；Tier 1 只注册 UiTreeExtractor；Tier 2 补 OcrExtractor + HybridExtractor。
- **ScreenshotStore.capture 返回 ScreenshotResult**，web / android 两侧统一接口。
- **DeviceMonitor 是后台任务**，不 HTTP-triggered；这也是整个项目第一个背景任务，为 Plan 5 奠定模板。

---

## 3. 数据模型 & Schema 变更

### 3.1 `Device` ORM

```python
class Device(Base):
    __tablename__ = "devices"
    serial          = Column(String, primary_key=True)
    label           = Column(String, nullable=True)
    model           = Column(String, nullable=True)
    android_version = Column(String, nullable=True)
    online          = Column(Boolean, default=False)
    enabled         = Column(Boolean, default=True)
    last_seen_at    = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
```

- **双状态灯**：`online` 由 DeviceMonitor 自动翻转（用户改不动）；`enabled` 由用户通过 `/devices/{serial}/connect|disconnect` 翻转。
- `DevicePool.acquire()` 只从 `online=True AND enabled=True` 候选里选。
- 迁移：延续项目约定（`init_db` 的 `metadata.create_all`），不引入 Alembic。

### 3.2 `AndroidProfile.input_method`

```python
class AndroidProfile(BaseModel):
    # ... 既有字段 ...
    input_method: Literal["auto", "adb_keyboard", "u2_send_keys"] = "auto"
```

`auto` 判定：prompt 含非 ASCII → `adb_keyboard`；否则 `u2_send_keys`。

### 3.3 `ScreenshotResult`

```python
@dataclass(frozen=True)
class ScreenshotResult:
    path: Path
    is_sensitive: bool = False
    error: str | None = None
```

`ScreenshotStore.capture(source, label, *, verbose) -> ScreenshotResult | None`（None = 非 verbose 且 label 不在 milestones 白名单）。Web / Android 共用。

### 3.4 `/devices` Pydantic schemas

```python
class DeviceInfo(BaseModel):
    serial: str
    label: str | None
    model: str | None
    android_version: str | None
    online: bool
    enabled: bool
    last_seen_at: datetime | None

class DeviceLabelUpdate(BaseModel):
    label: str | None
```

### 3.5 `ExecutorContext` 扩展

```python
@dataclass
class ExecutorContext:
    logs_dir: str | None = None
    verbose_logs: bool = False
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    action_log: list[dict[str, Any]] | None = None          # Plan 3
    action_replay_path: Path | None = None                  # Plan 4 新
    screenshot_index: list[ScreenshotResult] | None = None  # Plan 4 新
    device_serial: str | None = None                        # Plan 4 新
```

### 3.6 `ExtractionResult`

```python
@dataclass
class ExtractionResult:
    text: str
    method_used: Literal["ui_tree", "ocr"]
    ocr_lines: list[str] | None = None
    ui_tree_node_count: int | None = None
    frames: int = 1
    stitched: bool = False
```

结果写 JSONL 时 `text` 落到 `response`，其余元信息放 `extraction_meta` 可选子对象。

### 3.7 DB 迁移策略
Plan 4 不引入 Alembic。新表通过 `init_db` 的 `create_all` 建；`samples` 表**不**加 `device_serial` 列（写 JSONL 时作为 meta 字段记录即可）。若未来要改既有表，记入 Plan 5 统一做 Alembic 迁移。

---

## 4. API 端点 & 事件

### 4.1 `/devices` 端点

| 方法 | 路径 | 行为 | 响应 |
|---|---|---|---|
| GET | `/devices` | 列表；按 `online DESC, last_seen_at DESC` 排序 | `list[DeviceInfo]` |
| POST | `/devices/refresh` | 立即同步 `adb devices -l` + upsert | `list[DeviceInfo]` |
| POST | `/devices/{serial}/connect` | `enabled=True`；WiFi 形态额外 `adb connect` 尝试上线 | `DeviceInfo` |
| POST | `/devices/{serial}/disconnect` | `enabled=False`；WiFi 形态额外 `adb disconnect` | `DeviceInfo` |
| PATCH | `/devices/{serial}` | body: `DeviceLabelUpdate` | `DeviceInfo` |

**错误码**：404（无此 serial） / 409（设备被某 batch 占用，`_locks[serial]` locked，无法 disconnect） / 502（`adb` CLI 缺失或返回非零）。

所有端点继承 `require_user` JWT 依赖。**不提供** register 端点——C 档语义是自动发现。

### 4.2 `/profiles` 无新端点

Android profile 走既有 `PUT /profiles/{name}` YAML 上传；`parse_profile` 自动路由。`POST /profiles/{name}/test` 按 platform 派发到 `AndroidExecutor.health_check(profile)`。

### 4.3 `/tests/sync` 扩展

Plan 3 已按 platform 派发；Plan 4 加 `gui_android` 分支 + 默认超时 180s。请求/响应 schema 无变更。

### 4.4 `/batches` 无新端点

全部复用：`POST /batches` / `POST /batches/upload` / `GET /batches` / `GET /batches/{id}` / `POST /batches/{id}/cancel` / `GET /batches/{id}/events` (SSE) / screenshots list & download。`mode=gui_android` 在 `models/api.Mode` 中已是合法值，后端只需 `_build_executor` 增加分支。

### 4.5 事件 payload 扩展（最小）

`sample_update` 增加可选字段：
- `device_serial: str | None` — sample 在哪台设备上跑
- `waiting_for_device: bool = False` — 已进调度但在等 `DevicePool.acquire()`

`batch_progress` / `batch_done` 无变更。

### 4.6 SSE / seq 逻辑无变化

沿用 Plan 3：初始 GET 返回 `seq`，SSE `?last_event_id=N` 从 N+1 重放环形缓冲。Plan 4 不引入新 channel。

### 4.7 设备状态变化 **不推送**
不做 `/devices/events`；前端 `/devices` 页用 10s `refetchInterval` + 手动刷新按钮足够。

### 4.8 端点汇总

```
GET    /api/v1/devices                               ← 从 stub 升级
POST   /api/v1/devices/refresh                       ← 新
POST   /api/v1/devices/{serial}/connect              ← 从 501 升级
POST   /api/v1/devices/{serial}/disconnect           ← 从 501 升级
PATCH  /api/v1/devices/{serial}                      ← 新
GET    /api/v1/batches/{id}/samples/{sid}/actions.jsonl ← 新（下载动作回放）
```

**2 个新增 + 3 个 501 升级 + 2 个既有端点的分支扩展。**

---

## 5. Executor 主流程 & 错误恢复 & 生命周期

### 5.1 端到端时序

```
BatchScheduler (per-sample worker):
  publish sample_update {status=running, sample_id}

  async with _acquire_if_android(profile, pool) as serial:
      # 非 android 时 no-op
      # android 时：如果 acquire 阻塞 >1s，publish waiting_for_device=true
      #            acquire 成功后 publish waiting_for_device=false, device_serial=serial

      ctx = ExecutorContext(
          logs_dir, verbose_logs, gui_timeout_sec=180,
          device_serial=serial,
          action_replay_path=<logs>/<sid>.actions.jsonl,
          screenshot_index=[],
      )
      await executor.execute(sample, profile, ctx)

AndroidExecutor.execute(sample, profile, ctx):
  [0] device = await asyncio.to_thread(u2.connect, ctx.device_serial)
  [1] store = ScreenshotStore(root=logs/<batch>/<sample>)
  [2] async with AndroidInput(device, profile.input_method) as input_ctl:
        # __aenter__: 备份 IME；按需切 adb_keyboard
      [3] runner = AndroidActionRunner(device, input_ctl, log=ctx.action_log,
                                       replay=ctx.action_replay_path)
      [4] extractor = ResponseExtractor.for(profile.response_extraction)

      [5] 启动 + 初始就绪：
          device.app_start(profile.package, profile.activity, stop=True)
          device.wait_activity(profile.activity, timeout=30) if activity else no-op
          try:
              await wait_for_ready_check(profile.ready_check, timeout=5)
          except TimeoutError:
              store.capture(device, "ready_fail", verbose=True)
              await runner.run(profile.recovery_path)            # Q7-B: 一次自救
              await wait_for_ready_check(..., timeout=5)         # 最终 assertion
          store.capture(device, "ready", verbose=True)

      [6] if sample.new_session and profile.new_session_action:
          await runner.run(profile.new_session_action)
          store.capture(device, "new_session", verbose=ctx.verbose_logs)

      [7] for idx, prompt in enumerate(sample.prompts, 1):
          try:
              await input_ctl.set_text(profile.input_locator, prompt)
              store.capture(device, f"filled_{idx}", verbose=ctx.verbose_logs)

              await click_locator(profile.send_button_locator)
              store.capture(device, f"sent_{idx}", verbose=ctx.verbose_logs)

              await wait_for_complete(device, profile.complete_detection,
                  send_button_locator=profile.send_button_locator,
                  response_container_locator=
                      profile.response_extraction.response_container_locator)

              result = await extractor.extract(device, profile, store)
              responses.append(result.text)
              extraction_meta.append({...})
              store.capture(device, f"done_{idx}", verbose=True)

          except Exception:
              store.capture(device, f"error_{idx}", verbose=True)
              try:
                  await runner.run(profile.recovery_path)
              except Exception:
                  pass  # recovery 再失败就 suppress（与 Plan 3 对齐）
              raise
  # AndroidInput.__aexit__: IME 还原（finally 保证）
  # scheduler 外层从 ctx 拿 responses + extraction_meta 写 JSONL
  # _acquire_if_android 出域 → DevicePool 自动 release
```

### 5.2 失败分类 & 处理

| 失败点 | 分类 | 处理 |
|---|---|---|
| `u2.connect(serial)` 连不上 | 设备级 | sample fail；monitor 下一轮翻 offline；不跑 recovery |
| `launch_app` 抛错（包名错） | profile 级 | sample fail；error 写 `result.error`；不触发 recovery |
| `wait_activity` 超时 | profile 级 | 一次 recovery + 二次 ready_check，失败 → sample fail |
| `ready_check` 首次失败 | 场景级 | 一次 recovery + 重试；再失败 → sample fail |
| 发送/输入 locator 找不到 | 对话内 | error_N 截图 → recovery（suppress）→ raise 原错 → sample fail |
| `wait_for_complete` 超时 | 对话内 | 同上 |
| IME 切换失败（adb_keyboard 没装） | 环境级 | `AdbKeyboardNotInstalled`；sample fail；error 提示安装 |
| 设备中途掉线 | 设备级 | 当前 sample fail；IME 还原静默失败；DevicePool.release 正常；monitor 翻 offline；batch 继续 |
| OCR 冷启动失败（T2） | 环境级 | sample fail；OCR 单例失败短路，后续 sample 快速失败 |

### 5.3 `DevicePool.acquire` 语义

```python
@asynccontextmanager
async def acquire(
    self, preferred: str | None, timeout_sec: float = 60
) -> AsyncIterator[str]:
    # preferred 非空：只尝试该 serial；被占排队，超时抛 DeviceBusy
    # preferred 为空：挑第一个 online+enabled+lock 空闲的；全忙排队
    # acquire 期间目标 serial 被 disable → 立即抛 DeviceDisabled
    ...
```

**死锁保护**：每个 sample 只 acquire 一把锁；executor 内部不二次 acquire；无递归、无跨 sample 锁。

### 5.4 Scheduler 层改动

```python
def effective_concurrency(self, profile, requested: int) -> int:
    if isinstance(profile, WebProfile) and profile.browser.user_data_dir:
        return 1
    if isinstance(profile, AndroidProfile):
        avail = self.device_pool.available_count_sync()
        return max(1, min(requested, avail))
    return requested
```

batch 开始时算一次，**不动态调整**。中途用户禁用设备 → 剩余 sample 走到 acquire 被拒绝；不缩池。

### 5.5 `DeviceMonitor` 背景任务

- lifespan startup: `asyncio.create_task(monitor.run())`
- lifespan shutdown: `task.cancel(); await task`（suppress CancelledError）
- run(): `while True: try: self._sync_once(); except: log; await asyncio.sleep(5)`
- `_sync_once`：`adb devices -l` 解析后 upsert；**不覆盖** label / enabled（用户控制字段）。
- 新设备首次出现：`enabled=True`（Q2-C 约定），`label=None`。

### 5.6 `health_check`（连通性测试）

```python
async with self.device_pool.acquire(profile.serial, timeout=15) as serial:
    device = await asyncio.to_thread(u2.connect, serial)
    device.app_start(profile.package, profile.activity, stop=True)
    await asyncio.to_thread(device.wait_activity, profile.activity, 15)
    ok = await _check_ui_tree_contains(device, profile.ready_check)
    # 不跑 recovery_path —— 连通性测试要如实反映配置
```

失败时返回 `{ok: false, error, screenshot_url}` 供前端展示。

---

## 6. Tier 2 增量：OCR / Scroll Stitcher / pixel_stable

### 6.1 `executors/ocr.py` — RapidOCR 懒加载单例

```python
class OcrEngine:
    async def recognize(
        self, image: bytes | Path | np.ndarray,
        *, crop: tuple[int,int,int,int] | None = None,
    ) -> list[OcrLine]: ...

@dataclass
class OcrLine:
    text: str
    bbox: tuple[int,int,int,int]   # 屏幕坐标
    confidence: float
```

- 模块级 `_engine_instance`；首次 `get_engine()` 才 `from rapidocr_onnxruntime import RapidOCR`。
- `recognize()` 用 `asyncio.to_thread` 包裹同步推理。
- `crop` 先 PIL 裁剪再喂引擎，避开输入框/键盘干扰。
- 失败短路：抛错缓存到 `_engine_error`，后续调用快速失败。
- RapidOCR 包自带基础模型，无需额外下载。

### 6.2 `response_extractor.py` — 三策略

Tier 1 已落 `UiTreeExtractor`；Tier 2 补：

```python
class OcrExtractor:
    def __init__(self, ocr_engine, scroll_stitcher): ...
    async def extract(self, device, profile, store) -> ExtractionResult:
        # 1) 定位 response_container + scroll_container bounds
        # 2) scroll_stitcher.capture_full_response(scroll_bounds, response_bounds)
        # 3) 每帧 OCR + 行去重拼接
        # 4) 返回 ExtractionResult(text, method_used="ocr", ocr_lines, frames, stitched)

class HybridExtractor:
    """ui_tree_then_ocr: 优先 ui_tree；空文本或疑似截断则降级 ocr。"""
    async def extract(self, device, profile, store):
        r = await self.ui_tree.extract(device, profile, store)
        if _is_suspect(r.text):
            return await self.ocr.extract(device, profile, store)
        return r
```

**`_is_suspect` 启发式**（写死，不开放配置）：
- 空字符串；长度 < 3；末尾 `...` 或 `…` 且在首屏；含 `\ufffc`（object replacement character）。

任一命中 → 降级 OCR。**不做**全自动组合策略——用户要 OCR 就配 `ocr_only`，要兜底就 `ui_tree_then_ocr`，策略明确。

### 6.3 `scroll_stitcher.py` — 容器有界滚动

```python
async def capture_full_response(
    self, device, store,
    *, scroll_bounds, response_bounds,
    max_scrolls: int = 20, step_ratio: float = 0.7,
) -> list[bytes]:  # PNG 字节，从顶到底
```

**流程**：
1. 先滚到底：循环 `swipe_inside(scroll_bounds, up, height*0.7)`，直到响应容器 bounds 不变。
2. 底屏截一张（最后一帧）。
3. 逐屏上滚 + 截图；已滚距离 ≥ `response_bounds.total_height` 或连续两帧没动 → break。
4. 反转 frames 为从顶到底返回。
5. 每帧 crop 到 `response_bounds`，去掉顶导航 + 底输入栏。
6. `step_ratio=0.7` → 30% 重叠供 OCR 去重锚定。

### 6.3a OCR 行去重 `_stitch_lines`

1. 帧内按 y 坐标排序。
2. 帧间：如连续两帧尾部 N 行（N=3..1）文本序列相同，丢弃后一帧前 N 行。
3. 行间插 `\n`。
4. 匹配时 `strip()` 并归一化空白，容忍 OCR 微差。

### 6.4 `complete_detector.py` — `pixel_stable`

```python
async def wait_for_pixel_stable(
    device, *, stable_sec, max_wait_sec,
    roi: tuple[int,int,int,int] | None = None,
    sample_hz: float = 2,
) -> None:
    # 每 1/sample_hz 秒截图 + md5；连续 stable_sec 哈希不变 → return
    # 超时 raise TimeoutError
```

ROI 可选，profile 里独立字段，不强绑 `response_container_locator`。`send_button_reenable` 在 android 已通过 `u2.device(**locator).info["enabled"]` 支持。

### 6.5 Profile 字段行为

Tier 2 **不引入新字段**。`AndroidResponseExtraction.method` 的三值全部被 `ResponseExtractor` 识别；Tier 1 时 `ocr_only` / `ui_tree_then_ocr` 运行时抛 `NotImplementedError("OCR modes available in Tier 2")`，避免静默跑空。

### 6.6 Tier 2 测试固件

- `tests/fixtures/android_screenshots/` 真机典型响应截图（短答案 / 长答案滚动 / 代码块 / 表格），配套 `.expected.txt`。
- `test_scroll_stitcher.py`：mock swipe + screencap，验证停滚判定 / 帧反转 / 去重拼接。
- `test_response_extractor_ocr.py`：真跑 RapidOCR；标 `@pytest.mark.slow`，默认不跑。
- `test_complete_detector_android.py` 扩展 `pixel_stable` 单测。

### 6.7 Tier 2 完整 YAML 示例（豆包）

```yaml
name: doubao_app
platform: android
package: com.bytedance.doubao
activity: com.bytedance.doubao.home.HomeActivity
serial: null
input_method: auto
ready_check:
  type: ui_tree_contains
  text: 发送消息
  timeout_sec: 10
recovery_path:
  - { action: press_key, key: BACK }
  - { action: press_key, key: BACK }
  - { action: click_locator, locator: { type: text, value: 对话 } }
input_locator:     { type: resource_id, value: com.bytedance.doubao:id/chat_input }
send_button_locator: { type: resource_id, value: com.bytedance.doubao:id/send_btn }
response_extraction:
  method: ui_tree_then_ocr
  response_container_locator: { type: resource_id, value: ...:id/bubble_container }
  scroll_container_locator:   { type: resource_id, value: ...:id/chat_list }
  latest_bubble_match:        { type: last_child_with_class, value: android.widget.TextView }
new_session_action:
  - { action: click_locator, locator: { type: text, value: 新对话 } }
  - { action: wait_for,      locator: { type: text, value: 发送消息 }, timeout_sec: 5 }
complete_detection:
  type: ui_tree_stable
  stable_sec: 2
  max_wait_sec: 120
```

---

## 7. 前端 & 测试 & 风险

### 7.1 前端 Tier 1

**`/devices` 页**：表格（Serial / Label / Model / Android / 状态灯（online×enabled）/ 操作）。`useQuery refetchInterval: 10_000`。"立即刷新"按钮 → `POST /devices/refresh`，前端 2s debounce。标签就地编辑（AntD Typography editable → PATCH）。启用/停用 Switch → connect/disconnect；409 提示"设备被占用"。离线设备沉底降饱和。

**模式下拉 & profile 过滤**：`Batches/New.tsx` 和 `Tests/Quick.tsx` 的 mode 从两项扩到三项，profile 下拉按当前 mode 过滤 platform。Android 模式下 `concurrency` 输入框下方加一行提示"实际并发上限取决于在线可用设备数（当前 N 台）"，数据源是 `useQuery(['devices'])`。

**`SampleDetail` 改动**：
- 状态栏下追加"运行设备：{label ?? serial}"（android sample）。
- `ScreenshotStrip` 支持 `is_sensitive`：位置显示锁图标 + "受保护屏幕"文案。
- `ActionLogTable` 表头加 device_serial 列（android only）。
- "下载回放 JSONL" 按钮：`ctx.action_replay_path` 存在时显示，`GET /batches/{id}/samples/{sid}/actions.jsonl`。

**`types/api.ts` 扩展**：

```ts
export interface Device {
  serial: string; label: string | null
  model: string | null; android_version: string | null
  online: boolean; enabled: boolean
  last_seen_at: string | null
}

export interface ScreenshotInfo {
  name: string; label: string; taken_at: string
  is_sensitive?: boolean
}

export interface SampleUpdate {
  sample_id: string; status: SampleStatus
  device_serial?: string | null
  waiting_for_device?: boolean
}
```

### 7.2 测试分层

**单元（CI 默认跑）**：

| 文件 | 覆盖 |
|---|---|
| test_adb_wrapper.py | subprocess 全 mock；`adb devices -l` 解析、多设备、非零退出 |
| test_device_pool.py | per-serial Lock 不串扰；preferred 冲突排队超时 `DeviceBusy`；acquire 期间 disable 立刻抛；释放顺序 |
| test_device_monitor.py | 固定 adb 输出序列；upsert / online 翻转 / label 不被覆盖 |
| test_android_locator.py | 5 种 Locator 映射；`last_child_with_class` 行为 |
| test_android_input.py | IME 备份 → 切换 → 还原；`auto` 判 non-ASCII；`AdbKeyboardNotInstalled` |
| test_android_action_runner.py | 7 动作 mock 验证；$ENV_VAR 展开；error log 条目 |
| test_response_extractor_ui_tree.py | `last_child_with_class` 选最新气泡；空 text |
| test_response_extractor_ocr.py (T2, @pytest.mark.slow) | mock OCR 引擎；_is_suspect 命中/不命中 |
| test_scroll_stitcher.py (T2) | mock swipe + screencap 序列；停滚 / 帧反转 / 行去重 |
| test_complete_detector_android.py | ui_tree_stable / pixel_stable 两种序列 |
| test_android_executor_unit.py | 完整时序：launch → wait_activity → ready_check 失败 → recovery → 重试 → 3 prompts → IME 还原 |
| test_scheduler_device_pool.py | effective_concurrency；user_data_dir 仍降到 1 |

**`@pytest.mark.android` 真机（CI 默认 deselect）**：

- 固件 APK：`tests/fixtures/fake_chat_apk/app/` 源码 + 构建产物 `fake_chat-debug.apk`（< 500KB）。CI 不重新构建；构建说明写到 `fake_chat_apk/README.md`。
- `test_android_executor_e2e.py::conftest.py` session-scope 一次性 `adb install -r`；env `U2_UPDATE_AGENT=0` 禁 u2 agent 自动更新。
- 用例：Tier 1 一条 `ui_tree_only` 3-prompt 对话；Tier 2 加一条 `ocr_only`。
- 跑法记录到 CLAUDE.md：`pytest -m android -v` / `pytest -m "not android and not playwright"`。

**集成（mock executor 工厂）**：
- `test_devices_endpoint.py`：所有 /devices 端点；mock `adb.list_devices()`；404 / 409 / PATCH 路径。
- `test_tests_sync_android.py`：`/tests/sync` 派发到 AndroidExecutor；executor 工厂注入 fake；error 路径含 screenshot url。

### 7.3 已知风险 / 开放问题

1. **uiautomator2 + Android 14+**：u2 agent 在 Android 14 需要禁用一些权限弹窗；fake_chat.apk 的 `targetSdk` 要慎选。遇 agent 初始化失败时在 CLAUDE.md 记 workaround。
2. **ADB Keyboard 依赖**：`input_method: adb_keyboard` 要求设备预装 `com.android.adbkeyboard`；Tier 1 不自动 install，仅检测并抛清晰错误。APK License 不确定，**不纳入仓库**；CLAUDE.md 写清获取路径。
3. **RapidOCR on macOS M 系列**：默认 onnxruntime CPU；~200-400ms/帧；20 帧响应 ~6s。可接受；未来可选依赖 `onnxruntime-silicon`（Plan 5 级）。
4. **Scroll stitcher on Markdown 表格**：跨行 OCR 去重较难，可能重复列；已知缺陷，Tier 2 文档列出。
5. **真机"允许 USB 调试(安全设置)"默认关**：`input` 相关 shell 拒绝。连通性测试失败文案提示检查。
6. **多 batch 并发 DB 写**：SQLite WAL 下不死锁，但需确保所有写在同一 AsyncSession 提交；加一条集成测试覆盖。

### 7.4 任务估算

| 阶段 | 任务数 |
|---|---|
| Tier 1 基建（依赖 + docs、ADB wrapper、Device ORM + CRUD、DevicePool、DeviceMonitor） | 5 |
| Tier 1 动作与输入（AndroidLocator、AndroidInput、AndroidActionRunner） | 3 |
| Tier 1 执行器与抽取（UiTreeExtractor、AndroidExecutor mock+real、ScreenshotStore 改造） | 3 |
| Tier 1 调度 + API + 事件（scheduler、/devices 5 端点、/tests/sync + _deps、事件 payload、ui_tree_stable） | 4 |
| Tier 1 真机固件 + e2e（fake_chat.apk + @pytest.mark.android + conftest） | 1 |
| Tier 1 前端（types、/devices 页、mode 下拉、ScreenshotStrip is_sensitive、SampleDetail） | 4 |
| Tier 1 收尾（CLAUDE.md + 手动 smoke + tag） | 1 |
| **Tier 1 合计** | **~21** |
| Tier 2 OCR（RapidOCR 单例、OcrExtractor、HybridExtractor、_is_suspect） | 3 |
| Tier 2 滚动拼接（ScrollStitcher + 行去重 + crop） | 2 |
| Tier 2 像素稳定（pixel_stable + roi） | 1 |
| Tier 2 固件与集成（截图固件 + slow 单元测试 + e2e） | 2 |
| Tier 2 收尾（CLAUDE.md + 手动 smoke + tag） | 1 |
| **Tier 2 合计** | **~9** |
| **Plan 4 总计** | **~30** |

---

## 8. 交付后端点全景（仅新增与变更）

**新增**：
- `GET /api/v1/devices`
- `POST /api/v1/devices/refresh`
- `PATCH /api/v1/devices/{serial}`
- `GET /api/v1/batches/{id}/samples/{sid}/actions.jsonl`

**从 501 升级**：
- `POST /api/v1/devices/{serial}/connect`
- `POST /api/v1/devices/{serial}/disconnect`

**扩展 platform 分支**：
- `POST /api/v1/tests/sync`（+ gui_android）
- `POST /api/v1/profiles/{name}/test`（+ android）

**事件 payload 扩展**：
- `sample_update`：新增 `device_serial`、`waiting_for_device` 两个可选字段

---

## 9. 交付节奏建议

1. Tier 1 完成后先发 `android-executor-tier1-v0.4.0` 并在 `main` 上打 tag，前端可用（ui_tree 模式可测基于原生 View 的 App）。
2. 真机 smoke 做在 emulator 和一台真机（如有）两个环境，CLAUDE.md 记录配置要点。
3. Tier 2 在 Tier 1 基础上单独实现；无需回改 Tier 1 代码（ResponseExtractor 扩点，CompleteDetector 扩点，其他不动）。
4. Tier 2 完成后发 `android-executor-v0.4.0`，Plan 4 完成。
5. CLAUDE.md 里 Development status 在每个 tag 发出时立即更新（project feedback "keep CLAUDE.md current"）。

---

**End of design.**
