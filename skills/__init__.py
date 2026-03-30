"""
Skills 子系统：技能加载、过滤与 Prompt 注入。

Skills subsystem: skill loading, filtering and prompt injection.

- SkillMetadata 数据模型 / SkillMetadata data model.
- load_skills_from_sources: 从 skills 源目录加载技能元数据 / Load skill metadata from source dirs.
- filter_skills_for_agent: 根据 target_agents 过滤不同 Agent 可见技能 / Filter visible skills per agent.
- build_skills_system_section: 构造注入到 system prompt 的 Skills System 文本 / Build Skills System section for the prompt.
"""

from .loader import (
    SkillMetadata,
    load_skills_from_sources,
    filter_skills_for_agent,
    build_skills_system_section,
)

__all__ = [
    "SkillMetadata",
    "load_skills_from_sources",
    "filter_skills_for_agent",
    "build_skills_system_section",
]

