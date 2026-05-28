#!/usr/bin/env bash
set -euo pipefail

PARTITION_PATH=""
LABEL="SWOUTPUT"
FILESYSTEM="ext4"
YES_MODE=0

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./scripts/format-output-partition.sh <partition-path> [label]
  sudo ./scripts/format-output-partition.sh <partition-path> [label] [filesystem]
  sudo ./scripts/format-output-partition.sh --partition /dev/sdX3 --label SWOUTPUT --filesystem exfat

Example:
  sudo ./scripts/format-output-partition.sh /dev/sdX3 SWOUTPUT
  sudo ./scripts/format-output-partition.sh /dev/sdX3 SWOUTPUT exfat

Notes:
- target must be a partition (not whole disk)
- this formats the partition as ext4 or exfat and destroys its existing data
- default filesystem is ext4
USAGE
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

parse_args() {
    local positional=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            -y|--yes)
                YES_MODE=1
                ;;
            -p|--partition)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --partition"
                PARTITION_PATH="$1"
                ;;
            -l|--label)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --label"
                LABEL="$1"
                ;;
            -f|--filesystem)
                shift
                [ "$#" -gt 0 ] || fail "missing value for --filesystem"
                FILESYSTEM="$1"
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

    if [ -z "$PARTITION_PATH" ] && [ "${#positional[@]}" -gt 0 ]; then
        PARTITION_PATH="${positional[0]}"
    fi
    if [ "${#positional[@]}" -gt 1 ]; then
        LABEL="${positional[1]}"
    fi
    if [ "${#positional[@]}" -gt 2 ]; then
        FILESYSTEM="${positional[2]}"
    fi
    if [ "${#positional[@]}" -gt 3 ]; then
        usage
        fail "too many positional arguments"
    fi
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        fail "run this script as root (sudo)"
    fi
}

validate_inputs() {
    [ -n "$PARTITION_PATH" ] || { usage; fail "missing partition path"; }
    [ -b "$PARTITION_PATH" ] || fail "not a block device: $PARTITION_PATH"

    if lsblk -no TYPE "$PARTITION_PATH" | grep -qv '^part$'; then
        fail "target must be a partition, got: $PARTITION_PATH"
    fi

    case "$FILESYSTEM" in
        ext4|exfat)
            ;;
        *)
            fail "unsupported filesystem '$FILESYSTEM' (use ext4 or exfat)"
            ;;
    esac
}

confirm() {
    printf 'About to format %s as %s with label %s\n' "$PARTITION_PATH" "$FILESYSTEM" "$LABEL"
    printf 'ALL DATA ON %s WILL BE LOST. Type FORMAT to continue: ' "$PARTITION_PATH"
    read -r answer
    [ "$answer" = "FORMAT" ] || fail "aborted"
}

format_partition() {
    case "$FILESYSTEM" in
        ext4)
            require_cmd mkfs.ext4
            mkfs.ext4 -F -L "$LABEL" "$PARTITION_PATH"
            ;;
        exfat)
            require_cmd mkfs.exfat
            mkfs.exfat -n "$LABEL" "$PARTITION_PATH"
            ;;
    esac
}

main() {
    parse_args "$@"
    require_root
    validate_inputs
    if [ "$YES_MODE" -ne 1 ]; then
        confirm
    fi

    umount "$PARTITION_PATH" 2>/dev/null || true
    format_partition

    printf '[output] formatted %s as %s label=%s\n' "$PARTITION_PATH" "$FILESYSTEM" "$LABEL"
    printf '[output] live system can now mount /dev/disk/by-label/%s to /output\n' "$LABEL"
}

main "$@"
