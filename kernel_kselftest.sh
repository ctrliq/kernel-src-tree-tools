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

install_kselftest_deps_8() {
    echo
    echo "Installing kselftest deps for Rocky 8"
    echo
    sudo dnf -y groupinstall 'Development Tools'
    sudo dnf -y install epel-release
    sudo dnf -y install --enablerepo=devel \
    VirtualGL \
    alsa-lib-devel \
    bc \
    clang \
    curl \
    dropwatch \
    dwarves \
    glibc \
    iperf3 \
    jq \
    kernel-devel \
    libasan \
    libcap-devel \
    libcap-ng-devel \
    libmnl-devel \
    libreswan \
    libubsan \
    llvm \
    ncurses-devel \
    net-tools \
    netsniff-ng \
    nmap-ncat \
    numactl-devel \
    openssl-devel \
    perf \
    popt-devel \
    python3-pip \
    rsync \
    socat \
    tcpdump \
    wget

    # Doesn't work for 8.6?
    sudo dnf -y install --enablerepo=devel \
    fuse-devel \
    gcc-toolset-13-libasan-devel \
    glibc-static \
    kernel-selftests-internal

    pip3 install --user \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    scapy \
    tftpy
}

install_kselftest_deps_9() {
    echo
    echo "Installing kselftest deps for Rocky 9"
    echo
    sudo dnf -y groupinstall 'Development Tools'
    sudo dnf -y install epel-release
    sudo dnf -y install --enablerepo=crb,devel \
    VirtualGL \
    alsa-lib-devel \
    bc \
    clang \
    curl \
    dropwatch \
    dwarves \
    fuse-devel \
    gcc-toolset-13-libasan-devel \
    glibc \
    glibc-static \
    iperf3 \
    jq \
    kernel-devel \
    kernel-selftests-internal \
    libasan \
    libcap-devel \
    libcap-ng-devel \
    libmnl-devel \
    libreswan \
    libubsan \
    llvm \
    ncurses-devel \
    net-tools \
    netsniff-ng \
    nmap-ncat \
    numactl-devel \
    openssl-devel \
    packetdrill \
    perf \
    popt-devel \
    python3-pip \
    rsync \
    socat \
    tcpdump \
    virtme-ng \
    wget

    pip3 install --user \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    scapy \
    tftpy \
    wheel
}

install_kselftest_deps_10() {
    echo
    echo "Installing kselftest deps for Rocky 10"
    echo
    sudo dnf -y groupinstall 'Development Tools'
    sudo dnf -y install epel-release
    sudo dnf -y install --enablerepo=crb,devel \
    alsa-lib-devel \
    bc \
    clang \
    curl \
    dropwatch \
    dwarves \
    fuse-devel \
    glibc \
    glibc-static \
    iperf3 \
    kernel-devel \
    kernel-selftests-internal \
    libasan \
    libasan-static \
    libcap-devel \
    libcap-ng-devel \
    libmnl-devel \
    libreswan \
    libubsan \
    llvm \
    ncurses-devel \
    net-tools \
    nmap-ncat \
    numactl-devel \
    openssl-devel \
    packetdrill \
    perf \
    popt-devel \
    python3-pip \
    rsync \
    socat \
    tcpdump \
    virtme-ng \
    wget

    pip3 install --user \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    scapy \
    tftpy \
    wheel
}

run_kselftest() {
    SUDO_TARGETS=$1
    SKIP_TARGETS=$2
    mkdir -p $KSELFTEST_LOG_DIR
    make -C tools/testing/selftests clean
    make -C tools/testing/selftests SKIP_TARGETS="$SKIP_TARGETS"
    for run in $(seq 1 $runs) ; do
        make -C tools/testing/selftests SKIP_TARGETS="$SUDO_TARGETS $SKIP_TARGETS" run_tests | tee $KSELFTEST_LOG_DIR/selftest-$(uname -r)-$run.log
        sudo make -C tools/testing/selftests TARGETS="$SUDO_TARGETS" run_tests | tee -a $KSELFTEST_LOG_DIR/selftest-$(uname -r)-$run.log
    done
}

case "$ROCKY_SUPPORT_PRODUCT" in
    Rocky-Linux-10)
        install_kselftest_deps_10
        ;;
    Rocky-Linux-9)
        install_kselftest_deps_9
        ;;
    Rocky-Linux-8)
        install_kselftest_deps_8
        ;;
esac

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
    *5.14.0*)
        echo
        echo "Running 5.14.0 kselftests"
        echo
        SUDO_TARGETS="binderfs capabilities cgroup cpu-hotplug cpufreq efivars efivarfs firmware fpu gpio ipc intel_pstate ir kexec lib livepatch memfd memory-hotplug mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS="lkdtm proc"
        ;;
    *6.12.*)
        echo
        echo "Running 6.12 kselftests"
        echo
        SUDO_TARGETS="binderfs capabilities cgroup clone3 cpu-hotplug cpufreq damon drivers/net efivars efivarfs exec firmware fpu gpio ipc intel_pstate ir kexec lib livepatch memfd memory-hotplug mptcp mqueue net netfilter sync sysctl timens timers vm x86 zram"
        SKIP_TARGETS="lkdtm"
        ;;
    *)
        echo
        echo "Warning: Unknown kernel version ($(uname -r)). No kselftest targets defined."
        exit 1
        ;;
esac

run_kselftest "$SUDO_TARGETS" "$SKIP_TARGETS"

