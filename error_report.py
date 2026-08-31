# -*- coding: utf-8 -*-
"""
error_report.py — 問題彙整紀錄

要解決的問題
------------
批次跑幾十份時,警告會被大量正常輸出淹沒;更麻煩的是有些失敗在畫面上
長得像成功。實例:01007 那份通函,終端機顯示

    [check] ✓ 1 項會計恆等式交叉驗證全部通過
    [pipeline] 完成:1 / 1 份成功

但實際上 0 個財務科目、報表頁相距 39 頁。只看最後一行的人會以為沒事。

做法
----
把「查無結果」「分析失敗」「交叉驗證未通過」「0 個科目」這類事件集中
收進一份 txt,放在 error message/ 資料夾,格式:

    檔案名 | stock號 | 什麼事 | 運行指令時當刻時間

沒有問題就不產生檔案 —— 否則資料夾很快堆滿空檔,反而沒人看。

兩種訊息來源
------------
1. **明確回報**(下載階段):查無結果、下載失敗、分析丟例外。
   這些是 pipeline.py / hkexnews_selenium.py 自己知道的事,直接呼叫
   reporter.add() 記錄,不猜。

2. **輸出掃描**(分析階段):交叉驗證未通過、0 個科目、找不到報表頁。
   ⚠ 這些訊息目前是由 financials.py / pdf_reader.py 直接印出來的,
   process_one() 只回傳一個檔案路徑,沒有把「過程中發生什麼」結構化
   地交出來。所以這裡改用「攔截這些模組的輸出再比對 ERROR_PATTERNS」
   的方式取得。

   這是妥協,不是最佳解:文字比對會隨訊息措辭改變而失效。真正乾淨的
   做法是讓 process_one() 回傳一個結果物件(含 checks、missing_items
   等欄位),由 pipeline 直接讀取。等哪天要改 run.py / financials.py 時
   應該一併改掉,這個模組的 scan_text() 就可以退休。

   ERROR_PATTERNS 放在 config.py,措辭改了只要改設定檔,不用動邏輯。
"""

from __future__ import annotations

import io
import os
import re
import sys
import logging
from datetime import datetime

logger = logging.getLogger("error_report")

UNGENERATED = "無法生成"


# ──────────────────────────────────────────────────────────────
# 從檔名取股票代號
# ──────────────────────────────────────────────────────────────
def stock_from_name(name: str) -> str:
    """
    檔名格式是 01007_LONGHUI_INTL_MT_20260825.pdf,開頭那段數字就是代號。
    取不到就回空字串,不要瞎猜 —— 紀錄裡留白比填錯的代號好。
    """
    if not name:
        return ""
    m = re.match(r"^(\d{4,5})[_\-]", os.path.basename(name))
    return m.group(1) if m else ""


# ──────────────────────────────────────────────────────────────
# 攔截輸出
# ──────────────────────────────────────────────────────────────
class _Tee:
    """同時寫到原本的串流和緩衝區,讓使用者照樣看得到即時進度。"""

    def __init__(self, real, buf):
        self._real, self._buf = real, buf

    def write(self, s):
        self._real.write(s)
        self._buf.write(s)
        return len(s)

    def flush(self):
        self._real.flush()

    def __getattr__(self, item):
        return getattr(self._real, item)


class OutputCapture:
    """
    暫時攔截 print() 與 logging 的輸出,同時仍照常顯示在畫面上。

    為什麼 print 和 logging 要分開處理:logging 的 StreamHandler 在
    設定當下就把 sys.stderr 物件記住了,之後再替換 sys.stderr 對它
    沒有作用。所以除了接管 sys.stdout,還要另外掛一個 handler 到
    root logger,兩邊都收才不會漏掉訊息。
    """

    def __init__(self):
        self.buf = io.StringIO()
        self._old_stdout = None
        self._handler = None
        self._old_level = None

    def __enter__(self):
        self._old_stdout = sys.stdout
        sys.stdout = _Tee(self._old_stdout, self.buf)
        self._handler = logging.StreamHandler(self.buf)
        self._handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        self._handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(self._handler)
        # logger 的等級在訊息送到 handler **之前**就先過濾掉了。
        # 呼叫端若沒設過 basicConfig,root 預設是 WARNING,
        # 那 financials.py 用 logger.info 印的「共擷取 0 個財務科目」
        # 根本不會傳到這裡 —— 最重要的那幾條訊息剛好都是 INFO。
        # 所以攔截期間暫時把門檻降到 INFO,結束後還原。
        if root.level > logging.INFO:
            self._old_level = root.level
            root.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        sys.stdout = self._old_stdout
        root = logging.getLogger()
        if self._handler is not None:
            root.removeHandler(self._handler)
        if self._old_level is not None:
            root.setLevel(self._old_level)
        return False

    def text(self) -> str:
        return self.buf.getvalue()


def scan_text(text: str, patterns=None) -> list:
    """
    比對 ERROR_PATTERNS,回傳 (what, severity) 的清單(已去重、保留順序)。
    severity 取自 pattern 設定,沒寫的話預設 "medium"(不確定的狀況
    不該被自動歸進「輕微」而被忽略,寧可偏保守)。
    """
    if patterns is None:
        try:
            import config as _C
            patterns = getattr(_C, "ERROR_PATTERNS", [])
        except Exception:
            patterns = []

    found, seen = [], set()
    for spec in patterns:
        try:
            rx = re.compile(spec["pattern"])
        except re.error as e:
            logger.warning(f"ERROR_PATTERNS 有無效的正則式,略過: {spec} — {e}")
            continue
        severity = spec.get("severity", "medium")
        for m in rx.finditer(text or ""):
            groups = {k: (v or "").strip() for k, v in (m.groupdict() or {}).items()}
            if "items" in groups:
                groups["n_items"] = str(
                    len([x for x in groups["items"].split(",") if x.strip()]))
            try:
                what = spec["what"].format(**groups)
            except (KeyError, IndexError):
                what = spec["what"]
            if what not in seen:
                seen.add(what)
                found.append((what, severity))
    return found


# ──────────────────────────────────────────────────────────────
# 紀錄本體
# ──────────────────────────────────────────────────────────────
class ErrorReport:
    """
    收集一次執行過程中所有有問題的項目,最後寫成一份 txt。

    run_time 是「運行指令時當刻時間」,整份紀錄共用同一個時間戳 ——
    使用者要對照的是「哪一次執行出的問題」,不是每一列各自的秒數。
    """

    def __init__(self, out_dir: str | None = None, run_time: datetime | None = None,
                 root: str | None = None):
        self.root = root or os.path.dirname(os.path.abspath(__file__))
        if out_dir is None:
            try:
                import config as _C
                out_dir = getattr(_C, "ERROR_DIR", "error message")
            except Exception:
                out_dir = "error message"
        self.out_dir = out_dir if os.path.isabs(out_dir) \
            else os.path.join(self.root, out_dir)
        self.run_time = run_time or datetime.now()
        self.entries = []

    # ── 收集 ────────────────────────────────────────────────
    def add(self, what: str, filename: str | None = None,
            stock: str | None = None, severity: str = "medium") -> None:
        """
        記一筆問題。filename 留空表示沒有產生任何檔案。
        stock 留空時會試著從檔名推,推不出來就留白。

        severity 決定寫檔時排在哪一區:"high" / "medium" / "low"。
        預設 "medium" —— 呼叫端沒指定嚴重度時,不自動歸為「輕微」而
        被排到最後不顯眼的位置,寧可保守估計。
        """
        name = os.path.basename(filename) if filename else UNGENERATED
        code = stock or stock_from_name(filename or "")
        self.entries.append({
            "file": name,
            "stock": code or "",
            "what": (what or "").replace("\n", " ").strip(),
            "severity": severity if severity in ("high", "medium", "low") else "medium",
        })

    def add_many(self, items, filename=None, stock=None, severity: str = "medium") -> None:
        """items 可以是純字串清單(套用同一個 severity),也可以是 (what, severity) 的清單。"""
        for it in items or []:
            if isinstance(it, tuple):
                what, sev = it
            else:
                what, sev = it, severity
            self.add(what, filename=filename, stock=stock, severity=sev)

    def scan_and_add(self, text: str, filename=None, stock=None) -> list:
        """
        掃描一段輸出文字,把命中的問題連同各自的嚴重度記下來,
        回傳 (what, severity) 的命中清單。
        """
        hits = scan_text(text)
        self.add_many(hits, filename=filename, stock=stock)
        return hits

    def __len__(self):
        return len(self.entries)

    # ── 輸出 ────────────────────────────────────────────────
    @property
    def path(self) -> str:
        stamp = self.run_time.strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.out_dir, f"errors_{stamp}.txt")

    def save(self) -> str | None:
        """
        寫出紀錄檔;沒有任何問題就不建檔,回傳 None。

        依嚴重度分成三區塊,「嚴重」永遠在最前面 —— 讀的人不用先掃過
        全部 649 筆才找到真正要處理的那幾筆。順序來自
        config.ERROR_SEVERITY_ORDER,標籤來自 ERROR_SEVERITY_LABELS,
        兩者都是設定檔,不寫死在這裡。

        沒有任何一筆是某個嚴重度時,那個區塊整段不出現 —— 不留空標題。

        資料夾不存在會自動建立(含名稱有空白的 "error message")。
        寫檔失敗只警告不中斷 —— 紀錄檔的用途是事後追查,不該讓它
        反過來讓整批分析失敗。
        """
        if not self.entries:
            return None
        try:
            os.makedirs(self.out_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"無法建立資料夾 {self.out_dir}: {e}")
            return None

        try:
            import config as _C
            order = getattr(_C, "ERROR_SEVERITY_ORDER", ["high", "medium", "low"])
            labels = getattr(_C, "ERROR_SEVERITY_LABELS", {})
        except Exception:
            order = ["high", "medium", "low"]
            labels = {}

        stamp = self.run_time.strftime("%Y-%m-%d %H:%M:%S")
        counts = {lvl: sum(1 for e in self.entries if e["severity"] == lvl)
                 for lvl in order}
        breakdown = "、".join(f"{lvl}:{counts[lvl]}" for lvl in order if counts[lvl])

        lines = [
            "HKEX 文件處理 — 問題紀錄",
            f"執行時間 {stamp}",
            f"共 {len(self.entries)} 筆需要注意({breakdown})",
        ]

        w_file = max([len(e["file"]) for e in self.entries] + [len("檔案名")])
        w_stock = max([len(e["stock"]) for e in self.entries] + [len("stock號")])
        header = f"{'檔案名'.ljust(w_file)} | {'stock號'.ljust(w_stock)} | 什麼事 | 執行時間"
        rule = "-" * max(len(header), 40)

        for lvl in order:
            bucket = [e for e in self.entries if e["severity"] == lvl]
            if not bucket:
                continue
            lines.append("")
            lines.append("=" * 70)
            lines.append(labels.get(lvl, lvl))
            lines.append("=" * 70)
            lines.append("")
            lines.append(header)
            lines.append(rule)
            for e in bucket:
                lines.append(f"{e['file'].ljust(w_file)} | "
                             f"{e['stock'].ljust(w_stock)} | "
                             f"{e['what']} | {stamp}")

        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.warning(f"寫入錯誤紀錄失敗: {e}")
            return None
        return self.path
