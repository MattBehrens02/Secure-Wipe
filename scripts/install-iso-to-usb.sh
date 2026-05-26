#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

ISO_PATH="${1:-${ISO_PATH:-}}"
TARGET_DEVICE="${2:-${TARGET_DEVICE:-}}"
OUTPUT_LABEL="${OUTPUT_LABEL:-SWOUTPUT}"
OUTPUT_FILESYSTEM="${OUTPUT_FILESYSTEM:-exfat}"
WINDOWS_HIDE_BOOT_PARTITIONS="${WINDOWS_HIDE_BOOT_PARTITIONS:-1}"

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        fail "run this script as root (sudo)"
    fi
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./scripts/install-iso-to-usb.sh <iso-path> <target-device>

Example:
    sudo ./scripts/install-iso-to-usb.sh out/secure-wipe-trixie-amd64.iso /dev/sdX

Notes:
- target-device must be a whole-disk block device like /dev/sdX or /dev/nvme0n1
- this command destroys existing data on the target device
- after writing the ISO, this script creates and formats a data partition
- defaults: OUTPUT_FILESYSTEM=exfat OUTPUT_LABEL=SWOUTPUT
- defaults: WINDOWS_HIDE_BOOT_PARTITIONS=1 (hide raw ISO partitions from Windows drive-letter assignment)
USAGE
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_dependencies() {
    require_cmd dd
    require_cmd lsblk
    require_cmd parted
    require_cmd partprobe
    require_cmd udevadm
    require_cmd wipefs
    require_cmd mkfs.exfat
}

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

partition_number_from_path() {
    local partition_path="$1"
    local num

    num=$(printf '%s' "$partition_path" | sed -E 's/.*[^0-9]([0-9]+)$/\1/')
    if [ -n "$num" ] && printf '%s' "$num" | grep -Eq '^[0-9]+$'; then
        printf '%s\n' "$num"
        return 0
    fi
    return 1
}

validate_inputs() {
    [ -n "$ISO_PATH" ] || { usage; fail "missing ISO path"; }
    [ -n "$TARGET_DEVICE" ] || { usage; fail "missing target device"; }
    [ -f "$ISO_PATH" ] || fail "ISO file does not exist: $ISO_PATH"
    [ -b "$TARGET_DEVICE" ] || fail "target is not a block device: $TARGET_DEVICE"

    case "$TARGET_DEVICE" in
        *[0-9])
            if [[ "$TARGET_DEVICE" != *"nvme"*"n"* ]]; then
                fail "target device appears to be a partition, not a whole disk: $TARGET_DEVICE"
            fi
            ;;
    esac

    case "$OUTPUT_FILESYSTEM" in
        exfat)
            ;;
        *)
            fail "unsupported OUTPUT_FILESYSTEM '$OUTPUT_FILESYSTEM' (only exfat is supported here)"
            ;;
    esac
}

confirm() {
    printf 'About to write %s to %s\n' "$ISO_PATH" "$TARGET_DEVICE"
    printf 'A new %s partition labeled %s will be created using all remaining space.\n' "$OUTPUT_FILESYSTEM" "$OUTPUT_LABEL"
    printf 'ALL DATA ON %s WILL BE LOST. Type WIPEUSB to continue: ' "$TARGET_DEVICE"
    read -r answer
    [ "$answer" = "WIPEUSB" ] || fail "aborted"
}

partition_paths() {
    lsblk -ln -o NAME "$TARGET_DEVICE" | tail -n +2 | sed 's#^#/dev/#'
}

ensure_partition_nodes() {
    local attempts=20
    local i

    partprobe "$TARGET_DEVICE" || true
    udevadm settle || true

    for i in $(seq 1 "$attempts"); do
        if partition_paths | grep -q .; then
            return 0
        fi
        sleep 1
        partprobe "$TARGET_DEVICE" || true
        udevadm settle || true
    done

    fail "partition nodes did not appear for $TARGET_DEVICE"
}

create_data_partition() {
    local iso_size_bytes
    local start_mib

    iso_size_bytes=$(stat -c%s "$ISO_PATH")
    # Start safely after the ISO payload to avoid overlapping existing hybrid boot structures.
    start_mib=$(( (iso_size_bytes + 1048575) / 1048576 + 8 ))

    # After writing a hybrid ISO image, GPT backup headers can be stale.
    # Force non-interactive repair so mkpart can proceed in scripts.
    parted -s -f "$TARGET_DEVICE" print >/dev/null 2>&1 || true

    printf '[usb] creating data partition from %sMiB to end of disk\n' "$start_mib"
    parted -s "$TARGET_DEVICE" -- mkpart primary "${start_mib}MiB" 100%

    partprobe "$TARGET_DEVICE" || true
    udevadm settle || true
}

detect_new_partition() {
    local before_file="$1"
    local attempts=20
    local i
    local after_parts

    for i in $(seq 1 "$attempts"); do
        partprobe "$TARGET_DEVICE" || true
        udevadm settle || true
        after_parts=$(partition_paths || true)
        while IFS= read -r p; do
            if [ -n "$p" ] && ! grep -Fxq "$p" "$before_file"; then
                printf '%s\n' "$p"
                return 0
            fi
        done <<EOF
$after_parts
EOF
        sleep 1
    done

    return 1
}

format_data_partition() {
    local partition_path="$1"
    local formatter_script="$REPO_ROOT/scripts/format-output-partition.sh"

    [ -x "$formatter_script" ] || fail "formatter script is not executable: $formatter_script"
    "$formatter_script" --yes --partition "$partition_path" --label "$OUTPUT_LABEL" --filesystem "$OUTPUT_FILESYSTEM"
}

set_windows_partition_type() {
    local partition_path="$1"
    local partition_number

    if ! have_cmd sgdisk; then
        printf '[usb] warning: sgdisk not found; skipping GPT type hint for Windows compatibility.\n'
        printf '[usb] warning: install gdisk to enable this step.\n'
        return 0
    fi

    partition_number=$(partition_number_from_path "$partition_path" || true)
    [ -n "$partition_number" ] || {
        printf '[usb] warning: unable to derive partition number from %s; skipping GPT type update.\n' "$partition_path"
        return 0
    }

    # 0700 = Microsoft basic data (helps Windows identify exfat data partition on hybrid media).
    sgdisk --typecode="${partition_number}:0700" --change-name="${partition_number}:${OUTPUT_LABEL}" "$TARGET_DEVICE" >/dev/null
    partprobe "$TARGET_DEVICE" || true
    udevadm settle || true
}

set_windows_mount_behavior() {
    local data_partition_path="$1"
    local data_partition_number
    local part_path
    local part_number

    if [ "$WINDOWS_HIDE_BOOT_PARTITIONS" != "1" ]; then
        return 0
    fi

    if ! have_cmd sgdisk; then
        printf '[usb] warning: sgdisk not found; skipping Windows partition visibility tuning.\n'
        return 0
    fi

    data_partition_number=$(partition_number_from_path "$data_partition_path" || true)
    [ -n "$data_partition_number" ] || {
        printf '[usb] warning: unable to derive data partition number from %s; skipping visibility tuning.\n' "$data_partition_path"
        return 0
    }

    while IFS= read -r part_path; do
        [ -n "$part_path" ] || continue
        part_number=$(partition_number_from_path "$part_path" || true)
        [ -n "$part_number" ] || continue

        # Keep the SWOUTPUT partition visible/mountable in Windows.
        if [ "$part_number" = "$data_partition_number" ]; then
            sgdisk --attributes="${part_number}:clear:62" --attributes="${part_number}:clear:63" "$TARGET_DEVICE" >/dev/null || true
            continue
        fi

        # Mark non-output partitions as hidden + no-automount to reduce Windows prompts.
        sgdisk --attributes="${part_number}:set:62" --attributes="${part_number}:set:63" "$TARGET_DEVICE" >/dev/null || true
    done <<EOF
$(lsblk -ln -o PATH,TYPE "$TARGET_DEVICE" | awk '$2 == "part" {print $1}')
EOF

    partprobe "$TARGET_DEVICE" || true
    udevadm settle || true
}

main() {
    require_root
    require_dependencies
    validate_inputs
    confirm

    local before_parts_file
    local data_partition
    before_parts_file=$(mktemp)
    trap 'rm -f "${before_parts_file:-}"' EXIT

    printf '[usb] unmounting existing partitions on %s\n' "$TARGET_DEVICE"
    while IFS= read -r part; do
        [ -n "$part" ] || continue
        umount "$part" 2>/dev/null || true
    done <<EOF
$(partition_paths || true)
EOF

    if grep -qi microsoft /proc/version 2>/dev/null; then
        printf '[usb] warning: running under WSL. Ensure this disk is attached exclusively to WSL before writing.\n'
    fi

    printf '[usb] wiping existing partition signatures on %s\n' "$TARGET_DEVICE"
    wipefs -a "$TARGET_DEVICE"

    printf '[usb] writing ISO image...\n'
    dd if="$ISO_PATH" of="$TARGET_DEVICE" bs=4M status=progress oflag=sync conv=fsync
    sync

    partprobe "$TARGET_DEVICE" || true
    udevadm settle || true
    partition_paths > "$before_parts_file" || true

    create_data_partition
    ensure_partition_nodes

    data_partition=$(detect_new_partition "$before_parts_file") || fail "failed to detect newly created data partition"

    set_windows_partition_type "$data_partition"
    set_windows_mount_behavior "$data_partition"

    printf '[usb] formatting data partition %s as %s\n' "$data_partition" "$OUTPUT_FILESYSTEM"
    format_data_partition "$data_partition"

    printf '[usb] done. boot partition written and data partition created.\n'
    printf '[usb] target: %s\n' "$TARGET_DEVICE"
    printf '[usb] data partition: %s\n' "$data_partition"
    printf '[usb] data filesystem: %s label=%s\n' "$OUTPUT_FILESYSTEM" "$OUTPUT_LABEL"
    printf '[usb] verify with: lsblk -f %s\n' "$TARGET_DEVICE"
}

main "$@"
