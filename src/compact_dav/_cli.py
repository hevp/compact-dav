#!/usr/bin/env python3
"""Compact OwnCloud/NextCloud WebDAV client"""

import argparse
import os
import sys
import simplejson

_DEFAULT_CREDENTIALS = os.path.join(os.path.expanduser("~"), ".config", "compact-dav", "credentials.json")

from .client import WebDAVClient
from .config import Config
from .logger import Logger, error, debug

def _load_api(path: str | None = None) -> dict:
    try:
        if path:
            with open(path) as f:
                return simplejson.load(f)
        from importlib.resources import files
        with (files("compact_dav") / "data" / "webdav.json").open("r") as f:
            return simplejson.load(f)
    except Exception as e:
        error(f"api load failed: {e}", 1)


def _load_credentials_data(path: str) -> dict:
    try:
        with open(os.path.abspath(path)) as f:
            data = simplejson.load(f)
    except FileNotFoundError:
        return {"active": None, "remotes": {}}
    except Exception as e:
        error(f"failed to read {path}: {e}", 1)
    return data


def _save_credentials(path: str, data: dict) -> None:
    try:
        with open(os.path.abspath(path), "w") as f:
            simplejson.dump(data, f, indent=4)
    except Exception as e:
        error(f"failed to save {path}: {e}", 1)


def _run_config(credentials_file: str, name: str | None, use: str | None) -> None:
    data = _load_credentials_data(credentials_file)
    if "remotes" not in data:
        data = {"active": "default", "remotes": {"default": data}}

    if use is not None:
        if use not in data["remotes"]:
            error(f"credential set '{use}' not found", 1)
        data["active"] = use
        _save_credentials(credentials_file, data)
        print(f"Active credential set: '{use}'")
        return

    # Resolve name interactively if not given as argument
    if name is None:
        existing_names = list(data["remotes"].keys())
        default = data.get("active") or (existing_names[0] if existing_names else None)
        prompt = f"  Name [{default}]: " if default else "  Name: "
        entered = input(prompt).strip()
        name = entered if entered else default
        if not name:
            error("a name is required", 1)

    existing = data["remotes"].get(name, {})
    action = "Creating" if name not in data["remotes"] else "Editing"
    print(f"{action} credential set '{name}' ({credentials_file}). Press Enter to keep existing value.")

    fields = [
        ("hostname", "Hostname", False),
        ("endpoint", "Endpoint", False),
        ("user",     "User",     False),
        ("token",    "Token",    True),
    ]

    result = {}
    for key, label, secret in fields:
        current = existing.get(key, "")
        display = "****" if secret and current else current
        prompt = f"  {label} [{display}]: " if display else f"  {label}: "
        value = input(prompt).strip()
        result[key] = value if value else current

    data["remotes"][name] = result
    if not data.get("active"):
        data["active"] = name

    _save_credentials(credentials_file, data)
    active_note = " (active)" if data["active"] == name else ""
    print(f"Credential set '{name}'{active_note} saved to {credentials_file}")


def _build_parser(api: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dav",
        description="CompactDAV — OwnCloud/NextCloud WebDAV client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="CompactDAV 1.2")

    infra = parser.add_argument_group("infrastructure")
    infra.add_argument("--api", default=None, metavar="FILE",
                       help="API definition file (default: bundled webdav.json)")
    infra.add_argument("--credentials-file", "-c", default=_DEFAULT_CREDENTIALS, metavar="FILE",
                       help="Credentials JSON file (default: %(default)s)")

    out = parser.add_argument_group("output")
    out.add_argument("--printf", "-p", default="{date} {size:r} {path}", metavar="FORMAT",
                     help="Output format string (default: %(default)r)")
    # Note: -h is reserved by argparse for --help; original used -h for --human
    out.add_argument("--human", "-H", action="store_true", help="Human-readable file sizes")
    out.add_argument("--summary", "-u", action="store_true", help="Append size/count summary")
    out.add_argument("--no-colors", action="store_true", help="Disable ANSI colour output")
    out.add_argument("--no-parse", action="store_true", help="Skip response parsing")
    out.add_argument("--hide-root", action="store_true", help="Omit the root entry from listings")
    out.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    out.add_argument("--debug", action="store_true", help="Debug output")
    out.add_argument("--quiet", "-q", action="store_true", help="Suppress non-error output")

    req = parser.add_argument_group("request")
    req.add_argument("--dry-run", "-n", action="store_true",
                     help="Print the request without executing it")
    req.add_argument("--no-verify", "-k", action="store_true",
                     help="Disable SSL certificate verification")
    req.add_argument("--overwrite", "-o", action="store_true",
                     help="Overwrite an existing target")
    req.add_argument("--confirm", "-y", action="store_true",
                     help="Prompt before destructive operations")
    req.add_argument("--exists", action="store_true",
                     help="Verify source/target existence before the operation")
    req.add_argument("--timeout", type=int, default=30, metavar="SECONDS",
                     help="Request timeout in seconds (default: %(default)s)")
    req.add_argument("--checksum", action="store_true", help="Display file checksum on download")
    req.add_argument("--headers", action="store_true", help="Print response headers")
    req.add_argument("--head", action="store_true", help="Issue a HEAD request only")

    flt = parser.add_argument_group("listing and filtering")
    flt.add_argument("--recursive", "-R", action="store_true", help="Recurse into subdirectories")
    flt.add_argument("--sort", action="store_true", help="Sort results by path")
    flt.add_argument("--reverse", "-r", action="store_true", help="Reverse sort order")
    flt.add_argument("--dirs-first", "-t", action="store_true", help="List directories before files")
    flt.add_argument("--files-only", "-f", action="store_true", help="Show files only")
    flt.add_argument("--dirs-only", "-d", action="store_true", help="Show directories only")
    flt.add_argument("--list-empty", "-e", action="store_true", help="Show only empty directories")
    flt.add_argument("--no-path", action="store_true", help="Omit paths from output")

    subs = parser.add_subparsers(
        dest="operation",
        metavar="OPERATION",
        title="operations",
        description="run `dav OPERATION --help` for per-operation usage",
    )
    subs.required = True

    config_sp = subs.add_parser("config", help="Set up WebDAV remote credentials interactively")
    config_sp.add_argument("name", nargs="?", default=None, metavar="NAME",
                           help="credential set name to create or edit")
    config_sp.add_argument("--use", metavar="NAME",
                           help="switch the active credential set to NAME")

    for op, ov in api.items():
        argdefs = ov.get("arguments", {"min": 1, "max": 1})
        descs = ov.get("descriptions", {})
        min_args = argdefs.get("min", 1)
        max_args = argdefs.get("max", 1)

        sp = subs.add_parser(op, help=ov["description"],
                             formatter_class=argparse.RawDescriptionHelpFormatter)

        for i in range(max_args):
            desc = descs.get(str(i), f"arg{i + 1}")
            optional = i >= min_args
            sp.add_argument(
                f"arg{i + 1}",
                metavar=desc.replace(" ", "_").upper()[:24],
                nargs="?" if optional else None,
                default="" if optional else None,
                help=desc,
            )

        # Operation-specific flags (non-positional entries in descriptions)
        for key, desc in ((k, v) for k, v in descs.items() if not k.isdigit()):
            sp.add_argument(f"--{key}", help=desc)

    return parser


def _positional_args(ns: argparse.Namespace) -> list[str]:
    args = []
    i = 1
    while (val := getattr(ns, f"arg{i}", None)) is not None:
        args.append(val)
        i += 1
    return args


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Two-pass parse: resolve --api first so subparsers can be built from it
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--api", default=None)
    pre_ns, _ = pre.parse_known_args(argv)

    api = _load_api(pre_ns.api)
    parser = _build_parser(api)
    ns = parser.parse_args(argv)

    Logger.init()

    if ns.operation == "config":
        _run_config(ns.credentials_file, ns.name, ns.use)
        return

    defaults: dict = {
        "api": None,
        "credentials-file": _DEFAULT_CREDENTIALS,
        "printf": "{date} {size:r} {path}",
        "timeout": 30,
        **{k: False for k in [
            "overwrite", "headers", "head", "no-parse", "recursive", "sort",
            "reverse", "dirs-first", "files-only", "dirs-only", "summary",
            "list-empty", "checksum", "human", "confirm", "exists", "no-path",
            "verbose", "no-verify", "hide-root", "debug", "dry-run", "quiet", "no-colors",
        ]},
    }

    Config.set(ns, defaults)
    wd = WebDAVClient()

    if not wd.setargs(ns.operation, _positional_args(ns)) or \
       not wd.credentials(Config["credentials-file"]):
        sys.exit(1)

    if Config["debug"]:
        res = wd.run()
    else:
        try:
            res = wd.run()
        except Exception as e:
            error(f"{e}", 1)

    if res and wd.request.hassuccess():
        if wd.results is None or isinstance(wd.results, bool):
            debug(f"{ns.operation} successful")
        else:
            sys.stdout.write(wd.format())
            sys.stdout.flush()
    else:
        sys.exit(1)
