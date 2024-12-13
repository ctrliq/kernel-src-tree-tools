#!/bin/bash
#set -x

pwd

BRANCH=$(git branch | grep \* | cut -d ' ' -f2)

START=$(date +%s)
START_MRPROPER=$(date +%s)

END_MRPROPER=$(date +%s)
echo "[TIMER]{MRPROPER}: $(( $END_MRPROPER - $START_MRPROPER ))s"


ARCH=$(uname -m)
if [ "x86_64" == "${ARCH}" ] || [ "aarch64" == "${ARCH}" ]; then
    VERSION=$(uname -r | cut -d '-' -f1)
    echo "x86_64 architecture detected, copying config"
    cp -v configs/kernel-${VERSION}-${ARCH}.config .config
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

echo "Checking kABI"
# ../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_x86_64 -s Module.symvers || echo "kABI failed"
KABI_CHECK=$(../kernel-dist-git/SOURCES/check-kabi -k ../kernel-dist-git/SOURCES/Module.kabi_${ARCH} -s Module.symvers)
if [ $? -ne 0 ]; then
    echo "Error: kABI check failed"
    exit 1
fi
echo "kABI check passed"

echo "Making Modules"
START_MODULES=$(date +%s)
#sudo INSTALL_MOD_STRIP=1 make modules
if [ $? -ne 0 ]; then
    echo "Error: Modules install failed"
    echo "[TIMER]{MODULES} $(( $(date +%s) - $START_MODULES ))s"
    exit 1
fi
END_MODULES=$(date +%s)
echo "[TIMER]{MODULES}: $(( $END_MODULES - $START_MODULES ))s"

echo "Making Install"
START_INSTALL=$(date +%s)
END_INSTALL=$(date +%s)
echo "[TIMER]{INSTALL}: $(( $END_INSTALL - $START_INSTALL ))s"




END=$(date +%s)
DIFF=$(( $END - $START ))
echo "[TIMER]{BUILD}: $(( $END_BUILD - $START_BUILD ))s"
echo "[TIMER]{MODULES}: $(( $END_MODULES - $START_MODULES ))s"
echo "[TIMER]{TOTAL} ${DIFF}s"


