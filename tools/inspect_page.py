# -*- coding: utf-8 -*-
"""
inspect_page.py — 自動探測 HKEXnews 搜尋頁的真實元素結構

不用你手動一個一個按 F12 找,這個腳本會把頁面上所有輸入框、下拉選單、
按鈕的 id / name / class / placeholder 全部印出來,並存成 page_structure.txt。

用法:
    python3 inspect_page.py

跑完把印出來的內容(或 page_structure.txt 的內容)貼給 Claude,
就能一次把 SELECTORS 全部校正到正確。
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

    try:
        driver.get("https://www1.hkexnews.hk/search/titlesearch.xhtml")
        time.sleep(4)   # 等 JS 完全渲染

        out("=" * 70)
        out("A. 所有 INPUT 輸入框")
        out("=" * 70)
        for i, el in enumerate(driver.find_elements(By.TAG_NAME, "input"), 1):
            try:
                if not el.is_displayed():
                    continue
                out(f"[{i}] id={el.get_attribute('id')!r}")
                out(f"     name={el.get_attribute('name')!r}")
                out(f"     class={el.get_attribute('class')!r}")
                out(f"     placeholder={el.get_attribute('placeholder')!r}")
                out(f"     type={el.get_attribute('type')!r}")
                out(f"     value={el.get_attribute('value')!r}")
                out()
            except Exception:
                pass

        out("=" * 70)
        out("B. 所有 SELECT 下拉選單")
        out("=" * 70)
        for i, el in enumerate(driver.find_elements(By.TAG_NAME, "select"), 1):
            try:
                out(f"[{i}] id={el.get_attribute('id')!r}")
                out(f"     name={el.get_attribute('name')!r}")
                out(f"     class={el.get_attribute('class')!r}")
                out(f"     displayed={el.is_displayed()}")
                opts_txt = [o.text.strip() for o in el.find_elements(By.TAG_NAME, "option")][:15]
                out(f"     選項(前15個)={opts_txt}")
                out()
            except Exception:
                pass

        out("=" * 70)
        out("C. 所有 BUTTON / 可點擊元素(含 SEARCH 鈕)")
        out("=" * 70)
        for tag in ["button", "a"]:
            for el in driver.find_elements(By.TAG_NAME, tag):
                try:
                    if not el.is_displayed():
                        continue
                    txt = (el.text or "").strip()
                    # 只印有文字的,避免洗版
                    if not txt or len(txt) > 40:
                        continue
                    if txt.upper() in ("SEARCH", "CLEAR ALL", "SEARCH 搜尋"):
                        out(f"<{tag}> text={txt!r}")
                        out(f"     id={el.get_attribute('id')!r}")
                        out(f"     name={el.get_attribute('name')!r}")
                        out(f"     class={el.get_attribute('class')!r}")
                        out()
                except Exception:
                    pass

        out("=" * 70)
        out("D. PrimeFaces 風格的自訂下拉元件(可能不是標準 select)")
        out("=" * 70)
        for css in ["div[id*='ddl']", "div[class*='dropdown']", "span[class*='dropdown']",
                    "div[class*='ui-selectonemenu']"]:
            els = driver.find_elements(By.CSS_SELECTOR, css)
            for el in els[:8]:
                try:
                    if not el.is_displayed():
                        continue
                    out(f"selector={css}")
                    out(f"     id={el.get_attribute('id')!r}")
                    out(f"     class={el.get_attribute('class')!r}")
                    out(f"     text={(el.text or '')[:60]!r}")
                    out()
                except Exception:
                    pass

        with open("page_structure.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out("=" * 70)
        out("已存檔: page_structure.txt")
        out("請把這個檔案的內容貼給 Claude")
        out("=" * 70)

        input("\n按 Enter 關閉瀏覽器...")

    except Exception:
        traceback.print_exc()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
