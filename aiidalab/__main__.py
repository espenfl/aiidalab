# -*- coding: utf-8 -*-
"""Module that implements a basic command line interface (CLI) for AiiDA lab."""

import shutil
from itertools import repeat
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from subprocess import run
from urllib.parse import urldefrag

import click
from packaging.requirements import Requirement
from packaging.version import parse

from .app import AppVersion
from .config import AIIDALAB_APPS
from .utils import find_installed_packages
from .utils import load_app_registry


def _git_clone(url, branch, path):
    try:
        run(
            ["git", "clone", "--depth=1", f"--branch={branch}", str(url), str(path)],
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
    except CalledProcessError as error:
        raise RuntimeError(error.stderr)


@dataclass
class AiidaLabApp:

    name: str
    path: Path
    git_url: str
    metadata: dict
    categories: list
    releases: dict

    @classmethod
    def from_registry(cls, path, registry_entry):
        return cls(
            path=path,
            **{
                key: value
                for key, value in registry_entry.items()
                if key in ("categories", "git_url", "metadata", "name", "releases")
            },
        )

    @classmethod
    def from_name(cls, name, registry=None, apps_path=None):
        if registry is None:
            registry = load_app_registry()
        if apps_path is None:
            apps_path = AIIDALAB_APPS

        return cls.from_registry(
            path=Path(apps_path).joinpath(name), registry_entry=registry["apps"][name]
        )

    @property
    def _repo(self):
        from .git_util import GitManagedAppRepo as Repo

        if self.path.exists():
            return Repo(str(self.path))

    def installed_version(self):
        if self._repo:
            head_commit = self._repo.head().decode()
            versions_by_commit = {r["commit"]: k for k, r in self.releases.items()}
            return versions_by_commit.get(head_commit, AppVersion.UNKNOWN)
        return AppVersion.NOT_INSTALLED

    def dirty(self):
        if self._repo:
            return self._repo.dirty()

    def uninstall(self):
        if self.path.exists():
            shutil.rmtree(self.path)

    def find_matching_release(self, specifier):
        matching_releases = [
            version for version in self.releases if parse(version) in specifier
        ]
        # Sort by intrinsic order (e.g. 1.1.0 -> 1.0.1 -> 1.0.0 and so on)
        matching_releases.sort(key=parse, reverse=True)
        return matching_releases

    @staticmethod
    def _find_incompatibilities_python(requirements):
        packages = find_installed_packages()
        for requirement in map(Requirement, requirements):
            f = [p for p in packages if p.fulfills(requirement)]
            if not any(f):
                yield requirement

    def _find_incompatibilities(self, version):
        dependencies = self.releases[version]["dependencies"]
        for key, deps in dependencies.items():
            if key == "python-requirements":
                yield from zip(
                    repeat("python"), self._find_incompatibilities_python(deps)
                )
            else:
                raise ValueError("Unknown eco-system '{key}'")

    def is_compatible(self, version):
        return not any(self._find_incompatibilities(version))

    def install(self, version=None):
        if version is None:
            try:
                version = list(sorted(map(parse, self.releases)))[-1]
            except IndexError:
                raise ValueError("No versions available for '{self}'.")

        self.uninstall()
        try:
            _git_clone(urldefrag(self.git_url).url, version, self.path)
        except RuntimeError as error:
            raise RuntimeError(
                f"Failed to install '{self.name}' (version={version}) at '{self.path}'"
                f", due to error: {error}"
            )


@click.group()
def cli():
    pass


@cli.command()
@click.argument("app-requirement")
@click.option("--only-compatible", is_flag=True)
def search(app_requirement, only_compatible):
    app_requirement = Requirement(app_requirement)
    try:
        app = AiidaLabApp.from_name(app_requirement.name)
    except KeyError:
        raise click.ClickException(
            f"Did not find entry for app with name '{app_requirement.name}'."
        )
    matching_releases = [
        version
        for version in app.find_matching_release(app_requirement.specifier)
        if not only_compatible or app.is_compatible(version)
    ]
    click.echo("\n".join(f"{app.name}=={version}" for version in matching_releases))


@cli.command()
def list():
    installed_apps = [
        str(app_path.relative_to(AIIDALAB_APPS))
        for app_path in Path(AIIDALAB_APPS).iterdir()
    ]
    for app_name in sorted(installed_apps):
        try:
            app = AiidaLabApp.from_name(app_name)
        except KeyError:
            click.echo(f"{app_name:<29} [detached]")
        else:
            click.echo(
                f"{app_name:<29} {app.installed_version()}{'*' if app.dirty() else ''}"
            )


def _select_ecosystem(ctx, param, value):
    return tuple(
        {
            "jupyter": "jupyter-requirements",
            "python": "python-requirements",
        }.get(v, v)
        for v in value
    )


@cli.command()
@click.argument("app-requirement")
@click.option(
    "-e",
    "--eco-system",
    type=click.Choice(["python", "jupyter"]),
    multiple=True,
    callback=_select_ecosystem,
)
def show_dependencies(app_requirement, eco_system):
    app_requirement = Requirement(app_requirement)
    try:
        app = AiidaLabApp.from_name(app_requirement.name)
    except KeyError:
        raise click.ClickException(
            f"Did not find entry for app with name '{app_requirement.name}'."
        )
    matching_releases = app.find_matching_release(app_requirement.specifier)
    if matching_releases:
        version_selected = matching_releases[0]
        dependencies = app.releases[version_selected]["dependencies"]
        for key, deps in dependencies.items():
            if len(eco_system) and key not in eco_system:
                continue

            if key == "python-requirements":
                click.echo(
                    f"# Python requirements for AiiDAlab app '{app.name}' "
                    f"version '{version_selected}':"
                )
                click.echo("\n".join(deps))  # requirements.txt - format
            else:
                raise ValueError("Unknown eco-system '{key}'")
    else:
        raise click.ClickException(
            f"No matching release for '{app_requirement.specifier}'. "
            f"Available releases: {','.join(map(str, sorted(map(parse, app.releases))))}"
        )


@cli.command()
@click.argument("app-requirement")
@click.option("-f", "--force", is_flag=True)
@click.option("--ignore-dependencies", is_flag=True)
@click.option("-n", "--dry-run", is_flag=True)
def install(app_requirement, force, ignore_dependencies, dry_run):
    """Show basic information about the app and the installation status."""

    app_requirement = Requirement(app_requirement)
    try:
        app = AiidaLabApp.from_name(app_requirement.name)
    except KeyError:
        raise click.ClickException(
            f"Did not find entry for app with name '{app_requirement.name}'."
        )
    matching_releases = app.find_matching_release(app_requirement.specifier)
    compatible_releases = [
        version
        for version in matching_releases
        if ignore_dependencies or app.is_compatible(version)
    ]

    if compatible_releases:
        version_to_install = compatible_releases[0]
        if force or version_to_install != app.installed_version():
            if dry_run:
                click.echo(
                    f"Would install {app.name}=={version_to_install} at {app.path} ."
                )
            else:
                app.install(version=version_to_install)
                click.echo(
                    f"Installed {app.name}=={version_to_install} at {app.path} ."
                )
        elif version_to_install == app.installed_version():
            click.echo(
                f"App already installed in version '{version_to_install}' "
                "Use the -f/--force option to ignore and re-install."
            )
    elif len(matching_releases):
        click.echo(
            f"There are releases matching your specifiation ("
            f"{','.join(map(str, sorted(map(parse, matching_releases))))}), however "
            "none of these are compatible with this environment."
        )
    else:
        raise click.ClickException(
            f"No matching release for '{app_requirement.specifier}'. "
            f"Available releases: {','.join(map(str, sorted(map(parse, app.releases))))}"
        )


@cli.command()
@click.argument("app-name")
@click.option("-f", "--force", is_flag=True)
def uninstall(app_name, force):
    try:
        app = AiidaLabApp.from_name(app_name)
    except KeyError:
        app_path = Path(AIIDALAB_APPS).joinpath(app_name)
        if app_path.exists():
            raise click.ClickException(
                f"Did not find entry for app with name '{app_name}'. "
                f"However the directory '{app_path}' exists. "
                "Try removing the directory manually."
            )
        else:
            raise click.ClickException(
                f"Did not find entry for app with name '{app_name}'."
            )

    if app.path.exists():
        detached = app.dirty() or app.installed_version() is AppVersion.UNKNOWN
        if force or not detached:
            shutil.rmtree(app.path)
        elif detached:
            raise click.ClickException(
                f"Failed to uninstall '{app_name}', the app "
                f"{'was modified' if app.dirty() else 'is installed with an unknown version'}. "
                "Use the -f/--force option to ignore and uninstall anyways. "
                "WARNING: This may lead to data loss!"
            )


if __name__ == "__main__":
    cli()
