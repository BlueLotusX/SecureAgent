"""
浏览器自动化搜索工具（MCP Server 内统一实现）。
Browser automation search tool (unified implementation within MCP Server).

使用 Playwright 进行真实浏览器自动化，可绕过 Google 反爬虫机制。
Uses Playwright for real browser automation, capable of bypassing Google anti-scraping mechanisms.
"""

import sys
import os
import random
import time
from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path
from langchain_core.tools import tool

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_this_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from utils.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("Playwright未安装，请运行: pip install playwright && playwright install chromium")

USER_DATA_DIR = Path(_project_root) / ".browser_data"


@dataclass
class BrowserSearchResult:
    """
    浏览器搜索结果。
    Data class for a browser search result.
    """
    title: str
    url: str
    description: str = ""
    position: int = 0


class BrowserSearchTool:
    """
    使用 Playwright 进行浏览器自动化搜索（反检测、持久化 cookies）。
    Browser automation search using Playwright (anti-detection, persistent cookies).
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    def __init__(self, headless: bool = True, slow_mo: int = 0, use_persistent: bool = True):
        self.headless = headless
        self.slow_mo = slow_mo
        self.use_persistent = use_persistent
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

    def _random_delay(self, min_ms: int = 500, max_ms: int = 1500):
        """
        随机延迟，模拟人类行为。
        Random delay to simulate human behavior.
        """
        time.sleep(random.randint(min_ms, max_ms) / 1000)

    def _init_browser(self):
        """
        初始化浏览器实例。
        Initialize the browser instance.
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright未安装 / Playwright is not installed")
        self.playwright = sync_playwright().start()
        user_agent = random.choice(self.USER_AGENTS)
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage", "--no-sandbox",
            "--disable-setuid-sandbox", "--disable-infobars",
            "--window-size=1920,1080", "--start-maximized",
        ]
        if self.use_persistent:
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=self.headless, slow_mo=self.slow_mo,
                viewport={"width": 1920, "height": 1080}, user_agent=user_agent,
                locale="zh-CN", timezone_id="Asia/Shanghai", args=browser_args,
                ignore_default_args=["--enable-automation"],
            )
            self.page = self.context.new_page()
        else:
            self.browser = self.playwright.chromium.launch(
                headless=self.headless, slow_mo=self.slow_mo, args=browser_args,
            )
            self.context = self.browser.new_context(
                viewport={"width": 1920, "height": 1080}, user_agent=user_agent,
                locale="zh-CN", timezone_id="Asia/Shanghai",
            )
            self.page = self.context.new_page()
        self._inject_stealth_scripts()
        logger.info("浏览器已启动 / Browser launched")

    def _inject_stealth_scripts(self):
        """
        注入反检测脚本，隐藏自动化特征。
        Inject stealth scripts to hide automation fingerprints.
        """
        stealth_js = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        window.chrome = { runtime: {} };
        """
        self.page.add_init_script(stealth_js)

    def _close_browser(self):
        """
        关闭浏览器及相关资源。
        Close the browser and related resources.
        """
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.warning(f"关闭浏览器时出错 / Error closing browser: {e}")

    def _handle_consent(self):
        """
        处理 Cookie 同意弹窗。
        Handle cookie consent dialogs.
        """
        for selector in ['button:has-text("Accept all")', 'button:has-text("全部接受")', '#L2AGLb']:
            try:
                button = self.page.locator(selector).first
                if button.is_visible(timeout=1000):
                    self._random_delay(300, 800)
                    button.click()
                    return True
            except Exception:
                continue
        return False

    def _check_captcha(self) -> bool:
        """
        检测页面是否出现验证码。
        Check if the page shows a CAPTCHA.
        """
        try:
            content = self.page.content().lower()
            return "unusual traffic" in content or "验证" in content or "reCAPTCHA" in content
        except Exception:
            return False

    def _wait_for_captcha_resolution(self, timeout: int = 60) -> bool:
        """
        等待用户手动完成验证码。
        Wait for the user to manually solve the CAPTCHA.
        """
        print("\n⚠️ 检测到验证码，请在浏览器中手动完成。等待最多", timeout, "秒...")
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(2)
            if not self._check_captcha():
                return True
        return False

    def search_google(self, query: str, num_results: int = 5, wait_time: int = 3000) -> List[BrowserSearchResult]:
        """
        使用浏览器自动化执行 Google 搜索。
        Perform a Google search via browser automation.
        """
        results = []
        try:
            self._init_browser()
            self.page.goto("https://www.google.com", wait_until="domcontentloaded")
            self._random_delay(1000, 2000)
            self._handle_consent()
            if self._check_captcha() and not self.headless:
                if not self._wait_for_captcha_resolution():
                    return results
            search_box = self.page.locator('textarea[name="q"], input[name="q"]').first
            search_box.click()
            self._random_delay(200, 500)
            # 逐字输入模拟人类行为 / Type character by character to simulate human behavior
            for char in query:
                search_box.type(char, delay=random.randint(50, 150))
            self._random_delay(300, 800)
            search_box.press("Enter")
            self.page.wait_for_timeout(wait_time)
            self._random_delay(500, 1000)
            if self._check_captcha() and not self.headless:
                if not self._wait_for_captcha_resolution():
                    return results
            self._handle_consent()
            # 解析搜索结果 / Parse search results
            for selector in ['div.g', 'div[data-hveid]']:
                for element in self.page.locator(selector).all()[: num_results * 2]:
                    try:
                        title_el = element.locator('h3').first
                        title = title_el.text_content() if title_el.count() > 0 else ""
                        link_el = element.locator('a').first
                        url = link_el.get_attribute('href') if link_el.count() > 0 else ""
                        desc_el = element.locator('div[data-sncf], div.VwiC3b, span.aCOpRe').first
                        description = desc_el.text_content() if desc_el.count() > 0 else ""
                        if title and url and url.startswith('http') and 'google.com' not in url:
                            results.append(BrowserSearchResult(
                                title=title.strip(), url=url,
                                description=(description.strip()[:300] if description else ""),
                                position=len(results) + 1,
                            ))
                            if len(results) >= num_results:
                                break
                    except Exception:
                        continue
                if results:
                    break
            logger.info(f"Google 浏览器搜索完成，获取 {len(results)} 条结果 / Google browser search done, got {len(results)} results")
        except Exception as e:
            logger.error(f"浏览器搜索出错 / Browser search error: {e}")
        finally:
            self._close_browser()
        return results

    def search(self, query: str, num_results: int = 5) -> str:
        """
        执行搜索并返回格式化的结果字符串。
        Execute a search and return a formatted result string.
        """
        results = self.search_google(query, num_results)
        if not results:
            return "浏览器搜索失败：无法从Google获取结果。建议使用可视化模式或检查网络。"
        output = ["搜索结果 (来源: Google浏览器搜索):\n"]
        for r in results:
            output.append(f"{r.position}. {r.title}\n   URL: {r.url}")
            if r.description:
                output.append(f"   {r.description}")
            output.append("")
        return "\n".join(output)


@tool
def google_browser_search(query: str, num_results: int = 5) -> str:
    """Search Google using a real browser (Playwright) in headless mode."""
    if not PLAYWRIGHT_AVAILABLE:
        return "错误: Playwright未安装。请运行: pip install playwright && playwright install chromium"
    return BrowserSearchTool(headless=True, use_persistent=True).search(query, num_results)


@tool
def google_browser_search_visible(query: str, num_results: int = 5) -> str:
    """Search Google using a visible browser window (can manually solve CAPTCHA)."""
    if not PLAYWRIGHT_AVAILABLE:
        return "错误: Playwright未安装。"
    return BrowserSearchTool(headless=False, slow_mo=50, use_persistent=True).search(query, num_results)


def get_browser_search_tools():
    """
    获取浏览器搜索工具列表。
    Get the list of browser search tools.
    """
    return [google_browser_search, google_browser_search_visible]
