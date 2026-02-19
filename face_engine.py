"""
顔認識エンジン

encode_faces.py が生成した ~/encodings.pkl を読み込み、
カメラフレームから人物を識別する。

pkl のデータ構造:
    {"names": [str, ...], "encodings": [np.ndarray, ...]}

フレーム内で最も大きい顔（カメラに近い人）を1人だけ処理する。
face_distance の最小値で判定するため複数枚登録でも精度が上がる。
"""

import pickle
import face_recognition
import numpy as np
import cv2
from pathlib import Path


class FaceEngine:
    def __init__(self, pkl_path: str = "~/encodings.pkl", tolerance: float = 0.5):
        self.pkl_path  = Path(pkl_path).expanduser()
        self.tolerance = tolerance
        self.known_encodings: list[np.ndarray] = []
        self.known_names:     list[str]        = []
        self.load_faces()

    def load_faces(self):
        """encodings.pkl から特徴ベクトルをロードする"""
        self.known_encodings = []
        self.known_names     = []

        if not self.pkl_path.exists():
            print(f"[FaceEngine] {self.pkl_path} が見つかりません。"
                  "encode_faces.py を先に実行してください。")
            return

        with open(self.pkl_path, "rb") as f:
            data = pickle.load(f)

        self.known_names     = data["names"]
        self.known_encodings = data["encodings"]

        unique = set(self.known_names)
        print(f"[FaceEngine] ロード完了: "
              f"{len(self.known_names)} 枚 / {len(unique)} 人 "
              f"({', '.join(sorted(unique))})")

    def recognize(self, frame: np.ndarray) -> tuple[str | None, tuple | None]:
        """
        フレームから最大の顔を1人だけ識別する。

        Returns:
            (name, face_location)   登録済みの場合
            ("unknown", face_location)  未登録の場合
            (None, None)  顔が検出されなかった場合
        """
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            return None, None

        # 面積最大の顔を選ぶ
        largest = max(
            locations,
            key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3])
        )

        encodings = face_recognition.face_encodings(rgb, [largest])
        if not encodings:
            return None, largest

        enc = encodings[0]

        if not self.known_encodings:
            return "unknown", largest

        distances = face_recognition.face_distance(self.known_encodings, enc)
        best_idx  = int(np.argmin(distances))

        if distances[best_idx] <= self.tolerance:
            return self.known_names[best_idx], largest
        else:
            return "unknown", largest

    @property
    def unique_names(self) -> list[str]:
        return sorted(set(self.known_names))
