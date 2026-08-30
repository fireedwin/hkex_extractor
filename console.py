# -*- coding: utf-8 -*-
"""
console.py — 修正 Windows 主控台的編碼問題

問題:
    程式輸出含有 ✓ ✗ █ ⚠ 這類符號。在 Windows 上直接執行通常沒事,
    但只要輸出被重新導向(例如用 PowerShell 的 Measure-Command 計時、
    或 > file.txt 存檔),Python 就會改用系統地區編碼(繁中是 cp950),
    這些符號無法編碼就會整個程式崩掉:

        UnicodeEncodeError: 'cp950' codec can't encode character '\u2713'

    更糟的是,崩潰點在「印出成功訊息」那一行 —— Excel 其實已經產生了,
    卻被回報成分析失敗。

解法:
    把 stdout/stderr 強制設成 UTF-8,並用 errors="replace",
    萬一遇到真的無法顯示的字元就換成 ?,而不是讓程式中斷。

用法:在每個進入點的最上方 `import console`(要在其他 import 之前)。
"""

import sys


def setup():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            # Python 3.7+ 才有 reconfigure
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 舊版 Python 或已被包裝過的串流,靜靜跳過即可 ——
            # 這只是為了讓輸出好看,不該因此讓程式失敗
            pass


setup()
