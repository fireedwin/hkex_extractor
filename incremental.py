# -*- coding: utf-8 -*-
"""
incremental.py — 增量處理(路線三)

問題
----
旺季時的工作型態是「每天新增幾十份年報」,而不是「一次重跑全部」。
但目前每次執行 pipeline 都會把 downloads/ 裡的每一份 PDF 重新分析一次,
昨天已經處理過的 190 份也一起重跑。

做法
----
替每份 PDF 記錄一組「指紋」存進帳本(ledger),下次執行時比對:
指紋相同而且輸出檔還在,就直接跳過。

指紋不是只有檔案內容
--------------------
這是本模組最重要的設計判斷。只比對「PDF 內容有沒有變」是不夠的,
因為輸出結果不只取決於 PDF,也取決於**我們的分析邏輯**。

這個專案一路上不斷在擴充 config.py 的科目別名
(Cost of inventories、Bank balances and cash、Net assets ...)。
如果只看 PDF 指紋,那麼:

    第一天  跑 200 份 → 每份抓到 15 個科目
    第二天  補了 6 個別名,重跑 → **全部被跳過**,永遠停在 15 個科目

分析師拿到的是舊結果,而且畫面上寫著「已完成」。這種「安靜地給出過期
資料」對估值工作是不能接受的 —— 跟我們先前拒絕 fuzzy matching 的理由
是同一個:寧可多花時間,不可給出看起來合理的錯東西。

所以指紋由四個部分組成,任何一個變了就重跑:

    1. PDF 檔案內容    (SHA-256)
    2. 分析邏輯版本    (所有分析模組原始碼的 SHA-256)
    3. AI 層開關       (--ai 會改變輸出內容)
    4. 輸出檔是否還在  (使用者手動刪掉 Excel 就該重做)

用法
----
    from incremental import Ledger

    ledger = Ledger(out_dir="output")
    todo, skipped = ledger.split(pdf_paths, use_ai=False)
    for p in todo:
        out = process_one(p, ...)
        ledger.record(p, out, use_ai=False)   # 每份都即時存檔
"""

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger("incremental")

LEDGER_NAME = ".analysis_ledger.json"
SCHEMA_VERSION = 1

# 讀檔用的區塊大小。年報 PDF 動輒 5-10 MB,分塊讀避免一次載入記憶體。
_CHUNK = 1024 * 1024


# ──────────────────────────────────────────────────────────────
# 分析邏輯版本
# ──────────────────────────────────────────────────────────────
# 這些檔案「不影響萃取結果」,所以改了它們不需要重跑全部年報。
# 判斷標準只有一條:**同一份 PDF 餵進去,產出的 Excel 內容會不會不一樣?**
# 會 → 必須納入;不會 → 排除。
#
# 其餘所有 .py 都算進邏輯版本 —— 採用白名單排除而非黑名單列舉,
# 是因為將來新增分析模組時會**自動**被納入。若改成「只雜湊我列出的
# 那幾個檔案」,新模組會被漏掉,又回到「安靜地給出過期資料」。
#
# ⚠ 往這份清單加東西要非常保守。加錯了會導致「改了分析邏輯卻沿用舊結果」,
# 正是這個機制要防的事。加之前先問:同一份 PDF 的萃取結果真的完全不受影響嗎?
_EXCLUDE_EXACT = {
    "pipeline.py",      # 只負責串流程,不影響單份文件的萃取結果
    "incremental.py",   # 就是本檔案
    "console.py",       # 只修 Windows 主控台編碼
    "setup.py",
    # ── 下載層:只決定「PDF 從哪來、叫什麼名字」──────────────
    # 帳本是用 PDF 的**內容雜湊**當 key,不是檔名。同一份 PDF 不管
    # 是自動下載還是手動放進 downloads/,萃取結果完全一樣。
    # 先前擴充 --type 改了 hkexnews_selenium.py,導致全部年報被判定
    # 過期而重跑一次 —— 那次重跑是白費的。
    "hkexnews_selenium.py",
    "batch_download.py",
    "hkexnews.py",      # 已棄用
    # ── 錯誤紀錄層:只決定 error message/ 那份 txt 長什麼樣 ──────
    # 完全不參與萃取,改它不該讓幾百份年報重跑。
    "error_report.py",
    # ── 操作設定:下載哪一類文件、錯誤紀錄規則 ──────────────
    # 這些原本跟科目別名擠在 config.py 裡,導致旺季調一次錯誤訊息
    # 措辭就得重跑幾百份。拆成 ops_config.py 後在此排除。
    # config.py 只是 re-export 它,那一行不會變,所以隔離成立。
    "ops_config.py",
}
_EXCLUDE_PREFIX = ("test_", "check_", "diagnose_", "compare_", "make_", "_")


def _is_logic_file(name: str) -> bool:
    if not name.endswith(".py"):
        return False
    if name in _EXCLUDE_EXACT:
        return False
    if name.startswith(_EXCLUDE_PREFIX):
        return False
    return True


def logic_digests(root: str | None = None) -> dict:
    """
    回傳 {檔名: 內容雜湊} —— 每個會影響萃取結果的模組各算一份。

    有了逐檔雜湊,才答得出「為什麼突然全部重跑」:可以跟帳本裡上次
    存的快照逐一比對,直接指出是哪個檔案變了。先前 error_report.py
    被誤算進邏輯版本、害幾百份年報白重跑時,畫面上只寫「分析邏輯已更新」,
    沒有任何線索指向兇手 —— 那次診斷是靠人去翻程式碼才找到的,
    這種事不該再發生一次。
    """
    root = root or os.path.dirname(os.path.abspath(__file__))
    try:
        names = sorted(n for n in os.listdir(root) if _is_logic_file(n))
    except OSError:
        return {}

    out = {}
    for n in names:
        p = os.path.join(root, n)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()[:12]
        except OSError:
            continue
    return out


def compute_logic_version(root: str | None = None) -> tuple[str, list[str]]:
    """
    把所有「會影響萃取結果」的 .py 原始碼串起來雜湊。

    回傳 (版本碼, 納入計算的檔名清單)。檔名清單是給診斷工具用的,
    讓使用者能親眼確認哪些檔案被算進去 —— 「為什麼它突然要全部重跑」
    必須要能查得出來,不能是個黑盒子。
    """
    digests = logic_digests(root)
    h = hashlib.sha256()
    for n in sorted(digests):
        # 連檔名一起雜湊:只改檔名(等於換了模組)也要算版本變動
        h.update(n.encode("utf-8"))
        h.update(b"\0")
        h.update(digests[n].encode("ascii"))
    return h.hexdigest()[:16], list(sorted(digests))


def file_fingerprint(path: str) -> str:
    """PDF 內容的 SHA-256(前 16 碼)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:16]


# ──────────────────────────────────────────────────────────────
# 帳本
# ──────────────────────────────────────────────────────────────
class Ledger:
    """
    以「PDF 內容指紋」為 key 的處理紀錄。

    刻意用內容而非檔名當 key:HKEXnews 同一份年報可能因為重新下載而
    有不同檔名(例如加了 -R 或時間戳),用檔名會誤判成新檔案而重跑;
    反過來,同名但內容被換掉(公司重新提交修訂版)必須要能偵測到。
    """

    def __init__(self, out_dir: str = "output", root: str | None = None,
                 path: str | None = None):
        self.root = root or os.path.dirname(os.path.abspath(__file__))
        self.out_dir = out_dir
        self.path = path or os.path.join(out_dir, LEDGER_NAME)
        self.logic_version, self.logic_files = compute_logic_version(self.root)
        self.logic_digests = logic_digests(self.root)
        self._data = self._load()
        self.reasons = {}          # split() 之後填入:路徑 → 判斷理由
        # 本次執行的統計,供最後總結用
        self.stats = {"skipped": 0, "recorded": 0, "hash_seconds": 0.0}

    def logic_changes(self) -> dict:
        """
        比對帳本裡上次存的模組快照,回傳哪些檔案變了:
            {"added": [...], "removed": [...], "modified": [...]}

        這是「為什麼突然全部重跑」的答案。沒有它,使用者只會看到
        「分析邏輯已更新」,卻無從得知是自己改的 config.py、還是某個
        根本不該影響萃取的模組(例如錯誤紀錄層)被誤算進去。
        空 dict 代表沒有可比對的舊快照(第一次跑,或舊版帳本)。
        """
        old = self._data.get("logic_snapshot") or {}
        if not old:
            return {}
        new = self.logic_digests
        return {
            "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)),
            "modified": sorted(n for n in set(old) & set(new) if old[n] != new[n]),
        }

    # ── 讀寫 ────────────────────────────────────────────────
    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"schema": SCHEMA_VERSION, "entries": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "entries" not in data:
                raise ValueError("格式不符")
            if data.get("schema") != SCHEMA_VERSION:
                logger.warning(f"帳本版本不符(檔案 {data.get('schema')} ≠ "
                               f"程式 {SCHEMA_VERSION}),視為全新開始")
                return {"schema": SCHEMA_VERSION, "entries": {}}
            return data
        except Exception as e:
            # 帳本壞掉不該讓整條 pipeline 停擺 —— 最壞情況就是全部重跑一次,
            # 那正是沒有增量處理時的原狀,不會產生錯誤結果。
            logger.warning(f"帳本讀取失敗({e}),這次全部重新分析")
            return {"schema": SCHEMA_VERSION, "entries": {}}

    def save(self) -> None:
        """原子寫入:先寫暫存檔再 replace,中途斷電不會留下半個壞檔。"""
        # 每次存檔都更新模組快照,下次執行才比對得出「是哪個檔案變了」
        self._data["logic_snapshot"] = dict(self.logic_digests)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ── 判斷 ────────────────────────────────────────────────
    def check(self, pdf_path: str, use_ai: bool = False) -> tuple[bool, str, str]:
        """
        回傳 (可否跳過, 原因, 指紋)。

        原因字串是刻意設計的:使用者看到「跳過 190 份」時,一定會問
        「你確定沒漏掉嗎」。把每一份為什麼要跑、為什麼不用跑講清楚,
        這個功能才敢在正式工作裡用。
        """
        t0 = time.perf_counter()
        fp = file_fingerprint(pdf_path)
        self.stats["hash_seconds"] += time.perf_counter() - t0

        entry = self._data["entries"].get(fp)
        if entry is None:
            return False, "新檔案", fp

        if entry.get("logic_version") != self.logic_version:
            return False, "分析邏輯已更新", fp

        if bool(entry.get("ai")) != bool(use_ai):
            want = "有 AI 層" if use_ai else "無 AI 層"
            return False, f"AI 設定不同(本次{want})", fp

        outputs = entry.get("outputs") or []
        if not outputs:
            return False, "沒有輸出紀錄", fp
        missing = [o for o in outputs if not os.path.exists(self._abs(o))]
        if missing:
            return False, f"輸出檔遺失({os.path.basename(missing[0])})", fp

        prev = entry.get("file", "")
        cur = os.path.basename(pdf_path)
        if prev and prev != cur:
            # 內容一模一樣但檔名不同 —— 同一份年報被下載了兩次。
            # 這其實是增量處理順手帶來的去重效果,但必須講出來,
            # 否則使用者會以為某份文件被無故忽略。
            return True, f"內容與 {prev} 相同(重複檔案)", fp

        return True, "已分析過", fp

    def split(self, pdf_paths: list[str], use_ai: bool = False):
        """
        把待處理清單切成 (要分析的, 可跳過的)。

        可跳過的每一筆是 (路徑, 原因, 既有輸出清單),讓呼叫端可以在
        總結時把舊的 Excel 路徑一併印出來 —— 使用者要的是「檔案在哪」,
        不是「這次有沒有跑」。
        """
        todo, skipped = [], []
        # 記下每份的判斷理由,呼叫端要追問「為什麼這份要重跑」時直接查,
        # 不必再算一次指紋(7 MB 的年報重算一次是白花的成本)。
        self.reasons = {}
        for p in pdf_paths:
            if not os.path.exists(p):
                todo.append(p)          # 交給既有流程去回報「檔案不存在」
                self.reasons[p] = "檔案不存在"
                continue
            ok, reason, fp = self.check(p, use_ai=use_ai)
            self.reasons[p] = reason
            if ok:
                outs = [self._abs(o)
                        for o in self._data["entries"][fp].get("outputs", [])]
                skipped.append((p, reason, outs))
            else:
                todo.append(p)
        self.stats["skipped"] = len(skipped)
        return todo, skipped

    # ── 記錄 ────────────────────────────────────────────────
    def record(self, pdf_path: str, outputs, use_ai: bool = False,
               fingerprint: str | None = None, save: bool = True) -> None:
        """
        分析成功後立刻寫入帳本。

        預設每份都存檔(而不是等全部跑完才存一次)。200 份跑到第 150 份
        當掉時,前面 149 份的成果要保得住 —— 重跑時只補剩下的 51 份。
        寫一次 JSON 的成本遠低於重跑一份年報。
        """
        if isinstance(outputs, str):
            outputs = [outputs]
        outputs = [o for o in (outputs or []) if o]

        fp = fingerprint or file_fingerprint(pdf_path)
        self._data["entries"][fp] = {
            "file": os.path.basename(pdf_path),
            "size": os.path.getsize(pdf_path) if os.path.exists(pdf_path) else None,
            "outputs": [self._rel(o) for o in outputs],
            "logic_version": self.logic_version,
            "ai": bool(use_ai),
            "analysed_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.stats["recorded"] += 1
        if save:
            self.save()

    def forget(self, pdf_path: str) -> bool:
        """把某份文件從帳本移除,下次會重新分析。"""
        fp = file_fingerprint(pdf_path)
        if fp in self._data["entries"]:
            del self._data["entries"][fp]
            self.save()
            return True
        return False

    def clear(self) -> int:
        n = len(self._data["entries"])
        self._data["entries"] = {}
        self.save()
        return n

    # ── 雜項 ────────────────────────────────────────────────
    def entries(self) -> dict:
        return dict(self._data["entries"])

    def stale_count(self) -> int:
        """帳本裡有幾筆是舊邏輯版本產生的。"""
        return sum(1 for e in self._data["entries"].values()
                   if e.get("logic_version") != self.logic_version)

    def _rel(self, p: str) -> str:
        """輸出路徑存相對於專案根目錄的形式,整個資料夾搬走還能用。"""
        try:
            return os.path.relpath(os.path.abspath(p), self.root)
        except ValueError:          # Windows 跨磁碟機
            return os.path.abspath(p)

    def _abs(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(self.root, p)
