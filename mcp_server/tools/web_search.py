"""
网页搜索工具模块（MCP Server 内统一实现）。
Web search tool module (unified implementation within MCP Server).

支持多个搜索引擎，具有自动故障转移功能，使用免费的爬虫库实现，无需付费 API。
Supports multiple search engines with automatic failover, implemented using free crawling libraries without paid APIs.
"""

import sys
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

# 当前在 mcp_server/tools/，项目根为 SecureAgent / Current dir is mcp_server/tools/, project root is SecureAgent
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_this_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from utils.logger import logger
    from config import config
except ImportError:
    # 如果导入失败，使用简单的日志 / If import fails, use simple logging
    import logging
    logger = logging.getLogger(__name__)
    
    # 使用默认配置 / Use default configuration
    from dataclasses import dataclass, field
    
    @dataclass
    class SearchConfigDefault:
        engine: str = "google"
        fallback_engines: List = field(default_factory=lambda: ["duckduckgo", "bing", "baidu"])
        num_results: int = 5
        retry_delay: int = 60
        max_retries: int = 3
    
    @dataclass
    class ConfigDefault:
        search: SearchConfigDefault = field(default_factory=SearchConfigDefault)
    
    config = ConfigDefault()


@dataclass
class SearchResult:
    """
    搜索结果数据类。
    Data class for a single search result.
    """
    title: str
    url: str
    description: str = ""
    position: int = 0
    source: str = ""
    
    def __str__(self) -> str:
        return f"{self.position}. {self.title}\n   URL: {self.url}\n   {self.description}"


class BaseSearchEngine(ABC):
    """
    搜索引擎基类。
    Abstract base class for search engines.
    """
    
    name: str = "base"
    
    @abstractmethod
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        执行搜索。
        Execute a search query.
        
        Args:
            query: 搜索查询 / Search query
            num_results: 返回结果数量 / Number of results to return
            
        Returns:
            搜索结果列表 / List of search results
        """
        pass


class GoogleSearchEngine(BaseSearchEngine):
    """
    Google 搜索引擎。
    Google search engine.
    
    使用 googlesearch-python 库，无需 API Key，通过模拟浏览器请求爬取 Google 搜索结果。
    Uses the googlesearch-python library without an API key by simulating browser requests to scrape Google results.

    注意：Google 可能会因频繁请求而阻止 IP 或显示验证码。
    Note: Google may block IPs or show CAPTCHAs due to frequent requests.
    """
    
    name = "google"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        执行 Google 搜索。
        Execute a Google search.
        """
        try:
            from googlesearch import search
            
            results = []
            
            # advanced=True 返回生成器，需要转换为列表 / advanced=True returns a generator, needs conversion to list
            # 添加 sleep 参数避免被 Google 阻止 / Add sleep parameter to avoid being blocked by Google
            try:
                raw_results = list(search(
                    query, 
                    num_results=num_results, 
                    advanced=True,
                    sleep_interval=1
                ))
            except TypeError:
                # 某些版本可能不支持 sleep_interval 参数 / Some versions may not support the sleep_interval parameter
                raw_results = list(search(query, num_results=num_results, advanced=True))
            
            for i, item in enumerate(raw_results):
                if isinstance(item, str):
                    # 如果只返回 URL / If only a URL is returned
                    results.append(SearchResult(
                        title=f"Google Result {i+1}",
                        url=item,
                        description="",
                        position=i+1,
                        source=self.name
                    ))
                else:
                    # 返回完整结果对象 / Full result object returned
                    results.append(SearchResult(
                        title=getattr(item, 'title', f"Google Result {i+1}") or f"Google Result {i+1}",
                        url=getattr(item, 'url', '') or '',
                        description=getattr(item, 'description', '') or '',
                        position=i+1,
                        source=self.name
                    ))
            
            logger.info(f"Google搜索完成，获取 {len(results)} 条结果")
            return results
            
        except ImportError:
            logger.error("googlesearch-python 未安装，请运行: pip install googlesearch-python")
            return []
        except Exception as e:
            # 常见错误：被 Google 阻止、网络问题、验证码等 / Common errors: blocked by Google, network issues, CAPTCHAs, etc.
            logger.warning(f"Google搜索失败（可能被阻止或需要验证码）: {e}")
            return []


class DuckDuckGoSearchEngine(BaseSearchEngine):
    """
    DuckDuckGo 搜索引擎。
    DuckDuckGo search engine.
    
    使用 ddgs 库（原 duckduckgo-search），完全免费，DuckDuckGo 本身是隐私友好的搜索引擎。
    Uses the ddgs library (formerly duckduckgo-search), completely free. DuckDuckGo is a privacy-friendly search engine.
    """
    
    name = "duckduckgo"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        执行 DuckDuckGo 搜索。
        Execute a DuckDuckGo search.
        """
        try:
            # 尝试新包名 ddgs / Try the new package name ddgs
            try:
                from ddgs import DDGS
                logger.info("使用 ddgs 包进行搜索")
            except ImportError:
                # 回退到旧包名 / Fall back to the old package name
                from duckduckgo_search import DDGS
                logger.info("使用 duckduckgo_search 包进行搜索")
            
            results = []
            
            # 使用 with 语句确保正确关闭 / Use with-statement to ensure proper cleanup
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=num_results))
            
            logger.info(f"DuckDuckGo原始结果数量: {len(raw_results)}")
            
            for i, item in enumerate(raw_results):
                if isinstance(item, dict):
                    results.append(SearchResult(
                        title=item.get('title', f"DuckDuckGo Result {i+1}"),
                        url=item.get('href', ''),
                        description=item.get('body', ''),
                        position=i+1,
                        source=self.name
                    ))
                else:
                    results.append(SearchResult(
                        title=f"DuckDuckGo Result {i+1}",
                        url=str(item),
                        description="",
                        position=i+1,
                        source=self.name
                    ))
            
            logger.info(f"DuckDuckGo搜索完成，获取 {len(results)} 条结果")
            return results
            
        except ImportError as e:
            logger.error(f"ddgs 未安装: {e}，请运行: pip install ddgs")
            return []
        except Exception as e:
            import traceback
            logger.warning(f"DuckDuckGo搜索失败: {e}")
            logger.debug(traceback.format_exc())
            return []


class BingSearchEngine(BaseSearchEngine):
    """
    Bing 搜索引擎。
    Bing search engine.
    
    通过爬虫直接获取 Bing 搜索结果，无需 API。
    Scrapes Bing search results directly without an API.
    """
    
    name = "bing"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        执行 Bing 搜索。
        Execute a Bing search.
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            
            url = f"https://www.bing.com/search?q={query}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            
            # 解析 Bing 搜索结果 / Parse Bing search results
            ol_results = soup.find("ol", id="b_results")
            if ol_results:
                for i, li in enumerate(ol_results.find_all("li", class_="b_algo")):
                    if i >= num_results:
                        break
                    
                    title = ""
                    url = ""
                    description = ""
                    
                    h2 = li.find("h2")
                    if h2:
                        a = h2.find("a")
                        if a:
                            title = a.get_text(strip=True)
                            url = a.get("href", "")
                    
                    p = li.find("p")
                    if p:
                        description = p.get_text(strip=True)[:300]
                    
                    if url:
                        results.append(SearchResult(
                            title=title or f"Bing Result {i+1}",
                            url=url,
                            description=description,
                            position=i+1,
                            source=self.name
                        ))
            
            logger.info(f"Bing搜索完成，获取 {len(results)} 条结果")
            return results
            
        except ImportError:
            logger.error("requests 或 beautifulsoup4 未安装")
            return []
        except Exception as e:
            logger.warning(f"Bing搜索失败: {e}")
            return []


class BaiduSearchEngine(BaseSearchEngine):
    """
    百度搜索引擎。
    Baidu search engine.
    
    使用 baidusearch 库获取结果。
    Uses the baidusearch library to fetch results.
    """
    
    name = "baidu"
    
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        执行百度搜索。
        Execute a Baidu search.
        """
        try:
            from baidusearch.baidusearch import search
            
            results = []
            raw_results = search(query, num_results=num_results)
            
            for i, item in enumerate(raw_results):
                if isinstance(item, dict):
                    results.append(SearchResult(
                        title=item.get('title', f"Baidu Result {i+1}"),
                        url=item.get('url', ''),
                        description=item.get('abstract', ''),
                        position=i+1,
                        source=self.name
                    ))
                else:
                    results.append(SearchResult(
                        title=f"Baidu Result {i+1}",
                        url=str(item),
                        description="",
                        position=i+1,
                        source=self.name
                    ))
            
            logger.info(f"百度搜索完成，获取 {len(results)} 条结果")
            return results
            
        except ImportError:
            logger.error("baidusearch 未安装，请运行: pip install baidusearch")
            return []
        except Exception as e:
            logger.warning(f"百度搜索失败: {e}")
            return []


class WebSearchTool:
    """
    网页搜索工具。
    Web search tool.
    
    支持多个搜索引擎，具有自动故障转移功能：首选引擎失败后自动尝试备用引擎。
    Supports multiple search engines with automatic failover: falls back to alternate engines when the preferred one fails.
    """
    
    def __init__(self):
        """
        初始化搜索工具，注册所有可用引擎。
        Initialize the search tool and register all available engines.
        """
        self.engines: Dict[str, BaseSearchEngine] = {
            "google": GoogleSearchEngine(),
            "duckduckgo": DuckDuckGoSearchEngine(),
            "bing": BingSearchEngine(),
            "baidu": BaiduSearchEngine(),
        }
    
    def _get_engine_order(self) -> List[str]:
        """
        获取搜索引擎尝试顺序。
        Get the order in which search engines should be tried.
        """
        search_config = config.search
        
        # 首选引擎 / Preferred engine
        preferred = search_config.engine.lower()
        
        # 备用引擎 / Fallback engines
        fallbacks = [e.lower() for e in search_config.fallback_engines]
        
        # 构建完整顺序 / Build the full order
        order = []
        if preferred in self.engines:
            order.append(preferred)
        
        for fb in fallbacks:
            if fb in self.engines and fb not in order:
                order.append(fb)
        
        # 添加剩余引擎 / Append remaining engines
        for engine_name in self.engines:
            if engine_name not in order:
                order.append(engine_name)
        
        return order
    
    def _fetch_webpage_content(
        self, 
        url: str, 
        max_length: int = 5000,
        timeout: int = 10
    ) -> Optional[str]:
        """
        抓取单个网页内容（复用 WebCrawler）。
        Fetch content from a single webpage (reuses WebCrawler).
        
        Args:
            url: 网页 URL / Webpage URL
            max_length: 最大内容长度 / Maximum content length
            timeout: 超时时间（秒），超时后自动跳过 / Timeout in seconds; auto-skip on timeout
        """
        try:
            from .web_crawler import WebCrawler
            crawler = WebCrawler()
            result = crawler.fetch(url, mode="simple", max_length=max_length, timeout=timeout)
            
            if result.success and result.content:
                return result.content
            elif result.error:
                logger.warning(f"跳过网页 {url[:50]}... ({result.error})")
            return None
            
        except Exception as e:
            logger.warning(f"跳过网页 {url[:50]}... ({e})")
            return None
    
    def search(
        self, 
        query: str, 
        num_results: int = 5,
        fetch_content: bool = False,
        content_max_length: int = 3000,
        fetch_timeout: int = 8
    ) -> str:
        """
        执行网页搜索。
        Execute a web search.
        
        Args:
            query: 搜索查询 / Search query
            num_results: 返回结果数量 / Number of results to return
            fetch_content: 是否抓取搜索结果的网页内容 / Whether to fetch webpage content from search results
            content_max_length: 每个网页内容的最大长度 / Maximum content length per webpage
            fetch_timeout: 单个网页抓取超时时间（秒），超时自动跳过 / Per-page fetch timeout in seconds; auto-skip on timeout
            
        Returns:
            格式化的搜索结果字符串 / Formatted search results string
        """
        if not num_results:
            num_results = config.search.num_results
            
        engine_order = self._get_engine_order()
        search_config = config.search
        
        # 尝试所有引擎 / Try all engines
        for retry in range(search_config.max_retries + 1):
            for engine_name in engine_order:
                engine = self.engines[engine_name]
                logger.info(f"正在使用 {engine_name.capitalize()} 搜索: {query}")
                
                results = engine.search(query, num_results)
                
                if results:
                    # 如果需要抓取内容 / Fetch content if requested
                    if fetch_content:
                        logger.info(f"正在抓取 {len(results)} 个网页的内容 (超时: {fetch_timeout}秒)...")
                        success_count = 0
                        skip_count = 0
                        
                        for i, result in enumerate(results, 1):
                            logger.info(f"   [{i}/{len(results)}] 抓取: {result.title[:40]}...")
                            content = self._fetch_webpage_content(
                                result.url, 
                                content_max_length, 
                                timeout=fetch_timeout
                            )
                            if content:
                                result.description = f"{result.description}\n\n[网页内容摘要]: {content}"
                                success_count += 1
                                logger.info(f"   成功")
                            else:
                                skip_count += 1
                                logger.info(f"   已跳过")
                        
                        logger.info(f"抓取完成: {success_count} 成功, {skip_count} 跳过")
                    
                    # 格式化输出 / Format output
                    output = [f"搜索结果 (来源: {engine_name.capitalize()}):\n"]
                    for result in results:
                        output.append(str(result))
                        output.append("")
                    
                    return "\n".join(output)
            
            # 所有引擎都失败，等待重试 / All engines failed, wait and retry
            if retry < search_config.max_retries:
                logger.warning(f"所有搜索引擎失败，{search_config.retry_delay}秒后重试 ({retry+1}/{search_config.max_retries})...")
                import time
                time.sleep(search_config.retry_delay)
        
        # 最终失败 / Final failure
        logger.error("所有搜索引擎在多次重试后仍然失败")
        return "搜索失败：所有搜索引擎都无法获取结果，请稍后重试。"


# 创建全局搜索工具实例 / Create global search tool instance
_search_tool_instance = WebSearchTool()

# 交互模式全局开关 / Global toggle for interactive mode
_interactive_mode = False


def set_interactive_mode(enabled: bool):
    """
    设置是否启用交互式搜索模式。
    Set whether interactive search mode is enabled.
    """
    global _interactive_mode
    if _interactive_mode == enabled:
        return
    _interactive_mode = enabled
    logger.info(f"交互式搜索模式: {'已启用' if enabled else '已禁用'}")


def get_interactive_mode() -> bool:
    """
    获取当前交互模式状态。
    Get the current interactive mode status.
    """
    return _interactive_mode


def _ask_user_search_choice(query: str) -> str:
    """
    询问用户选择搜索方式。
    Ask the user to choose a search method.
    
    Returns:
        选择的搜索方式 / The chosen search method: "http", "browser", "browser_visible"
    """
    print("\n" + "=" * 50)
    print(f"🔍 即将搜索: {query}")
    print("=" * 50)
    print("请选择搜索方式:")
    print("  [1] HTTP搜索 (DuckDuckGo等，快速)")
    print("  [2] 浏览器搜索 (Google，无头模式)")
    print("  [3] 浏览器搜索 (Google，可视化)")
    print("  [0] 使用默认 (HTTP搜索)")
    print("-" * 50)
    
    try:
        choice = input("请输入选项 (0-3): ").strip()
        
        if choice == "1" or choice == "0" or choice == "":
            print("✓ 使用 HTTP 搜索")
            return "http"
        elif choice == "2":
            print("✓ 使用浏览器搜索 (无头模式)")
            return "browser"
        elif choice == "3":
            print("✓ 使用浏览器搜索 (可视化)")
            return "browser_visible"
        else:
            print("⚠ 无效选项，使用默认 HTTP 搜索")
            return "http"
    except (EOFError, KeyboardInterrupt):
        print("\n⚠ 输入中断，使用默认 HTTP 搜索")
        return "http"


def _do_browser_search(query: str, num_results: int, visible: bool = False) -> str:
    """
    执行浏览器搜索。
    Execute a browser-based search.
    """
    try:
        from .browser_search import BrowserSearchTool, PLAYWRIGHT_AVAILABLE
        
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright未安装，回退到HTTP搜索")
            return _search_tool_instance.search(query, num_results)
        
        tool = BrowserSearchTool(headless=not visible, slow_mo=100 if visible else 0)
        return tool.search(query, num_results)
        
    except ImportError as e:
        logger.warning(f"浏览器搜索不可用: {e}，回退到HTTP搜索")
        return _search_tool_instance.search(query, num_results)


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """
    Quick web search - returns only titles, URLs and brief descriptions.
    
    Use this for: simple factual queries, finding specific websites, getting a list of sources.
    
    For research/summarization tasks that need actual webpage content, use web_search_with_content instead.
    
    Args:
        query: The search query to look up on the web.
        num_results: Number of search results to return (default: 5).
        
    Returns:
        List of search results with titles, URLs, and descriptions (no full content).
    """
    global _interactive_mode
    
    if _interactive_mode:
        # 交互模式：询问用户选择搜索方式 / Interactive mode: ask user to choose search method
        choice = _ask_user_search_choice(query)
        
        if choice == "http":
            return _search_tool_instance.search(query, num_results)
        elif choice == "browser":
            return _do_browser_search(query, num_results, visible=False)
        elif choice == "browser_visible":
            return _do_browser_search(query, num_results, visible=True)
    
    # 非交互模式：直接使用 HTTP 搜索 / Non-interactive mode: use HTTP search directly
    return _search_tool_instance.search(query, num_results)


@tool
def web_search_with_content(query: str, num_results: int = 3, timeout: int = 8) -> str:
    """
    Deep web search - searches AND fetches full content from top results.
    
    RECOMMENDED FOR: research, summarization, comparing information, answering complex questions,
    any task requiring actual webpage content rather than just titles/descriptions.
    
    This tool automatically:
    1. Searches using multiple search engines
    2. Fetches the actual content from each result webpage (slow pages are auto-skipped)
    3. Returns both search metadata AND extracted webpage text
    
    Args:
        query: The search query to look up on the web.
        num_results: Number of webpages to fetch content from (default: 3).
        timeout: Max seconds to wait for each webpage (default: 8). Slow pages are skipped.
        
    Returns:
        Search results with full webpage content extracted and ready for analysis.
    """
    logger.info(f"搜索并抓取内容: {query}")
    return _search_tool_instance.search(
        query, 
        num_results, 
        fetch_content=True, 
        content_max_length=4000,
        fetch_timeout=timeout
    )


def get_search_tool():
    """
    获取搜索工具（LangChain Tool 格式）。
    Get the search tool (in LangChain Tool format).
    """
    return web_search


# 用于测试 / For testing
if __name__ == "__main__":
    print("测试搜索功能...")
    
    # 测试搜索 / Test search
    result = web_search.invoke({"query": "Python programming language", "num_results": 3})
    print(result)
