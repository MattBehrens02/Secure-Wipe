#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

ISO_PATH=""
TARGET_DEVICE=""
OUTPUT_LABEL="${OUTPUT_LABEL:-SWOUTPUT}"
OUTPUT_FILESYSTEM="${OUTPUT_FILESYSTEM:-exfat}"
WINDOWS_HIDE_BOOT_PARTITIONS="${WINDOWS_HIDE_BOOT_PARTITIONS:-1}"
STAGING_DIR=""
YES_MODE=0

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./scripts/update-iso-preserve-output.sh <iso-path> <target-device>
  sudo ./scripts/update-iso-preserve-output.sh --iso <iso-path> --target <target-device> [--staging-dir <path>] [--label <label>] [--yes]

Example:
  sudo ./scripts/update-iso-preserve-output.sh out/secure-wipe-trixie-amd64.iso /dev/sdX

Behavior:
- Backs up existing output partition data (label defaults to SWOUTPUT)
- Re-installs ISO using install-iso-to-usb.sh
- Restores backed-up data to the newly created output partition

Notes:
- This is destructive to target-device contents except data restored from backup
- Installer still asks for WIPEUSB confirmation unless script behavior changes
USAGE
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        fail "run this script as root (sudo)"
    fi
}

parse_args() {
    local positional=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            --iso)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --iso"
                ISO_PATH="$1"
                ;;
            --target)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --target"
                TARGET_DEVICE="$1"
                ;;
            --staging-dir)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --staging-dir"
                STAGING_DIR="$1"
                ;;
            --label)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --label"
                OUTPUT_LABEL="$1"
                ;;
            --yes|-y)
                YES_MODE=1
                ;;
            --)
                shift
                while [ "$#" -gt 0 ]; do
                    positional+=("$1")
                    shift
                done
                ;;
            -*)
                fail "unknown option: $1"
                ;;
            *)
                positional+=("$1")
                ;;
        esac
        shift
    done

    if [ -z "$ISO_PATH" ] && [ "${#positional[@]}" -gt 0 ]; then
        ISO_PATH="${positional[0]}"
    fi
    if [ -z "$TARGET_DEVICE" ] && [ "${#positional[@]}" -gt 1 ]; then
        TARGET_DEVICE="${positional[1]}"
    fi
    if [ "${#positional[@]}" -gt 2 ]; then
        usage
        fail "too many positional arguments"
    fi
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

partition_paths() {
    lsblk -ln -o NAME "$TARGET_DEVICE" | tail -n +2 | sed 's#^#/dev/#'
}

find_output_partition() {
    local by_label
    by_label="/dev/disk/by-label/$OUTPUT_LABEL"

    if [ -e "$by_label" ]; then
        readlink -f "$by_label"
        return 0
    fi

    # Fallback: choose a partition on target with matching filesystem and a non-empty label.
    lsblk -prno PATH,TYPE,FSTYPE,LABEL "$TARGET_DEVICE" \
        | awk '$2 == "part" && $3 == "exfat" && $4 != "" {print $1; exit}'
}

belongs_to_target() {
    local partition_path="$1"
    local parent
    local target_name

    parent=$(lsblk -no PKNAME "$partition_path" 2>/dev/null || true)
    target_name=$(basename "$TARGET_DEVICE")
    [ -n "$parent" ] && [ "$parent" = "$target_name" ]
}

ensure_not_mounted() {
    local partition_path="$1"
    if lsblk -no MOUNTPOINT "$partition_path" | grep -q .; then
        fail "output partition is mounted; unmount it before running: $partition_path"
    fi
}

confirm() {
    printf 'About to update ISO on %s while preserving data from label %s\n' "$TARGET_DEVICE" "$OUTPUT_LABEL"
    printf 'ISO source: %s\n' "$ISO_PATH"
    printf 'This operation rewrites the device and restores staged data afterwards.\n'
    printf 'Type PRESERVEUSB to continue: '
    local answer
    read -r answer
    [ "$answer" = "PRESERVEUSB" ] || fail "aborted"
}

prepare_staging_dir() {
    if [ -n "$STAGING_DIR" ]; then
        mkdir -p "$STAGING_DIR"
        STAGING_DIR=$(cd "$STAGING_DIR" && pwd)
    else
        STAGING_DIR=$(mktemp -d /tmp/securewipe-preserve.XXXXXX)
    fi

    mkdir -p "$STAGING_DIR/backup" "$STAGING_DIR/mount-old" "$STAGING_DIR/mount-new"
}

backup_output_data() {
    local source_partition="$1"
    local backup_dir="$STAGING_DIR/backup"

    printf '[preserve] backing up data from %s\n' "$source_partition"
    mount -o ro "$source_partition" "$STAGING_DIR/mount-old"
    if [ -d "$STAGING_DIR/mount-old" ] && [ -n "$(ls -A "$STAGING_DIR/mount-old" 2>/dev/null || true)" ]; then
        cp -a "$STAGING_DIR/mount-old/." "$backup_dir/"
    fi
    sync
    umount "$STAGING_DIR/mount-old"

    find "$backup_dir" -type f | wc -l > "$STAGING_DIR/backup_file_count"
    du -sb "$backup_dir" | awk '{print $1}' > "$STAGING_DIR/backup_bytes"
    printf '[preserve] backup complete: files=%s bytes=%s\n' "$(cat "$STAGING_DIR/backup_file_count")" "$(cat "$STAGING_DIR/backup_bytes")"
}

run_installer() {
    local installer="$REPO_ROOT/scripts/install-iso-to-usb.sh"
    [ -x "$installer" ] || fail "installer script is not executable: $installer"

    printf '[preserve] running base installer\n'
    OUTPUT_LABEL="$OUTPUT_LABEL" \
    OUTPUT_FILESYSTEM="$OUTPUT_FILESYSTEM" \
    WINDOWS_HIDE_BOOT_PARTITIONS="$WINDOWS_HIDE_BOOT_PARTITIONS" \
    "$installer" "$ISO_PATH" "$TARGET_DEVICE"
}

restore_output_data() {
    local destination_partition="$1"
    local backup_dir="$STAGING_DIR/backup"

    printf '[preserve] restoring data to %s\n' "$destination_partition"
    mount "$destination_partition" "$STAGING_DIR/mount-new"
    if [ -d "$backup_dir" ] && [ -n "$(ls -A "$backup_dir" 2>/dev/null || true)" ]; then
        cp -a "$backup_dir/." "$STAGING_DIR/mount-new/"
    fi
    sync
    umount "$STAGING_DIR/mount-new"

    find "$backup_dir" -type f | wc -l > "$STAGING_DIR/restore_expected_file_count"
    du -sb "$backup_dir" | awk '{print $1}' > "$STAGING_DIR/restore_expected_bytes"
}

verify_restore() {
    local destination_partition="$1"
    local expected_files
    local expected_bytes
    local restored_files
    local restored_bytes

    expected_files=$(cat "$STAGING_DIR/restore_expected_file_count")
    expected_bytes=$(cat "$STAGING_DIR/restore_expected_bytes")

    mount -o ro "$destination_partition" "$STAGING_DIR/mount-new"
    restored_files=$(find "$STAGING_DIR/mount-new" -type f | wc -l)
    restored_bytes=$(du -sb "$STAGING_DIR/mount-new" | awk '{print $1}')
    umount "$STAGING_DIR/mount-new"

    printf '[preserve] restore verification: expected_files=%s restored_files=%s expected_bytes=%s restored_bytes=%s\n' \
        "$expected_files" "$restored_files" "$expected_bytes" "$restored_bytes"

    if [ "$restored_files" -lt "$expected_files" ]; then
        fail "restore verification failed: restored file count is lower than backup"
    fi

    if [ "$restored_bytes" -lt "$expected_bytes" ]; then
        fail "restore verification failed: restored bytes are lower than backup"
    fi
}

cleanup() {
    set +e
    if mountpoint -q "$STAGING_DIR/mount-old" 2>/dev/null; then
        umount "$STAGING_DIR/mount-old"
    fi
    if mountpoint -q "$STAGING_DIR/mount-new" 2>/dev/null; then
        umount "$STAGING_DIR/mount-new"
    fi
}

main() {
    parse_args "$@"
    require_root
    require_cmd lsblk
    require_cmd mount
    require_cmd umount
    require_cmd cp
    require_cmd find
    require_cmd du
    validate_inputs

    local old_output_partition
    old_output_partition=$(find_output_partition || true)
    [ -n "$old_output_partition" ] || fail "could not find existing output partition with label '$OUTPUT_LABEL'"
    [ -b "$old_output_partition" ] || fail "resolved output partition is not a block device: $old_output_partition"
    belongs_to_target "$old_output_partition" || fail "resolved output partition does not belong to target device: $old_output_partition"
    ensure_not_mounted "$old_output_partition"

    if [ "$YES_MODE" -ne 1 ]; then
        confirm
    fi

    prepare_staging_dir
    trap cleanup EXIT

    backup_output_data "$old_output_partition"
    run_installer

    local new_output_partition
    new_output_partition=$(find_output_partition || true)
    [ -n "$new_output_partition" ] || fail "could not find newly created output partition with label '$OUTPUT_LABEL'"
    [ -b "$new_output_partition" ] || fail "resolved new output partition is not a block device: $new_output_partition"
    belongs_to_target "$new_output_partition" || fail "new output partition does not belong to target device: $new_output_partition"

    restore_output_data "$new_output_partition"
    verify_restore "$new_output_partition"

    printf '[preserve] update complete. staged backup remains at %s\n' "$STAGING_DIR"
}

main "$@"
