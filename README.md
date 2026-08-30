# HKEX Document Extractor — 港交所文件資料萃取工具

為 business valuation / appraisal 工作流設計的年報與招股書資料萃取工具。

---

## 這個工具解決什麼問題

把整份 400 頁年報丟給 AI 問問題,通常會失敗,原因有三個:

| 問題 | 本工具的處理方式 |
|---|---|
| 文件太大,超出模型上下文 | 規則層先把全份縮減到少數相關頁面再交給 AI |
| AI 讀數字會出錯或幻覺 | 數字一律由正則式從原文精確擷取,並做合理範圍檢查,不經模型生成 |
| 答案無法追溯、不敢採用 | 每一列輸出都帶 PDF 頁碼、年報印刷頁碼與**原文行**,可即時翻回原文覆核 |

核心理念:**規則層負責「找」,AI 負責「讀懂」。** 兩者分工,而不是把全部工作丟給 AI。

---

## 兩個入口,分工明確

```
pipeline.py    下載 + 分析(端到端)
run.py         只分析本機 PDF
```

下載一律走 `pipeline.py`。`run.py` 不再負責下載 —— 舊的 `hkexnews.py`
假設 HKEXnews 有公開 API,實測證實沒有,而且失敗時會回傳空白結果卻不報錯。
該檔案已標記為棄用,匯入時會直接擋下。

---

## 安裝

```bash
pip install -r requirements.txt
```

會安裝:`pymupdf`(PDF 讀取,預設引擎)、`pdfplumber`(備用引擎)、
`openpyxl`(Excel)、`selenium`(HKEXnews 下載)、`requests`、`reportlab`(產生測試檔)。

下載功能另需電腦已安裝 **Google Chrome**。

---

## 常用指令

```bash
# 先確認環境正常(產生模擬年報再分析)
python3 make_sample_pdf.py
python3 run.py --pdf sample_annual_report.pdf

# 分析單一 PDF
python3 run.py --pdf downloads/00700_TENCENT_20250408.pdf

# 分析整個資料夾(旺季批次最常用)
python3 pipeline.py --pdf downloads
python3 pipeline.py --pdf downloads --recursive        # 連子資料夾
python3 pipeline.py --pdf "downloads/007*.pdf"         # 萬用字元要加引號

# 下載 + 分析(指定公司)
python3 pipeline.py --stocks 00700,00731 --from 20250101 --to 20251231
python3 pipeline.py --stocks 00700 --from 20250101 --to 20251231 --show-browser

# 下載 + 分析(全市場,資料量大,不建議現場示範)
python3 pipeline.py --all-market --from 20250301 --to 20250430

# 加上 AI 語意層(選用)
export ANTHROPIC_API_KEY=sk-ant-...
python3 pipeline.py --pdf downloads --ai
```

沒有 API key 時工具仍完整運作,AI 只是加分項,不是單點故障。

---

## 輸出成果

一個 Excel 檔,七個分頁:

| 分頁 | 內容 |
|---|---|
| Summary 摘要 | 文件統計、擷取筆數、**會計恆等式交叉驗證**、方法論 |
| **Valuation Params 估值參數** | 折現率 / WACC / 永續增長率 / 資本化率 / 預期波幅 + 信心度 + 來源頁 |
| Financials 財務數據 | 三大報表科目,本年 vs 上年,附**原文行** |
| Ratios 財務比率 | 毛利率、流動比率、商譽佔比、ROE —— 以公式連結,改數字會自動重算 |
| Chart 趨勢圖 | 主要科目本年 vs 上年柱狀圖 |
| Extracts 主題段落 | 無形資產 / 減值測試 / 公允價值 / 投資物業 / 研發 / ESG 段落 |
| Review Queue 待覆核 | **未擷取到的財務科目** + 文字量過低(疑似掃描頁)的頁面 |

估值參數分頁是對估值行價值最高的部分 —— 它把每份年報變成 benchmark 資料庫裡的幾行資料。

---

## 自動驗證機制

工具不只擷取,還會自己檢查抓得對不對。終端機與 Excel 摘要頁都會顯示:

```
[check] ✓ 5 項會計恆等式交叉驗證全部通過
```

檢查項目:

- 流動資產 − 流動負債 = 淨流動資產
- 總資產 = 總負債 + 總權益
- 收入 − 銷售成本 = 毛利
- 除稅前溢利 ± 稅項 = 年內溢利(自動判斷稅項是費用還是抵免)
- 三大報表應相鄰(離群代表某張抓錯頁)

**報表數字之間本來就該對得上,對不上就代表某欄錯位。** 這比人工逐頁核對快得多。

另外,沒抓到的科目會列進待覆核分頁,不會靜靜消失。

---

## 檔案結構

```
核心流程
  config.py            領域知識層 —— 關鍵字、科目別名、估值參數(最值得客製化)
  pdf_reader.py        逐頁萃取 + 印刷頁碼校正 + 掃描頁標記 + 雙引擎切換
  scanner.py           主題定位 + 估值參數擷取 + 合理性檢查
  financials.py        三大報表解析 + 會計恆等式驗證
  excel_out.py         Excel 輸出 + 公式 + 圖表
  ai_layer.py          AI 語意層(選用)
  console.py           Windows 編碼修正
  run.py               分析單一/多個 PDF
  pipeline.py          端到端主流程

下載
  hkexnews_selenium.py 瀏覽器自動化下載核心
  batch_download.py    只下載不分析
  hkexnews.py          已棄用(保留作技術調查紀錄)

測試與診斷
  test_financials.py   財務科目擷取回歸測試
  test_engines.py      雙引擎一致性測試
  test_pagenos.py      頁碼偵測回歸測試
  check_files.py       確認檔案為最新版、無重複副本
  check_pagenos.py     頁碼偵測可靠度分析
  compare_engines.py   雙引擎逐項比對
  diagnose_params.py   估值參數漏抓診斷
  make_sample_pdf.py   產生測試樣本
```

要換一個行業或客戶,只需要改 `config.py`,不用動程式邏輯。

---

## 已在真實年報上驗證

用四份真實港股年報實測(騰訊 00700、C&D 00731、中國衛生 00673、WLS 08021):

- 騰訊 24 個財務科目,與 PDF 原文逐項核對 28 個數字全部一致
- 四份年報的會計恆等式交叉驗證全部通過
- 支援中英對照年報(港股半數以上是這種格式)
- 支援虧損公司(Profit → Loss 自動對稱)、毛損、稅務抵免
- 破折號(nil)正確轉為 0,不會造成年度欄位左移
- 自動剔除附註編號,但保留真實的小額數值
- 報表頁自動校正(曾把附註頁誤判為現金流量表,已修正)

處理速度:274 頁年報約 0.5 秒(PyMuPDF 引擎)。

---

## 已知限制(誠實揭露)

- **掃描版 PDF 無法處理**,只會被標記進待覆核清單。要處理需另接 OCR。
- **跨頁表格**目前不會自動接續(報表跨頁已處理,附註表格未處理)。
- **附註中的科目不擷取**,例如 R&D、折舊、攤銷若不在報表表面就抓不到。
- **HKEXnews 沒有官方 API**,下載走瀏覽器自動化,網站改版可能失效。
  `hkexnews_selenium.py` 的 `SELECTORS` 集中管理所有頁面元素,便於校正。
  下載已內建延遲,請遵守網站使用條款。
- **PyMuPDF 採 AGPL 授權**,自用無虞;若要對外散布或架成網路服務,
  請先確認授權合規。
- **這是輔助工具,不是取代人手覆核。** 信心度標為 Low、以及待覆核分頁
  列出的項目,應由分析師確認。
