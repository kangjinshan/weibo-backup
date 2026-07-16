# Weibo Cookie Chrome Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Chrome Manifest V3 extension that reads the user's current Weibo cookies and fills the existing Cookie field on the fixed Weibo backup dashboard without saving automatically.

**Architecture:** A UI-only popup delegates Chrome API coordination to a focused module, alongside a pure Cookie normalizer and page-injection function. The coordinator uses `chrome.cookies` only after a user click and exact-origin validation; the injected function repeats the origin check immediately before DOM access, then fills the already-open settings modal through `chrome.scripting`; the FastAPI backend remains unchanged.

**Tech Stack:** Chrome Extensions Manifest V3, browser JavaScript ES modules, Node built-in test runner, Python `unittest`, existing static FastAPI dashboard.

## Global Constraints

- The only supported dashboard origin is exactly `https://weibo.jinshanweb.com:8765`.
- Host permissions are limited to `https://*.weibo.cn/*`, `https://*.weibo.com/*`, and `https://weibo.jinshanweb.com:8765/*`.
- The extension must not store, log, display, copy, or place Cookie data in a URL.
- The only permitted display destination for the Cookie string is the existing `#configCookieInput` value; popup text, status text, logs, and errors must never display it.
- Chrome 92 or later is required by the manifest contract.
- The extension must not call `/api/backup-config`, click “保存设置”, or otherwise submit the configuration.
- The user must already be logged into Weibo and must open the dashboard's “备份设置” modal before filling.
- The existing Python Cookie helper remains available as a fallback and is not removed.
- Implementation documentation must update both `README.md` and `AGENTS.md`.
- No runtime npm dependencies are introduced.

---

## File Map

- `chrome-extension/manifest.json`: Manifest V3 metadata and exact Chrome permission boundary.
- `chrome-extension/package.json`: ES-module declaration and dependency-free Node test command.
- `chrome-extension/cookie-utils.js`: Pure filtering, merge-precedence, and serialization logic.
- `chrome-extension/page-fill.js`: Standalone function executed inside the dashboard tab.
- `chrome-extension/popup-coordinator.js`: DOM-free Chrome API coordinator with safe error codes.
- `chrome-extension/popup.html`: Accessible popup markup.
- `chrome-extension/popup.css`: Compact popup presentation and status states.
- `chrome-extension/popup.js`: Chrome API coordination, exact-origin validation, and safe user-facing errors.
- `chrome-extension/tests/cookie-utils.test.js`: Cookie normalization unit tests.
- `chrome-extension/tests/page-fill.test.js`: Page injection unit tests with a minimal fake DOM.
- `tests/test_chrome_extension.py`: Manifest, popup, and sensitive-API regression checks.
- `README.md`: Installation, use, privacy, fallback, and test instructions.
- `AGENTS.md`: Directory map, business scenario, security constraints, and verification commands.

---

### Task 1: Cookie Normalization Unit

**Files:**
- Create: `chrome-extension/package.json`
- Create: `chrome-extension/tests/cookie-utils.test.js`
- Create: `chrome-extension/cookie-utils.js`

**Interfaces:**
- Consumes: Chrome Cookie-shaped objects with `name: string`, `value: string`, and optional `expirationDate: number` fields.
- Produces: `buildCookieHeader(weiboCnCookies: object[], weiboComCookies: object[], nowSeconds?: number): string`. It returns a deterministic `name=value; name2=value2` string or `""` when no usable cookies exist.

- [ ] **Step 1: Add the ES-module test package declaration**

Create `chrome-extension/package.json`:

```json
{
  "name": "weibo-backup-cookie-filler",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test tests/*.test.js"
  }
}
```

- [ ] **Step 2: Write the failing Cookie normalization tests**

Create `chrome-extension/tests/cookie-utils.test.js`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import { buildCookieHeader } from "../cookie-utils.js";

const NOW = 2_000;

test("filters expired cookies and keeps session cookies", () => {
  const header = buildCookieHeader(
    [
      { name: "SESSION", value: "kept" },
      { name: "OLD", value: "discarded", expirationDate: NOW - 1 },
      { name: "FUTURE", value: "kept", expirationDate: NOW + 1 },
    ],
    [],
    NOW,
  );

  assert.equal(header, "FUTURE=kept; SESSION=kept");
});

test("prefers weibo.cn when both domains contain the same cookie name", () => {
  const header = buildCookieHeader(
    [{ name: "SUB", value: "cn-value" }],
    [{ name: "SUB", value: "com-value" }],
    NOW,
  );

  assert.equal(header, "SUB=cn-value");
});

test("includes unique cookies from both Weibo domains", () => {
  const header = buildCookieHeader(
    [{ name: "CN_ONLY", value: "cn" }],
    [{ name: "COM_ONLY", value: "com" }],
    NOW,
  );

  assert.equal(header, "CN_ONLY=cn; COM_ONLY=com");
});

test("sorts names and ignores malformed cookie records", () => {
  const header = buildCookieHeader(
    [
      { name: "z", value: "last" },
      { name: "", value: "empty-name" },
      { name: "a", value: "first" },
      { name: "NO_VALUE" },
      null,
    ],
    [],
    NOW,
  );

  assert.equal(header, "a=first; z=last");
});

test("returns an empty string when no usable cookies remain", () => {
  const header = buildCookieHeader(
    [{ name: "OLD", value: "discarded", expirationDate: NOW }],
    [],
    NOW,
  );

  assert.equal(header, "");
});
```

- [ ] **Step 3: Run the tests and verify the missing module failure**

Run:

```bash
node --test chrome-extension/tests/cookie-utils.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `chrome-extension/cookie-utils.js`.

- [ ] **Step 4: Implement the minimal Cookie normalizer**

Create `chrome-extension/cookie-utils.js`:

```javascript
function isUsableCookie(cookie, nowSeconds) {
  if (!cookie || typeof cookie.name !== "string" || cookie.name.length === 0) {
    return false;
  }
  if (typeof cookie.value !== "string") {
    return false;
  }
  return (
    typeof cookie.expirationDate !== "number" ||
    cookie.expirationDate > nowSeconds
  );
}

function mergeCookies(target, cookies, nowSeconds) {
  for (const cookie of cookies) {
    if (isUsableCookie(cookie, nowSeconds)) {
      target.set(cookie.name, cookie.value);
    }
  }
}

export function buildCookieHeader(
  weiboCnCookies,
  weiboComCookies,
  nowSeconds = Date.now() / 1_000,
) {
  const valuesByName = new Map();
  mergeCookies(valuesByName, weiboComCookies, nowSeconds);
  mergeCookies(valuesByName, weiboCnCookies, nowSeconds);

  return [...valuesByName.entries()]
    .sort(([leftName], [rightName]) =>
      leftName < rightName ? -1 : leftName > rightName ? 1 : 0,
    )
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
}
```

- [ ] **Step 5: Run the Cookie tests and verify they pass**

Run:

```bash
node --test chrome-extension/tests/cookie-utils.test.js
```

Expected: PASS, 5 tests passed and 0 failed.

- [ ] **Step 6: Commit the normalization unit**

```bash
git add chrome-extension/package.json chrome-extension/cookie-utils.js chrome-extension/tests/cookie-utils.test.js
git commit -m "feat: add weibo cookie normalization"
```

---

### Task 2: Chrome Popup and Dashboard Field Injection

**Files:**
- Create: `chrome-extension/tests/page-fill.test.js`
- Create: `chrome-extension/page-fill.js`
- Create: `tests/test_chrome_extension.py`
- Create: `chrome-extension/manifest.json`
- Create: `chrome-extension/popup.html`
- Create: `chrome-extension/popup.css`
- Create: `chrome-extension/popup.js`
- Test: `chrome-extension/tests/cookie-utils.test.js`

**Interfaces:**
- Consumes: `buildCookieHeader(weiboCnCookies, weiboComCookies, nowSeconds?)` from Task 1.
- Produces: `fillCookieInput(cookieHeader: string): {ok: true} | {ok: false, reason: "settings_closed"}`. The function writes only to `#configCookieInput` when `#backupModal.active` exists.
- Produces: A popup action that reads `weibo.cn` and `weibo.com`, validates the active tab origin, calls `fillCookieInput` through `chrome.scripting.executeScript`, and reports only non-sensitive status text.

- [ ] **Step 1: Write the failing page-injection tests**

Create `chrome-extension/tests/page-fill.test.js`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import { fillCookieInput } from "../page-fill.js";

function installFakeDom({ modalOpen = true, fieldPresent = true } = {}) {
  const events = [];
  const field = fieldPresent
    ? {
        value: "",
        dispatchEvent(event) {
          events.push({ type: event.type, bubbles: event.bubbles });
          return true;
        },
      }
    : null;
  const modal = {
    classList: {
      contains(name) {
        return name === "active" && modalOpen;
      },
    },
  };

  globalThis.document = {
    querySelector(selector) {
      if (selector === "#backupModal") return modal;
      if (selector === "#configCookieInput") return field;
      return null;
    },
  };
  globalThis.Event = class FakeEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.bubbles = Boolean(options.bubbles);
    }
  };

  return { field, events };
}

test.afterEach(() => {
  delete globalThis.document;
  delete globalThis.Event;
});

test("fills the Cookie field and emits input and change events", () => {
  const { field, events } = installFakeDom();

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: true });
  assert.equal(field.value, "SUB=secret");
  assert.deepEqual(events, [
    { type: "input", bubbles: true },
    { type: "change", bubbles: true },
  ]);
});

test("refuses to fill when the settings modal is closed", () => {
  const { field, events } = installFakeDom({ modalOpen: false });

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: false, reason: "settings_closed" });
  assert.equal(field.value, "");
  assert.deepEqual(events, []);
});

test("refuses to fill when the Cookie field is missing", () => {
  installFakeDom({ fieldPresent: false });

  const result = fillCookieInput("SUB=secret");

  assert.deepEqual(result, { ok: false, reason: "settings_closed" });
});
```

- [ ] **Step 2: Run the page-injection tests and verify the missing module failure**

Run:

```bash
node --test chrome-extension/tests/page-fill.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `chrome-extension/page-fill.js`.

- [ ] **Step 3: Implement the standalone page-injection function**

Create `chrome-extension/page-fill.js`:

```javascript
export function fillCookieInput(cookieHeader) {
  const modal = document.querySelector("#backupModal");
  const field = document.querySelector("#configCookieInput");
  if (!modal?.classList.contains("active") || !field) {
    return { ok: false, reason: "settings_closed" };
  }

  field.value = cookieHeader;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true };
}
```

- [ ] **Step 4: Run all JavaScript unit tests**

Run:

```bash
node --test chrome-extension/tests/*.test.js
```

Expected: PASS, 8 tests passed and 0 failed.

- [ ] **Step 5: Write the failing Manifest and security contract tests**

Create `tests/test_chrome_extension.py`:

```python
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
EXTENSION_DIR = ROOT / "chrome-extension"


class ChromeExtensionTests(unittest.TestCase):
    def test_manifest_uses_exact_manifest_v3_permissions(self):
        manifest = json.loads(
            (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(
            set(manifest["permissions"]),
            {"activeTab", "cookies", "scripting"},
        )
        self.assertEqual(
            set(manifest["host_permissions"]),
            {
                "https://*.weibo.cn/*",
                "https://*.weibo.com/*",
                "https://weibo.jinshanweb.com:8765/*",
            },
        )
        self.assertEqual(manifest["action"]["default_popup"], "popup.html")
        self.assertNotIn("background", manifest)

    def test_popup_exposes_only_manual_fill_controls(self):
        html = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")

        self.assertIn('id="fillCookieButton"', html)
        self.assertIn('id="status"', html)
        self.assertIn('type="module" src="popup.js"', html)
        self.assertNotIn("保存设置", html)

    def test_source_avoids_storage_clipboard_logging_and_backend_calls(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(EXTENSION_DIR.glob("*.js"))
        )

        for forbidden in (
            "chrome.storage",
            "localStorage",
            "indexedDB",
            "navigator.clipboard",
            "console.log",
            "fetch(",
            "/api/backup-config",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('document.querySelector("#backupModal")', source)
        self.assertIn('document.querySelector("#configCookieInput")', source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run the Python extension tests and verify the missing Manifest failure**

Run:

```bash
python3 -m unittest tests/test_chrome_extension.py
```

Expected: ERROR in `test_manifest_uses_exact_manifest_v3_permissions` because `chrome-extension/manifest.json` does not exist, with the other tests also failing until the popup files are created.

- [ ] **Step 7: Create the exact Manifest V3 permission boundary**

Create `chrome-extension/manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "微博备份 Cookie 填充器",
  "version": "1.0.0",
  "description": "把当前 Chrome 中的微博 Cookie 填入固定的微博备份后台。",
  "permissions": ["activeTab", "cookies", "scripting"],
  "host_permissions": [
    "https://*.weibo.cn/*",
    "https://*.weibo.com/*",
    "https://weibo.jinshanweb.com:8765/*"
  ],
  "action": {
    "default_title": "填入微博备份 Cookie",
    "default_popup": "popup.html"
  }
}
```

- [ ] **Step 8: Create the popup markup**

Create `chrome-extension/popup.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>微博备份 Cookie 填充器</title>
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <main>
    <h1>微博备份 Cookie</h1>
    <p class="description">读取当前 Chrome 的微博登录 Cookie，并填入已打开的备份设置。</p>
    <button id="fillCookieButton" type="button">获取并填入</button>
    <p id="status" class="status" role="status" aria-live="polite">
      请先登录微博，并打开备份后台的“备份设置”。
    </p>
  </main>
  <script type="module" src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 9: Create the popup styles**

Create `chrome-extension/popup.css`:

```css
:root {
  color-scheme: light;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #1f2937;
  background: #f8fafc;
}

body {
  width: 320px;
  margin: 0;
}

main {
  padding: 18px;
}

h1 {
  margin: 0 0 8px;
  font-size: 18px;
}

.description {
  margin: 0 0 16px;
  color: #526071;
  font-size: 13px;
  line-height: 1.5;
}

button {
  width: 100%;
  border: 0;
  border-radius: 8px;
  padding: 10px 14px;
  color: #ffffff;
  background: #e0443e;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

button:hover:not(:disabled) {
  background: #c93631;
}

button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.status {
  min-height: 38px;
  margin: 14px 0 0;
  color: #526071;
  font-size: 12px;
  line-height: 1.5;
}

.status.success {
  color: #147d3f;
}

.status.error {
  color: #b42318;
}
```

- [ ] **Step 10: Implement safe Chrome API coordination**

Create `chrome-extension/popup.js`:

```javascript
import { buildCookieHeader } from "./cookie-utils.js";
import { fillCookieInput } from "./page-fill.js";

const DASHBOARD_ORIGIN = "https://weibo.jinshanweb.com:8765";
const button = document.querySelector("#fillCookieButton");
const status = document.querySelector("#status");

const ERROR_MESSAGES = {
  wrong_page: "请先打开 https://weibo.jinshanweb.com:8765 的备份后台。",
  settings_closed: "请先在备份后台打开“备份设置”。",
  no_cookies: "未找到可用的微博 Cookie，请先登录或重新登录微博。",
  permission: "Chrome 未允许读取或填入，请检查插件权限并重新加载插件。",
  injection: "填入失败，请刷新备份后台后重试。",
  generic: "操作失败，请重新登录微博、刷新后台后重试。",
};

class OperationError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function showStatus(message, type = "") {
  status.textContent = message;
  status.className = type ? `status ${type}` : "status";
}

function setBusy(busy) {
  button.disabled = busy;
  button.textContent = busy ? "正在获取…" : "获取并填入";
}

function isTargetDashboard(tab) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") {
    return false;
  }
  try {
    return new URL(tab.url).origin === DASHBOARD_ORIGIN;
  } catch {
    return false;
  }
}

async function getActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  } catch {
    throw new OperationError("permission");
  }
}

async function getDomainCookies(domain) {
  try {
    return await chrome.cookies.getAll({ domain });
  } catch {
    throw new OperationError("permission");
  }
}

async function fillActiveDashboard(tabId, cookieHeader) {
  let injectionResults;
  try {
    injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: fillCookieInput,
      args: [cookieHeader],
    });
  } catch {
    throw new OperationError("injection");
  }

  const result = injectionResults?.[0]?.result;
  if (!result?.ok) {
    throw new OperationError(
      result?.reason === "settings_closed" ? "settings_closed" : "injection",
    );
  }
}

async function handleFill() {
  setBusy(true);
  showStatus("正在读取微博 Cookie…");
  try {
    const tab = await getActiveTab();
    if (!isTargetDashboard(tab)) {
      throw new OperationError("wrong_page");
    }

    const [weiboCnCookies, weiboComCookies] = await Promise.all([
      getDomainCookies("weibo.cn"),
      getDomainCookies("weibo.com"),
    ]);
    const cookieHeader = buildCookieHeader(weiboCnCookies, weiboComCookies);
    if (!cookieHeader) {
      throw new OperationError("no_cookies");
    }

    await fillActiveDashboard(tab.id, cookieHeader);
    showStatus("已填入，请检查并在后台手动保存。", "success");
  } catch (error) {
    const code = error instanceof OperationError ? error.code : "generic";
    showStatus(ERROR_MESSAGES[code] ?? ERROR_MESSAGES.generic, "error");
  } finally {
    setBusy(false);
  }
}

button.addEventListener("click", handleFill);
```

- [ ] **Step 11: Validate the Manifest and run all extension tests**

Run:

```bash
python3 -m json.tool chrome-extension/manifest.json >/dev/null
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py
```

Expected: all commands exit 0; Node reports 8 passed and Python reports 3 tests passed.

- [ ] **Step 12: Commit the working extension**

```bash
git add chrome-extension/manifest.json chrome-extension/page-fill.js chrome-extension/popup.html chrome-extension/popup.css chrome-extension/popup.js chrome-extension/tests/page-fill.test.js tests/test_chrome_extension.py
git commit -m "feat: add weibo cookie filler extension"
```

---

### Task 3: User Documentation and Full Verification

**Files:**
- Modify: `README.md:7-80`
- Modify: `README.md:160-167`
- Modify: `AGENTS.md:23-37`
- Modify: `AGENTS.md:83-95`
- Modify: `AGENTS.md:114-138`
- Include: `docs/superpowers/plans/2026-07-16-weibo-cookie-chrome-extension.md`

**Interfaces:**
- Consumes: The unpacked extension directory and exact security behavior delivered by Tasks 1 and 2.
- Produces: Installation and use instructions, an updated repository map, a maintained business scenario, and complete verification commands for future agents.

- [ ] **Step 1: Confirm the current documentation does not yet describe the extension**

Run:

```bash
rg -n "chrome-extension/|微博备份 Cookie 填充器" README.md AGENTS.md
```

Expected: exit 1 with no matches.

- [ ] **Step 2: Update README feature and directory summaries**

In `README.md`, add this feature bullet immediately after the existing manual Cookie bullet:

```markdown
- 提供 Manifest V3 Chrome 插件，从当前浏览器读取微博 Cookie 并填入固定公网后台；插件不会显示、保存或自动提交 Cookie。
```

Add this row to the directory table after `dashboard/`:

```markdown
| `chrome-extension/` | Chrome 微博 Cookie 填充插件及其无依赖单元测试 |
```

- [ ] **Step 3: Replace the primary Cookie acquisition instructions in README**

Replace the Cookie instructions beginning with `网页不会回显真实 cookie` and ending before `获取可用 cookie 的常用方式` with:

```markdown
网页不会回显真实 cookie。NAS 上如果启动备份提示 cookie 未配置或仍是示例值，可以使用仓库内的 Chrome 插件把当前浏览器的微博 Cookie 填入“备份设置”，再由你手动保存。

### 使用 Chrome 插件填入 Cookie

1. 在 Chrome 中登录 `weibo.cn` 或 `weibo.com`。
2. 打开 `chrome://extensions/`，启用“开发者模式”。
3. 点击“加载已解压的扩展程序”，选择本仓库的 `chrome-extension/` 目录。
4. 打开并登录 `https://weibo.jinshanweb.com:8765`，进入“备份设置”。
5. 点击“微博备份 Cookie 填充器”图标，再点击“获取并填入”。
6. 页面字段填入后，在后台手动点击“保存设置”。

插件权限只覆盖 `weibo.cn`、`weibo.com` 和固定后台 `https://weibo.jinshanweb.com:8765`。插件不会保存、显示、复制或自动提交 Cookie，也不保存后台密码。修改插件源码后，需要在 `chrome://extensions/` 中点击该插件的“重新加载”。

### 本机 Cookie 助手备用方案

如果无法安装插件，可以在正在使用 Chrome 的电脑上运行：

```bash
bash scripts/start_cookie_helper.sh
```

保持终端窗口打开，再回到备份设置页点击“自动获取新 Cookie”。页面会从本机 `http://127.0.0.1:8766` 读取已验证的微博 Cookie，并通过已登录的后台会话写回 NAS。助手只监听 `127.0.0.1`，不会把 Cookie 打印到日志。

### 手动获取 Cookie
```

Keep the existing four manual Network-panel steps under the new `### 手动获取 Cookie` heading.

- [ ] **Step 4: Add extension verification commands to README**

Replace the README test block with:

```bash
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_cookie_helper.py tests/test_sqlite_writer.py tests/test_page_parser_time.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py scripts/cookie_helper.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh scripts/start_cookie_helper.sh
```

- [ ] **Step 5: Update AGENTS.md directory navigation and test scope**

Add this row after `dashboard/static/`:

```markdown
| `chrome-extension/` | Chrome Cookie 填充插件 | Manifest V3 插件只读取微博域 Cookie，并填入固定后台已打开的 `#configCookieInput`；不保存、不显示、不自动提交 Cookie |
```

Replace the existing `tests/` row with:

```markdown
| `tests/` | 回归测试 | 覆盖 Chrome 插件权限、后台配置、Cookie 助手、列表排序、媒体同步、SQLite 迁移和 writer 兼容 |
```

- [ ] **Step 6: Add the Chrome extension business scenario to AGENTS.md**

Insert this scenario immediately before “启动本机 Cookie 助手”:

```markdown
- **用 Chrome 插件填入微博 Cookie**
  - 入口：`chrome-extension/manifest.json` -> `popup.html` -> `popup.js`
  - 核心逻辑：`buildCookieHeader()` 过滤并合并 `weibo.cn` / `weibo.com` Cookie；`fillCookieInput()` 只向固定后台已打开的 `#configCookieInput` 填值
  - 副作用：只更新当前页面内存中的输入框值；不会自动调用后台保存接口，用户必须手动保存
  - 注意：插件权限只允许微博域和 `https://weibo.jinshanweb.com:8765`；不得存储、打印、显示、复制 Cookie，也不得保存后台密码
```

- [ ] **Step 7: Add extension security and verification rules to AGENTS.md**

Add this global constraint after the existing frontend Cookie rule:

```markdown
- Chrome 插件只允许读取 `weibo.cn` / `weibo.com` Cookie，并向 `https://weibo.jinshanweb.com:8765` 已打开的更新字段填值；不得使用扩展存储、剪贴板、日志或 URL 保存/传递 Cookie，不得自动提交配置。
```

Replace the common verification block with:

```bash
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_cookie_helper.py tests/test_sqlite_writer.py tests/test_page_parser_time.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py scripts/cookie_helper.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh scripts/start_cookie_helper.sh
```

- [ ] **Step 8: Run automated extension and repository verification**

Run:

```bash
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_cookie_helper.py tests/test_sqlite_writer.py tests/test_page_parser_time.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py scripts/cookie_helper.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh scripts/start_cookie_helper.sh
git diff --check
```

Expected: Node reports 8 passed; Python reports all tests passed; compilation, JSON parsing, shell syntax, and diff checks exit 0.

- [ ] **Step 9: Perform the Chrome acceptance check**

In Chrome:

1. Open `chrome://extensions/`, enable Developer mode, and load `chrome-extension/` unpacked.
2. Click the extension while a non-dashboard tab is active; expect the fixed-dashboard guidance and no Cookie output.
3. Open `https://weibo.jinshanweb.com:8765` without opening settings; click the extension and expect the “备份设置” guidance.
4. Log into Weibo, open the dashboard settings modal, and click “获取并填入”; expect `#configCookieInput` to receive a value and the popup to show “已填入，请检查并在后台手动保存。”
5. Confirm no save request occurs until manually clicking “保存设置”.
6. Clear or log out of Weibo, retry, and expect the no-Cookie guidance without any Cookie text.

- [ ] **Step 10: Commit documentation and the implementation plan**

```bash
git add README.md AGENTS.md docs/superpowers/plans/2026-07-16-weibo-cookie-chrome-extension.md
git commit -m "docs: explain chrome cookie filler"
```
