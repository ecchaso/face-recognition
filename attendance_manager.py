"""
出退勤状態管理 + CSV ログ

判定ロジック:
    当日初回の顔認識  → "entry"        （自動で + 記録）
    当日2回目以降     → "exit_confirm"  （ブラウザ側でダイアログ表示）

状態リセット:
    日付が変わると全員の状態を自動リセット。
    退室（-）を記録した人は当日中でも再入室できる。
"""

import csv
from datetime import datetime, date
from pathlib import Path


class AttendanceManager:
    def __init__(self, log_csv: str = "logs/attendance.csv"):
        self.log_path = Path(log_csv)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()
        self._state: dict[str, dict] = {}

    def _ensure_header(self):
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["timestamp", "user_name", "action", "date"])

    def _get_state(self, user: str) -> dict:
        today = date.today()
        s = self._state.get(user)
        if s is None or s["date"] != today:
            self._state[user] = {"date": today, "entered": False}
        return self._state[user]

    def _write_log(self, dt: datetime, user: str, action: str):
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                dt.strftime("%Y-%m-%d %H:%M:%S"),
                user, action,
                dt.strftime("%Y-%m-%d")
            ])

    def check_action(self, user: str) -> str:
        """
        "entry"        → 当日初回（自動入室）
        "exit_confirm" → 2回目以降（ダイアログ確認が必要）
        """
        return "entry" if not self._get_state(user)["entered"] else "exit_confirm"

    def record_entry(self, user: str) -> datetime:
        self._get_state(user)["entered"] = True
        now = datetime.now()
        self._write_log(now, user, "+")
        return now

    def record_exit(self, user: str) -> datetime:
        """退室記録 + 状態リセット（当日中の再入室に対応）"""
        self._get_state(user)["entered"] = False
        now = datetime.now()
        self._write_log(now, user, "-")
        return now

    def is_inside(self, user: str) -> bool:
        return self._get_state(user)["entered"]
