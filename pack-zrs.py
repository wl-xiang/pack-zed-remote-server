#!/usr/bin/env python3
"""
Download latest stable ZRS from GitHub releases and pack as tgz
matching the exact filename Zed uses to skip online download.

Skip logic reference (crates/remote/src/transport/ssh.rs:840-853):
  binary_name = "zed-remote-server-{channel}-{version}"
  where version = client's full semver string including +build metadata.

Usage:
  # Get your client version:
  zed --version
  # Output: Zed 1.20.2+stable.356.df181c6f58d02677b385fa947d6bfde6d3530078

  # Then run this script:
  python3 pack-zrs.py --version 1.20.2+stable.356.df181c6f58d02677b385fa947d6bfde6d3530078

  # Or with just the tag version (if your client matches):
  python3 pack-zrs.py --version 1.20.2

  # Dry run to see what would happen:
  python3 pack-zrs.py --version 1.20.2 --dry-run

  # Specify platform explicitly:
  python3 pack-zrs.py --version 1.20.2 --os linux --arch x86_64

Deploy:
  scp *.tgz <host>:~/.zed_server/
  ssh <host> 'cd ~/.zed_server && tar xzf *.tgz && chmod +x zed-remote-server-*'
"""

import argparse
import gzip
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/zed-industries/zed/releases"
CHANNEL = "stable"

PLATFORM_MAP = {
    ("Linux", "x86_64"): ("linux", "x86_64"),
    ("Linux", "aarch64"): ("linux", "aarch64"),
    ("Darwin", "x86_64"): ("macos", "x86_64"),
    ("Darwin", "arm64"): ("macos", "aarch64"),
}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pack-zrs/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_latest_stable_release() -> dict:
    releases = fetch_json(f"{GITHUB_API}?per_page=10")
    for r in releases:
        if not r["prerelease"] and not r["draft"]:
            return r
    raise RuntimeError("No stable release found")


def detect_platform() -> tuple[str, str]:
    key = (platform.system(), platform.machine())
    if key in PLATFORM_MAP:
        return PLATFORM_MAP[key]
    raise RuntimeError(
        f"Unsupported platform: {key}. Use --os and --arch to specify manually."
    )


def find_asset(release: dict, os_name: str, arch: str) -> tuple[dict, str]:
    """Find asset and return (asset_info, extension)."""
    ext = "zip" if os_name == "windows" else "gz"
    asset_name = f"zed-remote-server-{os_name}-{arch}.{ext}"
    for a in release["assets"]:
        if a["name"] == asset_name:
            return a, ext
    raise RuntimeError(
        f"Asset {asset_name} not found in release {release['tag_name']}"
    )


def download_file(url: str, dest: Path) -> None:
    """Download with progress and retry."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pack-zrs/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                start = time.time()
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)  # 1MB chunks
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded * 100 // total
                            elapsed = time.time() - start
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            print(
                                f"\r  {pct:3d}% ({downloaded}/{total}) "
                                f"{speed / 1024 / 1024:.1f} MB/s",
                                end="",
                                flush=True,
                            )
                print()  # newline after progress
            print(f"  -> {dest} ({dest.stat().st_size} bytes)")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"\n  Retry {attempt + 2}/{max_retries}: {e}")
                time.sleep(2)
            else:
                raise


def unpack_gz(gz_path: Path, dest: Path) -> None:
    with gzip.open(gz_path, "rb") as f_in:
        with open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.chmod(dest, 0o755)
    print(f"Unpacked: {dest.name} ({dest.stat().st_size} bytes)")


def unpack_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Unzip and return path to the binary."""
    import zipfile
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Windows zip contains zed-remote-server.exe
        names = zf.namelist()
        if len(names) != 1:
            raise RuntimeError(f"Expected 1 file in zip, got {names}")
        zf.extractall(dest_dir)
        extracted = dest_dir / names[0]
    os.chmod(extracted, 0o755)
    print(f"Unpacked: {extracted.name} ({extracted.stat().st_size} bytes)")
    return extracted


def pack_tgz(source_file: Path, tgz_path: Path) -> None:
    with tarfile.open(tgz_path, "w:gz") as tar:
        tar.add(source_file, arcname=source_file.name)
    print(f"Packed:   {tgz_path.name} ({tgz_path.stat().st_size} bytes)")


def main():
    parser = argparse.ArgumentParser(
        description="Download stable ZRS and pack as tgz with correct skip-logic filename",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --version 1.20.2+stable.356.df181c6f...
  %(prog)s --version 1.20.2
  %(prog)s --version 1.20.2 --dry-run
  %(prog)s --version 1.20.2 --os linux --arch x86_64
""",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Full version string as shown by 'zed --version'. "
             "At minimum use tag version like 1.20.2.",
    )
    parser.add_argument(
        "--os",
        choices=["linux", "macos", "windows"],
        help="Target OS (auto-detected if omitted)",
    )
    parser.add_argument(
        "--arch",
        choices=["x86_64", "aarch64"],
        help="Target architecture (auto-detected if omitted)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory (default: current dir)",
    )
    parser.add_argument(
        "--tag",
        help="Specific release tag (default: latest stable, e.g. v1.20.2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without downloading",
    )
    args = parser.parse_args()

    # --- Determine OS/arch ---
    if args.os and args.arch:
        os_name, arch = args.os, args.arch
    else:
        os_name, arch = detect_platform()
    print(f"Platform:  {os_name}/{arch}")

    # --- Get release ---
    if args.tag:
        tag = args.tag if args.tag.startswith("v") else f"v{args.tag}"
        print(f"Fetching release: {tag}")
        try:
            release = fetch_json(f"{GITHUB_API}/tags/{tag}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"Error: Release tag '{tag}' not found on GitHub.")
                print("Check available tags at: https://github.com/zed-industries/zed/releases")
                sys.exit(1)
            raise
    else:
        print("Fetching latest stable release...")
        release = get_latest_stable_release()

    tag = release["tag_name"]
    print(f"Release:   {tag}")

    # --- Build skip-logic filename ---
    # ssh.rs:840-843: version_str = version.to_string() for non-Dev channels
    # ssh.rs:844-846: binary_name = "zed-remote-server-{channel}-{version_str}"
    version_str = args.version
    binary_name = f"zed-remote-server-{CHANNEL}-{version_str}"
    if os_name == "windows":
        binary_name += ".exe"

    tgz_name = f"{binary_name}.tgz"

    print(f"Channel:   {CHANNEL}")
    print(f"Version:   {version_str}")
    print(f"Filename:  {binary_name}")
    print(f"TGZ:       {tgz_name}")
    print()

    # --- Find asset ---
    asset, asset_ext = find_asset(release, os_name, arch)
    dl_url = asset["browser_download_url"]
    print(f"Asset:     {asset['name']} ({asset['size']:,} bytes)")
    print(f"URL:       {dl_url}")
    print()

    if args.dry_run:
        print("--- DRY RUN ---")
        print(f"Would download: {dl_url}")
        print(f"Would unpack to: {binary_name}")
        print(f"Would pack as:   {tgz_name}")
        print()
        print("Deploy commands:")
        print(f"  scp {tgz_name} <host>:~/.zed_server/")
        print(f"  ssh <host> 'cd ~/.zed_server && tar xzf {tgz_name} && chmod +x {binary_name}'")
        return

    # --- Download, unpack, repack ---
    args.output_dir.mkdir(parents=True, exist_ok=True)

    tgz_path = args.output_dir / tgz_name
    if tgz_path.exists():
        print(f"Warning: {tgz_path} already exists, overwriting")
        tgz_path.unlink()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Step 1: Download from GitHub
        dl_path = tmpdir / asset["name"]
        print(f"Step 1/3: Downloading .{asset_ext} from GitHub...")
        download_file(dl_url, dl_path)

        # Step 2: Unpack to get the raw binary
        binary_path = tmpdir / binary_name
        print(f"Step 2/3: Unpacking .{asset_ext}...")
        if asset_ext == "zip":
            extracted = unpack_zip(dl_path, tmpdir)
            shutil.move(extracted, binary_path)
        else:
            unpack_gz(dl_path, binary_path)

        # Step 3: Pack as .tgz with skip-logic filename
        print("Step 3/3: Packing .tgz...")
        pack_tgz(binary_path, tgz_path)

    print()
    print("=" * 60)
    print(f"Output: {tgz_path}")
    print()
    print("Deploy to remote server:")
    print(f"  scp {tgz_path} <host>:~/.zed_server/")
    print(f"  ssh <host> 'cd ~/.zed_server && tar xzf {tgz_name} && chmod +x {binary_name}'")
    print()
    print("Verify skip works:")
    print(f"  ssh <host> '~/.zed_server/{binary_name} version'")
    print("=" * 60)


if __name__ == "__main__":
    main()
