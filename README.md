# SecureAgent

_Welcome to SecureAgent. If you use, fork, or redistribute this project (or substantial parts of it), please provide attribution in your documentation._

[**Project Introduction Webpage**](https://bluelotusx.github.io/SecureAgent/)

SecureAgent is a **secure multi-agent system framework** built on LangGraph. It combines:

- a multi-agent execution graph,
- an MCP-based tool layer,
- a Skill system,
- RAG (Retrieval-Augmented Generation),
- and attack & defense mechanisms,

to let you customize the **architecture, toolset, knowledge base, and security strategies**.

---

## Acknowledgments

SecureAgent is heavily inspired by, and built upon the experience of, the open-source community, **including but not limited to the LangChain ecosystem and related projects**.  
We would like to thank all contributors who have shared their designs, ideas, tools, and best practices—this project would not exist in its current form without that collective effort.

---

## Project Structure

```text
SecureAgent/
├── main.py                       # CLI entrypoint
├── config.py                     # Configuration (LLM / search / agent / MCP / RAG / skills)
├── agent/
│   └── secure_agent.py           # Core SecureAgent implementation and LangGraph graph
├── mcp_server/                   # MCP server (tool implementations and exposure)
│   ├── server.py                 # MCP entrypoint, registers and exposes all tools
│   └── tools/
│       ├── web_search.py         # Multi-engine search, web_search_with_content
│       ├── web_crawler.py        # Web crawling
│       ├── browser_search.py     # Playwright-based browser search (optional)
│       └── file_tools.py         # File I/O, list directory, desktop path, time, workspace root
├── RAG/                          # RAG index building and retrieval service
│   ├── rag_config.py
│   ├── rag_service.py
│   └── build_index.py
├── skills/                       # Skill definitions and loading logic
│   ├── loader.py
│   └── ...                       # Concrete skills (extend as needed)
├── prompts/
│   └── prompts.py                # Prompts for multi-agent / RAG / skills / defense
├── utils/
│   └── logger.py                 # Logging
├── webui/                        # Web UI backend
│   └── app.py
└── project_intro_web/            # Project introduction site (shows SecureAgent and attack demos)
```

---

## Installation & Usage (Web UI)

### 1. Environment

- **Python**: Python 3.10+ is recommended. A virtual environment (`venv` or Conda) is strongly recommended.  
- **LLM endpoint (choose at least one option):**
  - Run an open-source model locally (e.g., via Ollama);
  - Or run Ollama / another open-source model service in the cloud and **expose its HTTP API** to this project via reverse proxy / SSH port forwarding;
  - Or connect to a **commercial LLM API** (through your own API gateway, etc.) as long as it provides a compatible `base_url` and `model` interface.

In `config.py`, configure `LLMConfig`:

- `base_url`: HTTP endpoint of your model service (Ollama default is `http://127.0.0.1:11434`);
- `model`: the concrete model name.

### 2. Install dependencies (recommended in a virtualenv)

```bash
# install dependencies
pip install -r requirements.txt
```

If you want browser-based search via the `browser_search` tool, additionally install:

```bash
pip install playwright
playwright install chromium
```

### 3. Run the Web UI

Make sure:

- Your LLM service is running (local or remote; for remote Ollama you should first expose/forward the HTTP port to the machine running SecureAgent);  
- `config.py` has correct LLM and MCP settings (e.g., local stdio MCP + local Ollama).

Then start the Web UI:

```bash
python webui/app.py
# default http://127.0.0.1:7860

# or bind to a custom host/port
python webui/app.py --host 0.0.0.0 --port 8080
```

The Web UI will start an MCP server (via stdio) in the background, wait until it is ready, and then create a singleton SecureAgent instance. All chat requests share this multi-agent + tools + RAG + skills + defense configuration.  
Open the URL in your browser and you can use SecureAgent through the Web UI.

---

## 1. Multi-Agent System

### Architecture flow

SecureAgent uses LangGraph to build a **stateful multi-agent graph**. The core nodes include:

- Task Decomposer  
- Planning  
- Decision  
- Execute  
- Memory  
- Reflection  
- Retry Reinforcement  

The typical main loop is:

> **Task Decomposition → Planning → Decision → (call tools / RAG / skills when needed) → Memory update → Reflection & result evaluation → (retry if necessary) → Final answer**

Each step’s input/output is explicitly represented in the graph state, which makes debugging and controlling the behavior much easier.

### Pluggable LLMs

The multi-agent graph depends only on an abstract LLM interface. You can:

- Use a **commercial LLM API** (via HTTP through your own gateway);  
- Use **local / self-hosted open-source models**, as long as they expose a compatible API (e.g., `base_url + /v1/chat/completions` style).

In the **default configuration**, we run **Ollama** on the server side and call open-source models (such as Qwen or Llama) via the `LLMConfig` settings in `config.py` (`base_url` and `model`).

### What you can customize

- Modify the multi-agent graph:
  - Add new nodes (e.g., audit / guard nodes),
  - Merge or remove nodes,
  - Change routing / termination conditions;
- Swap LLMs:
  - Switch between open-source models and commercial APIs;
- Toggle behavior with config flags (e.g., enabling/disabling reflection, memory, RAG, skills) to compare different architectures.

---

## 2. Tools & MCP

In SecureAgent, **all tools are provided through MCP (Model Context Protocol)**. The agent only sees tool names, descriptions, and parameter schemas; it does not care whether a tool is implemented locally or remotely.

### Local MCP server

The `mcp_server/` directory contains a local MCP server:

- `mcp_server/server.py`: MCP entrypoint, which registers and exposes all tools;
- `mcp_server/tools/`: concrete tool implementations, such as:
  - `web_search.py`: multi-engine HTTP search and `web_search_with_content`;
  - `web_crawler.py`: web page crawling;
  - `browser_search.py`: Playwright-based Google search (optional);
  - `file_tools.py`: file reading/writing, directory listing, desktop path, current time, workspace root, etc.

By default, we start this MCP server via **stdio**, and the agent connects to it automatically.

### Remote / cloud MCP services

If you have a **remote MCP service** (e.g., deployed in the cloud or your intranet), you can switch to it via `config.mcp`:

- set `transport = "sse"` (or another supported mode);  
- set `url` to your remote MCP server endpoint;  
- the rest of the agent logic stays the same.

This lets you:

- Develop and debug tools locally;  
- Deploy them to the cloud as a shared tool service;  
- Switch between **local** and **remote** MCP environments using the same multi-agent graph.

### Custom tools & search engines

You can add new tools under `mcp_server/tools/` by:

1. Creating a new module and defining functions decorated with `@tool`;  
2. Importing and registering them in `mcp_server/server.py`;  
3. Restarting MCP (by restarting `main.py` or the Web UI).

Examples of what you might add:

- An internal enterprise search / knowledge retrieval API;
- Custom business-system APIs;
- Extended web scraping or browser automation logic.

All the “available tools” and “search engines” are essentially **different MCP tool implementations**. You can add, remove, or replace them as needed without changing the high-level agent logic.

---

## 3. Skill System

Skills describe **reusable, structured task templates**, such as a standard evaluation pipeline or diagnostic procedure. Conceptually, they are **higher-level strategy plugins** that the agent can choose to invoke.

### Skill flow (high-level)

1. Under `skills/`, you define each skill’s:
   - Metadata (name, description, priority, tags, applicable scenarios, etc.),
   - Text description (to tell the LLM when this skill is appropriate),
   - Script / tool-calling logic (what to actually do when the skill is executed).
2. On startup, `skills/loader.py` scans and loads all skills, normalizing and validating them;
3. In the **Decision node**, based on the current task and context, the agent selects one or more skills (according to metadata, priority, etc.) and writes this choice into the state;
4. In subsequent execution steps, the corresponding logic runs the skill end-to-end.

### What you can customize

- Create your own skills under `skills/`:
  - Add a markdown/text description,
  - Implement the corresponding Python logic,
  - Configure metadata such as priority and triggers;
- Adjust the loading and selection rules:
  - Whitelist/blacklist certain skills,
  - Tune priorities for different scenarios.

This lets you turn “tacit knowledge” into reusable capabilities, instead of reinventing complex prompts every time.

---

## 4. RAG (Retrieval-Augmented Generation)

SecureAgent includes a lightweight RAG pipeline to safely inject your document knowledge into the agent’s decision process.

### RAG flow

1. **Prepare documents**: place your markdown / text (or converted) documents into the configured directory;  
2. **Build the index**: run `RAG/build_index.py`, which creates a vectorized, chunked index over your documents;  
3. **Online retrieval**: during conversations, when the agent decides it needs external knowledge, it calls the retrieval functions exposed by `rag_service.py`;  
4. **Context fusion**: retrieved chunks are combined with the current task and passed to the LLM for answering, planning, or reflection.

### What you can customize

- Replace or extend the **knowledge base documents**:
  - Add your own technical docs, product docs, safety rules, SOPs, etc.;  
- Tune chunking, embedding models, and retrieval parameters:
  - To match your document size and structure;  
- Control **where** RAG is used in the graph:
  - For example, only allow RAG in Reflection / Decision nodes, or disable it for certain tasks.

---

## 5. Attack & Defense (Security Evaluation)

Another core goal of SecureAgent is to help you **study and evaluate agent security** in realistic environments.

### Example attack: indirect prompt injection

We use the following pages to simulate **indirect prompt injection**:

- `https://bluelotusx.github.io/ai-intro-pages/ai_intro.html`  
- `https://bluelotusx.github.io/ai-intro-pages/ai_intro_hidden.html` (contains hidden instructions; check the page source)

When the agent visits these pages via tools (e.g., web_search/web_crawler/browser_search), the hidden content attempts to inject instructions into the agent, such as:

- Disrupting normal summarization;  
- Forcing the agent to exit the intended multi-agent flow;  
- Overwriting existing safety constraints.

### Built-in defenses

- **Sandboxed prompts**: system prompts label and isolate external content, explicitly distinguishing:
  - instructions from the **user** vs.
  - content from **external sources** (web pages, documents, etc.),
  so the model is discouraged from blindly following hidden instructions from external content;
- **Reflection + task progress checks**: the Reflection node uses task lists, tool call logs, and execution state to decide whether the overall task is truly finished, rather than blindly trusting “the model said it’s done”;
- **Controlled RAG & skills**: external knowledge and skills are injected through well-defined interfaces rather than arbitrary text concatenation into the system prompt.

### What you can customize

- Design your own attack pages or datasets and let the agent encounter them through tools (web_search, web_crawler, browser_search, etc.);  
- Modify / extend sandbox prompts, defense rules, and reflection logic (e.g., stricter checks for high-risk operations);  
- Use this project as a **security evaluation platform** to benchmark different LLMs, multi-agent architectures, and tool configurations under attack.

---

## License

MIT License

