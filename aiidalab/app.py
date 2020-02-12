# -*- coding: utf-8 -*-
"""Module to manage AiiDA lab apps."""

import os
import shutil
import json
from pathlib import Path
from subprocess import check_output, STDOUT

import requests
import ipywidgets as ipw
import traitlets
from dulwich.repo import Repo
from dulwich.objects import Commit, Tag
from dulwich.porcelain import clone, ls_remote
from dulwich.porcelain import status as git_status
from dulwich.errors import NotGitRepository
from cachetools.func import ttl_cache

from .widgets import StatusLabel
from .utils import get_remotes


class AppNotInstalledException(Exception):
    pass


class AiidaLabApp:
    """Class to manage AiiDA lab app."""

    class InvalidAppDirectory(TypeError):
        pass

    def __init__(self, path):
        self._path = Path(path).resolve()

    @property
    def path(self):
        return self._path

    @property
    def name(self):
        return self.path.stem

    def is_installed(self):
        """The app is installed if the corresponding folder is present."""
        return self.path.is_dir()

    @property
    def metadata(self):
        """Return the metadata dictionary."""
        # NOTE The inernal caching has been removed for now (premature optimization).
        metadata_file = self.path / 'metadata.json'
        try:
            return json.loads(metadata_file.read_bytes())
        except FileNotFoundError:
            raise self.InvalidAppDirectory(
                f"Metadata file missing: '{metadata_file}'")
        except json.decoder.JSONDecodeError:
            raise self.InvalidAppDirectory(
                f"Ill-formed metadata file: '{metadata_file}'")
        except Exception as error:
            raise self.InvalidAppDirectory(
                f"Unknown error accessing metadata file: {error}") from error


class GitManagedAiidaLabApp(traitlets.HasTraits):
    """Class to manage git-installed AiiDA lab app."""

    version = traitlets.Unicode(allow_none=True)
    available_versions = traitlets.List(
        traitlets.Tuple(traitlets.Unicode, traitlets.Unicode), readonly=True)
    installed = traitlets.Bool(readonly=True)

    def __init__(self, path, app_data):
        super().__init__()
        self.path = Path(path).resolve()
        assert app_data is not None
        self._app_data = app_data

        self.status_message = ipw.HTML()

    def is_installed(self):
        return self.path.is_dir()

    @property
    def name(self):
        return self.path.stem

    @property
    def _git_url(self):
        return self._app_data['git_url']

    @property
    def _meta_url(self):
        return self._app_data['meta_url']

    @property
    def _git_remote_refs(self):
        return self._app_data['gitinfo']

    @property
    def catgories(self):
        return self._app_data['categories']

    @ttl_cache()
    def _metadata(self):
        return requests.get(self._meta_url).json()

    @property
    def metadata(self):
        return self._metadata()

    def _get_from_metadata(self, key):
        """Get information from metadata."""
        # NOTE This function must be removed after we can make the assumption that
        #      the app must exist.
        try:
            return str(self.metadata[key])
        except KeyError:
            return f'the field "{key}" is not present in metadata.json file'
        except Exception as error:  # pylint: disable=broad-except
            return f'unknown while retrieving metadata: {error}'

    @property
    def authors(self):
        return self._get_from_metadata('authors')

    @property
    def description(self):
        return self._get_from_metadata('description')

    @property
    def title(self):
        return self._get_from_metadata('title')

    @property
    def categories(self):
        return self._app_data['categories']

    def in_category(self, category):
        # One should test what happens if the category won't be defined.
        return category in self.categories

    def _get_appdir(self):  # deprecated
        return str(self.path)

    def has_git_repo(self):
        """Check if the app has a .git folder in it."""
        try:
            Repo(self._get_appdir())
            return True
        except NotGitRepository:
            return False

    def found_uncommited_modifications(self):
        """Check whether the git-supervised files were modified."""
        status = git_status(self.repo)
        return status.unstaged or any(status.staged.values())

    def found_local_commits(self):
        """Check whether user did some work in the current branch."""
        config = self.repo.get_config()
        remotes = set(get_remotes(self.repo))
        remote_refs = set()
        for remote in remotes:
            url = config.get((b'remote', remote.encode()), 'url')
            remote_refs.update(ls_remote(url.decode()).values())
        return any(ref not in remote_refs for ref in self.repo.get_refs().values())

    def found_local_versions(self):
        """Find if local git branches are present."""
        return any(ref.startswith('refs/heads/') for _, ref in self.available_versions)

    def cannot_modify_app(self):
        """Check if there is any reason to not let modifying the app."""

        # It is not a git repo.
        if not self.has_git_repo():
            return 'not a git repo'

        # There is no remote URL specified.
        if not self._git_url:
            return 'no remote URL specified (risk to lose your work)'

        # The repo has some uncommited modifications.
        if self.found_uncommited_modifications():
            return 'found uncommited modifications (risk to lose your work)'

        # Found local commits.
        if self.found_local_commits():
            return 'local commits found (risk to lose your work)'

        # Found no branches.
        if not self.available_versions:
            return 'no branches found'

        return ''

    def _install_app(self, _=None):
        """Installing the app."""
        clone(source=self._git_url, target=self._get_appdir())
        self.available_versions = list(sorted(self._collect_available_versions()))
        self.version = self._current_version()

    def _uninstall_app(self):
        """Perfrom app uninstall."""
        cannot_modify = self.cannot_modify_app()

        # Check if one cannot install the app.
        if cannot_modify:
            raise RuntimeError(cannot_modify)

        if self.name == 'home':
            raise RuntimeError("Can't remove home app.")

        if self.found_local_commits():
            raise RuntimeError("You have local non-pushed commits.")

        # Perform removal
        shutil.rmtree(self._get_appdir())
        self.set_trait('available_versions', [])

    def _current_version(self):
        try:
            return self.repo.refs.follow(b'HEAD')[0][1]
        except IndexError:
            return None

    @traitlets.default('version')
    def _default_version(self):
        """App's version."""
        return self._current_version()

    @traitlets.default('installed')
    def _default_installed(self):
        return self.version is not None

    @property
    @ttl_cache()
    def refs_dict(self):
        """Returns a dictionary of references: branch names, tags."""
        if not self.repo:
            return None

        refs_dict = {}
        for key, value in self.repo.get_refs().items():
            if key.endswith(b'HEAD') or key.startswith(b'refs/heads/'):
                continue
            obj = self.repo.get_object(value)
            if isinstance(obj, Tag):
                refs_dict[key] = obj.object[1]
            elif isinstance(obj, Commit):
                refs_dict[key] = value
        return refs_dict

    @traitlets.default('available_versions')
    def _default_available_versions(self):
        return list(self._collect_available_versions())

    def _collect_available_versions(self):
        """Function that looks for all the available branches."""

        def human_ref_name(ref):
            prefixes_to_strip = (
                'refs/heads/',    # local branch
                'refs/remotes/',  # remote branch
                'refs/tags/',     # tag
            )
            for prefix in prefixes_to_strip:
                if ref.startswith(prefix):
                    return ref[len(prefix):]
            return ref

        if self.repo:
            for ref in [ref.decode('utf-8') for ref in self.repo.get_refs()]:
                if ref != 'HEAD':
                    yield human_ref_name(ref), ref

    @traitlets.validate('version')
    def _validate_version(self, proposal):
        if proposal['value'] is None and self.path.exists():
            raise traitlets.TraitError("Can't change version to 'None' if repository exists.")
        if self.found_uncommited_modifications():
            raise traitlets.TraitError("Can't change version with local modifications!")
        return proposal['value']

    @traitlets.observe('version')
    def _observe_version(self, change):
        """Change app's version."""
        new_version = change['new']
        if new_version is None:
            self._uninstall_app()
        elif new_version != self.repo.head():
            if new_version.startswith('refs/heads/'):  # local branch
                new_version = new_version[len('refs/heads/'):]

            check_output(['git', 'checkout', new_version], cwd=self._get_appdir(), stderr=STDOUT)

        self.set_trait('installed', new_version is not None)

    @property
    def git_url(self):
        """Provide explicit link to Git repository."""
        if self._git_url is None:
            return '-'
        # else
        return '<a href="{}">{}</a>'.format(self._git_url, self._git_url)

    @property
    def git_hidden_url(self):
        """Provide a link to Git repository."""
        if self._git_url is None:
            return 'No Git url'
        # else
        return '<a href="{}"><button>Git URL</button></a>'.format(self._git_url)

    @property
    def more(self):
        return """<a href=./single_app.ipynb?app={}>Manage App</a>""".format(self.name)

    def logo(self):
        return ipw.HTML(f'<img src="{self.logo_path()}">', layout=ipw.Layout({'width': '100px', 'height': '100px'}))

    def logo_path(self):
        """Return logo object. Give the priority to the local version"""
        if self.is_installed():  # pylint:disable=no-else-return
            return os.path.join('..', self.name, self.metadata['logo'])
        else:  # pylint:disable=no-else-return
            return "./aiidalab_logo_v4.svg"
        # TODO: Implement remote fetch

    @property
    def repo(self):
        """Returns Git repository."""
        if self.is_installed():  # pylint:disable=no-else-return
            return Repo(self._get_appdir())
        else:
            return None

    def render_app_manager_widget(self):
        """"Display widget to manage the app."""
        return GitManagedAiidaLabAppWidget(self)


class GitManagedAiidaLabAppWidget(ipw.VBox):

    def __init__(self, app):
        self.app = app

        self.status_message = StatusLabel()

        self.install_button = ipw.Button(description="Install", icon='check')
        self.install_button.on_click(self.app._install_app)
        self.install_button.disabled = self.app.installed

        self.uninstall_button = ipw.Button(description="Uninstall", icon='close')

        def _on_uninstall_button_clicked(_):
            self.app.version = None

        self.uninstall_button.on_click(_on_uninstall_button_clicked)
        self.uninstall_button.disabled = not self.app.installed

        self.app.observe(self._on_change_app_installed, 'installed')

        self.buttons = ipw.HBox([self.install_button, self.uninstall_button])

        self.version_selector = ipw.Select(
            options=self.app.available_versions,
            value=self.app.version,
            description='Select version',
            disabled=not self.app.installed,
            style={'description_width': 'initial'},
            )

        self.logo = ipw.HTML()
        self.logo.layout = {'width': '100px', 'height': '100px'}
        self.logo.layout.margin = "10px 10px 10px 10px"

        self.title = ipw.HTML(f"""<b> <div style="font-size: 30px; text-align:center;">{self.app.title}</div></b>""")
        self.title.layout = dict(height='50px')

        self.description = ipw.HTML()
        self.description.layout = {'width': '800px'}

        self._update_logo_and_description()  # initial update
        self.banner = ipw.HBox([self.logo, self.description])

        self.app.observe(self._update_logo_and_description, 'version')
        self.app.observe(self._show_version_switched_message, 'version')

        traitlets.dlink((self.app, 'available_versions'), (self.version_selector, 'options'))
        traitlets.link((self.app, 'version'), (self.version_selector, 'value'))

        super().__init__(children=[
            self.title, self.banner, self.buttons,
            self.version_selector, self.status_message])

    def _on_change_app_installed(self, change):
        installed = change['new']
        self.install_button.disabled = installed
        self.uninstall_button.disabled = not installed
        self.version_selector.disabled = not installed

    def _update_logo_and_description(self, _=None):
        self.description.value = F"""
        <b>Authors:</b> {self.app.authors}
        <br>
        <b>Description:</b> {self.app.description}
        <br>
        <b>Git URL:</b> {self.app.git_url}"""
        self.logo.value = f'<img src="{self.app.logo_path()}">'

    def _show_version_switched_message(self, change):
        self.status_message.show_temporary_message(
            f"Switched version from {change['old']} to {change['new']}.")
