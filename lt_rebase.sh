#!/bin/bash
set -x

CIQ_CONFIG_PATH=ciq/configs

CONFIG_LIST=$(ls ${CIQ_CONFIG_PATH}/*.config)

for config in $CONFIG_LIST; do
    echo "Rebasing $config"
    if [[ $config == *"x86_64"* ]]; then
	echo "Rebasing x86_64 config"
	cp $config .config
	make ARCH=x86_64  CROSS_COMPILE=scripts/dummy-tools/ olddefconfig
	CONFIG_DIFF=$(diff --ignore-matching-lines='^# Linux/x86_64' .config $config | wc -l)
	if [ $CONFIG_DIFF -eq 0 ]; then
	    echo "No changes to x86_64 config"
	else
	    echo "Changes to x86_64 config"
	    diff --ignore-matching-lines='^# Linux/x86_64' .config $config
	    cp .config $config
	fi
    elif [[ $config == *"aarch64"* ]]; then
	echo "Rebaseing aarch64 config"
	cp $config .config
	make ARCH=arm64 CROSS_COMPILE=scripts/dummy-tools/ olddefconfig
	CONFIG_DIFF=$(diff --ignore-matching-lines='^# Linux/arm64' .config $config | wc -l)
	if [ $CONFIG_DIFF -eq 0 ]; then
	    echo "No changes to aarch64 config"
	else
	    echo "Changes to aarch64 config"
	    diff --ignore-matching-lines='^# Linux/aarch64' .config $config
	    cp .config $config
	fi
    else
	echo "Config ${config} not of supported type"
	exit 1
    fi
done
