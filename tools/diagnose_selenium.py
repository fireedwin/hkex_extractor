# -*- coding: utf-8 -*-
"""
diagnose_selenium.py — 獨立診斷 Chrome + Selenium 能不能正常啟動

跟 batch_download.py 完全無關,單純測試最基本的「能不能打開一個瀏覽器視窗」。
如果這個腳本都失敗,問題100%出在你電腦的 Chrome/ChromeDriver 環境設定,
跟我們寫的程式邏輯無關。

用法:
    python3 diagnose_selenium.py
"""

import sys
import traceback


def main():
    print("=" * 60)
    print("步驟 1:檢查 selenium 套件版本")
    print("=" * 60)
    try:
        import selenium
        print(f"✓ selenium 版本: {selenium.__version__}")
    except ImportError as e:
        print(f"✗ selenium 沒裝好: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("步驟 2:嘗試啟動 Chrome(顯示視窗模式)")
    print("=" * 60)
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument("--window-size=1200,800")
        # 先不加 headless,確保看得到視窗

        print("正在啟動 Chrome... (如果卡超過30秒沒反應,直接 Ctrl+C 中斷)")
        driver = webdriver.Chrome(options=opts)
        print("✓ Chrome 啟動成功!")

        print()
        print("=" * 60)
        print("步驟 3:嘗試連上 HKEXnews 首頁(不做任何操作,只是打開)")
        print("=" * 60)
        driver.get("https://www1.hkexnews.hk/search/titlesearch.xhtml")
        print(f"✓ 頁面標題: {driver.title}")
        print(f"✓ 目前網址: {driver.current_url}")

        input("\n瀏覽器視窗應該已經開啟,請肉眼確認頁面內容,按 Enter 繼續關閉...")
        driver.quit()
        print("\n✓✓✓ 全部診斷通過,Chrome/Selenium 環境正常。")
        print("    可以回去執行 batch_download.py 了。")

    except Exception as e:
        print(f"\n✗ 失敗於此步驟,完整錯誤如下:\n")
        traceback.print_exc()
        print()
        print("=" * 60)
        print("常見原因對照:")
        print("=" * 60)
        msg = str(e).lower()
        if "chrome not reachable" in msg or "cannot find chrome" in msg or "no such file" in msg:
            print("→ 你的電腦可能沒裝 Google Chrome(只有裝 Edge/Firefox)。")
            print("  請到 https://www.google.com/chrome/ 下載安裝 Chrome。")
        elif "session not created" in msg and "version" in msg:
            print("→ Chrome 版本跟自動抓取的 ChromeDriver 版本不匹配。")
            print("  嘗試: pip install --upgrade selenium")
        elif "user-data-dir" in msg or "user data" in msg:
            print("→ 可能有另一個 Chrome 視窗正在用同一個設定檔,先關掉所有 Chrome 視窗再試。")
        else:
            print("→ 錯誤訊息不屬於以上常見情況,請把上面完整的錯誤內容"
                  "(包含 Traceback)複製給 Claude 判斷。")
            print("→ 也請順便確認:工作管理員裡有沒有防毒軟體最近攔截了 chromedriver.exe")
        sys.exit(1)


if __name__ == "__main__":
    main()
