# Pack ZRS (zed-remote-server)

Download the latest stable `zed-remote-server` binary from GitHub releases, rename it to match Zed's skip-logic filename, and pack as `.tgz` for offline deployment.

## Why

When Zed connects to a remote host via SSH, it checks for a binary at:

```
~/.zed_server/zed-remote-server-{channel}-{version}
```

If the file exists and runs successfully, the download is skipped. This script produces a `.tgz` with the exact filename Zed expects, so you can pre-deploy it to remote hosts.

## Files

| File | Description |
|------|-------------|
| `pack-zrs.py` | Python script that downloads and packs the binary |
| `pack-zrs.yml` | GitHub Actions workflow for automated builds |

## Usage

### Get your version string

```bash
zed --version
# → Zed 1.20.2+stable.356.df181c6f58d02677b385fa947d6bfde6d3530078
```

### Run the script

```bash
# Using full version string
python3 pack-zrs.py --version 1.20.2+stable.356.df181c6f58d02677b385fa947d6bfde6d3530078

# Using just tag version (if your client matches)
python3 pack-zrs.py --version 1.20.2

# Preview without downloading
python3 pack-zrs.py --version 1.20.2 --dry-run

# Cross-platform (build for a different target)
python3 pack-zrs.py --version 1.20.2 --os macos --arch aarch64
```

### Options

| Flag | Description |
|------|-------------|
| `--version` | Required. Version string from `zed --version` |
| `--os` | Target OS: `linux`, `macos`, `windows` (auto-detected) |
| `--arch` | Target arch: `x86_64`, `aarch64` (auto-detected) |
| `--tag` | Specific release tag, e.g. `v1.20.2` (default: latest stable) |
| `--output-dir` | Output directory (default: current dir) |
| `--dry-run` | Show what would happen without downloading |

## Deploy to remote host

```bash
# Copy to remote
scp zed-remote-server-stable-*.tgz <host>:~/.zed_server/

# Extract and set permissions
ssh <host> 'cd ~/.zed_server && tar xzf zed-remote-server-stable-*.tgz && chmod +x zed-remote-server-stable-*'

# Verify
ssh <host> '~/.zed_server/zed-remote-server-stable-* version'
```

## GitHub Actions

The workflow `pack-zrs.yml` can be triggered manually from the Actions tab.

| Input | Default | Description |
|-------|---------|-------------|
| `version` | (empty) | Version string. Empty = latest stable |
| `os` | `linux` | Target OS |
| `arch` | `x86_64` | Target architecture |

The resulting `.tgz` is uploaded as a downloadable artifact (30 day retention).

## Filename format

The binary name follows Zed's skip logic at `crates/remote/src/transport/ssh.rs:840-853`:

```
zed-remote-server-{channel}-{version}
```

- `{channel}`: `stable`, `nightly`, `preview`, or `dev`
- `{version}`: Full semver string including build metadata (e.g. `1.20.2+stable.356.df181c6f...`)

The version string is compiled into the Zed client binary. You must use the exact version your client reports.

## Requirements

- Python 3.10+
- No external dependencies (uses only stdlib)

## Troubleshooting

**"Release tag not found"** - Check the tag exists at https://github.com/zed-industries/zed/releases

**"Asset not found"** - The release may not have the binary for your platform. Check available assets.

**Zed still downloads online** - The filename must match exactly. Run `zed --version` and use the full output.
