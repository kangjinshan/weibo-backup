# NAS Deploy

这个仓库不带真实配置和已下载数据。复制到 NAS 后，先在 NAS 上生成本机 Python 环境和配置文件。

## 初始化

```bash
cd /path/to/weibo-backup
bash scripts/setup_nas.sh
```

`setup_nas.sh` 会：

- 创建根目录 `.venv`
- 安装 `requirements-nas.txt`
- 创建 `logs/` 和 `data/`
- 如果 `weiboSpider/config.json` 不存在，则从 `weiboSpider/config.example.json` 复制一份
- 清理旧的 `logs/*.pid`

## 配置账号

编辑：

```text
weiboSpider/config.json
```

至少需要改：

```json
{
  "user_id_list": ["你的微博用户ID"],
  "cookie": "你的微博 cookie",
  "sqlite_config": "../data/weibo.db"
}
```

`sqlite_config` 是相对 `weiboSpider/` 目录解析的路径。默认 `../data/weibo.db` 表示数据库在项目根目录的 `data/weibo.db`。

网页端只显示 cookie 是否已配置，不会回显真实 cookie。如果点击“启动备份”时提示 cookie 未配置或仍是示例值，可以在“备份设置”的“更新 Cookie”里粘贴新的 cookie 并保存，也可以回到 NAS 终端编辑 `weiboSpider/config.json`，把 `cookie` 从示例值替换为当前可用的微博登录 cookie。

获取可用 cookie：

1. 在自己的电脑浏览器登录微博网页。
2. 打开开发者工具的 Network/网络面板，刷新微博页面。
3. 点开任意发往 `weibo.com` 的请求，复制 Request Headers 里的完整 `Cookie` 值。
4. 在 NAS 监控页面“备份设置”中粘贴到“更新 Cookie”，或写入 `weiboSpider/config.json` 的 `cookie` 字段。

不要把 cookie 发到聊天、日志、截图或 Git 仓库里；它等同于当前微博登录态。

## 启动

```bash
bash scripts/start_dashboard.sh
```

默认监听：

```text
0.0.0.0:8765
```

部署检查：

```bash
curl http://127.0.0.1:8765/api/stats
curl http://127.0.0.1:8765/api/backup-config
```

如果启动备份失败，先看网页弹层提示；后台会在真正启动爬虫前检查 `user_id_list` 和 `cookie`，并把缺失配置作为 JSON 返回，避免浏览器出现 `Unexpected token` 一类的解析错误。

## Docker 启动

如果 NAS 自带 Python 版本太旧或缺少 SQLite 模块，可以用 Docker：

```bash
cd /path/to/weibo-backup
docker build -t weibo-backup-dashboard .
docker rm -f weibo-backup-dashboard 2>/dev/null || true
docker run -d \
  --name weibo-backup-dashboard \
  --restart unless-stopped \
  -p 8765:8765 \
  -v "$PWD:/app" \
  -w /app \
  weibo-backup-dashboard
```

访问：

```text
http://NAS_IP:8765/
```

默认镜像基于 `python:3.10-slim`。如果 NAS 拉取 DockerHub 较慢，可以先拉取可用镜像源里的 Alpine Python，再这样构建：

```bash
docker build --build-arg PYTHON_IMAGE=python:3.10-alpine -t weibo-backup-dashboard .
```

容器启动备份时会优先使用可执行且能真正启动的 Python。如果宿主机挂载目录里有旧的 `weiboSpider/venv/`，但容器内不可执行，后台会跳过它并改用容器 Python；也可以直接删除这些旧虚拟环境目录后重新部署。不要在 Docker 环境变量里把 `WEIBO_SPIDER_PYTHON` 指向 `/app/weiboSpider/venv/bin/python`。

如果要让后台直接在当前端口提供 HTTPS，启动容器时传入证书路径：

```bash
docker run -d \
  --name weibo-backup-dashboard \
  --restart unless-stopped \
  -p 8765:8765 \
  -v "$PWD:/app" \
  -w /app \
  -e WEIBO_DASHBOARD_SSL_CERTFILE=/app/certs/weibo.jinshanweb.com/fullchain.pem \
  -e WEIBO_DASHBOARD_SSL_KEYFILE=/app/certs/weibo.jinshanweb.com/privkey.pem \
  weibo-backup-dashboard
```

## 不需要复制或提交的内容

- `weiboSpider/config.json`
- `data/*.db`
- 账号目录，例如 `某微博昵称/`
- `img/`
- `video/`
- `logs/*`
- `.venv/`
- `dashboard/venv/`
- `weiboSpider/venv/`
- `__pycache__/`
- `.DS_Store`

这些内容已经在 `.gitignore` 中排除。
