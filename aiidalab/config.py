"""Module to manange AiiDA lab configuration."""
from os import getenv
from pathlib import Path

AIIDALAB_HOME = Path(getenv('AIIDALAB_HOME', '/project'))
AIIDALAB_APPS = Path(getenv('AIIDALAB_APPS', '/project/apps'))
AIIDALAB_SCRIPTS = Path(getenv('AIIDALAB_SCRIPTS', '/opt'))
AIIDALAB_REGISTRY = getenv('AIIDALAB_REGISTRY', 'https://aiidalab.materialscloud.org/appsdata/apps_meta.json')
AIIDALAB_DEFAULT_GIT_BRANCH = getenv('AIIDALAB_DEFAULT_GIT_BRANCH', 'master')
