# -*- coding: utf-8 -*-
"""
hkexnews_selenium.py — HKEXnews 批次下載(架構設計版)

═══════════════════════════════════════════════════════════════════
  重要:這個檔案的「邏輯架構」是完整的,但頁面元素的選擇器
  (CSS selector / XPath)是根據 HKEXnews 屬於 JSF(JavaServer Faces)
  應用程式的一般命名慣例推測的,還沒有對照過真實頁面校正。

  原本 hkexnews.py 猜測的 JSON API 端點已證實不存在 —— 這個網站是
  動態渲染的,沒有可以直接呼叫的公開介面,所以只能用瀏覽器自動化。

  你在本機第一次執行時,請先用「非無頭模式」(SELENIUM_HEADLESS=False)
  跑一次,肉眼看瀏覽器實際跑到哪一步卡住,再對照瀏覽器開發者工具
  (F12 → 檢查元素)把 SELECTORS 區塊裡對應的選擇器改成真實的。
  這是操作任何 JSF/動態網站都無法跳過的一步,不是這份程式碼寫得不好。
═══════════════════════════════════════════════════════════════════

為什麼要用 Selenium 而不是 requests:
  requests 只能拿到伺服器回傳的原始 HTML/JS,不會執行 JavaScript。
  HKEXnews 的搜尋結果是靠 JS 動態產生的,所以必須用真的瀏覽器引擎
  (Selenium 背後掛的是 Chrome/Chromium)把頁面「跑起來」再讀取結果。

架構總覽:
  HKEXBrowser         — 負責開瀏覽器、操作表單、翻頁、讀取結果列表
  DateWindowPlanner    — 負責把查詢區間切成合法的時間窗(見下方說明)
  BatchDownloader      — 串起「查誰、查多久、下載到哪」的整體流程
"""

import os
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Iterator

logger = logging.getLogger("hkexnews_selenium")
logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")


# ═══════════════════════════════════════════════════════════════════
# SELECTORS — 這個區塊全部需要在本機用瀏覽器 F12 校正
# ═══════════════════════════════════════════════════════════════════
class SELECTORS:
    """
    ✅ 已用三輪實際探測校正完成(inspect_page / inspect_dropdown / inspect_html)

    探測揭露的真實結構(跟一開始的猜測差很多):
      - 文件類型是「兩段式」下拉:先在 #tier1-select 選「Headline Category」,
        隱藏的 #rbAfter2006 才會顯示,那才是真正的分類選單。
      - 第三層(Annual Report)在 aria-haspopup 的 level-1 項目下,靠 hover 展開。
      - autocomplete 建議是 <table><tr>,不是 <li>。
      - 頁面底部有 Cookie 同意橫幅,會攔截點擊,必須先關掉。
    """
    URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

    # ── 輸入框(已確認)────────────────────────────────────
    STOCK_CODE_INPUT = "#searchStockCode"
    DATE_FROM_INPUT = "#searchDate-From"
    DATE_TO_INPUT = "#searchDate-To"
    TITLE_KEYWORD_INPUT = "#searchTitle"
    DATE_FORMAT = "%Y/%m/%d"

    # ── 按鈕(已確認)──────────────────────────────────────
    SEARCH_BUTTON = "a.filter__btn-applyFilters-js"
    CLEAR_ALL_BUTTON = "a.btn-clearall"

    # ── Cookie 同意橫幅(會擋住點擊,必須先處理)──────────
    COOKIE_ACCEPT_CANDIDATES = [
        "//button[contains(text(),'Accept')]",
        "//a[contains(text(),'Accept')]",
        "//button[contains(text(),'Decline')]",
    ]

    # ── autocomplete(已確認:table 結構)────────────────────
    AUTOCOMPLETE_LIST = "#autocomplete-list-0"
    AUTOCOMPLETE_ROW = "#autocomplete-list-0 table tbody tr"
    AUTOCOMPLETE_HAS_VALUE = "div.autocomplete-group__input-box.has-value"

    # ── 文件類型兩段式下拉(已確認)──────────────────────
    # 第一段:選「Headline Category」模式
    TIER1_SELECT = "#tier1-select"
    TIER1_FIELD = "#tier1-select a.combobox-field"
    TIER1_OPTION_HEADLINE_CATEGORY = "div.droplist-item[data-value='rbAfter2006']"

    # 第二段:選完上面後才會 display:block
    CATEGORY_GROUP = "#rbAfter2006"
    CATEGORY_FIELD = "#rbAfter2006 a.combobox-field"
    CATEGORY_LEVEL1_ITEM = "#rbAfter2006 li.droplist-item-level-1"

    # 目標分類與文件路徑改由 config.DOC_TYPES 統一管理(領域知識層),
    # 這裡不再寫死。CATEGORY_LEVEL1_ITEM 是路徑第一段的容器選擇器,
    # 第二段以後用可見文字比對展開,深度不限(見 set_document_type)。

    # ── 搜尋結果(仍待確認:要有結果才存在)──────────────
    RESULT_ROW = "table tbody tr"                        # ← 待確認
    RESULT_LINK = "a[href$='.pdf']"
    RESULT_STOCK_CODE_CELL = "td:nth-child(2)"           # ← 待確認
    RESULT_COMPANY_CELL = "td:nth-child(3)"              # ← 待確認
    RESULT_DATE_CELL = "td:nth-child(1)"                 # ← 待確認

    NEXT_PAGE_BUTTON = "a[aria-label='Next Page']"       # ← 待確認
    NEXT_PAGE_DISABLED_CLASS = "disabled"                # ← 待確認


# ═══════════════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════════════
@dataclass
class Filing:
    stock_code: str
    company: str
    title: str
    date: str
    url: str
    # 標記這筆資料是用哪個文件類型查到的,只影響檔名(避免不同類型撞檔名),
    # 不影響分析 —— pipeline.py 的增量處理帳本是用 PDF 內容雜湊當 key,
    # 跟檔名無關。
    doc_type: str = "annual_report"

    def clean_company(self) -> str:
        """
        清理公司名稱。實測發現雙櫃檯股票(如騰訊)會抓到跨行文字:
          'TENCENT-R (00700\n80700)'
        只取第一行、去掉括號內容,避免檔名變得又長又亂。
        """
        name = (self.company or "").split("\n")[0]
        name = re.sub(r"\(.*?\)?$", "", name).strip()
        return name or "UNKNOWN"

    def clean_code(self) -> str:
        """雙櫃檯會給多個代號,只取第一個。"""
        code = (self.stock_code or "").split("\n")[0].strip()
        return re.sub(r"\D", "", code) or "00000"

    def iso_date(self) -> str:
        """
        HKEXnews 顯示格式為 dd/mm/yyyy,轉成 YYYYMMDD 讓檔案能正確排序。
        轉換失敗就退回原始數字串,不讓程式中斷。
        """
        digits = re.sub(r"\D", "", self.date or "")
        if len(digits) >= 8:
            dd, mm, yyyy = digits[:2], digits[2:4], digits[4:8]
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
                return f"{yyyy}{mm}{dd}"
            return digits[:8]
        return digits or "00000000"

    def local_filename(self) -> str:
        """
        檔名裡加上文件類型標籤(除了年報)是刻意的:同一間公司同一天
        有可能同時刊發年報和通函,純用「代號+公司+日期」當檔名,
        後選中的那份會因為「檔案已存在」被誤判成已下載而跳過 ——
        這是會漏資料的靜默失敗。annual_report 的 tag 留空,
        不改變既有使用者 downloads/ 資料夾裡已經下載好的檔名。
        """
        try:
            import config as _C
            tag = _C.DOC_TYPES.get(self.doc_type, {}).get("filename_tag", "")
        except Exception:
            tag = "" if self.doc_type == "annual_report" else self.doc_type.upper()[:12]

        base = f"{self.clean_code()}_{self.clean_company()}"
        if tag:
            base = f"{base}_{tag}"
        safe = re.sub(r"[^\w\-]+", "_", base)[:50]
        return f"{safe}_{self.iso_date()}.pdf"


# ═══════════════════════════════════════════════════════════════════
# 日期區間規劃 — 這是純邏輯,不依賴網頁,可以先獨立測試、保證正確
# ═══════════════════════════════════════════════════════════════════
class DateWindowPlanner:
    """
    HKEXnews 的隱性規則(來自公開文件與第三方爬蟲專案交叉比對):
      - 不指定股票代號:查詢區間上限約 30 天
      - 指定股票代號:查詢區間上限約 366 天

    這個類別負責把使用者要的「總區間」切成合法的小區間,
    邏輯本身跟網站怎麼運作無關,可以獨立寫單元測試,不需要真的連網。
    """
    WINDOW_NO_STOCK = 30
    WINDOW_WITH_STOCK = 366

    @classmethod
    def plan(cls, from_date: str, to_date: str,
             has_stock_code: bool) -> Iterator[tuple]:
        """
        輸入 'YYYYMMDD' 格式的起訖日,yield 出一連串合法的 (start, end) 子區間。
        """
        window = cls.WINDOW_WITH_STOCK if has_stock_code else cls.WINDOW_NO_STOCK
        start = datetime.strptime(from_date, "%Y%m%d")
        end = datetime.strptime(to_date, "%Y%m%d")

        cur = start
        while cur <= end:
            chunk_end = min(cur + timedelta(days=window - 1), end)
            yield (cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"))
            cur = chunk_end + timedelta(days=1)


# ═══════════════════════════════════════════════════════════════════
# 瀏覽器操作層
# ═══════════════════════════════════════════════════════════════════
class HKEXBrowser:
    """
    包裝 Selenium 的操作細節。所有「等待元素出現」都刻意寫成
    explicit wait(WebDriverWait),而不是 time.sleep() 亂猜秒數 ——
    動態網站最常見的爬蟲bug就是等待時間沒抓對,時好時壞。
    """

    def __init__(self, headless: bool = True, timeout: int = 20):
        # 延遲 import,讓沒裝 selenium 的人仍可以 import 這個檔案的其他部分
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1400,1000")
        # 偽裝成一般瀏覽器 UA,降低被視為爬蟲阻擋的機率
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        self.driver = webdriver.Chrome(options=opts)
        self.wait = WebDriverWait(self.driver, timeout)
        self.timeout = timeout
        # 上一次 search_all_pages 回傳 0 筆的原因。空字串代表「真的查無結果」。
        # 「查無此類文件」和「選單沒設定成功」對使用者是完全不同的兩件事,
        # 都回傳空清單卻不說明是哪一種,等於把判斷責任丟回給人。
        self.last_error = ""

    def close(self):
        self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _wait_visible(self, css: str):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        return self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, css)))

    def _wait_clickable(self, css: str):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        return self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))

    def dismiss_cookie_banner(self):
        """
        關掉底部的 Cookie 同意橫幅。
        這個橫幅會蓋住頁面下半部並攔截點擊事件 —— 探測時「點了沒反應」
        有一部分就是它造成的。找不到就靜靜跳過,不影響流程。
        """
        from selenium.webdriver.common.by import By
        for xpath in SELECTORS.COOKIE_ACCEPT_CANDIDATES:
            try:
                els = [e for e in self.driver.find_elements(By.XPATH, xpath)
                       if e.is_displayed()]
                if els:
                    self._js_click(els[0])
                    logger.info("    已關閉 Cookie 橫幅")
                    time.sleep(1.0)
                    return
            except Exception:
                continue

    def open_search_page(self):
        self.driver.get(SELECTORS.URL)
        self._wait_visible(SELECTORS.SEARCH_BUTTON)
        time.sleep(1.5)
        self.dismiss_cookie_banner()

    def _js_click(self, element):
        """
        自訂 div 元件常有透明遮罩或 Cookie 橫幅擋住,
        一般 .click() 會噴 ElementClickInterceptedException。
        用 JS 直接觸發點擊比較穩。
        """
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.3)
        self.driver.execute_script("arguments[0].click();", element)

    def _hover(self, element):
        """第三層選單是 aria-haspopup,需要滑鼠移過去才會展開。"""
        from selenium.webdriver.common.action_chains import ActionChains
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.3)
        ActionChains(self.driver).move_to_element(element).perform()

    def set_stock_code(self, stock_code: Optional[str]) -> bool:
        """
        輸入股票代號並點選 autocomplete 建議。回傳是否成功選中。

        探測確認:建議清單是 #autocomplete-list-0 裡的 <table><tbody><tr>。

        為什麼要重試:實測發現第一次查詢偶爾會因為頁面剛載入、
        Cookie 橫幅剛關閉,autocomplete 的 AJAX 還沒就緒而回不了建議。
        沒選中建議就搜尋,HKEXnews 會回 0 筆 —— 而且不會報錯,
        只是靜靜地少了一間公司的資料。這種「安靜的失敗」最危險,
        所以這裡重試,而且把成敗回報給呼叫端。
        """
        from selenium.webdriver.common.by import By

        if not stock_code:
            return True

        for attempt in range(1, 4):
            box = self._wait_visible(SELECTORS.STOCK_CODE_INPUT)
            box.clear()
            time.sleep(0.3)
            box.send_keys(stock_code)
            # 每次重試多等一點,給 AJAX 更多時間
            time.sleep(1.5 + attempt * 1.2)

            try:
                rows = [r for r in self.driver.find_elements(
                    By.CSS_SELECTOR, SELECTORS.AUTOCOMPLETE_ROW)
                    if r.is_displayed() and (r.text or "").strip()]
                if rows:
                    txt = rows[0].text.strip()
                    self._js_click(rows[0])
                    logger.info(f"    已選取: {txt[:40]}")
                    time.sleep(1.2)
                    return True
            except Exception as e:
                logger.debug(f"    autocomplete 讀取失敗: {e}")

            if attempt < 3:
                logger.info(f"    autocomplete 未回應,重試 {attempt}/2")

        logger.warning(f"    ⚠ {stock_code} 的 autocomplete 三次都沒回應,"
                       f"查詢結果可能為空")
        return False

    def set_date_range(self, from_date: str, to_date: str):
        """
        日期格式 yyyy/mm/dd(已確認)。
        欄位可能帶唯讀屬性或綁日曆元件,所以用 JS 設值 + 觸發事件,
        比 send_keys 可靠。
        """
        def fmt(d):
            return datetime.strptime(d, "%Y%m%d").strftime(SELECTORS.DATE_FORMAT)

        for css, val in ((SELECTORS.DATE_FROM_INPUT, fmt(from_date)),
                         (SELECTORS.DATE_TO_INPUT, fmt(to_date))):
            el = self._wait_visible(css)
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                el, val)
        logger.info(f"    日期區間 {fmt(from_date)} ~ {fmt(to_date)}")

    # ── 巢狀選單操作的共用小工具 ──────────────────────────
    @staticmethod
    def _xpath_literal(text: str) -> str:
        """
        把字串安全地包成 XPath 字面值。HKEXnews 的選項文字含有逗號、
        斜線(例如 'Environmental, Social and Governance Information/Report'),
        將來也可能出現單引號,直接用 f-string 拼會產生壞掉的 XPath。
        """
        if "'" not in text:
            return f"'{text}'"
        parts = text.split("'")
        return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"

    def _menu_matches(self, label: str):
        """
        找出目前畫面上「整個元素的文字剛好等於 label」的可見元素。

        用 normalize-space(.) 而不是 normalize-space(text()):
        text() 只取第一個文字節點,選項若被包在 <span> 之類的內層標籤裡
        就會抓不到 —— 這正是 Major Transaction 找不到的可能原因之一。
        用 . 取整個子樹文字則不會有這個問題,而且因為要求「完全相等」,
        包含更多內容的外層容器自然不會誤中。

        回傳的清單依文字長度排序後,同一個選項通常會有巢狀的兩三個元素
        (li > a > span),全部保留 —— 因為「該 hover 哪一個才會展開子選單」
        沒辦法從外面看出來,後面會逐一試,用「子選單有沒有真的出現」
        當判準,而不是猜。
        """
        from selenium.webdriver.common.by import By
        lit = self._xpath_literal(label)
        xp = (f"//li[normalize-space(.)={lit}]"
              f" | //a[normalize-space(.)={lit}]"
              f" | //span[normalize-space(.)={lit}]"
              f" | //div[normalize-space(.)={lit}]")
        try:
            return [e for e in self.driver.find_elements(By.XPATH, xp)
                    if e.is_displayed()]
        except Exception:
            return []

    def _wait_menu_item(self, label: str, timeout: float = 2.5):
        """輪詢等待某個選項出現,回傳找到的元素清單(逾時則空清單)。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            els = self._menu_matches(label)
            if els:
                return els
            time.sleep(0.25)
        return []

    def _expand_to(self, parents, next_label: str, tries: int = 3):
        """
        想辦法讓 next_label 出現在畫面上,回傳 (成功與否, next_label 的元素清單)。

        對每個候選父元素,依序試 hover → 點擊 → 再 hover,每一步都用
        「next_label 有沒有真的出現」來判斷成功,而不是假設某個操作一定有效。

        為什麼要這樣寫:實測發現對 Circulars 這種第二層選單,單純 hover
        有時候展不開(時好時壞),而且該 hover 的可能是 <li> 而不是裡面的
        <a>。與其猜哪一個對,不如全部試一遍並檢查結果 —— 多花幾秒,
        換取不會靜靜地選錯分類。
        """
        for attempt in range(1, tries + 1):
            for parent in parents:
                try:
                    self._hover(parent)
                except Exception:
                    continue
                els = self._wait_menu_item(next_label, 2.0)
                if els:
                    return True, els

                try:
                    self._js_click(parent)
                except Exception:
                    continue
                els = self._wait_menu_item(next_label, 2.0)
                if els:
                    return True, els

                # 點擊有可能反而把選單收起來,再 hover 一次補救
                try:
                    self._hover(parent)
                except Exception:
                    continue
                els = self._wait_menu_item(next_label, 1.5)
                if els:
                    return True, els

            if attempt < tries:
                logger.info(f"    「{next_label}」還沒出現,重試展開 {attempt}/{tries - 1}")
                time.sleep(0.8)
        return False, []

    def _selected_category_text(self) -> str:
        """讀出第二段下拉目前顯示的文字,用來驗證真的選中了。"""
        from selenium.webdriver.common.by import By
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, SELECTORS.CATEGORY_FIELD)
            return (el.text or "").strip()
        except Exception:
            return ""

    def set_document_type(self, path: List[str]) -> bool:
        """
        依 path 展開巢狀選單並選取最後一層。**回傳是否成功**。

        path 來自 config.DOC_TYPES,例如:
            ["Financial Statements/ESG Information", "Annual Report"]      (兩層)
            ["Circulars", "Notifiable Transactions", "Major Transaction"]  (三層)

        回傳值很重要,不是裝飾用的:選不到文件類型時,HKEXnews 會用
        「ALL」去搜尋,結果看起來很正常(而且筆數更多),但拿到的是全類型
        公告,卻會被下游標成使用者指定的類型。呼叫端必須據此中止,
        絕不能把這種結果當成查詢成功 —— 這是最典型的「安靜的失敗」。

        每一層都用「下一層有沒有真的出現」來驗證,最後再讀下拉欄位的
        文字確認選中的就是要的那一項,而不是假設點下去就成功。
        """
        if not path:
            raise ValueError("set_document_type 需要至少一段路徑")

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC

        # 第1步:點開第一段下拉(ALL / Headline Category / Document Type)
        self._js_click(self._wait_visible(SELECTORS.TIER1_FIELD))
        time.sleep(1.0)

        # 第2步:選「Headline Category」
        try:
            opt = self.driver.find_element(
                By.CSS_SELECTOR, SELECTORS.TIER1_OPTION_HEADLINE_CATEGORY)
            self._js_click(opt)
            logger.info("    已選 Headline Category 模式")
            time.sleep(1.2)
        except Exception as e:
            logger.error(f"    找不到 Headline Category 選項: {e}")
            return False

        # 等 #rbAfter2006 從 display:none 變可見
        try:
            self.wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, SELECTORS.CATEGORY_GROUP)))
        except Exception:
            logger.warning("    #rbAfter2006 沒有如預期顯示出來")

        # 第3步:點開第二段下拉
        self._js_click(self._wait_visible(SELECTORS.CATEGORY_FIELD))
        time.sleep(1.2)

        # 第4步:第一層(Circulars / Financial Statements/ESG Information / ...)
        level1 = [e for e in self.driver.find_elements(
            By.CSS_SELECTOR, SELECTORS.CATEGORY_LEVEL1_ITEM) if e.is_displayed()]
        head = path[0].split("/")[0].strip().lower()
        current = [e for e in level1 if head in (e.text or "").strip().lower()]
        if not current:
            logger.error(f"    找不到分類「{path[0]}」,"
                         f"目前可見的分類: {[e.text.strip()[:30] for e in level1]}")
            return False

        # 中間層:每一段都要先確認下一段真的出現了才往下走
        for depth in range(1, len(path)):
            label = path[depth]
            okay, items = self._expand_to(current, label)
            if not okay:
                visible = self._visible_menu_labels()
                logger.error(f"    展開「{path[depth - 1]}」後找不到「{label}」")
                logger.error(f"    目前這一層看得到的選項: {visible}")
                logger.error(f"    → 請用 check_menu.py 對照真實頁面校正 "
                             f"config.DOC_TYPES 裡的文字")
                return False

            if depth < len(path) - 1:
                current = items
                logger.info(f"    已展開 {label}")
                continue

            # 最後一層:點擊選取,並逐一嘗試候選元素直到欄位文字確認選中
            for el in items:
                try:
                    self._js_click(el)
                except Exception:
                    continue
                time.sleep(1.0)
                shown = self._selected_category_text()
                if label.lower() in shown.lower():
                    logger.info(f"    已選取 {' → '.join(path)}(欄位顯示: {shown[:40]})")
                    return True

            shown = self._selected_category_text()
            logger.error(f"    點了「{label}」但下拉欄位仍顯示「{shown[:40]}」,"
                         f"無法確認有選中")
            return False

        return False

    def _visible_menu_labels(self, limit: int = 25) -> list:
        """
        列出目前畫面上可見的選單項目文字,失敗時印出來給人對照用。
        沒有這個,使用者只會看到「找不到 X」卻不知道實際有什麼可選。
        """
        from selenium.webdriver.common.by import By
        out = []
        try:
            for e in self.driver.find_elements(By.XPATH, "//li | //a"):
                if not e.is_displayed():
                    continue
                t = (e.text or "").strip()
                if t and 2 < len(t) < 70 and t not in out:
                    out.append(t)
                if len(out) >= limit:
                    break
        except Exception:
            pass
        return out

    def set_document_type_annual_report(self) -> bool:
        """向下相容用的別名 —— 舊呼叫端仍可用這個名字。"""
        return self.set_document_type(
            ["Financial Statements/ESG Information", "Annual Report"])

    def click_search(self):
        btn = self._wait_clickable(SELECTORS.SEARCH_BUTTON)
        self._js_click(btn)
        time.sleep(3.5)   # 等 AJAX 結果渲染

    def read_current_page(self, doc_type: str = "annual_report") -> List[Filing]:
        from selenium.webdriver.common.by import By
        rows = self.driver.find_elements(By.CSS_SELECTOR, SELECTORS.RESULT_ROW)
        out = []
        for row in rows:
            try:
                link_el = row.find_element(By.CSS_SELECTOR, SELECTORS.RESULT_LINK)
                url = link_el.get_attribute("href")
                stock = row.find_element(By.CSS_SELECTOR, SELECTORS.RESULT_STOCK_CODE_CELL).text.strip()
                company = row.find_element(By.CSS_SELECTOR, SELECTORS.RESULT_COMPANY_CELL).text.strip()
                date = row.find_element(By.CSS_SELECTOR, SELECTORS.RESULT_DATE_CELL).text.strip()
                title = link_el.text.strip() or "Annual Report"
                out.append(Filing(stock, company, title, date, url, doc_type=doc_type))
            except Exception as e:
                logger.debug(f"某一列解析失敗,略過: {e}")
        return out

    def has_next_page(self) -> bool:
        from selenium.webdriver.common.by import By
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, SELECTORS.NEXT_PAGE_BUTTON)
            classes = btn.get_attribute("class") or ""
            return SELECTORS.NEXT_PAGE_DISABLED_CLASS not in classes
        except Exception:
            return False

    def go_next_page(self):
        from selenium.webdriver.common.by import By
        self.driver.find_element(By.CSS_SELECTOR, SELECTORS.NEXT_PAGE_BUTTON).click()
        time.sleep(1.5)

    def search_all_pages(self, stock_code: Optional[str],
                         from_date: str, to_date: str,
                         max_pages: int = 50,
                         doc_type: str = "annual_report") -> List[Filing]:
        """
        跑完一次搜尋(單一時間窗)+ 自動翻頁,回傳這個窗內所有結果。

        doc_type 是 config.DOC_TYPES 裡的 key(例如 "annual_report"、
        "major_transaction"),用來查出選單路徑,並標記回傳的 Filing
        方便下載時決定檔名。

        查到 0 筆時會整輪重試一次 —— 因為「0 筆」有兩種可能:
        真的沒有這份文件,或是表單某一步沒設定成功。兩者外觀一樣,
        但後者重跑一次通常就好了。多花 20 秒換取不漏掉資料是值得的。
        """
        self.last_error = ""
        import config as _C
        spec = _C.DOC_TYPES.get(doc_type)
        if spec is None:
            raise ValueError(f"未知的文件類型「{doc_type}」,"
                             f"可用選項: {list(_C.DOC_TYPES.keys())}")
        path = spec["path"]

        for attempt in (1, 2):
            self.open_search_page()
            picked = self.set_stock_code(stock_code)

            # 文件類型沒設定成功就必須中止這一輪。
            # 若照樣往下搜尋,HKEXnews 會用「ALL」查詢:結果看起來完全正常,
            # 筆數甚至更多,但拿到的是全類型公告,而且會被下游標記成
            # 使用者指定的類型、用該類型的檔名存檔。這種「看起來成功的錯誤」
            # 比直接報錯危險得多 —— 寧可回報 0 筆,不可回報錯的 100 筆。
            if not self.set_document_type(path):
                logger.error(f"  文件類型「{doc_type}」未能設定成功,中止本輪查詢")
                logger.error("  (若繼續搜尋會拿到「全部類型」的結果並被誤標成此類型)")
                if attempt == 2:
                    self.last_error = (f"文件類型「{doc_type}」的選單未能設定成功,"
                                       f"已中止查詢(避免拿到全類型結果)")
                    return []
                logger.warning("  重試一次...")
                time.sleep(2.0)
                continue

            # 日期要在選完股票代號之後設定 —— HKEXnews 選了股票後會自動
            # 把日期區間重設為該股票的可查範圍,先設日期會被覆蓋掉。
            self.set_date_range(from_date, to_date)
            self.click_search()

            results: List[Filing] = []
            for page_no in range(1, max_pages + 1):
                results.extend(self.read_current_page(doc_type=doc_type))
                logger.info(f"  第 {page_no} 頁,累計 {len(results)} 筆")
                if not self.has_next_page():
                    break
                self.go_next_page()
            else:
                logger.warning(f"達到 max_pages={max_pages} 上限,"
                               f"可能還有更多結果未讀取")

            if results or attempt == 2:
                return results

            reason = "表單未正確設定" if not picked else "查詢無結果"
            logger.warning(f"  查得 0 筆({reason}),重試一次...")
            time.sleep(2.0)
        return []


# ═══════════════════════════════════════════════════════════════════
# 批次流程總指揮
# ═══════════════════════════════════════════════════════════════════
class BatchDownloader:
    """
    串起「哪些公司 / 多長區間 / 下載到哪裡」的整體流程。
    這一層不管 Selenium 細節,只管流程順序與容錯,方便未來把
    HKEXBrowser 換成別的實作(例如真的找到官方API時)而不用改這層。
    """

    def __init__(self, out_dir: str = "downloads", headless: bool = True,
                 polite_delay: float = 2.0, reporter=None):
        self.out_dir = out_dir
        self.headless = headless
        self.polite_delay = polite_delay
        # reporter 是 error_report.ErrorReport(可為 None)。下載階段的問題
        # 是這一層自己就知道的事實(查無結果、連線失敗),直接明確回報,
        # 不需要靠事後掃描輸出文字去猜。
        self.reporter = reporter
        os.makedirs(out_dir, exist_ok=True)

    def _report(self, what: str, filename=None, stock=None):
        if self.reporter is not None:
            try:
                self.reporter.add(what, filename=filename, stock=stock)
            except Exception as e:
                logger.debug(f"錯誤紀錄寫入失敗(不影響下載): {e}")

    def run_for_companies(self, stock_codes: List[str],
                          from_date: str, to_date: str,
                          doc_type: str = "annual_report") -> List[Filing]:
        """情境A:已知特定公司清單。每間公司各自查(可用366天大區間,較快)。"""
        all_filings: List[Filing] = []
        empty: List[str] = []
        reasons: dict = {}      # 代號 → 0 筆的具體原因(空字串代表真的查無)
        with HKEXBrowser(headless=self.headless) as browser:
            for i, code in enumerate(stock_codes, 1):
                logger.info(f"[{i}/{len(stock_codes)}] 查詢股票代號 {code}")
                try:
                    filings = browser.search_all_pages(code, from_date, to_date,
                                                        doc_type=doc_type)
                    all_filings.extend(filings)
                    logger.info(f"  {code}: 找到 {len(filings)} 筆")
                    if not filings:
                        empty.append(code)
                        reasons[code] = browser.last_error
                except Exception as e:
                    logger.error(f"  {code}: 查詢失敗 — {e}")
                    empty.append(code)
                    self._report(f"查詢失敗:{str(e)[:80]}", stock=code)
                time.sleep(self.polite_delay)

        # 查無結果的公司要明確列出來,不能靜靜地少掉 ——
        # 使用者需要知道哪幾間要人手確認
        if empty:
            logger.warning(f"以下 {len(empty)} 間公司查無「{doc_type}」,請人手確認: "
                           f"{', '.join(empty)}")
            logger.warning("  可能原因:該區間內未刊發此類文件 / 代號有誤 / 網站暫時異常")
            for code in empty:
                detail = reasons.get(code)
                self._report(
                    detail if detail else
                    (f"查無「{doc_type}」類型文件 "
                     f"(可能原因:該區間內未刊發此類文件 / 代號有誤 / 網站暫時異常)"),
                    stock=code)
        return all_filings

    def run_for_whole_market(self, from_date: str, to_date: str,
                             doc_type: str = "annual_report") -> List[Filing]:
        """
        情境B:整個市場、不限公司。
        因為不指定股票代號時查詢區間上限只有約30天,長區間要拆成多個窗。

        ⚠️ 這個情境即使架構正確,實際跑起來的資料量會非常大
        (旺季一個月可能上千筆),請搭配 DateWindowPlanner 拆更細的窗,
        並且認真考慮要不要真的對網站送出這麼多次查詢請求 —— 對伺服器
        負擔大、也更容易觸發網站的防爬蟲機制。面試demo建議用情境A即可。
        """
        all_filings: List[Filing] = []
        windows = list(DateWindowPlanner.plan(from_date, to_date, has_stock_code=False))
        logger.info(f"全市場查詢,總區間拆成 {len(windows)} 個時間窗")

        with HKEXBrowser(headless=self.headless) as browser:
            for i, (w_from, w_to) in enumerate(windows, 1):
                logger.info(f"[{i}/{len(windows)}] 時間窗 {w_from} ~ {w_to}")
                try:
                    filings = browser.search_all_pages(None, w_from, w_to,
                                                        doc_type=doc_type)
                    all_filings.extend(filings)
                    logger.info(f"  找到 {len(filings)} 筆")
                except Exception as e:
                    logger.error(f"  查詢失敗 — {e}")
                    self._report(f"全市場查詢失敗(時間窗 {w_from}~{w_to}):{str(e)[:60]}")
                time.sleep(self.polite_delay)
        return all_filings

    def download(self, filings: List[Filing]) -> List[str]:
        """下載階段跟 Selenium 無關,沿用原本 hkexnews.py 的 requests 邏輯即可。"""
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ValuationResearchBot/1.0)"}
        paths = []
        # 先去重:同一份文件在不同時間窗查詢下可能重複出現
        seen_urls = set()
        unique = [f for f in filings if not (f.url in seen_urls or seen_urls.add(f.url))]
        logger.info(f"去重後共 {len(unique)} 份文件待下載(原始 {len(filings)} 筆)")

        for i, f in enumerate(unique, 1):
            path = os.path.join(self.out_dir, f.local_filename())
            if os.path.exists(path):
                paths.append(path)
                continue
            logger.info(f"[{i}/{len(unique)}] 下載 {f.company} ({f.stock_code})")
            try:
                with requests.get(f.url, headers=headers, timeout=180, stream=True) as r:
                    r.raise_for_status()
                    with open(path, "wb") as fh:
                        for chunk in r.iter_content(1 << 16):
                            fh.write(chunk)
                paths.append(path)
            except Exception as e:
                logger.error(f"  下載失敗: {e}")
                self._report(f"下載失敗:{str(e)[:80]}",
                             stock=f.clean_code())
            time.sleep(self.polite_delay)
        return paths
