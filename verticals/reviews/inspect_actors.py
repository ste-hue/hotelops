"""Introspect Apify actors via the API.

Queries each actor configured in reviews.config.APIFY_ACTORS and prints:
- Actor name + current version + modification date
- Input schema fields (name, type, required/optional, description)

Used as a manual diagnostic to check param drift (e.g., "did the date-filter
param name change?"). Run periodically or after an actor update.

Usage:
    APIFY_API_TOKEN=... python -m reviews.inspect_actors
    APIFY_API_TOKEN=... python -m reviews.inspect_actors --only BOOKING
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from apify_client import ApifyClient

from verticals.reviews.config import APIFY_ACTORS


def _get_client() -> ApifyClient:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("ERROR: APIFY_API_TOKEN env var not set", file=sys.stderr)
        sys.exit(2)
    return ApifyClient(token)


def inspect_actor(client: ApifyClient, piattaforma: str, actor_id: str) -> None:
    """Print actor version + input schema for a single actor."""
    print(f"\n=== {piattaforma}  ({actor_id}) ===")
    try:
        actor = client.actor(actor_id).get()
    except Exception as e:
        print(f"  ERROR fetching actor: {e}")
        return

    if not actor:
        print("  ERROR: actor not found")
        return

    name = actor.get("name") or actor.get("title") or "?"
    version_info = actor.get("versions") or []
    latest = actor.get("taggedBuilds", {}).get("latest", {}) if actor.get("taggedBuilds") else {}
    latest_version = latest.get("versionNumber") or (
        version_info[-1].get("versionNumber") if version_info else "?"
    )
    modified = actor.get("modifiedAt", "?")

    print(f"  name:         {name}")
    print(f"  version:      {latest_version}")
    print(f"  modifiedAt:   {modified}")

    # Input schema lives in the versioned build. Try to pull the latest build.
    build_id = latest.get("buildId")
    schema = None
    if build_id:
        try:
            build = client.build(build_id).get()
            if build:
                schema = (build.get("inputSchema") or {})
                if isinstance(schema, str):
                    # Some actors store it as a JSON string
                    try:
                        schema = json.loads(schema)
                    except json.JSONDecodeError:
                        schema = None
        except Exception as e:
            print(f"  (build fetch failed: {e})")

    if not schema:
        # Fallback: try exampleRunInput or other fields
        example = actor.get("exampleRunInput") or {}
        if example:
            print("  input schema: NOT AVAILABLE via build; example input:")
            print("    " + json.dumps(example, indent=2).replace("\n", "\n    "))
        else:
            print("  input schema: NOT AVAILABLE")
        return

    props = (schema.get("properties") or {})
    required = set(schema.get("required") or [])
    print(f"  input schema: {len(props)} field(s)")

    # Sort required first, then alphabetical
    ordered = sorted(props.items(), key=lambda kv: (kv[0] not in required, kv[0]))
    for field, meta in ordered:
        tag = "REQUIRED" if field in required else "optional"
        ftype = meta.get("type", "?")
        title = meta.get("title", "")
        print(f"    - {field:32s}  [{ftype:10s}] {tag:8s}  {title}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        help="Inspect a single piattaforma (BOOKING|TRIPADVISOR|GOOGLE|EXPEDIA|TRIP)",
    )
    args = parser.parse_args(argv)

    client = _get_client()

    targets = {args.only.upper(): APIFY_ACTORS[args.only.upper()]} if args.only else APIFY_ACTORS

    for piattaforma, actor_id in targets.items():
        inspect_actor(client, piattaforma, actor_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
