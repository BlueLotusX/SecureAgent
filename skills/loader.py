"""
技能加载器：解析 SKILL.md 元数据、校验并构造 Skills System prompt 段落。

Skill loader: parses SKILL.md metadata, validates fields, and builds the
Skills System section that is injected into the Decision Agent's prompt.
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from utils.logger import logger


MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024  # 10 MB 文件大小上限 / 10 MB file size limit
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
MAX_SKILL_COMPATIBILITY_LENGTH = 500


@dataclass
class SkillMetadata:
    """
    Skill 元数据模型，与 Agent Skills 规范保持兼容。

    Metadata model for a Skill, compatible with the Agent Skills
    specification (path, name, description, license, compatibility,
    metadata, allowed_tools).
    """

    path: str
    name: str
    description: str
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)


def _read_frontmatter(text: str) -> Dict[str, Any]:
    """读取 SKILL.md 顶部的 YAML frontmatter（轻量级解析实现）。

    Read YAML frontmatter from the top of SKILL.md using a lightweight
    parser that supports simple key/value pairs and one-level metadata /
    allowed-tools sections, without introducing a full YAML dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    front_lines: List[str] = []
    # 从第二行开始，直到遇到下一个 '---' 为止 / Collect lines between the two '---' fences
    for line in lines[1:]:
        if line.strip() == "---":
            break
        front_lines.append(line.rstrip("\n"))

    result: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for raw in front_lines:
        if not raw.strip():
            continue
        # 简单支持 metadata 下的一层缩进键值 / Handle one-level indented key-value pairs under metadata
        if raw.startswith("  ") or raw.startswith("\t"):
            if current_section == "metadata":
                # 形如 "  key: value" / e.g. "  key: value"
                kv = raw.strip()
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    result.setdefault("metadata", {})
                    result["metadata"][k.strip()] = v.strip().strip('"').strip("'")
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        # 记录当前顶层 section，便于处理后续缩进行 / Track current top-level section for indented lines
        current_section = key if key in ("metadata",) else None
        if not value:
            # 例如 "metadata:"，后续缩进行再处理 / e.g. bare "metadata:" — children handled later
            if key == "metadata":
                result.setdefault("metadata", {})
            continue
        # 其他简单键值对：去掉包裹的引号 / Other simple key-value: strip surrounding quotes
        cleaned = value.strip().strip('"').strip("'")
        result[key] = cleaned

    return result


def _validate_and_normalize(meta: Dict[str, Any], path: str) -> Optional[SkillMetadata]:
    """根据约束对 SkillMetadata 进行校验与规范化。

    Validate and normalize SkillMetadata fields (name length, description,
    compatibility, metadata dict, allowed-tools list).
    """
    name = str(meta.get("name", "")).strip()
    if not name:
        logger.warning("[Skills] 跳过 %s：缺少 name 字段", path)
        return None
    if len(name) > MAX_SKILL_NAME_LENGTH:
        logger.warning("[Skills] 技能 %s 的 name 过长，将被截断", name)
        name = name[:MAX_SKILL_NAME_LENGTH]

    description = str(meta.get("description", "")).strip()
    if not description:
        logger.warning("[Skills] 技能 %s 缺少 description，将被忽略", name)
        return None
    if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        logger.warning("[Skills] 技能 %s 的 description 过长，将被截断", name)
        description = description[:MAX_SKILL_DESCRIPTION_LENGTH]

    license_val = meta.get("license")
    if license_val is not None:
        license_val = str(license_val).strip()

    compatibility_val = meta.get("compatibility")
    if compatibility_val is not None:
        compatibility_val = str(compatibility_val).strip()
        if len(compatibility_val) > MAX_SKILL_COMPATIBILITY_LENGTH:
            logger.warning("[Skills] 技能 %s 的 compatibility 过长，将被截断", name)
            compatibility_val = compatibility_val[:MAX_SKILL_COMPATIBILITY_LENGTH]

    raw_metadata = meta.get("metadata") or {}
    metadata: Dict[str, str] = {}
    # 规范要求 metadata 为 dict[str, str]，但也兼容 JSON 字符串写法 /
    # Spec requires dict[str, str]; also handle JSON-encoded string form.
    if isinstance(raw_metadata, str):
        s = raw_metadata.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    raw_metadata = parsed
            except Exception:
                # 解析失败则保持原样 / On parse failure keep as-is
                pass
    if isinstance(raw_metadata, dict):
        # 将所有 key/value 转为字符串 / Stringify all key/value pairs
        for k, v in raw_metadata.items():
            metadata[str(k)] = str(v)
    else:
        if raw_metadata not in ({}, None, ""):
            logger.warning("[Skills] 技能 %s 的 metadata 非 dict，将被忽略", name)

    # allowed-tools：空格或逗号分隔的字符串 / allowed-tools: space or comma separated string
    allowed_raw = meta.get("allowed-tools") or meta.get("allowed_tools") or ""
    allowed_tools: List[str] = []
    if isinstance(allowed_raw, str):
        # 兼容逗号与空格 / Support both comma and space as delimiters
        tmp = allowed_raw.replace(",", " ")
        allowed_tools = [t for t in (p.strip() for p in tmp.split()) if t]
    elif isinstance(allowed_raw, list):
        allowed_tools = [str(t).strip() for t in allowed_raw if str(t).strip()]
    else:
        if allowed_raw:
            logger.warning("[Skills] 技能 %s 的 allowed-tools 非字符串/列表，将被忽略", name)

    return SkillMetadata(
        path=path,
        name=name,
        description=description,
        license=license_val or None,
        compatibility=compatibility_val or None,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )


def load_skills_from_sources(sources: List[str], workspace_root: str) -> Dict[str, SkillMetadata]:
    """
    从一组 skill 源目录加载所有技能，返回 {name: SkillMetadata}。

    Load all skills from a list of source directories and return
    {name: SkillMetadata}.

    - sources: 形如 ["/skills/", "/skills/project/"] 的虚拟路径，
      相对于 workspace_root 解析为真实文件系统路径。
      Virtual paths resolved relative to *workspace_root*.
    - 多个源中同名技能按顺序覆盖：后出现的源优先。
      Duplicate names are overridden by later sources.
    """
    skills_index: Dict[str, SkillMetadata] = {}
    if not sources:
        return skills_index

    for source in sources:
        if not source:
            continue
        # 规范化虚拟路径：保留前导 "/" / Normalize virtual path: keep leading "/"
        virtual_root = source if source.startswith("/") else "/" + source
        virtual_root = virtual_root.rstrip("/") + "/"

        real_root = os.path.join(workspace_root, virtual_root.lstrip("/"))
        if not os.path.isdir(real_root):
            logger.info("[Skills] 技能源目录不存在，跳过: %s (real=%s)", virtual_root, real_root)
            continue

        logger.info("[Skills] 扫描技能源目录: %s (real=%s)", virtual_root, real_root)
        for entry in os.listdir(real_root):
            skill_dir = os.path.join(real_root, entry)
            if not os.path.isdir(skill_dir):
                continue
            skill_md = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue

            # 文件大小限制 / Enforce file size limit
            try:
                size = os.path.getsize(skill_md)
            except OSError:
                logger.warning("[Skills] 无法获取文件大小，跳过: %s", skill_md)
                continue
            if size > MAX_SKILL_FILE_SIZE:
                logger.warning("[Skills] SKILL.md 过大（>10MB），跳过: %s", skill_md)
                continue

            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                logger.warning("[Skills] 读取 SKILL.md 失败: %s (%s)", skill_md, e)
                continue

            front = _read_frontmatter(text)
            if not front:
                logger.warning("[Skills] SKILL.md 缺少有效 frontmatter，跳过: %s", skill_md)
                continue

            # 构造虚拟路径 / Build virtual path: /skills/<dir-name>/SKILL.md
            virtual_path = os.path.join(virtual_root, entry, "SKILL.md").replace(os.sep, "/")
            meta = _validate_and_normalize(front, virtual_path)
            if not meta:
                continue

            # 多源覆盖：后出现的源覆盖同名 skill / Later source overrides earlier one
            if meta.name in skills_index:
                logger.info(
                    "[Skills] 技能 %s 已存在，将被新来源覆盖 (old=%s, new=%s)",
                    meta.name,
                    skills_index[meta.name].path,
                    meta.path,
                )
            skills_index[meta.name] = meta

    logger.info("[Skills] 加载完毕，共 %d 个技能", len(skills_index))
    return skills_index


def filter_skills_for_agent(skills_index: Dict[str, SkillMetadata], agent_name: str) -> List[SkillMetadata]:
    """
    根据 target_agents 字段筛选当前 Agent 可见的技能。

    Filter skills visible to the given agent based on the target_agents
    field in SkillMetadata.metadata.

    - 若未设置 target_agents，则对所有 Agent 可见。
      If target_agents is unset, the skill is visible to every agent.
    - target_agents 可为逗号/空格分隔的字符串，或列表。
      target_agents may be a comma/space-separated string or a list.
    """
    if not skills_index:
        return []
    agent_name = (agent_name or "").strip().lower()
    visible: List[SkillMetadata] = []
    for meta in skills_index.values():
        targets = meta.metadata.get("target_agents") or meta.metadata.get("target-agent") or ""
        if not targets:
            visible.append(meta)
            continue
        names: List[str] = []
        if isinstance(targets, str):
            tmp = targets.replace(",", " ")
            names = [t for t in (p.strip().lower() for p in tmp.split()) if t]
        elif isinstance(targets, list):
            names = [str(t).strip().lower() for t in targets if str(t).strip()]
        else:
            # 非预期类型，忽略 target 限制 / Unexpected type — ignore target constraint
            visible.append(meta)
            continue
        if not names or agent_name in names:
            visible.append(meta)
    return visible


def build_skills_system_section(
    skills: List[SkillMetadata],
    sources: List[str],
    language: str = "zh",
) -> str:
    """
    动态构造 Skills System 数据段落（Markdown），注入 Decision Agent 的 system prompt。

    Dynamically build the Skills System section (Markdown) for injection
    into the Decision Agent's system prompt.

    生成内容 / Generated content:
      1. 可用技能列表（动态数据）/ Available skills list (dynamic data).
      2. Skill-driven tool usage 说明 / Skill-driven tool usage instructions.

    行为级优先规则由 prompts.py 的 SKILLS_PRIORITY_SECTION 提供。
    Behavioural priority rules come from SKILLS_PRIORITY_SECTION in prompts.py.
    """
    if not skills:
        return ""

    zh = language.lower().startswith("zh")

    # ── 1. 技能源位置 / Skill source locations ──
    locations_lines: List[str] = []
    for src in sources:
        if not src:
            continue
        normalized = src if src.startswith("/") else "/" + src
        normalized = normalized.rstrip("/") + "/"
        locations_lines.append(f"- `{normalized}`")
    locations_block = "\n".join(locations_lines) if locations_lines else ""

    # ── 2. 可用技能列表 / Available skills list ──
    skills_lines: List[str] = []
    for meta in sorted(skills, key=lambda m: m.name):
        skills_lines.append(f"- **{meta.name}** — {meta.description}")
        if meta.allowed_tools:
            skills_lines.append(f"  - Allowed tools: `" + "`, `".join(meta.allowed_tools) + "`")
        skills_lines.append(f"  - Full instructions: `{meta.path}`")
    skills_block = "\n".join(skills_lines)

    # ── 3. Skill-driven tool usage 说明 / Instructions for LLM on invoking tools via skills ──
    command_execution = (
        "## Skill‑driven tool usage\n\n"
        "Skills may describe workflows that involve specific tools such as web search,\n"
        "file access, or shell commands. When you decide to use a Skill, you MUST follow\n"
        "the tools and workflow it recommends.\n\n"
        "Examples:\n"
        "- If a Skill lists `web_search_with_content` or `web_search` in its allowed-tools,\n"
        "  you should construct an appropriate query based on the user's request and the\n"
        "  Skill's instructions, then call those tools.\n"
        "- If a Skill mentions shell commands together with `run_shell_command`, you may\n"
        "  execute those commands via `run_shell_command` (respecting any safety\n"
        "  constraints described in this environment).\n\n"
        "Always treat the Skill document as the primary source of HOW to perform the task,\n"
        "and translate its steps into concrete tool calls available in this environment.\n"
    )

    # ── 组装最终段落 / Assemble final section ──
    parts: List[str] = []
    parts.append("## Skills System\n")
    if locations_block:
        parts.append("**Skill locations:**\n" + locations_block + "\n")
    parts.append("**Available skills:**\n" + skills_block + "\n")
    parts.append(command_execution)
    return "\n".join(parts)

