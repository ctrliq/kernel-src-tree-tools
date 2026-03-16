#!/bin/bash
set -x

UPSTREAM_REF=$1
if [ -z "$UPSTREAM_REF" ]; then
    UPSTREAM_REF="stable_6.12.y"
    echo "UPSTREAM_REF not set, defaulting to $UPSTREAM_REF"
fi

# Validate UPSTREAM_REF format to prevent shell injection
if [[ ! "$UPSTREAM_REF" =~ ^stable_[0-9]+\.[0-9]+\.y$ ]]; then
    echo "Invalid UPSTREAM_REF format: $UPSTREAM_REF"
    echo "Expected format: stable_X.Y.y (e.g., stable_6.12.y)"
    exit 1
fi

# Extract kernel version from UPSTREAM_REF (e.g., stable_6.12.y -> 6.12)
KERNEL_VERSION=$(echo "$UPSTREAM_REF" | sed -E 's/.*_([0-9]+\.[0-9]+)\.y/\1/')
if [ -z "$KERNEL_VERSION" ]; then
    echo "Failed to extract kernel version from UPSTREAM_REF: $UPSTREAM_REF"
    echo "Expected format: stable_X.Y.y (e.g., stable_6.12.y)"
    exit 1
fi
echo "Detected kernel version: $KERNEL_VERSION"

# Define branch names based on kernel version
CIQ_BASE_BRANCH="ciq-${KERNEL_VERSION}.y"
CIQ_NEXT_BRANCH="ciq-${KERNEL_VERSION}.y-next"
CIQ_TMP_BRANCH="{automation_tmp}_ciq-${KERNEL_VERSION}.y-next"

git fetch --all
git show-ref --verify --quiet "refs/remotes/origin/${UPSTREAM_REF}"
if [ $? -ne 0 ]; then
    echo "UPSTREAM_REF $UPSTREAM_REF does not exist, please check status of remote and local branches"
    exit 1
fi

git checkout "${UPSTREAM_REF}"
if [ $? -ne 0 ]; then
    echo "Failed to checkout $UPSTREAM_REF, please check status of remote and local branches"
    exit 1
fi

git show-ref --verify --quiet "refs/heads/${CIQ_NEXT_BRANCH}"
if [ $? -eq 0 ]; then
    echo "$CIQ_NEXT_BRANCH branch already exists, please check status of remote and local branches"
    exit 1
fi

git show-ref --verify --quiet "refs/heads/${CIQ_TMP_BRANCH}"
if [ $? -eq 0 ]; then
    echo "$CIQ_TMP_BRANCH branch already exists, please check status of remote and local branches"
    exit 1
fi

git checkout -b "${CIQ_NEXT_BRANCH}" "${UPSTREAM_REF}"
if [ $? -ne 0 ]; then
    echo "Failed to checkout $CIQ_NEXT_BRANCH, please check status of remote and local branches"
    exit 1
fi
git checkout "${CIQ_BASE_BRANCH}"
if [ $? -ne 0 ]; then
    echo "Failed to checkout $CIQ_BASE_BRANCH, please check status of remote and local branches"
    exit 1
fi
git checkout -b "${CIQ_TMP_BRANCH}"
if [ $? -ne 0 ]; then
    echo "Failed to checkout $CIQ_TMP_BRANCH, please check status of remote and local branches"
    exit 1
fi
git rebase "${CIQ_NEXT_BRANCH}"
if [ $? -ne 0 ]; then
    echo "Failed to rebase $CIQ_TMP_BRANCH, please check status of remote and local branches"
    exit 1
fi

REPO_STATUS=$(git status -s)
if [ ! -z "$REPO_STATUS" ]; then
    echo "Repository is not clean, please check status of remote and local branches"
    exit 1
fi


CIQ_CONFIG_PATH=ciq/configs

CONFIG_LIST=$(ls ${CIQ_CONFIG_PATH}/*.config)

# scripts/dummy-tools doesn't normalize the rustc
# version.  So create a quick dummy rustc script
# to report the same version as our current normalized
# config and pass that to make as RUSTC

# Create a temporary directory for the dummy rustc
TMPDIR=$(mktemp -d)

# Create the dummy rustc that always reports the same version
cat > "$TMPDIR/rustc" << 'EOF'
#!/bin/sh
case "$1" in
    --version|-vV)
        echo "rustc 1.76.0"
        echo "LLVM version: 17.0.6"
        ;;
    *)
        ;;
esac
EOF
chmod +x "$TMPDIR/rustc"

for config in $CONFIG_LIST; do
    echo "Rebasing $config"
    if [[ $config == *"x86_64"* ]]; then
	echo "Rebasing x86_64 config"
	cp $config .config
	make ARCH=x86_64  CROSS_COMPILE=scripts/dummy-tools/ RUSTC=$TMPDIR/rustc olddefconfig
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
	make ARCH=arm64 CROSS_COMPILE=scripts/dummy-tools/ RUSTC="$TMPDIR/rustc" olddefconfig
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

rm -rf $TMPDIR

REPO_STATUS=$(git status -s)
if [ ! -z "$REPO_STATUS" ]; then
    echo "Repository is not clean adding configs"
    git add .
    git commit -m "[CIQ] $(git describe --tags --abbrev=0) - rebased configs"
fi

SPEC_FILE="./ciq/SPECS/kernel.spec"
if [ -f "$SPEC_FILE" ] ; then
    echo "Updating kernel.spec version variables and changelog..."

    # Set default values for DISTLOCALVERSION and DIST if not set
    DISTLOCALVERSION=${DISTLOCALVERSION:-".1.0.0"}
    DIST=${DIST:-".el9_clk"}

    # Get the directory where this script is located
    SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

    # Path to update_lt_spec.py in the same directory as this script
    UPDATE_LT_SPEC="$SCRIPT_DIR/update_lt_spec.py"

    if [ ! -f "$UPDATE_LT_SPEC" ]; then
        echo "ERROR: update_lt_spec.py not found at $UPDATE_LT_SPEC"
        exit 1
    fi

    # Call update_lt_spec.py to update the spec file
    python "$UPDATE_LT_SPEC" \
        --srcgit . \
        --spec-file "$SPEC_FILE" \
        --distlocalversion "$DISTLOCALVERSION" \
        --dist "$DIST" \
        --commit

    if [ $? -ne 0 ]; then
        echo "ERROR: update_lt_spec.py failed"
        exit 1
    fi

    echo "Spec file updated successfully"
fi
