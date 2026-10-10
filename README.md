# 知识世界 · Knowledge World

一个由 AI 系统 Agent 主持的个人养成游戏。记录现实行动，获得有依据的积分奖励，兑换休闲时间，培养角色与魔兽，再通过远征让家园逐步成长。

Python / FastAPI · React / TypeScript · SQLite · Three.js / React Three Fiber

## 当前功能

- **系统 Agent**：自然对话、受限工具调用、行动记录、积分判定与正式回执。
- **积分与奖励**：追加账本、幂等结算、自定义奖励、休闲券的开始/暂停/续用/退回。
- **签到与对赌**：连签、条款、押金、进度和后台结算；已有合约继续按原条款履行。
- **三维家园**：建筑、装饰、摆放、成长历史、可旋转场景与反馈演出。
- **角色与远征**：三属性训练、魔兽招募/升级/组队、三区九据点、服务端自动战斗、首胜和永久占领。
- **外部 Skill**：对赌与拾忆只读接入，提供当前账户的连接状态和工具目录。

主要入口是世界、角色与魔兽、奖励、系统。学习资料、题库、复习管理及屏幕时间不属于站内产品。

项目仍处于持续验收阶段。真实模型工具链已验证；不同服务商的兼容性、手机真机性能、完整声音与视觉体验需要在具体环境中验证。本仓库不会附带开发者账户、运行数据库或 API Key。

## 快速开始（Windows）

需要 Git、[uv](https://docs.astral.sh/uv/) 和 Node.js/npm。启动脚本通过锁文件安装依赖，并使用 `backend/.python-version` 指定的 Python。

```powershell
git clone https://github.com/libohan-ha/knowledge-world.git
cd knowledge-world
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

打开 **http://127.0.0.1:8000**，首次进入创建账户。初始赠予是营地、角色和伙伴；积分从实际玩法产生。

停止服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

自定义数据目录与端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -DataDir C:\KnowledgeWorldData -Port 8001
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1 -DataDir C:\KnowledgeWorldData
```

API 与 Worker 使用同一数据目录。正常重启会恢复持久任务；不要让不同版本的 Worker 同时处理同一个数据库。

## 配置 AI 与拾忆

在 **设置 → AI 服务**：

1. 填写兼容 Chat Completions 的 HTTP/HTTPS Base URL（通常以 `/v1` 结尾）和 API Key。
2. 点击“拉取模型”，从服务返回的列表选择模型。
3. 保存配置，再点击“测试所配置的服务”。结构化回复、流式工具调用及工具续答均通过后才启用。

Key 保存到运行后端的系统凭据库，也可引用服务端环境变量。设置读取不回显 Key，备份会清除凭据引用；不要把 Key 放入前端变量。模型只提出建议，最终积分、订单与胜负由后端规则和事务决定。

拾忆使用自己的地址和 Key，在 **设置 → Skill** 单独配置并检查。开关开启不等于连接已配置；状态为“已就绪”时系统可以只读查询。它不会自动导入电脑上的其他技能包。

服务测试与真实对话会使用供应商额度。没有 AI 时，家园、签到、兑换、培养和远征仍可使用，待处理输入会保留。

环境变量示例见 [.env.example](.env.example)。

## 开发与验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -DataDir .\artifacts\runtime\dev -TestAdapter
```

该命令显式开启测试适配器，不能作为真实模型接入证据。前端默认 5173，后端 8000；省略 `-TestAdapter` 使用真实服务。

```powershell
cd backend
uv sync --frozen
uv run pytest -q
uv run ruff check src tests
cd ..\frontend
npm ci
npm run typecheck
npm test
npm run build
```

浏览器验收：先构建前端，再在 `frontend/` 中执行 `npx playwright install chromium` 和 `npm run e2e`。测试使用独立目录和明确标识的模拟数据，不使用真实 AI 凭据。Windows 是当前启动脚本及完整浏览器夹具的验证平台。

修改 API 后，从 Pydantic/OpenAPI 生成前端类型：

```powershell
cd backend
uv run python -m knowledge_world.cli openapi --file ../artifacts/openapi.json
cd ..\frontend
npm run generate-api
```

## 目录

| 路径 | 内容 |
|---|---|
| `backend/src/knowledge_world/` | 领域逻辑、API、Agent、账本和后台任务 |
| `backend/migrations/` | 追加式 Alembic 迁移 |
| `backend/tests/` | 文件数据库、恢复、权限与业务回归 |
| `backend/legacy-fixture/` | 构造合成旧库的历史程序源码，不含用户数据库 |
| `frontend/src/` | 网站与三维场景 |
| `docs/contracts/` | 规则与视觉参数的版本化来源 |
| `scripts/` | 启动、停止、开发与验证脚本 |

规则目标 JSON 的 `target_not_activated` 是源文件状态；迁移将规则导入运行库的不可变版本。不要直接覆盖已经使用的规则、迁移或历史流水。升级已有账户前，在设置中创建备份并保留对应代码版本。

## 开源范围与许可

项目自有代码与原创程序化美术采用 [MIT](LICENSE)。第三方依赖、字体及内置拾忆客户端保留各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

公开版本使用项目自有的三维休闲房间。开发环境曾本地集成的 CozySpace 背景、音频与适配样式因缺少明确再分发许可，**不包含在本仓库**；第三方产品参考截图、内部实施日志、聊天记录、测试运行目录和历史私有备份也不发布。
