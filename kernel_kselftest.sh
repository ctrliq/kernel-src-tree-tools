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
    SUDO_TARGETS=$1
    SKIP_TARGETS=$2
    mkdir -p $KSELFTEST_LOG_DIR
    make -j $(nproc) -C tools/testing/selftests clean
    make -j $(nproc) -C tools/testing/selftests SKIP_TARGETS="$SKIP_TARGETS"
    for run in $(seq 1 $runs) ; do
        make -C tools/testing/selftests SKIP_TARGETS="$SUDO_TARGETS $SKIP_TARGETS" run_tests | tee $KSELFTEST_LOG_DIR/selftest-$(uname -r)-$run.log
        sudo make -C tools/testing/selftests TARGETS="$SUDO_TARGETS" run_tests | tee -a $KSELFTEST_LOG_DIR/selftest-$(uname -r)-$run.log
    done
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/kernel_install_dep.sh"

case $(uname -r) in
    *3.10.0*)
        echo
        echo "Running 3.10.0 kselftests"
        echo
        SUDO_TARGETS="x86"
        SKIP_TARGETS=""
        ;;
    *4.18.0*)
        echo
        echo "Running 4.18.0 kselftests"
        echo
        SUDO_TARGETS="capabilities cpu-hotplug cpufreq efivars efivarfs fpu ipc intel_pstate kexec lib livepatch memfd memory-hotplug mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS=""
        ;;
    *5.14.0-570*|\
    *5.14.0-611*)
        echo
        echo "Running 5.14.0-570/611 kselftests (el9_6/el9_7 - skipping pidfd)"
        echo
	#SUDO_TARGETS="zram"
	#SUDO_TARGETS="binderfs capabilities cgroup cpu-hotplug cpufreq efivars efivarfs firmware fpu zram"
	#SUDO_TARGETS="gpio ipc intel_pstate ir kexec lib livepatch memory-hotplug zram"
	#SUDO_TARGETS="mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        #SUDO_TARGETS="binderfs capabilities cgroup cpu-hotplug cpufreq efivars efivarfs firmware fpu gpio ipc intel_pstate ir kexec lib livepatch memory-hotplug mptcp mqueue netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS="lkdtm memfd net pidfd"
        ;;
    *5.14.0*)
        echo
        echo "Running 5.14.0 kselftests"
        echo
        SUDO_TARGETS="binderfs capabilities cgroup cpu-hotplug cpufreq efivars efivarfs firmware fpu gpio ipc intel_pstate ir kexec lib livepatch memfd memory-hotplug mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS="lkdtm proc"
        ;;
    *6.12.*|\
    *6.18.*)
        echo
        echo "Running 6.12/6.18 kselftests"
        echo
        SUDO_TARGETS="binderfs capabilities cgroup clone3 cpu-hotplug cpufreq damon drivers/net efivars efivarfs exec firmware fpu gpio ipc intel_pstate ir kexec lib livepatch memfd memory-hotplug mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS="lkdtm net/forwarding"
        ;;
    *)
        echo
        echo "Warning: Unknown kernel version ($(uname -r)). No kselftest targets defined."
        exit 1
        ;;
esac

run_kselftest "$SUDO_TARGETS" "$SKIP_TARGETS"
