# Cetus：單一任務處理多份文件，只跑 OCR

本指南的 Windows 指令在 PowerShell（提示字 `PS C:\...>`）執行；Linux 指令在
SSH 登入後的 Cetus（提示字 `[YOUR_HPC_ID@hpc-login01 ...]$`）執行。只複製程式碼區塊。

2026-10-11 本次資料夾 `138` 清點結果：實際包含 **326 個 PDF**，
分布在六個子資料夾，總大小約 275.4 MiB。資料夾名稱不等於文件數量。
以下整個資料夾的上傳方式會包含全部 326 份；如果只選部分，先準備獨立選定資料夾。
PDF 可能多頁，因此文件數量不等於頁數。這次沒有把真實文件用於自動化測試。

共用文件不記錄個人學校帳號。使用前將 `YOUR_HPC_ID` 替換成自己的 Cetus 帳號，
將 `C:\path\to\138` 與本機專案路徑替換成實際位置。Linux 指令使用 `$HOME`
與 `id -un` 自動取得目前登入者的家目錄與帳號，不必硬編碼 ID。

## 1. 本機 PowerShell：登入 Cetus

```powershell
ssh YOUR_HPC_ID@hpc-login01.hpc.uts.edu.au
```

依學校登入流程輸入密碼／驗證；密碼輸入不顯示是正常情況。

## 2. Cetus Linux：確認程式與建立上傳位置

```bash
cd "$HOME/ocr-rag-australian-financial-docs"
git status
.venv-gpu/bin/python --version
.venv-gpu/bin/python -m app.cli parse --help
ls -l .models/manifest.json
mkdir -p private_inputs .runtime/ocr-batch .runtime/jobs
qstat -Qf small_gpuq
```

既有環境應為 Python 3.11，並存在 parse 指令及模型 manifest。不要在 login node
直接執行真正的 OCR 或 GPU 計算，下面會交由 PBS compute node 執行。

若現有程式缺少 parse，且 git status 顯示乾淨，可由你更新：

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

若有未提交檔案或 Git 錯誤，先保留狀態，不要覆蓋／強制重設。這次兩個新腳本可直接
上傳至 `.runtime`，不需要先 commit/push；也不會與日後 Git 追蹤的 scripts 路徑衝突。

記錄 `qstat -Qf small_gpuq` 的 `resources_max.walltime` 和限制。若沒有該欄位，
也不能斷定無上限：可能還有 server／routing queue／學校政策。要延長任務前先確認。

返回本機：

```bash
exit
```

## 3. 本機 PowerShell：上傳資料與腳本

確認提示字已經是 `PS C:\...>`，不是 `[YOUR_HPC_ID@...]$`。

```powershell
Get-ChildItem -LiteralPath "C:\path\to\138" -Recurse -File | Measure-Object
scp -r "C:\path\to\138" "YOUR_HPC_ID@hpc-login01.hpc.uts.edu.au:/shared/homes/YOUR_HPC_ID/ocr-rag-australian-financial-docs/private_inputs/"
```

上傳後位置是 `private_inputs/138/`，其中保留 b-files、cc-photos 等原子資料夾。
OneDrive 若尚未下載實體檔案，先在檔案總管對資料夾選「永遠保留在此裝置」，再上傳。
SCP 只傳輸檔案，不會執行 OCR。上傳中不要修改來源 PDF。

再上傳這次產生的兩個腳本：

```powershell
cd "C:\path\to\ocr-rag-australian-financial-docs"
scp .\scripts\cetus_ocr_batch.pbs .\scripts\run_ocr_batch.py "YOUR_HPC_ID@hpc-login01.hpc.uts.edu.au:/shared/homes/YOUR_HPC_ID/ocr-rag-australian-financial-docs/.runtime/ocr-batch/"
```

## 4. 重新登入 Cetus，檢查上傳

```powershell
ssh YOUR_HPC_ID@hpc-login01.hpc.uts.edu.au
```

以下改為 Cetus Linux 指令：

```bash
cd "$HOME/ocr-rag-australian-financial-docs"
find private_inputs/138 -type f -iname '*.pdf' | wc -l
du -sh private_inputs/138
ls -l .runtime/ocr-batch/
sed -i 's/\r$//' .runtime/ocr-batch/cetus_ocr_batch.pbs
bash -n .runtime/ocr-batch/cetus_ocr_batch.pbs
.venv-gpu/bin/python .runtime/ocr-batch/run_ocr_batch.py --help
```

整個原資料夾上傳時 PDF 數應為 326。`bash -n` 沒有輸出且沒有錯誤表示 Bash 語法通過，
不是 GPU 測試。`sed` 只移除上傳腳本可能有的 Windows 行尾，不處理你的 PDF。

## 5. 提交一個任務

建立一個你之後可以記住的批次名稱：

```bash
BATCH_ID="cetus138_$(date +%Y%m%d_%H%M%S)"
echo "$BATCH_ID"
qsub -v "INPUT_DIR=private_inputs/138,BATCH_ID=$BATCH_ID,BATCH_RUNNER=.runtime/ocr-batch/run_ocr_batch.py" .runtime/ocr-batch/cetus_ocr_batch.pbs
qstat -u "$(id -un)"
```

只會回傳 **一個 Job ID**，整批依序共用一個 GPU allocation。不是每個文件一個 job，
也不是 job array。PDF 不論幾頁都作為一份文件送入完整 DocLayoutV3＋PaddleOCR-VL-1.6。

預設沿用曾成功提交的資源：small_gpuq、1 GPU、4 CPU、32 GB RAM、walltime 01:15:00。
此預設不保證全部 326 份能跑完。排隊 Q 不消耗執行 walltime；開始 R 後才計時。
批次仍受 PBS 的資源、使用者名額、queue 可用性限制，單一 job 不保證立刻開始。

**只有確認 queue 允許八小時時**，可在第一次提交時改用下列命令（不要兩條都送）：

```bash
qsub -l walltime=08:00:00 -v "INPUT_DIR=private_inputs/138,BATCH_ID=$BATCH_ID,BATCH_RUNNER=.runtime/ocr-batch/run_ocr_batch.py" .runtime/ocr-batch/cetus_ocr_batch.pbs
```

2026-10-11 使用者提供的 `qstat -Qf small_gpuq` 顯示 queue 上限為 48 小時，
因此 8 小時未超過當時的 queue walltime 上限，但仍受其他 PBS 政策與資源可用性限制。
8 小時是可調的執行預算，不是完成時間預估；日後應重新查詢 queue 限制。
腳本指定的 01:15:00 優先於 queue 的預設 10 小時，提交時的 `-l walltime` 再覆蓋腳本值。
若排程拒絕該 walltime，依實際 queue 上限調整，不要以改 job 名稱繞過限制。

### GPU 資源怎麼選

`ngpus=1` 申請一張 GPU，不指定型號；`ncpus=4` 申請四個 CPU 核心；
`mem=32gb` 是主機 RAM，不是 GPU 顯示記憶體。`gpu:0` 表示程式使用可見的第一張 GPU，
不是要求特定硬體型號。實際 GPU 型號可從工作 log 的 `nvidia-smi` 查看。

不同 queue 可能對應不同硬體；以學校當前 queue／node 資訊為準，不能只憑
small／med／large 名稱判斷速度。需要比較其他 GPU 時，先查看 `qstat -Qf med_gpuq`
及校方的 [queue 說明](https://cetus.hpc.uts.edu.au/pbs/queues/)，確認資源與權限後再提交。
目前逐份執行且只使用一張 GPU，申請兩張不會自動平行加速；每份重新載入模型的開銷也仍存在。

## 6. 查看進度與結果

```bash
qstat -u "$(id -un)"
ls -lt .runtime/jobs/ocr_batch_*.log
```

開始執行後會產生 `.runtime/jobs/ocr_batch_<jobid>.log`；尚在 Q 時該檔可能不存在。
例如 job ID 是 `123456.hpc-head01`：

```bash
tail -f .runtime/jobs/ocr_batch_123456_hpc-head01.log
```

按 Ctrl+C 只停止 tail，不取消 PBS 任務。log 每份會列 START、COMPLETED 或 FAILED；
不印收據辨識內容。GPU／模型 preflight 失敗會先結束，避免整批逐份失敗。

批次摘要：

```bash
.venv-gpu/bin/python -c 'import json,sys; s=json.load(open("outputs/batches/"+sys.argv[1]+"/summary.json")); print(s["status"]); print(s["counts"])' "$BATCH_ID"
```

摘要於每份開始與結束都更新，包含 source、source hash、歷次 run ID、耗時、狀態和
output 位置。每份文件結果仍只有 `raw.json`、`parsed.md`、`manifest.json`，放在
`outputs/ocrb_<batchhash>_<序號>_<檔名>_<唯一碼>/`。沒有 extracted.json、LLM request 或欄位驗證。

## 7. 時間不夠時續跑

runner 讀取 PBS 實際分配 walltime，扣除 preflight 耗時與餘裕。PBS 批次每份預設 timeout 300 秒；
剩餘時間不足「一份 timeout＋60 秒」時，提前停止，狀態 `paused_time_budget`，exit code 2。
這是預定的暫停，不代表 OCR 錯誤；預設可能因此保留約六分鐘及其他預留餘裕沒有使用。
300 秒是每份文件整個 worker 的上限，包含初始化，不是每頁的上限；多頁或複雜文件可能需要另外重試。

文件內部仍使用既有單文件 OCR worker，每份重新載入模型；本次沒有實作模型常駐加速。
單份失敗會記錄並繼續下一份；耗時上限是每個 PDF，不是每一頁。

**等前一個 job 結束後**，用同一個 BATCH_ID 加 RESUME=1：

```bash
qsub -v "INPUT_DIR=private_inputs/138,BATCH_ID=$BATCH_ID,RESUME=1,BATCH_RUNNER=.runtime/ocr-batch/run_ocr_batch.py" .runtime/ocr-batch/cetus_ocr_batch.pbs
```

斷線重新登入後變數會消失，可用 `ls outputs/batches` 找到批次名稱，重新設定：

```bash
BATCH_ID="填入前一次的批次名稱"
```

續跑逐一驗證成功 run 的 source hash 與 raw/Markdown hash；成功檔跳過，失敗或中斷
文件新建 run 重試，不覆蓋舊結果。若 PBS 硬性終止時 summary 仍顯示 running，下一次
resume 會根據每份 manifest 與 artifacts 恢復進度，不必自行編輯 summary。
不要同時提交同一個 batch ID；OS 檔案鎖拒絕並行寫入，job 結束後鎖會釋放。
输入清單、內容、device 或 model manifest 改變時，請使用新 batch ID。
程式／依賴版本也應保持一致；要做不同版本比較時使用新 batch ID。

### 優先處理未完成文件，暫時跳過先前失敗

先確認沒有同一批次的排隊或執行中任務，再依第 3 節重新上傳兩個更新後的腳本。
依第 4 節執行 `sed`、`bash -n` 和 `--help`，確認 help 包含 `--skip-failed`。
設定原本的 `BATCH_ID`，只提交下面這條（不要同時提交上方一般續跑指令）：

```bash
qsub -q small_gpuq -l walltime=08:00:00 -v "INPUT_DIR=private_inputs/138,BATCH_ID=$BATCH_ID,RESUME=1,SKIP_FAILED=1,PADDLEOCR_TIMEOUT_SECONDS=300,BATCH_RUNNER=.runtime/ocr-batch/run_ocr_batch.py" .runtime/ocr-batch/cetus_ocr_batch.pbs
```

`SKIP_FAILED=1` 對應 runner 的 `--skip-failed`，只能搭配 `--resume`。
已驗證成功文件跳過；先前失敗文件保留 failed 狀態與全部舊嘗試，不重試；
未開始或中斷的文件繼續處理。成功 artifacts 若核對失敗，仍會重新處理，不默認它成功。
本輪新失敗的文件記錄後繼續下一份。若處理完待辦但仍有失敗，狀態是
`completed_with_failures`、exit code 1，不能解讀為全部成功。

這次更新只調整批次策略與逾時，可沿用原批次；原嘗試的 timeout 不會被覆寫，
新嘗試各自記錄 300 秒。OCR 模型和辨識流程保持不變。要在未來重試失敗文件時，
移除 `SKIP_FAILED=1` 或設為 `0`，並明確選擇當次的 timeout；不會自動重試。

本腳本不會自動再送 qsub，也不會繞過 queue walltime。較大批次仍可能需要數次續跑。
成功是流程完成，並非 OCR 正確率已經確認。

## 8. 下載本批結果

在 Cetus 上（先確定 job 已結束），將本批摘要與所有嘗試的結果打包：

```bash
.venv-gpu/bin/python - "$BATCH_ID" <<'PY'
import json, pathlib, sys, tarfile
batch_id = sys.argv[1]
summary = pathlib.Path('outputs/batches') / batch_id / 'summary.json'
data = json.loads(summary.read_text())
archive = pathlib.Path('.runtime') / (batch_id + '_results.tar.gz')
with tarfile.open(archive, 'w:gz') as tar:
    tar.add(summary, arcname=summary.as_posix())
    for row in data['files']:
        for attempt in row['attempts']:
            path = pathlib.Path(attempt['output'])
            if path.is_dir():
                tar.add(path, arcname=path.as_posix())
print(archive)
PY
```

記下輸出的 archive 檔名。回本機 PowerShell 使用 scp，例如將範例名稱替換成實際批次名：

```powershell
cd "C:\path\to\ocr-rag-australian-financial-docs"
$batchId = "填入實際批次名稱"
New-Item -ItemType Directory -Force "outputs/cetus_downloads" | Out-Null
scp "YOUR_HPC_ID@hpc-login01.hpc.uts.edu.au:/shared/homes/YOUR_HPC_ID/ocr-rag-australian-financial-docs/.runtime/${batchId}_results.tar.gz" "outputs/cetus_downloads/"
tar -xzf "outputs/cetus_downloads/${batchId}_results.tar.gz"
```

解壓前確認本機沒有同名批次結果，避免覆蓋；run ID 含隨機碼以減少不同批次撞名。

## 驗證界線

本機僅用 synthetic PDFs／fake parser 測試遞迴、續跑、失敗繼續、雜湊與鎖定；
沒有上傳使用者文件或登入 Cetus，沒有測新 PBS job 的實際 GPU 執行。
queue 的當前政策須以你的 `qstat -Qf` 與校方說明為準。
PBS 的 walltime／qsub 概念參考 [PBS 官方使用指南](https://2021.help.altair.com/2021.1/PBSProfessional/PBSUserGuide2021.1.pdf)。
