# 操作日志

- 时间: 2026-05-01 21:16 (UTC+8)
- 执行者: Codex
- 任务: 成功生图后保存自定义 API 密钥到 localStorage.
- 修改: templates/index.html.
- 验证: compileall 通过, node --check 通过.

- 时间: 2026-05-01 21:47 (UTC+8)
- 执行者: Codex
- 任务: 保存自定义模型配置; 新增用户登录, 退出和管理员; 引入 SQLite 图片历史.
- 修改: app.py, templates/index.html, templates/auth.html, templates/my_images.html, templates/admin.html, README.md.
- 验证: compileall, node --check, Flask test client 通过; 临时用户已清理.
- 工具降级: sequential-thinking 和 code-index 不可用, 使用 rg, PowerShell, apply_patch.
- conversationId: NOT_FOUND; 未提供 task_marker.

- 时间: 2026-05-01 22:18 (UTC+8)
- 执行者: Codex
- 任务: 完成管理员内置接口配置, 积分扣费与退款, 异步生成任务, 用户任务列表和私有图片隔离.
- 修改: app.py, templates/index.html, templates/admin.html, templates/my_jobs.html, templates/my_images.html, README.md, requirements.txt, Dockerfile.
- 验证: 仅执行静态检查; py_compile/ast 通过, 抽取前端 script 后 node --check 通过. 未安装依赖, 未启动项目.
- conversationId: NOT_FOUND; 未提供 task_marker.

- 时间: 2026-05-01 22:25 (UTC+8)
- 执行者: Codex
- 任务: 在 README.md 补充原项目地址和基于原项目修改说明。
- 验证: 静态文本修改，未运行项目。
- conversationId: NOT_FOUND; 未提供 task_marker.

- 时间: 2026-05-01 22:35 (UTC+8)
- 执行者: Codex
- 任务: 修复内置接口模式下生成按钮不可点问题; 内置模式隐藏模型选择和自定义接口字段.
- 修改: templates/index.html.
- 验证: 仅静态检查; py_compile/ast 通过, 抽取前端 script 后 node --check 通过.
- conversationId: NOT_FOUND; 未提供 task_marker.

- 时间: 2026-05-01 22:45 (UTC+8)
- 执行者: Codex
- 任务: 新增 docker-compose.yml, 将默认 Base URL 改为 https://ai.wqwlkj.cn, 更新 README Docker Compose 部署说明.
- 修改: app.py, templates/index.html, docker-compose.yml, README.md.
- 验证: 仅静态检查; py_compile/ast 通过, 文件读取和关键字检索通过.
- conversationId: NOT_FOUND; 未提供 task_marker.

- 时间: 2026-05-01 22:55 (UTC+8)
- 执行者: Codex
- 任务: 将页面内错误和 flash 提示卡片改为统一弹窗.
- 修改: templates/_modal_messages.html, templates/index.html, templates/auth.html, templates/admin.html, templates/my_jobs.html.
- 验证: 仅静态检查; py_compile/ast 通过, 抽取前端 script 后 node --check 通过.
- conversationId: NOT_FOUND; 未提供 task_marker.


## 2026-05-02 17:06（UTC+8） Codex
- 任务：排查 Nginx 502/504 与内置接口后台失败问题。
- 操作：将自定义接口生成改为异步任务，新增 custom_generation_jobs 队列、/jobs/<token> 状态页与 /api/jobs/<token> 轮询接口；修复后台 worker 完成内置任务时复用传入 SQLite 连接，避免 Flask 请求上下文依赖；自定义任务完成/失败后清空暂存 API Key。
- 静态检查：执行 git diff --check，通过；Python 解释器在当前 sandbox 中不可访问，未执行 py_compile。
- 说明：未安装依赖，未启动项目，未运行 Docker。

## 2026-05-02 17:08（UTC+8） Codex
- 补充验证：已通过授权执行静态语法检查 python -m py_compile app.py，结果通过；未启动项目，未安装依赖。

## 2026-05-02 17:11（UTC+8） Codex
- 任务：修复内置接口扣费成功后报 Working outside of application context。
- 操作：为 generation_worker_loop 添加 app.app_context，并为 process_generation_job/process_custom_generation_job 增加 has_app_context 兜底。
- 验证：仅做关键代码静态查看；按用户要求未执行依赖安装、项目启动或本机环境检查。

## 2026-05-02 18:08（UTC+8） Codex
- 任务：修复旧 SQLite 库启动时报 no such column: access_token。
- 操作：移除 executescript 内对新列 access_token 的索引创建，改为 ensure_column 之后单独创建 idx_images_access_token。
- 验证：按用户要求未执行本机环境检查。

## 2026-05-02 18:59（UTC+8） Codex
- 任务：修复自定义任务页不自动刷新，拆分管理员后台并增加侧栏。
- 操作：custom_job.html 改为活跃任务 5 秒强制刷新并附带时间戳；新增 admin_layout/admin_dashboard/admin_provider/admin_users/admin_jobs 模板；新增 /admin/provider、/admin/users、/admin/jobs 路由；后台任务列表合并内置与自定义任务，隐藏 API 和 Key。
- 验证：按用户要求仅做关键代码静态查看，未执行依赖安装、项目启动或本机环境检查。

## 2026-05-02 19:17（UTC+8） Codex
- 任务：调整管理员概览与新增图片审核能力。
- 操作：admin 概览最近任务/图片改为 5 条；最近图片改显示路径；新增 /admin/images 图片审核页和侧栏入口，管理员可查看公开与私有图片记录。
- 验证：仅做模板与路由引用静态查看，未执行项目启动或依赖检查。

## 2026-05-02 19:36（UTC+8） Codex
- 任务：调整管理员用户管理与任务列表分页。
- 操作：用户列表移除独立积分调整表单，改为每行编辑积分/密码、禁用/启用、删除；新增用户禁用字段迁移和禁用会话清理；用户编辑积分写入积分流水；任务列表新增每页条数选择、上一页/下一页和页码跳转。
- 修改：app.py, templates/admin_layout.html, templates/admin_users.html, templates/admin_jobs.html。
- 验证：按用户要求仅做代码文本静态查看；未安装依赖，未启动项目，未运行 Docker。

## 2026-05-02 19:38（UTC+8） Codex
- 任务：删除废弃 templates/admin.html 旧积分表单页，避免继续引用已移除的后台路由。
- 验证：仅用 rg 关键引用做文本检查，未找到旧积分路由的代码入口。

## 2026-05-02 19:45（UTC+8） Codex
- 任务：将管理员用户编辑从行内表单改为弹窗。
- 操作：用户列表行仅保留编辑、禁用和删除按钮；点击编辑打开弹窗修改积分和密码。
- 修改：templates/admin_users.html。
- 验证：按用户要求仅做文本静态检查，未运行项目。

## 2026-05-02 20:18（UTC+8） Codex
- 任务：新增卡密充值积分功能。
- 操作：新增 redeem_codes、redeem_code_uses、recharge_settings 数据表；支持单人一次卡和多人上限卡；用户可输入卡密充值；管理员可批量生成、软删卡密并配置充值公告。
- 修改：app.py, templates/index.html, templates/admin_layout.html, templates/recharge.html, templates/admin_redeem_codes.html。
- 验证：仅做 rg 引用和关键代码文本检查；未安装依赖，未启动项目，未运行 Docker。

## 2026-05-02 20:45（UTC+8） Codex
- 任务：修复后台分页每页条数切换不保持，并优化卡密管理页布局。
- 操作：用户页开放 10/20/50/100 条分页并保持 per_page；任务页切换每页条数回到第 1 页并保持 per_page；卡密页生成表单改为弹窗，卡密列表和最近使用记录改为 Tab 切换。
- 修改：app.py, templates/admin_users.html, templates/admin_jobs.html, templates/admin_redeem_codes.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 20:55（UTC+8） Codex
- 任务：移除三个后台页面顶部每页条数下拉框，避免与底部分页器状态不同步。
- 操作：/admin/users、/admin/jobs、/admin/redeem-codes 顶部仅保留统计文字；底部 per_page 下拉框切换时自动回到第 1 页并提交。
- 修改：templates/admin_users.html, templates/admin_jobs.html, templates/admin_redeem_codes.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 21:08（UTC+8） Codex
- 任务：精简首页布局，将卡密充值公告编辑改为弹窗。
- 操作：删除首页左侧新建创作、连接配置、本次参数、共享画廊等侧栏内容和主容器双列布局；删除顶部 OpenAI Compatible/Public Gallery 标签；管理端充值公告改成点击“编辑公告”后在弹窗内修改。
- 修改：templates/index.html, templates/admin_redeem_codes.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 21:31（UTC+8） Codex
- 任务：按 image-inspirer-main 案例库接入本地提示词灵感润色。
- 操作：新增本地 image-inspirer 分类路由表、案例读取和风格要点提取逻辑；将现有 polish_prompt 升级为基于灵感分类的 effective_prompt 生成；首页增加润色分类下拉和来源链接 https://github.com/wukongnotnull/image-inspirer。
- 修改：app.py, templates/index.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:05（UTC+8） Codex
- 任务：将图片审核页改为可隐藏违规图片，并支持可选封禁所属账号。
- 操作：新增管理员隐藏/恢复图片 POST 路由；隐藏图片使用 images.visibility='hidden'，仅管理员可访问；用户侧图片、任务图片列表过滤 hidden；审核页增加状态、隐藏、恢复、同时封禁用户操作。
- 修改：app.py, templates/admin_images.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:12（UTC+8） Codex
- 任务：图片审核封禁账号时禁止封禁管理员账号。
- 操作：管理员图片列表查询补充用户 is_admin；后端隐藏图片时即使提交 ban_user 也跳过管理员账号；前端不再为管理员图片显示“同时封禁用户”选项。
- 修改：app.py, templates/admin_images.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:18（UTC+8） Codex
- 任务：静态审计图片审核隐藏/封禁接口的管理员权限链路。
- 操作：检查 admin_required、validate_csrf_token、admin_image_hide、admin_image_restore 与隐藏图片访问控制；确认隐藏/恢复接口均为 POST、带管理员装饰器和 CSRF 校验，ban_user 仅在通过管理员校验后处理。
- 修改：无业务代码修改，仅追加审计日志。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:27（UTC+8） Codex
- 任务：将提示词润色后的实际提示词展示给用户。
- 操作：首页结果卡片、公共画廊、内置接口任务详情/列表、自定义任务详情、我的图片页面均在 prompt_polished 时显示 effective_prompt。
- 修改：templates/index.html, templates/my_jobs.html, templates/custom_job.html, templates/my_images.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:46（UTC+8） Codex
- 任务：新增管理员配置的 AI 提示词润色接口，并让内置接口生图先确认润色结果。
- 操作：provider_configs 增加润色接口配置字段和迁移；后台内置接口页增加润色 Base URL/API Key/模型/启用项；内置接口开启润色时先调用 AI 润色并展示确认面板，确认后才扣积分提交任务；自定义接口继续使用本地规则润色；本地规则润色改成直接输出最终生图提示词。
- 修改：app.py, templates/admin_provider.html, templates/index.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 22:55（UTC+8） Codex
- 任务：自定义接口开启提示词润色时也必须先给用户确认。
- 操作：create_custom_job 改为优先使用用户确认后的 confirmed_effective_prompt；新增本地润色预览 build_custom_polish_preview；首页提交逻辑在自定义接口开启润色时先展示确认面板，用户确认后才创建自定义生成任务；确认面板文案改为同时适配 AI 润色和本地润色。
- 修改：app.py, templates/index.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 23:02（UTC+8） Codex
- 任务：隐藏润色实现差异文案，并增加重新润色入口。
- 操作：首页润色说明改为通用确认提示，不再说明自定义/内置分别使用什么润色方式；确认面板不显示 AI/本地标签；新增 polish_action=repolish 分支，点击“重新润色”可在当前表单直接重新生成润色结果，不提交生图任务。
- 修改：app.py, templates/index.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 23:18（UTC+8） Codex
- 任务：优化自动分类策略，并为站内 AI 润色增加可配置积分价格。
- 操作：自动分类未命中时不再落到“其他应用场景”；内置 AI 润色在自动模式下让模型自行判断视觉方向，手动分类才作为强制方向；自定义本地润色识别不到分类时不写方向；provider_configs 增加 polish_price，后台可设置每次润色积分且默认 0；站内内置润色要求登录并按 polish_price 扣积分，价格为 0 时不扣费。
- 修改：app.py, templates/admin_provider.html, templates/index.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 23:31（UTC+8） Codex
- 任务：增加用户积分消耗记录，并核对多张图片扣费逻辑。
- 操作：新增 /my/credits 用户积分记录页，读取 credit_ledger 并区分图片生成、提示词润色、充值、退款、管理员调整；首页、我的任务、我的图片、充值页增加积分记录入口；图片生成扣费流水改为记录“单价 × 张数”，现有扣费逻辑为 price_per_image * requested_n。
- 修改：app.py, templates/my_credits.html, templates/index.html, templates/my_jobs.html, templates/my_images.html, templates/recharge.html。
- 验证：仅做文本静态检查，未运行项目。

## 2026-05-02 23:37（UTC+8） Codex
- 任务：润色确认结果出现后自动滚动到提示框。
- 操作：首页润色确认面板增加 polish-preview-panel 锚点；页面加载时检测到该面板后自动 smooth scroll 到确认区域，避免用户看不到润色后的提示词。
- 修改：templates/index.html。
- 验证：仅做文本静态检查，未运行项目。
## 2026-05-03 19:29（Codex）
- 动作：修复图片公开规则与首页移动端适配。
- 工具：`rg`、`Get-Content`、`apply_patch`，仅做静态核对，未安装依赖、未运行项目。
- 变更：`generation_jobs` 增加 `publish_to_gallery` 字段；内置接口默认私有，可由用户勾选公开；自定义接口完成入库时强制 `public/custom`。
- 变更：管理员恢复隐藏图片时尊重内置任务公开设置；首页增加内置公开开关，并优化手机端头部按钮、标题、结果卡片和提交按钮布局。

## 2026-05-03 19:42（Codex）
- 动作：补充用户在“我的图片”页面修改图片可见性。
- 工具：`rg`、`Get-Content`、`apply_patch`，仅做静态核对，未安装依赖、未运行项目。
- 变更：新增 `/my/images/<image_id>/visibility` POST 路由，仅允许图片本人把未隐藏图片切换为 `public/private`，并保留 CSRF 校验。
- 变更：`templates/my_images.html` 增加公开/私有切换按钮和弹窗提示引用；管理员隐藏的图片不允许用户自行恢复。

## 2026-05-03 19:49（Codex）
- 动作：为“我的图片”页面增加分页器并优化手机端展示。
- 工具：`rg`、`Get-Content`、`apply_patch`，仅做静态核对，未安装依赖、未运行项目。
- 变更：复用通用分页参数，新增 `load_user_images_page`，默认每页 12 张，可选 6/12/24/48；切换图片可见性后保持当前分页参数。
- 变更：`templates/my_images.html` 增加底部分页器、页码跳转和每页条数选择；顶部仅显示总数，避免上下两个每页控件不同步；导航按钮和卡片操作区适配手机端。
