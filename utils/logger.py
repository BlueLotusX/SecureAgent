"""日志管理模块：提供带颜色和图标的统一 logger。

Logging utilities: provides a unified logger with colored output and icons.
"""

import logging
import sys
from datetime import datetime
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器 / Log formatter with ANSI colors and icons."""
    
    # 颜色代码 / ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
        'RESET': '\033[0m'       # 重置
    }
    
    # Emoji 图标 / Emoji icons for log levels
    ICONS = {
        'DEBUG': '🔍',
        'INFO': '✨',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '💥'
    }
    
    def format(self, record):
        """格式化日志记录 / Format log record with color and icon."""
        # 添加颜色和图标 / Attach color and icon prefix
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        icon = self.ICONS.get(record.levelname, '')
        reset = self.COLORS['RESET']
        
        # 格式化时间 / Format timestamp
        record.asctime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建格式化消息 / Build final log message
        log_message = f"{color}{icon} [{record.asctime}] [{record.levelname}] {record.getMessage()}{reset}"
        
        return log_message


def setup_logger(
    name: str = "SecureAgent",
    level: int = logging.INFO,
    log_file: Optional[str] = None
) -> logging.Logger:
    """创建并配置日志记录器 / Create and configure a logger.

    Args:
        name: 日志记录器名称 / Logger name.
        level: 日志级别 / Log level.
        log_file: 日志文件路径（可选）/ Optional log file path.

    Returns:
        配置好的日志记录器 / Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # 避免重复：不向 root 传播，只使用本 logger 的 handler / Do not propagate to root.

    # 清除现有处理器 / Clear existing handlers
    logger.handlers.clear()
    
    # 控制台处理器（仅消息+时间，不含文件名行号）/
    # Console handler: show time and message only, no filename/lineno.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)
    
    # 文件处理器（如果指定）/ Optional file handler.
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


# 创建默认日志记录器 / Create default logger instance.
logger = setup_logger()

# 屏蔽第三方库的部分 INFO 日志，避免刷屏 /
# Suppress noisy INFO logs from third-party libraries.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("faiss").setLevel(logging.WARNING)
logging.getLogger("faiss.loader").setLevel(logging.WARNING)
logging.getLogger("langchain_community.vectorstores.faiss").setLevel(logging.WARNING)
