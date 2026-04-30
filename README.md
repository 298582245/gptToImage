# AI Image Studio

一个基于 Python + Flask 的生图工作台，使用 OpenAI Python SDK 调用官方图片生成接口，并兼容自定义 `Base URL`。

## 功能

- 支持自定义 `Base URL`
- 支持自定义 `API Key`
- 已内置默认 `Base URL` 和 `API Key`
- 支持自定义模型名
- 支持常见图片参数：`size`、`quality`、`background`、`output_format`、`style`、`n`
- 生成中的 loading 遮罩和动态进度条
- 生成后的图片会自动保存到本地 `generated/` 目录
- 公共历史记录画廊，所有访问者都能看到已经生成的图片
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

```bash
docker build -t gpt-text-to-image:latest .
docker run -d \
  --name gpt-text-to-image \
  -p 127.0.0.1:8090:8090 \
  -e BASE_PATH=/image-studio \
  -v $(pwd)/generated:/app/generated \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  gpt-text-to-image:latest
```

如果通过 Nginx 反代到子路径，例如 `/image-studio/`，请设置 `BASE_PATH=/image-studio`。

## 环境变量（可选，会覆盖默认值）

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_IMAGE_MODEL`

## 说明

- 默认按照 OpenAI 官方图片生成接口格式发起请求。
- 如果 `Base URL` 只填写域名，程序会自动补成 `/v1`。
- 如果你填入兼容 OpenAI API 的第三方 `Base URL`，也可以直接复用这个界面。
- `gpt-image-*` 模型通常返回 base64 图片数据。
- `dall-e-2` / `dall-e-3` 在官方接口中支持 `response_format`，这里统一请求 `b64_json` 以便保存到本地。
- 共享历史记录保存在 `data/history.json`。
- 程序支持通过 `BASE_PATH` 部署到子路径，例如 `/image-studio`。
