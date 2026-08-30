# -*- coding: utf-8 -*-
"""
inspect_html.py — 第三階段:直接印出關鍵容器的內部 HTML

前兩輪用「找元素」的方式探測,但自訂下拉點開後選項沒進 DOM,
表示點擊沒真的展開。這輪改用最直接的方法:把整個容器的 innerHTML
印出來,一眼就能看到真實的巢狀結構跟 class 命名。

用法:
    python3 inspect_html.py
"""

import time
import re
import traceback


def main():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By

    opts = Options()
    opts.add_argument("--window-size=1400,1000")
    driver = webdriver.Chrome(options=opts)

    lines = []

    def out(s=""):
        print(s)
        lines.append(str(s))

    def pretty(html, max_len=6000):
        """把 HTML 稍微整理一下方便閱讀"""
        html = re.sub(r">\s*<", ">\n<", html)
        html = re.sub(r"\n{2,}", "\n", html)
        return html[:max_len]

    def dump_html(css, label):
        out("=" * 70)
        out(label)
        out("=" * 70)
        try:
            el = driver.find_element(By.CSS_SELECTOR, css)
            out(pretty(el.get_attribute("outerHTML")))
        except Exception as e:
            out(f"找不到 {css}: {e}")
        out()

    try:
        driver.get("https://www1.hkexnews.hk/search/titlesearch.xhtml")
        time.sleep(4)

        # ── 1. 文件類型下拉容器(收合狀態)──────────────────
        dump_html("li.searchDocType", "1. 文件類型容器 searchDocType(收合狀態)")

        # ── 2. 嘗試多種方式點開下拉 ────────────────────────
        out("=" * 70)
        out("2. 嘗試點開下拉(測試多個候選元素)")
        out("=" * 70)
        candidates = [
            "li.searchDocType div.tier1-wrap",
            "li.searchDocType .combobox-group",
            "li.searchDocType [class*='combobox']",
            "li.searchDocType div",
            "div.tier1-wrap",
        ]
        opened = False
        for css in candidates:
            try:
                el = driver.find_element(By.CSS_SELECTOR, css)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.4)
                driver.execute_script("arguments[0].click();", el)
                time.sleep(1.8)
                # 檢查是否有新的可見元素出現
                vis = driver.find_elements(
                    By.XPATH, "//*[contains(text(),'Annual Report')]")
                vis = [v for v in vis if v.is_displayed()]
                out(f"  點擊 {css!r} → 可見的 'Annual Report' 元素數: {len(vis)}")
                if vis:
                    out(f"  ✓ 成功展開!")
                    opened = True
                    break
            except Exception as e:
                out(f"  點擊 {css!r} 失敗: {str(e)[:80]}")

        if not opened:
            out("  ⚠ 所有候選都沒展開,可能需要真人滑鼠 hover 事件")

        out()
        # ── 3. 展開後再看一次容器 HTML ────────────────────
        dump_html("li.searchDocType", "3. 文件類型容器(嘗試展開後)")

        # ── 4. 全頁搜尋 Annual Report 的所在位置 ───────────
        out("=" * 70)
        out("4. 全頁所有 'Annual Report' 元素(含隱藏)")
        out("=" * 70)
        try:
            els = driver.find_elements(
                By.XPATH, "//*[contains(text(),'Annual Report')]")
            out(f"共找到 {len(els)} 個")
            for i, el in enumerate(els[:10], 1):
                out(f"[{i}] tag={el.tag_name} displayed={el.is_displayed()}")
                out(f"    class={el.get_attribute('class')!r}")
                out(f"    outerHTML={el.get_attribute('outerHTML')[:200]!r}")
                # 印出父元素,看它在什麼結構裡
                try:
                    parent = el.find_element(By.XPATH, "..")
                    out(f"    父元素 tag={parent.tag_name} class={parent.get_attribute('class')!r}")
                except Exception:
                    pass
                out()
        except Exception as e:
            out(f"搜尋失敗: {e}")

        # ── 5. autocomplete 結構(已知會出現)──────────────
        out("=" * 70)
        out("5. 股票代號 autocomplete 結構")
        out("=" * 70)
        try:
            box = driver.find_element(By.ID, "searchStockCode")
            box.clear()
            box.send_keys("00700")
            time.sleep(2.5)
            container = driver.find_element(By.CSS_SELECTOR, "li.searchStockCodeName")
            out(pretty(container.get_attribute("outerHTML"), 4000))
        except Exception as e:
            out(f"失敗: {e}")
        out()

        with open("html_structure.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out("=" * 70)
        out("已存檔: html_structure.txt — 請把這個檔案上傳給 Claude")
        out("=" * 70)

        input("\n瀏覽器保持開啟。建議你現在手動操作一次:\n"
              "  點開 Headline Category 下拉 → 選 Annual Report → 按 SEARCH\n"
              "看看真人操作要幾個步驟,然後告訴 Claude。按 Enter 關閉...")

    except Exception:
        traceback.print_exc()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
