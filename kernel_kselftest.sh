#!/bin/sh
set -e

KSELFTEST_LOG_DIR=${KSELFTEST_LOG_DIR:-../kselftest-logs}

# So we can detect what version of Rocky we are running on
. /etc/os-release

if [ ! -f .config ] ; then
    echo "No .config found.  Please configure before testing"
    exit 1
fi

if [ $# -eq 1 ] ; then
    runs=$1
else
    runs=1
fi

run_kselftest() {
    mkdir -p "$KSELFTEST_LOG_DIR"
    pushd tools/bpf/bpftool
    make -j$(nproc)
    popd

    make -j$(nproc) samples/bpf/

    BPFTOOL=$(pwd)/tools/bpf/bpftool/bpftool
    KSELFTEST_PATH=/var/kselftests

    pushd tools/testing/selftests

    make -j$(nproc) SKIP_TARGETS="$SKIP_TARGETS" INSTALL_PATH="$KSELFTEST_PATH" install
    popd

    for run in $(seq 1 $runs) ; do
        "$KSELFTEST_PATH/run_kselftest.sh" | tee "$KSELFTEST_LOG_DIR/selftest-$(uname -r)-$run.log"
    done
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/kernel_install_dep.sh"

case $(uname -r) in
    *3.10.0*)
        echo
        echo "Running 3.10.0 kselftests"
        echo
        SKIP_TARGETS=""
        ;;
    *4.18.0*)
        echo
        echo "Running 4.18.0 kselftests"
        echo
        SKIP_TARGETS=""
        ;;
    *5.14.0*)
        echo
        echo "Running 5.14.0 kselftests"
        echo
        SKIP_TARGETS="lkdtm proc pidfd"
        ;;
    *6.12.*|\
    *6.18.*)
        echo
        echo "Running 6.12/6.18 kselftests"
        echo
        SKIP_TARGETS="lkdtm net/forwarding"
        ;;
    *)
        echo
        echo "Warning: Unknown kernel version ($(uname -r)). No kselftest targets defined."
        exit 1
        ;;
esac

run_kselftest
