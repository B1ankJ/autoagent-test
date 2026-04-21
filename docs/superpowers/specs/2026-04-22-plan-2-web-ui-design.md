# Plan 2: Web UI — Design Spec

**Date:** 2026-04-22
**Status:** Approved — ready for implementation plan
**Depends on:** Plan 1 (Backend MVP, tag `backend-mvp-v0.1.0`)

---

## 1. 目标与范围

### 1.1 目标

为 Plan 1 后端提供一个可用的操作界面，让操作员能通过浏览器完成：登录、管理 Profile、跑单次 API 测试、创建和监控批量测试、下载结果、配置 VLM / 全局默认值。全流程不再需要 `curl` 或命令行。

### 1.2 范围（含）

- 登录页
- Dashboard（最小版：最近批次 + 基础统计卡）
- Profiles：列表（按 platform 分组 Tab）、新建、编辑、YAML 校验、API 型的连通性测试
- 单次测试（Quick）：同步与异步两种
- Batches：列表（过滤 + 分页）、新建（JSON 表单 or 文件上传）、详情（轮询更新 + 取消 + 下载结果）、Sample 详情
- Config：VLM 配置、全局默认值

### 1.3 范围（不含，留给后续 Plan）

- `/devices` 页（Plan 4）
- Sample 详情中的截图序列 / action 日志画廊（Plan 3/4）
- WebSocket 实时推送（Plan 3 一起做；Plan 2 用 2s 轮询替代）
- Web GUI / Android 执行器相关任何 UI

### 1.4 非目标

- 多用户管理界面（后端目前也只有单 admin）
- 国际化：UI 中文单语言，不引入 i18n 框架
- 主题定制、暗色模式
- 移动端适配（桌面优先，≥1280px）

### 1.5 成功判据

操作员从零启动服务 → 浏览器登录 → 创建一个 API Profile → 在 Profile 编辑页点"连通性测试"看到返回 → 在 `/tests/quick` 同步跑一条 → 在 `/batches/new` 上传 3 条 JSONL → `/batches/:id` 页面在 2s 内刷新状态到 `done` → 点击"下载结果"得到 JSONL 文件。全程无 CLI。

---

## 2. 架构与技术栈

### 2.1 部署形态

**单二进制**：Vite `pnpm build` 产物输出到 `src/autoagent/static/`；FastAPI 在启动时挂载 `StaticFiles(html=True)` 在根路径 `/`，API 保留在 `/api/v1/*`；SPA 路由在未命中静态资源时 fallback 返回 `index.html`。生产单 `uvicorn` 启动。

开发时前端跑 Vite dev server（默认 5173 端口），`vite.config.ts` 配置 `proxy` 把 `/api/v1` 代理到 `http://localhost:8000`。

**后端改动**（Plan 2 唯一的后端改动）：`src/autoagent/main.py` 增加静态挂载，条件检查 `src/autoagent/static/index.html` 是否存在——不存在跳过，保证纯后端开发场景不报错。相应增加一条 integration test：`GET /` 在有静态产物时返回 HTML，无则返回健康信息或 404（具体行为在实现计划中确定）。

### 2.2 技术栈

| 维度 | 选型 |
|---|---|
| 语言 | TypeScript 5 |
| 框架 | React 18 |
| 构建 | Vite 5 |
| UI 组件 | Ant Design 5 |
| 路由 | React Router v6 |
| 数据层 | TanStack Query v5（含内置 `refetchInterval` 轮询） |
| HTTP | axios |
| 表单 | AntD Form |
| YAML 编辑器 | Monaco Editor（VS Code 同款，语法高亮） |
| 单元测试 | Vitest + React Testing Library |
| Lint / Format | eslint + prettier |
| 包管理 | pnpm |
| E2E 测试 | 暂不做（Playwright 留给 Plan 3，届时已装好） |

### 2.3 目录结构（新增部分）

```
web/                          # 独立前端子项目
  package.json
  pnpm-lock.yaml
  vite.config.ts              # proxy /api/v1 → http://localhost:8000 (dev)
  tsconfig.json
  index.html
  src/
    main.tsx                  # ReactDOM.createRoot + QueryClientProvider + ConfigProvider(zh_CN)
    App.tsx                   # React Router 根
    api/
      client.ts               # axios 实例 + 请求/响应拦截器（Bearer 注入、401 退出、ApiError）
      auth.ts                 # login / logout hooks
      profiles.ts             # list / get / create / update / delete / validate / test
      batches.ts              # list / get / create / upload / cancel / download
      tests.ts                # sync / async + poll
      config.ts               # vlm / defaults
    pages/
      Login.tsx
      Dashboard.tsx
      Profiles/
        List.tsx
        Edit.tsx              # 新建和编辑共用（根据路由参数判断）
      Tests/
        Quick.tsx
      Batches/
        List.tsx
        New.tsx
        Detail.tsx
        SampleDetail.tsx
      Config.tsx
    components/
      AppLayout.tsx           # Sider 菜单 + Header 顶栏（用户名 + 登出）
      RequireAuth.tsx         # 路由守卫
      YamlEditor.tsx          # Monaco 封装 + 校验按钮
      StatusTag.tsx           # 按 sample/batch 状态染色
      ModeTag.tsx             # api / web / android 标签
      ErrorBoundary.tsx
    hooks/
      useAuth.ts              # token 读写 + 用户状态
      usePollingBatch.ts      # 封装 useBatch(id, refetchInterval)
    types/
      api.ts                  # 手写：与后端 Pydantic 模型对齐（OpenAPI codegen 留给 Plan 5 有余力时）
    utils/
      download.ts             # blob + Content-Disposition 文件下载
      errors.ts               # ApiError 规范化
```

**源代码不引入 JS 构建到 Python 打包流程**——`pyproject.toml` 保持原样。Plan 5 Docker 里用多阶段构建：node stage `pnpm build` → python stage `COPY --from=node /web/dist /app/src/autoagent/static`。

### 2.4 数据流

所有组件通过 TanStack Query hook 读数据：
- 读：`useProfiles()`、`useBatch(id)`、`useBatches({status, mode})` 等
- 写：`useMutation` 封装 POST/PUT/DELETE，成功 `onSuccess` 调 `queryClient.invalidateQueries(['batches'])` 等刷列表。

**轮询规则**（批次详情页 + 异步单测）：
```ts
useBatch(id, {
  refetchInterval: (data) =>
    data?.status === 'running' || data?.status === 'pending' ? 2000 : false,
})
```
2 秒间隔足够（后端 scheduler 本身不会毫秒级变化），`status` 进入终态自动停。

### 2.5 认证

- 登录成功后 token 存 `localStorage['autoagent_token']`
- axios 请求拦截器每请求注入 `Authorization: Bearer <token>`
- 响应拦截器遇 401：清 token + `window.location = '/login'`
- `RequireAuth` 组件包所有非登录路由，无 token 直接重定向 `/login`
- 登出：`POST /api/v1/auth/logout` → 清 token → 跳 `/login`（后端无状态，接口相当于 no-op 也无妨）

### 2.6 错误处理

- axios 响应拦截器把非 2xx 统一抛 `ApiError { status, detail }`（从 FastAPI 的 `{"detail": "..."}` 或 Pydantic 的 `{"detail":[{...}]}` 规范化）
- TanStack Query 的 `onError` 默认调 AntD `message.error(err.detail)`
- 多行错误（如 `/profiles/validate` 返回的 YAML 校验错误）用 `Modal.error`
- 网络层错误（无 response）统一显示"服务不可达，请检查后端"
- 根部 `<ErrorBoundary>` 兜底 React render 崩溃，展示"页面出错"+刷新按钮

---

## 3. 路由与页面

### 3.1 路由表

| 路由 | 页面 | 后端调用 |
|---|---|---|
| `/login` | 登录 | `POST /auth/login` |
| `/` | Dashboard | `GET /batches?limit=10`（聚合统计由前端算） |
| `/profiles` | Profile 列表（Tab 按 platform 分组） | `GET /profiles` |
| `/profiles/new` | 新建 Profile（Monaco YAML 编辑器） | `POST /profiles/{name}` + `POST /profiles/validate` |
| `/profiles/:name` | 编辑 Profile + 校验 + 删除 + 连通性测试 | `GET/PUT/DELETE /profiles/{name}`；测试按钮 → `POST /tests/sync` |
| `/tests/quick` | 单次测试（同步/异步） | `POST /tests/sync` 或 `POST /tests` + `GET /tests/{task_id}` 轮询 |
| `/batches` | 批次列表（status/mode/日期过滤） | `GET /batches` |
| `/batches/new` | 新建批次（JSON 表单 / 文件上传两 Tab） | `POST /batches` 或 `POST /batches/upload` |
| `/batches/:id` | 批次详情：summary + sample 表 + 取消 + 下载 | `GET /batches/{id}` 2s 轮询；`POST /batches/{id}/cancel`；`GET /batches/{id}/results` |
| `/batches/:id/samples/:sid` | Sample 详情：prompt 列表 + 多轮响应 + 耗时 + 元数据 | 从 `GET /batches/{id}` 返回中筛出（后端无单 sample 端点，够用） |
| `/config` | VLM + 全局默认值 | `GET/PUT /config/vlm`、`GET/PUT /config/defaults` |

### 3.2 布局

`AppLayout` 组件：左侧 `Sider` 固定菜单（Dashboard / Profiles / Tests / Batches / Config），顶部 `Header` 显示当前用户名 + 登出按钮，右侧内容区用 `Outlet` 渲染路由。登录页不进该 layout。

### 3.3 批次新建表单字段

**JSON 模式**：
- `name`（必填）
- `mode`（固定 `api`，下拉但只有一个选项；Plan 3/4 后再开）
- `concurrency`（默认 1，范围 1–10）
- `target_profile_default`（下拉自 `GET /profiles`）
- `webhook_url`（可选）
- `samples`（动态数组，每条：`id` / `prompts`（多行文本，一行一 prompt）/ `new_session`（布尔）/ `metadata`（可选 JSON 编辑器））

**文件上传模式**：
- `name`（必填）
- `mode`（api）
- `concurrency`
- `target_profile_default`
- `<input type="file">` 接受 `.jsonl,.json,.csv`
- 提交前端显示文件名和大小；后端返回 400 时用 `Modal.error` 展示 `detail`

---

## 4. 关键交互细节

### 4.1 Profile 编辑器

- Monaco + YAML 语法高亮
- 两个按钮：**校验**（`POST /profiles/validate`，把结果用 `message` 或 `Modal.error` 显示）、**保存**（`POST /profiles/{name}` 新建 / `PUT` 编辑）
- `platform: api` 的 Profile 额外展示 **连通性测试** 按钮
  - 点击弹 `Modal`，内含一个短 prompt 输入（默认 `"hello"`）和"发送"按钮
  - "发送"调 `POST /tests/sync` 以当前 profile 名 + 一次性 prompt 跑
  - 模态框内显示返回结果 `responses[0]` 或错误 `error`
- 非 API profile 上 **连通性测试** 按钮置灰，tooltip："该能力在 Plan 3/4 提供"
- 删除 Profile 用 `Popconfirm` 二次确认

### 4.2 单次测试（Quick）

- 表单：`id`（可留空自动生成 `uuid`）、`mode`（api）、`target_profile`（下拉）、`prompts`（多行）、`同步 / 异步` 单选
- **同步**：提交后按钮 loading，收到响应显示在下方卡片；多轮响应用 `Collapse` 展开每轮
- **异步**：提交拿到 `task_id` 后页面切换到轮询视图，1s 间隔 `GET /tests/{task_id}`，直到 `status ∈ {done, failed}`，同样在下方卡片呈现结果

### 4.3 批次详情

- 顶部 `Descriptions`：name、mode、concurrency、status、progress、started_at、finished_at
- 进度条：`done + failed / total`
- `Table` 列出 samples：id、status（`StatusTag` 染色）、duration_ms、last_error（截断 + tooltip）、操作列"查看"跳 sample 详情
- Status 染色：pending 灰 / running 蓝 / done 绿 / failed 红 / cancelled 橙
- 右上角按钮组：**取消**（仅 running/pending 批次可用；`Popconfirm` 描述"取消后未完成 sample 将中止，已完成结果保留"）、**下载结果**（任意状态可用）
- 轮询规则：`useBatch(id, { refetchInterval: pickInterval })`——`status ∈ {running, pending}` 返回 `2000`，否则返回 `false` 停轮询

### 4.4 结果下载

不能简单 `window.location = /api/v1/batches/{id}/results`——token 无法附上。方案：

```ts
const res = await client.get(`/batches/${id}/results`, { responseType: 'blob' })
const filename = parseContentDisposition(res.headers['content-disposition']) ?? `${id}.jsonl`
const url = URL.createObjectURL(res.data)
const a = document.createElement('a')
a.href = url; a.download = filename; a.click()
URL.revokeObjectURL(url)
```

### 4.5 空态

- 无批次时批次列表页显示 "还没有批次，去创建一个" + 按钮直达 `/batches/new`
- 无 Profile 时批次新建页提示 "至少创建一个 Profile 才能跑测试" + 按钮跳 `/profiles/new`
- 单测和批次页的 Profile 下拉在无 Profile 时显示禁用占位项

---

## 5. 测试与验收

### 5.1 前端单元测试（Vitest + RTL）

目标 ~15 个测试，覆盖：

- `api/client.ts`：响应 401 触发登出（清 token + 跳转）
- `hooks/useAuth`：token 读写 / 登录成功后状态
- `components/YamlEditor`：校验按钮触发调用 + 错误展示
- `components/RequireAuth`：无 token 重定向 /login
- `pages/Batches/Detail`：
  - status=running 时 refetchInterval=2000
  - status=done 时 refetchInterval=false
  - 取消按钮按 status 启用/禁用
- `pages/Profiles/Edit`：提交流程 + 连通性测试模态框（mock `/tests/sync`）
- `pages/Tests/Quick`：同步/异步分支 + 异步轮询停在 done

运行：`pnpm test`。

### 5.2 后端测试

Plan 2 仅对后端加一项静态挂载改动，相应加一条 integration test：
- `GET /` 在 `static/index.html` 存在时返回 HTML（fixture 里临时建文件）
- `GET /` 在不存在时行为合理（具体行为由实现计划定，例如返回 404 或简化 JSON）

其余 66 个既有测试应保持全绿。

### 5.3 手动 Smoke Test（README 追加 "Web UI Smoke Test" 一节）

1. `pnpm --filter web build` → FastAPI 启动 → 浏览器打开 `http://localhost:8000/` 自动重定向 `/login`
2. 输入 admin 凭证 → 跳 Dashboard
3. 创建一个 API Profile（YAML 含 `api_key_env: OPENAI_KEY`）→ 连通性测试返回成功
4. `/tests/quick` 同步跑一条 "hello" → 看到响应
5. `/batches/new` 上传一份 3 条 JSONL（预置在 `tests/fixtures/`）→ 跳转 `/batches/:id`
6. 观察状态在 2s 内刷新到 `done`
7. 点击"下载结果"得到 `.jsonl` 文件
8. 在 `/config` 改一个 default 字段 → 刷新页面仍保留
9. 登出 → 访问 `/` → 自动跳 `/login`

### 5.4 Plan 2 完成判据

1. ✅ `pnpm --filter web build` 产物能被 FastAPI 正确服务（单个 `uvicorn` 启动跑全）
2. ✅ 后端 `pytest` 全绿（原 66 测试 + 1 个静态挂载测试）
3. ✅ 前端 `pnpm test` 全绿
4. ✅ 前端 `pnpm lint` 无错误
5. ✅ 5.3 的 9 步手动 smoke test 全通过
6. ✅ 所有非 `/login` 路由在未登录时重定向 `/login`

---

## 6. 与后续 Plan 的衔接

### 6.1 Plan 3 交接点

- `/batches/:id/samples/:sid` 页面预留截图序列和 action 日志区块（Plan 3 填充）
- 将 2s 轮询替换为 `WebSocket`：详情页的 `usePollingBatch` hook 改为 `useWebSocketBatch`，其余调用点不变
- `mode` 下拉添加 `web` 选项
- Profile 编辑器"连通性测试"对 web 型 profile 生效

### 6.2 Plan 4 交接点

- 新增 `/devices` 路由（菜单项已留位置）
- `mode` 下拉添加 `android` 选项
- Profile 编辑器"连通性测试"对 android 型 profile 生效

### 6.3 Plan 5 交接点

- Docker 多阶段构建：node 构建前端 → copy 到 python 镜像的 `src/autoagent/static/`
- Plan 5 的安全加固（SecretStr / JWT audience / 登录计时侧信道）不直接影响前端，但登录失败提示要与后端保持一致

---

## 7. 风险与开放问题

- **Monaco 包大小**：完整 Monaco 体积较大（~2MB gzipped）。如果最终产物过大，可在 Plan 5 换成 `@monaco-editor/react` 按需加载 worker，或降级为 CodeMirror 6。先做 Monaco，Plan 5 视情况优化。
- **OpenAPI codegen**：前端 `types/api.ts` 手写与后端同步需要纪律。若手写偏差成为痛点，Plan 5 引入 `openapi-typescript` 从 `/openapi.json` 生成。
- **后端 `/tests/sync` 复用为连通性测试**：如果 profile 的 `api_key_env` 指向未设置的环境变量，后端会返回 failed sample。前端模态框需要清晰展示 `error` 字段，不误导用户以为是网络问题。
