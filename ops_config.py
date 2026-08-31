# -*- coding: utf-8 -*-
"""
ops_config.py — 操作設定層 (Operational settings)

跟 config.py 的分界只有一條線:
**改了這個檔案,同一份 PDF 產出的 Excel 內容會不會不一樣?**

    會不一樣  → 放 config.py(科目別名、主題關鍵字、估值參數、擷取參數)
    不會      → 放這裡  (下載哪一類文件、錯誤紀錄怎麼寫)

為什麼要分開:增量處理會把「所有影響萃取結果的模組」原始碼一起雜湊,
當成「分析邏輯版本」。版本一變,全部既有結果視為過期並重新分析 ——
這是刻意的,補了科目別名就該讓舊結果失效。

但錯誤紀錄規則和下載文件類型**不影響任何一份 PDF 的萃取結果**。
它們原本跟科目別名擠在同一個 config.py 裡,結果變成:旺季調一次
錯誤訊息措辭,幾百份年報就白白重跑一次。所以把它們獨立出來,
並在 incremental.py 的 _EXCLUDE_EXACT 裡排除。

⚠ 往這個檔案加東西前先問一次那條分界線的問題。加錯邊的後果是
「改了萃取邏輯卻沿用舊結果」—— 使用者會拿到過期資料而毫無察覺,
正是整個專案最想防的那種安靜失敗。

config.py 會 re-export 這裡的名稱,所以既有的 config.DOC_TYPES、
config.ERROR_PATTERNS 等寫法都照常可用,不需要改其他檔案。
"""


# --------------------------------------------------------------------------
# 1. HKEXnews 下載文件類型 —— 「Headline Category and Document Type」下拉路徑
#
#    HKEXnews 的分類選單是巢狀的,不同類別深度不一樣:
#        Financial Statements/ESG Information → Annual Report          (兩層)
#        Circulars → Notifiable Transactions → Major Transaction       (三層)
#
#    path 就是從第一層(CATEGORY_LEVEL1_ITEM)到要點的最後一項,依序列出
#    畫面上看到的完整文字。hkexnews_selenium.py 會依序展開每一層、
#    最後一項用點擊選取 —— 不管深度多少,邏輯統一。
#
#    filename_tag 用來避免不同文件類型撞檔名:同一間公司同一天,
#    有可能同時有年報和一份通函(機率低但不是零),純用「代號+公司+日期」
#    當檔名會讓後選中的那份被誤判成「已下載過」而跳過,是會產生資料
#    遺漏的靜默失敗。annual_report 留空字串,是為了不改變既有使用者
#    downloads/ 資料夾裡已經下載好的檔名。
#
#    驗證狀態(2026/08/31 用 check_menu.py --all 實機確認):
#      七種類型的選單展開路徑全部驗證通過 —— 文字、巢狀層數都對得上
#      真實頁面。annual_report 額外驗證過完整下載流程(查詢→結果→存檔)。
#      其餘六種還沒驗證「按下 SEARCH 後讀到的結果筆數/內容是否正確」,
#      第一次用建議搭配 --show-browser 肉眼看一次搜尋結果再放心批次跑。
# --------------------------------------------------------------------------
DOC_TYPES = {
    "annual_report": {
        "zh": "年報",
        "path": ["Financial Statements/ESG Information", "Annual Report"],
        "filename_tag": "",
    },
    "interim_report": {
        "zh": "中期報告",
        "path": ["Financial Statements/ESG Information", "Interim/Half-Year Report"],
        "filename_tag": "INTERIM",
    },
    "esg_report": {
        "zh": "環境社會及管治報告",
        "path": ["Financial Statements/ESG Information",
                 "Environmental, Social and Governance Information/Report"],
        "filename_tag": "ESG",
    },
    # 以下四種是通函裡「須予公布交易」的子分類,規則上達到一定規模的
    # 資產收購/處置通常要附獨立估值師報告 —— 是估值參數 benchmark
    # 最直接的資料來源,價值高於從年報附註裡零散地撈。
    "major_transaction": {
        "zh": "主要交易通函",
        "path": ["Circulars", "Notifiable Transactions", "Major Transaction"],
        "filename_tag": "MT",
    },
    "very_substantial_acquisition": {
        "zh": "非常重大收購事項通函",
        "path": ["Circulars", "Notifiable Transactions", "Very Substantial Acquisition"],
        "filename_tag": "VSA",
    },
    "very_substantial_disposal": {
        "zh": "非常重大出售事項通函",
        "path": ["Circulars", "Notifiable Transactions", "Very Substantial Disposal"],
        "filename_tag": "VSD",
    },
    "reverse_takeover": {
        "zh": "反收購行動通函",
        "path": ["Circulars", "Notifiable Transactions", "Reverse Takeover"],
        "filename_tag": "RTO",
    },
}

DEFAULT_DOC_TYPE = "annual_report"


# --------------------------------------------------------------------------
# 2. 錯誤紀錄 —— 哪些狀況該被寫進 error message/ 資料夾
#
#    為什麼需要這個:批次跑幾十份時,警告訊息會被大量正常輸出淹沒,
#    而且有些「失敗」在畫面上長得像成功。例如 01007 那份通函,終端機
#    顯示「完成:1/1 份成功」「✓ 交叉驗證全部通過」,但實際上 0 個財務
#    科目、報表頁相距 39 頁。人只看最後一行會以為沒事。
#
#    ERROR_PATTERNS 是「什麼算有問題」的定義,放在設定檔而不是寫死在
#    程式裡 —— 跟科目別名一樣,將來要多抓一種狀況只要加一列。
#
#    pattern : 對照分析過程輸出文字的正則式
#    what    : 寫進紀錄的說明,可用 {群組名} 代入 pattern 抓到的內容;
#              若 pattern 有名為 items 的群組,額外可用 {n_items}
#              (以逗號分隔的項目數)
# --------------------------------------------------------------------------
ERROR_DIR = "error message"

# 三級嚴重度,決定紀錄檔裡的區塊順序與標題。
# "嚴重"永遠排最前面 —— 這幾種狀況代表數字可能是錯的,或整份等於白跑。
ERROR_SEVERITY_ORDER = ["high", "medium", "low"]
ERROR_SEVERITY_LABELS = {
    "high": "嚴重 — 數字可能有誤或整份等於沒抓到,請優先處理",
    "medium": "一般 — 結構性缺角,已抓到的數字未必受影響",
    "low": "輕微 — 多屬預期範圍內的落差(附註科目本來就不擷取等),通常不需逐筆處理",
}

ERROR_PATTERNS = [
    {
        "pattern": r"⚠\s*(?P<bad>\d+)\s*/\s*(?P<total>\d+)\s*項.*?未通過",
        "what": "會計恆等式交叉驗證 {bad}/{total} 項未通過,請對照來源頁人手確認",
        "severity": "high",
    },
    {
        "pattern": r"共擷取\s*0\s*個財務科目",
        "what": "完全沒有擷取到財務科目(這份文件可能不是財務報表類文件)",
        "severity": "high",
    },
    {
        "pattern": r"找不到「(?P<name>[^」]+)」的頁面",
        "what": "找不到報表頁:{name}",
        "severity": "medium",
    },
    {
        "pattern": r"(?P<stmt>[^\s:]+):\s*PDF p\.\d+\s*\(年度欄\s*未偵測\)",
        "what": "{stmt} 的年度欄未偵測到,本年/上年可能對不上",
        "severity": "medium",
    },
    {
        "pattern": r"(?P<stmt>[^\s:]+)\s*未擷取:\s*(?P<items>.+)",
        "what": "{stmt} 有 {n_items} 個科目未擷取",
        "severity": "low",
    },
    {
        "pattern": r"可能需要 OCR 的頁數:\s*(?P<n>[1-9]\d*)",
        "what": "有 {n} 頁疑似掃描頁,需另接 OCR 才能處理",
        "severity": "low",
    },
    {
        "pattern": r"估值參數\s*0\s*筆",
        "what": "沒有擷取到任何估值參數",
        "severity": "low",
    },
]
