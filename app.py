"""
顔認証エントリーシステム - Flask メインアプリ

起動方法:
    python app.py
ブラウザで http://localhost:5000 にアクセス
"""

import cv2
import time
import threading
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, render_template, jsonify, request

from config import Config
from face_engine import FaceEngine
from attendance_manager import AttendanceManager
from slack_notifier import SlackNotifier

app = Flask(__name__)

# ══════════════════════════════════════════════
# 構造化ログ設定
# ══════════════════════════════════════════════
def setup_logger() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("face_entry")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # ファイル: 1MB で最大5世代ローテーション
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    # コンソール
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

logger = setup_logger()

# ══════════════════════════════════════════════
# 初期化
# ══════════════════════════════════════════════
config = Config("config.json")

face_engine = FaceEngine(
    pkl_path  = config.get("paths",    "encodings_pkl"),
    tolerance = config.get("settings", "face_tolerance")
)
attendance = AttendanceManager(
    log_csv = config.get("paths", "log_csv")
)
notifier = SlackNotifier(
    user_webhooks = config.get("slack", "user_webhooks") or {},
    alert_webhook = config.get("slack", "alert_webhook") or "",
)

# ══════════════════════════════════════════════
# 共有状態
# ══════════════════════════════════════════════
frame_lock    = threading.Lock()
raw_frame     = None   # 認識処理用（生フレーム）
display_frame = None   # MJPEG配信用（顔枠描画済み）

face_lock   = threading.Lock()
latest_face = {"name": None, "loc": None}

status_lock = threading.Lock()
status = {
    "user":         None,
    "action":       None,    # "entry" / "exit"
    "time":         None,
    "pending_exit": None,    # 退室確認待ちのユーザー名
}

cooldown_sec  = config.get("settings", "cooldown_sec")
last_rec_lock = threading.Lock()
last_rec_times: dict[str, datetime] = {}

# ウォッチドッグ用ハートビート（各スレッドが定期更新）
heartbeat_lock = threading.Lock()
heartbeat: dict[str, float] = {
    "camera":      time.time(),
    "recognition": time.time(),
}


# ══════════════════════════════════════════════
# カメラスレッド
# ══════════════════════════════════════════════
def camera_worker():
    global raw_frame, display_frame

    idx = config.get("settings", "camera_index")
    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC,       cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS,          15)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

    if not cap.isOpened():
        logger.error(f"カメラ {idx} を開けませんでした")
        return

    logger.info(f"カメラ起動 (index={idx}, MJPG, 640x480, 15fps)")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        # ウォッチドッグ用ハートビート更新
        with heartbeat_lock:
            heartbeat["camera"] = time.time()

        # 最新の顔検出結果で毎フレーム枠を描画（15fps を維持）
        with face_lock:
            name = latest_face["name"]
            loc  = latest_face["loc"]

        draw = frame.copy()
        if loc:
            top, right, bottom, left = loc
            color = (139, 180, 250) if (name and name != "unknown") \
                    else (243, 139, 168)
            cv2.rectangle(draw, (left, top), (right, bottom), color, 2)
            if name and name != "unknown":
                cv2.putText(draw, name, (left, top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)

        with frame_lock:
            raw_frame     = frame.copy()
            display_frame = draw


# ══════════════════════════════════════════════
# 顔認識スレッド
# ══════════════════════════════════════════════
def recognition_worker():
    interval = config.get("settings", "recognition_interval_ms") / 1000.0

    while True:
        time.sleep(interval)

        # ウォッチドッグ用ハートビート更新
        with heartbeat_lock:
            heartbeat["recognition"] = time.time()

        # 退室確認待ち中は認識しない
        with status_lock:
            if status["pending_exit"] is not None:
                continue

        with frame_lock:
            if raw_frame is None:
                continue
            frame = raw_frame.copy()

        name, face_loc = face_engine.recognize(frame)

        # 顔検出結果を保存（描画は camera_worker が毎フレーム行う）
        with face_lock:
            latest_face["name"] = name
            latest_face["loc"]  = face_loc

        if not name or name == "unknown":
            # unknown の顔画像をクールダウン付きで保存
            if name == "unknown" and face_loc is not None:
                now = datetime.now()
                with last_rec_lock:
                    last = last_rec_times.get("unknown")
                    if not last or (now - last).total_seconds() >= cooldown_sec:
                        last_rec_times["unknown"] = now
                        with frame_lock:
                            unknown_frame = raw_frame.copy() if raw_frame is not None else None
                        if unknown_frame is not None:
                            notifier.save_unknown_image(unknown_frame, now)
            continue

        # クールダウンチェック
        now = datetime.now()
        with last_rec_lock:
            last = last_rec_times.get(name)
            if last and (now - last).total_seconds() < cooldown_sec:
                continue
            last_rec_times[name] = now

        # 出退勤判定
        action = attendance.check_action(name)
        logger.info(f"認識: {name} → {action}")

        if action == "entry":
            dt = attendance.record_entry(name)
            with frame_lock:
                entry_frame = raw_frame.copy() if raw_frame is not None else None
            notifier.notify_entry(name, dt, face_frame=entry_frame)
            with status_lock:
                status.update({
                    "user":         name,
                    "action":       "entry",
                    "time":         dt.strftime("%H:%M:%S"),
                    "pending_exit": None,
                })
            logger.info(f"入室: {name} {dt.strftime('%H:%M:%S')}")

        elif action == "exit_confirm":
            with status_lock:
                status["pending_exit"] = name
            logger.info(f"退室確認待ち: {name}")


# ══════════════════════════════════════════════
# MJPEG ストリーム
# ══════════════════════════════════════════════
def generate_frames():
    while True:
        with frame_lock:
            frame = display_frame

        if frame is None:
            time.sleep(0.05)
            continue

        ret, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
        )
        if ret:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n"
                   + buf.tobytes() + b"\r\n")
        time.sleep(1 / 15)


# ══════════════════════════════════════════════
# Flask ルート
# ══════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html",
                           users=face_engine.unique_names)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/api/status")
def api_status():
    """500ms ポーリング用：現在の状態を返す"""
    with status_lock:
        return jsonify(status.copy())


@app.route("/api/exit_confirm", methods=["POST"])
def api_exit_confirm():
    """退室確認ダイアログの応答を受け取る"""
    confirmed = request.get_json().get("confirmed", False)

    with status_lock:
        user = status.get("pending_exit")
        status["pending_exit"] = None

    if not user:
        return jsonify({"ok": False, "error": "no pending exit"})

    if confirmed:
        dt = attendance.record_exit(user)
        notifier.notify_exit(user, dt)
        with status_lock:
            status.update({
                "user":   user,
                "action": "exit",
                "time":   dt.strftime("%H:%M:%S"),
            })
        logger.info(f"退室: {user} {dt.strftime('%H:%M:%S')}")
    else:
        logger.info(f"退室キャンセル: {user}")

    return jsonify({"ok": True})


@app.route("/api/reload_faces", methods=["POST"])
def api_reload_faces():
    """encodings.pkl を再読込する"""
    face_engine.load_faces()
    return jsonify({"ok": True, "users": face_engine.unique_names})


# ══════════════════════════════════════════════
# ウォッチドッグスレッド
# ══════════════════════════════════════════════

# 各スレッドのハートビートがこの秒数を超えたら異常とみなす
WATCHDOG_TIMEOUT_SEC = 10
WATCHDOG_INTERVAL_SEC = 5

def watchdog_worker():
    """camera_worker / recognition_worker のハートビートを監視する"""
    # アラート送信の連続抑制（同じ異常で何度も送らない）
    alerted: dict[str, bool] = {"camera": False, "recognition": False}

    while True:
        time.sleep(WATCHDOG_INTERVAL_SEC)
        now = time.time()

        with heartbeat_lock:
            beats = heartbeat.copy()

        for name, last in beats.items():
            elapsed = now - last
            if elapsed > WATCHDOG_TIMEOUT_SEC:
                if not alerted[name]:
                    msg = f"{name}_worker が {elapsed:.0f}秒間応答なし"
                    logger.error(f"[Watchdog] {msg}")
                    notifier.notify_alert(msg)
                    alerted[name] = True
            else:
                if alerted[name]:
                    msg = f"{name}_worker が復旧しました"
                    logger.info(f"[Watchdog] {msg}")
                    notifier.notify_alert(msg)
                    alerted[name] = False


# ══════════════════════════════════════════════
# USB カメラ監視スレッド
# ══════════════════════════════════════════════

USB_CHECK_INTERVAL_SEC = 10

def usb_monitor_worker():
    """カメラデバイスファイルの存在を監視する"""
    idx = config.get("settings", "camera_index")
    device_path = Path(f"/dev/video{idx}")
    was_present = device_path.exists()

    while True:
        time.sleep(USB_CHECK_INTERVAL_SEC)
        now_present = device_path.exists()

        if was_present and not now_present:
            msg = f"カメラデバイス {device_path} が切断されました"
            logger.error(f"[USBMonitor] {msg}")
            notifier.notify_alert(msg)

        elif not was_present and now_present:
            msg = f"カメラデバイス {device_path} が再接続されました"
            logger.info(f"[USBMonitor] {msg}")
            notifier.notify_alert(msg)

        was_present = now_present


# ══════════════════════════════════════════════
# エントリーポイント
# ══════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=camera_worker,      daemon=True).start()
    threading.Thread(target=recognition_worker, daemon=True).start()
    threading.Thread(target=watchdog_worker,    daemon=True).start()
    threading.Thread(target=usb_monitor_worker, daemon=True).start()
    logger.info("http://localhost:5000 で起動します")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
