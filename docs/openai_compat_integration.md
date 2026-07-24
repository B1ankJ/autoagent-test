# AutoAgent OpenAI 兼容接口 — 接入文档

给请求发送方(调用方)看的文档:怎么把已有的 OpenAI SDK / HTTP 调用代码接到 AutoAgent 上。

本文档对应代码版本:`src/autoagent/openai_compat/`、`src/autoagent/api/openai_compat.py`、`src/autoagent/api/devices.py`(`/sessions/{id}/release`)。如果行为对不上,以代码为准,并提 issue。

## 1. 这是什么

`POST /v1/chat/completions` 是 AutoAgent 对外暴露的、形状上兼容 OpenAI Chat Completions 的接口。但它**不是**一个真的 LLM 代理——请求最终会落到 AutoAgent 里配置好的一个"目标"上执行,这个目标可能是:

- 一个真的 OpenAI 兼容 API(`platform: api`)
- 一个 Web 聊天页面,用 Playwright 操作浏览器(`platform: web`)
- 一台真实 Android 设备上的 App,用 uiautomator2 操作(`platform: android`)
- 一个视觉 Agent 在跑 PC 桌面操作(`platform: agent_pc`)
- 一个视觉 Agent 在跑 Android 设备操作(`platform: agent_android`)

`model` 字段填的**不是**模型名,是 AutoAgent 里配置好的 **profile 名称**(对应 `data/profiles/<name>.yaml`)。请求打过去之后,AutoAgent 会按这个 profile 的类型选对应的执行方式,把 `messages` 里的内容当成"要发给这个产品的一句话"发过去,拿到真实产品的回复后按 OpenAI 的响应格式包一层返回。

> **命名提醒**:profile 配置里的 `platform` 字段和响应/日志里出现的"执行模式"用词不完全一样——`platform: web` 对应的执行模式叫 `gui_pc_web`,`platform: android` 对应的执行模式叫 `gui_android`,其余三个(`api`/`agent_pc`/`agent_android`)两边用词一致。本文档下面涉及"哪些模式默认超时是多少"这类按**执行模式**分类的地方,用的是 `gui_pc_web`/`gui_android` 这套词;涉及"哪些 profile 类型支持某个字段"这类按**profile 配置**分类的地方,用的是 `web`/`android` 这套词。如果两边对不上,大概率是这个原因,不是文档写错了。

## 2. 鉴权

所有接口(包括 `/v1/chat/completions`)统一用 `Authorization: Bearer <token>`,`<token>` 可以是下面两种之一:

### 方式一:静态 Key(推荐给纯脚本/服务端调用方)

如果部署方配置了 `STATIC_API_KEY` 环境变量,直接把这个值当 Bearer token 用,永久有效,不用登录、不用刷新:

```
Authorization: Bearer <STATIC_API_KEY 的值>
```

问部署方要这个值。如果部署方没配置这个变量,这条路不可用,只能走方式二。

### 方式二:登录拿 JWT

```
POST /api/v1/auth/login
Content-Type: application/json

{"username": "...", "password": "..."}
```

返回:

```json
{"token": "eyJ...", "expires_in_sec": 86400}
```

后续请求用 `Authorization: Bearer <token>`。默认有效期 24 小时,过期后要重新登录换新 token(接口不支持 refresh token,直接重新 `/login`)。

注意:登录接口有失败次数限制——同一个用户名连续 5 次密码错误会被锁 15 分钟(返回 429),重试逻辑不要对着 `/login` 疯狂重试。

## 3. 接口:`POST /v1/chat/completions`

**注意路径前缀是 `/v1`,不是 `/api/v1`**(这个接口是唯一一个不带 `/api/v1` 前缀的,故意跟真实 OpenAI 的路径保持一致,方便直接换 base_url 接入已有 SDK)。

### 3.1 请求体字段

标准 OpenAI 字段:

| 字段 | 必填 | 说明 |
|---|---|---|
| `model` | 是 | **AutoAgent profile 名称**,不是模型名。必须是已存在的 profile。 |
| `messages` | 是 | 至少 1 条。见下方"取哪条消息当输入" |
| `stream` | 否 | **必须是 `false` 或不传**。传 `true` 直接 400,不支持流式。 |
| `temperature` / `top_p` / `max_tokens` / `max_completion_tokens` / `stop` / `user` | 否 | **接受但完全忽略**,不会报错,但也不会生效——AutoAgent 转发的是"发这句话给真实产品",不是调 LLM 参数。留着是为了不用改调用方现有代码结构。 |
| `tools` / `tool_choice` / `functions` / `function_call` / `response_format` / `audio` / `modalities` / `parallel_tool_calls` | 否 | **不支持,只要传了非空值就 400**。不要在请求里带这些字段(哪怕值是 `null` 以外的东西)。 |
| `n` | 否 | 只支持 `n=1`(默认值),传别的值 400。 |
| `metadata` | 否 | 透传的自定义 kv,会原样出现在响应的 `x_autoagent.metadata` 里(和执行过程中产生的 metadata 合并,比如 `device_serial`)。 |

**取哪条消息当输入**:从 `messages` 倒着找,取第一条 `role` 是 `user` 或 `assistant`、且内容非空字符串的消息,发给目标产品。也就是说正常情况下就是"最后一条消息";`system` 消息永远被跳过;消息的 `content` 必须是纯字符串,传多模态数组格式(`list[dict]`)会 400。

AutoAgent 扩展字段(通过 OpenAI SDK 的 `extra_body` 传,或者 raw HTTP 直接放请求体顶层):

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `new_session` | bool | `false` | 见第 5 节。是否让目标产品"开始新一轮对话"(点新建对话 / 重置浏览器会话 / Android 执行 new_session_action)。 |
| `session_id` | string\|null | `null` | 见第 5 节。**仅对 `agent_android`/`android` 类型的 profile 有意义**,用于多轮对话跨请求粘在同一台设备上。 |
| `end_session` | bool | `false` | 见第 5 节。表示"这轮多轮对话结束了",不会真的发消息,只释放设备占用。 |
| `timeout_sec` | int\|null | 按 mode 给默认值 | 单次执行超时(秒)。不传的话:`api` 模式 60s,GUI/Agent 类模式 180s。**这个是执行超时,不是 HTTP 调用本身的超时**,后者见第 6 节。 |
| `retry` | int | `2` | 失败自动重试次数(不含首次尝试)。 |
| `dry_run` | bool | `false` | `true` 时不会真的执行,直接返回 `status: "done"`、内容是 `"[DRY RUN] would send: <你发的内容>"`。用来验证接入是否打通,不消耗真实设备/额度。 |

### 3.2 响应体(200)

```json
{
  "id": "chatcmpl_a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1732000000,
  "model": "your_profile_name",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "目标产品的真实回复文本" },
      "finish_reason": "stop"
    }
  ],
  "x_autoagent": {
    "sample_id": "chatcmpl_a1b2c3d4e5f6",
    "status": "done",
    "attempt_count": 1,
    "duration_ms": 3421,
    "responses": ["原始抽取到的回复(可能有多条,取决于产品形态)"],
    "llm_responses": [],
    "llm_errors": [],
    "logs_dir": "b_xxx/chatcmpl_xxx",
    "metadata": {}
  }
}
```

只关心"这次到底成没成、回复是什么"的话看两个地方就够:

- `choices[0].message.content` —— AutoAgent 认为的"最终回复"(如果 profile 配了 LLM 复核抽取且复核成功,这里是复核后的文本,否则是原始抽取文本;和 `x_autoagent.status` 无关,即使执行失败这个字段也会存在,可能是空字符串)。
- `x_autoagent.status` —— `done` / `failed` / `timeout` / `extraction_failed` / `cancelled` 之一(同步调用不会看到 `queued`/`running`,因为接口是阻塞到跑完才返回)。**HTTP 200 不代表业务成功**,一定要看这个字段,非 `done` 时 `content` 大概率是空的。

`x_autoagent.responses` / `llm_responses` / `llm_errors` 是更细粒度的原始数据(比如一个 sample 发了多轮 prompt 时,每轮一条),一般不需要用,除非要排查为什么 `content` 是这个值。

### 3.3 错误响应

统一走 OpenAI 的错误信封格式,外面多一个 `x_autoagent` 字段(跟成功响应的 `x_autoagent` 是同一个思路的扩展位,大部分错误这个字段是 `null`,只有需要额外结构化信息的错误才会填):

```json
{"error": {"message": "...", "type": "...", "param": "...", "code": "..."}, "x_autoagent": null}
```

| HTTP 状态码 | `error.type` | 触发场景 |
|---|---|---|
| 400 | `invalid_request_error` | JSON 格式错、字段校验不过(缺 `model`/`messages`、`stream=true`、带了不支持的字段、`messages` 全是空内容等) |
| 401 | `invalid_request_error` | 没带 Bearer token / token 格式不对 / token 过期或无效 |
| 404 | `invalid_request_error`(`code: not_found`) | `model` 指定的 profile 不存在 |
| **429** | **`rate_limit_error`**(`code: device_reserved`) | **新增行为,见第 5.3 节**:`session_id` 指定的设备池里所有设备都被别的会话占着,直接快速失败,不会傻等 |
| 500 | `api_error` | AutoAgent 内部异常,或者执行完了但没拿到结果 |

**429 时 `x_autoagent.blocking_session_ids` 是个字符串数组**,告诉你具体是哪个/哪些 `session_id` 占着设备,方便程序化处理(不用去 `error.message` 里正则提取):

```json
{
  "error": {
    "message": "all devices reserved by other session(s): ['conv-other-123']",
    "type": "rate_limit_error",
    "param": null,
    "code": "device_reserved"
  },
  "x_autoagent": {
    "blocking_session_ids": ["conv-other-123"]
  }
}
```

拿到 429 的正确处理方式是**退避重试**或者提示"设备忙",而不是当成普通失败直接报错给用户——设备很可能几分钟内就会被释放。

## 4. 快速验证接入

```bash
curl -X POST https://<你的AutoAgent地址>/v1/chat/completions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your_profile_name",
    "messages": [{"role": "user", "content": "你好"}],
    "dry_run": true
  }'
```

`dry_run: true` 不会真的跑,秒回,确认链路通了之后再去掉。

用 OpenAI 官方 SDK(Python 示例,`extra_body` 传 AutoAgent 扩展字段):

```python
from openai import OpenAI

client = OpenAI(base_url="https://<你的AutoAgent地址>/v1", api_key="<token>")

resp = client.chat.completions.create(
    model="your_profile_name",
    messages=[{"role": "user", "content": "你好"}],
    extra_body={"dry_run": True},
)
print(resp.choices[0].message.content)
print(resp.model_extra["x_autoagent"])  # SDK 不认识的字段落在这里
```

## 5. 多轮对话

有两种不同的实现路径,**用错路径在多设备场景下会有问题**,先看清楚自己适用哪种。

### 5.1 路径 A:一个请求发完整段对话(推荐,只要能这么用就优先用这个)

如果你能一次性拿到整段对话的所有轮次,不需要 AutoAgent 帮你维护"上一轮发到哪了"的状态,直接不要用 OpenAI 的 `/v1/chat/completions` 形状,改用 AutoAgent 原生的 `/api/v1/tests/sync`,一个 `Sample` 的 `prompts` 字段本身就是个列表,一次性把多轮 prompt 都放进去,AutoAgent 会在**同一个执行过程、同一台设备**上依次发完,不存在"跨请求""跨设备"的问题。这条路径不需要读下面的内容。

### 5.2 路径 B:拆成多个独立请求,靠标志位串起来(你现在在用的方式)

如果你的调用方式就是"发一句、等回复、根据回复决定下一句发什么"这种交互式的多轮,那必须拆成多个独立 HTTP 请求。这种情况下,**如果目标 profile 配了多台设备**(Android/agent_android 场景),AutoAgent 需要知道"这几个请求属于同一段对话",不然可能被路由到不同的物理设备上,导致对话上下文断裂。

用法:

1. **第一轮**:`new_session: true` + `session_id: "<你自己生成的会话标识,比如 uuid>"`。AutoAgent 会挑一台设备,把这个 `session_id` 和这台设备**强绑定**。
2. **后续每一轮**:`new_session: false`(或不传,默认就是 false) + 同一个 `session_id`。AutoAgent 会强制把请求路由到第一轮绑定的那台设备上,保证上下文连续。
3. **对话结束时**:发一个 `end_session: true` + 同一个 `session_id` 的请求(`messages` 随便填,内容会被忽略,不会真的执行)。AutoAgent 会立刻释放这台设备,让别的对话能用。**这一步不要省略**——不发的话设备会一直被这个 `session_id` 占着,直到 30 分钟没有新请求才会自动释放。

```python
import uuid
session_id = str(uuid.uuid4())

# 第一轮
r1 = client.chat.completions.create(
    model="android_profile", messages=[{"role": "user", "content": "你好"}],
    extra_body={"new_session": True, "session_id": session_id},
)

# 第二轮、第三轮……
r2 = client.chat.completions.create(
    model="android_profile", messages=[{"role": "user", "content": "继续问点别的"}],
    extra_body={"session_id": session_id},  # new_session 不传，默认 false
)

# 结束
client.chat.completions.create(
    model="android_profile", messages=[{"role": "user", "content": "-"}],
    extra_body={"session_id": session_id, "end_session": True},
)
```

`session_id`/`end_session` **只对 `android`/`agent_android` 类型的 profile 有效**(因为只有这两种模式背后是"多台设备的池子"这个概念)。对 `api`/`web`/`agent_pc` 类型的 profile,这两个字段会被接受(不报错)但完全不起作用:

- `api` 模式本来就是无状态的,每次都是独立请求。
- `web` 模式的"会话"是按 profile 名字绑定浏览器上下文的,同一个 profile 名下的所有请求(不管来自哪个 `session_id`)天然共享同一个浏览器 tab——**如果你对同一个 web profile 并发发起多段不同的对话,它们会互相干扰**,这是当前的已知限制,不是靠 `session_id` 能解决的,需要为每段对话配不同的 profile。
- `agent_pc` 是操作本机桌面,不存在多设备的概念。

不管哪种 profile,`new_session` 本身(不涉及 `session_id`)都生效——它控制的是"要不要执行 profile 里配置的新建对话动作",跟设备粘性是两回事。

### 5.3 设备都被占满时会发生什么

如果 `session_id` 指定的设备池(profile 配置的所有设备)**全部**被别的活跃会话占着(不是临时忙,是真的都被别的 `session_id` 预留了),AutoAgent 不会傻等——会**立刻**返回 429(不是等到 `timeout_sec` 超时才失败),响应里带着是哪些 `session_id` 占着设备,方便你决策要不要重试/提示用户。

反过来,如果你**没传** `session_id`(路径 A,或者压根没用多轮对话),遇到设备都被预留的情况,行为跟以前一样——正常排队等待,不会主动 429(因为没有"是哪个会话"的上下文可以报告)。

### 5.4 备选:不发消息、单纯释放设备

如果某次要结束的对话不方便凑一条 `messages`(比如客户端逻辑里没有"最后一条消息"这个概念),可以直接调 AutoAgent 原生接口跳过 chat completions 的形状:

```
POST /api/v1/devices/sessions/{session_id}/release
Authorization: Bearer <同上>
```

返回 `{"session_id": "...", "released": true|false}`,`false` 表示这个 `session_id` 本来就没设备占用(比如已经释放过、或从没绑定过)——**这不是错误**,可以放心无脑调用,不用先查状态。

## 6. 超时与耗时预期

HTTP 调用本身会**阻塞**直到拿到结果(不支持异步轮询这种形态,如果需要异步,改用 `POST /api/v1/tests` + `GET /api/v1/tests/{task_id}` 这一对原生接口)。这里有**两层不同的超时**,容易搞混,分开说:

1. **单次执行超时**(执行器内部,失败会按 `retry` 重试):就是 `timeout_sec` 字段本身的语义,不传的话 `api` 模式 60s,其余模式(`gui_pc_web`/`gui_android`/`agent_pc`/`agent_android`)180s。这层决定"一次尝试最多跑多久算超时"。
2. **服务端愿意等多久才给 HTTP 响应**(这层跟上面那层默认值**不是同一套数字**,容易踩坑):不传 `timeout_sec` 时,只有 `gui_android` 模式走 180s,**其余所有模式(含 `api`、`agent_android`)默认是 600s**,再加固定 30 秒缓冲。也就是说默认情况下,一次 `/v1/chat/completions` 调用理论上最长可能挂起 **630 秒**(`api`/`web`/`agent_pc`/`agent_android`)或 **210 秒**(仅 `gui_android`)才返回——哪怕是 `api` 模式,也别按"这应该很快"去设一个几秒钟的客户端超时。如果你显式传了 `timeout_sec`,这两层会用同一个值(第二层是 `你传的值 + 30`),行为会更好预测,**建议接入时直接显式传 `timeout_sec`,不要依赖默认值**。

有个特殊情况:如果卡在"等一台空闲设备"这一步(设备都在忙,但没到 429 的"全被预留"程度),等待上限是另一个配置(`device_acquire_timeout_sec`,部署方默认给的是 2 小时),比上面说的服务端等待上限长得多。这种情况下 HTTP 调用会先超时返回 500,但**执行本身并没有被取消**,会在后台继续跑,只是这次 HTTP 请求拿不到结果了——如果对这种情况有感知需求,问部署方要这批次的执行记录(AutoAgent 内部按 batch 记录,不通过 `/v1/chat/completions` 这条路暴露查询)。

## 7. 已知限制清单

- 不支持流式(`stream: true` 直接 400)。
- 不支持多模态输入(`content` 必须是纯字符串)。
- 不支持 `tools`/`function_call` 等工具调用相关字段。
- `temperature` 等采样参数只是摆设,不生效。
- 一次请求只处理 `messages` 里的一条内容(倒着找到的最后一条 user/assistant 消息),不会把整个 `messages` 数组当上下文一起发给目标产品——多轮上下文是由目标产品自己(浏览器里的聊天记录、App 里的对话历史)维护的,不是 AutoAgent 在拼接 prompt。
- `session_id` 设备粘性只对 Android 类 profile 有效,见 5.2。
- Web 类 profile 同名 profile 下天然共享一个浏览器上下文,同一 profile 不要并发跑多段互不相关的对话。
