# 機票追蹤器

每天自動查 Google Flights 票價（透過 SerpAPI），跌破門檻就在 GitHub 開 issue（GitHub 會自動寄信給你）。所有歷史價格存在 `history.json`，可以畫線圖看趨勢。

## 一次性設定（約 5 分鐘）

### 1. 申請 SerpAPI key
1. 到 https://serpapi.com/users/sign_up 註冊（email + 密碼，跟註冊一般網站一樣）
2. 收信點驗證連結
3. 登入後，dashboard 首頁就會顯示 **Your Private API Key**，複製下來

免費方案 100 次/月，我們每天 1 次 × 1 條航線 = 30 次/月，剛好。

### 2. 把 key 放進 GitHub Secrets
repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|---|---|
| `SERPAPI_KEY` | 你的 SerpAPI key |

`GITHUB_TOKEN` 不用自己設，GitHub Actions 會自動給。

### 3. 確認通知打開
GitHub 預設新 issue 會寄 email 到你註冊的信箱。如果沒收到，到 https://github.com/settings/notifications 檢查。

### 4. 改 `config.yml`
編輯航線、日期、門檻。要加多條航線就在 `routes:` 下面複製一段。

### 5. 跑一次測試
repo → **Actions** → **Track flight prices** → **Run workflow**

跑完後：
- 看 log 確認有抓到價格
- `history.json` 會多一筆紀錄
- 如果已經低於門檻，會看到一個新 issue

## 之後

排程是每天台北早上 9 點，會自動跑。不用管它。

- **看歷史**：直接打開 `history.json`，或丟給我幫你畫圖
- **改門檻**：編輯 `config.yml` 的 `threshold`
- **加航線**：在 `config.yml` 加一段
- **暫停**：把 `.github/workflows/track-flight.yml` 改個檔名（或在 Actions 頁面 disable）

## 注意事項

- 價格直接抓 Google Flights，跟你在瀏覽器看到的一樣（含 OTA 行情）
- 跌破門檻時，同一條航線只會開一個 issue。關掉 issue 後，下次再跌破才會再開
- 免費 100 次/月。每天 1 次 × 1 條航線 = 30 次/月，可以放心。如果加到 3 條航線就會逼近上限，要再加就升級或減頻率
