"""Module to manange AiiDA lab configuration."""
import os
import sys
import site
from pathlib import Path


AIIDALAB_HOME = os.getenv('AIIDALAB_HOME', '/project')
AIIDALAB_HOME_PATH = Path(AIIDALAB_HOME)


_AIIDALAB_APPS_DEFAULT = [
    Path(AIIDALAB_HOME) / 'apps',
    Path(site.USER_BASE, 'apps'),
    Path(sys.prefix, 'apps'),
]

AIIDALAB_APPS = os.getenv(
    'AIIDALAB_APPS',
    ':'.join(map(str, _AIIDALAB_APPS_DEFAULT)))

AIIDALAB_SCRIPTS = os.getenv(
    'AIIDALAB_SCRIPTS',
    '/opt')

AIIDALAB_REGISTRY = os.getenv(
    'AIIDALAB_REGISTRY',
    'https://aiidalab.materialscloud.org/appsdata/apps_meta.json')
