# Device Watchdog / Auto-Heal — Design

## Problem

When an android/agent_android device drops offline (wifi blip, adb TCP dropped), `DevicePool` can't schedule it and its samples fail at device-acquisition or wait — you don't get responses from that device until someone manually re-runs `adb connect`. AutoAgent's job is to *obtain* responses; a device silently staying offline is lost throughput.

## Goals

- Automatically re-establish `adb connect` for **network (wifi) devices** that go offline, so a device whose network briefly dropped (or comes back later) rejoins the pool without manual intervention.
- Persistent-but-bounded: keep retrying on an exponential backoff while a device stays offline, so a device that returns minutes later is still recovered.
- Safe and opt-in: reconnect is a gentle, side-effect-free action; no reboot / no host-side `adb kill-server` this iteration.

## Non-goals (this iteration)

- Reboot or any device-state-mutating recovery (reconnect only — `adb connect` doesn't change anything on the device).
- Host-side `adb kill-server`/restart (would drop every device's connection — too broad).
- Healing USB devices (offline USB is a physical-layer problem `adb connect` can't fix).
- New per-device UI (the Devices page already shows online/offline; a recovered device just turns green). Only a Config toggle is added.
- New alerting channel (the existing online↔offline DingTalk transitions already cover "device went offline" and "device recovered").

## Config, scope, and safety exclusions

- **`DefaultsConfig.device_autoheal_enabled: bool = False`** — opt-in, default **off** (consistent with every other auto-action in this repo: DingTalk rules, self-update, backups, ANR). A toggle on the Config page. Read from the kv `defaults` config each tick, so toggling needs no restart.
- **Network devices only**: heal a serial only when `devices/adb.py::_is_network_serial(serial)` (host:port form). USB serials are skipped.
- **Excluded from healing** (never `adb connect`-ed):
  1. `enabled == False` — the user deliberately disabled it; don't touch it.
  2. `devices/expected_state.py::is_expected_reboot(serial)` — a planned init/reboot is in progress; don't fight the init playbook.
  3. Currently held by `DevicePool` — a new public `DevicePool.is_locked(serial) -> bool` (reads the existing per-serial `asyncio.Lock`); conservative double-safety so we don't touch a device the scheduler thinks it's using.

## Healer

New module `devices/healer.py::DeviceHealer` — one clear responsibility, injectable for testing:

```python
class DeviceHealer:
    def __init__(
        self,
        *,
        list_devices,                 # async () -> list[DeviceInfo]  (DB rows: .serial/.online/.enabled)
        is_locked,                    # (serial: str) -> bool  (DevicePool.is_locked)
        is_enabled,                   # async () -> bool       (reads device_autoheal_enabled)
        connect=adb.connect,          # (serial: str) -> None  (adb connect)
    ): ...

    async def maybe_heal(self) -> None: ...
```

`maybe_heal()` (called once per monitor tick):
1. If `not await is_enabled()` → return (respects the toggle live).
2. `rows = await list_devices()` (the DB device rows the monitor just refreshed this tick — fresh online/offline + `enabled`).
3. For each `d` in rows:
   - **online** → reset that serial's backoff state (recovered) and continue.
   - **offline** and `_is_network_serial(d.serial)` and `d.enabled` and not `is_expected_reboot(serial)` and not `is_locked(serial)` → if `monotonic() >= next_attempt[serial]`, run `adb.connect(serial)` via `asyncio.to_thread` (same off-loop pattern as the monitor, so a hung device can't freeze uvicorn), then bump backoff (`×2`, capped) and set `next_attempt`. Otherwise skip this tick.
   - offline but excluded/USB → skip.
4. Wrapped so a single device's `adb connect` failure/exception never aborts the tick or the loop; each attempt is `log.info`-ed (attempt + outcome).

**Backoff**: `_HEAL_INITIAL_SEC = 30`, `×2`, `_HEAL_MAX_SEC = 300`. Per-serial, in-memory monotonic state (a process restart just resets to the initial interval — acceptable).

## Wiring

- `DeviceMonitor` gains an optional `on_tick: Callable[[], Awaitable[None]] | None = None`, awaited at the end of `sync_once` (after `_emit_transitions`), guarded so a healer failure can't stall the poll loop.
- `api/_deps.py::get_device_monitor` constructs a `DeviceHealer` (with `list_devices=list_stored_devices`, `is_locked=pool.is_locked`, `is_enabled=<reads DefaultsConfig.device_autoheal_enabled>`, `connect=adb.connect`) and passes `healer.maybe_heal` as the monitor's `on_tick`. Same `DevicePool` instance as scheduling.
- No new background task — it rides the existing 5s `DeviceMonitor` loop.

## Alerting & result

- **Reuse existing**: a successful reconnect makes the device go offline→online, which the monitor's existing `on_state_change` hook already reports as a DingTalk "recovered" alert; the offline transition already alerted. So auto-heal adds **no new alert path** — only `log.info` per attempt/success.
- **UI**: a Config-page toggle for `device_autoheal_enabled`. No per-device heal-status UI (recovered devices turn green on the Devices page as they already do).

## Error handling

- Healer exceptions are caught per-attempt and at the `on_tick` boundary — the monitor poll never stalls.
- A device that never comes back just keeps hitting the capped backoff (a reconnect attempt every ~5min) and is otherwise ignored; no reboot-loop, no unbounded spam.
- `is_enabled` read failure (transient DB error) → treated as off for that tick (no heal), retried next tick.

## Testing

**Unit (`DeviceHealer`, all deps injected — mock `connect`, `is_enabled`, `list_devices`, `is_locked`):**
- Offline network device, enabled, not excluded, past its backoff → `connect(serial)` called; backoff bumped.
- Second immediate tick (before `next_attempt`) → not called again.
- Device turns online → backoff reset (next offline starts from the initial interval).
- USB serial (no `:port`) → never called.
- `enabled=False` / `is_expected_reboot` True / `is_locked` True → skipped.
- `is_enabled()` returns False → nothing called.
- A `connect` exception on one serial doesn't stop the others / doesn't raise out of `maybe_heal`.
- `DevicePool.is_locked(serial)`: True while the per-serial lock is held, False otherwise.
- `DeviceMonitor` awaits `on_tick` at the end of `sync_once` (a small monitor test with a spy `on_tick`).

**Backend suite** stays green; `DefaultsConfig` round-trips the new field; the Config `defaults` GET/PUT accepts it.

**Frontend:** the Config page renders/saves `device_autoheal_enabled` (a `Switch`), plus its type on the TS `GlobalDefaults`.
