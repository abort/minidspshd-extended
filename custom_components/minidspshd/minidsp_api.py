from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from threading import Thread
from typing import Callable

import websocket

_LOGGER = logging.getLogger(__name__)


@dataclass
class MiniDSPApi:
    """Class to keep track of MiniDSP API."""
    host: str
    port: int
    device_id: int

    @staticmethod
    def from_dict(dictionary: dict) -> MiniDSPApi:
        return MiniDSPApi(dictionary["host"], dictionary["port"], dictionary["device_id"])

    def verify_ws_connection(self) -> None:
        ws = websocket.WebSocket()
        try:
            ws.connect(self.get_ws_device_url(False))
        except Exception as ex:
            raise ex
        finally:
            ws.close()

    def get_ws_device_url(self, poll: bool = True) -> str:
        return "ws://{}:{}/devices/{}?poll={}".format(self.host, self.port, self.device_id, poll)


@dataclass
class MiniDSPState:
    """Class to keep track of MiniDSP state."""
    preset: int = 0
    source: str = "Lan"
    volume: float = -127.0
    mute: bool = False
    dirac: bool = False

    has_changed: bool = False


class MiniDSPApiConnection:
    api: MiniDSPApi
    ws: websocket.WebSocketApp | None
    last_state: MiniDSPState
    thread: Thread | None = None
    on_updated_callback: Callable[[MiniDSPState], None] | None = None

    def __init__(self, api, last_state):
        self.on_updated_callback = None
        self.api = api
        self.last_state = MiniDSPState()

    def __del__(self):
        if self.ws:
            self.ws.close()

    def update_last_state(self, payload):
        prev_state = dataclasses.replace(self.last_state)
        new_data = payload.get("master", {})
        self.last_state.dirac = new_data.get("dirac", self.last_state.dirac)
        self.last_state.mute = new_data.get("mute", self.last_state.mute)
        self.last_state.volume = new_data.get("volume", self.last_state.volume)
        self.last_state.preset = new_data.get("preset", self.last_state.preset)
        self.last_state.source = new_data.get("source", self.last_state.source)
        self.last_state.has_changed = prev_state != self.last_state

    def on_message(self, _, msg):
        new_data = dict(json.loads(msg))
        self.update_last_state(new_data)
        if self.last_state.has_changed and self.on_updated_callback is not None:
            self.on_updated_callback(self.last_state)

    def establish_connection(self, on_updated: Callable[[MiniDSPState], None]):
        self.on_updated_callback = on_updated
        self.ws = websocket.WebSocketApp(self.api.get_ws_device_url(), on_message=self.on_message)
        self.thread = Thread(target=self.ws.run_forever)
        self.thread.start()

    def disconnect(self):
        self.ws.close()
        if self.thread is not None:
            self.thread.join()
            self.thread = None