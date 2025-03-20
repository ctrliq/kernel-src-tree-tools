#!/bin/bash
#set -x

pwd

REAL_BRANCH="$(git branch --show-current)"
# Enforce branch naming so that we can determine
# 1. If a kABI check is even necessary
# 2. Which git tag to checkout in the kernel-dist-git
# Can do with an if but I always get it wrong
if ! echo "$REAL_BRANCH" | grep -q -E '((ciqlts[0-9]+_[0-9]+(-rt)?|ciqcbr7_9)$|fips-([0-9]+|legacy-[0-9]+)(-compliant|-certified)?/)'; then
    echo "Unexpected branch name."
    echo "Either of the following must be present (part of) in the branch name, enforced for kABI check."
    echo "- 'ciqcbr7_9'"
    echo "- 'ciqltsX_Y'"
    echo "- 'ciqltsX_Y-rt'"
    echo "- 'fips-legacy-X-compliant/'"
    echo "- 'fips-legacy-X/'"
    echo "- 'fips-X/'"
    echo "- 'fips-X-compliant/'"
    echo "- 'fips-X-certified/'"
    exit 1
fi
BRANCH=$(echo "$REAL_BRANCH" | sed -r 's/[{}/]/_/g')

START=$(date +%s)
START_MRPROPER=$(date +%s)
if [ -e .config ]; then
    make mrproper | tee "/tmp/${BRANCH}_make_mrproper.log"
    if [ $? -ne 0 ]; then
        echo "Error: make mrproper failed"
        echo "[TIMER]{MRPROPER} $(( $(date +%s) - $START_MRPROPER ))s"
        exit 1
    fi
else
    echo "no .config file found, moving on"
fi

END_MRPROPER=$(date +%s)
echo "[TIMER]{MRPROPER}: $(( $END_MRPROPER - $START_MRPROPER ))s"


ARCH=$(uname -m)
if [ "x86_64" == "${ARCH}" ] || [ "aarch64" == "${ARCH}" ]; then
    VERSION=$(uname -r | cut -d '-' -f1)
    echo "x86_64 architecture detected, copying config"
    if [ -f configs/kernel-${VERSION}-${ARCH}.config ]; then
	cp -v configs/kernel-${VERSION}-${ARCH}.config .config
    elif [ -f configs/kernel-${ARCH}-rhel.config ]; then
	# Rocky 9 SIG CLOUD
	cp -v configs/kernel-${ARCH}-rhel.config .config
    elif [ -f configs/kernel-${ARCH}.config ]; then
	# Rocky 8 SIG CLOUD
	cp -v configs/kernel-${ARCH}.config .config
    elif [ -f configs/kernel-rt-${VERSION}-${ARCH}.config ]; then
        cp -v configs/kernel-rt-${VERSION}-${ARCH}.config .config
	# Some sort of RT build?
    else
	echo "Error: Config file not found"
	exit 1
    fi
else
    echo "Error: Unsupported architecture"
    exit 1
fi

echo "Setting Local Version for build"
sed -i_bak "s/CONFIG_LOCALVERSION=\"\"/CONFIG_LOCALVERSION=\"-${BRANCH}-$(git rev-parse --short HEAD)\"/g" .config
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
sudo INSTALL_MOD_STRIP=1 make modules_install
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

CHECK_KABI=true
# We disable kABI checks only on RT kernels up-to 9.4
if echo "$REAL_BRANCH" | grep -q 'ciqlts8_6-rt'; then
    CHECK_KABI=false

elif echo "$REAL_BRANCH" | grep -q 'ciqlts8_8-rt'; then
    CHECK_KABI=false

elif echo "$REAL_BRANCH" | grep -q 'ciqlts9_2-rt'; then
    CHECK_KABI=false
fi

if [ $CHECK_KABI == 'true' ]; then
    echo "Checking kABI"
    KABI_CHECK=$(../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_${ARCH} -s Module.symvers)
    if [ $? -ne 0 ]; then
        echo -e "Error: kABI check failed for following symbols:\n$KABI_CHECK"
        exit 1
    else
        echo "kABI check passed"
    fi
fi

GRUB_INFO=$(sudo grubby --info=ALL | grep -E "^kernel|^index")

AWK_RES=$(awk -F '=' -v INDEX=0 -v KERNEL="" -v FINAL_INDEX=0 -v BRANCH="${BRANCH}" \
    '{if ($2 ~/^[0-9]+$/) {INDEX=$2}} {if ($2 ~BRANCH) {KERNEL=$2; FINAL_INDEX=INDEX}} END {print FINAL_INDEX"  "KERNEL}' \
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

echo "Rebooting in 10 seconds"
sleep 10
sudo reboot

