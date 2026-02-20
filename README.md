# 顔認証 × Slack 通知 入退室システム

カメラで顔を認識し、入退室を自動判定して Slack に通知する Web アプリケーション。

---

## 機能

- リアルタイムカメラ映像（MJPEG ストリーミング）
- 顔検出（HOG）+ 顔認証（ResNet / dlib）
- 入室（+）/ 退室（-）の自動判定と CSV ログ記録
- ユーザー別 Slack Webhook 通知
- 入室時の顔画像ローカル保存（`logs/images/`）
- 退室確認ダイアログ（10秒で自動キャンセル）
- ブラウザからの顔データ再読込
- 再起動時の入退室状態復元（CSV から当日分を読み込み）
- 構造化ログ（`logs/app.log`、1MB ローテーション × 5世代）
- ウォッチドッグ（スレッド異常を検知して Slack アラート）
- USB カメラ監視（切断・再接続を検知して Slack アラート）

---

## ファイル構成

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
├── config.json           # 設定ファイル（要編集、Git 管理外）
├── config.json.example   # 設定テンプレート
├── requirements.txt
└── templates/
    └── index.html
```

---

## セットアップ

### 1. カメラを WSL にブリッジ（usbipd-win）

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

### 3. config.json を作成・編集

```bash
cp config.json.example config.json
```

```json
{
  "slack": {
    "user_webhooks": {
      "sato":   "https://hooks.slack.com/services/XXX",
      "yamada": "https://hooks.slack.com/services/YYY"
    },
    "alert_webhook": "https://hooks.slack.com/services/ZZZ"
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

`camera_index` は `/dev/video0` なら `0`、`/dev/video4` なら `4`。  
`alert_webhook` はシステム障害通知用（カメラ切断・スレッド異常など）。ユーザー別とは別に作成する。

---

## 顔登録手順

```bash
# Step 1. 顔画像を撮影
python capture_faces.py --name yamada --camera 4
# http://localhost:5001 を開いて「撮影開始」
# 正面・左右・上下など角度を変えて撮ると精度が上がる

# Step 2. 撮影結果を確認（任意）
python check_faces.py
# http://localhost:5002 で OK / NG を確認
# NG 画像（顔未検出・複数人）は撮り直し推奨

# Step 3. 特徴ベクトルを生成
python encode_faces.py
# ~/encodings.pkl が生成される
# 起動中は「顔データ再読込」ボタンで即時反映できる
```

---

## 起動

```bash
python app.py
# http://localhost:5000 にアクセス
```

---

## 動作フロー

| 状況 | 動作 |
|------|------|
| 顔未検出 | 何もしない |
| 未登録の顔を検出 | 赤枠表示のみ |
| 当日初回の認識 | 入室（+）記録・Slack 通知・顔画像保存 |
| 2回目以降の認識 | 退室確認ダイアログ表示 |
| ダイアログ → 退室する | 退室（-）記録・Slack 通知 |
| ダイアログ → キャンセル or 10秒放置 | 何もしない |
| 日付変更 | 全員の状態を自動リセット |
| 再起動 | CSV から当日の入退室状態を復元 |
| スレッド異常（10秒無応答） | Slack アラート通知 |
| カメラ切断 / 再接続 | Slack アラート通知 |

---

## ポート一覧

| ポート | ファイル | 用途 |
|--------|----------|------|
| 5000 | `app.py` | メインダッシュボード |
| 5001 | `capture_faces.py` | 顔画像撮影 |
| 5002 | `check_faces.py` | 顔画像チェック |

---

## config.json パラメータ

| キー | デフォルト | 説明 |
|------|-----------|------|
| slack.user_webhooks | `{}` | ユーザー別 Slack Webhook URL |
| slack.alert_webhook | `""` | システム障害通知用 Slack Webhook URL |
| settings.cooldown_sec | `5` | 同一人物の再認識抑制（秒） |
| settings.camera_index | `0` | カメラデバイス番号 |
| settings.face_tolerance | `0.5` | 認証閾値（低いほど厳格、推奨: 0.4〜0.5） |
| settings.recognition_interval_ms | `500` | 顔認識の実行間隔（ミリ秒） |
| paths.encodings_pkl | `~/encodings.pkl` | 特徴ベクトルの保存先 |
| paths.log_csv | `logs/attendance.csv` | 出退勤ログの保存先 |

---

## ログ

| ファイル | 内容 |
|----------|------|
| `logs/attendance.csv` | 入退室記録（全日分を追記） |
| `logs/app.log` | システムログ（1MB でローテーション、最大 5 世代） |
| `logs/images/` | 入室時の顔画像 |

---

## 常時稼働設定

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

```
0 7  * * * systemctl start  face-entry
0 21 * * * systemctl stop   face-entry
```

---

## Git 管理外のファイル

| ファイル / ディレクトリ | 理由 |
|------------------------|------|
| `config.json` | Webhook URL を含むため |
| `logs/` | 出退勤ログ・顔画像 |
| `new_faces/` | 顔画像データ |
| `encodings.pkl` | 顔の特徴ベクトル |
