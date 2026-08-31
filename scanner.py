# -*- coding: utf-8 -*-
"""
scanner.py — 功能B:關鍵字定位與清洗(規則層 / 第一道篩選)

為什麼要先跑規則層,而不是直接丟給 AI?

  一份年報 400 頁 ≈ 60 萬字 ≈ 40 萬 tokens。
  直接丟給任何模型,不是超出上下文上限,就是模型「讀完前面忘記後面」,
  這正是準確度崩壞的主因。

  規則層做的事:用純文字比對,把 400 頁縮到 10-20 頁真正相關的內容。
  成本近乎零、100% 可重現、不會產生幻覺。
  之後才把這 10-20 頁交給 AI 做語意判斷 —— 這時候 AI 是可靠的。

兩種輸出:
  A) TopicHit  —— 段落層級,給人閱讀 / 給 AI 複核
  B) ParamHit  —— 數字層級,直接進 benchmark 資料庫(估值行最想要的東西)
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from config import TOPICS, VALUATION_PARAMS, PARAM_WINDOW, SETTINGS
from pdf_reader import Page


# ==========================================================================
# A. 主題段落擷取
# ==========================================================================
@dataclass
class TopicHit:
    topic: str
    topic_zh: str
    matched_term: str
    page_index: int
    page_cite: str
    snippet: str
    priority: str


def _clean(text: str) -> str:
    """把 PDF 常見的斷行、多重空白清乾淨,方便閱讀與後續 AI 處理。"""
    text = text.replace("\u00ad", "")            # soft hyphen
    text = re.sub(r"-\n(?=[a-z])", "", text)     # 英文斷字還原
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def scan_topics(pages: List[Page]) -> List[TopicHit]:
    hits: List[TopicHit] = []
    span = SETTINGS["snippet_chars"]

    for topic, cfg in TOPICS.items():
        count = 0
        for page in pages:
            if not page.text:
                continue
            low = page.text.lower()
            for term in cfg["terms"]:
                pos = low.find(term.lower())
                if pos == -1:
                    continue
                start = max(0, pos - span // 3)
                end = min(len(page.text), pos + span)
                hits.append(TopicHit(
                    topic=topic,
                    topic_zh=cfg["zh"],
                    matched_term=term,
                    page_index=page.index,
                    page_cite=page.cite,
                    snippet=_clean(page.text[start:end]),
                    priority=cfg["priority"],
                ))
                count += 1
                break   # 同一頁同一主題只記一次,避免重複洗版
            if count >= SETTINGS["max_hits_per_topic"]:
                break
    return hits


def relevant_page_indices(hits: List[TopicHit], priority_only=True) -> List[int]:
    """
    回傳「值得交給 AI 細看」的頁碼。
    這就是把 400 頁縮成 10-20 頁的那一步。
    """
    idx = {h.page_index for h in hits
           if (not priority_only or h.priority == "high")}
    return sorted(idx)


# ==========================================================================
# B. 估值參數數字擷取  ← 這是給估值行建 benchmark 用的核心功能
# ==========================================================================
@dataclass
class ParamHit:
    parameter: str
    parameter_zh: str
    value_low: Optional[float]
    value_high: Optional[float]
    raw_text: str
    page_index: int
    page_cite: str
    context: str
    confidence: str
    # 數值性質:點估計 / 上限 / 下限 / 區間。
    # 原文「不超過 22%」與「22%」對估值師是兩件事:前者是天花板,
    # 後者是採用值。底稿若一律記成 Low=High=22,讀起來像單一確定假設。
    nature: str = "點估計"


# 百分比:12.5%  /  12.5 per cent  /  12.5％(全形)
_PCT = r"(\d{1,3}(?:\.\d{1,2})?)\s*(?:%|％|per\s?cent)"
_PCT_RE = re.compile(_PCT, re.I)
# 區間:"10.5% to 12.0%" / "10.5% - 12.0%" / "between 10.5% and 12.0%"
#      / "2.55% ~ 3.52%"(騰訊 2024 年報實際寫法)
#
# ⚠ 分隔符漏一個,後果是整個區間變成單點值:比對失敗會退回下面的
# 「單一百分比」分支,只抓到下限。實測騰訊年報 21 筆參數全部
# Low = High,原因就是原文用的 `~` 不在這份清單裡 ——
# 波幅 32%~82% 被記成 32%,拿去做選擇權評價會嚴重低估。
# 全形 ～、連字號各種變體都要收,寧可多列也不要漏。
_RANGE_SEP = r"(?:to|and|至|~|～|-|‐|‑|–|—|―|­|/)"
_RANGE_RE = re.compile(
    _PCT + r"\s*" + _RANGE_SEP + r"\s*" + _PCT, re.I)

# 「某個百分比 + 分隔符」結尾 —— 用來判斷緊接在後的百分比是不是區間上限
_RANGE_TAIL_RE = re.compile(_PCT + r"\s*" + _RANGE_SEP + r"\s*$", re.I)

# ── 表格式寫法(實測 C&D 年報時發現的漏抓) ──────────────────
# 年報附註的表格常把百分號放在欄標題,數字本身不帶 %:
#     Discount rate (%)              13.2      12.8
#     Discount rate (% per annum)    13.2      12.8
#     折現率(%)                       13.2      12.8
# 這種寫法用一般的「數字+%」正則完全抓不到,但它在年報裡非常常見。
#
# 安全做法:只有當觸發詞後方很近的地方出現 (%) 這類單位標示時,
# 才接受不帶百分號的裸數字 —— 避免誤抓附註編號或其他無關數字。
_PCT_UNIT_MARKER = re.compile(r"^[\s:：]*[（(]\s*[%％][^)）]{0,20}[)）]", re.I)
# 裸數字必須帶小數點,進一步降低誤抓整數編號的機率
_BARE_NUM_RE = re.compile(r"(\d{1,3}\.\d{1,2})")


def _match_percent(window: str):
    """
    從觸發詞「後方」的文字裡找出百分比數值。
    回傳 (下限, 上限, 原文, 命中方式) 或 None。
    """
    rng = _RANGE_RE.search(window)
    if rng:
        return float(rng.group(1)), float(rng.group(2)), rng.group(0), "range"

    one = _PCT_RE.search(window)
    if one:
        return float(one.group(1)), float(one.group(1)), one.group(0), "percent"

    # 表格式:觸發詞緊接著 (%) 標示,後面的裸數字才採信
    unit = _PCT_UNIT_MARKER.match(window)
    if unit:
        rest = window[unit.end(): unit.end() + 60]
        nums = _BARE_NUM_RE.findall(rest)
        if nums:
            # 第一個是本年,第二個(若有)是上年;這裡只取本年
            v = float(nums[0])
            return v, v, f"{unit.group(0).strip()} {nums[0]}", "table"
    return None


# ── 上年度比較數字 ─────────────────────────────────────────
# 年報習慣在本年數字後面用括號附上去年:「13.2% (2023: 12.8%)」。
# 這些數字不能跟本年度的混在一起數,否則並列句型會對錯位。
_PRIOR_YEAR_RE = re.compile(r"[（(]\s*20\d\d\s*[:：][^)）]*[)）]")


# ── 並列句型 ───────────────────────────────────────────────
# 實測 C&D 年報 p.144 發現的句型:
#
#   "The growth rate and pre-tax discount rate used by the Group to prepare
#    the cashflow forecast of UPPSD is 1.9% (2023: 2%) and 8.19% (2023: 10.03%)
#    respectively."
#
# 兩個參數先一起提,兩個數值後面按順序給。只抓「觸發詞後第一個百分比」
# 會把折現率誤判成 1.9%(增長率的值)。必須按出現順序配對。
#
# 這裡用比正式觸發詞更寬鬆的措辭清單 —— 因為並列句常用簡略講法
# (「growth rate」而非「long-term growth rate」)。放寬只用在這個
# 情境,不影響一般擷取的嚴謹度。
_RESPECTIVELY_PHRASES = {
    "Discount Rate": ["pre-tax discount rate", "post-tax discount rate",
                      "discount rate", "折現率", "貼現率"],
    "WACC": ["weighted average cost of capital", "wacc"],
    "Terminal Growth Rate": ["long-term growth rate", "terminal growth rate",
                             "growth rate", "增長率"],
    "Capitalisation Rate": ["capitalisation rate", "capitalization rate", "資本化率"],
    "Expected Volatility": ["expected volatility", "預期波幅"],
    "Risk-free Rate": ["risk-free rate", "risk free rate", "無風險利率"],
    "Gross Margin": ["gross profit margin", "gross margin", "毛利率"],
}


def _sentence_around(text: str, pos: int) -> tuple:
    """取出 pos 所在的整個句子,回傳 (句子, pos 在句中的相對位置)。"""
    start = text.rfind(". ", 0, pos)
    start = 0 if start == -1 else start + 2
    end = text.find(". ", pos)
    end = len(text) if end == -1 else end + 1
    return text[start:end], pos - start


def _values_excluding_prior_year(sentence: str):
    """找出句中所有百分比,但排除掉「(2023: X%)」這類上年度數字。"""
    prior_spans = [(m.start(), m.end()) for m in _PRIOR_YEAR_RE.finditer(sentence)]

    def in_prior(p):
        return any(a <= p < b for a, b in prior_spans)

    return [m for m in _PCT_RE.finditer(sentence) if not in_prior(m.start())]


def _resolve_respectively(sentence: str, trigger_pos: int, param: str):
    """
    解析並列句型。回傳 (值, 值, 原文) 或 None。

    做法:數出句中依序提到幾個參數、依序給了幾個數值,
    兩邊數量相同才配對 —— 數量對不上就寧可放棄,不硬猜。
    """
    low = sentence.lower()

    # 找出句中依序出現的參數(同一參數只算一次,取最早位置)
    seen = {}
    for pname, phrases in _RESPECTIVELY_PHRASES.items():
        for ph in phrases:
            p = low.find(ph.lower())
            if p != -1:
                if pname not in seen or p < seen[pname]:
                    seen[pname] = p
                break
    if len(seen) < 2:
        return None

    ordered = sorted(seen.items(), key=lambda kv: kv[1])
    names = [n for n, _ in ordered]
    if param not in names:
        return None

    values = _values_excluding_prior_year(sentence)
    # 數量必須一致才敢配對
    if len(values) != len(names):
        return None

    idx = names.index(param)
    m = values[idx]
    v = float(m.group(1))
    return v, v, m.group(0)


# ── 往回搜尋 ───────────────────────────────────────────────
# 觸發詞「前方」要往回看多少字元。
# 刻意設得比往後找短很多:往回找本來就比較容易跨到別的句子,
# 距離放寬只會增加誤抓。實測 70 字元足以涵蓋
# "growth rate of 1.9%. This rate does not exceed the average long-term growth rate"
# 這類真實案例,又能擋掉跨句誤抓。
BACKWARD_WINDOW = 70
BACKWARD_MAX_GAP = 60


def _match_percent_backward(before: str):
    """
    往回找百分比。實測 C&D 年報時發現的必要功能:

        "...growth rate of 1.9%. This rate does not exceed the
         average long-term growth rate for the relevant markets."

    數字 1.9% 出現在觸發詞「long-term growth rate」的前面,
    只往後找永遠抓不到。

    取「最靠近觸發詞」的那一個(最後一個 match),距離太遠就放棄 ——
    測試時發現放寬距離會把前一句的 WACC 誤判成折現率。

    ⚠ 但不能撿「已經是某個區間上限」的數字。實測騰訊年報:

        Expected volatility (Note) 38% ~ 39% 36% ~ 37%
        Note: The expected volatility, measured as ...

    附註裡的「expected volatility」也是觸發詞,它後方沒有百分比,
    於是往回抓 —— 抓到的 37% 其實是**上年度比較欄的區間上限**,
    卻被記成一筆獨立的當年度參數。同一頁因此同時出現 38~39 與 37,
    無法分辨年度。這種重複計入會直接污染參數庫,所以要擋掉。
    """
    matches = list(_PCT_RE.finditer(before))
    if not matches:
        return None
    m = matches[-1]
    gap = len(before) - m.end()
    if gap > BACKWARD_MAX_GAP:
        return None

    # 這個百分比是不是某個區間的上限?是的話代表它已經被前面的
    # 區間比對涵蓋(或屬於比較年度欄),不該再當成獨立的點估計。
    head = before[:m.start()]
    if _RANGE_TAIL_RE.search(head):
        return None

    v = float(m.group(1))
    return v, v, m.group(0), "backward", gap


# ── 數值性質(上限/下限/區間)───────────────────────────
# 年報常寫「a pre-tax discount rate of not more than 22%」、
# 「terminal growth rate of generally not more than 5%」。
# 這是**上限**,不是採用值。實測騰訊 p.216 兩個參數都是這種寫法,
# 但底稿記成 Low = High,讀起來像確定假設。
_CAP_WORDS = re.compile(
    r"(not\s+more\s+than|no\s+more\s+than|not\s+exceed(?:ing)?|"
    r"up\s+to|maximum\s+of|at\s+most|capped\s+at|"
    r"不超過|不高於|最高|上限)", re.I)
_FLOOR_WORDS = re.compile(
    r"(not\s+less\s+than|at\s+least|minimum\s+of|"
    r"不低於|不少於|最低|下限)", re.I)


def _value_nature(before: str, window: str, is_range: bool) -> str:
    """
    判斷數值性質。只看觸發詞前後很近的文字 —— 距離放寬會把
    上一句的修飾語誤套到這一筆上。
    """
    if is_range:
        return "區間"
    near = (before[-70:] if before else "") + " " + window[:40]
    if _CAP_WORDS.search(near):
        return "上限"
    if _FLOOR_WORDS.search(near):
        return "下限"
    return "點估計"


def _plausible(param: str, v: float) -> bool:
    """
    合理性檢查 —— 防止抓到不相干的百分比(例如持股比例 51%)。
    這種 sanity check 是 AI 常常做不好、但規則層很擅長的事。
    """
    bounds = {
        "Discount Rate": (2, 40),
        "WACC": (2, 30),
        "Terminal Growth Rate": (0, 8),
        "Capitalisation Rate": (0.5, 15),
        "Expected Volatility": (5, 120),
        "Risk-free Rate": (0, 10),
        "Gross Margin": (0, 100),
    }
    lo, hi = bounds.get(param, (0, 100))
    return lo <= v <= hi


# ── 年增率欄位誤判(實測騰訊年報時發現)────────────────────
# MD&A 的分部表格排版是:
#     Gross profit  Gross margin
#     2024      2023   change   2024  2023
#     181,657 161,919    12%     57%   54%
# 攤平成一行之後是「VAS 181,657 161,919 12% 57% 54%」。
# 觸發詞「gross margin」後方的第一個百分比是 **change 欄**,不是毛利率
# —— 實測把 12% 和 19% 記成了毛利率。
#
# 這裡選擇**直接剔除**而不是改抓第二個百分比:欄位順序在不同公司、
# 不同排版下並不保證一致,猜錯就是把錯的數字寫進參數庫。
# 依照本專案一貫原則:寧可漏抓,不可錯抓 —— 漏抓會列進待覆核,
# 錯抓則會被當成可用資料。
_TRAILING_PCTS = re.compile(r"\s*(?:\d{1,3}(?:\.\d{1,2})?)\s*(?:%|％)")
_BIG_NUMS_BEFORE = re.compile(
    r"\d{1,3}(?:,\d{3})+\s+\(?\d{1,3}(?:,\d{3})+\)?\s*$")


def _looks_like_change_column(window: str, raw: str) -> bool:
    """
    判斷抓到的百分比是不是表格裡的「年增率 / 環比」欄。

    同時要滿足兩個條件才判定為 change 欄,避免誤殺正常的單一百分比:
      1. 這個百分比**前面**緊接著兩個帶千分位的大額數字(本年、上年金額)
      2. 這個百分比**後面**還連續跟著兩個以上的百分比(本年、上年的比率)

    以 `VAS 181,657 161,919 12% 57% 54%` 為例:12% 兩個條件都成立;
    而 57% 後面只剩一個百分比,不會被誤殺。
    """
    idx = window.find(raw)
    if idx < 0:
        return False
    before = window[:idx]
    if not _BIG_NUMS_BEFORE.search(before):
        return False
    after = window[idx + len(raw):]
    n = 0
    pos = 0
    while n < 2:
        m = _TRAILING_PCTS.match(after, pos)
        if not m:
            break
        pos = m.end()
        n += 1
    return n >= 2


def scan_valuation_params(pages: List[Page]) -> List[ParamHit]:
    results: List[ParamHit] = []

    for page in pages:
        if not page.text:
            continue
        flat = _clean(page.text)
        low = flat.lower()

        for param, cfg in VALUATION_PARAMS.items():
            for trig in cfg["triggers"]:
                for m in re.finditer(re.escape(trig.lower()), low):
                    window = flat[m.end(): m.end() + PARAM_WINDOW]

                    lo_v = hi_v = raw = conf = None

                    # 優先處理並列句型(「A 和 B 分別為 X 和 Y」)。
                    # 這種句型下,單純往後抓第一個百分比一定是錯的。
                    if "respectively" in window.lower() or "分別" in window:
                        sent, rel = _sentence_around(flat, m.start())
                        res = _resolve_respectively(sent, rel, param)
                        if res:
                            lo_v, hi_v, raw = res
                            conf = "High"

                    # 一般情況:往後找
                    if lo_v is None:
                        matched = _match_percent(window)
                        if matched:
                            lo_v, hi_v, raw, how = matched
                            # 表格年增率欄誤判:剔除,不猜第二個百分比
                            if how == "percent" and _looks_like_change_column(window, raw):
                                continue
                            dist = window.find(raw.split()[-1]) if raw else 999
                            if how == "table":
                                conf = "Medium" if dist <= 60 else "Low"
                            else:
                                conf = ("High" if dist <= 40
                                        else "Medium" if dist <= 90 else "Low")

                    # 都沒有才往回看
                    if lo_v is None:
                        before = flat[max(0, m.start() - BACKWARD_WINDOW): m.start()]
                        back = _match_percent_backward(before)
                        if not back:
                            continue
                        lo_v, hi_v, raw, how, gap = back
                        conf = "Medium"

                    if not (_plausible(param, lo_v) and _plausible(param, hi_v)):
                        continue

                    ctx_start = max(0, m.start() - 80)
                    results.append(ParamHit(
                        parameter=param,
                        parameter_zh=cfg["zh"],
                        value_low=lo_v,
                        value_high=hi_v,
                        raw_text=raw,
                        page_index=page.index,
                        page_cite=page.cite,
                        context=flat[ctx_start: m.end() + PARAM_WINDOW],
                        confidence=conf,
                        nature=_value_nature(
                            flat[max(0, m.start() - 90): m.start()],
                            window,
                            is_range=(lo_v is not None and hi_v is not None
                                      and lo_v != hi_v),
                        ),
                    ))

    # 去重:同一頁、同一參數、同一數值只留信心度最高的一筆
    seen, dedup = {}, []
    order = {"High": 0, "Medium": 1, "Low": 2}
    for r in sorted(results, key=lambda x: order[x.confidence]):
        key = (r.parameter, r.page_index, r.value_low, r.value_high)
        if key not in seen:
            seen[key] = True
            dedup.append(r)
    return sorted(dedup, key=lambda x: (x.parameter, x.page_index))
