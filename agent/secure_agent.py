"""
SecureAgent 核心实现（多智能体编排，含任务分解 / 规划 / 决策 / 执行 / 记忆 / 反思）。

Core implementation of SecureAgent: a LangGraph-based multi-agent workflow
including task decomposition, planning, decision making, tool execution,
memory update, and reflection.
"""

import re
import json
import time
import hashlib
import requests
import sys
import os
import threading
import asyncio
from typing import List, Optional, Dict, Any, Callable, Annotated

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# 确保能导入父模块 / Ensure parent package is importable
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from config import config
from utils.logger import logger
from skills import load_skills_from_sources, filter_skills_for_agent, build_skills_system_section
from prompts.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_CLOUD,
    build_system_prompt,
    PLANNING_PROMPT,
    DECISION_SYSTEM_EXTRA,
    ERROR_FLAG_TRUE,
    ERROR_FLAG_FALSE,
    get_memory_prompt,
    get_reflection_prompt,
    RAG_PROMPT_SECTION,
    SKILLS_PRIORITY_SECTION,
)
from RAG.rag_config import RAG_ENABLED_DEFAULT, MAX_CONTEXT_CHARS
from RAG.rag_service import get_rag_context
from typing import TYPE_CHECKING
from typing_extensions import TypedDict

DEFAULT_CHAT_MODEL: str = "qwen3:8b"

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


# --- 结构化任务模型与图状态 / Structured task models & graph state ---

class Task(TypedDict, total=False):
    """
    结构化任务条目，跟踪子任务完成状态。
    Structured task item for tracking sub-task completion status.
    """

    id: str
    description: str
    status: str  # "pending" | "in_progress" | "completed"
    evidence: str


class StepRecord(TypedDict, total=False):
    """
    结构化操作记录：每次工具调用后写入，用于判重和防空转。
    Structured step record written after each tool call; used for
    deduplication, task-status updates, and loop prevention.
    """

    id: str
    tool: str
    target: str
    params: Dict[str, Any]
    success: bool
    timestamp: float
    task_ids: List[str]
    result_summary: str
    signature: str


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    agent_memory: str
    task_progress: str
    operation_history: list
    error_flag: bool
    retry_count: int
    tasks: List[Task]
    step_records: List[StepRecord]
    recent_signatures: List[str]
    repeat_counter: Dict[str, int]
    no_progress_count: int


def _parse_task_progress(text: str) -> str:
    """
    从规划节点输出中解析 '### Task progress ###' 段落。
    Parse the '### Task progress ###' section from Planning node output.
    """
    m = re.search(r"###\s*Task progress\s*###\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"###\s*Completed contents\s*###\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip() or "No operations completed yet"


# 记忆节点输出中视为「无新内容」的无意义短语，匹配后不写入 agent_memory
# Trivial phrases from Memory node output — skip them to avoid polluting agent_memory
_MEMORY_SKIP_PHRASES = (
    "no new information",
    "the task is ongoing",
    "no meaningful new content",
    "nothing new to add",
    "no new content",
    "none",
)


def _parse_important_content(text: str) -> Optional[str]:
    """
    从记忆节点输出中解析 '### Important content ###'，过滤无意义短语。
    Parse '### Important content ###' from Memory node output; filter trivial phrases.
    """
    if not text or not text.strip():
        return None
    content = None
    m = re.search(r"###\s*Important content\s*###\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(1).strip()
    else:
        # 回退：取首段文本 / Fallback: extract the first paragraph
        stripped = text.strip()
        if re.match(r"^\s*none\s*$", stripped, re.IGNORECASE):
            return None
        first_para = stripped.split("\n\n")[0].strip() if "\n\n" in stripped else stripped
        if first_para and len(first_para) > 2:
            content = first_para
    if not content:
        return None
    # 过滤模型残留的占位符行 / Strip leftover placeholder lines from the model
    try:
        lines = [ln for ln in content.splitlines() if ln.strip()]
        filtered_lines = []
        for ln in lines:
            if "Your concise focus points or None" in ln:
                continue
            # 泛化的尖括号占位符 / Generic angle-bracket placeholder
            if re.match(r"^<[^>]+>$", ln.strip()):
                continue
            filtered_lines.append(ln)
        content = "\n".join(filtered_lines).strip()
    except Exception:
        content = content.strip()
    if not content:
        return None
    if content.lower() == "none":
        return None
    # 过滤无意义短语 / Filter trivial phrases
    lower = content.lower().strip()
    for phrase in _MEMORY_SKIP_PHRASES:
        if lower == phrase or lower.startswith(phrase + ".") or lower.startswith(phrase + ","):
            return None
    return content


def _parse_reflection_answer(text: str) -> str:
    """
    从反思节点输出中解析 '### Answer ###' → A / B / C。
    Parse '### Answer ###' from Reflection node output → A / B / C.
    """
    m = re.search(r"###\s*Answer\s*###\s*([ABC])", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if "A" in text.upper():
        return "A"
    if "B" in text.upper():
        return "B"
    if "C" in text.upper():
        return "C"
    return "A"


def _get_last_ai(messages: list) -> Optional[AIMessage]:
    """
    取消息列表中最后一条 AIMessage。
    Return the last AIMessage from the message list, or None.
    """
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return m
    return None


def _message_content_to_str(content: Any) -> str:
    """
    将消息 content（list 或 str）统一转为字符串。
    Normalize message content (list or str) into a plain string.
    """
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(str(p) for p in content).strip()
    return str(content).strip()


def _get_last_user_content(messages: list) -> str:
    """
    取消息列表中最后一条用户消息文本。
    Return the text content of the last HumanMessage.
    """
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _message_content_to_str(m.content)
    return ""


def _format_tool_calls_action(ai_message: Optional[AIMessage]) -> str:
    """
    将 AIMessage 中的 tool_calls 格式化为可读字符串。
    Format tool_calls from an AIMessage into a readable action description.
    """
    if not ai_message or not getattr(ai_message, "tool_calls", None):
        return ""
    tcs = ai_message.tool_calls or []
    return "; ".join(
        (tc.get("name") or getattr(tc, "name", "")) + "(" + str(tc.get("args") or getattr(tc, "args", "")) + ")"
        for tc in tcs
    )


def _extract_last_ai_content(messages: list) -> Optional[str]:
    """
    从消息列表末尾取第一条非空 AI 文本，作为最终回复。
    Extract the first non-empty AI text from the tail of message list for final reply.
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            c = _message_content_to_str(msg.content)
            if c:
                return c
    return None


# ---------------------------------------------------------------------------
# StepRecord 辅助函数 / StepRecord helpers: fingerprint, construction, task matching
# ---------------------------------------------------------------------------

def _fingerprint_operation(tool: str, target: str, params: Dict[str, Any]) -> str:
    """
    生成稳定的操作签名（不含结果），用于判重。
    Generate a stable operation signature (result-independent) for deduplication.
    """
    base = "|".join([
        (tool or "").lower().strip(),
        (target or "").lower().strip(),
        json.dumps(params or {}, sort_keys=True, ensure_ascii=False)[:500],
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _make_step_record(
    tool: str,
    target: str,
    params: Dict[str, Any],
    success: bool,
    result_summary: str,
    task_ids: Optional[List[str]] = None,
) -> StepRecord:
    sig = _fingerprint_operation(tool, target, params or {})
    return StepRecord(
        id=f"step-{int(time.time() * 1000)}",
        tool=tool,
        target=target,
        params=params or {},
        success=bool(success),
        timestamp=time.time(),
        task_ids=task_ids or [],
        result_summary=(result_summary or "")[:1000],
        signature=sig,
    )


def _extract_tool_target(tool_name: str, args: Dict[str, Any]) -> str:
    """
    从工具参数中提取最具代表性的目标值（URL/路径/查询词）。
    Extract the most representative target value (URL, path, or query) from tool args.
    """
    if not args:
        return ""
    for key in ("query", "url", "path", "file_path"):
        v = args.get(key)
        if v and isinstance(v, str):
            return v.strip()
    return str(next(iter(args.values()), ""))[:200]


def _match_tasks_for_tool(tool_name: str, target: str, success: bool, tasks: List[Task]) -> List[str]:
    """
    基于简单规则将工具调用结果映射到受影响的任务 ID。
    Map a tool call result to affected task IDs using simple keyword rules.
    """
    if not tasks or not tool_name:
        return []
    affected: List[str] = []
    target_lower = (target or "").lower()
    target_tokens = set(target_lower.replace("/", " ").replace("\\", " ").replace(".", " ").split())
    for t in tasks:
        desc = str(t.get("description") or "").lower()
        if not desc:
            continue
        tid = str(t.get("id") or "")
        status = str(t.get("status") or "pending").lower()
        if status == "completed":
            continue
        matched = False
        if tool_name in ("write_file",) and any(kw in desc for kw in ("write", "save", "create", "写", "保存", "创建")):
            matched = True
        elif tool_name in ("web_search", "web_search_with_content") and any(kw in desc for kw in ("search", "搜索", "查", "find")):
            matched = True
        elif tool_name in ("fetch_webpage", "fetch_and_summarize_url") and any(kw in desc for kw in ("fetch", "read", "获取", "抓取", "url")):
            matched = True
        elif tool_name == "get_current_datetime" and any(kw in desc for kw in ("date", "time", "日期", "时间", "today", "今天")):
            matched = True
        elif tool_name == "get_desktop_path" and any(kw in desc for kw in ("desktop", "桌面", "path", "路径")):
            matched = True
        if not matched and target_tokens:
            overlap = sum(1 for tok in target_tokens if len(tok) > 2 and tok in desc)
            if overlap >= 1:
                matched = True
        if matched:
            affected.append(tid)
    return affected


def get_available_models(base_url: str = "http://127.0.0.1:11434") -> List[str]:
    """
    获取 Ollama 服务器上可用的模型列表。
    Fetch the list of available models from the Ollama server.
    """
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [m["name"] for m in models]
    except Exception as e:
        logger.warning(f"无法获取模型列表: {e}")
        return []


def select_best_model(base_url: str = "http://127.0.0.1:11434") -> str:
    """
    按偏好列表自动选择最佳可用模型。
    Automatically select the best available model from a preference list.
    """
    available = get_available_models(base_url)
    
    if not available:
        logger.warning("无法获取可用模型，使用默认模型 llama2")
        return "llama2"
    
    preferred_models = ["qwen", "llama3", "llama2", "mistral", "codellama"]
    
    for preferred in preferred_models:
        for model in available:
            if preferred in model.lower():
                return model
    return available[0]


def _ensure_chat_model_name(model: Optional[str]) -> str:
    """
    确保对话模型不是纯嵌入模型；为空或包含 'embedding' 时回退为 DEFAULT_CHAT_MODEL。
    Ensure the chat model is not an embedding-only model; fall back to
    DEFAULT_CHAT_MODEL when the name is empty or contains 'embedding'.
    """
    name = (model or "").strip()
    if not name:
        return DEFAULT_CHAT_MODEL
    lower = name.lower()
    if "embedding" in lower:
        logger.warning(
            "[LLM] 检测到疑似嵌入模型 '%s'，已自动切换为聊天模型 '%s'",
            name,
            DEFAULT_CHAT_MODEL,
        )
        return DEFAULT_CHAT_MODEL
    return name


class SecureAgent:
    """
    SecureAgent — 基于 LangGraph StateGraph 的多节点 Agent 系统。
    节点：任务分解 → 规划 → 决策 → 执行 → 记忆 → 反思 → 重试强化。
    SecureAgent — multi-node agent system built on LangGraph StateGraph.
    Nodes: task_decomposer → planning → decision → execute → memory → reflection → retry_reinforcement.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: str = "http://127.0.0.1:11434",
        temperature: float = 0.7,
        max_steps: int = 10,
        tools: Optional[List["BaseTool"]] = None,
        mcp_loop: Optional[asyncio.AbstractEventLoop] = None,
        prompt_kind: str = "local",
        prompt_sandbox_enabled: bool = False,
    ):
        if tools is None:
            raise ValueError("tools 为必选，请通过 MCP 获取后传入")
        self.base_url = base_url
        self.max_steps = max_steps
        self._mcp_loop = mcp_loop
        # RAG 开关，可被每次请求覆盖 / RAG toggle, overridable per request
        self._rag_enabled: bool = RAG_ENABLED_DEFAULT

        if model is None:
            # 优先使用全局配置模型，为空时回退默认值 / Prefer global config model; fallback to default
            cfg_model = getattr(config.llm, "model", "") if hasattr(config, "llm") else ""
            model = (cfg_model or DEFAULT_CHAT_MODEL)

        model = _ensure_chat_model_name(model)
        self.model_name = model

        self.llm = ChatOllama(model=self.model_name, base_url=base_url, temperature=temperature)
        self.tools = tools
        workspace_root = getattr(config.agent, "workspace_root", "") or ""

        # --- Skills System 初始化 / Skills System initialization ---
        self._skills_index = {}
        self._skills_path_to_name: Dict[str, str] = {}
        self._skills_system_section = ""
        try:
            agent_cfg = getattr(config, "agent", None)
            enable_skills = bool(getattr(agent_cfg, "enable_skills", False))
            skills_enabled_agents = getattr(agent_cfg, "skills_enabled_agents", ["decision"])
            is_decision_agent = "decision" in skills_enabled_agents
            if enable_skills and is_decision_agent:
                sources = list(getattr(agent_cfg, "skills_sources", ["/skills/"]))
                self._skills_index = load_skills_from_sources(sources, workspace_root or os.getcwd())
                visible_skills = filter_skills_for_agent(self._skills_index, "decision")
                if visible_skills:
                    # path → name 映射，用于日志 / path→name map for logging
                    self._skills_path_to_name = {m.path: m.name for m in visible_skills}
                    # 构建决策节点的 Skills 描述段 / Build Skills section for Decision node
                    self._skills_system_section = build_skills_system_section(
                        visible_skills,
                        sources=sources,
                        language="zh",
                    )
        except Exception as e:
            logger.warning("[Skills] 初始化 Skills System 失败，将忽略技能系统: %s", e)
            self._skills_index = {}
            self._skills_path_to_name = {}
            self._skills_system_section = ""

        base = SYSTEM_PROMPT_CLOUD if prompt_kind == "cloud" else SYSTEM_PROMPT
        self.system_prompt = build_system_prompt(
            base, workspace_root, enable_sandbox=prompt_sandbox_enabled, kind=prompt_kind
        )
        self.memory = MemorySaver()
        self.session_id = "default"

        # 可选节点开关 / Optional node switches
        self._reflection_switch = getattr(config.agent, "reflection_switch", True)
        self._memory_switch = getattr(config.agent, "memory_switch", True)

        # 构建多节点状态图 / Build the multi-node state graph
        builder = StateGraph(AgentState)

        builder.add_node("task_decomposer", lambda s: self._task_decomposer_node(s))
        builder.add_node("planning", lambda s: self._planning_node(s))
        builder.add_node("decision", lambda s: self._decision_node(s))
        builder.add_node("execute", lambda s: self._execute_node(s))
        builder.add_node("memory", lambda s: self._memory_node(s))
        builder.add_node("reflection", lambda s: self._reflection_node(s))
        builder.add_node("retry_reinforcement", lambda s: self._retry_reinforcement_node(s))

        builder.add_edge(START, "task_decomposer")
        builder.add_edge("task_decomposer", "planning")
        builder.add_edge("planning", "decision")
        builder.add_conditional_edges(
            "decision",
            self._route_after_decision,
            {"execute": "execute", "retry_reinforcement": "retry_reinforcement", "end": END},
        )
        builder.add_edge("retry_reinforcement", "decision")
        if self._memory_switch:
            builder.add_edge("execute", "memory")
            builder.add_edge("memory", "reflection" if self._reflection_switch else "planning")
        else:
            builder.add_edge("execute", "reflection" if self._reflection_switch else "planning")
        if self._reflection_switch:
            builder.add_edge("reflection", "planning")

        # 编译图 / Compile the graph (recursion_limit passed at invoke time)
        self.agent = builder.compile(checkpointer=self.memory)

    def _initial_state_for_turn(self, user_input: str, invoke_config: dict) -> AgentState:
        """
        构造本轮初始状态：有 checkpoint 时合并历史，否则创建全新 state。
        Build the initial state for this turn: merge from checkpoint if available, else create fresh state.
        """
        try:
            snap = self.agent.get_state(invoke_config)
            v = getattr(snap, "values", snap) if snap else None
            if v is not None:
                prev_messages = list((v or {}).get("messages") or [])
                # 新一轮输入：重置重试计数和任务列表 / New turn: reset retry_count & tasks
                return {
                    "messages": prev_messages + [HumanMessage(content=user_input)],
                    "agent_memory": v.get("agent_memory") or "",
                    "task_progress": v.get("task_progress") or "",
                    "operation_history": list(v.get("operation_history") or []),
                    "error_flag": bool(v.get("error_flag")),
                    "retry_count": 0,
                    "tasks": [],
                    "step_records": [],
                    "recent_signatures": [],
                    "repeat_counter": {},
                    "no_progress_count": 0,
                }
        except Exception:
            pass
        return {
            "messages": [HumanMessage(content=user_input)],
            "agent_memory": "",
            "task_progress": "",
            "operation_history": [],
            "error_flag": False,
            "retry_count": 0,
            "tasks": [],
            "step_records": [],
            "recent_signatures": [],
            "repeat_counter": {},
            "no_progress_count": 0,
        }

    # 防空转阈值 / Anti-loop thresholds
    _MAX_SAME_SIGNATURE_REPEAT = 2
    _MAX_NO_PROGRESS_CYCLES = 3

    def _route_after_decision(self, state: AgentState) -> str:
        """
        决策后三路由：有 tool_calls → execute（含空转检查）；
        error_flag 且未重试 → retry_reinforcement；其余 → end。
        Three-way routing after Decision: tool_calls → execute (with
        loop check); error_flag & no retry yet → retry; otherwise → end.
        """
        last_ai = _get_last_ai(state.get("messages") or [])
        has_tool_calls = bool(last_ai and getattr(last_ai, "tool_calls", None))
        if has_tool_calls:
            no_progress = int(state.get("no_progress_count", 0))
            if no_progress >= self._MAX_NO_PROGRESS_CYCLES:
                logger.warning("[Route] 连续 %d 轮无进展，强制结束循环", no_progress)
                return "end"
            repeat = dict(state.get("repeat_counter") or {})
            recent = list(state.get("recent_signatures") or [])
            if recent:
                latest_sig = recent[-1]
                if repeat.get(latest_sig, 0) >= self._MAX_SAME_SIGNATURE_REPEAT:
                    logger.warning("[Route] signature %s 已重复 %d 次，强制结束循环", latest_sig[:8], repeat[latest_sig])
                    return "end"
            return "execute"
        error_flag = bool(state.get("error_flag"))
        retry_count = int(state.get("retry_count", 0))
        if error_flag and retry_count < 1:
            return "retry_reinforcement"
        return "end"

    def _task_decomposer_node(self, state: AgentState) -> dict:
        """
        任务分解节点：tasks 为空时根据用户指令生成子任务列表。
        Task decomposer node: generate sub-task list from user instruction when tasks is empty.
        """
        logger.info("[Task Decomposer] 检查是否需要生成任务列表")
        existing_tasks = list(state.get("tasks") or [])
        if existing_tasks:
            logger.info("[Task Decomposer] 已存在任务列表，跳过分解")
            return {}
        instruction = _get_last_user_content(state.get("messages") or [])
        if not instruction:
            logger.info("[Task Decomposer] 无用户指令，跳过分解")
            return {}
        from prompts.prompts import TASK_DECOMPOSER_PROMPT  # 局部导入 / local import to avoid circular dependency
        prompt = TASK_DECOMPOSER_PROMPT.format(instruction=instruction)
        try:
            resp = self.llm.invoke([HumanMessage(content=prompt)])
            raw = (resp.content or "").strip()
            # 从响应中提取 JSON 数组 / Extract JSON array from response
            start = raw.find("[")
            end = raw.rfind("]")
            if start == -1 or end == -1 or end <= start:
                logger.warning("[Task Decomposer] 未找到有效 JSON 数组，任务列表保持为空")
                return {}
            json_str = raw[start : end + 1]
            parsed = json.loads(json_str)
            if not isinstance(parsed, list):
                logger.warning("[Task Decomposer] JSON 顶层不是列表，任务列表保持为空")
                return {}
            tasks: List[Task] = []
            for idx, item in enumerate(parsed, start=1):
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("description") or "").strip()
                if not desc:
                    continue
                tid = str(item.get("id") or f"task-{idx}")
                status = str(item.get("status") or "pending").lower()
                if status not in ("pending", "in_progress", "completed"):
                    status = "pending"
                evidence = str(item.get("evidence") or "").strip()
                tasks.append(
                    Task(
                        id=tid,
                        description=desc,
                        status=status,
                        evidence=evidence,
                    )
                )
            if not tasks:
                logger.info("[Task Decomposer] 解析结果为空，任务列表保持为空")
                return {}
            logger.info("[Task Decomposer] 已生成 %d 个任务", len(tasks))
            return {"tasks": tasks}
        except Exception as e:
            logger.warning("[Task Decomposer] 分解任务失败，将继续无任务列表: %s", e)
            return {}

    def _build_routing_hints(self, instruction: str) -> str:
        """
        根据用户指令构建 RAG / web_search 路由提示（仅建议，非强制）。
        Build soft routing hints (RAG vs web_search) based on user instruction keywords.
        """
        if not instruction:
            return ""
        text = instruction.lower()
        hints = []
        time_keywords = ("今天", "今日", "现在", "最新", "实时", "weather", "today", "now", "news")
        internal_keywords = ("代码", "函数", "类", "接口", "api", "config", "配置", "path", "路径", "项目文档")
        is_time_sensitive = any(k.lower() in text for k in time_keywords)
        is_internal_like = any(k.lower() in text for k in internal_keywords)
        if is_time_sensitive:
            hints.append(
                "- The query looks time-sensitive (e.g. today/now/latest); prefer using web_search or similar real-time tools."
            )
        if is_internal_like:
            hints.append(
                "- The query seems related to internal code/docs; prefer using RAG over generic web search when possible."
            )
        if not hints:
            return ""
        return "### Routing hints ###\n" + "\n".join(hints) + "\n"

    # 重试强化节点注入的系统提示 / System prompt injected by retry-reinforcement node
    RETRY_REINFORCEMENT_NOTICE = (
        "SYSTEM_REINFORCEMENT_NOTICE: Your previous response was a direct text reply, but the task is classified as not yet complete. "
        "Under system rules, you are FORBIDDEN from replying with text until all tool-based actions are finished. "
        "You MUST call a tool (e.g., get_desktop_path or write_file) to complete the physical execution of the user's request. "
        "Failure to do so in this turn will be logged as a logic error. Call the tool now."
    )

    def _retry_reinforcement_node(self, state: AgentState) -> dict:
        """
        重试强化节点：递增 retry_count 并注入强制工具调用提示。
        Retry-reinforcement node: increment retry_count and inject forced tool-call prompt.
        """
        logger.info("[Retry Reinforcement] 注入强制工具调用提示，重试次数 +1")
        retry_count = int(state.get("retry_count", 0)) + 1
        return {
            "messages": [SystemMessage(content=self.RETRY_REINFORCEMENT_NOTICE)],
            "retry_count": retry_count,
        }

    def _planning_node(self, state: AgentState) -> dict:
        """
        规划节点：汇总指令、上一步操作和任务列表，输出任务进度摘要。
        Planning node: synthesize instruction, last operation, and task list
        into an updated task-progress summary.
        """
        logger.info("[Planning Agent] 开始更新任务进度")
        instruction = _get_last_user_content(state.get("messages") or [])
        last_op = ""
        oh = state.get("operation_history") or []
        if oh:
            last = oh[-1]
            if isinstance(last, dict):
                last_op = str(last.get("thought", "")) + "; " + str(last.get("action", ""))
            else:
                last_op = str(getattr(last, "thought", "")) + "; " + str(getattr(last, "action", ""))
        # 将任务列表序列化为可读文本 / Serialize task list to readable text
        tasks = list(state.get("tasks") or [])
        if tasks:
            lines = []
            for t in tasks:
                try:
                    tid = str(t.get("id") or "")
                    desc = str(t.get("description") or "")
                    status = str(t.get("status") or "pending")
                    lines.append(f"- [{status}] {desc}" + (f" (id={tid})" if tid else ""))
                except Exception:
                    continue
            tasks_block = "\n".join(lines) if lines else "(none)"
        else:
            tasks_block = "(none)"

        prompt = PLANNING_PROMPT.format(
            instruction=instruction or "(none)",
            last_operation=last_op or "(none)",
            task_progress=state.get("task_progress") or "",
            agent_memory=state.get("agent_memory") or "",
            tasks_block=tasks_block,
        )
        response = self.llm.invoke([HumanMessage(content=prompt)])
        content = (response.content or "").strip()
        tp = _parse_task_progress(content)
        logger.info("[Planning Agent] 完成: task_progress=%s", (tp[:100] + "...") if len(tp) > 100 else tp)
        return {"task_progress": tp}

    def _decision_node(self, state: AgentState) -> dict:
        """
        决策节点：组装上下文（RAG/Skills/路由提示）并调用 LLM，输出 tool_calls 或纯文本。
        Decision node: assemble context (RAG, Skills, routing hints) and invoke LLM; outputs tool_calls or text.
        """
        logger.info("[Decision Agent] 开始决策")
        messages = state.get("messages") or []
        task_progress = state.get("task_progress") or ""
        agent_memory = state.get("agent_memory") or ""
        error_flag = state.get("error_flag") or False
        error_note = ERROR_FLAG_TRUE if error_flag else ERROR_FLAG_FALSE

        # RAG 上下文注入 / Inject RAG context into system prompt if enabled
        rag_section = ""
        rag_prompt = ""
        user_query = _get_last_user_content(messages)
        if getattr(self, "_rag_enabled", False):
            if user_query:
                try:
                    rag_context = get_rag_context(user_query, max_chars=MAX_CONTEXT_CHARS)
                except Exception as e:
                    logger.warning(f"[RAG] 检索失败（将忽略本轮 RAG）: {e}")
                    rag_context = ""
                if rag_context:
                    rag_prompt = RAG_PROMPT_SECTION + "\n\n"
                    rag_section = (
                        "### RAG Context ###\n"
                        f"{rag_context}\n\n"
                        "You are given the above internal knowledge base snippets (RAG context). "
                        "When they are relevant to the user's question, you MUST treat them as the primary source of truth. "
                        "If they appear incomplete or conflicting with other sources, explain the uncertainty instead of hallucinating.\n"
                    )
                    logger.info("[RAG] 本轮决策已启用 RAG 上下文")

        # 构建最近工具调用摘要 / Build recent tool-call summary from StepRecords
        step_records = list(state.get("step_records") or [])
        no_progress = int(state.get("no_progress_count", 0))
        if step_records:
            recent_steps = step_records[-5:]
            rts_lines = []
            for s in recent_steps:
                rts_lines.append("- tool={}, target={}, success={}, affected_tasks={}".format(
                    s.get("tool", "?"),
                    (s.get("target") or "")[:50],
                    s.get("success"),
                    s.get("task_ids") or [],
                ))
            recent_tool_summary = "\n".join(rts_lines)
            if no_progress > 0:
                recent_tool_summary += f"\n⚠ WARNING: {no_progress} consecutive cycles with NO progress detected."
        else:
            recent_tool_summary = "(no tool calls yet)"

        extra = DECISION_SYSTEM_EXTRA.format(
            task_progress=task_progress,
            agent_memory=agent_memory or "(none)",
            recent_tool_summary=recent_tool_summary,
            error_flag_note=error_note,
        )
        full_system_parts = [self.system_prompt]
        # Skills System：注入优先规则 + 技能数据 / Skills: inject priority rules + skill data
        if getattr(self, "_skills_system_section", ""):
            full_system_parts.append(SKILLS_PRIORITY_SECTION)
            full_system_parts.append(self._skills_system_section)
        if rag_prompt:
            full_system_parts.append(rag_prompt)
        if rag_section:
            full_system_parts.append(rag_section)
        # 软路由提示 / Soft routing hints
        routing_hints = self._build_routing_hints(user_query or "")
        if routing_hints:
            full_system_parts.append(routing_hints)
        full_system_parts.append(extra)
        full_system = "\n".join(full_system_parts)
        llm_with_tools = self.llm.bind_tools(self.tools)
        response = llm_with_tools.invoke(
            [SystemMessage(content=full_system)] + list(messages)
        )
        tcs = getattr(response, "tool_calls", None) or []
        if tcs:
            names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in tcs]
            logger.info("[Decision Agent] 完成: 调用工具 %s", ", ".join(names))
        else:
            logger.info("[Decision Agent] 完成: 直接回复")
        return {"messages": [response]}

    def _execute_node(self, state: AgentState) -> dict:
        """
        执行节点：调用工具、写入 StepRecord、根据规则更新任务状态。
        Execute node: invoke tools, write StepRecords, update task status by rules.
        """
        logger.info("[Execute] 开始执行工具")
        messages = state.get("messages") or []
        last_ai = _get_last_ai(messages)
        if not last_ai or not getattr(last_ai, "tool_calls", None):
            return {}
        tool_calls = last_ai.tool_calls or []
        name_to_tool = {t.name: t for t in self.tools}
        tool_messages: List[ToolMessage] = []
        new_steps: List[StepRecord] = []
        tasks = list(state.get("tasks") or [])

        for tc in tool_calls:
            tid = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", None) or getattr(tc, "tool_call_id", "") or ""
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            raw_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args if isinstance(raw_args, dict) else {}
            tool = name_to_tool.get(name)
            if not tool:
                tool_messages.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=tid))
                continue
            try:
                if self._mcp_loop and hasattr(tool, "ainvoke"):
                    future = asyncio.run_coroutine_threadsafe(tool.ainvoke(args), self._mcp_loop)
                    result = future.result(timeout=120)
                else:
                    result = tool.invoke(args)
            except Exception as e:
                result = str(e)
            logger.info("[Execute] 工具 %s 执行完成", name)

            try:
                if isinstance(args, dict):
                    skill_path = str(args.get("path") or args.get("file_path") or "")
                    if skill_path.startswith("/skills/"):
                        skill_name = self._skills_path_to_name.get(skill_path, "<unknown-skill>")
                        logger.info("[Skills] 使用技能 %s (path=%s) via tool %s", skill_name, skill_path, name)
            except Exception:
                pass

            content = result if isinstance(result, str) else str(result)
            tool_messages.append(ToolMessage(content=content, tool_call_id=str(tid)))

            # --- 构造 StepRecord / Build StepRecord ---
            target = _extract_tool_target(name, args)
            result_lower = content.lower()
            success = "error" not in result_lower[:200] and "not found" not in result_lower[:200] and "unknown tool" not in result_lower[:200]
            if name == "write_file":
                success = "success" in result_lower
            affected_ids = _match_tasks_for_tool(name, target, success, tasks)
            step = _make_step_record(name, target, args, success, content[:500], affected_ids)
            new_steps.append(step)
            logger.info("[Execute] StepRecord: tool=%s target=%s success=%s tasks=%s sig=%s",
                        name, target[:40], success, affected_ids, step["signature"][:8])

            # --- 根据 StepRecord 更新任务状态 / Update task status from StepRecord ---
            if affected_ids and success:
                updated_tasks = []
                for t in tasks:
                    t_id = str(t.get("id") or "")
                    if t_id in affected_ids and str(t.get("status") or "pending") != "completed":
                        updated_tasks.append(Task(
                            id=t_id,
                            description=str(t.get("description") or ""),
                            status="completed",
                            evidence=step["result_summary"][:200],
                        ))
                    else:
                        updated_tasks.append(t)
                tasks = updated_tasks

        # --- 更新签名与重复计数 / Update signatures & repeat counter ---
        sr = list(state.get("step_records") or [])
        sr.extend(new_steps)
        recent = list(state.get("recent_signatures") or [])
        repeat = dict(state.get("repeat_counter") or {})
        for s in new_steps:
            sig = s["signature"]
            recent.append(sig)
            repeat[sig] = repeat.get(sig, 0) + 1
        recent = recent[-50:]

        # --- 追加操作历史 / Append to operation_history ---
        oh = list(state.get("operation_history") or [])
        thought = (last_ai.content or "").strip() if last_ai else ""
        action_desc = _format_tool_calls_action(last_ai)
        oh.append({"thought": thought[:300], "action": action_desc})

        logger.info("[Execute] 共执行 %d 个工具, 生成 %d 个 StepRecord", len(tool_messages), len(new_steps))
        return {
            "messages": tool_messages,
            "retry_count": 0,
            "tasks": tasks,
            "step_records": sr,
            "recent_signatures": recent,
            "repeat_counter": repeat,
            "operation_history": oh,
        }

    def _memory_node(self, state: AgentState) -> dict:
        """
        记忆节点：优先用 StepRecord 写入结构化里程碑，无 StepRecord 时降级为 LLM 提取。
        Memory node: prefer structured milestone from StepRecord; fall back to LLM extraction.
        """
        logger.info("[Memory Agent] 开始提炼焦点内容")
        messages = state.get("messages") or []
        instruction = _get_last_user_content(messages)
        existing = state.get("agent_memory") or ""

        # 优先从 StepRecord 生成里程碑 / Try structured milestone from StepRecord first
        step_records = list(state.get("step_records") or [])
        recent_sigs = set(state.get("recent_signatures") or [])
        repeat = dict(state.get("repeat_counter") or {})
        content = None

        if step_records:
            latest = step_records[-1]
            sig = latest.get("signature") or ""
            sig_count = repeat.get(sig, 0)

            if sig_count <= 1 or latest.get("success"):
                content = "STEP {}: tool={}, target={}, success={}, tasks={}, summary={}".format(
                    latest.get("id", "?"),
                    latest.get("tool", "?"),
                    (latest.get("target") or "")[:60],
                    latest.get("success"),
                    latest.get("task_ids") or [],
                    (latest.get("result_summary") or "")[:300],
                )
            else:
                logger.info("[Memory Agent] signature %s 已重复 %d 次且 success=%s，跳过",
                            sig[:8], sig_count, latest.get("success"))

        # 降级走 LLM 提取 / Fallback: LLM extraction when no usable StepRecord
        if not content:
            last_ai = None
            tool_results_after_last_ai: List[str] = []
            for m in messages:
                if isinstance(m, AIMessage):
                    last_ai = m
                    tool_results_after_last_ai = []
                elif isinstance(m, ToolMessage):
                    tool_results_after_last_ai.append((m.content or "")[:2000])
            thought = (last_ai.content or "").strip() if last_ai else ""
            action_desc = _format_tool_calls_action(last_ai)
            tool_result = "\n---\n".join(tool_results_after_last_ai[-5:]) if tool_results_after_last_ai else "(no tool result yet)"
            context_summary = f"Intent: {thought or 'N/A'}\nAction: {action_desc or 'N/A'}\nResult: {tool_result}"
            prompt = get_memory_prompt(instruction or "(none)", context_summary, existing)
            response = self.llm.invoke([HumanMessage(content=prompt)])
            raw_response = (response.content or "").strip()
            content = _parse_important_content(raw_response)
            if not content and last_ai and tool_results_after_last_ai:
                last_result = tool_results_after_last_ai[-1]
                has_write = "write_file" in action_desc
                if has_write and "success" in last_result.lower():
                    content = "操作成功：已执行文件写入。"

        if not content:
            logger.info("[Memory Agent] 完成: 无新内容")
            return {}

        # 精确判重 / Exact-match deduplication
        content_line = content.strip()
        if content_line and content_line in existing:
            logger.info("[Memory Agent] 完成: 该条目已存在，跳过")
            return {}

        logger.info("[Memory Agent] 完成: 已追加 %d 字", len(content_line))
        return {"agent_memory": existing + content_line + "\n"}

    def _reflection_node(self, state: AgentState) -> dict:
        """
        反思节点：A/B/C 判定 + no_progress_count 维护 + 任务一致性检查。
        Reflection node: A/B/C judgment, no_progress_count maintenance, and task consistency check.
        """
        logger.info("[Reflection Agent] 开始反思")
        messages = state.get("messages") or []
        last_ai = _get_last_ai(messages)
        last_tool_content = ""
        for m in messages:
            if isinstance(m, ToolMessage):
                last_tool_content = m.content or ""
        thought = (last_ai.content or "").strip() if last_ai else ""
        action_desc = _format_tool_calls_action(last_ai)
        instruction = _get_last_user_content(messages)

        task_progress = state.get("task_progress") or ""
        tasks = list(state.get("tasks") or [])
        if tasks:
            lines = []
            for t in tasks:
                try:
                    tid = str(t.get("id") or "")
                    desc = str(t.get("description") or "")
                    status = str(t.get("status") or "pending")
                    lines.append(f"- [{status}] {desc}" + (f" (id={tid})" if tid else ""))
                except Exception:
                    continue
            tasks_block = "\n".join(lines) if lines else "(none)"
        else:
            tasks_block = "(none)"
        all_tasks_completed = bool(tasks) and all(
            str(t.get("status") or "pending").lower() == "completed" for t in tasks
        )

        prompt = get_reflection_prompt(
            instruction, thought, action_desc, last_tool_content[:1500],
            task_progress, tasks_block, all_tasks_completed,
        )
        response = self.llm.invoke([HumanMessage(content=prompt)])
        answer = _parse_reflection_answer((response.content or "").strip())
        error_flag = answer != "A"
        out: Dict[str, Any] = {"error_flag": error_flag, "reflection_answer": answer}

        # 一致性检查 / Consistency check
        if all_tasks_completed and answer != "A":
            logger.warning("[Reflection] all_tasks_completed=True 但模型给出 %s", answer)
        if (not all_tasks_completed) and answer == "A" and tasks:
            logger.warning("[Reflection] all_tasks_completed=False 但模型给出 A")

        # 判断本轮是否有实质进展 / Check if real progress was made this cycle
        step_records = list(state.get("step_records") or [])
        observed_progress = False
        if step_records:
            latest = step_records[-1]
            observed_progress = bool(latest.get("success") and latest.get("task_ids"))

        # 维护无进展计数 / Maintain no_progress_count
        if observed_progress or answer == "A":
            out["no_progress_count"] = 0
        else:
            out["no_progress_count"] = int(state.get("no_progress_count", 0)) + 1
            logger.info("[Reflection] no_progress_count=%d", out["no_progress_count"])

        # answer==A 时标记所有任务完成 / Mark all tasks completed when answer==A
        if answer == "A" and tasks:
            completed_tasks: List[Task] = []
            for t in tasks:
                try:
                    completed_tasks.append(Task(
                        id=str(t.get("id") or ""),
                        description=str(t.get("description") or ""),
                        status="completed",
                        evidence=str(t.get("evidence") or ""),
                    ))
                except Exception:
                    continue
            if completed_tasks:
                out["tasks"] = completed_tasks

        logger.info("[Reflection Agent] 完成: 结果=%s, observed_progress=%s", answer, observed_progress)
        return out

    async def _chat_async(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        status_callback: Optional[Callable[..., None]] = None,
        use_rag: Optional[bool] = None,
    ) -> str:
        """
        异步对话入口，通过 astream_events 流式推送节点状态。
        Async chat entry; streams node status via astream_events and falls back to ainvoke.
        """
        if session_id:
            self.session_id = session_id
        if use_rag is not None:
            self._rag_enabled = bool(use_rag)
        invoke_config = {
            "configurable": {"thread_id": self.session_id},
            "recursion_limit": self.max_steps * 8,
        }
        inputs = self._initial_state_for_turn(user_input, invoke_config)

        # 记录本轮前最后 AIMessage 索引，区分新旧回复 / Track last AI index to detect new replies
        prev_last_ai_idx: int = -1
        try:
            snap = self.agent.get_state(invoke_config)
            values = getattr(snap, "values", snap) if snap else {}
            base_messages = (values or {}).get("messages") or []
            for i in range(len(base_messages) - 1, -1, -1):
                if isinstance(base_messages[i], AIMessage):
                    prev_last_ai_idx = i
                    break
        except Exception:
            prev_last_ai_idx = -1

        node_start: Dict[str, float] = {}
        NODE_NAMES = {"planning", "decision", "execute", "memory", "reflection", "retry_reinforcement"}

        def _emit(status: str, detail: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> None:
            if status_callback:
                try:
                    status_callback(status, detail, extra)
                except TypeError:
                    try:
                        status_callback(status, detail)
                    except Exception:
                        pass
                except Exception:
                    pass
            if status == "planning":
                logger.info("[MCP] 状态: 规划中")
            elif status == "decision":
                logger.info("[MCP] 状态: 决策中")
            elif status == "execute" and detail:
                logger.info(f"[MCP] 工具执行: {detail}")
            elif status == "memory":
                logger.info("[MCP] 状态: 记忆中")
            elif status == "reflection":
                logger.info("[MCP] 状态: 反思中")

        def _content_for_node(name: str, output: Any) -> str:
            """
            统一的 UI 展示格式：前缀 + 内容，处理占位符。
            Unified UI display format per node: prefix + content; handles placeholder.
            """
            if not isinstance(output, dict):
                return ""
            if name == "planning":
                tp = (output.get("task_progress", "") or "").strip()
                if not tp or tp.lower() == "<your updated task progress summary here>":
                    return "Task progress: (none yet)"
                if not tp.lower().startswith("task progress:"):
                    tp = "Task progress: " + tp
                return (tp[:300] + "...") if len(tp) > 300 else tp
            if name == "decision":
                msgs = output.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                        tcs = last.tool_calls or []
                        names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in tcs]
                        return "Decision: call tools " + ", ".join(names)
                return "Decision: direct reply"
            if name == "execute":
                msgs = output.get("messages", [])
                n = sum(1 for m in msgs if isinstance(m, ToolMessage))
                return f"Execute: ran {n} tool(s)" if n else "Execute: running"
            if name == "memory":
                am = output.get("agent_memory") or ""
                if am:
                    snippet = (am[:200] + "...") if len(am) > 200 else am
                    return "Memory: focus content recorded — " + snippet
                return "Memory: no new content"
            if name == "reflection":
                ans = output.get("reflection_answer")
                if ans == "A":
                    return "Reflection: result correct"
                if ans == "B":
                    return "Reflection: result erroneous"
                if ans == "C":
                    return "Reflection: result ineffective"
                return "Reflection: " + str(ans) if ans else ""
            if name == "retry_reinforcement":
                return "Retry: must call tool"
            return ""

        last_content: Optional[str] = None
        if status_callback:
            try:
                async for event in self.agent.astream_events(inputs, config=invoke_config, version="v2"):
                    kind = event.get("event") or ""
                    name = event.get("name") or ""
                    if kind == "on_chain_start" and name and name in NODE_NAMES:
                        node_start[name] = time.perf_counter()
                        _emit(name, None)
                    elif kind == "on_chain_end" and name and name in NODE_NAMES:
                        out = event.get("data", {}).get("output")
                        duration_sec = round(time.perf_counter() - node_start.get(name, 0), 2)
                        content = _content_for_node(name, out) if isinstance(out, dict) else ""
                        extra = {"content": content, "duration_sec": duration_sec}
                        _emit(name, None, extra)
                        if isinstance(out, dict) and "messages" in out:
                            last_content = _extract_last_ai_content(out["messages"])
            except Exception as e:
                logger.warning("[MCP] astream_events 异常，回退 ainvoke: %s", e)
            if last_content is not None:
                logger.info("[MCP] 全部任务结束")
                return last_content
            # 流式无新回复时，从最新状态提取 / If streaming produced no new reply, try latest state
            try:
                state = self.agent.get_state(invoke_config)
                values = getattr(state, "values", state) if state else {}
                messages = (values or {}).get("messages", [])
                new_last_ai_idx = -1
                for i in range(len(messages) - 1, -1, -1):
                    if isinstance(messages[i], AIMessage):
                        new_last_ai_idx = i
                        break
                if new_last_ai_idx > prev_last_ai_idx:
                    last_content = _extract_last_ai_content(messages)
                    if last_content is not None:
                        logger.info("[MCP] 全部任务结束（来自最新状态的新回复）")
                        return last_content
            except Exception:
                pass
        result = await self.agent.ainvoke(inputs, config=invoke_config)
        messages = result.get("messages", [])
        last_content = _extract_last_ai_content(messages)
        if last_content is not None:
            logger.info("[MCP] 全部任务结束")
            return last_content
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                logger.info("[MCP] 全部任务结束")
                return "无法生成有效回复。"
        logger.info("[MCP] 全部任务结束")
        return "抱歉，我无法生成有效的响应。"

    def chat(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        status_callback: Optional[Callable[..., None]] = None,
        use_rag: Optional[bool] = None,
    ) -> str:
        """
        同步对话入口：通过 MCP event loop 调度 _chat_async。
        Synchronous chat entry: dispatches _chat_async via the MCP event loop.
        """
        if session_id:
            self.session_id = session_id
        logger.info(f"[MCP] 请求: {user_input[:50]}..." if len(user_input) > 50 else f"[MCP] 请求: {user_input}")
        if use_rag is not None:
            self._rag_enabled = bool(use_rag)
        try:
            if self._mcp_loop is None:
                return "错误: 当前仅支持通过 MCP 使用 Agent（请通过 main.py 或 Web UI 启动）。"
            future = asyncio.run_coroutine_threadsafe(
                self._chat_async(user_input, session_id, status_callback=status_callback, use_rag=use_rag),
                self._mcp_loop,
            )
            return future.result(timeout=300)
        except Exception as e:
            logger.error(f"[MCP] 处理错误: {e}")
            return f"处理请求时发生错误: {str(e)}"
    
    def run(self, user_input: str) -> str:
        """chat() 的别名。 / Alias for chat()."""
        return self.chat(user_input)
    
    def reset(self, new_session_id: Optional[str] = None):
        """
        重置会话状态。
        Reset the agent session state with a new session ID.
        """
        if new_session_id:
            self.session_id = new_session_id
        else:
            import time
            self.session_id = f"session_{int(time.time())}"
        logger.info(f"Agent状态已重置，新会话ID: {self.session_id}")
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """
        获取当前会话的对话历史。
        Get the conversation history for the current session.
        """
        try:
            invoke_config = {"configurable": {"thread_id": self.session_id}}
            state = self.agent.get_state(invoke_config)
            values = getattr(state, "values", state) if state else {}
            messages = (values or {}).get("messages", [])
            history = []
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    history.append({"role": "user", "content": _message_content_to_str(msg.content)})
                elif isinstance(msg, AIMessage):
                    history.append({"role": "assistant", "content": _message_content_to_str(msg.content)})
            return history
        except Exception:
            return []


async def _connect_mcp_impl(use_stdio: bool, sse_url: Optional[str] = None):
    """
    内部 MCP 连接实现：支持 stdio 和 SSE 两种传输方式。
    Internal MCP connection: supports stdio and SSE transports; returns (tools, session, transport).
    """
    from mcp import ClientSession
    from langchain_mcp_adapters.tools import load_mcp_tools
    if use_stdio:
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters
        secure_agent_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server", "--transport", "stdio"],
            env={**os.environ, "PYTHONPATH": secure_agent_root},
        )
        transport = stdio_client(params)
        read, write = await transport.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        tools = await load_mcp_tools(session)
        return tools, session, transport
    else:
        from mcp.client.sse import sse_client
        transport = sse_client(sse_url)
        streams = await transport.__aenter__()
        session = ClientSession(*streams)
        await session.__aenter__()
        await session.initialize()
        tools = await load_mcp_tools(session)
        return tools, session, transport


async def _connect_mcp_and_get_tools():
    """
    CLI 模式：连接 MCP 并返回 (tools, session, transport)。
    CLI mode: connect to MCP using config.mcp and return (tools, session, transport).
    """
    mcp_cfg = config.mcp
    use_stdio = mcp_cfg.transport == "stdio"
    url = None if use_stdio else mcp_cfg.url
    tools, session, transport = await _connect_mcp_impl(use_stdio, url)
    logger.info("[MCP] 连接就绪，共 %d 个工具", len(tools))
    return tools, session, transport


async def _connect_mcp_and_get_tools_web():
    """
    Web UI 模式：根据 _current_web_mcp_source 选择 stdio 或 SSE 连接 MCP。
    Web UI mode: connect to MCP via stdio or SSE based on _current_web_mcp_source.
    """
    source = _current_web_mcp_source
    if source == "cloud":
        url = config.mcp.mcp_cloud_url or config.mcp.url
        tools, session, transport = await _connect_mcp_impl(False, url)
        source_label = "云(Bright Data)"
        logger.info("[MCP] 连接就绪 (来源: %s)，共 %d 个工具", source_label, len(tools))
    else:
        tools, session, transport = await _connect_mcp_impl(True, None)
        source_label = "本地"
        logger.info("[MCP] 连接就绪 (来源: %s)，共 %d 个工具", source_label, len(tools))
    return tools, session, transport


async def run_with_mcp_async(
    run_fn,
    model: Optional[str] = None,
    base_url: str = "http://127.0.0.1:11434",
    **kwargs
):
    """
    在 MCP 连接存活期间运行 Agent，供 main.py CLI 模式使用。
    Run agent with MCP tools; keeps MCP connection alive while run_fn(agent) executes.
    """
    tools, session, transport = await _connect_mcp_and_get_tools()
    try:
        loop = asyncio.get_event_loop()
        agent = SecureAgent(model=model, base_url=base_url, tools=tools, mcp_loop=loop, **kwargs)
        return await loop.run_in_executor(None, lambda: run_fn(agent))
    finally:
        await session.__aexit__(None, None, None)
        await transport.__aexit__(None, None, None)


# --- MCP Web UI 长驻连接 / MCP persistent connection for Web UI ---
_current_web_mcp_source: str = "local"
_web_prompt_sandbox_enabled: bool = False  # Web UI 提示词沙盒开关 / prompt sandbox toggle for Web UI
_mcp_web_agent: Optional["SecureAgent"] = None
_mcp_web_loop: Optional[asyncio.AbstractEventLoop] = None
_mcp_web_session = None
_mcp_web_transport = None
_mcp_web_ready = threading.Event()
_mcp_web_thread: Optional[threading.Thread] = None
_mcp_web_lock = threading.Lock()
_reconnect_event: Optional[asyncio.Event] = None  # 重连信号 / reconnect signal, created inside holder task


async def _mcp_web_connection_holder():
    """
    单任务持有连接：建连/关连/重连均在同一 async task 内，满足 anyio cancel scope 约束。
    Single-task connection holder: open / close / reconnect all happen in the same
    async task to satisfy anyio cancel-scope requirements.
    """
    global _mcp_web_agent, _mcp_web_loop, _mcp_web_session, _mcp_web_transport, _reconnect_event
    _reconnect_event = asyncio.Event()
    llm_cfg = config.llm
    agent_cfg = config.agent
    loop = asyncio.get_event_loop()

    while True:
        # 关闭上一轮连接 / Close previous connection (must be same task for anyio)
        if _mcp_web_session is not None:
            try:
                await _mcp_web_session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("[MCP] 关闭 session 时异常: %s", e)
            _mcp_web_session = None
        if _mcp_web_transport is not None:
            try:
                await _mcp_web_transport.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("[MCP] 关闭 transport 时异常: %s", e)
            _mcp_web_transport = None
        _mcp_web_agent = None
        _mcp_web_ready.clear()

        tools, session, transport = await _connect_mcp_and_get_tools_web()
        _mcp_web_session = session
        _mcp_web_transport = transport
        _mcp_web_agent = SecureAgent(
            model=None,
            base_url=getattr(llm_cfg, "base_url", "http://127.0.0.1:11434"),
            max_steps=getattr(agent_cfg, "max_steps", 10),
            tools=tools,
            mcp_loop=loop,
            prompt_kind=_current_web_mcp_source,
            prompt_sandbox_enabled=_web_prompt_sandbox_enabled,
        )
        _mcp_web_ready.set()
        logger.info("[MCP] Web UI Agent 已就绪 (来源: %s)", _current_web_mcp_source)

        await _reconnect_event.wait()
        _reconnect_event.clear()


def get_current_web_mcp_source() -> str:
    """
    返回当前 Web UI 的 MCP 来源（'local' 或 'cloud'）。
    Return the current MCP source for Web UI ('local' or 'cloud').
    """
    return _current_web_mcp_source


def get_web_prompt_sandbox_enabled() -> bool:
    """
    返回 Web UI 是否开启提示词沙盒防御。
    Return whether the prompt sandbox defense is enabled for Web UI.
    """
    return _web_prompt_sandbox_enabled


def set_web_prompt_sandbox_enabled(enabled: bool) -> None:
    """
    设置 Web UI 提示词沙盒开关，下次重连 MCP 时生效。
    Set the prompt sandbox toggle for Web UI; takes effect on next MCP reconnect.
    """
    global _web_prompt_sandbox_enabled
    _web_prompt_sandbox_enabled = enabled


def switch_web_mcp_source(source: str) -> None:
    """
    切换 Web UI 的 MCP 来源为 'local' 或 'cloud'，触发 holder 任务重连。
    Switch the Web UI MCP source to 'local' or 'cloud'; triggers holder reconnect.
    """
    global _current_web_mcp_source
    if source not in ("local", "cloud"):
        raise ValueError("source 必须为 'local' 或 'cloud'")
    old_source = _current_web_mcp_source
    _current_web_mcp_source = source
    logger.info("[MCP] 切换 MCP 来源: %s -> %s", old_source, source)
    if _reconnect_event is None or _mcp_web_loop is None:
        return
    _mcp_web_ready.clear()
    # asyncio.Event 非线程安全，需 call_soon_threadsafe / Event is not thread-safe; use call_soon_threadsafe
    _mcp_web_loop.call_soon_threadsafe(_reconnect_event.set)
    if not _mcp_web_ready.wait(timeout=120):
        logger.error("[MCP] 切换后等待新连接超时")


def _run_mcp_web_loop():
    """
    在独立线程中运行 event loop，承载 _mcp_web_connection_holder。
    Run the event loop in a dedicated thread to host _mcp_web_connection_holder.
    """
    global _mcp_web_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _mcp_web_loop = loop
    try:
        loop.run_until_complete(_mcp_web_connection_holder())
    finally:
        loop.close()


def start_mcp_background_for_web():
    """
    启动 Web UI 的 MCP 后台线程（幂等，仅首次生效）。
    Start the background MCP thread for Web UI (idempotent, first call only).
    """
    global _mcp_web_thread
    with _mcp_web_lock:
        if _mcp_web_thread is not None and _mcp_web_thread.is_alive():
            return
        _mcp_web_ready.clear()
        _mcp_web_thread = threading.Thread(target=_run_mcp_web_loop, daemon=True)
        _mcp_web_thread.start()


def get_web_mcp_agent(timeout: float = 60.0) -> "SecureAgent":
    """
    获取 Web UI 使用的 MCP Agent；自动启动后台线程并等待连接就绪。
    Get the MCP Agent for Web UI; auto-starts background thread and waits for connection.
    """
    if getattr(config.mcp, "use_mcp", False) is False:
        raise RuntimeError("config.mcp.use_mcp 为 False，不应调用 get_web_mcp_agent")
    start_mcp_background_for_web()
    if not _mcp_web_ready.wait(timeout=timeout):
        raise RuntimeError("等待 MCP 连接超时，Web UI 无法使用 MCP 工具")
    if _mcp_web_agent is None:
        raise RuntimeError("MCP 连接就绪但 Agent 未创建")
    return _mcp_web_agent


def create_agent(
    model: Optional[str] = None,
    base_url: str = "http://127.0.0.1:11434",
    tools: Optional[List["BaseTool"]] = None,
    **kwargs
) -> SecureAgent:
    """
    创建 SecureAgent 实例（工具仅通过 MCP 提供）。
    Create a SecureAgent instance (tools are provided exclusively via MCP).
    """
    if tools is None:
        raise RuntimeError(
            "工具仅通过 MCP 提供。请使用 run_with_mcp_async（命令行）或 get_web_mcp_agent（Web UI）获取 Agent。"
        )
    return SecureAgent(model=model, base_url=base_url, tools=tools, **kwargs)
