from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
from typing import Any, Callable
from urllib.request import urlopen
import json
import requests

import websocket

import logging

_LOGGER = logging.getLogger(__name__)

@dataclass
class MiniDSPApi:
    """Class to keep track of MiniDSP API."""
    host: str
    port: int
    device_id: int
    websocket: bool

    @staticmethod
    def from_dict(dictionary: dict) -> MiniDSPApi:
        return MiniDSPApi(dictionary["host"], dictionary["port"], dictionary["device_id"], dictionary["websocket"])

    def verify_connection(self) -> None:
        urlopen(self.get_device_url())

    def verify_ws_connection(self) -> None:
        if self.websocket:
            ws = websocket.WebSocket()
            try:
                ws.connect(self.get_ws_device_url(False))
            except Exception as ex:
                raise ex
            finally:
                ws.close()

    def get_device_url(self) -> str:
        return "http://{}:{}/devices/{}".format(self.host, self.port, self.device_id)

    def get_ws_device_url(self, poll: bool = True) -> str:
        return "ws://{}:{}/devices/{}?poll={}".format(self.host, self.port, self.device_id, poll)

class MiniDSPApiConnection:
    api: MiniDSPApi
    ws: websocket.WebSocketApp | None
    last_state: dict[str, Any] = {}
    thread: Thread | None = None
    on_updated_callback: Callable[[dict[str, Any]], None] | None = None

    def __init__(self, api, last_state):
        self.on_updated_callback = None
        self.api = api
        self.last_state = last_state

    def __del__(self):
        if self.ws:
            self.ws.close()

    def merge_dicts(self, source, updates):
        """
        Recursively merge two dictionaries. If a key exists in both, and its value is a dictionary,
        merge them recursively. Otherwise, take the value from `updates`.
        """
        for key, value in updates.items():
            # If the value is a dictionary and the key exists in the source as a dictionary, recurse
            if isinstance(value, dict) and key in source and isinstance(source[key], dict):
                self.merge_dicts(source[key], value)
            else:
                # Otherwise, set or update the key in the source
                source[key] = value
        return source

    def on_message(self, _, msg):
        new_data = dict(json.loads(msg))
        _LOGGER.info(f"Received new data: {new_data}, old: {self.last_state}")
        prev_state = self.last_state
        self.merge_dicts(self.last_state, new_data)
        if prev_state != self.last_state and self.on_updated_callback is not None:
            _LOGGER.info(f"Calling on_updated_callback callback")
            self.on_updated_callback(self.last_state)

    def establish_connection(self, on_updated: Callable[[dict[str, Any]], None]):
        if self.api.websocket:
            self.on_updated_callback = on_updated
            self.ws = websocket.WebSocketApp(self.api.get_ws_device_url(), on_message=self.on_message)
            self.thread = Thread(target=self.ws.run_forever)
            self.thread.start()

    def get_status(self):
        if self.api.websocket:
            return self.last_state

        result = requests.get(self.api.get_device_url())
        new_data = dict(result.json())
        self.merge_dicts(self.last_state, new_data)

        return self.last_state