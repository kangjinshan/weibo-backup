# Automatic Backup Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start one backup immediately when the dashboard starts, then retry every 30 minutes without creating overlapping backup processes.

**Architecture:** Extract the existing process-launch code into a synchronous internal function shared by the authenticated HTTP endpoint and an asyncio scheduler. Attach the scheduler to FastAPI's lifespan, make its interval configurable through `WEIBO_AUTO_BACKUP_INTERVAL_SECONDS`, and cancel only the scheduler task at shutdown while leaving any spawned spider process alone.

**Tech Stack:** Python 3, FastAPI lifespan, asyncio, subprocess, unittest/unittest.mock

---

### Task 1: Share Backup Process Launching

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `dashboard/server.py`

- [ ] **Step 1: Write the failing helper test**

Add this test to `DashboardTests` in `tests/test_dashboard.py`:

```python
def test_start_backup_wraps_shared_process_launcher(self):
    result = {
        "ok": False,
        "status": {"running": True, "status": "running", "pid": 123},
        "message": "backup already running",
    }

    with patch.object(server, "launch_backup_process", return_value=(result, 200)) as launch:
        response = asyncio.run(server.start_backup())

    self.assertEqual(json.loads(response.body), result)
    self.assertEqual(response.status_code, 200)
    launch.assert_called_once_with()
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard.DashboardTests.test_start_backup_wraps_shared_process_launcher
```

Expected: FAIL because `dashboard.server` has no `launch_backup_process`.

- [ ] **Step 3: Extract the existing launch behavior**

Replace the body of the current `start_backup()` endpoint in `dashboard/server.py` with a wrapper and move its existing logic into this synchronous helper. Every previous `JSONResponse(content, status_code=...)` becomes `return content, status_code`:

```python
def launch_backup_process():
    status = get_backup_process_status()
    if status["running"]:
        return {"ok": False, "status": status, "message": "backup already running"}, 200
    try:
        config = read_backup_config()
    except Exception as exc:
        return {
            "ok": False,
            "message": f"启动失败：无法读取 weiboSpider/config.json：{exc}",
        }, 400
    issues = backup_config_issues(config)
    if issues:
        return {
            "ok": False,
            "message": "启动失败：" + "；".join(issues),
            "config_issues": issues,
        }, 400
    ensure_logs_dir()
    command = spider_command()
    try:
        with BACKUP_LOG_PATH.open("ab") as log_fh:
            process = subprocess.Popen(
                command,
                cwd=str(SPIDER_DIR),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        return {
            "ok": False,
            "message": f"启动失败：{exc}",
            "command": command,
            "cwd": str(SPIDER_DIR),
            "log_path": str(BACKUP_LOG_PATH),
        }, 500
    BACKUP_PID_PATH.write_text(str(process.pid) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "pid": process.pid,
        "log_path": str(BACKUP_LOG_PATH),
    }, 200


@app.post("/api/backup/start")
async def start_backup():
    payload, status_code = launch_backup_process()
    return JSONResponse(payload, status_code=status_code)
```

- [ ] **Step 4: Run helper and existing launch tests to verify GREEN**

Run:

```bash
python3 -m unittest \
  tests.test_dashboard.DashboardTests.test_start_backup_wraps_shared_process_launcher \
  tests.test_dashboard.DashboardTests.test_start_backup_refuses_to_run_without_configured_cookie \
  tests.test_dashboard.DashboardTests.test_start_backup_returns_json_when_process_fails_to_start
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit the shared launcher**

```bash
git add dashboard/server.py tests/test_dashboard.py
git commit -m "refactor: share backup process launcher"
```

### Task 2: Add the Resilient 30-Minute Scheduler

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `dashboard/server.py`

- [ ] **Step 1: Write failing interval and scheduler tests**

Add `import os` to `tests/test_dashboard.py`, then add these tests to `DashboardTests`:

```python
def test_automatic_backup_interval_defaults_to_thirty_minutes(self):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WEIBO_AUTO_BACKUP_INTERVAL_SECONDS", None)
        self.assertEqual(server.automatic_backup_interval_seconds(), 1800.0)

    with patch.dict(os.environ, {"WEIBO_AUTO_BACKUP_INTERVAL_SECONDS": "0"}):
        self.assertEqual(server.automatic_backup_interval_seconds(), 0.0)

    with patch.dict(os.environ, {"WEIBO_AUTO_BACKUP_INTERVAL_SECONDS": "invalid"}):
        self.assertEqual(server.automatic_backup_interval_seconds(), 1800.0)

def test_automatic_backup_runs_immediately_then_waits(self):
    calls = []
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        raise asyncio.CancelledError

    async def scenario():
        with (
            patch.object(server, "launch_backup_process", side_effect=lambda: (calls.append("run") or ({"ok": True}, 200))),
            patch.object(server.asyncio, "sleep", side_effect=fake_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await server.run_automatic_backup_scheduler(1800)

    asyncio.run(scenario())
    self.assertEqual(calls, ["run"])
    self.assertEqual(sleeps, [1800])

def test_automatic_backup_recovers_after_one_attempt_raises(self):
    attempts = []
    sleeps = []

    def launch():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("temporary failure")
        return {"ok": True}, 200

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    async def scenario():
        with (
            patch.object(server, "launch_backup_process", side_effect=launch),
            patch.object(server.asyncio, "sleep", side_effect=fake_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await server.run_automatic_backup_scheduler(1800)

    asyncio.run(scenario())
    self.assertEqual(attempts, [1, 2])
    self.assertEqual(sleeps, [1800, 1800])
```

- [ ] **Step 2: Run the scheduler tests to verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_dashboard.DashboardTests.test_automatic_backup_interval_defaults_to_thirty_minutes \
  tests.test_dashboard.DashboardTests.test_automatic_backup_runs_immediately_then_waits \
  tests.test_dashboard.DashboardTests.test_automatic_backup_recovers_after_one_attempt_raises
```

Expected: FAIL because the interval reader and scheduler loop do not exist.

- [ ] **Step 3: Implement interval parsing and the scheduler loop**

Add `import logging` near the imports and define the logger and default near the other constants in `dashboard/server.py`:

```python
LOGGER = logging.getLogger(__name__)
DEFAULT_AUTO_BACKUP_INTERVAL_SECONDS = 30 * 60
```

Add these functions after `launch_backup_process()`:

```python
def automatic_backup_interval_seconds():
    raw_value = os.environ.get(
        "WEIBO_AUTO_BACKUP_INTERVAL_SECONDS",
        str(DEFAULT_AUTO_BACKUP_INTERVAL_SECONDS),
    )
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        LOGGER.warning(
            "Invalid WEIBO_AUTO_BACKUP_INTERVAL_SECONDS; using %s seconds",
            DEFAULT_AUTO_BACKUP_INTERVAL_SECONDS,
        )
        return float(DEFAULT_AUTO_BACKUP_INTERVAL_SECONDS)


async def run_automatic_backup_scheduler(interval_seconds):
    while True:
        try:
            payload, status_code = launch_backup_process()
            if not payload.get("ok"):
                LOGGER.warning(
                    "Automatic backup attempt skipped or failed (%s): %s",
                    status_code,
                    payload.get("message", "unknown error"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Automatic backup attempt failed unexpectedly")
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 4: Run the scheduler tests to verify GREEN**

Run the same three-test command from Step 2.

Expected: 3 tests pass. A single expected error log may be emitted by the recovery test.

- [ ] **Step 5: Write the failing FastAPI lifespan test**

Add this test to `DashboardTests`:

```python
def test_dashboard_lifespan_starts_and_cancels_scheduler(self):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    received_intervals = []

    async def scheduler(interval):
        received_intervals.append(interval)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def scenario():
        with (
            patch.object(server, "automatic_backup_interval_seconds", return_value=1800.0),
            patch.object(server, "run_automatic_backup_scheduler", side_effect=scheduler),
        ):
            async with server.dashboard_lifespan(None):
                await started.wait()
        self.assertTrue(cancelled.is_set())

    asyncio.run(scenario())
    self.assertEqual(received_intervals, [1800.0])
```

- [ ] **Step 6: Run the lifespan test to verify RED**

Run:

```bash
python3 -m unittest tests.test_dashboard.DashboardTests.test_dashboard_lifespan_starts_and_cancels_scheduler
```

Expected: FAIL because `dashboard_lifespan` does not exist.

- [ ] **Step 7: Attach the scheduler to FastAPI lifespan**

Add these imports in `dashboard/server.py`:

```python
from contextlib import asynccontextmanager, suppress
```

Define the lifespan before creating `app`, relying on normal runtime name resolution for the scheduler functions defined later in the module:

```python
@asynccontextmanager
async def dashboard_lifespan(_app):
    interval_seconds = automatic_backup_interval_seconds()
    scheduler_task = None
    if interval_seconds > 0:
        scheduler_task = asyncio.create_task(
            run_automatic_backup_scheduler(interval_seconds)
        )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task


app = FastAPI(title="微博备份监控", lifespan=dashboard_lifespan)
```

Remove the previous `app = FastAPI(title="微博备份监控")` assignment.

- [ ] **Step 8: Run scheduler, lifespan, and dashboard tests**

Run:

```bash
python3 -m unittest tests/test_dashboard.py
```

Expected: all dashboard tests pass.

- [ ] **Step 9: Commit the scheduler**

```bash
git add dashboard/server.py tests/test_dashboard.py
git commit -m "feat: run backups every thirty minutes"
```

### Task 3: Document Automatic Backup Operations

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update README behavior and deployment notes**

Add this feature bullet near the existing backup process controls:

```markdown
- 监控后台启动后立即尝试一次备份，之后默认每 30 分钟自动重试；已有备份运行或暂停时会跳过，不会创建重复进程。
```

Add the environment variable to the existing block:

```bash
WEIBO_AUTO_BACKUP_INTERVAL_SECONDS=1800
```

Add these paragraphs after the environment variable block:

```markdown
自动备份默认启用。`WEIBO_AUTO_BACKUP_INTERVAL_SECONDS` 使用秒为单位；设为 `0` 可以关闭。定时备份能减少 Cookie 长时间闲置，但微博仍可能主动使 Cookie 失效，此时需要通过备份设置页更新 Cookie。

自动定时器运行在 Uvicorn 进程内，部署时应保持单 worker；仓库的 `scripts/start_dashboard.sh` 默认就是单 worker。
```

- [ ] **Step 2: Update AGENTS.md architecture guidance**

Extend “启动监控后台” to mention `dashboard_lifespan()` and its scheduler side effect. Add this core business scenario after it:

```markdown
- **每 30 分钟自动备份**
  - 入口：`dashboard_lifespan()` -> `run_automatic_backup_scheduler()`
  - 核心逻辑：启动时立即调用 `launch_backup_process()`，之后按 `WEIBO_AUTO_BACKUP_INTERVAL_SECONDS` 间隔重试
  - 副作用：创建与手动启动相同的爬虫子进程和 `logs/backup.pid`；已有进程运行或暂停时跳过
  - 注意：默认间隔为 1800 秒，设为 `0` 可关闭；Uvicorn 应保持单 worker；服务关闭只取消定时器，不终止已经启动的爬虫进程
```

Add these global constraints:

```markdown
- 自动备份必须复用手动备份的配置校验和进程启动逻辑，不得绕过 Cookie 示例值检查，也不得并行启动第二个备份进程。
- 自动备份日志不得包含 Cookie 明文；单次触发失败不能终止后续调度。
```

- [ ] **Step 3: Check documentation consistency**

Run:

```bash
rg -n "WEIBO_AUTO_BACKUP_INTERVAL_SECONDS|每 30 分钟|单 worker|dashboard_lifespan" README.md AGENTS.md
git diff --check
```

Expected: both documents describe the 1800-second default, disable value `0`, single-worker rule, and lifespan scheduler; `git diff --check` exits 0.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md AGENTS.md
git commit -m "docs: explain automatic backup schedule"
```

### Task 4: Full Verification

**Files:**
- Verify only; no planned file changes

- [ ] **Step 1: Prepare the supported environment**

Run:

```bash
bash scripts/setup_nas.sh
source .venv/bin/activate
```

Expected: the root `.venv` exists and dependencies are installed without copying a virtual environment from another machine.

- [ ] **Step 2: Run all repository checks**

Run:

```bash
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_cookie_helper.py tests/test_sqlite_writer.py tests/test_page_parser_time.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py scripts/cookie_helper.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh scripts/start_cookie_helper.sh
```

Expected: every command exits 0 with no test failures or syntax errors.

- [ ] **Step 3: Review the final diff and repository state**

Run:

```bash
git diff HEAD~3 --check
git status --short
git log -4 --oneline
```

Expected: no whitespace errors; only the user's pre-existing unrelated untracked directory may remain; the design, implementation, and documentation commits are visible.
