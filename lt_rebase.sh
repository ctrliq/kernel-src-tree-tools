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

# Target branch: use explicit second argument, or derive from upstream ref
if [ -n "$2" ]; then
    CIQ_BASE_BRANCH="$2"
    echo "Using explicit target branch: $CIQ_BASE_BRANCH"
else
    CIQ_BASE_BRANCH="ciq-${KERNEL_VERSION}.y"
    echo "Derived target branch: $CIQ_BASE_BRANCH"
fi
CIQ_NEXT_BRANCH="${CIQ_BASE_BRANCH}-next"
CIQ_TMP_BRANCH="{automation_tmp}_${CIQ_BASE_BRANCH}-next"

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

# Spec file discovery: versioned -> clkstable -> generic
VERSIONED_SPEC_FILE="./ciq/SPECS/kernel-clk${KERNEL_VERSION}.spec"
STABLE_SPEC_FILE="./ciq/SPECS/kernel-clkstable.spec"
GENERIC_SPEC_FILE="./ciq/SPECS/kernel.spec"

if [ -f "$VERSIONED_SPEC_FILE" ]; then
    SPEC_FILE="$VERSIONED_SPEC_FILE"
    echo "Found versioned spec file: $SPEC_FILE"
elif [ -f "$STABLE_SPEC_FILE" ]; then
    SPEC_FILE="$STABLE_SPEC_FILE"
    echo "Found stable spec file: $SPEC_FILE"
elif [ -f "$GENERIC_SPEC_FILE" ]; then
    SPEC_FILE="$GENERIC_SPEC_FILE"
    echo "Found spec file: $SPEC_FILE"
else
    SPEC_FILE=""
fi

if [ -n "$SPEC_FILE" ]; then
    echo "Updating spec file version variables and changelog..."

    # Set default value for BUILDID if not set
    BUILDID=${BUILDID:-".1"}

    # Get the directory where this script is located
    SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

    # Path to update_lt_spec.py in the same directory as this script
    UPDATE_LT_SPEC="$SCRIPT_DIR/update_lt_spec.py"

    if [ ! -f "$UPDATE_LT_SPEC" ]; then
        echo "ERROR: update_lt_spec.py not found at $UPDATE_LT_SPEC"
        exit 1
    fi

    # Call update_lt_spec.py to update the spec file
    "$UPDATE_LT_SPEC" \
        --srcgit . \
        --spec-file "$SPEC_FILE" \
        --buildid "$BUILDID" \
        --commit

    if [ $? -ne 0 ]; then
        echo "ERROR: update_lt_spec.py failed"
        exit 1
    fi

    echo "Spec file updated successfully"
fi
