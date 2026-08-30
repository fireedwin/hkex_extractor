# -*- coding: utf-8 -*-
"""
inspect_dropdown.py — 第二階段探測:自訂 div 下拉元件的選項結構

第一階段(inspect_page.py)發現 HKEXnews 頁面上沒有標準 <select>,
三個下拉全部是自訂的 div 元件。這種元件的選項清單通常「點開才會出現在 DOM」,
所以需要模擬點擊後再抓一次。

這個腳本會:
  1. 點開「Headline Category and Document Type」下拉
  2. 把展開後出現的所有選項印出來(找出「年報 Annual Report」在哪一層)
  3. 順便測試股票代號輸入後會不會跳 autocomplete 建議清單

用法:
    python3 inspect_dropdown.py
"""

import time
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

    def dump_visible(css, label, limit=60):
        """把符合條件且可見的元素印出來"""
        out(f"--- {label} (selector: {css}) ---")
        els = driver.find_elements(By.CSS_SELECTOR, css)
        shown = 0
        for el in els:
            try:
                if not el.is_displayed():
                    continue
                txt = (el.text or "").strip()
                if not txt:
                    continue
                out(f"  id={el.get_attribute('id')!r} "
                    f"class={el.get_attribute('class')!r}")
                out(f"    text={txt[:80]!r}")
                shown += 1
                if shown >= limit:
                    out("  ...(超過上限,截斷)")
                    break
            except Exception:
                pass
        if shown == 0:
            out("  (沒有可見元素)")
        out()

    try:
        driver.get("https://www1.hkexnews.hk/search/titlesearch.xhtml")
        time.sleep(4)

        # ============================================================
        out("=" * 70)
        out("步驟 1:點開 Headline Category 下拉(tier1-wrap)")
        out("=" * 70)
        try:
            tier1 = driver.find_element(By.CSS_SELECTOR, "div.tier1-wrap")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tier1)
            time.sleep(0.5)
            tier1.click()
            time.sleep(2)
            out("✓ 已點擊 tier1-wrap")
        except Exception as e:
            out(f"✗ 點擊失敗: {e}")

        dump_visible("li", "點開後出現的所有 <li> 選項")
        dump_visible("div.tier1-wrap ul li", "tier1-wrap 內的 li")
        dump_visible("[class*='droplist'] li", "droplist 類別內的 li")
        dump_visible("[class*='dropdown'] li", "dropdown 類別內的 li")

        # ============================================================
        out("=" * 70)
        out("步驟 2:整頁 HTML 中搜尋 'Annual Report' 出現在什麼元素裡")
        out("=" * 70)
        try:
            els = driver.find_elements(
                By.XPATH, "//*[contains(text(),'Annual Report')]")
            if not els:
                out("  找不到 'Annual Report' 文字,可能要先選第一層分類")
            for el in els[:20]:
                out(f"  tag={el.tag_name} id={el.get_attribute('id')!r}")
                out(f"    class={el.get_attribute('class')!r}")
                out(f"    text={(el.text or '')[:60]!r}")
                out(f"    displayed={el.is_displayed()}")
                out()
        except Exception as e:
            out(f"  搜尋失敗: {e}")

        # ============================================================
        out("=" * 70)
        out("步驟 3:測試股票代號輸入是否跳 autocomplete")
        out("=" * 70)
        try:
            box = driver.find_element(By.ID, "searchStockCode")
            box.clear()
            box.send_keys("00700")
            time.sleep(2.5)
            out("✓ 已輸入 00700")
        except Exception as e:
            out(f"✗ 輸入失敗: {e}")

        dump_visible("[class*='autocomplete'] li", "autocomplete 建議清單", limit=10)
        dump_visible("[class*='suggest'] li", "suggest 建議清單", limit=10)
        dump_visible("ul li", "輸入後所有可見的 li", limit=15)

        # ============================================================
        out("=" * 70)
        out("步驟 4:Search Type 下拉(selectedCategory)的選項")
        out("=" * 70)
        try:
            sc = driver.find_element(By.ID, "selectedCategory")
            sc.click()
            time.sleep(1.5)
            out("✓ 已點開 selectedCategory")
        except Exception as e:
            out(f"✗ 點擊失敗: {e}")
        dump_visible("#selectedCategory li", "selectedCategory 內的選項", limit=10)

        with open("dropdown_structure.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out("=" * 70)
        out("已存檔: dropdown_structure.txt — 請把內容貼給 Claude")
        out("=" * 70)

        input("\n瀏覽器保持開啟,你可以自己手動操作看看。按 Enter 關閉...")

    except Exception:
        traceback.print_exc()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
