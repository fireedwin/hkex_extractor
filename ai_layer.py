# -*- coding: utf-8 -*-
"""
ai_layer.py — AI 語意層(第二道)

這一層的定位很重要,面試時要講清楚:

  規則層負責「找」,AI 負責「讀懂」。

  規則層抓到 "discount rate" 附近有 "12.5%",但它不知道這是
  商譽減值測試用的折現率,還是租賃負債的增量借款利率。
  AI 讀那一段就分得出來。

三個防止幻覺的設計:
  1. 只餵規則層篩出的少數頁(通常 10-20 頁),不是整份文件
  2. 每一段都標上頁碼一起送進去,要求模型在輸出中回填頁碼
  3. 要求嚴格 JSON,且明確指示「找不到就回 not_found,不要推測」

即使沒有 API key,整個工具仍能完整運作 —— AI 是加分項,不是單點故障。
"""

import os
import json
import urllib.request
from typing import List, Dict

from config import SETTINGS
from pdf_reader import Page

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a data extraction assistant for a business valuation firm.

You will receive excerpts from a Hong Kong listed company's annual report.
Each excerpt is tagged with its PDF page number.

Extract ONLY the following, and ONLY if explicitly stated in the text provided:
- valuation parameters (discount rate, WACC, terminal growth rate, capitalisation rate)
- what each parameter was used for (e.g. "goodwill impairment test of CGU X")
- intangible asset classes and their useful lives
- R&D expenditure figures
- ESG quantitative metrics (GHG emissions, energy consumption) with units

CRITICAL RULES:
- Never infer, estimate, or calculate a number that is not written in the text.
- If a field is not present, use the string "not_found".
- Every extracted item MUST include the page number it came from.
- Respond with raw JSON only. No markdown fences, no commentary.

Schema:
{"findings":[{"category":"...","item":"...","value":"...","unit":"...",
"used_for":"...","page":<int>,"verbatim":"<short quote, max 15 words>"}]}
"""


def _call_api(prompt: str, api_key: str, timeout: int = 120) -> str:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 4000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")


def refine(pages: List[Page], page_indices: List[int],
           verbose: bool = True) -> List[Dict]:
    """
    對規則層篩出的頁面做 AI 語意擷取。
    沒有 API key 時回傳空清單,不影響主流程。
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        if verbose:
            print("[ai_layer] 未設定 ANTHROPIC_API_KEY,略過 AI 複核層。"
                  "(規則層結果不受影響)")
        return []

    if not page_indices:
        return []

    page_map = {p.index: p for p in pages}
    selected = page_indices[: SETTINGS["ai_max_pages"]]
    if verbose:
        print(f"[ai_layer] 規則層把 {len(pages)} 頁縮減到 {len(selected)} 頁 "
              f"送交 AI 複核: {selected}")

    chunks = []
    for i in selected:
        p = page_map.get(i)
        if p and p.text:
            chunks.append(f"<page number=\"{i}\">\n{p.text[:4000]}\n</page>")

    prompt = ("Extract the required data from these annual report pages.\n\n"
              + "\n\n".join(chunks))

    try:
        raw = _call_api(prompt, key)
    except Exception as e:
        print(f"[ai_layer] API 呼叫失敗: {e} — 略過 AI 層")
        return []

    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print("[ai_layer] 模型回傳非合法 JSON,略過")
        return []

    findings = parsed.get("findings", [])

    # 驗證:模型宣稱的頁碼必須真的在我們送出的頁面裡,否則丟棄。
    # 這是最後一道防幻覺的閘門。
    clean = []
    for f in findings:
        try:
            pg = int(f.get("page", -1))
        except (TypeError, ValueError):
            continue
        if pg in selected:
            f["_verified_page"] = True
            clean.append(f)
    if verbose:
        print(f"[ai_layer] AI 回傳 {len(findings)} 筆,通過頁碼驗證 {len(clean)} 筆")
    return clean
