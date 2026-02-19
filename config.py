"""
設定管理モジュール
config.json を読み込み、アプリ全体に提供する。
キーが存在しない場合はデフォルト値で補完する。
"""

import json
from pathlib import Path

DEFAULT = {
    "slack": {
        "user_webhooks": {}
    },
    "settings": {
        "cooldown_sec":            5,
        "camera_index":            0,
        "face_tolerance":          0.5,
        "recognition_interval_ms": 500
    },
    "paths": {
        "encodings_pkl": "~/encodings.pkl",
        "log_csv":       "logs/attendance.csv"
    }
}


class Config:
    def __init__(self, path: str = "config.json"):
        self._path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            self._write(DEFAULT)
            print(f"[Config] {self._path} を新規作成しました。")
            return DEFAULT.copy()

        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        merged = {}
        for key, default_val in DEFAULT.items():
            if isinstance(default_val, dict):
                merged[key] = {**default_val, **raw.get(key, {})}
            else:
                merged[key] = raw.get(key, default_val)
        return merged

    def _write(self, data: dict):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get(self, *keys, default=None):
        """config.get("settings", "cooldown_sec") のように使う"""
        val = self._data
        for k in keys:
            if not isinstance(val, dict):
                return default
            val = val.get(k, default)
        return val
