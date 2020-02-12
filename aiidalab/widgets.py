# -*- coding: utf-8 -*-
"""AiiDA lab basic widgets."""

from threading import Thread
from time import sleep, time

import ipywidgets as ipw


class StatusLabel(ipw.Label):
    """Show temporary messages for example for status updates."""

    def __init__(self, *args, **kwargs):
        self._clear_timer = 0
        super().__init__(*args, **kwargs)

    def _clear_value_after_delay(self, delay):
        self._clear_timer = time() + delay  # reset timer
        sleep(delay)
        if time() > self._clear_timer:
            self.value = ''

    def show_temporary_message(self, value, clear_after=3):
        self.value = value
        if clear_after > 0:
            Thread(target=self._clear_value_after_delay, args=(clear_after,)).start()
