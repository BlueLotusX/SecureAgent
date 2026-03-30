# SecureAgent

_欢迎使用 SecureAgent。如你在项目中使用、改造或发布本项目的（主要）代码/配置，请在文档或发布说明中注明出处。_

SecureAgent 是一个基于 LangGraph 的**安全多智能体系统框架**：多 Agent 图编排 + 工具 / MCP + Skill + RAG，再叠加攻防能力，让你可以自定义架构、工具集、知识库以及攻击与防御策略。

---

## 致谢

SecureAgent 的设计与实现，深受开源社区的经验启发，**包括但不限于 LangChain 生态及相关项目**。  
感谢所有在社区中分享过设计思路、工具实现和最佳实践的开发者和研究者，没有这些沉淀，本项目不可能发展到现在的形态。

---

## 项目结构

```text
SecureAgent/
├── main.py                       # 命令行入口
├── config.py                     # 配置（LLM / 搜索 / Agent / MCP / RAG / Skills）
├── agent/
│   └── secure_agent.py           # 核心 SecureAgent 实现与 LangGraph 图
├── mcp_server/                   # MCP Server（工具实现与暴露）
│   ├── server.py                 # MCP 入口，注册并暴露所有工具
│   └── tools/
│       ├── web_search.py         # 多引擎搜索、web_search_with_content
│       ├── web_crawler.py        # 网页抓取
│       ├── browser_search.py     # Playwright 浏览器搜索（可选）
│       └── file_tools.py         # 文件读写、列目录、桌面路径、时间、工作区根
├── RAG/                          # RAG 索引构建与检索服务
│   ├── rag_config.py
│   ├── rag_service.py
│   └── build_index.py
├── skills/                       # Skill 定义与加载逻辑
│   ├── loader.py
│   └── ...                       # 具体技能文件（按需扩展）
├── prompts/
│   └── prompts.py                # 多 Agent / RAG / Skill / 防御相关提示词
├── utils/
│   └── logger.py                 # 日志
├── webui/                        # Web UI 后端
│   └── app.py
└── project_intro_web/            # 项目介绍网页
```

---

## 安装与使用（以 Web UI 为主）

### 1. 环境准备

- **Python**：建议 Python 3.10+，推荐使用虚拟环境（`venv` 或 Conda）。  
- **大模型接口（至少满足其一）：**
  - 在本地使用开源模型；
  - 或在云端运行 Ollama / 其他开源模型服务，并**通过反向代理 / 端口转发**将模型 HTTP 接口暴露给本项目；
  - 或配置为调用商用大模型 API（例如通过 API 网关），只要提供兼容的 `base_url` 和 `model` 即可。

在 `config.py` 中，通过 `LLMConfig` 配置：

- `base_url`: 模型服务的 HTTP 地址（ Ollama 默认 `http://127.0.0.1:11434`）；
- `model`: 具体模型名称。

### 2. 安装依赖（建议虚拟环境）

```bash
# 安装依赖
pip install -r requirements.txt
```

如需浏览器搜索（`browser_search` 工具），额外安装：

```bash
pip install playwright
playwright install chromium
```

### 3. 启动 Web UI

确保：

- 大模型服务已就绪（本地或云端；如果是云端 Ollama，需要先把**端口代理/转发**到本机或服务器）；  
- `config.py` 中的 LLM 与 MCP 配置正确（例如本地 stdio MCP + 本地 Ollama）。

然后运行：

```bash
python webui/app.py
# 默认 http://127.0.0.1:7860

# 或自定义绑定地址和端口
python webui/app.py --host 0.0.0.0 --port 8080
```

Web UI 启动后会在后台连接 MCP Server（默认通过 stdio 启动本地 MCP），就绪后创建单例 Agent，所有聊天请求共用这一套多 Agent + 工具 + RAG + Skill + 防御配置。你只需要在浏览器中打开对应地址，即可开始通过 Web UI 使用 SecureAgent。

---

## 1. 多 Agent 系统（Multi-Agent System）

- **架构流程**  
  SecureAgent 使用 LangGraph 构建有状态的多智能体图，核心节点包括：
  
  - 任务分解（Task Decomposer）
  - 规划（Planning）
  - 决策（Decision）
  - 执行（Execute）
  - 记忆（Memory）
  - 反思（Reflection）
  - 重试强化（Retry Reinforcement）
  
  典型主流程为：  
  **任务分解 → 规划 → 决策 →（需要时调用工具 / RAG / Skill）→ 记忆更新 → 反思与结果评估 →（必要时重试）→ 最终答复**。  
  每一步的输入 / 输出状态都在图里显式建模，方便你调试和控制。
  
- **可插拔的 LLM**  
  多 Agent 图只依赖一个抽象的 LLM 接口，你可以：
  
  - 使用**商用大模型 API**（如通过 HTTP 调用云端大模型网关）；
  - 使用**本地 / 自建开源模型**，只要提供兼容的 API（形如 `base_url + /v1/chat/completions` 风格）。
  
  在本项目的默认配置中，我们在服务器端通过 **Ollama** 调用开源模型（例如 Qwen、Llama 等），通过 `config.py` 中的 `LLMConfig` 配置 `base_url` 和 `model`。
  
- **你可以自定义的内容**
  - 调整多 Agent 图结构：新增节点（例如审计节点）、合并节点或修改路由条件；
  - 替换 LLM：从开源模型切换到商用 API，或反向切回本地模型；
  - 通过配置开关（如反思/记忆/RAG/Skill 开关）快速对比不同架构方案。

---

## 2. 工具 / MCP（Tools & MCP）

SecureAgent 中，**所有工具都通过 MCP（Model Context Protocol）提供**，Agent 自身只看到工具名称、描述和参数签名，而不关心它们在本地还是远程实现。

- **本地 MCP Server**
  - 仓库内的 `mcp_server/` 目录提供了一套本地 MCP Server：
    - `mcp_server/server.py`：MCP 入口，负责注册并暴露所有工具；
    - `mcp_server/tools/`：具体工具实现：
      - `web_search.py`：多引擎 HTTP 搜索 / `web_search_with_content`
      - `web_crawler.py`：网页抓取
      - `browser_search.py`：基于 Playwright 的浏览器搜索（可选）
      - `file_tools.py`：文件读写、列目录、桌面路径、当前时间、工作区根目录等
  - 默认通过 **stdio 传输** 启动本地 MCP Server，并由 Agent 连接使用。

- **远程 / 云端 MCP 服务**
  - 如果你已经购买了或在云端部署了 **远程 MCP 服务**，可以在 `config.mcp` 中切换为 SSE / HTTP 模式，并配置 URL（本项目已经内置了一个远程 MCP 服务的开关，将 API key 替换为你自己的即可）：
    - 切换 `transport` 为 `sse`；
    - 设置 `url` 为远程 MCP 服务地址；
    - 其余 Agent 逻辑无需修改。
  - 这样，你可以：
    - 在本地开发 /调试工具；
    - 部署到云端作为统一的工具服务；
    - 或在同一个 Agent 图中切换不同环境（本地 / 远程）的 MCP。

- **自定义工具 & 搜索引擎**
  你可以在 `mcp_server/tools/` 下新增工具模块，用 `@tool` 装饰器定义函数，然后在 `mcp_server/server.py` 注册即可被 Agent 发现。  
  例如：
  - 新增公司内部搜索引擎、知识库检索接口；
  - 新增内部业务系统 API 封装；
  - 扩展网页抓取 / 浏览器自动化逻辑。

  所有「可用工具」「搜索引擎」本质上都属于这一层：**它们是 MCP 工具的不同实现**，你可以根据需要增加、删除或替换。

---

## 3. Skill 系统（Skills）

Skill 用来描述一类「相对固定的复杂任务模板」，例如某种评估流程、标准化诊断流程等。它有点像「可被 Agent 选择调用的高层策略插件」。

- **Skill 流程（高层视角）**
  1. 在 `skills/` 中定义 Skill 的：
     - 元数据（名称、描述、优先级、适用场景等）；
     - 文本说明（告诉 LLM 这个 Skill 适合什么任务）；
     - 脚本 / 工具调用逻辑（真正执行 Skill 时要做什么）。
  2. 启动时，由 `skills/loader.py` 扫描并加载所有 Skill，做规范校验与归一化；
  3. 在 **决策节点（Decision）** 中，根据当前任务、上下文和 Skill 元数据，选择是否调用某个 Skill，并将其写入状态；
  4. 随后在执行节点中，由对应逻辑真正跑完这个 Skill 的一整套流程。

- **你可以自定义的内容**
  - 在 `skills/` 下新增自己的 Skill 目录（或文件），定义：
    - Skill 的介绍文档（markdown / 文本）；
    - Skill 执行脚本（Python）；
    - Skill 元数据（优先级、标签、触发条件等）。
  - 调整 Skill 加载规则和优先级策略（例如对某些 Skill 进行「白名单 / 黑名单」控制）。

这样，你可以把经验沉淀为能力单元，而不是每次都靠「临场 prompt」临时发挥。

---

## 4. RAG（Retrieval-Augmented Generation）

SecureAgent 内置一套轻量的 RAG 管线，用来把你的文档库安全地接入 Agent 决策过程。

- **RAG 流程**
  1. **准备文档**：把你的 Markdown / 文本等资料放入指定目录；
  2. **构建索引**：运行 `RAG/build_index.py`，采用向量化 + 分片策略，为文档构建索引；
  3. **在线检索**：在对话过程中，当 Agent 判断需要外部知识时，会调用 `rag_service.py` 暴露的检索接口；
  4. **上下文融合**：检索到的片段会与当前任务一起传入 LLM，用于回答、规划或反思。

- **你可以自定义的内容**
  - 替换或扩展 **知识库文档**：把你自己的技术文档、产品文档、安全规则、SOP 等加入索引；
  - 调整分片策略、向量模型和检索参数，以适配你的文档粒度与规模；
  - 控制在哪些节点允许 / 禁止使用 RAG（例如只在 Reflection / Decision 里使用）。

---

## 5. 攻防与安全评估（Attack & Defense）

SecureAgent 的另一个核心目标，是帮助你**研究和评估 Agent 在真实环境中的安全性**。

- **攻击场景示例：间接提示词注入**
  我们使用如下页面模拟**间接提示词注入攻击**（indirect prompt injection），其中第二个网页带有隐藏指令，你可以查看网页源代码：
  
  - `https://bluelotusx.github.io/ai-intro-pages/ai_intro.html`
  - `https://bluelotusx.github.io/ai-intro-pages/ai_intro_hidden.html`
  
  当 Agent 通过工具访问这些页面时，页面中的隐藏内容会尝试向 Agent 注入指令，例如：
  - 干扰正常的总结流程；
  - 让 Agent 直接跳出原本的多 Agent 图流程；
  - 覆盖原有的安全约束。
  
- **防御思路（本项目内置）**
  - **沙盒提示词防御**：在系统提示词层面，对外部内容进行「隔离与标注」，告诉模型哪些指令是「来源于用户」，哪些是「来源于外部内容」，避免盲目执行网页里的隐藏指示；
  - **反思节点 + 任务进度检查**：Reflection 节点会结合任务列表、工具调用记录等信息判断是否真的完成任务，而不是简单看「模型说完成了」；
  - **RAG 与 Skill 的受控接入**：外部知识和技能调用都通过明确的接口进入，而不是直接拼接任意文本到系统提示词中。

- **你可以自定义的内容**
  - 自己设计更多攻击页面或数据集，通过工具（web_search、web_crawler、browser_search 等）让 Agent 接触它们；
  - 修改 / 拓展沙盒提示词、防御规则和反思逻辑，例如对高风险任务提高审查强度；
  - 将本项目作为「攻防评测平台」，系统化地验证不同 LLM、不同多 Agent 架构与不同工具集在攻击下的表现。

---

## License

MIT License

