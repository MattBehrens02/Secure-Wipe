# Secure-Wipe Live ISO

Secure-Wipe is a terminal-first drive sanitization workflow packaged as a bootable Debian-based live ISO.

This repository now contains the full build flow:
- Build the live ISO from this repo
- Write the ISO to USB
- Create a persistent output partition on remaining disk space
- Boot and run the Secure-Wipe application from the live environment

## Repository Layout

```text
Secure-Wipe/
├── app/                         # Secure-Wipe application code
├── config/chroot-packages.txt   # Debian packages installed in the live image
├── iso/boot/grub/grub.cfg       # GRUB boot menu
├── overlay/                     # Files copied into the live rootfs
├── scripts/
│   ├── build-iso.sh             # Build live ISO
│   ├── install-iso-to-usb.sh    # Write ISO + create data partition
│   ├── format-output-partition.sh
│   └── update-iso-preserve-output.sh  # Refresh ISO while restoring output data backup
├── build/                       # Build artifacts (gitignored)
└── out/                         # Final ISO output (gitignored)
```

## What The Build Produces

- Bootable amd64 live ISO
- Debian root filesystem with live-boot and systemd
- Auto-login terminal user named its
- Secure-Wipe app staged at /opt/live-app
- Launcher command securewipe in the live environment

## Host Prerequisites

Run these on the machine doing the ISO build (Linux or WSL distro):

```bash
sudo apt update
sudo apt install -y \
  debootstrap \
  grub-common \
  grub-pc-bin \
  grub-efi-amd64-bin \
  mtools \
  xorriso \
  squashfs-tools \
  parted \
  util-linux \
  udev \
  exfatprogs \
  gdisk
```

Notes:
- gdisk is optional but recommended so the USB installer can set GPT hints for better Windows behavior.
- You must run the build and USB installer scripts with sudo.

## Minimum Requirements

The tables below separate the host used to build and write the ISO from the machine that boots the live USB.

### Installer Host

| Item | Minimum | Notes |
|---|---:|---|
| OS | Linux or WSL | Used to build the ISO and write it to USB |
| Privileges | sudo/root | The build and installer scripts require elevated privileges |
| CPU architecture | amd64/x86_64 | The generated live ISO is amd64-based |
| RAM | 2 GB | Enough for the build tooling on a minimal host |
| USB tooling | present | `debootstrap`, GRUB tools, `xorriso`, `squashfs-tools`, `parted`, `util-linux`, `udev`, and `exfatprogs` |
| Optional tooling | gdisk | Recommended for Windows-friendly GPT hints |
| USB stick size | 2 GB minimum recommended | The live ISO is under 500 MB and the remaining space is enough for roughly 1.5 GB of persistent storage |

### Wipe Station

| Item | Minimum | Notes |
|---|---:|---|
| Boot support | USB boot capable system | The target machine must be able to boot the live ISO from USB |
| CPU architecture | amd64/x86_64 | The live environment is built for amd64 |
| RAM | 2 GB | Sufficient for the terminal-based live workflow |
| USB stick size | 2 GB minimum recommended | Leaves room for the live ISO plus persistent reports, logs, and state |
| Persistent storage | About 1.5 GB usable | Reports are only a few KB each, so most of the space is for logs and state rather than output files |

## Build ISO (Native Linux or WSL)

From the repository root:

```bash
sudo ./scripts/build-iso.sh
```

Default output:

```text
out/secure-wipe-trixie-amd64.iso
```

Optional build variables:

```bash
sudo DIST=bookworm ARCH=amd64 ISO_NAME=secure-wipe-bookworm-amd64.iso ./scripts/build-iso.sh
```

Supported variables:
- DIST (default: trixie)
- ARCH (default: amd64)
- MIRROR (default: http://deb.debian.org/debian)
- ISO_NAME (default: secure-wipe-<dist>-<arch>.iso)
- BUILD_DIR (default: ./build)
- OUT_DIR (default: ./out)

## Install ISO To USB

Warning: this destroys all data on the target disk.

```bash
sudo ./scripts/install-iso-to-usb.sh out/secure-wipe-trixie-amd64.iso /dev/sdX
```

What this script does:
1. Wipes signatures on the target disk
2. Writes the ISO image to disk
3. Creates a new partition using remaining space
4. Formats that partition as exfat with label SWOUTPUT
5. Applies Windows-friendly GPT partition flags (when gdisk is available)
6. Seeds `docs/` from this repository into the output partition at `docs/`

You will be prompted to type WIPEUSB before destructive actions start.

### USB installer options

```bash
sudo OUTPUT_FILESYSTEM=exfat OUTPUT_LABEL=SWOUTPUT WINDOWS_HIDE_BOOT_PARTITIONS=1 \
  ./scripts/install-iso-to-usb.sh out/secure-wipe-trixie-amd64.iso /dev/sdX
```

Current installer supports OUTPUT_FILESYSTEM=exfat for the integrated flow.

## Update ISO While Preserving Output Data

Use this script when you want to refresh the boot ISO on a USB device and restore existing `SWOUTPUT` data afterward:

```bash
sudo ./scripts/update-iso-preserve-output.sh out/secure-wipe-trixie-amd64.iso /dev/sdX
```

What this script does:
1. Finds the current output partition (default label `SWOUTPUT`)
2. Copies output data to a staging backup directory
3. Runs the standard installer flow to rewrite the ISO and recreate partitions
4. Restores the staged data to the newly created output partition
5. Verifies restored file count/size against backup

Optional flags:

```bash
sudo ./scripts/update-iso-preserve-output.sh \
  --iso out/secure-wipe-trixie-amd64.iso \
  --target /dev/sdX \
  --staging-dir /path/to/staging \
  --label SWOUTPUT \
  --yes
```

Notes:
- This script still invokes the base installer, so it rewrites the target disk and then restores backed-up output data.
- It is intended as an update/repair helper for small output datasets.

## Manual Output Partition Formatting

If needed, format a specific partition manually:

```bash
sudo ./scripts/format-output-partition.sh /dev/sdX3 SWOUTPUT exfat
```

Or non-interactive:

```bash
sudo ./scripts/format-output-partition.sh --yes --partition /dev/sdX3 --label SWOUTPUT --filesystem exfat
```

## Windows + WSL USB Workflow (usbipd)

When running installer scripts inside WSL, pass the physical USB disk through to WSL first.

### 1) In Administrator PowerShell (Windows)

List attachable USB devices:

```powershell
usbipd list
```

Bind the target USB bus ID (if needed):

```powershell
usbipd bind --busid <BUSID>
```

Attach to your WSL distro:

```powershell
usbipd attach --wsl --busid <BUSID>
```

### 2) In WSL terminal

Confirm the disk identity before any destructive command:

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,TYPE
```

Run installer from this repo:

```bash
cd /home/mbehrens/projects/Secure-Wipe
sudo ./scripts/install-iso-to-usb.sh out/secure-wipe-trixie-amd64.iso /dev/sdX
```

### 3) After finishing (Administrator PowerShell)

Detach the USB from WSL so Windows can own it again:

```powershell
usbipd detach --busid <BUSID>
```

WSL safety notes:
- Ensure the disk is not mounted by Windows while writing.
- Re-run lsblk immediately before using the installer.
- Always target the whole disk path (for example /dev/sdX), not a partition.

## Boot And Runtime Behavior

At boot, the live OS:
- Presents a Secure-Wipe GRUB menu entry
- Auto-logs in on tty1 as user its
- Starts the Secure-Wipe launcher via systemd service

The app includes main menu actions for:
- Start Job
- Restart Pending Jobs
- View Reports
- View Logs
- Configuration
- Maintenance
- Open Terminal
- Shutdown System
- Restart System

Main menu navigation uses numeric options only.

## App Configuration

The app config file is:

```text
app/configuration.toml
```

From inside the app, changing settings in the Configuration menu persists values to configuration.toml and now retains inline option hints/comments for user-facing keys.

## Documentation

Application-focused docs in this repository:
- [docs/operator-runbook.md](docs/operator-runbook.md): Day-to-day operator workflow, runtime modes, menu usage, and completion checklist.
- [docs/hard-failure-playbook.md](docs/hard-failure-playbook.md): Recovery procedures for lock contention, interrupted runs, and other hard-failure scenarios.
- [docs/developer-guide.md](docs/developer-guide.md): Architecture, module responsibilities, testing expectations, and development workflow.

Core app references:
- [app/configuration.toml](app/configuration.toml): User-facing configuration values and inline option hints.
- [app/main.py](app/main.py): Application entrypoint and orchestration flow.

## Quick Validation Checklist

1. Build succeeds and emits out/secure-wipe-*.iso
2. USB installer completes without partition detection errors
3. lsblk shows ISO partitions plus SWOUTPUT data partition
4. Boot target hardware from USB and confirm app starts on tty1
5. Generate a dry-run report and verify output paths

## Troubleshooting

If build script reports missing commands, install the apt packages shown under Host Prerequisites.

If install script reports formatter script is not executable, run:

```bash
chmod +x ./scripts/format-output-partition.sh
```

If WSL cannot access USB disk, verify usbipd attach was run from Administrator PowerShell and re-check lsblk in WSL.

If the update-preserve script reports `unknown filesystem type exfat`, the host does not have exFAT mount support available. Run it on a system with kernel exFAT support enabled, or install the appropriate exFAT mount support for that host before retrying.

## License

To be determined.
