"""Per-user conversation ownership store.

On the shared account, the conversation history list is account-wide, so
without filtering every user would see everyone's conversations. We attribute
each conversation id opened in a user's tab to that user (data/ownership.json)
and tell the injected page script which sidebar entries to show.

Structure: {username: {platform: {conversation_id: created_timestamp}}}
"""
import os
import json
import time
import threading


class OwnershipStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def _save_locked(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def add(self, user, platform, conv_id):
        """Attribute a conversation to a user; returns True if newly added."""
        if not conv_id:
            return False
        with self.lock:
            plat = self.data.setdefault(user, {}).setdefault(platform, {})
            if conv_id in plat:
                return False
            plat[conv_id] = time.time()
            self._save_locked()
            return True

    def get(self, user, platform):
        with self.lock:
            return list(self.data.get(user, {}).get(platform, {}).keys())
