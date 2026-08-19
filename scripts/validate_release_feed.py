#!/usr/bin/env python3
"""Validate the Sparkle feed, immutable release ledger, and live assets."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "spire" / "appcast.xml"
LEDGER = ROOT / "spire" / "releases.json"
SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)-(?P<build>\d+)$")
ASSET_URL = re.compile(
    r"^https://github\.com/Truth-Forge/spire-releases/releases/download/"
    r"(?P<tag>v[^/]+)/(?P<asset>[^/]+)$"
)


class ValidationFailure(RuntimeError):
    """Release state does not satisfy the publication contract."""


def fail_if_duplicates(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValidationFailure(f"{label} values must be unique")


def load_ledger() -> tuple[dict[str, dict[str, Any]], str]:
    with LEDGER.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != 1:
        raise ValidationFailure("unsupported release-ledger schema version")
    if document.get("release_repository") != "Truth-Forge/spire-releases":
        raise ValidationFailure("release repository is not canonical")
    source_repository = document.get("source_repository")
    if source_repository != "Truth-Forge/spire":
        raise ValidationFailure("source repository is not canonical")

    records = document.get("releases")
    if not isinstance(records, list) or not records:
        raise ValidationFailure("release ledger is empty")
    builds = [record.get("build") for record in records]
    if not all(isinstance(build, int) and build > 0 for build in builds):
        raise ValidationFailure("release builds must be positive integers")
    if builds != sorted(builds, reverse=True):
        raise ValidationFailure("release ledger must be newest-first")

    for label in ("tag", "version", "build", "source_commit", "asset", "asset_sha256"):
        fail_if_duplicates([record.get(label) for record in records], label)

    by_tag: dict[str, dict[str, Any]] = {}
    for record in records:
        match = TAG.fullmatch(str(record.get("tag", "")))
        if not match:
            raise ValidationFailure(f"invalid release tag: {record.get('tag')}")
        if (
            match.group("version") != record.get("version")
            or int(match.group("build")) != record.get("build")
        ):
            raise ValidationFailure(f"tag metadata diverges for {record['tag']}")
        if not COMMIT.fullmatch(str(record.get("source_commit", ""))):
            raise ValidationFailure(f"invalid source commit for {record['tag']}")
        expected_asset = f"Spire-{record['version']}-{record['build']}.zip"
        if record.get("asset") != expected_asset:
            raise ValidationFailure(f"primary asset diverges for {record['tag']}")
        if not SHA256.fullmatch(str(record.get("asset_sha256", ""))):
            raise ValidationFailure(f"invalid asset digest for {record['tag']}")
        by_tag[record["tag"]] = record
    return by_tag, source_repository


def valid_signature(value: str, context: str) -> None:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValidationFailure(f"invalid EdDSA signature for {context}") from error
    if len(decoded) != 64:
        raise ValidationFailure(f"EdDSA signature is not 64 bytes for {context}")


def enclosure_identity(element: ET.Element) -> tuple[str, str, str, int]:
    url = element.get("url", "")
    match = ASSET_URL.fullmatch(url)
    if not match:
        raise ValidationFailure(f"non-canonical enclosure URL: {url}")
    try:
        length = int(element.get("length", ""))
    except ValueError as error:
        raise ValidationFailure(f"invalid enclosure length: {url}") from error
    if length <= 0:
        raise ValidationFailure(f"non-positive enclosure length: {url}")
    if element.get("type") != "application/octet-stream":
        raise ValidationFailure(f"invalid enclosure type: {url}")
    valid_signature(element.get(f"{SPARKLE}edSignature", ""), url)
    return match.group("tag"), match.group("asset"), url, length


def validate_feed(
    ledger: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], int]:
    root = ET.parse(FEED).getroot()
    items = root.findall("./channel/item")
    if not items:
        raise ValidationFailure("Sparkle feed has no releases")

    builds: list[int] = []
    versions: list[str] = []
    live_assets: dict[tuple[str, str], int] = {}
    for item in items:
        version = item.findtext(f"{SPARKLE}shortVersionString", "")
        try:
            build = int(item.findtext(f"{SPARKLE}version", ""))
        except ValueError as error:
            raise ValidationFailure("feed contains a non-numeric build") from error
        tag = f"v{version}-{build}"
        record = ledger.get(tag)
        if record is None:
            raise ValidationFailure(f"feed release is absent from ledger: {tag}")
        if item.findtext("title") != version:
            raise ValidationFailure(f"feed title diverges for {tag}")

        primary = item.find("enclosure")
        if primary is None:
            raise ValidationFailure(f"feed release has no enclosure: {tag}")
        primary_tag, primary_asset, _, primary_length = enclosure_identity(primary)
        if primary_tag != tag or primary_asset != record["asset"]:
            raise ValidationFailure(f"primary enclosure diverges for {tag}")
        live_assets[(primary_tag, primary_asset)] = primary_length

        for delta in item.findall(f"{SPARKLE}deltas/enclosure"):
            delta_tag, delta_asset, _, delta_length = enclosure_identity(delta)
            if delta_tag not in ledger:
                raise ValidationFailure(
                    f"delta is hosted by an unrecorded release: {delta_tag}"
                )
            if not delta.get(f"{SPARKLE}deltaFrom", "").isdigit():
                raise ValidationFailure(f"delta has no numeric source build: {delta_asset}")
            live_assets[(delta_tag, delta_asset)] = delta_length

        builds.append(build)
        versions.append(version)

    if builds != sorted(builds, reverse=True):
        raise ValidationFailure("Sparkle feed must be newest-first")
    fail_if_duplicates(builds, "feed build")
    fail_if_duplicates(versions, "feed version")
    return live_assets


def github_json(path: str, token: str | None) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise ValidationFailure(f"GitHub release query failed: {error}") from error


def validate_live_assets(
    ledger: dict[str, dict[str, Any]],
    feed_assets: dict[tuple[str, str], int],
    token: str | None,
) -> None:
    releases = github_json(
        "/repos/Truth-Forge/spire-releases/releases?per_page=100", token
    )
    by_tag = {release["tag_name"]: release for release in releases}
    for tag, record in ledger.items():
        release = by_tag.get(tag)
        if release is None or release.get("draft") or release.get("prerelease"):
            raise ValidationFailure(f"ledger release is not published: {tag}")
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        primary = assets.get(record["asset"])
        if primary is None:
            raise ValidationFailure(f"primary asset is not published: {record['asset']}")
        if primary.get("digest") != f"sha256:{record['asset_sha256']}":
            raise ValidationFailure(f"primary asset digest diverges: {record['asset']}")

    for (tag, name), expected_size in feed_assets.items():
        release = by_tag.get(tag)
        assets = (
            {asset["name"]: asset for asset in release.get("assets", [])}
            if release
            else {}
        )
        asset = assets.get(urllib.parse.unquote(name))
        if asset is None:
            raise ValidationFailure(f"feed asset is not published: {tag}/{name}")
        if asset.get("size") != expected_size:
            raise ValidationFailure(f"feed asset length diverges: {tag}/{name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github-live",
        action="store_true",
        help="verify release assets and digests against the GitHub API",
    )
    args = parser.parse_args(argv)
    try:
        ledger, source_repository = load_ledger()
        feed_assets = validate_feed(ledger)
        if args.github_live:
            validate_live_assets(ledger, feed_assets, os.environ.get("GITHUB_TOKEN"))
    except (OSError, UnicodeError, json.JSONDecodeError, ET.ParseError, ValidationFailure) as error:
        print(f"Release validation failed: {error}", file=sys.stderr)
        return 1

    live = " and live GitHub assets" if args.github_live else ""
    print(
        f"Validated {len(ledger)} source-bound releases, "
        f"{len(feed_assets)} feed assets{live}; source is {source_repository}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
