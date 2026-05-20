<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

Skills 已迁移至全局目录 `~/.claude/skills/`（21 个），所有项目共享。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->

# Smart BI — 外汇交易智能查询系统

## 语义层

智能 BI 分析平台，支持自然语言查询外汇交易数据。LLM（DeepSeek v4-flash）解析用户意图 + 规则引擎守门，生成 Oracle SQL 后执行聚合查询并可视化展示。

**技术栈**: Python 3 + FastAPI（后端），Vue 3 + Naive UI（前端），Oracle 19c（数据源），Vite 5（构建）

**架构**: `backend/` FastAPI API 层 → `llm_parser/` 关键词规则解析 + LLM 解析 → `db/` Oracle SQL 构建器；`frontend/` Vue 3 SPA，Vite 代理 `/api` 到后端

**核心依赖**: FastAPI + uvicorn，Oracle instant client，Vue 3.5 + Naive UI 2.40，Vite 5.4

## 操作层

| 场景 | 命令 | 说明 |
|------|------|------|
| 启动后端 | `cd backend && uvicorn app:app --reload --host 0.0.0.0 --port 8000` | FastAPI 开发服务器 |
| 启动前端 | `cd frontend && npm run dev` | Vite 开发服务器，端口 5173 |
| 前端构建 | `cd frontend && npm run build` | 输出到 `frontend/dist/` |
| 生产运行 | 构建前端后启动后端，FastAPI 自动服务 `dist/` 静态文件 | |
| 安装依赖 | `cd frontend && npm install` | 首次或 package.json 变更后 |
| 环境变量 | `.env` 文件 | DB_HOST/DB_PORT/DB_SERVICE/DB_USER/DB_PASSWORD |

## 规范层

- **组件**: Vue 3 Composition API（`<script setup>`），`reactive()` 管理表单状态，Naive UI 按需导入
- **API**: FastAPI RESTful，`/api/parse` 解析查询，`/api/query` 执行查询，`/api/health` 健康检查
- **SQL**: 通过 `query_builder.py` 参数化构建，禁止字符串拼接用户输入
- **提交**: 参考 chinese-commit-conventions skill
- **验收**: 每次改动涉及 API 返回结构或组件 props 变化时，必须在提交前运行端到端验证：`python -c "import requests; r=requests.post('http://localhost:8000/api/query',json={'text':'本月交易量'}); d=r.json(); assert all(k in d for k in ['summary','chartOption','insights','comparison']), f'Missing: {[k for k in ['summary','chartOption','insights','comparison'] if k not in d]}'; print('PASS')"`。ResultCard 的四段式（摘要→图表→洞察→表格）全部依赖这些字段，缺一个都不渲染。
- **前端数据流**: `App.vue handleSend()` 中 `messages[botIdx].data` 必须包含后端返回的 `summary`、`chartOption`、`insights`，否则 ResultCard 只显示空表格。
