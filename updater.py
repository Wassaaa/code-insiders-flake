#! /usr/bin/env nix-shell
#! nix-shell -i python3 -p python3Packages.pygithub -I nixpkgs=https://github.com/NixOS/nixpkgs/archive/nixos-unstable.tar.gz

import json
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve

ASSET_NAME = "code-insiders.tar.gz"
DOWNLOAD_URL = "https://update.code.visualstudio.com/latest/linux-x64/insider"
PACKAGE_JSON = "VSCode-linux-x64/resources/app/package.json"


def download_insiders(tmpdir: str, repository: str, release_time: str) -> tuple[dict, str]:
    print("Downloading latest Code Insiders")
    filename, _ = urlretrieve(DOWNLOAD_URL, str(Path(tmpdir) / ASSET_NAME))
    sha256 = subprocess.check_output(
        ["nix-hash", "--flat", "--type", "sha256", "--base32", filename],
        text=True,
    ).strip()
    with tarfile.open(filename, "r:gz") as archive:
        matches = [
            member for member in archive
            if member.name.removeprefix("./") == PACKAGE_JSON and member.isfile()
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one regular {PACKAGE_JSON} in the archive")
        package_file = archive.extractfile(matches[0])
        if package_file is None:
            raise ValueError(f"{PACKAGE_JSON} is not a regular file")
        with package_file:
            version = json.load(package_file)["version"]

    return {
        "version": version,
        "sha256": sha256,
        "url": f"https://github.com/{repository}/releases/download/{release_time}/{ASSET_NAME}",
    }, filename


def create_github_release(local_artifact: str, meta: dict, repository: str, release_time: str) -> None:
    from github import Github

    client = Github(os.environ["GITHUB_TOKEN"])
    repo = client.get_repo(repository)
    print("Creating release and uploading snapshot")
    release = repo.create_git_release(
        tag=release_time,
        name=meta["version"],
        message=f"Snapshot of Code Insiders at {release_time} UTC",
        target_commitish="main",
        draft=False,
        prerelease=False,
    )
    release.upload_asset(local_artifact, name=ASSET_NAME)


def commit(metafile: str, message: str) -> None:
    subprocess.run(["git", "config", "--local", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "--local", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", "--", metafile], check=True)
    subprocess.run(["git", "commit", "-sm", message], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)


def main(metafile: str, tmpdir: str, repository: str, release_time: str) -> None:
    remote_meta, local_file = download_insiders(tmpdir, repository, release_time)
    with open(metafile, encoding="utf-8") as file:
        local_meta = json.load(file)
    if remote_meta["sha256"] == local_meta["sha256"]:
        print("Code Insiders is up to date")
        return

    create_github_release(local_file, remote_meta, repository, release_time)
    with open(metafile, "w", encoding="utf-8") as file:
        json.dump(remote_meta, file, indent=4)
        file.write("\n")
    commit(metafile, f"Update Code Insiders snapshot at {release_time} to {remote_meta['version']}")


if __name__ == "__main__":
    release_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    with tempfile.TemporaryDirectory() as tmpdir:
        main("meta.json", tmpdir, os.environ["GITHUB_REPOSITORY"], release_time)
