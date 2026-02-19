"""
顔画像撮影スクリプト - Flask 版 (ポート 5001)

使い方:
    python capture_faces.py --name yamada
    python capture_faces.py --name yamada --count 15 --interval 2.0 --camera 4
"""

import os, time, argparse, threading
import cv2
from flask import Flask, Response, render_template_string, jsonify

app  = Flask(__name__)
parser = argparse.ArgumentParser()
parser.add_argument("--name",     required=True)
parser.add_argument("--count",    type=int,   default=10)
parser.add_argument("--interval", type=float, default=2.0)
parser.add_argument("--camera",   type=int,   default=0)
args = parser.parse_args()

OUT_DIR   = os.path.expanduser(f"~/new_faces/{args.name}")
os.makedirs(OUT_DIR, exist_ok=True)
start_idx = len([f for f in os.listdir(OUT_DIR) if f.endswith(".jpg")])

frame_lock   = threading.Lock()
latest_frame = None

def camera_worker():
    global latest_frame
    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC,       cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS,          15)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
    for _ in range(5): cap.read()
    while True:
        ret, frame = cap.read()
        if ret:
            with frame_lock: latest_frame = frame.copy()
        time.sleep(1/15)

threading.Thread(target=camera_worker, daemon=True).start()

state      = {"saved": 0, "total": args.count, "shooting": False, "message": "撮影開始ボタンを押してください"}
state_lock = threading.Lock()

def do_capture():
    with state_lock: state["shooting"] = True
    for i in range(args.count):
        for c in range(max(1, int(args.interval)), 0, -1):
            with state_lock: state["message"] = f"撮影まで {c} 秒..."
            time.sleep(1)
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is None:
            with state_lock: state["message"] = "フレーム取得失敗、リトライ..."
            time.sleep(0.5)
            continue
        with state_lock: idx = start_idx + state["saved"]
        filename = os.path.join(OUT_DIR, f"{args.name}_{idx:03d}.jpg")
        cv2.imwrite(filename, frame)
        with state_lock:
            state["saved"] += 1
            state["message"] = f"✅ 保存: {os.path.basename(filename)}"
        print(f"  📸 [{state['saved']:02d}/{args.count}] {os.path.basename(filename)}")
    with state_lock:
        state["shooting"] = False
        state["message"]  = "🎉 完了！ encode_faces.py を実行してください"

def generate_frames():
    while True:
        with frame_lock: frame = latest_frame
        if frame is None: time.sleep(0.05); continue
        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret: yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        time.sleep(1/15)

HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><title>顔画像撮影 - {{ name }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Segoe UI", sans-serif; background: #11111b; color: #cdd6f4;
         display: flex; flex-direction: column; align-items: center; padding: 28px 20px; gap: 16px; }
  h1 { font-size: 14px; font-weight: 800; letter-spacing: 2px; color: #89b4fa; }
  .cam { width: 640px; max-width: 100%; border-radius: 14px; border: 2px solid #313244;
         overflow: hidden; background: #1e1e2e; }
  .cam img { width: 100%; display: block; }
  .row { display: flex; width: 640px; max-width: 100%; justify-content: space-between; align-items: center; }
  #progress { font-size: 16px; font-weight: 700; color: #89b4fa; }
  #message  { font-size: 13px; color: #a6adc8; }
  .btns { display: flex; gap: 12px; }
  button { padding: 10px 28px; border: none; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .start { background: #89b4fa; color: #11111b; }
  .start:hover { background: #b4d0ff; }
  .start:disabled { background: #313244; color: #585b70; cursor: default; }
  .close { background: #313244; color: #cdd6f4; }
  .close:hover { background: #45475a; }
  .info { font-size: 11px; color: #6c7086; }
</style></head>
<body>
  <h1>顔画像撮影 — {{ name }}</h1>
  <div class="cam"><img src="/video_feed" alt="camera"></div>
  <div class="row">
    <div id="progress">0 / {{ total }} 枚</div>
    <div id="message">撮影開始ボタンを押してください</div>
  </div>
  <div class="btns">
    <button class="start" id="btn" onclick="start()">▶ 撮影開始</button>
    <button class="close" onclick="window.close()">閉じる</button>
  </div>
  <div class="info">保存先: ~/new_faces/{{ name }}/　既存: {{ existing }} 枚</div>
  <script>
    let timer;
    async function start() {
      document.getElementById("btn").disabled = true;
      await fetch("/api/start", { method: "POST" });
      timer = setInterval(async () => {
        const d = await (await fetch("/api/state")).json();
        document.getElementById("progress").textContent = d.saved + " / {{ total }} 枚";
        document.getElementById("message").textContent  = d.message;
        if (!d.shooting) {
          clearInterval(timer);
          const b = document.getElementById("btn");
          b.disabled = false; b.textContent = "▶ もう一度撮影";
        }
      }, 500);
    }
  </script>
</body></html>"""

@app.route("/")
def index(): return render_template_string(HTML, name=args.name, total=args.count, existing=start_idx)

@app.route("/video_feed")
def video_feed(): return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/start", methods=["POST"])
def api_start():
    with state_lock:
        if state["shooting"]: return jsonify({"ok": False})
    threading.Thread(target=do_capture, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/state")
def api_state():
    with state_lock: return jsonify(dict(state))

if __name__ == "__main__":
    print(f"[Capture] http://localhost:5001 で起動します")
    print(f"[Capture] 保存先: {OUT_DIR}  既存: {start_idx} 枚")
    app.run(host="0.0.0.0", port=5001, threaded=True, debug=False)
