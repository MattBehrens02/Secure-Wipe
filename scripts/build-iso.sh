#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

DIST="${DIST:-trixie}"
ARCH="${ARCH:-amd64}"
MIRROR="${MIRROR:-http://deb.debian.org/debian}"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/out}"
ISO_NAME="${ISO_NAME:-secure-wipe-${DIST}-${ARCH}.iso}"

ROOTFS_DIR="$BUILD_DIR/rootfs"
ISO_ROOT="$BUILD_DIR/iso-root"
PACKAGES_FILE="$REPO_ROOT/config/chroot-packages.txt"
APP_DIR="$REPO_ROOT/app"
OVERLAY_DIR="$REPO_ROOT/overlay"
GRUB_CFG="$REPO_ROOT/iso/boot/grub/grub.cfg"
REQUIREMENTS_FILE="$APP_DIR/requirements.txt"
OUTPUT_ISO="$OUT_DIR/$ISO_NAME"

cleanup() {
    set +e
    if mountpoint -q "$ROOTFS_DIR/dev/pts"; then
        umount "$ROOTFS_DIR/dev/pts"
    fi
    if mountpoint -q "$ROOTFS_DIR/dev"; then
        umount "$ROOTFS_DIR/dev"
    fi
    if mountpoint -q "$ROOTFS_DIR/proc"; then
        umount "$ROOTFS_DIR/proc"
    fi
    if mountpoint -q "$ROOTFS_DIR/sys"; then
        umount "$ROOTFS_DIR/sys"
    fi
    if mountpoint -q "$ROOTFS_DIR/run"; then
        umount "$ROOTFS_DIR/run"
    fi
}

trap cleanup EXIT

log() {
    printf '[build] %s\n' "$1"
}

fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        fail "run this script with sudo or as root"
    fi
}

require_files() {
    [ -f "$PACKAGES_FILE" ] || fail "missing $PACKAGES_FILE"
    [ -f "$APP_DIR/main.py" ] || fail "missing $APP_DIR/main.py"
    [ -f "$GRUB_CFG" ] || fail "missing $GRUB_CFG"
}

require_commands() {
    local missing=()
    local cmd
    for cmd in chroot cp debootstrap find grub-mkrescue mformat mksquashfs mount mountpoint tr umount xorriso; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("$cmd")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        printf 'missing commands: %s\n' "${missing[*]}" >&2
        printf 'install: debootstrap grub-common grub-pc-bin grub-efi-amd64-bin mtools xorriso squashfs-tools\n' >&2
        exit 1
    fi
}

prepare_dirs() {
    rm -rf "$BUILD_DIR"
    mkdir -p "$ROOTFS_DIR" "$ISO_ROOT/live" "$ISO_ROOT/boot/grub" "$OUT_DIR"
}

bootstrap_rootfs() {
    log "bootstrapping Debian $DIST ($ARCH)"
    debootstrap --arch="$ARCH" --variant=minbase "$DIST" "$ROOTFS_DIR" "$MIRROR"
}

mount_chroot() {
    mkdir -p "$ROOTFS_DIR/dev/pts" "$ROOTFS_DIR/proc" "$ROOTFS_DIR/sys" "$ROOTFS_DIR/run"
    mount --bind /dev "$ROOTFS_DIR/dev"
    mount --bind /dev/pts "$ROOTFS_DIR/dev/pts"
    mount -t proc proc "$ROOTFS_DIR/proc"
    mount -t sysfs sys "$ROOTFS_DIR/sys"
    mount --bind /run "$ROOTFS_DIR/run"
}

install_chroot_packages() {
    local package_list
    package_list=$(tr '\n' ' ' < "$PACKAGES_FILE")
    if [ -s "$REQUIREMENTS_FILE" ]; then
        package_list="$package_list python3-pip"
    fi

    log "installing runtime packages in chroot"
    chroot "$ROOTFS_DIR" /usr/bin/env DEBIAN_FRONTEND=noninteractive /bin/bash -lc \
        "apt-get update && apt-get install -y --no-install-recommends $package_list && update-initramfs -u"
}

configure_terminal_user() {
    log "configuring terminal user its"
    chroot "$ROOTFS_DIR" /usr/bin/env DEBIAN_FRONTEND=noninteractive /bin/bash -lc '
        if ! id its >/dev/null 2>&1; then
            useradd -m -s /bin/bash -G sudo its
        fi
        passwd -d its >/dev/null 2>&1 || true
        cat >/etc/hosts <<"EOF"
127.0.0.1 localhost
127.0.1.1 secure-wipe
EOF
        install -d -m 0755 /etc/systemd/system/getty@tty1.service.d
        cat >/etc/systemd/system/getty@tty1.service.d/autologin.conf <<"EOF"
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin its --noclear %I $TERM
EOF
        install -d -m 0750 /etc/sudoers.d
        cat >/etc/sudoers.d/its <<"EOF"
its ALL=(ALL) NOPASSWD:ALL
EOF
        chown -R root:root /etc/sudoers.d
        chmod 0440 /etc/sudoers.d/its
    '
}

copy_payload() {
    log "copying Python app and overlay"
    mkdir -p "$ROOTFS_DIR/opt/live-app"
    cp -a "$APP_DIR/." "$ROOTFS_DIR/opt/live-app/"
    cp -a "$OVERLAY_DIR/." "$ROOTFS_DIR/"
    mkdir -p "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants"
    ln -sf /etc/systemd/system/live-python.service \
        "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/live-python.service"
    if [ -f "$ROOTFS_DIR/lib/systemd/system/systemd-networkd.service" ]; then
        ln -sf /lib/systemd/system/systemd-networkd.service \
            "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/systemd-networkd.service"
    elif [ -f "$ROOTFS_DIR/usr/lib/systemd/system/systemd-networkd.service" ]; then
        ln -sf /usr/lib/systemd/system/systemd-networkd.service \
            "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/systemd-networkd.service"
    fi
    if [ -f "$ROOTFS_DIR/lib/systemd/system/systemd-resolved.service" ]; then
        ln -sf /lib/systemd/system/systemd-resolved.service \
            "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/systemd-resolved.service"
    elif [ -f "$ROOTFS_DIR/usr/lib/systemd/system/systemd-resolved.service" ]; then
        ln -sf /usr/lib/systemd/system/systemd-resolved.service \
            "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/systemd-resolved.service"
    fi
    mkdir -p "$ROOTFS_DIR/etc/systemd/system/network-online.target.wants"
    if [ -f "$ROOTFS_DIR/lib/systemd/system/systemd-networkd-wait-online.service" ]; then
        ln -sf /lib/systemd/system/systemd-networkd-wait-online.service \
            "$ROOTFS_DIR/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service"
    elif [ -f "$ROOTFS_DIR/usr/lib/systemd/system/systemd-networkd-wait-online.service" ]; then
        ln -sf /usr/lib/systemd/system/systemd-networkd-wait-online.service \
            "$ROOTFS_DIR/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service"
    fi
    mkdir -p "$ROOTFS_DIR/etc/systemd/system/sysinit.target.wants"
    if [ -f "$ROOTFS_DIR/lib/systemd/system/systemd-timesyncd.service" ]; then
        ln -sf /lib/systemd/system/systemd-timesyncd.service \
            "$ROOTFS_DIR/etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service"
    elif [ -f "$ROOTFS_DIR/usr/lib/systemd/system/systemd-timesyncd.service" ]; then
        ln -sf /usr/lib/systemd/system/systemd-timesyncd.service \
            "$ROOTFS_DIR/etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service"
    fi
    ln -sf /run/systemd/resolve/stub-resolv.conf "$ROOTFS_DIR/etc/resolv.conf"
    chmod 0755 "$ROOTFS_DIR/usr/local/bin/run-live-app"
    cat >"$ROOTFS_DIR/usr/local/bin/securewipe" <<'EOF'
#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    exec /usr/local/bin/run-live-app "$@"
fi

exec sudo /usr/local/bin/run-live-app "$@"
EOF
    chmod 0755 "$ROOTFS_DIR/usr/local/bin/securewipe"
}

install_python_requirements() {
    if [ ! -s "$REQUIREMENTS_FILE" ]; then
        return
    fi

    log "installing Python requirements"
    chroot "$ROOTFS_DIR" /usr/bin/env PYTHONUNBUFFERED=1 /bin/bash -lc \
        "cd /opt/live-app && python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt"
}

cleanup_chroot() {
    log "cleaning chroot"
    chroot "$ROOTFS_DIR" /bin/bash -lc \
        "apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*"
}

unmount_chroot() {
    cleanup
}

copy_boot_artifacts() {
    local kernel
    local initrd

    kernel=$(find "$ROOTFS_DIR/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort | tail -n1)
    initrd=$(find "$ROOTFS_DIR/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort | tail -n1)

    [ -n "$kernel" ] || fail "no kernel found in $ROOTFS_DIR/boot"
    [ -n "$initrd" ] || fail "no initrd found in $ROOTFS_DIR/boot"

    cp "$GRUB_CFG" "$ISO_ROOT/boot/grub/grub.cfg"
    cp "$kernel" "$ISO_ROOT/live/vmlinuz"
    cp "$initrd" "$ISO_ROOT/live/initrd.img"
}

build_squashfs() {
    log "building squashfs filesystem"
    mksquashfs "$ROOTFS_DIR" "$ISO_ROOT/live/filesystem.squashfs" -e boot
}

build_iso() {
    log "building ISO image"
    rm -f "$OUTPUT_ISO"
    grub-mkrescue -o "$OUTPUT_ISO" "$ISO_ROOT"
}

print_result() {
    log "ISO ready: $OUTPUT_ISO"
}

main() {
    require_files
    require_commands
    require_root
    prepare_dirs
    bootstrap_rootfs
    mount_chroot
    install_chroot_packages
    copy_payload
    configure_terminal_user
    install_python_requirements
    cleanup_chroot
    unmount_chroot
    copy_boot_artifacts
    build_squashfs
    build_iso
    print_result
}

main "$@"
