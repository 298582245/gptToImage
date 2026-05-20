# AI Image Studio

原项目地址：<https://gitee.com/papamenu/gpt-text-to-image>，本项目基于该项目修改。
提示词感谢项目：<https://github.com/wukongnotnull/image-inspirer>

一个基于 Python + Flask 的生图工作台，使用 OpenAI Python SDK 调用官方图片生成接口，并兼容自定义 `Base URL`。

## 功能

- 支持自定义 `Base URL`
- 支持自定义 `API Key`
- 自定义接口仅在当前浏览器会话内暂存接口信息，不会长期保存 `API Key`
- 已内置默认 `Base URL`，`API Key` 需要用户自行填写或由管理员配置内置接口
- 支持自定义模型名
- 支持用户注册、登录、退出；管理员账号通过环境变量初始化或后台配置
- 管理员可配置内置接口、默认模型、单张图片积分价格、并发数和单用户排队上限
- 登录用户可使用内置接口提交异步生成任务，任务排队执行，失败自动退还预扣积分
- 内置接口生成的图片默认私有，只能所属用户和管理员查看
- 支持常见图片参数：`size`、`quality`、`background`、`output_format`、`style`、`n`
- 生成中的 loading 遮罩和动态进度条
- 生成后的图片会自动保存到本地 `generated/` 目录
- 公共历史记录画廊，所有访问者都能看到公开图片；登录用户可查看自己的生成记录
- 页面里可直接预览，并查看本次请求参数

## 运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

## Docker 部署

推荐使用 Docker Compose，以后每次 `git pull` 后只需重新构建并启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

停止服务：

```bash
docker compose down
```

`docker-compose.yml` 默认映射 `127.0.0.1:8090:8090`，挂载 `./generated` 和 `./data`，并设置 `BASE_PATH=/image-studio`、`OPENAI_BASE_URL=https://ai.wqwlkj.cn`。

如果通过 Nginx 反代到子路径，例如 `/image-studio/`，请保持 `BASE_PATH=/image-studio`。

## 环境变量（可选，会覆盖默认值）

- `OPENAI_BASE_URL`
- `OPENAI_IMAGE_MODEL`
- `INITIAL_ADMIN_USERNAME`
- `INITIAL_ADMIN_PASSWORD`

## 说明

- 默认按照 OpenAI 官方图片生成接口格式发起请求。
- 如果 `Base URL` 只填写域名，程序会自动补成 `/v1`。
- 如果你填入兼容 OpenAI API 的第三方 `Base URL`，也可以直接复用这个界面。
- `gpt-image-*` 模型通常返回 base64 图片数据。
- `dall-e-2` / `dall-e-3` 在官方接口中支持 `response_format`，这里统一请求 `b64_json` 以便保存到本地。
- 用户、图片记录和后续积分数据保存在 `data/app.sqlite3`；旧版 `data/history.json` 会在首次启动时迁移到公开图片记录。
- 设置 `INITIAL_ADMIN_USERNAME` 和 `INITIAL_ADMIN_PASSWORD` 后，启动时会创建或更新初始管理员，可访问 `/admin` 查看基础后台概览。
- 管理员在 `/admin` 配置内置接口后，用户可在首页选择“使用站内内置接口”，提交后去 `/my/jobs` 查看排队、生成中、已完成或失败状态。
- 内置接口密钥会加密保存到 `data/app.sqlite3`，加密密钥在 `data/fernet.key`，部署时请和数据库一起持久化备份。
- 当前异步队列使用应用内后台线程实现，适合单实例部署；如果服务器跑多个 Web 实例，建议下一步改为 Redis/RQ 或 Celery，避免多个实例重复处理队列。
- Dockerfile 已设置 Gunicorn 单 worker 多线程，避免应用内队列被多进程重复消费。
- 程序支持通过 `BASE_PATH` 部署到子路径，例如 `/image-studio`。
