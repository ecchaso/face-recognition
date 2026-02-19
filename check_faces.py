"""
顔画像チェックスクリプト - Flask 版 (ポート 5002)

使い方:
    python check_faces.py
    python check_faces.py --faces-dir ~/new_faces
"""

import os, glob, base64, threading, argparse
import cv2, face_recognition
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)
parser = argparse.ArgumentParser()
parser.add_argument("--faces-dir", default=os.path.expanduser("~/new_faces"))
args = parser.parse_args()
FACES_DIR = args.faces_dir

check_lock    = threading.Lock()
check_running = False
check_results = []

def run_check():
    global check_running, check_results
    with check_lock:
        if check_running: return
        check_running = True
        check_results = []

    paths   = sorted(glob.glob(os.path.join(FACES_DIR, "*", "*.jpg")))
    results = []

    for path in paths:
        person = os.path.basename(os.path.dirname(path))
        img    = cv2.imread(path)
        if img is None:
            results.append({"path": path, "person": person, "filename": os.path.basename(path),
                            "ok": False, "face_count": 0, "reason": "読み込み失敗", "thumb": None})
            with check_lock: check_results = list(results)
            continue

        rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb, model="hog")
        draw = img.copy()
        for (top, right, bottom, left) in locs:
            color = (139, 180, 250) if len(locs) == 1 else (243, 139, 168)
            cv2.rectangle(draw, (left, top), (right, bottom), color, 2)

        thumb   = cv2.resize(draw, (160, 120))
        _, buf  = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
        b64     = base64.b64encode(buf).decode()
        ok      = len(locs) == 1
        reason  = "OK" if ok else ("顔が検出されませんでした" if len(locs) == 0 else f"顔が {len(locs)} 人検出されました")

        results.append({"path": path, "person": person, "filename": os.path.basename(path),
                        "ok": ok, "face_count": len(locs), "reason": reason, "thumb": b64})
        with check_lock: check_results = list(results)

    with check_lock: check_running = False

HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><title>顔画像チェック</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Segoe UI", sans-serif; background: #11111b; color: #cdd6f4; padding: 24px; }
  header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
  h1 { font-size: 14px; font-weight: 800; letter-spacing: 2px; color: #89b4fa; }
  .summary { display: flex; gap: 20px; font-size: 14px; font-weight: 700; }
  .c-all { color: #cdd6f4; } .c-ok { color: #a6e3a1; } .c-ng { color: #f38ba8; }
  .filters { display: flex; gap: 8px; margin-left: auto; }
  .fb { padding: 5px 14px; border: none; border-radius: 8px; font-size: 12px; font-weight: 700;
        cursor: pointer; background: #313244; color: #a6adc8; }
  .fb.active { background: #89b4fa; color: #11111b; }
  .run-btn { padding: 9px 22px; border: none; border-radius: 8px; background: #89b4fa; color: #11111b;
             font-size: 13px; font-weight: 700; cursor: pointer; }
  .run-btn:hover { background: #b4d0ff; }
  .run-btn:disabled { background: #313244; color: #585b70; cursor: default; }
  #pb-wrap { height: 4px; background: #313244; border-radius: 2px; margin-bottom: 14px; display: none; }
  #pb { height: 100%; background: #89b4fa; border-radius: 2px; width: 0; transition: width 0.3s; }
  .grid { display: flex; flex-direction: column; gap: 8px; }
  .card { display: flex; align-items: center; gap: 12px; background: #1e1e2e;
          border-radius: 10px; border: 1px solid #313244; padding: 10px 14px; }
  .card.ok { background: #1e2a1e; border-color: #2d4a2d; }
  .card.ng { background: #2a1e1e; border-color: #4a2d2d; }
  .thumb { width: 120px; height: 90px; object-fit: cover; border-radius: 6px; flex-shrink: 0; }
  .no-thumb { width: 120px; height: 90px; flex-shrink: 0; background: #11111b; border-radius: 6px;
              display: flex; align-items: center; justify-content: center; font-size: 11px; color: #585b70; }
  .info { flex: 1; display: flex; flex-direction: column; gap: 4px; }
  .i-name { font-size: 13px; font-weight: 700; }
  .i-status { font-size: 12px; }
  .i-path { font-size: 10px; color: #585b70; }
  .s-ok { color: #a6e3a1; } .s-ng { color: #f38ba8; } .s-warn { color: #fab387; }
  #empty { color: #585b70; font-size: 14px; padding: 40px; text-align: center; }
</style></head>
<body>
<header>
  <h1>顔画像チェック</h1>
  <div class="summary">
    <span class="c-all">合計: <span id="s-all">—</span></span>
    <span class="c-ok">✅ OK: <span id="s-ok">—</span></span>
    <span class="c-ng">❌ NG: <span id="s-ng">—</span></span>
  </div>
  <div class="filters">
    <button class="fb active" id="f-all" onclick="filter('all')">すべて</button>
    <button class="fb"        id="f-ok"  onclick="filter('ok')">OK のみ</button>
    <button class="fb"        id="f-ng"  onclick="filter('ng')">NG のみ</button>
  </div>
  <button class="run-btn" id="run-btn" onclick="runCheck()">▶ チェック実行</button>
</header>
<div id="pb-wrap"><div id="pb"></div></div>
<div class="grid" id="grid"><div id="empty">「チェック実行」を押して開始してください</div></div>

<script>
  let curFilter = "all", cards = [];
  function filter(f) {
    curFilter = f;
    ["all","ok","ng"].forEach(id => document.getElementById("f-"+id).classList.toggle("active", id===f));
    cards.forEach(({el, ok}) => {
      el.style.display = (f==="all"||(f==="ok"&&ok)||(f==="ng"&&!ok)) ? "" : "none";
    });
  }
  async function runCheck() {
    const btn = document.getElementById("run-btn");
    btn.disabled = true; btn.textContent = "実行中...";
    document.getElementById("grid").innerHTML = "";
    cards = [];
    ["s-all","s-ok","s-ng"].forEach(id => document.getElementById(id).textContent = "—");
    await fetch("/api/run", { method: "POST" });
    const wrap = document.getElementById("pb-wrap"), pb = document.getElementById("pb");
    wrap.style.display = "block"; pb.style.width = "0%";
    const timer = setInterval(async () => {
      const d = await (await fetch("/api/results")).json();
      pb.style.width = (d.done ? 100 : d.progress) + "%";
      d.results.slice(cards.length).forEach(addCard);
      document.getElementById("s-all").textContent = d.results.length;
      document.getElementById("s-ok").textContent  = d.results.filter(r=>r.ok).length;
      document.getElementById("s-ng").textContent  = d.results.filter(r=>!r.ok).length;
      if (d.done) {
        clearInterval(timer); wrap.style.display = "none";
        btn.disabled = false; btn.textContent = "▶ 再チェック";
      }
    }, 400);
  }
  function addCard(r) {
    const grid = document.getElementById("grid");
    const el   = document.createElement("div");
    el.className = "card " + (r.ok ? "ok" : "ng");
    const sc = r.ok ? "s-ok" : (r.face_count===0 ? "s-ng" : "s-warn");
    const si = r.ok ? "✅" : (r.face_count===0 ? "❌" : "⚠️");
    el.innerHTML = r.thumb
      ? `<img class="thumb" src="data:image/jpeg;base64,${r.thumb}" alt="">`
      : `<div class="no-thumb">読込失敗</div>`;
    el.innerHTML += `<div class="info">
      <div class="i-name">${r.person} / ${r.filename}</div>
      <div class="i-status ${sc}">${si} ${r.reason}</div>
      <div class="i-path">${r.path}</div></div>`;
    grid.appendChild(el);
    cards.push({ el, ok: r.ok });
    filter(curFilter);
  }
</script>
</body></html>"""

@app.route("/")
def index(): return render_template_string(HTML)

@app.route("/api/run", methods=["POST"])
def api_run():
    threading.Thread(target=run_check, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/results")
def api_results():
    with check_lock:
        results = list(check_results)
        running = check_running
    total    = len(glob.glob(os.path.join(FACES_DIR, "*", "*.jpg")))
    progress = int(len(results) / max(total, 1) * 100)
    return jsonify({"results": results, "done": not running, "progress": progress})

if __name__ == "__main__":
    print(f"[Check] http://localhost:5002 で起動します")
    print(f"[Check] 対象: {FACES_DIR}")
    app.run(host="0.0.0.0", port=5002, threaded=True, debug=False)
