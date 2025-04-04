#!/bin/bash
set -x

UPSTREAM_REF=$1
if [ -z "$UPSTREAM_REF" ]; then
    UPSTREAM_REF="stable_6.12.y"
    echo "UPSTREAM_REF not set, defaulting to $UPSTREAM_REF"
fi

git fetch --all
RES=$(git branch --all | grep ciq-6.12.y-next | wc -l)
if [ $RES -ne 0 ]; then 
    echo "cit-6.12.y-next branch already exists, please check status of remote and local branches"
    exit 1
fi

git checkout -b ciq-6.12.y-next $UPSTREAM_REF
git checkout ciq-6.12.y
git checkout -b {automation_tmp}_ciq-6.12.y-next
git rebase ciq-6.12.y-next

REPO_STATUS=$(git status -s)
if [ ! -z "$REPO_STATUS" ]; then
    echo "Repository is not clean, please check status of remote and local branches"
    exit 1
fi


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

REPO_STATUS=$(git status -s)
if [ ! -z "$REPO_STATUS" ]; then
    echo "Repository is not clean adding configs"
    git add .
    git commit -m "[CIQ] $(git describe --tags --abbrev=0) - rebased configs"
fi


