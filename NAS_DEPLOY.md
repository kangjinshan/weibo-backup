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
