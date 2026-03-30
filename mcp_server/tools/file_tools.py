"""
文件和通用工具（MCP Server 使用）。
File and general-purpose tools (used by MCP Server).

所有文件操作均限制在允许的根目录下。
All file operations are restricted to allowed root directories.
"""

import os
import sys
from datetime import datetime
from typing import Optional

# 确保 MCP Server 运行时 SecureAgent 根目录在路径中 / Ensure SecureAgent root is on path when MCP server runs
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from config import config
except ImportError:
    config = None

ENCODING = "utf-8"


def _get_allowed_root() -> str:
    if config is None:
        return os.path.realpath(os.getcwd())
    allowed = getattr(config.mcp, "allowed_file_root", None) or getattr(
        config.agent, "workspace_root", os.getcwd()
    )
    return os.path.realpath(os.path.abspath(allowed))


def _get_allowed_roots() -> list:
    """
    返回允许访问的根目录列表（工作区 + 桌面）。
    Return the list of allowed root directories (workspace + desktop).
    """
    roots = [_get_allowed_root()]
    try:
        desktop = get_desktop_path()
        if desktop and os.path.isabs(desktop):
            desktop_real = os.path.realpath(desktop)
            if desktop_real not in roots:
                roots.append(desktop_real)
    except Exception:
        pass
    return roots


def _check_path(path: str) -> str:
    """
    解析并校验路径是否位于允许的根目录下，返回绝对路径。
    Resolve and verify that the path is under an allowed root directory; return the absolute path.

    说明 / Notes:
    - 默认情况下，传入绝对路径或相对路径，都会根据 _get_allowed_roots 做安全校验。
      By default, both absolute and relative paths are validated against _get_allowed_roots.
    - 为了兼容 Skills System 使用的「虚拟路径」写法（例如 `/skills/.../SKILL.md`），
      当检测到以单个 `/` 开头且不包含盘符的路径时，将其视为「相对于 workspace_root 的路径」。
      To support "virtual paths" used by the Skills System (e.g. `/skills/.../SKILL.md`),
      paths starting with `/` without a drive letter are treated as relative to workspace_root.
    """
    # 兼容类似 "/skills/xxx/SKILL.md" 的虚拟路径：视为相对于 workspace_root
    # Handle virtual paths like "/skills/xxx/SKILL.md": treat as relative to workspace_root
    drive, _ = os.path.splitdrive(path)
    if path.startswith("/") and not drive:
        base = _get_allowed_root()
        path = os.path.join(base, path.lstrip("/"))

    path_abs = os.path.realpath(os.path.abspath(path))
    for allowed in _get_allowed_roots():
        if path_abs == allowed or path_abs.startswith(allowed + os.sep):
            return path_abs
    raise PermissionError(
        f"Path must be under an allowed root (workspace or desktop). Got: {path_abs}"
    )


def read_file(path: str) -> str:
    """
    读取文本文件内容，路径必须在允许的根目录中。
    Read the contents of a text file; the path must be under an allowed root directory.
    """
    path_abs = _check_path(path)
    if not os.path.isfile(path_abs):
        return f"Error: Not a file or does not exist: {path}"
    try:
        with open(path_abs, "r", encoding=ENCODING) as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str, append: bool = False) -> str:
    """
    创建或覆盖/追加写入文本文件，路径必须在允许的根目录中。
    Create or overwrite/append to a text file; the path must be under an allowed root directory.
    """
    path_abs = _check_path(path)
    try:
        mode = "a" if append else "w"
        os.makedirs(os.path.dirname(path_abs) or ".", exist_ok=True)
        with open(path_abs, mode, encoding=ENCODING) as f:
            f.write(content)
        return f"Success: wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def list_directory(path: str) -> str:
    """
    列出目录下的文件和子目录，路径必须在允许的根目录中。
    List files and subdirectories under a directory; the path must be under an allowed root directory.
    """
    path_abs = _check_path(path)
    if not os.path.isdir(path_abs):
        return f"Error: Not a directory or does not exist: {path}"
    try:
        entries = sorted(os.listdir(path_abs))
        lines = []
        for name in entries:
            full = os.path.join(path_abs, name)
            kind = "[dir]" if os.path.isdir(full) else "[file]"
            lines.append(f"  {kind} {name}")
        return "Directory listing:\n" + "\n".join(lines) if lines else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {e}"


def get_desktop_path() -> str:
    """
    返回当前用户桌面的绝对路径。
    Return the absolute path to the current user's desktop.
    """
    if sys.platform == "win32":
        base = os.environ.get("USERPROFILE", "")
        return os.path.join(base, "Desktop")
    return os.path.expanduser("~/Desktop")


def get_current_datetime(timezone: Optional[str] = None) -> str:
    """
    返回当前日期时间的 ISO 字符串（使用本地时间）。
    Return the current date-time as an ISO string (using local time).
    """
    return datetime.now().isoformat()


def get_workspace_root() -> str:
    """
    返回允许文件操作的根目录。
    Return the root directory allowed for file operations.
    """
    return _get_allowed_root()
