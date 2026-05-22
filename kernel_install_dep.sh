#!/bin/sh
set -e

# So we can detect what version of Rocky we are running on
. /etc/os-release

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
    conntrack-tools \
    curl \
    dropwatch \
    dwarves \
    e2fsprogs \
    ethtool \
    fuse \
    glibc \
    iperf3 \
    iptables \
    iputils \
    ipvsadm \
    jq \
    kernel-devel \
    kernel-tools \
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
    nftables \
    nmap-ncat \
    numactl-devel \
    openssl-devel \
    perf \
    popt-devel \
    python3-pip \
    rsync \
    socat \
    tcpdump \
    teamd \
    traceroute \
    wget

    # Doesn't work for 8.6?
    sudo dnf -y install --enablerepo=devel \
    fuse-devel \
    gcc-toolset-13-libasan-devel \
    glibc-static \
    kernel-selftests-internal

    pip3 install --user \
    jsonschema \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    pyyaml \
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
    conntrack-tools \
    curl \
    dropwatch \
    dwarves \
    e2fsprogs \
    ethtool \
    fuse \
    fuse-devel \
    gcc-toolset-13-libasan-devel \
    glibc \
    glibc-static \
    iperf3 \
    iptables \
    iputils \
    ipvsadm \
    jq \
    kernel-devel \
    kernel-selftests-internal \
    kernel-tools \
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
    nftables \
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
    teamd \
    traceroute \
    virtme-ng \
    wget

    pip3 install --user \
    jsonschema \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    pyyaml \
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
    conntrack-tools \
    curl \
    dropwatch \
    dwarves \
    e2fsprogs \
    ethtool \
    fuse \
    fuse-devel \
    glibc \
    glibc-static \
    iperf3 \
    iptables \
    iputils \
    ipvsadm \
    jq \
    kernel-devel \
    kernel-selftests-internal \
    kernel-tools \
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
    netsniff-ng \
    nftables \
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
    teamd \
    traceroute \
    virtme-ng \
    wget

    pip3 install --user \
    jsonschema \
    netaddr \
    packaging \
    pyftpdlib \
    pyparsing \
    pytest \
    pyyaml \
    scapy \
    tftpy \
    wheel
}

case "${VERSION_ID%%.*}" in
    10)
        install_kselftest_deps_10
        ;;
    9)
        install_kselftest_deps_9
        ;;
    8)
        install_kselftest_deps_8
        ;;
esac
