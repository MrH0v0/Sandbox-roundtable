# sandbox

一个基于 Python 3.11、FastAPI、asyncio 和 AIHubMix/OpenAI 风格接口的“军事沙盘圆桌讨论引擎”MVP，当前提供：

- FastAPI API 接口
- PySide6 桌面端入口
- 可插拔的外部 skill 机制
- 本地 session 保存与 replay

建议环境：

Windows 10 / 11
Python 3.11
PowerShell
可用的 OpenAI 兼容接口 / AIHubMix 接口 Key

项目使用：

- 模型身份：哪个成员用哪个 `model`
- 外部 skill：哪个成员绑定哪个 `skills/` 下的文件

这样你后续只需要维护 skill 文件和成员配置，不需要改核心业务代码。

## 功能概览

- 支持多个圆桌成员并发发言
- 固定四阶段流程：独立判断、交叉质疑、修正方案、最终裁决
- 主持人与裁判由独立配置承担
- skill 支持 `markdown`、`yaml`、`json`
- skill 缺失、格式错误、字段不完整时会明确报错
- AIHubMix 配置全部来自环境变量
- 使用 `httpx` + `asyncio` 调用 OpenAI 风格接口
- 支持超时、重试、单成员失败隔离
- 讨论结果同时输出结构化 JSON 和人类可读 markdown
- 完整 session 自动保存到本地 JSON，可通过 API replay

## 目录结构

```text
.
├── configs/
│   └── roundtable.example.yaml      # 圆桌成员、模型、Moderator、Judge 等示例配置
├── sandbox/
│   ├── agents/                      # 圆桌成员、主持人、裁判等 Agent 逻辑
│   ├── api/                         # FastAPI 接口层
│   ├── application/                 # 桌面端 / API 复用的应用服务层
│   ├── clients/                     # OpenAI / AIHubMix 兼容模型客户端
│   ├── core/                        # 配置、依赖装配、核心运行设置
│   ├── desktop/                     # PySide6 桌面工作台
│   ├── engines/                     # 圆桌讨论主流程与调度逻辑
│   ├── renderers/                   # Markdown / 文本结果渲染
│   ├── schemas/                     # Pydantic 数据结构定义
│   ├── storage/                     # session 保存、读取与回放相关逻辑
│   ├── main.py                      # API 启动入口
│   └── skill_loader.py              # skill 文件加载与校验
├── scripts/
│   ├── setup.ps1                    # 创建虚拟环境并安装依赖
│   ├── start-desktop.ps1            # 从源码启动 PySide6 桌面端
│   ├── start-api.ps1                # 启动 FastAPI 服务
│   ├── run-tests.ps1                # 运行测试
│   ├── run-desktop-smoke.ps1        # 桌面端 smoke 测试
│   ├── demo-request.ps1             # API 示例请求
│   └── build-launchers.ps1          # 构建项目内启动器
├── launcher_sources/
│   ├── common.py                    # 启动器公共逻辑
│   ├── setup_launcher.py            # setup 启动器入口
│   ├── start_api_launcher.py        # API 启动器入口
│   ├── start_desktop_launcher.py    # 桌面端启动器入口
│   ├── demo_request_launcher.py     # demo 请求启动器入口
│   ├── run_tests_launcher.py        # 测试启动器入口
│   └── run_desktop_smoke_launcher.py # 桌面 smoke 测试启动器入口
├── skills/
│   ├── skill_template.md            # 新建 skill 的模板
│   ├── placeholder_alpha.md         # 示例 skill
│   ├── placeholder_beta.yaml        # 示例 skill
│   ├── placeholder_gamma.json       # 示例 skill
│   ├── guderian-perspective/        # 示例人物视角 skill
│   ├── syrskyi-perspective/         # 示例人物视角 skill
│   └── yang-zhibin-perspective/     # 示例人物视角 skill
├── sessions/
│   └── .gitkeep                     # 运行后生成的 session 默认保存在这里
├── tests/
│   ├── test_aihubmix_client.py      # 模型客户端测试
│   ├── test_api.py                  # API 测试
│   ├── test_desktop_real_boot.py    # 桌面端真实启动测试
│   ├── test_desktop_smoke.py        # 桌面端 smoke 测试
│   ├── test_roundtable_engine.py    # 圆桌引擎测试
│   ├── test_skill_loader.py         # skill 加载测试
│   └── test_workbench_service.py    # 工作台服务层测试
├── .env.example                     # 环境变量示例，不要提交真实 .env
├── .gitignore                       # Git 忽略规则
├── LICENSE                          # MIT License
├── pyproject.toml                   # 项目依赖与打包配置
├── README.md                        # 项目说明文档
└── uv.lock                          # uv 锁定文件
```

## 如何配置成员

成员配置放在 `configs/` 目录下，推荐使用 YAML。

示例文件：[`configs/roundtable.example.yaml`](./configs/roundtable.example.yaml)

每个成员至少配置：

- `id`
- `display_name`
- `model`
- `skill`
- `generation.temperature`
- `generation.max_tokens`

示例片段：

```yaml
members:
  - id: analyst_alpha
    display_name: Analyst Alpha
    model: gpt-5.4-mini
    skill: placeholder_alpha.md
    generation:
      temperature: 0.4
      max_tokens: 1200
```

说明：

- `skill` 可以写 skill 文件名，比如 `placeholder_alpha.md`
- 也可以写 skill 文件中的 `id`
- 主持人和裁判也可以单独配置自己的 `model`，并可选绑定 skill

## 如何新增 skill

于主控台新增或是把新 skill 文件放进 `skills/` 目录即可，不需要改 Python 代码。

推荐流程：

1. 复制 [`skills/skill_template.md`](./skills/skill_template.md)
2. 改文件名，例如 `sun_tzu_style.md`
3. 按模板填写字段
4. 在 `configs/*.yaml` 里把某个成员的 `skill` 指向这个文件名或对应 `id`

程序启动时会自动加载 skill；运行某轮讨论前也会再次校验 skill 引用是否存在。

## skill 文件格式说明

### 1. Markdown

如果你已经有自己的 skill 蒸馏流程，也可以按同样字段结构生成 skill 文件。（推荐使用nuwa-skill蒸馏）
推荐格式是“Markdown + YAML front matter”：

```md
---
id: your-skill-id
name: "你的 skill 名称"
core_strategy: "核心战略观"
decision_priorities:
  - "优先级 1"
  - "优先级 2"
risk_preference: "风险偏好"
information_view: "信息观"
tempo_view: "节奏观"
resource_view: "资源观"
common_failure_modes:
  - "失败模式 1"
output_format_requirements:
  - "输出要求 1"
---

# Notes

这里可以放人工维护备注。
```

### 2. YAML / JSON

也支持纯 `yaml` / `json`，字段结构与 markdown front matter 一致。

### 必填字段

- `name`
- `core_strategy`
- `decision_priorities`
- `risk_preference`
- `information_view`
- `tempo_view`
- `resource_view`
- `common_failure_modes`
- `output_format_requirements`

说明：

- `id` 不写时会默认取文件名（不含扩展名）
- `decision_priorities`、`common_failure_modes`、`output_format_requirements` 必须是非空列表

## 环境变量

复制 `.env.example` 为 `.env`，然后至少填写：

```env
AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
AIHUBMIX_API_KEY=your_aihubmix_api_key
```

可选变量：

- `AIHUBMIX_REQUEST_TIMEOUT_SECONDS`
- `AIHUBMIX_MAX_RETRIES`
- `AIHUBMIX_RETRY_BACKOFF_SECONDS`
- `SANDBOX_SKILLS_DIR`
- `SANDBOX_CONFIGS_DIR`
- `SANDBOX_SESSIONS_DIR`

## 如何启动项目

项目提供两种启动方式

### 方式 1：源码运行（推荐开发者）
适合：
- 想直接从源码启动
- 需要修改代码
- 需要稳定复现开发环境
- 准备参与贡献或二次开发

### 方式 2：项目内启动器运行
适合：
- 已经在完整项目目录中
- 已经完成环境初始化
- 想少敲一条命令

注意：

`sandbox-start-desktop.exe` **不是独立绿色版桌面程序**，它只是项目内启动器。  
它依赖当前目录中的：

- `scripts/`
- `sandbox/`
- `.venv/`

因此：

- 它不能只拷贝一个 exe 到别的目录直接运行
- 如果你是第一次部署，请先按下面的“源码运行步骤”完成环境准备

---

## 一、运行前准备

### 1. 系统要求

建议环境：

- Windows 10 / 11
- Python 3.11
- PowerShell
- 可用的 OpenAI 兼容接口 / AIHubMix API Key

---

### 2. 获取源码

```powershell
git clone https://github.com/MrH0v0/Sandbox-roundtable
cd Sandbox-roundtable
```

如果你不是用 Git，也可以直接下载 ZIP 并解压，然后进入项目根目录。

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 .env，至少填写：

```env
AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1
AIHUBMIX_API_KEY=your_api_key_here
```

如果你使用的是别的 OpenAI 兼容接口，也可以替换成你自己的地址：

```env
AIHUBMIX_BASE_URL=https://your-openai-compatible-endpoint/v1
AIHUBMIX_API_KEY=your_api_key_here
```

·AIHUBMIX_BASE_URL：模型服务接口地址
·AIHUBMIX_API_KEY：接口密钥

## 源码运行步骤

### 1. 创建虚拟环境并安装依赖

```powershell
.\scripts\setup.ps1 -Desktop
```

如果你只需要 API / 测试环境，也可以执行：

```powershell
.\scripts\setup.ps1
```

·-Desktop 会额外安装 PySide6 桌面依赖
·不带 -Desktop 时，不保证桌面端可启动

如果你的 py -3.11 不可用，但你知道 Python 3.11 的完整路径，可以这样执行：

```powershell
.\scripts\setup.ps1 -Desktop -PythonExe "C:\Path\To\Python311\python.exe"
```

### 2.确认桌面依赖已安装

```powershell
Test-Path .\.venv\Scripts\python.exe
```

如果返回 True，说明虚拟环境已经创建成功。

### 3.从源码启动桌面端

推荐直接使用脚本启动：

```powershell
.\scripts\start-desktop.ps1
```

这个脚本本质上会执行：

```powershell
.\.venv\Scripts\python.exe -m sandbox.desktop.main
```

如果你想手动启动，也可以直接运行：

```powershell
.\.venv\Scripts\python.exe -m sandbox.desktop.main
```

### 4.从源码启动 API（如需要）

如果你还需要本地 API 服务，执行：

```powershell
.\scripts\start-api.ps1
```

启动后可用接口通常包括：

·GET /health
·POST /api/v1/discussions/run
·GET /api/v1/sessions/{session_id}

## 项目内启动器的正确理解

根目录下的：

```powershell
sandbox-start-desktop.exe
```

只是对下面这条源码启动命令的包装：

```powershell
.\scripts\start-desktop.ps1
```

所以它只适用于这种场景：

你当前就在完整项目根目录中
已经执行过 .\scripts\setup.ps1 -Desktop
当前目录里已经有 .venv

如果你缺少 .venv，它会直接报错，例如：

```text
Virtual environment was not found. Run scripts/setup.ps1 first.
```

因此，第一次部署请优先使用“源码运行步骤”，不要把这个 exe 当成可独立分发的软件包。

## 省流

如果你只想最快从源码把桌面端跑起来，按顺序执行下面 3 条命令：

```powershell
Copy-Item .env.example .env
.\scripts\setup.ps1 -Desktop
.\scripts\start-desktop.ps1
```

如果你还需要 API：

```powershell
.\scripts\start-api.ps1
```

## API 使用示例

### 发起完整圆桌讨论

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/discussions/run" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "roundtable.example.yaml",
    "scenario": {
      "title": "岛礁夺控推演",
      "background": "蓝方需要在有限时间内完成夺控并稳固防御。",
      "constraints": ["72 小时内完成主要行动", "不能依赖外部增援"],
      "friendly_forces": ["两栖突击群", "舰载航空兵"],
      "enemy_forces": ["岸防导弹营", "近海巡逻舰"],
      "objectives": ["夺取登陆点", "建立持续补给通道"],
      "victory_conditions": ["72 小时内保持控制权", "主力损失低于阈值"],
      "additional_notes": ["情报存在不完整区域"]
    }
  }'
```

或者直接用 PowerShell 示例脚本：

```powershell
.\scripts\demo-request.ps1
```

返回内容包含：

- `session`：结构化 JSON
- `markdown`：完整可读版本
- `session_id`：后续 replay 用

### 读取已保存 session

```bash
curl "http://127.0.0.1:8000/api/v1/sessions/<session_id>"
```

## 会话保存与 replay

- 每次运行完成后，session 会保存到 `sessions/<session_id>.json`
- `GET /api/v1/sessions/{session_id}` 会从本地 JSON 读取并返回
- JSON 中保留了场景、四阶段结果、成员记忆和 markdown 汇总

## 设计说明

### 1. 为什么把“模型”和“skill”拆开

这是本项目的核心约束。成员本质上是：

`成员 = 模型 + 外部 skill + 生成参数 + 轮次记忆`

而不是把“某历史人物”硬编码进程序。这样后续你新增思想流派、自定义方法论、训练营风格模板时，只需要维护 skill 文件。

### 2. 为什么没有引入 LangChain

这是有意的 MVP 选择。当前实现直接使用：

- `FastAPI`
- `asyncio`
- `httpx`
- `pydantic`

这样链路更显式、可调试、适合后续按自己需求继续扩。

### 3. 并发与失败隔离

- 成员阶段使用 `asyncio.gather` 并发执行
- 每个成员调用都包裹在安全执行层里
- 单个成员失败会记录错误，但不会中断其他成员
- 裁判和主持人也有回退逻辑，避免整轮直接崩掉

## 测试

```powershell
.\scripts\run-tests.ps1
```

当前基础测试覆盖：

- skill loader 对 markdown/yaml/json 的解析与校验
- 圆桌调度的并发执行
- 单成员失败不拖垮整轮
- session 保存与 API replay

## 后续可扩展方向

- 增加多轮 session 续跑，而不是固定单轮四阶段
- 为主持人增加更细的追问策略与目标分配策略
- 为裁判增加结构化字段抽取，而不只保留原始 markdown
- 增加 session 检索、列表和版本化 replay
- 增加更细粒度的成员记忆压缩策略
- 增加 Web UI、地图系统、战场要素可视化
- 风格转换，不局限于军事沙盘圆桌

## 当前版本边界

这是 MVP，当前重点是验证：

- 多模型圆桌讨论流程
- 外部 skill 插件机制
- 本地 session 保存与 replay
- API 与桌面端的基础可用链路

当前尚未完成的部分包括：

- 未提供 Web 前端
- 未实现地图 / 兵棋可视化
- 未接入复杂数据库持久化
- 未实现 skill 热更新监听
- 未实现强约束的结构化结果校验与解析
- 桌面端目前仍以可用性验证为主，尚非完整产品化界面

## Contributing

欢迎提交 PR，请按照以下步骤：
1. Fork 仓库
2. 创建分支
3. 提交代码
4. 发起 Pull Request

## Contributors

SHIMH

## License

Distributed under the MIT License. See `LICENSE` for more information.

### 随便改 随便嵌入 随便商用 但请按协议对Author与Contributor进行署名 :)

## Author

R & H
