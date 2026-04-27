## Fake Chat APK

This fixture is the stable Android target for Plan 4 real-device verification.

It intentionally exposes fixed resource IDs so `AndroidExecutor` can interact
with a predictable UI instead of a third-party app:

- `com.autoagent.fakechat:id/input`
- `com.autoagent.fakechat:id/send`
- `com.autoagent.fakechat:id/newChat`
- `com.autoagent.fakechat:id/responses`

Expected behavior:

- typing `hi` then tapping `Send` appends `echo: hi`
- tapping `New Chat` clears previous responses

### Build

Open this folder in Android Studio and build the debug APK.

Place the built artifact at:

`tests/fixtures/fake_chat_apk/fake_chat-debug.apk`

Or point the test to a different output with:

```bash
export AUTOAGENT_FAKE_CHAT_APK=/abs/path/to/app-debug.apk
```

### Install

```bash
adb -s <serial> install -r tests/fixtures/fake_chat_apk/fake_chat-debug.apk
```
