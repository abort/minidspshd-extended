from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
from typing import Any, Callable
from urllib.request import urlopen
import json
import requests

import websocket


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

    def __init__(self, api, last_state):
        self.api = api
        self.last_state = last_state

    def __del__(self):
        if self.ws:
            self.ws.close()

    def on_message(self, _, msg):
        new_data = dict(json.loads(msg))
        prev_state = self.last_state
        self.last_state += new_data
        if prev_state != self.last_state and self.on_updated_callback is not None:
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
        self.last_state += dict(result.json())

        return self.last_state
