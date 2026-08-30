# -*- coding: utf-8 -*-
"""
config.py — 領域知識層 (Domain knowledge layer)

這個檔案是整個工具最重要的部分。它不是程式技巧,而是「估值師知道要找什麼」。
把估值分析師的專業判斷,編碼成機器可以重複執行的規則。

三個層次:
  1. TOPICS          — 主題式段落抓取 (功能B):無形資產 / ESG / 研發 ...
  2. VALUATION_PARAMS— 估值參數抓取:折現率 / WACC / 資本化率 ...  ← 最高價值
  3. FIN_LINE_ITEMS  — 三大財務報表科目 (功能D)
"""

# --------------------------------------------------------------------------
# 1. 主題關鍵字 — 用來把 400 頁縮減成 10-20 頁的候選段落
#    每個主題含中英文,因為港交所文件常見中英對照版本
# --------------------------------------------------------------------------
TOPICS = {
    "Intangible Assets & Goodwill": {
        "zh": "無形資產及商譽",
        "terms": [
            "intangible asset", "goodwill", "amortisation", "amortization",
            "useful life", "customer relationship", "brand name", "trademark",
            "licence", "patent", "development cost",
            "無形資產", "商譽", "攤銷", "可使用年期", "客戶關係", "商標", "專利",
        ],
        # 這些主題特別重要,面試時可強調:商譽減值測試是估值行的核心業務來源
        "priority": "high",
    },
    "Impairment Testing": {
        "zh": "減值測試",
        "terms": [
            "impairment test", "impairment loss", "recoverable amount",
            "value in use", "cash-generating unit", "CGU", "fair value less costs",
            "減值測試", "減值虧損", "可收回金額", "使用價值", "現金產生單位",
        ],
        "priority": "high",
    },
    "Fair Value Measurement": {
        "zh": "公允價值計量",
        "terms": [
            "fair value hierarchy", "level 1", "level 2", "level 3",
            "unobservable input", "valuation technique", "market approach",
            "income approach", "cost approach", "independent valuer",
            "公允價值", "第三級", "估值技術", "不可觀察輸入值", "獨立估值師",
        ],
        "priority": "high",
    },
    "Investment Properties": {
        "zh": "投資物業",
        "terms": [
            "investment property", "capitalisation rate", "capitalization rate",
            "rental yield", "market rent", "reversionary", "gross floor area",
            "投資物業", "資本化率", "租金回報", "市值租金", "建築面積",
        ],
        "priority": "high",
    },
    "R&D Expenditure": {
        "zh": "研發開支",
        "terms": [
            "research and development", "R&D expense", "R&D expenditure",
            "capitalised development", "研發", "研究及開發", "開發成本",
        ],
        "priority": "medium",
    },
    "Share-based Payment": {
        "zh": "以股份為基礎的付款",
        "terms": [
            "share-based payment", "share option", "expected volatility",
            "risk-free rate", "binomial model", "black-scholes",
            "以股份為基礎", "購股權", "預期波幅", "無風險利率",
        ],
        "priority": "medium",
    },
    "Segment Information": {
        "zh": "分部資料",
        "terms": [
            "segment information", "reportable segment", "operating segment",
            "geographical", "分部資料", "呈報分部", "經營分部",
        ],
        "priority": "medium",
    },
    "ESG Data": {
        "zh": "環境社會及管治數據",
        "terms": [
            "greenhouse gas", "GHG emission", "scope 1", "scope 2", "scope 3",
            "carbon", "energy consumption", "ESG", "sustainability",
            "溫室氣體", "碳排放", "能源消耗", "環境、社會及管治", "可持續",
        ],
        "priority": "medium",
    },
    "Related Party Transactions": {
        "zh": "關聯方交易",
        "terms": [
            "related party", "connected transaction", "關連交易", "關聯方",
        ],
        "priority": "low",
    },
}


# --------------------------------------------------------------------------
# 2. 估值參數 — 這是給估值行「建立 benchmark 資料庫」用的
#
#    邏輯:先找到觸發詞,再在其後 N 個字元內抓百分比數字。
#    這比讓 AI 通讀全文可靠得多,因為數字是用正則精確抓出來的,不會被「幻覺」。
# --------------------------------------------------------------------------
VALUATION_PARAMS = {
    "Discount Rate": {
        "zh": "折現率",
        "triggers": [
            "discount rate", "pre-tax discount rate", "post-tax discount rate",
            "折現率", "貼現率",
        ],
        "unit": "%",
    },
    "WACC": {
        "zh": "加權平均資本成本",
        "triggers": [
            "weighted average cost of capital", "WACC", "加權平均資本成本",
        ],
        "unit": "%",
    },
    "Terminal Growth Rate": {
        "zh": "永續增長率",
        "triggers": [
            "terminal growth", "long-term growth rate", "perpetual growth",
            "growth rate beyond", "永續增長", "長期增長率",
        ],
        "unit": "%",
    },
    "Capitalisation Rate": {
        "zh": "資本化率",
        "triggers": [
            "capitalisation rate", "capitalization rate", "cap rate",
            "資本化率", "還原率",
        ],
        "unit": "%",
    },
    "Expected Volatility": {
        "zh": "預期波幅",
        "triggers": ["expected volatility", "預期波幅", "預期波動率"],
        "unit": "%",
    },
    "Risk-free Rate": {
        "zh": "無風險利率",
        "triggers": ["risk-free rate", "risk free rate", "無風險利率"],
        "unit": "%",
    },
    "Gross Margin": {
        "zh": "毛利率",
        "triggers": ["gross profit margin", "gross margin", "毛利率"],
        "unit": "%",
    },
}

# 觸發詞後方要掃描多少字元來找數字
PARAM_WINDOW = 160


# --------------------------------------------------------------------------
# 3. 財務報表科目 (功能D)
#    key = 標準化科目名;value = 在年報中可能出現的寫法 (由長到短排序很重要,
#    否則 "Revenue" 會先match到 "Revenue from contracts with customers")
# --------------------------------------------------------------------------
_RAW_FIN_STATEMENTS = {
    "Income Statement": {
        "zh": "綜合損益表",
        "page_anchors": [
            "consolidated statement of profit or loss",
            "consolidated income statement",
            "statement of profit or loss and other comprehensive income",
            "綜合損益表", "綜合收益表",
        ],
        "line_items": {
            "Revenue": ["revenue from contracts with customers", "total revenues", "revenues",
                        "revenue", "turnover", "收入", "營業額"],
            "Cost of Sales": ["cost of revenues", "cost of sales", "cost of revenue", "銷售成本"],
            # 虧損年度會寫「Gross loss」而不是「Gross profit」。
            # 估值案件常常正是虧損公司,漏掉這個影響很大。
            "Gross Profit": ["gross profit/(loss)", "gross (loss)/profit",
                             "gross profit", "gross loss", "毛利", "毛損"],
            "Operating Profit": ["operating profit", "profit from operations", "經營溢利"],
            "Finance Costs": ["finance costs", "finance cost", "融資成本"],
            "Profit Before Tax": ["profit before income tax", "profit before tax",
                                  "profit before taxation", "除稅前溢利"],
            "Income Tax": ["income tax expense", "income tax", "所得稅開支"],
            "Profit for the Year": ["profit for the year", "profit for the period", "年內溢利"],
            "R&D Expenses": ["research and development expenses", "research and development costs", "研發開支"],
            "Depreciation": ["depreciation", "折舊"],
            "Amortisation": ["amortisation", "amortization", "攤銷"],
        },
    },
    "Balance Sheet": {
        "zh": "資產負債表",
        "page_anchors": [
            "consolidated statement of financial position",
            "consolidated balance sheet",
            "綜合財務狀況表", "綜合資產負債表",
        ],
        "line_items": {
            "Total Assets": ["total assets", "資產總值", "總資產"],
            "Total Current Assets": ["total current assets", "流動資產總值"],
            "Cash and Equivalents": ["cash and cash equivalents", "現金及現金等價物"],
            "Inventories": ["inventories", "存貨"],
            "Trade Receivables": ["accounts receivable", "trade and other receivables",
                                  "trade receivables", "應收賬款"],
            "Goodwill": ["goodwill", "商譽"],
            "Intangible Assets": ["intangible assets", "無形資產"],
            "Investment Properties": ["investment properties", "投資物業"],
            "Property Plant and Equipment": ["property, plant and equipment", "物業、廠房及設備"],
            "Total Liabilities": ["total liabilities", "負債總值", "總負債"],
            "Total Current Liabilities": ["total current liabilities", "流動負債總值"],
            "Borrowings": ["bank borrowings", "borrowings", "銀行借款"],
            "Total Equity": ["total equity", "權益總額", "總權益"],
        },
        # 有些公司(如騰訊)不印「Total current assets」,小計是裸數字行。
        # 這裡定義區段標題與停止點,讓工具能從區段結構推出小計。
        "section_subtotals": {
            # stop 必須列出「下一個區段的完整標題」。
            # 只寫 "liabilities" 是不夠的 —— "CURRENT LIABILITIES" 並非
            # 以 "liabilities" 開頭,掃描不會停,結果會一路掃到負債區段,
            # 把流動負債的小計當成流動資產(兩者拿到相同數字)。
            "Total Current Assets": {
                "header": ["current assets", "流動資產"],
                "stop": ["current liabilities", "net current", "total assets",
                         "non-current liabilities", "equity", "total equity",
                         "流動負債", "資產淨值", "總資產", "權益"],
            },
            "Total Current Liabilities": {
                "header": ["current liabilities", "流動負債"],
                "stop": ["net current", "total assets", "non-current",
                         "total equity", "equity", "net assets",
                         "資產淨值", "總資產", "權益總額", "非流動"],
            },
        },
    },
    "Cash Flow": {
        "zh": "現金流量表",
        "page_anchors": [
            "consolidated statement of cash flows",
            "consolidated cash flow statement",
            "綜合現金流量表",
        ],
        "line_items": {
            # 注意順序無關,程式會取「最長=最精確」的別名。
            # 騰訊寫「Net cash flows generated from...」比「Cash generated
            # from operations」精確,兩者差 460 億且概念不同(後者未扣利息稅項)。
            "Operating Cash Flow": ["net cash flows generated from operating activities",
                                    "net cash flows from operating activities",
                                    "net cash generated from operating activities",
                                    "net cash from operating activities",
                                    "cash generated from operations",
                                    "經營活動所得現金淨額"],
            "Investing Cash Flow": ["net cash used in investing activities",
                                    "net cash flows used in investing activities",
                                    "net cash generated from investing activities",
                                    "投資活動所用現金淨額"],
            "Financing Cash Flow": ["net cash used in financing activities",
                                    "net cash flows used in financing activities",
                                    "net cash from financing activities",
                                    "融資活動所得現金淨額"],
            "Capital Expenditure": ["purchase of/prepayments for property, plant and equipment",
                                    "purchase of property, plant and equipment",
                                    "payments for property, plant and equipment",
                                    "購買物業、廠房及設備"],
        },
    },
}

import re


def _add_profit_loss_variants(statements: dict) -> dict:
    """
    虧損年度會把「Profit」全部換成「Loss」,而且不是「Profit/(Loss)」
    這種括號插語(那個已經在 scanner 的 _strip_alternatives 處理過),
    是整個字直接換掉,例如:

        OPERATING PROFIT    → OPERATING LOSS
        Profit before tax   → Loss before tax
        Profit for the year → Loss for the year

    實測 CHINA HEALTH 年報(2025 年度轉虧)踩到這個問題,
    Operating Profit / Profit Before Tax / Profit for the Year 三項全部漏抓。

    與其每個科目手動加一次「loss」版本、下次換一間公司又要再補,
    不如在設定檔載入時自動幫每個含 profit/loss 的別名生成對應版本。
    這樣往後任何虧損公司都能直接受益,不用逐一維護。
    """
    for stmt in statements.values():
        for item, aliases in stmt["line_items"].items():
            extra = []
            for a in aliases:
                low = a.lower()
                if "profit" in low and not re.search(r"\bloss\b", low):
                    extra.append(low.replace("profit", "loss"))
                elif re.search(r"\bloss\b", low) and "profit" not in low:
                    extra.append(re.sub(r"\bloss\b", "profit", low))
            for e in extra:
                if e not in [x.lower() for x in aliases]:
                    aliases.append(e)
    return statements


FIN_STATEMENTS = _add_profit_loss_variants(_RAW_FIN_STATEMENTS)


# --------------------------------------------------------------------------
# 4. 一般設定
# --------------------------------------------------------------------------
SETTINGS = {
    # 抓到關鍵字後,前後各取多少字元作為 context snippet
    "snippet_chars": 400,
    # 一個主題最多輸出多少段落 (避免 Excel 爆量)
    "max_hits_per_topic": 40,
    # AI 複核層:每次送給模型的最大頁數
    "ai_max_pages": 12,
}
