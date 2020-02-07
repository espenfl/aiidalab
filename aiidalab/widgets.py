# -*- coding: utf-8 -*-
"""AiiDA lab basic widgets."""

import ipywidgets as ipw

class VersionSelectorWidget(ipw.VBox):
    """Class to choose app's version."""

    def __init__(self):
        self.change_btn = ipw.Button(description="choose seleted")
        self.selected = ipw.Select(
            options={},
            description='Select version',
            disabled=False,
            style={'description_width': 'initial'},
        )
        self.info = ipw.HTML('')
        super().__init__([self.selected, self.change_btn, self.info])
