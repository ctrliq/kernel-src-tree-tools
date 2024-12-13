#!/bin/bash
#set -x

pwd

BRANCH=$(git branch | grep \* | cut -d ' ' -f2)

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
	cp -v configs/kernel-${ARCH}-rhel.config .config
    else
	echo "Error: Config file not found"
	exit 1
    fi
else
    echo "Error: Unsupported architecture"
    exit 1
fi

echo "Setting Local Version for build"
sed -i_bak "s/CONFIG_LOCALVERSION=\"\"/CONFIG_LOCALVERSION=\"-${BRANCH}\"/g" .config
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

echo "Checking kABI"
# ../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_x86_64 -s Module.symvers || echo "kABI failed"
KABI_CHECK=$(../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_${ARCH} -s Module.symvers)
if [ $? -ne 0 ]; then
    echo "Error: kABI check failed"
    exit 1
fi
echo "kABI check passed"

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

