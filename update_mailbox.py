"""Ordered, bounded hand-off from transport workers to the OBS thread."""

from collections import deque
from threading import Lock


class UpdateMailbox:
    def __init__(self, capacity=200):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._lock = Lock()
        self._items = deque()
        self._token = 0
        self._dropped = 0

    def new_token(self):
        with self._lock:
            self._token += 1
            self._items.clear()
            self._dropped = 0
            return self._token

    def publish(self, item, token):
        return self.publish_many([item], token)

    def publish_many(self, items, token):
        with self._lock:
            if token != self._token:
                return False
            for item in items:
                if len(self._items) == self.capacity:
                    self._items.popleft()
                    self._dropped += 1
                self._items.append(item)
            return True

    def drain(self):
        with self._lock:
            items = list(self._items)
            self._items.clear()
            dropped = self._dropped
            self._dropped = 0
        return items, dropped