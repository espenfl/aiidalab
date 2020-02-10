# -*- coding: utf-8 -*-
"""AiiDA lab basic widgets."""

from threading import Thread
from time import sleep, time

import ipywidgets as ipw


class VersionSelectorWidget(ipw.VBox):
    """Class to choose app's version."""

    def __init__(self, options=None, value=None):
        self.selected = ipw.Select(
            options=options,
            value=value,
            description='Select version',
            disabled=False,
            style={'description_width': 'initial'},
        )
        self.selected.observe(self.version_changed, 'value')
        self.info = ipw.HTML('')
        self._clear_timer = 0
        super().__init__([self.selected, self.info])

    def _clear_info_after_delay(self, delay=3):
        self._clear_timer = time() + delay  # reset timer
        sleep(delay)
        if time() > self._clear_timer:
            self.info.value = ''

    def version_changed(self, change):
        old, new = change['old'], change['new']
        self.info.value = f"Switched version from {old} to {new}."
        Thread(target=self._clear_info_after_delay).start()
