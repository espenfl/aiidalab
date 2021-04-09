# -*- coding: utf-8 -*-
"""Module that implements a basic command line interface (CLI) for AiiDA lab."""

import shutil
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from subprocess import run
from urllib.parse import urldefrag

import click
from packaging.version import parse

from .config import AIIDALAB_APPS
from .utils import load_app_registry


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
        if self._repo and not self._repo.dirty():
            head_sha = self._repo.head().decode()
            versions_by_sha = {r["sha"]: k for k, r in self.releases.items()}
            return versions_by_sha.get(head_sha)

    def uninstall(self):
        if self.path.exists():
            shutil.rmtree(self.path)

    def install(self, version=None):
        if version is None:
            try:
                version = list(sorted(map(parse, self.releases)))[-1]
            except IndexError:
                raise ValueError("No versions available for '{self}'.")

        self.uninstall()

        try:
            run(
                [
                    "git",
                    "clone",
                    "--depth=1",
                    "--branch",
                    str(version),
                    f"{urldefrag(self.git_url).url}",
                    str(self.path),
                ],
                capture_output=True,
                check=True,
            )
        except CalledProcessError as error:
            raise RuntimeError(
                f"Failed to install '{self.name}' at '{self.path}': {error.stderr}"
            )


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "-a",
    "--all",
    "all_",
    is_flag=True,
    help="List all available apps, even those not installed.",
)
def list(all_):
    registry = load_app_registry()
    for app_name in registry["apps"]:
        app = AiidaLabApp.from_name(app_name)
        app_version = app.installed_version()
        if all_ or app_version is not None:
            click.echo(
                f"{app.name:<30} {'[not installed]' if app_version is None else app_version}"
            )


@cli.command()
@click.argument("app-requirement")
@click.option("-f", "--force", is_flag=True)
def install(app_requirement, force):
    """Show basic information about the app and the installation status."""
    from packaging.requirements import Requirement

    registry = load_app_registry()

    app_requirement = Requirement(app_requirement)
    try:
        app = AiidaLabApp.from_registry(
            path=Path(AIIDALAB_APPS).joinpath(app_requirement.name),
            registry_entry=registry["apps"][app_requirement.name],
        )
    except KeyError:
        raise click.ClickException(
            f"Did not find entry for app with name '{app_requirement.name}'."
        )

    matching_releases = [
        version
        for version in app.releases
        if parse(version) in app_requirement.specifier
    ]

    # Sort by intrinsic order (e.g. 1.1.0 -> 1.0.1 -> 1.0.0 and so on)
    matching_releases.sort(key=parse, reverse=True)

    if matching_releases:
        version_to_install = matching_releases[0]

        if force or version_to_install != app.installed_version():
            app.install(version=version_to_install)
            click.echo(f"Installed {app.name}=={matching_releases[0]} at {app.path} .")
        elif version_to_install == app.installed_version():
            click.echo(
                f"App already installed in version '{version_to_install}' "
                "Use the -f/--force option to ignore and re-install."
            )
    else:
        raise click.ClickException(
            f"No matching release for '{app_requirement.specifier}'. "
            f"Available releases: {','.join(map(str, sorted(map(parse, app.releases))))}"
        )


@cli.command()
@click.argument("app-name")
def uninstall(app_name):
    path = Path(AIIDALAB_APPS).joinpath(app_name)
    if path.exists():
        shutil.rmtree(path)


if __name__ == "__main__":
    cli()
