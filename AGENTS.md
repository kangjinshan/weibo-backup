# AGENTS.md

## 系统概述

`weibo-backup` 是一个可公开发布的本地微博备份工作区。它用 `weiboSpider` 抓取微博内容、图片和视频，用 FastAPI 网页监控备份进度、配置增量备份，并浏览本地归档。

仓库不包含真实微博数据、媒体文件、SQLite 数据库或 cookie。真实运行配置来自本地 `weiboSpider/config.json`，公开仓库只提交 `weiboSpider/config.example.json`。

业务边界：

- 负责本地备份、备份状态监控、网页浏览和 NAS 部署。
- 不负责微博账号登录流程本身；认证依赖用户自行填写 `weiboSpider/config.json` 中的 cookie。
- 不负责云端存储同步；账号目录、`data/*.db`、图片和视频都是本地运行产物，不应提交到 Git。

主要技术栈：

- Python 3
- FastAPI / Uvicorn：`dashboard/server.py`
- 原始爬虫包：`weiboSpider/weibo_spider`
- SQLite：`sqlite_store.py`、`weiboSpider/weibo_spider/writer/sqlite_writer.py`
- 静态前端：`dashboard/static/index.html`

## 目录导航

| 目录 | 职责 | 关键说明 |
| --- | --- | --- |
| `dashboard/` | 监控后台与 API | `server.py` 暴露统计、微博列表、媒体文件、备份配置和进程控制接口 |
| `dashboard/static/` | 单页监控界面 | `index.html` 内含日历、微博列表筛选、备份弹层、图片灯箱和自动刷新逻辑 |
| `weiboSpider/` | 微博爬虫主体 | 包含上游爬虫源码、示例配置和写入逻辑；`config.json` 为本地私密文件，不提交 |
| `weiboSpider/weibo_spider/` | 抓取、解析、下载、写入核心包 | `spider.py` 调度解析器、下载器和 writers |
| `scripts/` | 部署与启动脚本 | `setup_nas.sh` 创建根 `.venv`；`start_dashboard.sh` 启动 Uvicorn |
| `tests/` | 回归测试 | 覆盖后台配置、列表排序、媒体同步、SQLite 迁移和 writer 兼容 |
| `data/` | 默认数据库目录 | 只提交 `.gitkeep`；真实 `*.db` 不提交 |
| `logs/` | 运行日志目录 | 只提交 `.gitkeep`；真实日志不提交 |
| `Dockerfile` | 容器部署 | 只安装依赖；运行时挂载项目目录到 `/app` |

本地虚拟环境如 `.venv/`、`dashboard/venv/`、`weiboSpider/venv/` 都是可重建依赖产物，不应作为源码维护。

## 核心业务场景

- **初始化部署**
  - 入口：`scripts/setup_nas.sh`
  - 核心逻辑：创建 `.venv`、安装 `requirements-nas.txt`、创建 `logs/` 和 `data/`
  - 副作用：如果 `weiboSpider/config.json` 不存在，会从 `weiboSpider/config.example.json` 复制一份

- **启动监控后台**
  - 入口：`scripts/start_dashboard.sh`
  - 核心逻辑：启动 `dashboard.server:app`
  - 副作用：监听 `WEIBO_DASHBOARD_HOST` / `WEIBO_DASHBOARD_PORT`，读取 `WEIBO_BACKUP_DIR`

- **Docker 部署**
  - 入口：`Dockerfile`
  - 核心逻辑：构建 Python 3.10 运行环境，容器启动时执行 `scripts/start_dashboard.sh`
  - 副作用：生产运行时应通过 `-v "$PWD:/app"` 挂载项目目录，避免把真实数据打进镜像

- **读取备份统计**
  - 入口：`GET /api/stats` -> `dashboard.server.stats`
  - 核心逻辑：`get_stats()`、`sqlite_store.count_weibos()`、`find_user_dir()`
  - 副作用：微博数量来自 `sqlite_config` 指向的 SQLite；媒体大小遍历本地账号目录

- **浏览微博列表**
  - 入口：`GET /api/weibo` -> `dashboard.server.weibo_list`
  - 核心逻辑：`sqlite_store.fetch_weibos()`、`with_local_media_urls()`
  - 副作用：根据 `publish_time` 正序返回，支持 `post_type` 和 `media_type` 筛选，并给图片/视频补本地 `/media/...` URL

- **访问本地媒体文件**
  - 入口：`GET /media/{media_path:path}` -> `dashboard.server.media`
  - 核心逻辑：`media_url()`、`get_local_picture_urls()`、`get_local_video_url()`
  - 副作用：只允许返回 `WEIBO_BACKUP_DIR` 目录内的真实文件

- **保存网页备份配置**
  - 入口：`POST /api/backup-config` -> `dashboard.server.save_backup_config`
  - 核心逻辑：`sanitize_backup_config()`、`write_json_atomic()`
  - 副作用：备份旧 `weiboSpider/config.json` 为本地 `.before-dashboard-*` 文件，再写入新配置；这些备份文件不提交

- **启动/暂停/继续/停止备份**
  - 入口：`POST /api/backup/start|pause|resume|stop`
  - 核心逻辑：`spider_command()`、`get_backup_process_status()`、`signal_backup_process()`
  - 副作用：创建或读取 `logs/backup.pid`，通过进程组信号控制爬虫

- **运行原始微博抓取**
  - 入口：`python -m weibo_spider --config_path=... --output_dir=...`
  - 核心逻辑：`weiboSpider/weibo_spider/spider.py`
  - 副作用：按 `write_mode` 写入账号目录和 `sqlite_config` 指向的数据库

- **以 JSON 重建 SQLite**
  - 入口：`sync_sqlite_from_json.py`
  - 核心逻辑：`backup_paths.resolve_archive_paths()`、`sqlite_store.replace_from_json()`
  - 副作用：删除并重建目标 SQLite 中的 `user` 与 `weibo` 表内容

## 全局设计约束

- `weiboSpider/config.json` 是本地私密文件，可能包含 cookie，不能提交、打印到日志或写入文档。
- 公开仓库使用 `weiboSpider/config.example.json` 作为配置模板。
- 默认 SQLite 路径是 `../data/weibo.db`，该路径相对 `weiboSpider/` 目录解析。
- 当前备份配置 `write_mode` 应包含 `sqlite`，否则网页无法读取新微博。
- JSON 写入必须使用临时文件替换方式，避免半写入损坏主数据。
- 媒体文件路径在 JSON 中应使用相对路径，不要写入本机绝对路径。
- 后台默认只寻找根目录下包含 JSON 的账号目录；`dashboard/`、`logs/`、`scripts/`、`tests/`、`weiboSpider/`、`data/` 等服务目录必须排除。
- 不要提交账号目录、`data/*.db`、`img/`、`video/`、日志、pid 文件或虚拟环境。
- 备份进程控制依赖 pid 文件和 POSIX 信号；修改启动/停止逻辑后必须验证 paused/running/stopped 状态。

## 常用验证命令

```bash
python3 -m unittest tests/test_sqlite_store.py tests/test_backup_paths.py tests/test_dashboard.py tests/test_sqlite_writer.py
python3 -m py_compile sqlite_store.py sync_sqlite_from_json.py backup_paths.py dashboard/server.py
bash -n scripts/setup_nas.sh scripts/start_dashboard.sh
```

后台接口烟测：

```bash
curl http://127.0.0.1:8765/api/stats
curl http://127.0.0.1:8765/api/backup-config
```

## AGENTS 维护规则

- 修改代码、配置模板、脚本、部署流程或数据路径时，必须同步更新 `README.md` 和本文件。
- 新增长期维护脚本或源码目录时，必须补充目录导航和核心业务场景。
- 删除或重命名文件后必须清理失效引用。
- 只有用户明确要求跳过文档维护时，才可以不更新 `AGENTS.md`。
