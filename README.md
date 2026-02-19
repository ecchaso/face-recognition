# 顔認証 × slack messaging api

カメラで顔を認識し、入退室を自動判定して Slack に通知する Web アプリケーション

---

## 機能

- リアルタイムカメラ映像（MJPEG ストリーミング）
- 顔検出（HOG）+ 顔認証（ResNet / dlib）
- 入室（+）/ 退室（-）の自動判定と CSV ログ記録
- ユーザー別 Slack Webhook 通知
- 入室時の顔画像ローカル保存（`logs/images/`）
- 退室確認ダイアログ（10秒で自動キャンセル）
- ブラウザからの顔データ再読込

---

## システム構成

```
flask_entry/
├── app.py                # メインアプリ（ポート 5000）
├── capture_faces.py      # 顔撮影ツール（ポート 5001）
├── check_faces.py        # 顔画像チェックツール（ポート 5002）
├── encode_faces.py       # 特徴ベクトル生成（CLI）
├── face_engine.py        # 顔認識エンジン
├── attendance_manager.py # 出退勤状態管理 + CSV
├── slack_notifier.py     # Slack Webhook 通知
├── config.py             # 設定管理
├── config.json           # 設定ファイル（要編集、Git管理外）
├── config.json.example   # 設定テンプレート
├── requirements.txt
└── templates/
    └── index.html        # メインダッシュボード
```

---

## セットアップ

### 1. usbipd-win でカメラを WSL にブリッジ

管理者 PowerShell で実行：

```powershell
usbipd list
usbipd bind   --busid <BUSID>
usbipd attach --wsl --busid <BUSID> --auto-attach
```

WSL 側で確認：

```bash
ls /dev/video*
```

### 2. 依存パッケージをインストール

```bash
sudo apt update
sudo apt install -y cmake build-essential libopenblas-dev liblapack-dev

pip install -r requirements.txt
```

### 3. config.json を作成

```bash
cp config.json.example config.json
```

`config.json` を編集：

```json
{
  "slack": {
    "user_webhooks": {
      "sato":   "https://hooks.slack.com/services/XXX",
      "yamada": "https://hooks.slack.com/services/YYY"
    }
  },
  "settings": {
    "cooldown_sec": 5,
    "camera_index": 0,
    "face_tolerance": 0.5,
    "recognition_interval_ms": 500
  },
  "paths": {
    "encodings_pkl": "~/encodings.pkl",
    "log_csv": "logs/attendance.csv"
  }
}
```

> `camera_index` は `/dev/video0` なら `0`、`/dev/video4` なら `4`

---

## 顔登録手順

### Step 1. 顔画像を撮影

```bash
python capture_faces.py --name yamada --camera 4
# オプション: --count 枚数（デフォルト10） --interval 秒（デフォルト2.0）
```

`http://localhost:5001` を開いて「撮影開始」を押す。  
正面・左右・上下など角度を変えながら撮影すると精度が上がる。

### Step 2. チェック（任意）

```bash
python check_faces.py
```

`http://localhost:5002` で OK / NG を確認する。  
NG 画像（顔未検出・複数人）は登録に使われないため撮り直しを推奨。

### Step 3. 特徴ベクトルを生成

```bash
python encode_faces.py
```

`~/encodings.pkl` が生成される。  
メインアプリ起動中は「顔データ再読込」ボタンで即時反映できる。

---

## 起動

```bash
python app.py
```

ブラウザで `http://localhost:5000` にアクセス。

---

## 動作フロー

| 状況 | 動作 |
|------|------|
| 顔未検出 | 何もしない |
| 未登録の顔を検出 | 赤枠表示のみ |
| 当日初回の認識 | 自動で入室（+）記録・Slack 通知・顔画像保存 |
| 2回目以降の認識 | 退室確認ダイアログ表示 |
| ダイアログ → 退室する | 退室（-）記録・Slack 通知 |
| ダイアログ → キャンセル or 10秒放置 | 何もしない |
| 日付変更 | 全員の状態を自動リセット |

---

## ポート一覧

| ポート | ファイル | 用途 |
|--------|----------|------|
| 5000 | `app.py` | メインダッシュボード |
| 5001 | `capture_faces.py` | 顔画像撮影 |
| 5002 | `check_faces.py` | 顔画像チェック |

---

## CSV ログ形式

```
timestamp,user_name,action,date
2026-02-19 09:15:32,yamada,+,2026-02-19
2026-02-19 18:30:01,yamada,-,2026-02-19
```

保存先: `logs/attendance.csv`

---

## 顔画像ローカル保存

入室時の顔画像を自動保存する。

```
logs/images/yamada_2026-02-19_09-15-32.jpg
```

---

## config.json パラメータ

| キー | デフォルト | 説明 |
|------|-----------|------|
| slack.user_webhooks | `{}` | ユーザー別 Slack Webhook URL |
| settings.cooldown_sec | `5` | 同一人物の再認識抑制（秒） |
| settings.camera_index | `0` | カメラデバイス番号 |
| settings.face_tolerance | `0.5` | 認証閾値（低いほど厳格、推奨: 0.4〜0.5） |
| settings.recognition_interval_ms | `500` | 顔認識の実行間隔（ミリ秒） |
| paths.encodings_pkl | `~/encodings.pkl` | 特徴ベクトルの保存先 |
| paths.log_csv | `logs/attendance.csv` | 出退勤ログの保存先 |

---

## 常時稼働設定（任意）

### systemd で自動再起動

```bash
sudo nano /etc/systemd/system/face-entry.service
```

```ini
[Unit]
Description=Face Entry System
After=network.target

[Service]
User=kumamoto
WorkingDirectory=/home/kumamoto/project/face_recognition
ExecStart=/usr/bin/python3 app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable face-entry
```

### cron で時間制御（7:00 起動 / 21:00 停止）

```bash
crontab -e
```

```cron
0 7  * * * systemctl start  face-entry
0 21 * * * systemctl stop   face-entry
```

---

## Git 管理外のファイル

以下は `.gitignore` で除外されている：

- `config.json`（Webhook URL を含むため）
- `logs/`（出退勤ログ・顔画像）
- `new_faces/`（顔画像データ）
- `encodings.pkl`（顔の特徴ベクトル）
