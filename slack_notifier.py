"""
Slack 通知モジュール（Webhook のみ）

config.json の user_webhooks にユーザー名と Webhook URL を設定する。
入室・退室とも同じ URL に通知する。
登録されていないユーザーは通知しない。
入室時の顔画像は logs/images/ にローカル保存する。
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime

import cv2
import numpy as np


class SlackNotifier:
    def __init__(
        self,
        user_webhooks: dict = None,
        proxy_url:     str  = "http://wwwproxy.kanazawa-it.ac.jp:8080",
        timeout_sec:   int  = 20,
    ):
        self.user_webhooks = user_webhooks or {}
        self.timeout_sec   = timeout_sec

        proxy_handler = urllib.request.ProxyHandler({
            "http":  proxy_url,
            "https": proxy_url,
        })
        self.opener = urllib.request.build_opener(proxy_handler)

    def notify_entry(self, user: str, dt: datetime,
                     face_frame: np.ndarray | None = None):
        """入室通知 + 顔画像ローカル保存"""
        self._send(user, f"+ {user} {dt.strftime('%H:%M:%S')}")
        if face_frame is not None:
            self._save_image(face_frame, user, dt)

    def notify_exit(self, user: str, dt: datetime):
        """退室通知"""
        self._send(user, f"- {user} {dt.strftime('%H:%M:%S')}")

    def _send(self, user: str, text: str):
        url = self.user_webhooks.get(user, "")
        if not url:
            print(f"[Slack] {user} の Webhook 未設定のためスキップ")
            return
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with self.opener.open(req, timeout=self.timeout_sec):
                print(f"[Slack] 送信成功: {text}")
        except urllib.error.URLError as e:
            print(f"[Slack] 送信失敗: {e}")

    def _save_image(self, frame: np.ndarray, user: str, dt: datetime):
        """顔画像を logs/images/ にローカル保存する"""
        save_dir = os.path.join("logs", "images")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{user}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
        filepath = os.path.join(save_dir, filename)
        if cv2.imwrite(filepath, frame):
            print(f"[Local] 顔画像保存: {filepath}")
        else:
            print(f"[Local] 顔画像保存失敗: {filepath}")
