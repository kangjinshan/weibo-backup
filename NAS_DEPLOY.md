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
