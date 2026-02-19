#!/usr/bin/env python3
"""
顔特徴ベクトル生成スクリプト（CLI）

使い方:
    python encode_faces.py
    python encode_faces.py --faces-dir ~/new_faces --out ~/encodings.pkl
"""

import os, sys, glob, pickle, argparse, json
import cv2, face_recognition


def load_pkl_path():
    try:
        with open("config.json") as f:
            return json.load(f).get("paths", {}).get("encodings_pkl", "~/encodings.pkl")
    except:
        return "~/encodings.pkl"


def main():
    default_out = os.path.expanduser(load_pkl_path())
    parser = argparse.ArgumentParser()
    parser.add_argument("--faces-dir", default=os.path.expanduser("~/new_faces"))
    parser.add_argument("--out",       default=default_out)
    args = parser.parse_args()

    base     = args.faces_dir
    out_path = args.out

    if not os.path.isdir(base):
        print(f"❌ フォルダが見つかりません: {base}")
        sys.exit(1)

    print(f"📂 顔画像フォルダ: {base}")
    print(f"💾 出力先        : {out_path}\n")

    names, encs, skipped = [], [], 0
    persons = sorted([p for p in os.listdir(base) if os.path.isdir(os.path.join(base, p))])

    if not persons:
        print("❌ new_faces/ 内に人物フォルダが見つかりません。")
        sys.exit(1)

    for person in persons:
        images = sorted(glob.glob(os.path.join(base, person, "*.jpg")))
        if not images:
            print(f"⚠  {person}: jpg が見つかりません、スキップ")
            continue
        print(f"👤 {person} ({len(images)} 枚)")
        count = 0
        for path in images:
            img = cv2.imread(path)
            if img is None:
                print(f"   ❌ 読み込み失敗: {os.path.basename(path)}")
                skipped += 1
                continue
            rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb, model="hog")
            if len(locs) != 1:
                print(f"   ⚠  スキップ（顔 {len(locs)} 人）: {os.path.basename(path)}")
                skipped += 1
                continue
            enc = face_recognition.face_encodings(rgb, locs)[0]
            names.append(person)
            encs.append(enc)
            count += 1
            print(f"   ✅ {os.path.basename(path)}")
        print(f"   → {count} 枚採用\n")

    if not encs:
        print("❌ 有効な顔画像が見つかりませんでした。")
        sys.exit(1)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump({"names": names, "encodings": encs}, f)

    print("─" * 40)
    print(f"🎉 完了: {len(encs)} 枚 / {len(set(names))} 人 → {out_path}")
    print(f"   スキップ: {skipped} 枚")
    print(f"   登録人物: {', '.join(sorted(set(names)))}")


if __name__ == "__main__":
    main()
