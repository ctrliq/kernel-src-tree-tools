# LTP Test Runner for Rocky Linux and CentOS

A comprehensive script to install, build, and run the Linux Test Project (LTP) test suites on Rocky Linux 8, 9, and 10, and CentOS 7.

## Features

- Automatic detection of Rocky Linux and CentOS version
- Installation of all required build dependencies
- Downloads and builds LTP from official releases
- Support for running individual test suites or all suites
- Flexible configuration via command-line options or environment variables
- Detailed logging of test results in machine-parseable format
- Result comparison tool to detect kernel regressions
- Can skip installation/build steps if LTP is already installed

## Prerequisites

- Rocky Linux 8, 9, or 10, or CentOS 7
- Root/sudo access
- Internet connection (for downloading packages and LTP source)

## Quick Start

### Basic Usage (Install and Run Default Test Suite)

```bash
sudo ./run_ltp_tests.sh
```

This will:
1. Install all necessary dependencies
2. Download LTP (version 20250930 by default)
3. Build and install LTP to `/opt/ltp`
4. Run the default `syscalls` test suite

### List Available Test Suites

```bash
sudo ./run_ltp_tests.sh --list
```

### Run Specific Test Suite

```bash
sudo ./run_ltp_tests.sh --suite fs
```

### Run All Test Suites (Warning: Takes Many Hours)

```bash
sudo ./run_ltp_tests.sh --suite all
```

## Common Test Suites

- `syscalls` - System call tests (default)
- `fs` - Filesystem tests
- `mm` - Memory management tests
- `commands` - Command tests
- `io` - I/O tests
- `ipc` - Inter-process communication tests
- `sched` - Scheduler tests
- `math` - Math library tests
- `nptl` - POSIX thread library tests
- `pty` - Pseudo-terminal tests
- `containers` - Container tests
- `fcntl-locktests` - File locking tests
- `cap_bounds` - Capability bounding tests
- `modules` - Kernel module tests
- `can` - Controller Area Network tests
- `net.ipv6` - IPv6 networking tests
- `crypto` - Cryptographic API tests
- `cve` - CVE regression tests

## Command-Line Options

```
Usage: ./run_ltp_tests.sh [OPTIONS]

OPTIONS:
    -h, --help              Show help message
    -l, --list              List available test suites
    -s, --suite SUITE       Run specific test suite (default: syscalls)
                           Use 'all' to run all suites
    -f, --file FILE         Run custom test file
    -i, --install-only      Only install dependencies and build LTP
    -t, --test-only         Only run tests (skip installation)
    -v, --version VERSION   LTP version to download (default: 20250930)
    --skip-deps            Skip dependency installation
    --ltp-dir DIR          LTP installation directory (default: /opt/ltp)
    --log-file FILE        Output log file (default: auto-generated)
    --fail-on-build-error  Fail if any test fails to compile (default: continue)
```

## Environment Variables

You can also configure the script using environment variables:

- `LTP_VERSION` - LTP version to download (default: 20250930)
- `LTP_INSTALL_DIR` - Installation directory (default: /opt/ltp)
- `LTP_SRC_DIR` - Source directory (default: /opt/ltp-src)
- `LTP_TMP_DIR` - Temporary directory for test output (default: /tmp/ltp)
- `TEST_SUITE` - Test suite to run (default: syscalls)
- `CONTINUE_ON_BUILD_FAIL` - Continue if build fails (default: true)
- `LOG_FILE` - Log file path (default: auto-generated with timestamp)

## Examples

### Install Only (Without Running Tests)

```bash
sudo ./run_ltp_tests.sh --install-only
```

### Run Tests Only (If Already Installed)

```bash
sudo ./run_ltp_tests.sh --test-only --suite commands
```

### Run Multiple Test Suites Sequentially

```bash
sudo ./run_ltp_tests.sh --suite syscalls
sudo ./run_ltp_tests.sh --test-only --suite fs
sudo ./run_ltp_tests.sh --test-only --suite mm
```

### Use Specific LTP Version

```bash
sudo ./run_ltp_tests.sh --version 20231020
```

### Custom Installation Directory

```bash
sudo LTP_INSTALL_DIR=/usr/local/ltp ./run_ltp_tests.sh
```

### Custom Log File

```bash
sudo ./run_ltp_tests.sh --suite syscalls --log-file /var/log/ltp_syscalls.log
```

### Run Custom Test File

```bash
sudo ./run_ltp_tests.sh --file /opt/ltp/runtest/mytest
```

## Detecting Kernel Regressions

The `compare_ltp_results.sh` script compares two LTP test runs to detect regressions. This is useful for validating kernel changes.

### Basic Workflow

```bash
# 1. Run tests before kernel change
sudo ./run_ltp_tests.sh --suite syscalls --log-file before_kernel_change.log

# 2. Apply kernel change (reboot if needed)

# 3. Run tests after kernel change
sudo ./run_ltp_tests.sh --test-only --suite syscalls --log-file after_kernel_change.log

# 4. Compare results
./compare_ltp_results.sh \
    /opt/ltp/results/before_kernel_change.log \
    /opt/ltp/results/after_kernel_change.log
```

### Comparison Output

The comparison script provides:

- **Summary statistics**: Total tests, passed, failed, skipped counts before and after
- **Regressions**: Tests that passed before but failed/skipped after
- **Improvements**: Tests that failed before but passed after
- **New test results**: Tests that ran only in the second run
- **Exit code**: 0 if no regressions, 1 if regressions detected

Example output:

```
================================================================
Summary Statistics
================================================================
Metric               Before      After      Delta
----------------------------------------------------------------
Total Tests            1500       1500          0
Passed                 1450       1440        -10
Failed                    5         15         10
Not Configured           40         40          0
Skipped                   5          5          0
================================================================

================================================================
Regressions (tests that got worse)
================================================================

Tests that PASSED before but FAILED/SKIPPED after:
----------------------------------------------------------------
  ✗ read02: PASS -> FAIL
  ✗ write03: PASS -> FAIL
  ...

================================================================
Final Verdict
================================================================
REGRESSION DETECTED: 10 test(s) got worse
WARNING: Total failures increased by 10
```

### Integration into CI/CD

The comparison script returns an appropriate exit code, making it easy to integrate into automated testing:

```bash
#!/bin/bash
# Example CI script

# Run baseline tests
sudo ./run_ltp_tests.sh --suite syscalls --log-file baseline.log

# Apply changes
apply_kernel_patch

# Run tests again
sudo ./run_ltp_tests.sh --test-only --suite syscalls --log-file after_patch.log

# Compare and fail if regressions detected
if ! ./compare_ltp_results.sh \
    /opt/ltp/results/baseline.log \
    /opt/ltp/results/after_patch.log; then
    echo "Regressions detected! Build failed."
    exit 1
fi

echo "No regressions. Build passed."
```

### Log File Format

LTP log files use a simple, parseable format:

```
tag=test_name stime=<timestamp> dur=<duration> exit=exited stat=<status> core=no cu=<user_cpu> cs=<sys_cpu>
```

Where `stat` values are:
- `0` = PASS
- `1` = FAIL
- `2` = NOT CONFIGURED (test not built/available)
- `32` = SKIP

This format makes it easy to write custom parsing scripts if needed.

## Installed Dependencies

The script installs the following packages:

**Build Tools:**
- gcc, gcc-c++, make, autoconf, automake, libtool, pkgconfig, bison, flex, m4

**Development Libraries:**
- kernel-devel, glibc-devel, libaio-devel, libacl-devel, libcap-devel
- numactl-devel, openssl-devel, libselinux-devel, libtirpc-devel
- keyutils-libs-devel

**Utilities:**
- git, wget, tar, xz, procps-ng, psmisc, quota

**Networking:**
- iproute, iptables, net-tools

The script also enables the appropriate extra repository and installs EPEL:
- **CentOS 7**: enables the `extras` repo (via `yum`)
- **Rocky/RHEL 8**: enables `powertools` (via `dnf`)
- **Rocky/RHEL 9+**: enables `crb` (via `dnf`)

## Directory Structure

After installation:

- **LTP Source:** `/opt/ltp-src` (or custom `LTP_SRC_DIR`)
- **LTP Installation:** `/opt/ltp` (or custom `LTP_INSTALL_DIR`)
- **Test Suites:** `/opt/ltp/runtest/`
- **Temporary Files:** `/tmp/ltp` (or custom `LTP_TMP_DIR`)
- **Log Files:** Current directory (or custom location)

## Output and Logs

Test results are saved to a log file with a timestamp (e.g., `ltp_test_results_20260109_143022.log`).

The log includes:
- Individual test results (PASS/FAIL/SKIP)
- Test summary statistics
- Detailed error messages for failed tests

## Troubleshooting

### Script Must Run as Root

All operations require root privileges:
```bash
sudo ./run_ltp_tests.sh
```

### Missing Dependencies

If you get build errors, try re-running with fresh dependency installation:
```bash
sudo ./run_ltp_tests.sh --skip-deps
# Then manually install missing packages
sudo dnf install <package-name>   # Rocky/RHEL 8+
sudo yum install <package-name>   # CentOS 7
```

### Build Errors

**Important:** Some LTP tests may fail to compile on certain systems due to conflicts between LTP's internal headers and system headers. This is particularly common with:

- `cve-2017-16939` - Conflicts with `sched_attr` structure on newer glibc
- `cve-2015-3290` - Architecture-specific assembly issues on some systems
- Other CVE tests with system header dependencies

**The script handles this automatically** by continuing the build with `-k` flag (keep going) and installing all successfully compiled tests. This is the default behavior.

If you want the script to fail immediately on any build error instead:
```bash
sudo ./run_ltp_tests.sh --fail-on-build-error
```

Or set the environment variable:
```bash
sudo CONTINUE_ON_BUILD_FAIL=false ./run_ltp_tests.sh
```

The script will report how many tests were successfully compiled and installed.

### Disk Space

LTP source and build requires approximately 1-2 GB of disk space. Ensure `/opt` has sufficient space.

### Test Failures

Some tests may fail during execution due to:
- Kernel configuration differences
- Missing kernel modules
- Security policies (SELinux, etc.)
- Hardware dependencies
- Architecture-specific features

This is normal and expected. Review the log file to understand specific failures.

### Re-downloading LTP

If the source directory exists, the script will prompt before re-downloading. To force a fresh download:
```bash
sudo rm -rf /opt/ltp-src
sudo ./run_ltp_tests.sh
```

## Performance Notes

- **Build Time:** Building LTP typically takes 5-15 minutes depending on system resources
- **Test Time:**
  - Single suite: 5-30 minutes
  - All suites: Several hours to a full day
- The script uses `make -j$(nproc)` for parallel compilation

## Additional Resources

- [LTP Project Homepage](https://linux-test-project.github.io/)
- [LTP GitHub Repository](https://github.com/linux-test-project/ltp)
- [LTP Documentation](https://github.com/linux-test-project/ltp/wiki)

## License

This script is provided as-is. LTP itself is licensed under GPL v2.

## Contributing

Feel free to submit issues or pull requests for improvements.
