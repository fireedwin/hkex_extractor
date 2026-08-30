# -*- coding: utf-8 -*-
"""
pdf_reader.py — 功能A:自動化萃取(支援雙引擎)

設計重點(面試可講的點):

1. **逐頁處理,不整份載入。** 400 頁年報從第一步就切成 400 個獨立單元,
   後面每一筆抓到的資料都天然帶著頁碼。這是「可追溯性」的基礎。

2. **同時記錄 PDF 頁序 與 年報印刷頁碼。**
   年報封面/目錄不算頁,所以 PDF 第 144 頁可能印的是 "143"。
   估值報告引用來源時要寫印刷頁碼,不然覆核的人翻不到。

3. **偵測掃描頁。** 某頁若幾乎抓不到文字,標記為 needs_ocr,
   讓使用者知道哪幾頁要人手處理,而不是靜靜地漏掉資料。

4. **讀取引擎可切換。**
   pdfplumber 約 134 ms/頁,PyMuPDF 約 1.3 ms/頁(實測 200 頁檔案)。
   兩者輸出的文字幾乎相同,但速度差兩個數量級。
   引擎抽換不影響上層任何模組 —— 因為讀取層跟分析層一開始就分開了。

   ⚠ 換引擎前請先用 compare_engines.py 在你自己的年報上驗證兩者結果一致,
     確認無誤再把 DEFAULT_ENGINE 改成 "pymupdf"。
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

# 某些年報用了 pdfminer 不支援的雙分量色彩空間,會對每一頁噴一次警告,
# 洗版到看不見真正重要的訊息。這不影響文字擷取,直接關掉。
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfminer.pdfinterp").setLevel(logging.ERROR)


# ══════════════════════════════════════════════════════════════
# 預設引擎
#
# 已用騰訊(274頁)與 C&D(165頁)兩份真實年報驗證:
# 估值參數、財務科目、主題段落、掃描頁偵測全部逐項相同,速度快 27-39 倍。
# 若要臨時切回舊引擎除錯,用 --engine pdfplumber。
# ══════════════════════════════════════════════════════════════
DEFAULT_ENGINE = "pymupdf"


@dataclass
class Page:
    index: int                      # PDF 第幾頁 (1-based)
    printed_no: Optional[str]       # 年報上印的頁碼,可能是 None
    text: str
    char_count: int
    needs_ocr: bool = False
    tables: list = field(default_factory=list)
    # 這一頁所有的頁碼候選,供 _reconcile_page_numbers() 用整份文件的
    # 偏移量一致性挑選正確的那個
    page_no_candidates: list = field(default_factory=list)

    @property
    def cite(self) -> str:
        """給 Excel 用的來源標註,例如 'PDF p.144 (印刷頁 143)'"""
        if self.printed_no and self.printed_no != str(self.index):
            return f"PDF p.{self.index} (印刷頁 {self.printed_no})"
        return f"PDF p.{self.index}"


# 印刷頁碼通常在頁首/頁尾,單獨一行的數字(可能夾雜公司名)
_PAGE_NO_RE = re.compile(r"^\s*[-–—]?\s*(\d{1,4})\s*[-–—]?\s*$")


def _looks_like_year(n: str) -> bool:
    """
    年報裡到處都是 '2024'(封面、'For the year ended 31 December 2024'、
    欄位標題)。不排除掉的話,頁碼偵測會全部被年份污染。
    """
    return len(n) == 4 and 1990 <= int(n) <= 2099


def _page_no_candidates(text: str) -> List[str]:
    """
    收集這一頁所有「看起來像印刷頁碼」的候選數字,依可信度排序。

    為什麼要收集多個而不是直接回傳第一個:
    實測 C&D 年報 p.86,頁尾是
        ['2', 'ANNUAL REPORT 2024 85']
    那個孤立的「2」其實是 CO₂ 的下標被拆行了,真正的頁碼是 85。
    只取第一個候選就會抓錯。收集全部,再由 _reconcile_page_numbers()
    用整份文件的偏移量一致性挑出對的那個。
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    # 目錄頁的「........ 26」點引導線會被誤認成頁碼,直接跳過整頁
    if sum(1 for l in lines if "....." in l) >= 3:
        return []

    # 頁尾優先於頁首
    ordered = lines[-2:][::-1] + lines[:2]
    cands: List[str] = []

    # 第一輪:整行只有一個數字
    for line in ordered:
        m = _PAGE_NO_RE.match(line)
        if m and not _looks_like_year(m.group(1)):
            cands.append(m.group(1))

    # 第二輪:數字夾在文字旁邊,例如 'ANNUAL REPORT 2024 85' 或 '85 Annual Report'
    #
    # 注意 trailing 的寫法:不能要求數字前面是非數字字元,
    # 因為「ANNUAL REPORT 2024 85」的 85 前面隔著空白的是 '4'。
    # 年份會被 _looks_like_year() 濾掉,所以放寬是安全的。
    for line in ordered:
        for m2 in (re.match(r"^(\d{1,4})(?:\s|$)", line),
                   re.search(r"(?:^|\s)(\d{1,4})\s*$", line)):
            if m2 and not _looks_like_year(m2.group(1)):
                cands.append(m2.group(1))

    # 去重但保留順序
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _guess_printed_page_no(text: str) -> Optional[str]:
    """回傳最可信的單一候選(維持舊介面,供診斷工具使用)。"""
    c = _page_no_candidates(text)
    return c[0] if c else None


def _make_page(index: int, text: str, tables=None) -> Page:
    """兩個引擎共用的 Page 建構邏輯,確保行為完全一致。"""
    cands = _page_no_candidates(text)
    return Page(
        index=index,
        printed_no=cands[0] if cands else None,
        text=text,
        char_count=len(text.strip()),
        # 一頁少於 60 個字元,通常是掃描圖或純圖表頁
        needs_ocr=len(text.strip()) < 60,
        tables=tables or [],
        page_no_candidates=cands,
    )


# ══════════════════════════════════════════════════════════════
# 頁碼一致性校正
#
# 年報的「PDF 頁序」與「印刷頁碼」之間有固定偏移量(封面/目錄不編號)。
# 利用這個特性可以自動挑出正確的候選、剔除誤判 —— 不需要人工逐頁核對。
#
# 實測案例(C&D 年報 p.86):
#   頁尾兩行是 ['2', 'ANNUAL REPORT 2024 85']
#   那個「2」是 CO₂ 下標被拆行,真正的頁碼是 85。
#   全份文件的主流偏移是 1,86-85=1 相符、86-2=84 不符 → 自動選中 85。
#
# 安全閘門:只有當主流偏移涵蓋過半數頁面時才啟用校正。
# 偏移量本來就雜亂的文件(例如附錄自成一套編號)不會被硬套。
# ══════════════════════════════════════════════════════════════
_RECONCILE_MIN_PAGES = 5
_RECONCILE_MIN_SHARE = 0.5


def _reconcile_page_numbers(pages: List[Page], verbose: bool = True) -> None:
    """就地修正 pages 的 printed_no。"""
    from collections import Counter

    offsets = []
    for p in pages:
        if p.printed_no:
            try:
                offsets.append(p.index - int(p.printed_no))
            except ValueError:
                pass
    if not offsets:
        return

    counter = Counter(offsets)
    main_off, main_cnt = counter.most_common(1)[0]

    # 主流偏移不夠強勢就不動 —— 寧可保留原判,也不要硬套一個錯的規律
    if main_cnt < _RECONCILE_MIN_PAGES or main_cnt < len(offsets) * _RECONCILE_MIN_SHARE:
        if verbose:
            print(f"[pdf_reader] 頁碼偏移量不集中(主流 {main_off} 僅 "
                  f"{main_cnt}/{len(offsets)} 頁),略過一致性校正")
        return

    fixed = dropped = 0
    for p in pages:
        if not p.page_no_candidates:
            continue
        # 在所有候選裡找偏移量符合主流的那個
        match = None
        for c in p.page_no_candidates:
            try:
                if p.index - int(c) == main_off:
                    match = c
                    break
            except ValueError:
                continue

        if match:
            if match != p.printed_no:
                p.printed_no = match
                fixed += 1
        elif p.printed_no is not None:
            # 沒有任何候選符合主流偏移 → 原本那個八成是誤判
            p.printed_no = None
            dropped += 1

    if verbose and (fixed or dropped):
        print(f"[pdf_reader] 頁碼一致性校正(主流偏移 {main_off}): "
              f"修正 {fixed} 頁,剔除可疑 {dropped} 頁")


def engine_available(name: str) -> bool:
    """檢查某個引擎的套件裝了沒。"""
    if name == "pymupdf":
        try:
            import pymupdf  # noqa: F401
            return True
        except ImportError:
            pass
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════════════════════
# 引擎一:pdfplumber(慢,但支援表格擷取)
# ══════════════════════════════════════════════════════════════
def _read_pdfplumber(path: str, extract_tables: bool, verbose: bool) -> List[Page]:
    import pdfplumber

    pages: List[Page] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        if verbose:
            print(f"[pdf_reader] 開啟 {path},共 {total} 頁 (引擎: pdfplumber)")

        for i, p in enumerate(pdf.pages, start=1):
            try:
                text = p.extract_text() or ""
            except Exception as e:
                text = ""
                if verbose:
                    print(f"[pdf_reader] 第 {i} 頁文字擷取失敗: {e}")

            tables = []
            if extract_tables:
                try:
                    raw = p.extract_tables()
                    tables = [t for t in raw if t and len(t) > 1]
                except Exception:
                    tables = []

            pages.append(_make_page(i, text, tables))

            if verbose and i % 50 == 0:
                print(f"[pdf_reader]   ...已處理 {i}/{total} 頁")
    return pages


# ══════════════════════════════════════════════════════════════
# 引擎二:PyMuPDF(實測約快 20-40 倍)
#
# 授權提醒:PyMuPDF 採 AGPL v3。在自己電腦上私下使用沒有問題;
# 若要對外散布程式、或架成網路服務讓別人透過網路使用,才會觸發
# 開源義務。這不是法律意見 —— 公司內部正式導入前建議走一次法務確認。
#
# ⚠ 為什麼不能直接用 get_text():
#   PyMuPDF 預設按「文字繪製順序」輸出,真實年報的表格是一格一格畫的,
#   所以會變成:
#       Revenue / 5 / 1,284,500 / 1,142,800    ← 四個獨立的行
#   而 financials.py 是靠「同一行同時有科目名和數字」來解析的,
#   這樣一筆都抓不到。(實測騰訊與 C&D 年報,財務科目全歸零)
#
#   解法:用 get_text("words") 拿到每個詞的座標,再按 y 座標把
#   同一水平線上的詞重新組成一行 —— 也就是重建「視覺上的行」,
#   讓輸出跟 pdfplumber 一致。
# ══════════════════════════════════════════════════════════════

# 同一行的 y 座標容許誤差(點)。太小會把同一行拆開,
# 太大會把上下兩行併在一起。3 點約等於小字級的半個字高。
_LINE_TOLERANCE = 3.0


def _words_to_lines(words) -> str:
    """
    把 (x0, y0, x1, y1, word, ...) 的詞清單,按垂直位置重建成文字行。
    同一行內依水平位置由左至右排序,用空白接起來。
    """
    if not words:
        return ""

    # 依 y 再依 x 排序,y 相近的視為同一行
    words = sorted(words, key=lambda w: (round(w[1], 1), w[0]))

    lines = []
    current, current_y = [], None
    for w in words:
        x0, y0, text = w[0], w[1], w[4]
        if current_y is None or abs(y0 - current_y) <= _LINE_TOLERANCE:
            current.append((x0, text))
            # 用第一個詞的 y 當基準,避免逐漸漂移
            current_y = current_y if current_y is not None else y0
        else:
            lines.append(current)
            current, current_y = [(x0, text)], y0
    if current:
        lines.append(current)

    out = []
    for line in lines:
        line.sort(key=lambda t: t[0])
        out.append(" ".join(t for _, t in line))
    return "\n".join(out)


def _read_pymupdf(path: str, extract_tables: bool, verbose: bool) -> List[Page]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    pages: List[Page] = []
    doc = fitz.open(path)
    try:
        total = doc.page_count
        if verbose:
            print(f"[pdf_reader] 開啟 {path},共 {total} 頁 (引擎: PyMuPDF)")

        for i in range(total):
            try:
                text = _words_to_lines(doc[i].get_text("words"))
            except Exception as e:
                text = ""
                if verbose:
                    print(f"[pdf_reader] 第 {i+1} 頁文字擷取失敗: {e}")
            pages.append(_make_page(i + 1, text, []))

            if verbose and (i + 1) % 200 == 0:
                print(f"[pdf_reader]   ...已處理 {i+1}/{total} 頁")
    finally:
        doc.close()

    if extract_tables and verbose:
        print("[pdf_reader] 註:PyMuPDF 模式不做表格擷取"
              "(分析邏輯本來就沒用到,僅影響摘要頁的表格頁數統計)")
    return pages


# ══════════════════════════════════════════════════════════════
def read_pdf(path: str,
             extract_tables: bool = False,
             verbose: bool = True,
             engine: Optional[str] = None) -> List[Page]:
    """
    讀取整份 PDF,回傳 Page 物件清單。

    engine: "pdfplumber" / "pymupdf" / None(採用 DEFAULT_ENGINE)
    extract_tables: 只有 pdfplumber 支援。分析邏輯並未使用表格資料,
                    它只影響摘要頁的統計數字,預設關閉以節省時間。
    """
    eng = (engine or DEFAULT_ENGINE).lower()

    if eng == "pymupdf" and not engine_available("pymupdf"):
        if verbose:
            print("[pdf_reader] 找不到 PyMuPDF,改用 pdfplumber。"
                  "安裝方式: pip install pymupdf")
        eng = "pdfplumber"

    if eng == "pymupdf":
        pages = _read_pymupdf(path, extract_tables, verbose)
    else:
        pages = _read_pdfplumber(path, extract_tables, verbose)

    # 用整份文件的偏移量一致性校正頁碼(必須在全部讀完之後才做)
    _reconcile_page_numbers(pages, verbose)

    if verbose:
        ocr_pages = [p.index for p in pages if p.needs_ocr]
        print(f"[pdf_reader] 完成。可能需要 OCR 的頁數: {len(ocr_pages)}")
        if ocr_pages[:10]:
            print(f"[pdf_reader]   例如: {ocr_pages[:10]}")
    return pages


def page_summary(pages: List[Page]) -> dict:
    """給 Excel 封面頁用的統計。"""
    return {
        "total_pages": len(pages),
        "total_chars": sum(p.char_count for p in pages),
        "pages_needing_ocr": sum(1 for p in pages if p.needs_ocr),
        "pages_with_tables": sum(1 for p in pages if p.tables),
    }
