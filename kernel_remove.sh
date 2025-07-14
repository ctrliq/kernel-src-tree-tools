#!/usr/bin/env bash
set -xeuf -o pipefail

requested_kernel_to_remove="${1:-}"
rpm_kernels=( $(rpm -q kernel-core --qf "%{VERSION}-%{RELEASE}\n" 2>/dev/null | tr '\n' ' ') )
current_kernel="$(uname -r)"

if [ -z "${requested_kernel_to_remove}" ]; then
    echo 'Specify the kernel version'
    echo 'Look under /lib/modules/ for "correct" versions'
    exit 1
fi

for rpm_kernel in "${rpm_kernels[@]}"; do
    if [ "${requested_kernel_to_remove}" == "${rpm_kernel}" ] || [ "${requested_kernel_to_remove}" == "${rpm_kernel}.$(uname -m)" ]; then
        echo 'ERROR: Will not remove a kernel installed as an RPM package'
        exit 1
    fi
done

if [ "${requested_kernel_to_remove}" == "${current_kernel}" ]; then
    echo 'ERROR: Will not remove the current kernel'
    exit 1
else
    # The checks exist to prevent "no such [file|directory] found" "errors" on console
    # Also helps with error management
    [ -d "/lib/modules/${requested_kernel_to_remove}" ] && sudo rm -fr "/lib/modules/${requested_kernel_to_remove}"
    [ -d "/boot/dtb-${requested_kernel_to_remove}" ] && sudo rm -fr "/boot/dtb-${requested_kernel_to_remove}"
    [ -f "/boot/config-${requested_kernel_to_remove}" ] && sudo rm -f "/boot/config-${requested_kernel_to_remove}"
    [ -f "/boot/initramfs-${requested_kernel_to_remove}.img" ] && sudo rm -f "/boot/initramfs-${requested_kernel_to_remove}.img"
    [ -f "/boot/symvers-${requested_kernel_to_remove}.xz" ] && sudo rm -f "/boot/symvers-${requested_kernel_to_remove}.xz"
    [ -f "/boot/symvers-${requested_kernel_to_remove}.gz" ] && sudo rm -f "/boot/symvers-${requested_kernel_to_remove}.gz"
    [ -f "/boot/System.map-${requested_kernel_to_remove}" ] && sudo rm -f "/boot/System.map-${requested_kernel_to_remove}"
    [ -f "/boot/vmlinuz-${requested_kernel_to_remove}" ] && sudo rm -f "/boot/vmlinuz-${requested_kernel_to_remove}"
    # If $requested_kernel_to_remove is current default kernel, grubby will make the next-in-line kernel default
    sudo grubby --remove-kernel="/boot/vmlinuz-${requested_kernel_to_remove}"
fi
