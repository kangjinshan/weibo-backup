# 微博 Cookie 填充 Chrome 插件设计

## 背景

微博备份监控已经提供“更新 Cookie”输入框和配置保存接口，但 NAS/Docker 无法直接读取用户电脑上的 Chrome Cookie。现有本机 Python Cookie 助手可以桥接该能力，不过需要用户启动并保持一个本地进程。

本次新增一个 Chrome Manifest V3 插件。插件从当前 Chrome 登录状态读取微博 Cookie，并将其填入固定微博备份后台页面的“更新 Cookie”字段。用户检查后仍需手动点击后台的保存按钮。

## 目标

- 从 `weibo.cn` 和 `weibo.com` 读取当前 Chrome 中仍然有效的 Cookie。
- 仅在 `https://weibo.jinshanweb.com:8765` 的微博备份后台中填充 Cookie。
- 通过插件弹窗中的单一操作完成读取和填入。
- Cookie 只在本次操作的内存和目标输入框中短暂流转。
- 保留后台现有手动保存与 Cookie 可用性检测流程。

## 非目标

- 插件不负责微博登录。
- 插件不自动保存或提交后台配置。
- 插件不保存后台密码，也不直接调用后台 API。
- 插件不支持用户配置其他后台地址。
- 插件不替换或删除现有本机 Python Cookie 助手；后者继续作为兼容备用方案。
- 插件不把 Cookie 写入剪贴板、扩展存储、浏览器日志、弹窗状态或错误信息；唯一允许的显示目的地是目标页面的 `#configCookieInput`。

## 用户流程

1. 用户在 Chrome 中登录微博。
2. 用户打开 `https://weibo.jinshanweb.com:8765`，登录微博备份后台并打开“备份设置”弹层。
3. 用户点击插件图标，在弹窗中点击“获取并填入”。
4. 插件读取并合并微博 Cookie，然后将结果写入后台的 `#configCookieInput` 文本框。
5. 插件提示“已填入，请检查并保存”，但不展示 Cookie 内容。
6. 用户在后台页面手动点击“保存设置”。后台继续负责验证 Cookie 并原子更新 `weiboSpider/config.json`。

## 插件结构

插件放在独立目录 `chrome-extension/`，与 FastAPI 后台和本机 Python 助手解耦。建议包含：

- `manifest.json`：Chrome 92+ 的 Manifest V3 清单和最小权限声明。
- `popup.html`：插件弹窗结构。
- `popup.css`：弹窗样式。
- `popup.js`：仅负责弹窗 UI、状态提示和用户操作。
- `popup-coordinator.js`：无 DOM 依赖的 Chrome API 协调、页面校验、注入和安全错误分类。
- `cookie-utils.js`：无 Chrome API 依赖的 Cookie 过滤、合并和序列化函数，便于单元测试。
- `tests/cookie-utils.test.js`：使用 Node 内置测试运行器验证纯函数行为。

不需要常驻后台 service worker。弹窗脚本在用户主动点击按钮时调用 `chrome.cookies` 和 `chrome.scripting`，完成后即结束。

## 权限边界

`manifest.json` 只申请以下权限：

- `cookies`：读取微博 Cookie，包括 HttpOnly Cookie。
- `activeTab`：只操作用户当前激活的页面。
- `scripting`：将填充函数注入当前后台页面。

主机权限仅包含：

- `https://*.weibo.cn/*`
- `https://*.weibo.com/*`
- `https://weibo.jinshanweb.com:8765/*`

插件在读取 Cookie 或执行注入前必须显式校验当前标签页 origin 等于 `https://weibo.jinshanweb.com:8765`。注入函数也必须在任何 DOM 查询或写入前再次校验页面 `location.origin`；即使标签页在两步之间导航或权限清单发生误配，也不能向其他页面填入 Cookie。

## Cookie 处理规则

插件分别通过 `chrome.cookies.getAll` 读取 `weibo.cn` 和 `weibo.com` Cookie，并应用以下规则：

1. 忽略 `expirationDate` 已早于当前时间的 Cookie；会话 Cookie 没有 `expirationDate`，予以保留。
2. 忽略名称为空的异常 Cookie。
3. 在每个域内按 Chrome 返回顺序保留第一个可用的同名 Cookie。
4. 将 `weibo.cn` 的去重结果覆盖到 `weibo.com` 的去重结果；同名 Cookie 优先采用 `weibo.cn` 的值，因为备份爬虫主要请求 `weibo.cn`。
5. 对名称排序后序列化为 `name=value; name2=value2`，使结果稳定且便于测试。
6. 如果最终没有 Cookie，停止操作并提示用户先登录微博。

插件不在弹窗、状态、日志或错误中显示 Cookie 字符串，也不把字符串传给非目标页面；唯一允许的显示目的地是目标页面的 `#configCookieInput`。

## 页面填充

插件确认当前标签页地址后，通过 `chrome.scripting.executeScript` 在页面中执行一个小型填充函数。该函数在任何 DOM 查询或写入前再次确认 `location.origin`，并且：

- 查找 `#configCookieInput`。
- 找不到时返回结构化失败结果，提示用户先打开“备份设置”。
- 找到后设置文本框的 `value`。
- 触发冒泡的 `input` 和 `change` 事件，以兼容当前页面及未来可能增加的表单监听逻辑。
- 只返回成功或失败状态，不返回 Cookie。

插件不会点击“保存设置”，也不会调用 `/api/backup-config`。

## 状态与错误处理

弹窗初始显示“获取并填入”按钮。操作期间禁用按钮并显示处理中状态，结束后恢复按钮。

错误按以下场景给出可操作提示：

- 当前页面不是指定后台：提示先打开微博备份后台。
- 后台设置弹层未打开：提示先打开“备份设置”。
- 未找到可用微博 Cookie：提示先登录或重新登录微博。
- Chrome 拒绝 Cookie 或页面权限：提示检查插件权限并重新加载插件。
- 页面注入或 Chrome API 调用失败：显示通用失败说明和不含敏感数据的错误类别。

任何状态和错误文案都不得包含 Cookie 名称、值或完整 Cookie 字符串。

## 安全约束

- 不使用 `chrome.storage`、`localStorage`、IndexedDB 或剪贴板保存 Cookie。
- 不调用 `console.log` 输出 Cookie 或包含 Cookie 的对象。
- 不把 Cookie 放入 URL、查询参数或页面 DOM 属性；唯一允许的显示目的地是现有更新输入框的 `value`，弹窗、状态、日志和错误也不得显示 Cookie 内容。
- 不保存后台密码或后台登录会话。
- 不自动提交配置，最终写入仍由用户在受登录会话保护的后台页面中确认。
- README 和 AGENTS.md 只描述使用方式和权限，不包含真实 Cookie 示例。

## 测试与验收

自动验证：

- 使用 Node 内置测试运行器验证过期过滤、会话 Cookie 保留、每域第一个同名项、`weibo.cn` 覆盖、稳定排序、空结果、页面内 origin 防护和 Chrome API 协调错误分类。
- 使用 Python 回归测试解析 `manifest.json`，确认 Chrome 92+、Manifest V3、权限和主机范围没有扩大。
- 检查插件源码不使用扩展存储或剪贴板 API。
- 继续运行仓库现有 Python、编译和 shell 语法验证命令。

Chrome 手工验收：

1. 以“加载已解压的扩展程序”安装 `chrome-extension/`。
2. 在未打开目标后台时点击插件，确认给出页面错误且不泄露 Cookie。
3. 打开后台但不打开设置弹层，确认提示先打开设置。
4. 登录微博并打开设置弹层，确认一次点击会填入字段。
5. 确认插件不会自动保存，必须由用户点击“保存设置”。
6. 保存后确认后台 Cookie 状态检测和备份启动流程仍正常。
7. 退出微博或清除微博 Cookie 后重试，确认插件提示未找到可用 Cookie。

## 文档更新

实现时同步更新 README.md 和 AGENTS.md：

- 将 Chrome 插件作为推荐的本机 Cookie 填充方式。
- 写明固定后台地址、安装步骤、使用步骤和权限范围。
- 保留本机 Python Cookie 助手的备用说明。
- 在目录导航、核心业务场景和验证命令中加入插件及其测试。

## 完成标准

- 用户无需启动本机 Python 进程即可把 Chrome 中的微博 Cookie 填入固定后台页面。
- Cookie 不被持久化、打印、复制或自动提交。
- 插件只对声明的微博域和固定后台域生效。
- 自动测试和 Chrome 手工验收全部通过。
- README.md 与 AGENTS.md 和实现保持一致。
