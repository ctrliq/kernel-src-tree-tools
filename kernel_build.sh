#!/bin/bash
set -e

NO_REBOOT=0
SKIP_MRPROPER=0
SKIP_KABI=0

print_help() {
cat <<EOF
Usage: $0 [OPTIONS]

Options:
  -n, --no-reboot       Don't reboot after kernel install
  -m, --skip-mrproper   Skip 'make mrproper'
  -k, --skip-kabi       Skip kABI check
  -h, --help            Show this help message
EOF
}

# Parse arguments
while [ "$#" -gt 0 ]; do
    case "$1" in
        -n|--no-reboot) NO_REBOOT=1 ;;
        -m|--skip-mrproper) SKIP_MRPROPER=1 ;;
        -k|--skip-kabi) SKIP_KABI=1 ;;
        -h|--help) print_help; exit 0 ;;
        --) shift; break ;;
        -*)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
        *) break ;;
    esac
    shift
done

pwd

BRANCH=$(git branch | grep \* | cut -d ' ' -f2 | sed 's/[{}()]//g; s/\//_/g')

START=$(date +%s)
START_MRPROPER=$(date +%s)

if [ "$SKIP_MRPROPER" -ne 1 ]; then
    echo "Running make mrproper..."
    make mrproper | tee "/tmp/${BRANCH}_make_mrproper.log"
    if [[ $? -ne 0 ]]; then
        echo "Error: make mrproper failed"
        echo "[TIMER]{MRPROPER} $(( $(date +%s) - $START_MRPROPER ))s"
        exit 1
    fi
else
    echo "Skipping make mrproper"
fi

END_MRPROPER=$(date +%s)
echo "[TIMER]{MRPROPER}: $(( $END_MRPROPER - $START_MRPROPER ))s"

ARCH=$(uname -m)
if [ "x86_64" == "${ARCH}" ] || [ "aarch64" == "${ARCH}" ]; then
    VERSION=$(uname -r | cut -d '-' -f1)
    echo "${ARCH} architecture detected, copying config"
    if [ -f ciq/configs/kernel-${ARCH}.config ]; then
	cp -v ciq/configs/kernel-${ARCH}.config .config
    elif [ -f configs/kernel-${ARCH}.config ]; then
	cp -v configs/kernel-${ARCH}.config .config
    elif [ -f configs/kernel-${ARCH}-rhel.config ]; then
	cp -v configs/kernel-${ARCH}-rhel.config .config
    elif [ -f configs/kernel-${VERSION}-${ARCH}.config ]; then
	cp -v configs/kernel-${VERSION}-${ARCH}.config .config
    else
	echo "Error: Config file not found"
	exit 1
    fi
else
    echo "Error: Unsupported architecture"
    exit 1
fi

echo "Setting Local Version for build"
LOCALVERSION="-${BRANCH}-$(git rev-parse --short HEAD)"
# Shrink the LOCALVERSION to fit in the config
# Remove to a max of 54 characters (max is 64 but we want a buffer)
if [ ${#LOCALVERSION} -gt 54 ]; then
    LOCALVERSION=$(echo "${LOCALVERSION}" | cut -c1-54)
fi

sed -i_bak "s/CONFIG_LOCALVERSION=\"\"/CONFIG_LOCALVERSION=\"${LOCALVERSION}\"/g" .config
grep "CONFIG_LOCALVERSION=" .config

echo "Making olddefconfig"
make olddefconfig

START_BUILD=$(date +%s)
echo "Starting Build"
make -j$(nproc)
if [ $? -ne 0 ]; then
    echo "Error: Build failed"
    echo "[TIMER]{BUILD} $(( $(date +%s) - $START_BUILD ))s"
    exit 1
fi
END_BUILD=$(date +%s)
echo "[TIMER]{BUILD}: $(( $END_BUILD - $START_BUILD ))s"

echo "Making Modules"
START_MODULES=$(date +%s)
sudo INSTALL_MOD_STRIP=1 make -j$(nproc) modules_install
if [ $? -ne 0 ]; then
    echo "Error: Modules install failed"
    echo "[TIMER]{MODULES} $(( $(date +%s) - $START_MODULES ))s"
    exit 1
fi
END_MODULES=$(date +%s)
echo "[TIMER]{MODULES}: $(( $END_MODULES - $START_MODULES ))s"

echo "Making Install"
START_INSTALL=$(date +%s)
sudo make install
if [ $? -ne 0 ]; then
    echo "Error: Install failed"
    echo "[TIMER]{INSTALL} $(( $(date +%s) - $START_INSTALL ))s"
    exit 1
fi
END_INSTALL=$(date +%s)
echo "[TIMER]{INSTALL}: $(( $END_INSTALL - $START_INSTALL ))s"

# Run kABI check unless skipped
if [ "$SKIP_KABI" -eq 1 ]; then
    echo "Skipping kABI check"
else
    echo "Checking kABI"
    ../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_${ARCH} -s Module.symvers
    if [ $? -ne 0 ]; then
        echo "Error: kABI check failed"
        exit 1
    fi
    echo "kABI check passed"
fi

GRUB_INFO=$(sudo grubby --info=ALL | grep -E "^kernel|^index")

AWK_RES=$(awk -F '=' -v INDEX=0 -v KERNEL="" -v FINAL_INDEX=0 -v VERSION="${LOCALVERSION}" \
    '{if ($2 ~/^[0-9]+$/) {INDEX=$2}} {if ($2 ~VERSION) {KERNEL=$2; FINAL_INDEX=INDEX}} END {print FINAL_INDEX"  "KERNEL}' \
    <<< "${GRUB_INFO}")
if [ $? -ne 0 ]; then
    echo "Error: awk failed"
    exit 1
fi
read -r INDEX KERNEL <<< "${AWK_RES}"

KERNEL=$(echo ${KERNEL} | sed 's/\"//g')

echo "Setting Default Kernel to ${KERNEL} and Index to ${INDEX}"
sudo grubby --set-default-index=${INDEX}
if [ $? -ne 0 ]; then
    echo "Error: grubby failed"
    exit 1
fi
sudo grubby --set-default=${KERNEL}
if [ $? -ne 0 ]; then
    echo "Error: grubby failed"
    exit 1
fi
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
if [ $? -ne 0 ]; then
    echo "Error: grub2-mkconfig failed"
    exit 1
fi

echo "Hopefully Grub2.0 took everything ... rebooting after time metrices"


END=$(date +%s)
DIFF=$(( $END - $START ))
echo "[TIMER]{MRPROPER}: $(( $END_MRPROPER - $START_MRPROPER ))s"
echo "[TIMER]{BUILD}: $(( $END_BUILD - $START_BUILD ))s"
echo "[TIMER]{MODULES}: $(( $END_MODULES - $START_MODULES ))s"
echo "[TIMER]{INSTALL}: $(( $END_INSTALL - $START_INSTALL ))s"
echo "[TIMER]{TOTAL} ${DIFF}s"

if [ "$NO_REBOOT" -ne 1 ]; then
    echo "Rebooting in 10 seconds"
    sleep 10
    sudo reboot
fi

