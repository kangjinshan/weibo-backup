# weibo-backup

本项目是一个本地微博备份与监控工作区：用 `weiboSpider` 抓取微博内容、图片和视频，用 FastAPI 网页查看备份进度、配置增量备份、浏览本地微博归档。

仓库不包含任何已下载的微博数据、图片、视频、SQLite 数据库或真实 cookie。下载后先创建自己的 `weiboSpider/config.json`，再运行备份。

## 功能

- 首次访问监控后台时设置访问密码，之后必须登录才能访问 API、媒体文件和备份控制。
- 在网页弹层里配置账号、日期范围、是否下载图片/视频。
- 在启动备份前检查账号 ID 和 cookie 是否仍是示例值；页面可粘贴更新 cookie，不回显真实 cookie。
- 提供 Manifest V3 Chrome 插件，从当前浏览器读取微博 Cookie 并填入固定公网后台；插件不会显示、保存或自动提交 Cookie。
- 备份设置页支持 cookie 可用性检测（有效/疑似过期/未知）与“一键自动获取新 Cookie”；NAS/Docker 读不到本机 Chrome 时，可通过本机 `127.0.0.1` Cookie 助手自动写回新 cookie。
- 启动、暂停、继续、停止微博备份进程。
- 查看备份进度、日期日历、微博列表、本地图片和视频。
- 微博列表支持按“全部/仅原创”和“纯文字/文字+图片/文字+图片+视频”筛选。
- 支持图片点击预览、缩放、点空白关闭。
- 支持微博昵称主页链接和微博详情链接。
- 支持在 NAS 或普通 Linux/macOS 机器上创建独立 Python 环境部署。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `dashboard/` | FastAPI 监控后台与静态页面 |
| `chrome-extension/` | Chrome 微博 Cookie 填充插件及其无依赖单元测试 |
| `weiboSpider/` | 微博爬虫主体，含 `weibo_spider` 包和示例配置 |
| `scripts/` | 环境初始化、后台启动和本机 Cookie 助手脚本 |
| `tests/` | 本项目回归测试 |
| `data/` | 默认 SQLite 数据目录，仓库只保留 `.gitkeep` |
| `logs/` | 运行日志目录，仓库只保留 `.gitkeep` |

真实备份运行后，`weiboSpider` 会按账号昵称在项目根目录生成账号目录，例如：

```text
某微博昵称/
  1234567890.json
  1234567890.csv
  1234567890.txt
  img/
  video/
data/
  weibo.db
```

这些数据目录和资源文件都已被 `.gitignore` 排除。

## 快速部署

1. 创建环境并生成本地配置：

```bash
bash scripts/setup_nas.sh
```

2. 编辑 `weiboSpider/config.json`：

```json
{
  "user_id_list": ["你的微博用户ID"],
  "cookie": "你的微博 cookie",
  "sqlite_config": "../data/weibo.db"
}
```

保留 `write_mode` 中的 `sqlite`，否则网页无法从 SQLite 读取新微博。

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

1. 在自己的电脑浏览器登录微博网页。
2. 打开浏览器开发者工具的 Network/网络面板，刷新微博页面。
3. 找到发往 `weibo.com` 的请求，复制 Request Headers 里的完整 `Cookie` 请求头值。
4. 粘贴到网页“更新 Cookie”输入框或 `weiboSpider/config.json` 的 `cookie` 字段。

3. 启动监控后台：

```bash
bash scripts/start_dashboard.sh
```

默认监听：

```text
0.0.0.0:8765
```

打开：

```text
http://127.0.0.1:8765/
```

首次打开会要求设置访问密码。密码哈希和会话签名密钥会写入本地 `logs/dashboard-auth.json`，仓库不会提交该文件。后续访问后台、API 和本地媒体文件都需要先登录。

部署或更新后可以先访问 `/api/auth/status` 做烟测；如果登录时提示 `Not Found`，通常说明后台还在运行旧进程，需要重启 `scripts/start_dashboard.sh` 或对应容器/服务后再试。不要把临时初始密码写入 README、脚本、环境模板或任何会提交到 Git 的文件。

## Docker 部署

NAS 上如果系统 Python 太旧，推荐用 Docker：

```bash
docker build -t weibo-backup-dashboard .
docker run -d \
  --name weibo-backup-dashboard \
  --restart unless-stopped \
  -p 8765:8765 \
  -v "$PWD:/app" \
  -w /app \
  weibo-backup-dashboard
```

容器会读取宿主机项目目录里的 `weiboSpider/config.json`、账号数据目录和 SQLite 数据库。
默认镜像基于 `python:3.10-slim`。如果 NAS 拉取 DockerHub 较慢，也可以改用可用镜像源的 Alpine Python：

```bash
docker build --build-arg PYTHON_IMAGE=python:3.10-alpine -t weibo-backup-dashboard .
```

## 常用环境变量

```bash
WEIBO_DASHBOARD_HOST=0.0.0.0
WEIBO_DASHBOARD_PORT=8765
WEIBO_BACKUP_DIR=/path/to/weibo-backup
WEIBO_SPIDER_PYTHON=/path/to/weibo-backup/.venv/bin/python
WEIBO_DASHBOARD_SSL_CERTFILE=/path/to/fullchain.pem
WEIBO_DASHBOARD_SSL_KEYFILE=/path/to/privkey.pem
WEIBO_DASHBOARD_AUTH_PATH=/path/to/weibo-backup/logs/dashboard-auth.json
WEIBO_DASHBOARD_COOKIE_SECURE=1
```

设置 `WEIBO_DASHBOARD_SSL_CERTFILE` 和 `WEIBO_DASHBOARD_SSL_KEYFILE` 后，后台会直接以 HTTPS 方式监听 `WEIBO_DASHBOARD_PORT`。
如果通过 HTTPS 或反向代理暴露到公网，建议设置 `WEIBO_DASHBOARD_COOKIE_SECURE=1`，让浏览器只通过 HTTPS 发送登录 cookie。

## 数据同步

网页 API 读取 `weiboSpider/config.json` 中的 `sqlite_config`。默认示例配置使用：

```text
../data/weibo.db
```

如果手工修改了账号目录里的 `{user_id}.json`，可以用 JSON 重建 SQLite：

```bash
python3 sync_sqlite_from_json.py
```

## 时间与时区

微博发布时间按东八区 `Asia/Shanghai` 解析和保存。即使 Docker 容器或 NAS 系统默认时区是 UTC，爬虫遇到“刚刚”“几分钟前”“今天 06:26”或“06月01日 06:26”这类微博相对时间时，也会写入北京时间。

## 测试

运行以下命令前，请先在当前机器执行 `bash scripts/setup_nas.sh`，再运行 `source .venv/bin/activate` 激活脚本创建的、与当前架构兼容的根 `.venv`。不支持复制其他机器的虚拟环境后直接运行 `python3`。

```bash
node --test chrome-extension/tests/*.test.js
python3 -m unittest tests/test_chrome_extension.py tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_cookie_helper.py tests/test_sqlite_writer.py tests/test_page_parser_time.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py scripts/cookie_helper.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh scripts/start_cookie_helper.sh
```

## 注意事项

- 不要提交 `weiboSpider/config.json`，里面通常包含微博 cookie。
- 不要提交 `logs/dashboard-auth.json`；忘记访问密码时，停止后台后删除该文件并重启，即可重新走首次设置流程。
- 启动备份前，后台会检查 `user_id_list` 和 `cookie` 是否仍是示例值；真实 cookie 可以通过配置保存接口写入，但不会通过 API 返回给网页。
- 不要提交账号目录、`data/*.db`、`img/`、`video/`、`logs/` 和本机虚拟环境。
- 新机器不要复用复制来的旧 `dashboard/venv/` 或 `weiboSpider/venv/`，运行 `scripts/setup_nas.sh` 重新创建根目录 `.venv`。
- Docker 运行时不要依赖挂载目录里的旧 `weiboSpider/venv/`；后台启动爬虫会跳过不可执行或无法启动的 venv Python，改用容器当前 Python。不要把 `WEIBO_SPIDER_PYTHON` 指向 `/app/weiboSpider/venv/bin/python`。
- 备份默认以当前已备份的最近一天作为开始日期，以今天作为结束日期，适合每天做增量备份。
- 微博发布时间和增量备份保存的 `since_date` 使用东八区时间，不依赖容器默认本地时区。
