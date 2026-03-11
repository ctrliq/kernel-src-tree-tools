#!/bin/bash
#
# LTP Test Runner for Rocky Linux 8, 9, 10 and CentOS 7
# This script installs dependencies, builds LTP, and runs test suites
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
LTP_VERSION="${LTP_VERSION:-20250930}"
LTP_URL="https://github.com/linux-test-project/ltp/releases/download/${LTP_VERSION}/ltp-full-${LTP_VERSION}.tar.xz"
LTP_SRC_DIR="${LTP_SRC_DIR:-/opt/ltp-src}"
LTP_INSTALL_DIR="${LTP_INSTALL_DIR:-/opt/ltp}"
LTP_TMP_DIR="${LTP_TMP_DIR:-/tmp/ltp}"
SKIP_INSTALL="${SKIP_INSTALL:-false}"
SKIP_BUILD="${SKIP_BUILD:-false}"
RUN_TESTS="${RUN_TESTS:-true}"
CONTINUE_ON_BUILD_FAIL="${CONTINUE_ON_BUILD_FAIL:-true}"

# Test suite selection
TEST_SUITE="${TEST_SUITE:-syscalls}"  # Default to syscalls suite
CUSTOM_TESTS="${CUSTOM_TESTS:-}"      # Custom test file

# Log file
LOG_FILE="${LOG_FILE:-ltp_test_results_$(date +%Y%m%d_%H%M%S).log}"

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root"
        exit 1
    fi
}

# Function to detect OS version (Rocky Linux or CentOS)
detect_os_version() {
    RHEL_VERSION=$(rpm -E %{rhel})

    if [[ -f /etc/rocky-release ]]; then
        OS_TYPE="rocky"
        OS_NAME="Rocky Linux"
    elif [[ -f /etc/centos-release ]]; then
        OS_TYPE="centos"
        OS_NAME="CentOS"
    elif [[ -f /etc/redhat-release ]]; then
        OS_TYPE="rhel"
        OS_NAME="RHEL"
    else
        print_error "This script is designed for Rocky Linux or CentOS systems"
        exit 1
    fi

    print_info "Detected ${OS_NAME} ${RHEL_VERSION}"

    # Set package manager based on OS version
    if [[ "$RHEL_VERSION" -le 7 ]]; then
        PKG_MANAGER="yum"
    else
        PKG_MANAGER="dnf"
    fi

    if [[ "$OS_TYPE" == "centos" && "$RHEL_VERSION" -lt 7 ]]; then
        print_error "CentOS versions below 7 are not supported"
        exit 1
    fi

    if [[ "$OS_TYPE" == "rocky" && ! "$RHEL_VERSION" =~ ^[8-9]$|^10$ ]]; then
        print_warn "This script is tested on Rocky 8, 9, and 10. Your version: ${RHEL_VERSION}"
    fi
}

# Function to install build dependencies
install_dependencies() {
    print_info "Installing build dependencies..."

    # Common dependencies for all Rocky versions
    local packages=(
        # Build essentials
        gcc
        gcc-c++
        make
        autoconf
        automake
        libtool
        pkgconfig
        bison
        flex
        m4

        # Development libraries
        kernel-devel
        glibc-devel
        libaio-devel
        libacl-devel
        libcap-devel
        numactl-devel
        openssl-devel

        # Utilities
        git
        wget
        tar
        xz
        procps-ng
        psmisc

        # Additional dependencies
        libselinux-devel
        libtirpc-devel
        quota

        # For networking tests
        iproute
        iptables
        net-tools
    )

    packages+=(keyutils-libs-devel)

    # Enable extra repositories based on OS version
    if [[ "$RHEL_VERSION" -eq 7 ]]; then
        # CentOS 7: install yum-utils for yum-config-manager, enable extras
        $PKG_MANAGER install -y yum-utils || true
        yum-config-manager --enable extras &>/dev/null || true
    elif [[ "$RHEL_VERSION" -eq 8 ]]; then
        dnf config-manager --set-enabled powertools || true
    elif [[ "$RHEL_VERSION" -ge 9 ]]; then
        dnf config-manager --set-enabled crb || true
    fi

    # Install EPEL if not already installed
    if ! rpm -q epel-release &>/dev/null; then
        print_info "Installing EPEL repository..."
        $PKG_MANAGER install -y epel-release
    fi

    # Install packages
    $PKG_MANAGER install -y "${packages[@]}"

    print_info "Dependencies installed successfully"
}

# Function to download and extract LTP
download_ltp() {
    print_info "Downloading LTP version ${LTP_VERSION}..."

    mkdir -p "$(dirname "$LTP_SRC_DIR")"

    if [[ -d "$LTP_SRC_DIR" ]]; then
        print_warn "LTP source directory already exists: ${LTP_SRC_DIR}"
        read -p "Remove and re-download? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$LTP_SRC_DIR"
        else
            print_info "Using existing source directory"
            return 0
        fi
    fi

    # Download LTP
    local tmp_file="/tmp/ltp-${LTP_VERSION}.tar.xz"
    wget -O "$tmp_file" "$LTP_URL"

    # Extract
    print_info "Extracting LTP..."
    mkdir -p "$LTP_SRC_DIR"
    tar -xf "$tmp_file" -C "$LTP_SRC_DIR" --strip-components=1
    rm -f "$tmp_file"

    print_info "LTP downloaded and extracted to ${LTP_SRC_DIR}"
}

# Function to build and install LTP
build_ltp() {
    print_info "Building LTP..."

    cd "$LTP_SRC_DIR"

    # Configure
    print_info "Running configure..."
    make autotools
    ./configure --prefix="$LTP_INSTALL_DIR"

    # Build
    print_info "Compiling (this may take a while)..."
    print_warn "Note: Some tests may fail to compile due to system header conflicts"
    print_warn "This is normal - the script will continue and install what built successfully"

    if [[ "$CONTINUE_ON_BUILD_FAIL" == "true" ]]; then
        # Continue on build failures - some tests may not compile
        make -j$(nproc) -k || {
            print_warn "Build completed with some errors (this is expected on some systems)"
            print_info "Proceeding with installation of successfully built tests..."
        }
    else
        # Fail on any build error
        make -j$(nproc)
    fi

    # Install
    print_info "Installing to ${LTP_INSTALL_DIR}..."
    if [[ "$CONTINUE_ON_BUILD_FAIL" == "true" ]]; then
        # Use -k to keep going on errors and install everything possible
        make -k install || {
            print_warn "Installation completed with some errors (expected with partial build)"
        }
    else
        # Fail on any install error
        make install
    fi

    print_info "LTP installation completed"

    # Check what was installed
    if [[ -d "${LTP_INSTALL_DIR}/testcases/bin" ]]; then
        local test_count=$(find "${LTP_INSTALL_DIR}/testcases/bin" -type f -executable | wc -l)
        print_info "Successfully installed ${test_count} test executables"
    fi

    # Verify runltp is available
    if [[ ! -f "${LTP_INSTALL_DIR}/runltp" ]]; then
        print_error "runltp script not found in ${LTP_INSTALL_DIR}"
        print_error "Installation may be incomplete"
        if [[ "$CONTINUE_ON_BUILD_FAIL" != "true" ]]; then
            exit 1
        fi
    else
        print_info "runltp script installed successfully"
    fi
}

# Function to list available test suites
list_test_suites() {
    print_info "Available test suites in ${LTP_INSTALL_DIR}/runtest/:"
    if [[ -d "${LTP_INSTALL_DIR}/runtest" ]]; then
        ls -1 "${LTP_INSTALL_DIR}/runtest/" | column
    else
        print_error "LTP not installed. Run with installation first."
        exit 1
    fi
}

# Function to run LTP tests
run_ltp_tests() {
    print_info "Running LTP tests..."

    if [[ ! -d "$LTP_INSTALL_DIR" ]]; then
        print_error "LTP not installed at ${LTP_INSTALL_DIR}"
        exit 1
    fi

    # Create temporary directory for test output
    mkdir -p "$LTP_TMP_DIR"

    cd "$LTP_INSTALL_DIR"

    # Build runltp command
    local runltp_cmd="./runltp"
    local runltp_args=()

    # Output directory and log file
    runltp_args+=("-d" "$LTP_TMP_DIR")
    runltp_args+=("-l" "$LOG_FILE")

    # Test suite selection
    if [[ -n "$CUSTOM_TESTS" ]]; then
        print_info "Running custom test file: ${CUSTOM_TESTS}"
        runltp_args+=("-f" "$CUSTOM_TESTS")
    elif [[ "$TEST_SUITE" == "all" ]]; then
        print_info "Running all test suites (this will take a long time)..."
    elif [[ -f "${LTP_INSTALL_DIR}/runtest/${TEST_SUITE}" ]]; then
        print_info "Running test suite: ${TEST_SUITE}"
        runltp_args+=("-f" "$TEST_SUITE")
    else
        print_error "Test suite '${TEST_SUITE}' not found"
        print_info "Available test suites:"
        list_test_suites
        exit 1
    fi

    # Run tests
    print_info "Command: ${runltp_cmd} ${runltp_args[*]}"
    print_info "Results will be logged to: ${LOG_FILE}"
    print_info "Temporary files in: ${LTP_TMP_DIR}"

    $runltp_cmd "${runltp_args[@]}" || true

    print_info "Test execution completed"

    # Find where logs actually ended up (runltp may move them)
    local actual_log="${LTP_INSTALL_DIR}/results/${LOG_FILE}"
    if [[ -f "$actual_log" ]]; then
        print_info "Results saved to: ${actual_log}"
        LOG_FILE="$actual_log"
    elif [[ -f "$LOG_FILE" ]]; then
        print_info "Results saved to: ${LOG_FILE}"
    else
        print_warn "Log file not found at expected location"
    fi

    # Show summary
    if [[ -f "$LOG_FILE" ]]; then
        local total=$(grep -c "^tag=" "$LOG_FILE" 2>/dev/null | tr -d '\n' || echo "0")
        local passed=$(grep -c "stat=0" "$LOG_FILE" 2>/dev/null | tr -d '\n' || echo "0")
        local failed=$(grep -c "stat=1" "$LOG_FILE" 2>/dev/null | tr -d '\n' || echo "0")
        local tconf=$(grep -c "stat=2" "$LOG_FILE" 2>/dev/null | tr -d '\n' || echo "0")
        local skipped=$(grep -c "stat=32" "$LOG_FILE" 2>/dev/null | tr -d '\n' || echo "0")

        print_info "Test Summary:"
        echo "----------------------------------------"
        echo "Total tests:    $total"
        echo "Passed:         $passed"
        echo "Failed:         $failed"
        echo "Not configured: $tconf (tests not built/available)"
        echo "Skipped:        $skipped"
        echo "----------------------------------------"

        if [[ "$tconf" -gt 0 ]] && [[ "$passed" -eq 0 ]]; then
            print_warn "No tests actually ran - all tests were not configured"
            print_warn "This likely means the test executables were not built due to compilation errors"
            print_info "Only $( find "${LTP_INSTALL_DIR}/testcases/bin" -type f -executable 2>/dev/null | wc -l) test executables are available"
        fi

        print_info "Detailed logs: ${LTP_INSTALL_DIR}/output/"
        print_info "Full results:  ${LOG_FILE}"
    fi
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

LTP Test Runner for Rocky Linux 8, 9, 10 and CentOS 7

OPTIONS:
    -h, --help              Show this help message
    -l, --list              List available test suites
    -s, --suite SUITE       Run specific test suite (default: syscalls)
                           Use 'all' to run all suites
    -f, --file FILE         Run custom test file
    -i, --install-only      Only install dependencies and build LTP
    -t, --test-only         Only run tests (skip installation)
    -v, --version VERSION   LTP version to download (default: 20250930)
    --skip-deps            Skip dependency installation
    --ltp-dir DIR          LTP installation directory (default: ${LTP_INSTALL_DIR})
    --log-file FILE        Output log file (default: auto-generated)
    --fail-on-build-error  Fail if any test fails to compile (default: continue)

ENVIRONMENT VARIABLES:
    LTP_VERSION               LTP version to download
    LTP_INSTALL_DIR           Installation directory
    LTP_SRC_DIR               Source directory
    LTP_TMP_DIR               Temporary directory for test output
    TEST_SUITE                Test suite to run
    SKIP_INSTALL              Skip installation if set to 'true'
    SKIP_BUILD                Skip build if set to 'true'
    CONTINUE_ON_BUILD_FAIL    Continue if build fails (default: true)
    LOG_FILE                  Log file path

EXAMPLES:
    # Install and run default test suite (syscalls)
    $0

    # List available test suites
    $0 --list

    # Run specific test suite
    $0 --suite fs

    # Run multiple suites by running script multiple times
    $0 --suite syscalls
    $0 --test-only --suite fs

    # Install only
    $0 --install-only

    # Run tests only (if already installed)
    $0 --test-only --suite commands

    # Use specific LTP version
    $0 --version 20231020

EOF
}

# Main function
main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -l|--list)
                list_test_suites
                exit 0
                ;;
            -s|--suite)
                TEST_SUITE="$2"
                shift 2
                ;;
            -f|--file)
                CUSTOM_TESTS="$2"
                shift 2
                ;;
            -i|--install-only)
                RUN_TESTS="false"
                shift
                ;;
            -t|--test-only)
                SKIP_INSTALL="true"
                SKIP_BUILD="true"
                shift
                ;;
            -v|--version)
                LTP_VERSION="$2"
                LTP_URL="https://github.com/linux-test-project/ltp/releases/download/${LTP_VERSION}/ltp-full-${LTP_VERSION}.tar.xz"
                shift 2
                ;;
            --skip-deps)
                SKIP_INSTALL="true"
                shift
                ;;
            --ltp-dir)
                LTP_INSTALL_DIR="$2"
                shift 2
                ;;
            --log-file)
                LOG_FILE="$2"
                shift 2
                ;;
            --fail-on-build-error)
                CONTINUE_ON_BUILD_FAIL="false"
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    print_info "=== LTP Test Runner for Rocky Linux / CentOS ==="

    # Check if running as root
    check_root

    # Detect OS version
    detect_os_version

    # Install dependencies and build LTP
    if [[ "$SKIP_INSTALL" != "true" ]]; then
        install_dependencies
    fi

    if [[ "$SKIP_BUILD" != "true" ]]; then
        download_ltp
        build_ltp
    fi

    # Run tests
    if [[ "$RUN_TESTS" == "true" ]]; then
        run_ltp_tests
    else
        print_info "Skipping test execution (install-only mode)"
        print_info "To run tests later, use: $0 --test-only --suite <suite_name>"
    fi

    print_info "=== Done ==="
}

# Run main function
main "$@"
