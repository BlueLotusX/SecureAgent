"""
网页内容抓取工具模块（MCP Server 内统一实现）。
Web content crawling tool module (unified implementation within MCP Server).

提供两种方式获取网页内容：
Two modes for fetching webpage content:
1. 简单抓取：使用 requests + BeautifulSoup（轻量级，适合静态页面）
   Simple crawling: uses requests + BeautifulSoup (lightweight, for static pages)
2. 高级抓取：使用 crawl4ai（支持 JavaScript 渲染，适合动态页面）
   Advanced crawling: uses crawl4ai (supports JS rendering, for dynamic pages)
"""

import sys
import os
from typing import Optional, List, Union
from dataclasses import dataclass
from urllib.parse import urlparse
from langchain_core.tools import tool

# 当前在 mcp_server/tools/，项目根为 SecureAgent / Current dir is mcp_server/tools/, project root is SecureAgent
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_this_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    """
    网页抓取结果。
    Data class for a webpage crawl result.
    """
    url: str
    success: bool
    title: str = ""
    content: str = ""
    word_count: int = 0
    error: str = ""
    
    def __str__(self) -> str:
        if self.success:
            return f"📄 {self.title}\n🔗 {self.url}\n📊 {self.word_count} 字\n\n{self.content}"
        else:
            return f"❌ 抓取失败: {self.url}\n   错误: {self.error}"


class WebCrawler:
    """
    网页内容抓取器，提供简单和高级两种抓取模式。
    Web content crawler providing both simple and advanced crawling modes.
    """
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5,zh-CN;q=0.3",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
    
    def _is_valid_url(self, url: str) -> bool:
        """
        验证 URL 格式。
        Validate the URL format.
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ["http", "https"]
        except Exception:
            return False
    
    def _clean_text(self, text: str, max_length: int = 15000) -> str:
        """
        清理和截断文本。
        Clean up and truncate text.
        """
        text = " ".join(text.split())
        if len(text) > max_length:
            text = text[:max_length] + "...[内容已截断 / content truncated]"
        return text
    
    def fetch_simple(
        self, 
        url: str, 
        timeout: int = 15,
        max_length: int = 15000
    ) -> CrawlResult:
        """
        简单抓取模式（requests + BeautifulSoup）。
        Simple crawling mode (requests + BeautifulSoup).
        """
        if not self._is_valid_url(url):
            return CrawlResult(url=url, success=False, error="无效的URL格式 / Invalid URL format")
        try:
            import requests
            from bs4 import BeautifulSoup
            logger.info(f"正在抓取网页: {url}")
            response = requests.get(url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(response.text, "html.parser")
            title = ""
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            for tag in soup(["script", "style", "nav", "footer", "header",
                           "aside", "form", "button", "iframe", "noscript"]):
                tag.decompose()
            main_content = None
            content_selectors = [
                ("article", {}), ("main", {}), ("div", {"class": "content"}),
                ("div", {"class": "article"}), ("div", {"class": "post"}),
                ("div", {"id": "content"}), ("div", {"id": "article"}),
                ("div", {"class": "entry-content"}), ("div", {"class": "post-content"}),
            ]
            for tag, attrs in content_selectors:
                main_content = soup.find(tag, attrs) if attrs else soup.find(tag)
                if main_content:
                    break
            if not main_content:
                main_content = soup.find("body") or soup
            text = main_content.get_text(separator="\n", strip=True)
            text = self._clean_text(text, max_length)
            word_count = len(text)
            logger.info(f"抓取成功: {title[:50]}... ({word_count} 字)")
            return CrawlResult(url=url, success=True, title=title, content=text, word_count=word_count)
        except ImportError:
            return CrawlResult(url=url, success=False, error="缺少依赖 / Missing dependency: pip install requests beautifulsoup4")
        except requests.exceptions.Timeout:
            return CrawlResult(url=url, success=False, error=f"请求超时 / Request timed out ({timeout}s)")
        except requests.exceptions.RequestException as e:
            return CrawlResult(url=url, success=False, error=f"请求错误 / Request error: {str(e)}")
        except Exception as e:
            return CrawlResult(url=url, success=False, error=f"抓取错误 / Crawl error: {str(e)}")
    
    def fetch_advanced(self, url: str, timeout: int = 30, max_length: int = 15000) -> CrawlResult:
        """
        高级抓取模式（crawl4ai，支持 JavaScript 渲染）。
        Advanced crawling mode (crawl4ai, supports JavaScript rendering).
        """
        if not self._is_valid_url(url):
            return CrawlResult(url=url, success=False, error="无效的URL格式 / Invalid URL format")
        try:
            import asyncio
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
            logger.info(f"使用 Crawl4AI 抓取: {url}")
            async def crawl():
                browser_config = BrowserConfig(
                    headless=True, verbose=False, browser_type="chromium",
                    ignore_https_errors=True, java_script_enabled=True,
                )
                run_config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS, word_count_threshold=10,
                    process_iframes=False, remove_overlay_elements=True,
                    excluded_tags=["script", "style", "nav", "footer", "header"],
                    page_timeout=timeout * 1000, verbose=False, wait_until="domcontentloaded",
                )
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    return await crawler.arun(url=url, config=run_config)
            result = asyncio.run(crawl())
            if result.success:
                title = result.metadata.get("title", "") if result.metadata else ""
                content = result.markdown if hasattr(result, "markdown") and result.markdown else ""
                content = self._clean_text(content, max_length)
                word_count = len(content)
                logger.info(f"Crawl4AI 抓取成功: {title[:50]}... ({word_count} 字)")
                return CrawlResult(url=url, success=True, title=title, content=content, word_count=word_count)
            return CrawlResult(url=url, success=False, error=getattr(result, "error_message", "未知错误 / Unknown error"))
        except ImportError:
            return self.fetch_simple(url, timeout, max_length)
        except Exception as e:
            logger.warning(f"Crawl4AI 错误: {e}，回退简单模式 / Crawl4AI error, falling back to simple mode")
            return self.fetch_simple(url, timeout, max_length)
    
    def fetch(self, url: str, mode: str = "auto", timeout: int = 15, max_length: int = 15000) -> CrawlResult:
        """
        抓取网页内容。
        Fetch webpage content.

        Args:
            url: 目标网页 URL / Target webpage URL
            mode: 抓取模式 / Crawl mode: "simple" / "advanced" / "auto"
            timeout: 超时秒数 / Timeout in seconds
            max_length: 最大内容长度 / Maximum content length
        """
        if mode == "simple":
            return self.fetch_simple(url, timeout, max_length)
        if mode == "advanced":
            return self.fetch_advanced(url, timeout, max_length)
        result = self.fetch_simple(url, timeout, max_length)
        if not result.success or result.word_count < 100:
            advanced_result = self.fetch_advanced(url, timeout, max_length)
            if advanced_result.success and advanced_result.word_count > result.word_count:
                return advanced_result
        return result


_crawler = WebCrawler()


@tool
def fetch_webpage(url: str, max_length: int = 10000) -> str:
    """Fetch and extract the main text content from a webpage URL."""
    result = _crawler.fetch(url, mode="auto", max_length=max_length)
    if result.success:
        return f"📄 标题: {result.title}\n🔗 URL: {result.url}\n📊 内容长度: {result.word_count} 字符\n\n{'='*50}\n\n{result.content}"
    return f"❌ 无法获取网页内容\nURL: {url}\n错误: {result.error}"


@tool
def fetch_and_summarize_url(url: str) -> str:
    """Fetch a webpage and prepare its content for summarization."""
    result = _crawler.fetch(url, mode="auto", max_length=12000)
    if result.success:
        return (
            f"📄 网页标题: {result.title}\n🔗 URL: {result.url}\n\n"
            f"以下是网页的主要内容，请进行总结:\n\n{'='*50}\n\n{result.content}\n\n{'='*50}\n"
            "请根据以上内容提供一个简洁的中文总结。"
        )
    return f"❌ 无法获取网页内容进行总结\nURL: {url}\n错误: {result.error}"


def get_webpage_tools():
    """
    获取网页相关工具列表。
    Get the list of webpage-related tools.
    """
    return [fetch_webpage, fetch_and_summarize_url]
