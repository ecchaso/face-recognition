"""
Slack 通知モジュール（KIT プロキシ対応・全リクエスト・リダイレクト対応版）
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from typing import Any

import cv2
import numpy as np


class SlackNotifier:
    def __init__(
        self,
        entry_webhook: str,
        exit_webhook: str,
        alert_webhook: str = "",
        bot_token: str = "",
        channel_id: str = "",
        timeout_sec: int = 20,
        debug: bool = True,
    ):
        self.entry_webhook = entry_webhook
        self.exit_webhook = exit_webhook
        self.alert_webhook = alert_webhook
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.timeout_sec = timeout_sec
        self.debug = debug

        # ──────────────────────────────────────────
        # KIT プロキシの設定
        # ──────────────────────────────────────────
        self.proxy_url = "http://wwwproxy.kanazawa-it.ac.jp:8080"
        
        # プロキシハンドラを作成し、urllibのデフォルトの「開き方」として登録
        proxy_handler = urllib.request.ProxyHandler({
            "http": self.proxy_url,
            "https": self.proxy_url
        })
        self.opener = urllib.request.build_opener(proxy_handler)
        # これ以降、self.opener.open() を使うことでプロキシを経由します

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────
    def notify_entry(self, user: str, dt: datetime, face_frame: np.ndarray | None = None):
        text = f"+ {user} {dt.strftime('%H:%M:%S')}"
        if self._bot_mode():
            self._post_message(text)
        else:
            self._webhook(self.entry_webhook, text)
        # 顔画像をローカルに保存
        if face_frame is not None:
            self._save_image(face_frame, user, dt)

    def notify_exit(self, user: str, dt: datetime):
        text = f"- {user} {dt.strftime('%H:%M:%S')}"
        if self._bot_mode():
            self._post_message(text)
        else:
            self._webhook(self.exit_webhook, text)

    def notify_alert(self, message: str):
        """システム障害・異常をアラート用 Webhook に通知する"""
        if not self.alert_webhook:
            self._log(f"[Alert] alert_webhook 未設定のため送信スキップ: {message}")
            return
        text = f":warning: [SYSTEM ALERT] {message}"
        try:
            self._webhook(self.alert_webhook, text)
            self._log(f"[Alert] 送信: {message}")
        except Exception as e:
            self._log(f"[Alert] 送信失敗: {e}")

    # ──────────────────────────────────────────
    # 汎用 HTTP リクエスト（プロキシ & リダイレクト対応）
    # ──────────────────────────────────────────
    def _http_request(self, url: str, method: str, data: bytes, headers: dict) -> bytes:
        """プロキシを経由し、リダイレクト(302等)を検出し再送する"""
        
        # POST/PUT の場合、Content-Length を明示的に設定
        headers["Content-Length"] = str(len(data))
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            # urlopen ではなく、プロキシ設定済みの opener を使用
            with self.opener.open(req, timeout=self.timeout_sec) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            # 301, 302, 307, 308 のリダイレクト処理
            if e.code in (301, 302, 307, 308):
                new_url = e.headers.get("Location")
                if new_url:
                    self._log(f"[DEBUG] {e.code} Redirecting: {url} -> {new_url}")
                    return self._http_request(new_url, method, data, headers)
            
            return e.read()
        except Exception as e:
            self._log(f"[CRITICAL] Network Error: {e}")
            raise e

    # ──────────────────────────────────────────
    # Slack API / 個別処理 (変更なし)
    # ──────────────────────────────────────────
    def _slack_api_call(self, method: str, data: bytes, is_json: bool) -> dict[str, Any]:
        url = f"https://slack.com/api/{method}"
        ct = "application/json; charset=utf-8" if is_json else "application/x-www-form-urlencoded"
        headers = {
            "Content-Type": ct,
            "Authorization": f"Bearer {self.bot_token}",
        }
        raw_res = self._http_request(url, "POST", data, headers)
        try:
            return json.loads(raw_res)
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid_response", "raw": raw_res.decode()[:200]}

    def _post_message(self, text: str) -> str | None:
        payload = {"channel": self.channel_id, "text": text}
        res = self._slack_api_call("chat.postMessage", json.dumps(payload).encode(), True)
        if res.get("ok"): return res.get("ts")
        print(f"[Slack] メッセージ送信失敗: {res}")
        return None

    def _save_image(self, frame: np.ndarray, user: str, dt: datetime):
        """顔画像を logs/images/ にローカル保存する"""
        import os
        save_dir = os.path.join("logs", "images")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{user}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
        filepath = os.path.join(save_dir, filename)
        ret = cv2.imwrite(filepath, frame)
        if ret:
            self._log(f"[Local] 顔画像保存: {filepath}")
        else:
            print(f"[Local] 顔画像保存失敗: {filepath}")

    def save_unknown_image(self, frame: np.ndarray, dt: datetime):
        """未登録人物の顔画像を logs/images/unknown/ に保存する"""
        import os
        save_dir = os.path.join("logs", "images", "unknown")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"unknown_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
        filepath = os.path.join(save_dir, filename)
        ret = cv2.imwrite(filepath, frame)
        if ret:
            self._log(f"[Local] unknown 顔画像保存: {filepath}")
        else:
            print(f"[Local] unknown 顔画像保存失敗: {filepath}")


    def _bot_mode(self) -> bool:
        return bool(self.bot_token and self.channel_id)

    def _log(self, *args):
        if self.debug: print(*args)

    def _webhook(self, url: str, text: str):
        if not url: return
        try:
            self._http_request(url, "POST", json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
        except: pass