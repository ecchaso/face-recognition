"""
顔認証エントリーシステム - Flask メインアプリ

起動方法:
    python app.py
ブラウザで http://localhost:5000 にアクセス
"""

import cv2
import time
import threading
from datetime import datetime

from flask import Flask, Response, render_template, jsonify, request

from config import Config
from face_engine import FaceEngine
from attendance_manager import AttendanceManager
from slack_notifier import SlackNotifier

app = Flask(__name__)

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
        print(f"[Camera] カメラ {idx} を開けませんでした")
        return

    print(f"[Camera] 起動 (index={idx}, MJPG, 640x480, 15fps)")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

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
        print(f"[Recognition] {name} → {action}")

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
            print(f"[Entry] {name} {dt.strftime('%H:%M:%S')}")

        elif action == "exit_confirm":
            with status_lock:
                status["pending_exit"] = name
            print(f"[ExitConfirm] {name} 退室確認待ち")


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
        print(f"[Exit] {user} {dt.strftime('%H:%M:%S')}")
    else:
        print(f"[ExitCancelled] {user}")

    return jsonify({"ok": True})


@app.route("/api/reload_faces", methods=["POST"])
def api_reload_faces():
    """encodings.pkl を再読込する"""
    face_engine.load_faces()
    return jsonify({"ok": True, "users": face_engine.unique_names})


# ══════════════════════════════════════════════
# エントリーポイント
# ══════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=camera_worker,      daemon=True).start()
    threading.Thread(target=recognition_worker, daemon=True).start()
    print("[App] http://localhost:5000 で起動します")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
