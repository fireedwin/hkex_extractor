# -*- coding: utf-8 -*-
"""
⚠️ 已棄用 (DEPRECATED) —— 請改用 hkexnews_selenium.py

這個模組假設 HKEXnews 有一個可以直接呼叫的 JSON API。
實測證實**沒有**:該網站是 JSF 動態頁面,查詢邏輯靠瀏覽器執行
JavaScript,沒有公開端點。

更糟的是它失敗時不會報錯,而是回傳空白結果:

    [hkexnews] 找到 1 筆
       -   |  |          ← 每個欄位都是空的

這種「安靜的失敗」比直接當掉危險得多。保留這個檔案只是為了
記錄當初的技術調查過程,程式已不再匯入它。

正確做法:
    python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231
"""

raise ImportError(
    "hkexnews.py 已棄用(HKEXnews 沒有公開 API)。"
    "請改用 pipeline.py --stocks,它使用 hkexnews_selenium.py。")

# ---------------------------------------------------------------------
# 以下為原始實作,僅供參考,不會被執行
# ---------------------------------------------------------------------
import os
import re
import json
import time
import requests
from typing import List, Dict, Optional

BASE = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE}/search/titleSearchServlet.do"
PREFIX_URL = f"{BASE}/search/prefix.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ValuationResearchBot/1.0)",
    "Referer": f"{BASE}/search/titlesearch.xhtml",
}

DOC_TYPES = {
    "annual_report":   "40100",
    "interim_report":  "40200",
    "quarterly_report": "40300",
    "listing_document": "30000",
}


def lookup_stock_id(stock_code: str, lang: str = "EN") -> Optional[str]:
    """把股票代號 (如 '00700') 轉成 HKEXnews 內部 stockId。"""
    code = stock_code.zfill(5)
    r = requests.get(PREFIX_URL, params={
        "callback": "c", "lang": lang, "type": "A",
        "name": code, "market": "SEHK",
    }, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r"\{.*\}", r.text, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    for item in data.get("stockInfo", []):
        if item.get("code") == code:
            return str(item.get("stockId"))
    return None


def search(from_date: str, to_date: str,
           doc_type: str = "annual_report",
           stock_code: Optional[str] = None,
           max_rows: int = 100,
           lang: str = "EN") -> List[Dict]:
    """
    搜尋指定日期區間的文件。日期格式 'YYYYMMDD'。
    stock_code 留空 = 搜尋全市場(注意結果可能很多)。
    """
    stock_id = "-1"
    if stock_code:
        stock_id = lookup_stock_id(stock_code, lang) or "-1"

    params = {
        "sortDir": "0", "sortByOptions": "DateTime",
        "category": "0", "market": "SEHK",
        "stockId": stock_id, "documentType": "-1",
        "fromDate": from_date, "toDate": to_date,
        "title": "", "searchType": "1",
        "t1code": "40000",
        "t2Gcode": "-2",
        "t2code": DOC_TYPES.get(doc_type, "40100"),
        "rowRange": str(max_rows),
        "lang": lang,
    }
    r = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()

    payload = r.json()
    body = payload.get("result", payload)
    if isinstance(body, str):
        body = json.loads(body)

    out = []
    for item in body if isinstance(body, list) else body.get("result", []):
        link = item.get("fileLink") or ""
        out.append({
            "stock_code": item.get("stockCode", ""),
            "company": item.get("stockName", ""),
            "title": item.get("title", ""),
            "date": item.get("dateTime", ""),
            "size": item.get("fileInfo", ""),
            "url": link if link.startswith("http") else BASE + link,
        })
    return out


def download(records: List[Dict], out_dir: str = "downloads",
             delay: float = 1.5, verbose: bool = True) -> List[str]:
    """下載搜尋結果中的 PDF,回傳本機路徑清單。"""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, rec in enumerate(records, 1):
        url = rec["url"]
        if not url.lower().endswith(".pdf"):
            continue
        safe = re.sub(r"[^\w\-]+", "_", f"{rec['stock_code']}_{rec['company']}")[:60]
        path = os.path.join(out_dir, f"{safe}_{rec['date'][:10].replace('/','')}.pdf")

        if os.path.exists(path):
            if verbose:
                print(f"[hkexnews] ({i}/{len(records)}) 已存在,略過 {path}")
            paths.append(path)
            continue

        if verbose:
            print(f"[hkexnews] ({i}/{len(records)}) 下載 {rec['company']} — {rec['size']}")
        try:
            with requests.get(url, headers=HEADERS, timeout=180, stream=True) as resp:
                resp.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(1 << 16):
                        f.write(chunk)
            paths.append(path)
        except Exception as e:
            print(f"[hkexnews]   下載失敗: {e}")
        time.sleep(delay)   # 禮貌性延遲,避免對伺服器造成壓力
    return paths
