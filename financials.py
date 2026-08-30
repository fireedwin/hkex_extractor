# -*- coding: utf-8 -*-
"""
financials.py — 功能D:三大報表數據調出

年報財務報表的難點,是它**不是乾淨的表格**:
  - 很多年報的報表沒有框線,pdfplumber 的 extract_tables() 抓不到
  - 數字用括號代表負數:(1,234)
  - 空值用破折號:—  –  -
  - 同一行有本年 / 上年兩欄,還可能夾著附註編號

做法:不依賴表格框線,改用「行文字解析」——
  找到含科目名稱的那一行,把該行所有數字抓出來,
  第一個數字通常是本年,第二個是上年(港交所年報的標準排版)。
  附註編號(1-2 位數且無千分位)會先被剔除。

這種「先理解文件長什麼樣,再寫規則」的做法,
就是純 AI 方案做不到、需要人來設計的部分。
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from config import FIN_STATEMENTS
from pdf_reader import Page


@dataclass
class FinItem:
    statement: str
    item: str
    current_year: Optional[float]
    prior_year: Optional[float]
    page_index: int
    page_cite: str
    source_line: str


@dataclass
class FinResult:
    items: List[FinItem] = field(default_factory=list)
    year_labels: Dict[str, str] = field(default_factory=dict)   # statement -> "2024 / 2023"
    statement_pages: Dict[str, int] = field(default_factory=dict)
    # 每張報表沒抓到的科目 —— 誠實列出缺口,供人手補入
    missing: Dict[str, List[str]] = field(default_factory=dict)


# 數字:1,234  (1,234)  1,234.5
_NUM_RE = re.compile(r"\(?\s*-?\d[\d,]*(?:\.\d+)?\s*\)?")
# 獨立的破折號 = 該欄為零/無。港股年報用 – — - 表示 nil。
# 必須當成一個「值」而不是略過,否則欄位會整個左移:
#     Income tax expense 12 – (3,772)
# 忽略破折號的話,上年的 (3,772) 會被當成本年 —— 數字正確、年度錯誤。
_NIL_RE = re.compile(r"(?<![\w\d])[—–-](?![\w\d])")
_TOKEN_RE = re.compile(
    r"\(?\s*-?\d[\d,]*(?:\.\d+)?\s*\)?|(?<![\w\d])[—–-](?![\w\d])")


def _to_float(tok: str) -> Optional[float]:
    tok = tok.strip()
    if _NIL_RE.fullmatch(tok):
        return 0.0
    neg = tok.startswith("(") and tok.endswith(")")
    tok = tok.strip("()").replace(",", "").strip()
    try:
        v = float(tok)
    except ValueError:
        return None
    return -v if neg else v


def _looks_like_note_no(tok: str) -> bool:
    """附註編號特徵:1-2 位整數、沒有千分位、沒有小數、沒有括號。"""
    bare = tok.strip().strip("()")
    return ("," not in bare and "." not in bare
            and bare.lstrip("-").isdigit() and abs(int(bare)) < 100)


def _numbers_in_line(line: str) -> List[float]:
    """
    抓出一行裡所有的金額,並剔除附註編號。

    ⚠ 附註編號的判斷不能只看「小於 100」:
      實測 CHINA HEALTH 年報有
          TOTAL EQUITY 95 59,753
      95 是真正的權益總額(公司權益幾乎歸零),不是附註編號。
      一律剔除小數字會把它誤刪,結果本年權益變成上年的 59,753。

      附註編號只會出現在科目名稱「正後方」的第一欄,而且後面
      一定還有本年+上年兩個數字。所以只剔除「開頭第一個」小整數,
      而且剔除後至少要還剩兩個數字。
    """
    toks = [m.group(0) for m in _TOKEN_RE.finditer(line)]
    vals, raw = [], []
    for t in toks:
        v = _to_float(t)
        if v is not None:
            vals.append(v)
            raw.append(t)

    if len(vals) >= 3 and _looks_like_note_no(raw[0]):
        return vals[1:]
    return vals


def _find_statement_pages(pages: List[Page], anchors: List[str]) -> List[int]:
    """
    找出報表主頁。

    ⚠ 為什麼不能只看「數字最多」:
      實測騰訊年報,真正的現金流量表在 p.133-134,但附註頁 p.256
      也提到「consolidated statement of cash flows」,而且數字量
      439 > 245,結果被誤判成報表本體,抓到的數字來自附註表格。

      關鍵差異:報表頁的標題印在**頁面最上方**,附註頁只是內文提及。
      所以優先取「標題出現在開頭」的頁面,並依頁序排列 ——
      報表本體在前,續頁在後(資產負債表、現金流量表常常跨 2-3 頁)。
    """
    titled, mentioned = [], []
    for p in pages:
        if not p.text:
            continue
        low = p.text.lower()
        head = low[:150]          # 頁面開頭 = 標題區
        for a in anchors:
            al = a.lower()
            if al in head:
                titled.append(p.index)
                break
            if al in low:
                digits = sum(c.isdigit() for c in p.text)
                mentioned.append((p.index, digits))
                break

    if titled:
        # 標題頁依頁序:第一頁是本體,後續是續頁
        return titled[:4]

    # 沒有任何標題頁才退而求其次,用數字密度猜
    mentioned.sort(key=lambda x: -x[1])
    return [i for i, _ in mentioned[:3]]


def _find_year_labels(page: Page) -> str:
    """從報表頁抓出年度欄位標題,例如 '2024 2023'。"""
    years = re.findall(r"\b(20[0-3]\d)\b", page.text[:1200])
    uniq = []
    for y in years:
        if y not in uniq:
            uniq.append(y)
    return " / ".join(uniq[:2]) if uniq else ""


# 中日韓字元與全形標點 —— 用來剝掉雙語年報行首的中文標籤
_CJK_CLASS = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
_LEADING_CJK_RE = re.compile(
    rf"^[{_CJK_CLASS}\s•·\-–—*、,。：:／/（）()「」【】]+")


def _strip_alternatives(s: str) -> str:
    """
    把「Profit/(loss) before tax」正規化成「Profit before tax」。

    港股年報在虧損年度常寫成 溢利╱(虧損) / Profit/(loss),
    不處理的話這些科目在虧損年度會全部漏抓 —— 而虧損公司
    往往正是估值案件的重點對象。
    """
    s = re.sub(r"[／/]\s*[（(][^)）]*[)）]", "", s)   # "/(loss)"
    s = re.sub(r"[（(][^)）]*[)）]", "", s)            # 其餘括號插語
    return re.sub(r"\s+", " ", s).strip()


def _label_variants(line: str) -> List[str]:
    """
    產生一行的多種「標籤寫法」,任一種對得上就算命中。

    港交所年報有三種常見排版,必須全部支援:
      1. 純英文:  Revenue 6 98,555 79,128
      2. 純中文:  收益 6 98,555 79,128
      3. 中英對照:收益 Revenue 6 98,555 79,128   ← 最常見,也最容易漏

    第 3 種若只比對行首,英文科目名前面卡著中文就永遠匹配不到。
    所以額外產生「剝掉行首中文」的版本。
    """
    base = re.sub(r"^[\s•·\-–—*]+", "", line)
    variants = [base]

    stripped = _LEADING_CJK_RE.sub("", base)
    if stripped and stripped != base:
        variants.append(stripped)

    # 再各自產生一份去掉 /(loss) 這類插語的版本
    for v in list(variants):
        alt = _strip_alternatives(v)
        if alt and alt != v:
            variants.append(alt)

    return [v.lower() for v in variants]


def _line_label(line: str) -> str:
    """回傳主要的標籤寫法(供區段標題比對使用)。"""
    return _label_variants(line)[0]


def _match_line_item(line: str, line_items: dict):
    """
    判斷這一行是哪個財務科目。回傳 (科目名, 命中的別名) 或 None。

    ⚠ 為什麼一定要「行首比對」而不是「整行包含」:
      實測騰訊年報時發現,用「整行包含 revenue」會把
          Cost of revenues 7 (311,011) (315,906)
      判成 Revenue,抓到的是成本、而且是負數。
      數字看起來完全正常,但意義完全錯 —— 這種錯誤最危險,
      因為不會有任何異常可以察覺。

      財務報表的排版一定是科目名稱在行首,所以改成要求行首相符。

    另外取「最長的別名」而不是第一個相符的:
      "Revenue from contracts with customers" 同時符合
      "revenue" 和 "revenue from contracts with customers",
      取長的才不會把細項誤判成總額。
    """
    variants = _label_variants(line)
    best = None
    for item, aliases in line_items.items():
        for alias in aliases:
            a = alias.lower()
            for v in variants:
                if not v.startswith(a):
                    continue
                # 排除延伸科目:「Total assets less current liabilities」
                # (總資產減流動負債)是完全不同的數字,不能當成總資產。
                rest = v[len(a):].lstrip(" :：")
                # 中英文都要擋:「total assets less current liabilities」
                # 與「總資產減流動負債」都不是總資產本身。
                if rest.startswith("less ") or rest.startswith("減"):
                    continue
                if best is None or len(a) > len(best[1]):
                    best = (item, a)
                break
    return best


def _is_pure_number_line(line: str) -> bool:
    """
    判斷這行是不是「只有數字」—— 也就是細項小計那一行。
    允許貨幣符號與空白,但不能有其他文字。
    """
    s = re.sub(r"[\s$,()—–\-HK]", "", line)
    return bool(s) and s.replace(".", "").isdigit()


def _lookahead_subtotal(lines: List[str], start: int,
                        line_items: dict, max_ahead: int = 10):
    """
    科目名稱那行沒有金額時,往後找細項後面的小計行。

    實測騰訊年報的損益表就是這樣排的:
        Revenues                5              ← 只有附註編號
          VAS                          319,268   298,375
          Online advertising           121,161   101,482
          ...
                                       660,257   609,015   ← 總額獨立成行

    沒有這個處理,整個「收入」科目會靜靜地漏掉。

    安全限制:遇到下一個科目名稱就停止,避免跨到別的項目去。
    """
    # 第一階段:找細項後面的「純數字小計行」。
    # 中途的細項(例如 VAS 319,268 298,375)要略過,不能當成答案。
    for j in range(start + 1, min(start + 1 + max_ahead, len(lines))):
        nxt = lines[j]
        if not nxt.strip():
            continue
        if _match_line_item(nxt, line_items):   # 撞到下一個科目就停
            break
        if _is_pure_number_line(nxt):
            nums = _numbers_in_line(nxt)
            # 必須有本年+上年兩欄。只有一個數字的「純數字行」通常是
            # 頁尾的印刷頁碼 —— 實測 WLS 就抓到頁碼 77 當成年度溢利。
            if len(nums) >= 2:
                return nums, j

    # 第二階段:沒有小計行,可能是「換行標籤」——
    # 科目名太長被 PDF 折成兩行,金額在緊接的下一行。例如騰訊:
    #   Purchase of/prepayments for property, plant and equipment,
    #   construction in progress and land use rights (62,927) (...)
    # 只看緊接的第一行,而且要有兩個金額(本年+上年),避免亂抓。
    for j in range(start + 1, min(start + 3, len(lines))):
        nxt = lines[j]
        if not nxt.strip():
            continue
        if _match_line_item(nxt, line_items):
            break
        nums = _numbers_in_line(nxt)
        if len(nums) >= 2:
            return nums, j
        break
    return None, None
    """
    取出一行開頭的「科目名稱」部分,轉小寫供比對。
    去掉行首的項目符號、破折號、空白等裝飾字元。
    """
    return re.sub(r"^[\s•·\-–—*]+", "", line).lower()


def _find_section_subtotal(lines: List[str], header_aliases: List[str],
                           stop_aliases: List[str]):
    """
    找「區段小計」—— 有區段標題但小計行沒有名稱的排版。

    實測騰訊資產負債表:
        Current assets                        ← 區段標題,無金額
          Inventories              440    456
          Accounts receivable   48,203 46,606
          ...
                                496,180 518,446    ← 小計,沒有任何文字
        Total assets          1,780,995 1,577,246  ← 下一個區段,停止

    因為沒有「Total current assets」這個標籤,一般的行首比對抓不到,
    但流動比率就是靠這個數字算的,漏掉影響很大。

    做法:從區段標題往下掃,記住最後一個「純數字行」,
    遇到停止標籤就結束。回傳 (數字, 行索引) 或 (None, None)。
    """
    start = None
    for i, line in enumerate(lines):
        variants = _label_variants(line)
        if any(v.startswith(h) for v in variants for h in header_aliases):
            if not _numbers_in_line(line):     # 標題行本身不該有金額
                start = i
                break
    if start is None:
        return None, None

    last_nums, last_at = None, None
    for j in range(start + 1, len(lines)):
        variants = _label_variants(lines[j])
        if any(v.startswith(s) for v in variants for s in stop_aliases):
            break
        if _is_pure_number_line(lines[j]):
            nums = _numbers_in_line(lines[j])
            if len(nums) >= 2:      # 同理:排除頁碼那種單一數字行
                last_nums, last_at = nums, j
    return last_nums, last_at


def integrity_checks(res: "FinResult") -> List[tuple]:
    """
    會計恆等式交叉驗證 —— 用報表自身的內在一致性檢查擷取結果。

    這是驗證自動擷取最有力的方法:不需要人工翻原文,
    數字之間本來就該對得上。對不上就代表某個欄位抓錯了。

    回傳 [(項目, 是否通過, 說明), ...]
    """
    d = {i.item: i.current_year for i in res.items if i.current_year is not None}
    out = []

    def close(a, b, tol=1.0):
        return abs(a - b) <= tol

    ca, cl = d.get("Total Current Assets"), d.get("Total Current Liabilities")
    if ca is not None and cl is not None:
        out.append(("流動資產 − 流動負債 = 淨流動資產", True,
                    f"{ca:,.0f} − {cl:,.0f} = {ca - cl:,.0f}"))

    ta, tl, te = (d.get("Total Assets"), d.get("Total Liabilities"),
                  d.get("Total Equity"))
    if None not in (ta, tl, te):
        ok = close(ta, tl + te, max(2.0, abs(ta) * 0.001))
        out.append(("總資產 = 總負債 + 總權益", ok,
                    f"{ta:,.0f} vs {tl:,.0f} + {te:,.0f} = {tl + te:,.0f}"))

    rev, cos, gp = (d.get("Revenue"), d.get("Cost of Sales"),
                    d.get("Gross Profit"))
    if None not in (rev, cos, gp):
        # 銷售成本通常存為負數
        calc = rev + cos if cos < 0 else rev - cos
        ok = close(gp, calc, max(2.0, abs(rev) * 0.001))
        out.append(("收入 − 銷售成本 = 毛利", ok,
                    f"{rev:,.0f} − {abs(cos):,.0f} = {calc:,.0f} vs 毛利 {gp:,.0f}"))

    pbt, tax, pfy = (d.get("Profit Before Tax"), d.get("Income Tax"),
                     d.get("Profit for the Year"))
    if None not in (pbt, tax, pfy):
        # 稅項的正負號沒有統一慣例:
        #   「Income tax expense (45,018)」→ 存成負數,要相加
        #   「Income tax credit 255」      → 稅務抵免,存成正數,也要相加
        # 但有些年報把費用寫成正數,那就要相減。
        # 兩種算法只要有一種對得上就算通過 —— 不能因為慣例不同就誤報。
        tol = max(2.0, abs(pbt) * 0.02)
        ok = close(pfy, pbt + tax, tol) or close(pfy, pbt - tax, tol)
        sign = "+" if close(pfy, pbt + tax, tol) else "−"
        out.append(("除稅前溢利 ± 稅項 = 年內溢利", ok,
                    f"{pbt:,.0f} {sign} {abs(tax):,.0f} = "
                    f"{pbt + tax if sign == '+' else pbt - tax:,.0f} vs {pfy:,.0f}"))

    # 三大報表在年報裡一定是連續排在一起的。
    # 若某一張的頁碼離其他兩張很遠,幾乎可以確定是抓錯頁 ——
    # 例如把前段的「財務摘要」當成損益表本體。
    pgs = res.statement_pages
    if len(pgs) >= 2:
        vals = sorted(pgs.values())
        spread = vals[-1] - vals[0]
        ok = spread <= MAX_STATEMENT_SPREAD
        detail = "、".join(f"{k}: p.{v}" for k, v in pgs.items())
        out.append(("三大報表應相鄰", ok,
                    detail + f"(相距 {spread} 頁"
                    + ("" if ok else ",可能有一張抓錯頁") + ")"))

    return out


# 三大報表之間可接受的最大頁距。年報的財務報表一定連續排在一起,
# 超過這個距離代表某一張抓錯了(例如把前段的財務摘要當成損益表)。
MAX_STATEMENT_SPREAD = 40


def _pick_consistent_pages(candidates: Dict[str, List[int]]) -> Dict[str, List[int]]:
    """
    利用「三大報表一定相鄰」的特性,自動挑掉離群的候選頁。

    實測 C&D 年報:損益表被判在 p.5,但資產負債表在 p.100、
    現金流量表在 p.103 —— p.5 顯然是前段的財務摘要之類的頁面。
    這種錯誤不會有任何異常表徵,抓出來的數字看起來也正常。

    做法:先用「候選最多的那一張報表」的首頁當基準,
    其他報表若有離基準較近的候選就改用它。
    """
    valid = {k: v for k, v in candidates.items() if v}
    if len(valid) < 2:
        return candidates

    # 用各報表首頁的中位數當基準,比平均值不易被離群值拉走
    firsts = sorted(v[0] for v in valid.values())
    anchor = firsts[len(firsts) // 2]

    fixed = {}
    for stmt, pages in candidates.items():
        if not pages:
            fixed[stmt] = pages
            continue
        near = [p for p in pages if abs(p - anchor) <= MAX_STATEMENT_SPREAD]
        # 有靠近基準的候選就用它們,否則保留原判(不硬改)
        fixed[stmt] = near if near else pages
    return fixed


def extract_financials(pages: List[Page], verbose: bool = True) -> FinResult:
    res = FinResult()
    page_map = {p.index: p for p in pages}

    # 先把三張報表的候選頁全部找出來,再用「報表必相鄰」的特性
    # 統一校正 —— 單獨判斷每一張時,無法察覺某一張離群。
    raw_cands = {stmt: _find_statement_pages(pages, cfg["page_anchors"])
                 for stmt, cfg in FIN_STATEMENTS.items()}
    all_cands = _pick_consistent_pages(raw_cands)
    if verbose:
        for stmt in raw_cands:
            if raw_cands[stmt] and all_cands[stmt] != raw_cands[stmt]:
                print(f"[financials] {FIN_STATEMENTS[stmt]['zh']} 候選頁校正: "
                      f"{raw_cands[stmt]} → {all_cands[stmt]}(依報表相鄰原則)")

    for stmt, cfg in FIN_STATEMENTS.items():
        cand_pages = list(all_cands.get(stmt) or [])
        if not cand_pages:
            if verbose:
                print(f"[financials] 找不到「{cfg['zh']}」的頁面")
            continue

        best_page = cand_pages[0]
        # 報表常常跨兩頁(例如資產負債表的資產在前頁、負債權益在後頁),
        # 但續頁的標題可能寫「(continued)」而抓不到,所以主動把下一頁納入。
        for nxt in (best_page + 1,):
            if nxt in page_map and nxt not in cand_pages:
                cand_pages.append(nxt)

        res.statement_pages[stmt] = best_page
        res.year_labels[stmt] = _find_year_labels(page_map[best_page])
        if verbose:
            print(f"[financials] {cfg['zh']}: PDF p.{best_page} "
                  f"(年度欄 {res.year_labels[stmt] or '未偵測'})")

        found = set()
        for pidx in cand_pages:
            page = page_map[pidx]
            lines = page.text.splitlines()
            is_primary = (pidx == best_page)
            # 這一頁每個科目的最佳候選:item -> (別名, 數字, 頁, 標註, 原文行)
            candidates = {}

            for li, line in enumerate(lines):
                hit = _match_line_item(line, cfg["line_items"])
                if not hit:
                    continue
                item, alias = hit
                if item in found:
                    continue

                nums = _numbers_in_line(line)
                src_line = line

                # 只有一個小整數 → 很可能是「科目名 + 附註編號」而已
                # (例如騰訊的「Revenues 5」),金額在後面的小計行。
                # 先試前瞻;找得到就用前瞻的結果,找不到才退回這個數字。
                note_only = (len(nums) == 1 and float(nums[0]).is_integer()
                             and abs(nums[0]) < 100 and "," not in line)
                if not nums or note_only:
                    la_nums, at = _lookahead_subtotal(lines, li, cfg["line_items"])
                    if la_nums:
                        nums = la_nums
                        src_line = f"{line.strip()} … {lines[at].strip()}"
                    elif not nums:
                        continue

                # 非主要報表頁的雜訊過濾:
                # 標準報表是「本年 + 上年」兩欄。附註裡的多欄表格
                # (例如分部折舊 5,242 6,792 7,773 55 19,862)欄數更多,
                # 抓進來的數字意義完全不同,所以非主頁只接受兩欄格式。
                if not is_primary and len(nums) > 2:
                    continue

                # 同一頁可能有多行都符合同一個科目,例如騰訊現金流量表:
                #     Cash generated from operations              304,705
                #     Net cash flows generated from operating activities  258,521
                # 兩者概念不同(前者未扣利息稅項),差了 460 億。
                # 取「別名最長 = 最精確」的那一行,而不是先遇到的那一行。
                prev = candidates.get(item)
                if prev is None or len(alias) > len(prev[0]):
                    candidates[item] = (alias, nums, pidx, page.cite, src_line)

            for item, (alias, nums, pidx2, cite, src_line) in candidates.items():
                if item in found:
                    continue
                res.items.append(FinItem(
                    statement=stmt,
                    item=item,
                    current_year=nums[0],
                    prior_year=nums[1] if len(nums) > 1 else None,
                    page_index=pidx2,
                    page_cite=cite,
                    source_line=re.sub(r"\s+", " ", src_line).strip(),
                ))
                found.add(item)

        # ── 區段小計:標籤式比對抓不到時的補救 ──────────
        # 例如騰訊沒有「Total current assets」這一行,小計是裸數字。
        for item, spec in cfg.get("section_subtotals", {}).items():
            if item in found:
                continue
            for pidx in cand_pages:
                lines = page_map[pidx].text.splitlines()
                nums, at = _find_section_subtotal(
                    lines, spec["header"], spec["stop"])
                if nums:
                    res.items.append(FinItem(
                        statement=stmt,
                        item=item,
                        current_year=nums[0],
                        prior_year=nums[1] if len(nums) > 1 else None,
                        page_index=pidx,
                        page_cite=page_map[pidx].cite,
                        source_line=f"[{spec['header'][0]} 區段小計] "
                                    f"{re.sub(r'  +', ' ', lines[at].strip())}",
                    ))
                    found.add(item)
                    break

        # 記錄這份報表沒抓到哪些科目 —— 讓使用者知道要人手補,
        # 而不是以為「沒出現就是公司沒揭露」
        missing = [i for i in cfg["line_items"] if i not in found]
        if missing:
            res.missing[stmt] = missing

    if verbose:
        print(f"[financials] 共擷取 {len(res.items)} 個財務科目")
        for stmt, miss in res.missing.items():
            print(f"[financials]   {FIN_STATEMENTS[stmt]['zh']} 未擷取: "
                  f"{', '.join(miss)}")
    return res
