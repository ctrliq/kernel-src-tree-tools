#!/bin/bash
#
# Rolling Release Rebase Orchestrator
#
# This script orchestrates the full rolling release rebase process for any
# Rocky Linux version (8, 9, 10, etc.):
# 1. Update repositories
# 2. Detect the latest rolling branch
# 3. Run rolling-release-update.py to create new branch
# 4. Build kernel in VM
# 5. Run kselftests in VM
# 6. Push branches and create PR
#
# Usage:
#   ./rlc_rebase_orchestrator.sh [options]
#
# Options:
#   -P, --product        Rolling product (e.g., rlc-10, rlc-9, rlc-8)
#                        Default: auto-detect from repository
#   -b, --base-branch    Base branch to rebase onto (e.g., rocky10_1, rocky9_5)
#                        Default: auto-detect latest rockyX_Y branch
#   -o, --old-branch     Old rolling branch (default: auto-detect latest)
#   -j, --jira           JIRA ticket ID for the PR (e.g., KERNEL-485)
#   -k, --kvm            KVM/VM name for build testing (default: auto from product)
#   -n, --no-vm          Skip VM build and test
#   -p, --no-push        Skip pushing branches to origin
#   -r, --no-pr          Skip creating PR
#   --dry-run            Show what would be done without executing
#   --resume             Resume from saved state
#   -i, --interactive    Interactive mode - pause on merge conflicts for user resolution
#   --new-minor-version  New minor version release (e.g., el9_7 -> el9_8)
#   --fips-override      Override FIPS check abort in rolling-release-update.py
#   --build-only         Only run VM build phase (skip rebase, test, push, PR)
#   --test-only          Only run kselftest phase (skip rebase, build, push, PR)
#   --pr-only            Only create PR (skip rebase, build, test)
#   -h, --help           Show this help message
#
# Examples:
#   # Auto-detect everything for the repo
#   ./rlc_rebase_orchestrator.sh
#
#   # Specify Rocky 10 rolling release
#   ./rlc_rebase_orchestrator.sh -P rlc-10 -b rocky10_1
#
#   # Specify Rocky 9 sig-cloud
#   ./rlc_rebase_orchestrator.sh -P sig-cloud-9 -b rocky9_5
#
#   # Full manual specification
#   ./rlc_rebase_orchestrator.sh -P rlc-10 -b rocky10_1 -o rlc-10/6.12.0-124.27.1.el10_1
#
#   # New minor version release (e.g., el9_7 -> el9_8)
#   ./rlc_rebase_orchestrator.sh -P rlc-9 -b rocky9_8 -o rlc-9/5.14.0-611.34.1.el9_7 --new-minor-version

set -e  # Exit on any error
set -o pipefail  # Catch errors in pipes

# Script directory (this script lives in kernel-src-tree-tools/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
ROLLING_REPO="${PARENT_DIR}/kernel-src-tree-rolling"
TOOLS_REPO="${SCRIPT_DIR}"  # We're already in kernel-src-tree-tools
BUILD_DIR="${PARENT_DIR}/kernel-src-tree-build"
LOG_DIR="${PARENT_DIR}"  # Store logs in parent directory with other logs

# Timestamp for log files
LOG_TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Default values
ROLLING_PRODUCT=""
BASE_BRANCH=""
OLD_BRANCH=""
JIRA_TICKET=""
KVM_NAME=""
SKIP_VM=false
SKIP_PUSH=false
SKIP_PR=false
DRY_RUN=false
RESUME_MODE=false
BUILD_ONLY=false
TEST_ONLY=false
PR_ONLY=false
FIPS_OVERRIDE=false
NEW_MINOR_VERSION=false
INTERACTIVE=false
STARTTIME=$(date +%s)

# Log file variables (initialized later after ROLLING_PRODUCT is determined)
RR_LOGFILE=""
ORCH_LOGFILE=""
LOGFILE=""

# State management
STATE_DIR="${PARENT_DIR}/.rlc_rebase_state"
STATE_FILE="${STATE_DIR}/current.state"
CURRENT_STAGE="init"

# Rocky version configurations
# Format: ROCKY_CONFIG_<version>_<property>
# Supported properties: rolling_prefix, base_pattern, vm_name
# These variables are used via indirect expansion: ${!varname}
# shellcheck disable=SC2034
ROCKY_CONFIG_10_rolling_prefix="rlc-10"
# shellcheck disable=SC2034
ROCKY_CONFIG_10_base_pattern="rocky10_"
# shellcheck disable=SC2034
ROCKY_CONFIG_10_vm_name="rocky10"

# shellcheck disable=SC2034
ROCKY_CONFIG_9_rolling_prefix="rlc-9"
# shellcheck disable=SC2034
ROCKY_CONFIG_9_base_pattern="rocky9_"
# shellcheck disable=SC2034
ROCKY_CONFIG_9_vm_name="rocky9"

# shellcheck disable=SC2034
ROCKY_CONFIG_8_rolling_prefix="rlc-8"
# shellcheck disable=SC2034
ROCKY_CONFIG_8_base_pattern="rocky8_"
# shellcheck disable=SC2034
ROCKY_CONFIG_8_vm_name="rocky8"

# Priority order for version detection (newest first)
ROCKY_VERSIONS="10 9 8"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# State management functions
save_state() {
    local stage="$1"
    mkdir -p "$STATE_DIR"
    cat > "$STATE_FILE" << EOF
STAGE=$stage
ROLLING_PRODUCT=$ROLLING_PRODUCT
BASE_BRANCH=$BASE_BRANCH
OLD_BRANCH=$OLD_BRANCH
NEW_ROLLING_BRANCH=${NEW_ROLLING_BRANCH:-}
NEW_PR_BRANCH=${NEW_PR_BRANCH:-}
JIRA_TICKET=${JIRA_TICKET:-}
KVM_NAME=$KVM_NAME
NEW_MINOR_VERSION=$NEW_MINOR_VERSION
RR_LOGFILE=${RR_LOGFILE:-}
ORCH_LOGFILE=${ORCH_LOGFILE:-}
TIMESTAMP=$(date +%s)
EOF
    CURRENT_STAGE="$stage"
}

load_state() {
    if [ -f "$STATE_FILE" ]; then
        # shellcheck source=/dev/null
        source "$STATE_FILE"
        CURRENT_STAGE="${STAGE:-init}"
        log_info "Loaded state from previous run (stage: $CURRENT_STAGE)"
        return 0
    fi
    return 1
}

# shellcheck disable=SC2317  # Called indirectly via cleanup_on_exit trap
clear_state() {
    rm -f "$STATE_FILE"
    CURRENT_STAGE="init"
}

# Trap handler for cleanup on exit
# shellcheck disable=SC2317  # Functions are called indirectly via trap
cleanup_on_exit() {
    local exit_code=$?
    if [ "$exit_code" -ne 0 ] && [ "$DRY_RUN" = false ]; then
        log_warn "Script failed with exit code $exit_code at stage: $CURRENT_STAGE"
        log_info "State saved. Resume with: $0 --resume"
        save_state "$CURRENT_STAGE"
    elif [ "$exit_code" -eq 0 ]; then
        # Clear state on success
        clear_state
    fi
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Repository URLs for auto-cloning
ROLLING_REPO_URL="git@github.com:ctrliq/kernel-src-tree.git"

# Clone a repository if it doesn't exist
clone_repo_if_missing() {
    local repo_path="$1"
    local repo_url="$2"
    local repo_name="$3"

    if [ ! -d "$repo_path" ]; then
        log_info "$repo_name not found at $repo_path. Cloning..."
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would clone: git clone $repo_url $repo_path"
            return 0
        fi
        if git clone "$repo_url" "$repo_path"; then
            log_success "Cloned $repo_name successfully"
        else
            log_error "Failed to clone $repo_name from $repo_url"
            return 1
        fi
    fi
    return 0
}

# VM lifecycle management
ensure_vm_running() {
    local vm_name="$1"
    local vm_state

    if ! command -v virsh &> /dev/null; then
        log_warn "virsh not found, cannot manage VM"
        return 1
    fi

    vm_state=$(virsh domstate "$vm_name" 2>/dev/null || echo "not found")

    case "$vm_state" in
        "running")
            log_info "VM $vm_name is already running"
            return 0
            ;;
        "shut off")
            log_info "Starting VM $vm_name..."
            if [ "$DRY_RUN" = true ]; then
                log_info "[DRY RUN] Would start: virsh start $vm_name"
                return 0
            fi
            virsh start "$vm_name"
            wait_for_vm_ssh "$vm_name"
            return $?
            ;;
        "not found")
            log_warn "VM $vm_name not found. Please create it manually or use qcows/new_ciq_builder.sh"
            return 1
            ;;
        *)
            log_warn "VM $vm_name is in state: $vm_state"
            return 1
            ;;
    esac
}

wait_for_vm_ssh() {
    local vm_name="$1"
    local max_wait=60
    local attempt=0

    log_info "Waiting for VM $vm_name to become accessible via SSH..."

    while [ $attempt -lt $max_wait ]; do
        VMIP=$(virsh domifaddr "$vm_name" 2>/dev/null | grep ipv4 | awk '{print $4}' | cut -d'/' -f1)
        if [ -n "$VMIP" ]; then
            if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "$VMIP" "echo" &>/dev/null; then
                log_success "VM is ready at $VMIP"
                return 0
            fi
        fi
        ((++attempt))
        if [ $((attempt % 6)) -eq 0 ]; then
            log_info "Still waiting for VM (attempt $attempt/$max_wait)..."
        fi
        sleep 10
    done
    log_error "VM failed to become ready after $((max_wait * 10)) seconds"
    return 1
}

show_help() {
    head -55 "$0" | grep -E "^#" | sed 's/^# \?//'
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -P|--product)
            ROLLING_PRODUCT="$2"
            shift 2
            ;;
        -b|--base-branch)
            BASE_BRANCH="$2"
            shift 2
            ;;
        -o|--old-branch)
            OLD_BRANCH="$2"
            shift 2
            ;;
        -j|--jira)
            JIRA_TICKET="$2"
            shift 2
            ;;
        -k|--kvm)
            KVM_NAME="$2"
            shift 2
            ;;
        -n|--no-vm)
            SKIP_VM=true
            shift
            ;;
        -p|--no-push)
            SKIP_PUSH=true
            shift
            ;;
        -r|--no-pr)
            SKIP_PR=true
            shift
            ;;
        -i|--interactive)
            INTERACTIVE=true
            shift
            ;;
        --new-minor-version)
            NEW_MINOR_VERSION=true
            shift
            ;;
        --fips-override)
            FIPS_OVERRIDE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --resume)
            RESUME_MODE=true
            shift
            ;;
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        --pr-only)
            PR_ONLY=true
            SKIP_VM=true  # No VM needed for PR-only mode
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            ;;
    esac
done

# Handle resume mode
if [ "$RESUME_MODE" = true ]; then
    if load_state; then
        log_info "Resuming from stage: $CURRENT_STAGE"
        # Variables were loaded from state file
    else
        log_error "No saved state found to resume from"
        exit 1
    fi
fi

# Handle phase-only modes
if [ "$BUILD_ONLY" = true ]; then
    log_info "BUILD-ONLY mode: skipping rebase, tests, push, and PR"
    SKIP_PUSH=true
    SKIP_PR=true
fi

if [ "$TEST_ONLY" = true ]; then
    log_info "TEST-ONLY mode: skipping rebase, build, push, and PR"
    SKIP_PUSH=true
    SKIP_PR=true
fi

if [ "$PR_ONLY" = true ]; then
    log_info "PR-ONLY mode: skipping rebase, build, and tests"
    # SKIP_VM already set in argument parsing
fi

# Verify prerequisites
log_info "Verifying prerequisites..."

# Auto-clone kernel-src-tree-rolling if missing
clone_repo_if_missing "$ROLLING_REPO" "$ROLLING_REPO_URL" "kernel-src-tree-rolling" || exit 1

if [ ! -d "$TOOLS_REPO" ]; then
    log_error "kernel-src-tree-tools not found at $TOOLS_REPO"
    exit 1
fi

# Check for required Python modules
if ! python3 -c "import git" 2>/dev/null; then
    log_error "Python GitPython module not found. Install with: pip install GitPython"
    exit 1
fi

# Update repositories (fetch is read-only, always do it for accurate detection)
log_info "Updating kernel-src-tree-tools..."
pushd "$TOOLS_REPO" > /dev/null
git fetch origin
if [ "$DRY_RUN" = false ]; then
    git pull --rebase origin "$(git rev-parse --abrev-ref HEAD)" 2>/dev/null || log_warn "Could not pull latest changes for kernel-src-tree-tools (not critical)"
fi
popd > /dev/null

log_info "Updating kernel-src-tree-rolling..."
pushd "$ROLLING_REPO" > /dev/null
git fetch origin --tags
popd > /dev/null

# Auto-detect rolling product if not specified
if [ -z "$ROLLING_PRODUCT" ]; then
    pushd "$ROLLING_REPO" > /dev/null

    # Look for rolling product branches using version priority order
    # Check for rlc-X branches in order: 10, 9, 8
    for ver in $ROCKY_VERSIONS; do
        prefix_var="ROCKY_CONFIG_${ver}_rolling_prefix"
        prefix="${!prefix_var}"
        if git branch -a | grep -qE "${prefix}/" 2>/dev/null; then
            ROLLING_PRODUCT="$prefix"
            break
        fi
    done

    # If no rlc-X found, show available branches
    if [ -z "$ROLLING_PRODUCT" ]; then
        log_error "Could not auto-detect rolling product."
        log_info "Available remote branches:"
        git branch -a | grep -E "remotes/origin/(rlc-|sig-cloud-)" | head -20 || echo "  (none found)"
        log_info "Specify a product with -P (e.g., -P rlc-10, -P rlc-9, -P rlc-8)"
        popd > /dev/null
        exit 1
    fi

    popd > /dev/null
    log_info "Auto-detected rolling product: $ROLLING_PRODUCT"
fi

# Extract major version from rolling product (e.g., rlc-10 -> 10)
MAJOR_VERSION=$(echo "$ROLLING_PRODUCT" | grep -oE "[0-9]+$")
if [ -z "$MAJOR_VERSION" ]; then
    log_error "Could not extract major version from rolling product: $ROLLING_PRODUCT"
    log_info "Expected format: rlc-<version> (e.g., rlc-10, rlc-9, rlc-8)"
    exit 1
fi

# Validate version is supported
vm_name_var="ROCKY_CONFIG_${MAJOR_VERSION}_vm_name"
if [ -z "${!vm_name_var}" ]; then
    log_error "Unsupported Rocky version: $MAJOR_VERSION"
    log_info "Supported versions: 8, 9, 10"
    exit 1
fi

# Auto-detect KVM name if not specified (use version-specific default)
if [ -z "$KVM_NAME" ]; then
    KVM_NAME="${!vm_name_var}"
    log_info "Auto-detected KVM name: $KVM_NAME"
fi

# Auto-detect base branch if not specified
if [ -z "$BASE_BRANCH" ]; then
    pushd "$ROLLING_REPO" > /dev/null

    # Use version-specific base pattern
    base_pattern_var="ROCKY_CONFIG_${MAJOR_VERSION}_base_pattern"
    base_pattern="${!base_pattern_var}"

    # Look for rockyX_Y branches (exactly rockyX_Y, not rockyX_Y_rebuild)
    # Pattern: rocky10_1, rocky9_5, rocky8_10, etc.
    AVAILABLE_BASES=$(git branch -a | grep -oE "${base_pattern}[0-9]+$" | sort -t_ -k2 -n | uniq)
    BASE_BRANCH=$(echo "$AVAILABLE_BASES" | tail -1)

    if [ -z "$BASE_BRANCH" ]; then
        log_error "Could not auto-detect base branch for Rocky $MAJOR_VERSION"
        log_info "Available branches matching '${base_pattern}*':"
        git branch -a | grep -E "remotes/origin/${base_pattern}" | head -10 || echo "  (none found)"
        log_info "Specify a base branch with -b (e.g., -b ${base_pattern}1)"
        popd > /dev/null
        exit 1
    fi

    popd > /dev/null
    log_info "Auto-detected base branch: $BASE_BRANCH"
    log_info "Available base branches: $(echo "$AVAILABLE_BASES" | tr '\n' ' ')"
fi

# Update and checkout base branch (only on fresh run — resume preserves PR branch checkout)
log_info "Checking out base branch: $BASE_BRANCH"
if [ "$DRY_RUN" = false ] && [[ "$CURRENT_STAGE" =~ ^(init|detected)$ ]]; then
    pushd "$ROLLING_REPO" > /dev/null
    git checkout "$BASE_BRANCH"
    git pull origin "$BASE_BRANCH"
    popd > /dev/null
fi

# Auto-detect kernel release from base branch's resf_kernel tag
NEW_KERNEL_RELEASE=""
PREDICTED_NEW_BRANCH=""

pushd "$ROLLING_REPO" > /dev/null

# Use origin/BASE_BRANCH to get latest remote state (works in dry-run without checkout)
TAG_REF="origin/$BASE_BRANCH"
if [ "$DRY_RUN" = false ]; then
    TAG_REF="$BASE_BRANCH"
fi

# Get the latest resf_kernel tag from the base branch
# Tags look like: resf_kernel-6.12.0-124.28.1.el10_1
LATEST_RESF_TAG=$(git log "$TAG_REF" --oneline --decorate 2>/dev/null | \
    grep -oE "tag: resf_kernel-[^,)]*" | \
    head -1 | \
    sed 's/tag: resf_kernel-//')

if [ -n "$LATEST_RESF_TAG" ]; then
    NEW_KERNEL_RELEASE="$LATEST_RESF_TAG"
    PREDICTED_NEW_BRANCH="${ROLLING_PRODUCT}/${NEW_KERNEL_RELEASE}"
    log_info "Auto-detected kernel release: $NEW_KERNEL_RELEASE"
    log_info "Predicted new branch: $PREDICTED_NEW_BRANCH"
else
    log_warn "Could not detect kernel release from base branch tags"
fi

popd > /dev/null

# Auto-detect old rolling branch if not specified
if [ -z "$OLD_BRANCH" ]; then
    pushd "$ROLLING_REPO" > /dev/null

    # Extract minor version from base branch (e.g., rocky10_1 -> 10_1)
    MINOR_VERSION=$(echo "$BASE_BRANCH" | grep -oE "[0-9]+_[0-9]+")

    if [ "$NEW_MINOR_VERSION" = true ]; then
        # For minor version jumps (e.g., el9_7 -> el9_8), find the latest rolling
        # branch for this product regardless of minor version
        OLD_BRANCH=$(git branch -a | grep -E "^\s*${ROLLING_PRODUCT}/[0-9]" | \
            sed "s/.*${ROLLING_PRODUCT}/${ROLLING_PRODUCT}/" | \
            sort -V | \
            tail -1 | \
            tr -d ' *')
    else
        # Find the latest rolling branch that matches the minor version
        # Branches look like: rlc-10/6.12.0-124.27.1.el10_1 or sig-cloud-9/5.14.0-553.33.1.el9_5
        OLD_BRANCH=$(git branch -a | grep -E "${ROLLING_PRODUCT}/.*\.el${MINOR_VERSION}$" | \
            sed "s/.*${ROLLING_PRODUCT}/${ROLLING_PRODUCT}/" | \
            sort -V | \
            tail -1 | \
            tr -d ' *')
    fi

    popd > /dev/null

    if [ -z "$OLD_BRANCH" ]; then
        log_error "Could not auto-detect old rolling branch for $BASE_BRANCH. Please specify with -o"
        exit 1
    fi
    log_info "Auto-detected old rolling branch: $OLD_BRANCH"
fi

# Generate PR title prefix based on product
PR_PREFIX=$(echo "$ROLLING_PRODUCT" | tr '[:lower:]' '[:upper:]')

# Show summary
echo ""
echo "======================================"
log_info "Rolling Release Rebase Configuration:"
echo "  Rolling Product:    $ROLLING_PRODUCT"
echo "  Base Branch:        $BASE_BRANCH"
echo "  Old Rolling Branch: $OLD_BRANCH"
if [ -n "$NEW_KERNEL_RELEASE" ]; then
echo "  New Kernel Release: $NEW_KERNEL_RELEASE"
echo "  New Branch (pred.): $PREDICTED_NEW_BRANCH"
fi
echo "  KVM Name:           $KVM_NAME"
echo "  JIRA Ticket:        ${JIRA_TICKET:-'(not specified)'}"
echo "  Skip VM Build:      $SKIP_VM"
echo "  Skip Push:          $SKIP_PUSH"
echo "  Skip PR:            $SKIP_PR"
echo "  New Minor Version:  $NEW_MINOR_VERSION"
echo "  FIPS Override:      $FIPS_OVERRIDE"
echo "  Dry Run:            $DRY_RUN"
echo "======================================"
echo ""

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
fi

# Set up log files
# RR_LOGFILE: Clean rolling-release-update.py output only (for PR body)
# ORCH_LOGFILE: Full orchestrator log including VM build/test output
RR_LOGFILE="${LOG_DIR}/RR.${ROLLING_PRODUCT}.${LOG_TIMESTAMP}.log"
ORCH_LOGFILE="${LOG_DIR}/orchestrator.${ROLLING_PRODUCT}.${LOG_TIMESTAMP}.log"

# For backwards compatibility, LOGFILE points to orchestrator log
LOGFILE="$ORCH_LOGFILE"

# Save state after detection (only on fresh run — preserve loaded stage when resuming)
[[ "$CURRENT_STAGE" == "init" ]] && save_state "detected"

# Run rolling-release-update.py (skip if resuming from later stage or in phase-only modes)
if [[ "$CURRENT_STAGE" =~ ^(detected|init)$ ]] && [ "$BUILD_ONLY" = false ] && [ "$TEST_ONLY" = false ] && [ "$PR_ONLY" = false ]; then
    log_info "Running rolling-release-update.py..."

if [ "$DRY_RUN" = false ]; then
    pushd "$TOOLS_REPO" > /dev/null

    # Capture clean RR output to RR_LOGFILE, and also to orchestrator log
    RR_ARGS=(--repo "$ROLLING_REPO" --new-base-branch "$BASE_BRANCH" --old-rolling-branch "$OLD_BRANCH")
    if [ "$NEW_MINOR_VERSION" = true ]; then
        RR_ARGS+=(--new-minor-version)
    fi
    if [ "$FIPS_OVERRIDE" = true ]; then
        RR_ARGS+=(--fips-override)
    fi
    if [ "$INTERACTIVE" = true ]; then
        RR_ARGS+=(--interactive)
    fi

    python3 rolling-release-update.py "${RR_ARGS[@]}" \
        2>&1 | tee "$RR_LOGFILE" | tee -a "$ORCH_LOGFILE"

    RR_STATUS=${PIPESTATUS[0]}

    popd > /dev/null

    if [ "$RR_STATUS" -ne 0 ]; then
        log_error "rolling-release-update.py failed with exit code $RR_STATUS"
        log_error "Check log file: $RR_LOGFILE"
        exit 1
    fi

    log_success "rolling-release-update.py completed successfully"
    log_info "RR log file: $RR_LOGFILE"
    log_info "Orchestrator log: $ORCH_LOGFILE"
else
    NEW_MINOR_FLAG=""
    if [ "$NEW_MINOR_VERSION" = true ]; then
        NEW_MINOR_FLAG=" --new-minor-version"
    fi
    FIPS_FLAG=""
    if [ "$FIPS_OVERRIDE" = true ]; then
        FIPS_FLAG=" --fips-override"
    fi
    INTERACTIVE_FLAG=""
    if [ "$INTERACTIVE" = true ]; then
        INTERACTIVE_FLAG=" --interactive"
    fi
    log_info "[DRY RUN] Would run: python3 rolling-release-update.py --repo $ROLLING_REPO --new-base-branch $BASE_BRANCH --old-rolling-branch $OLD_BRANCH${NEW_MINOR_FLAG}${FIPS_FLAG}${INTERACTIVE_FLAG}"
fi
else
    log_info "Skipping rebase phase (resuming from $CURRENT_STAGE or phase-only mode)"
fi

# Extract the new branch name — preserve loaded state when resuming
if [ "$DRY_RUN" = false ]; then
    pushd "$ROLLING_REPO" > /dev/null

    if [ -n "${NEW_PR_BRANCH:-}" ]; then
        # Resuming with a saved PR branch — switch to it so build/test use the right tree
        git checkout "$NEW_PR_BRANCH"
        NEW_ROLLING_BRANCH="${NEW_ROLLING_BRANCH:-${NEW_PR_BRANCH#*_}}"
    else
        # Fresh run — read from current branch (set by rolling-release-update.py)
        NEW_PR_BRANCH=$(git branch --show-current)
        NEW_ROLLING_BRANCH="${NEW_PR_BRANCH#*_}"
    fi

    popd > /dev/null

    log_info "New rolling branch: $NEW_ROLLING_BRANCH"
    log_info "New PR branch:      $NEW_PR_BRANCH"
else
    # In dry-run mode, use predicted branch names
    if [ -n "$PREDICTED_NEW_BRANCH" ]; then
        NEW_ROLLING_BRANCH="$PREDICTED_NEW_BRANCH"
        NEW_PR_BRANCH="$(whoami)_${PREDICTED_NEW_BRANCH}"
        log_info "[DRY RUN] Predicted new rolling branch: $NEW_ROLLING_BRANCH"
        log_info "[DRY RUN] Predicted new PR branch:      $NEW_PR_BRANCH"
    fi
fi

# Save state after rebase
save_state "rebased"

# VM Build and Test
if [ "$SKIP_VM" = false ]; then
    log_info "Starting VM build and test..."

    # Clean up old build directory
    if [ -d "$BUILD_DIR" ]; then
        log_info "Cleaning up old build directory..."
        if [ "$DRY_RUN" = false ]; then
            rm -rf "$BUILD_DIR"
        fi
    fi

    # Copy kernel source to build directory
    log_info "Copying kernel source to build directory..."
    if [ "$DRY_RUN" = false ]; then
        cp -r "$ROLLING_REPO" "$BUILD_DIR"
    fi

    # Ensure VM is running (auto-start if shut off)
    VMIP=""
    if ensure_vm_running "$KVM_NAME"; then
        VMIP=$(virsh domifaddr "$KVM_NAME" 2>/dev/null | grep ipv4 | awk '{print $4}' | cut -d'/' -f1)
        if [ -z "$VMIP" ]; then
            log_error "Could not get VM IP address"
            exit 1
        fi
        log_info "VM IP: $VMIP"

        # Build kernel
        log_info "Building kernel in VM..."
        if [ "$DRY_RUN" = false ]; then
            # Temporarily disable exit-on-error because kernel_build.sh reboots the VM,
            # which causes SSH to disconnect with exit code 255 - this is expected behavior
            set +e
            ssh -o StrictHostKeyChecking=no "$VMIP" "cd /mnt/code/kernel-src-tree-build && ../kernel-src-tree-tools/kernel_build.sh" 2>&1 | tee -a "$LOGFILE"
            BUILD_STATUS=${PIPESTATUS[0]}
            set -e

            # Exit code 255 means SSH connection closed (expected during reboot)
            # Exit code 0 means success without reboot
            # Any other non-zero exit code is a real failure
            if [ "$BUILD_STATUS" -ne 0 ] && [ "$BUILD_STATUS" -ne 255 ]; then
                log_error "Kernel build failed with exit code $BUILD_STATUS"
                exit 1
            fi

            if [ "$BUILD_STATUS" -eq 255 ]; then
                log_info "SSH connection closed (VM is rebooting - this is expected)"
            fi
            log_success "Kernel build completed"
            save_state "built"
        fi

        # Exit early if BUILD_ONLY mode
        if [ "$BUILD_ONLY" = true ]; then
            log_info "BUILD-ONLY mode: stopping after build"
            exit 0
        fi

        # Wait for reboot
        log_info "Waiting for VM to come back online after reboot..."
        if [ "$DRY_RUN" = false ]; then
            sleep 60

            MAX_WAIT=120
            ATTEMPT=0
            until ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$VMIP" "echo" > /dev/null 2>&1; do
                ATTEMPT=$((ATTEMPT+1))
                if [ $ATTEMPT -ge $MAX_WAIT ]; then
                    log_error "VM failed to come back online"
                    exit 1
                fi
                log_info "Waiting for VM (attempt $ATTEMPT/$MAX_WAIT)..."
                sleep 10
            done
            log_success "VM is back online"
        fi

        # Run kselftests (skip if BUILD_ONLY)
        if [ "$BUILD_ONLY" = false ]; then
            log_info "Running kselftests..."
            if [ "$DRY_RUN" = false ]; then
                ssh -o StrictHostKeyChecking=no "$VMIP" "cd /mnt/code/kernel-src-tree-build && ../kernel-src-tree-tools/kernel_kselftest.sh" 2>&1 | tee -a "$LOGFILE"
                log_success "Kselftests completed"
                save_state "tested"
            fi
        fi

        # Exit early if TEST_ONLY mode
        if [ "$TEST_ONLY" = true ]; then
            log_info "TEST-ONLY mode: stopping after tests"
            exit 0
        fi
    else
        log_warn "VM $KVM_NAME could not be started, skipping VM testing"
    fi
else
    log_info "Skipping VM build and test (--no-vm specified)"
fi

# Build PR content (needed for both actual PR creation and preview)
PR_TITLE=""
PR_BODY=""

if [ "$DRY_RUN" = false ] && [ -n "$NEW_ROLLING_BRANCH" ]; then
    # Extract kernel version for PR title
    KERNEL_VERSION="${NEW_ROLLING_BRANCH#"${ROLLING_PRODUCT}/"}"
    PR_TITLE="[${PR_PREFIX}] Rebase Custom Changes to $NEW_ROLLING_BRANCH"

    # Get build timing from latest kbuild log (filtered to [TIMER] lines)
    # shellcheck disable=SC2012  # ls is safe here - we control the log naming convention
    LATEST_KBUILD=$(ls -t "${PARENT_DIR}"/kbuild*.log 2>/dev/null | head -n1)
    BUILD_TIMING=""
    if [ -n "${LATEST_KBUILD}" ] && [ -f "${LATEST_KBUILD}" ]; then
        BUILD_TIMING=$(grep -E -B 5 -A 5 "\[TIMER\]|^Starting Build" "${LATEST_KBUILD}" 2>/dev/null || echo "")
    fi

    # Get kselftest diff
    # Run from kselftest-logs/ where kernel_kselftest.sh stores kselftest.*.log files
    KSELFTEST_SCRIPT="${PARENT_DIR}/kernel-tools/kernel_auto_rebuild/get_kselftest_diff.sh"
    KSELFTEST_DIFF=""
    if [ -x "${KSELFTEST_SCRIPT}" ] && [ -d "${PARENT_DIR}/kselftest-logs" ]; then
        pushd "${PARENT_DIR}/kselftest-logs" > /dev/null
        KSELFTEST_DIFF=$(bash "${KSELFTEST_SCRIPT}" 2>/dev/null || echo "")
        popd > /dev/null
    fi

    # Build PR body (following PR #864 format)
    PR_BODY="## Update process (This kernel CentOS base for $KERNEL_VERSION)
* Rolling Release Rebase Process
* Create \`$NEW_ROLLING_BRANCH\` branch from \`$BASE_BRANCH\`
* Cherry-pick all code from previous branch \`$OLD_BRANCH\` into new branch (skipping unneeded code)
  * Fix conflicts as they arise
* Build and Test

## Rebase Log
\`\`\`
$(cat "$RR_LOGFILE" 2>/dev/null || echo "Log file not available")
\`\`\`"

    # Add BUILD section if we have timing data
    if [ -n "${BUILD_TIMING}" ]; then
        PR_BODY="${PR_BODY}

## BUILD
\`\`\`
\$ egrep -B 5 -A 5 \"\\[TIMER\\]|^Starting Build\" \$(ls -t kbuild* | head -n1)
${BUILD_TIMING}
\`\`\`"
    fi

    # Add KSelfTest section if we have diff data
    if [ -n "${KSELFTEST_DIFF}" ]; then
        PR_BODY="${PR_BODY}

## KSelfTest
\`\`\`
\$ ./kernel-tools/kernel_auto_rebuild/get_kselftest_diff.sh
${KSELFTEST_DIFF}
\`\`\`"
    fi

    # Add JIRA link at the top if specified
    if [ -n "$JIRA_TICKET" ]; then
        PR_BODY="https://ciqinc.atlassian.net/browse/$JIRA_TICKET

$PR_BODY"
    fi
fi

# Push branches
if [ "$DRY_RUN" = false ] && [ -n "$NEW_ROLLING_BRANCH" ]; then
    if [ "$SKIP_PUSH" = false ]; then
        log_info "Pushing branches to origin..."

        pushd "$ROLLING_REPO" > /dev/null

        # Push the rolling branch (with tags)
        log_info "Pushing $NEW_ROLLING_BRANCH (with tags)..."
        git push --follow-tags origin "$NEW_ROLLING_BRANCH"

        # Push the PR branch
        log_info "Pushing $NEW_PR_BRANCH..."
        git push origin "$NEW_PR_BRANCH"

        popd > /dev/null

        log_success "Branches pushed successfully"
        save_state "pushed"
    else
        log_info "Skipping push (--no-push specified)"
        echo ""
        log_info "Would push the following branches:"
        echo "  git push origin $NEW_ROLLING_BRANCH"
        echo "  git push origin $NEW_PR_BRANCH"
    fi
fi

# PR fallback file function - creates MD file if gh pr create fails
create_pr_fallback_file() {
    local fallback_file="${LOG_DIR}/PR.${ROLLING_PRODUCT}.${KERNEL_VERSION}.md"
    cat > "$fallback_file" << EOF
# PR: ${PR_TITLE}

**Repository:** ctrliq/kernel-src-tree
**Base:** ${NEW_ROLLING_BRANCH}
**Head:** ${NEW_PR_BRANCH}

---

${PR_BODY}

---

## To create manually:
\`\`\`bash
gh pr create --repo ctrliq/kernel-src-tree --base "${NEW_ROLLING_BRANCH}" --head "${NEW_PR_BRANCH}" --title "${PR_TITLE}" --body-file "${fallback_file}"
\`\`\`
EOF
    log_info "PR content saved to: $fallback_file"
    echo "$fallback_file"
}

# Create PR
PR_URL=""
if [ "$DRY_RUN" = false ] && [ -n "$NEW_ROLLING_BRANCH" ]; then
    if [ "$SKIP_PR" = false ] && [ "$SKIP_PUSH" = false ]; then
        log_info "Creating pull request..."

        # Create PR using gh CLI
        if command -v gh &> /dev/null; then
            pushd "$ROLLING_REPO" > /dev/null

            # Check for existing PR first
            EXISTING_PR=$(gh pr list --repo ctrliq/kernel-src-tree --head "$NEW_PR_BRANCH" --base "$NEW_ROLLING_BRANCH" --state open --json number --jq '.[0].number // empty' 2>/dev/null || echo "")
            if [ -n "${EXISTING_PR}" ]; then
                log_warn "PR already exists: https://github.com/ctrliq/kernel-src-tree/pull/${EXISTING_PR}"
                PR_URL="https://github.com/ctrliq/kernel-src-tree/pull/${EXISTING_PR}"
            else
                # Create new PR
                if gh pr create \
                    --repo ctrliq/kernel-src-tree \
                    --title "$PR_TITLE" \
                    --body "$PR_BODY" \
                    --base "$NEW_ROLLING_BRANCH" \
                    --head "$NEW_PR_BRANCH"; then

                    PR_URL=$(gh pr view --json url -q '.url' 2>/dev/null || echo "")

                    if [ -n "$PR_URL" ]; then
                        log_success "Pull request created: $PR_URL"
                    else
                        log_success "Pull request created"
                    fi
                else
                    log_error "gh pr create failed"
                    FALLBACK_FILE=$(create_pr_fallback_file)
                    log_info "You can create the PR manually using the fallback file: $FALLBACK_FILE"
                fi
            fi

            popd > /dev/null
        else
            log_warn "gh CLI not found, creating fallback file"
            FALLBACK_FILE=$(create_pr_fallback_file)
            log_info "Create PR manually using: $FALLBACK_FILE"
        fi
    else
        if [ "$SKIP_PR" = true ] || [ "$SKIP_PUSH" = true ]; then
            log_info "Skipping PR creation (--no-push or --no-pr specified)"
            echo ""
            echo "======================================"
            log_info "Proposed Pull Request:"
            echo "======================================"
            echo ""
            echo "Repository: ctrliq/kernel-src-tree"
            echo "Base branch: $NEW_ROLLING_BRANCH"
            echo "Head branch: $NEW_PR_BRANCH"
            echo ""
            echo "Title: $PR_TITLE"
            echo ""
            echo "Body:"
            echo "--------------------------------------"
            echo "$PR_BODY"
            echo "--------------------------------------"
        fi
    fi
fi

# Summary
ENDTIME=$(date +%s)
ELAPSED=$((ENDTIME - STARTTIME))
HOURS=$((ELAPSED / 3600))
MINUTES=$(((ELAPSED % 3600) / 60))
SECONDS=$((ELAPSED % 60))

echo ""
echo "======================================"
log_success "Rolling Release Rebase completed!"
echo "  Rolling Product:    $ROLLING_PRODUCT"
echo "  New rolling branch: $NEW_ROLLING_BRANCH"
echo "  New PR branch:      $NEW_PR_BRANCH"
if [ -n "$PR_URL" ]; then
echo "  PR URL:             $PR_URL"
fi
echo "  RR log file:        $RR_LOGFILE"
echo "  Orchestrator log:   $ORCH_LOGFILE"
printf "  Elapsed time:       %02d:%02d:%02d\n" "$HOURS" "$MINUTES" "$SECONDS"
echo "======================================"

exit 0
