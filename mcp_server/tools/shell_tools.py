"""
Shell 工具：受限的命令行执行（供 Skills System 使用）。
Shell tool: restricted command-line execution (used by the Skills System).

安全策略 / Security policies:
  - 命令白名单：仅允许预定义的安全命令前缀 / Command allowlist: only predefined safe command prefixes are permitted
  - 工作目录锁定：始终在 workspace_root 下执行 / Working directory lock: always executes under workspace_root
  - 超时限制：默认 10 秒 / Timeout limit: default 10 seconds
  - 输出大小限制：stdout/stderr 各截断至 50KB / Output size limit: stdout/stderr truncated to 50KB each
"""

import os
import sys
import subprocess
from typing import Dict, Any

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from config import config
except ImportError:
    config = None

COMMAND_ALLOWLIST = [
    "curl",
    "wget",
    "python",
    "python3",
    "node",
    "jq",
    "grep",
    "echo",
    "cat",
    "head",
    "tail",
    "wc",
    "sort",
    "uniq",
    "ping",
]

COMMAND_BLOCKLIST = [
    "rm", "rmdir", "del",
    "shutdown", "reboot",
    "mkfs", "format",
    "dd",
    "chmod", "chown", "chattr",
    "sudo", "su", "runas",
    "powershell", "cmd",
    "reg",
    "kill", "taskkill",
]

DEFAULT_TIMEOUT = 10
MAX_OUTPUT_BYTES = 50 * 1024  # 50KB


def _get_workspace_root() -> str:
    if config is None:
        return os.path.realpath(os.getcwd())
    allowed = getattr(config.mcp, "allowed_file_root", None) or getattr(
        config.agent, "workspace_root", os.getcwd()
    )
    return os.path.realpath(os.path.abspath(allowed))


def _extract_command_name(command: str) -> str:
    """
    从完整命令字符串中提取首个可执行文件名（去掉路径前缀）。
    Extract the first executable name from a full command string (strip path prefix).
    """
    first_token = command.strip().split()[0] if command.strip() else ""
    return os.path.basename(first_token).lower()


def _is_command_allowed(command: str) -> bool:
    cmd_name = _extract_command_name(command)
    if not cmd_name:
        return False
    for blocked in COMMAND_BLOCKLIST:
        if cmd_name == blocked or cmd_name.startswith(blocked + "."):
            return False
    for allowed in COMMAND_ALLOWLIST:
        if cmd_name == allowed or cmd_name.startswith(allowed + "."):
            return True
    return False


def _truncate(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + f"\n... [truncated, total {len(encoded)} bytes]"


def run_shell_command(command: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    在受限环境中执行 shell 命令并返回结果。
    Execute a shell command in a restricted environment and return the result.

    Returns:
        dict with keys: stdout, stderr, exit_code
    """
    if not command or not command.strip():
        return {"stdout": "", "stderr": "Error: empty command", "exit_code": -1}

    if not _is_command_allowed(command):
        cmd_name = _extract_command_name(command)
        allowed_str = ", ".join(COMMAND_ALLOWLIST)
        return {
            "stdout": "",
            "stderr": (
                f"Error: command '{cmd_name}' is not in the allowlist. "
                f"Allowed commands: {allowed_str}"
            ),
            "exit_code": -1,
        }

    cwd = _get_workspace_root()
    timeout = max(1, min(timeout, 30))

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        return {
            "stdout": _truncate(stdout),
            "stderr": _truncate(stderr),
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Error: command timed out after {timeout} seconds",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error executing command: {e}",
            "exit_code": -1,
        }
