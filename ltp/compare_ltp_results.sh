#!/bin/bash
#
# Compare two LTP test result logs
# Usage: ./compare_ltp_results.sh <before.log> <after.log>
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <before.log> <after.log>"
    echo ""
    echo "Compare LTP test results between two runs to detect regressions"
    echo ""
    echo "Example:"
    echo "  $0 /opt/ltp/results/before_kernel_change.log /opt/ltp/results/after_kernel_change.log"
    exit 1
fi

BEFORE_LOG="$1"
AFTER_LOG="$2"

if [[ ! -f "$BEFORE_LOG" ]]; then
    echo "Error: Before log not found: $BEFORE_LOG"
    exit 1
fi

if [[ ! -f "$AFTER_LOG" ]]; then
    echo "Error: After log not found: $AFTER_LOG"
    exit 1
fi

# Extract statistics from a log file
get_stats() {
    local logfile="$1"
    local total=$(grep -c "^tag=" "$logfile" 2>/dev/null || echo "0")
    local passed=$(grep -c "stat=0 " "$logfile" 2>/dev/null || echo "0")
    local failed=$(grep -c "stat=1 " "$logfile" 2>/dev/null || echo "0")
    local tconf=$(grep -c "stat=2 " "$logfile" 2>/dev/null || echo "0")
    local skipped=$(grep -c "stat=32 " "$logfile" 2>/dev/null || echo "0")

    echo "$total $passed $failed $tconf $skipped"
}

# Get test results by name
extract_test_results() {
    local logfile="$1"
    grep "^tag=" "$logfile" | sed 's/tag=\([^ ]*\).*stat=\([^ ]*\).*/\1:\2/' | sort
}

echo "================================================================"
echo "LTP Test Results Comparison"
echo "================================================================"
echo ""
echo "Before: $BEFORE_LOG"
echo "After:  $AFTER_LOG"
echo ""

# Get statistics
read -r before_total before_passed before_failed before_tconf before_skipped <<< $(get_stats "$BEFORE_LOG")
read -r after_total after_passed after_failed after_tconf after_skipped <<< $(get_stats "$AFTER_LOG")

# Display summary
echo "================================================================"
echo "Summary Statistics"
echo "================================================================"
printf "%-20s %10s %10s %10s\n" "Metric" "Before" "After" "Delta"
echo "----------------------------------------------------------------"
printf "%-20s %10d %10d %10d\n" "Total Tests" "$before_total" "$after_total" "$((after_total - before_total))"
printf "%-20s %10d %10d %10d\n" "Passed" "$before_passed" "$after_passed" "$((after_passed - before_passed))"
printf "%-20s %10d %10d %10d\n" "Failed" "$before_failed" "$after_failed" "$((after_failed - before_failed))"
printf "%-20s %10d %10d %10d\n" "Not Configured" "$before_tconf" "$after_tconf" "$((after_tconf - before_tconf))"
printf "%-20s %10d %10d %10d\n" "Skipped" "$before_skipped" "$after_skipped" "$((after_skipped - before_skipped))"
echo "================================================================"
echo ""

# Extract individual test results
TEMP_DIR=$(mktemp -d)
extract_test_results "$BEFORE_LOG" > "$TEMP_DIR/before.txt"
extract_test_results "$AFTER_LOG" > "$TEMP_DIR/after.txt"

# Find regressions (tests that passed before but failed/skipped after)
echo "================================================================"
echo "Regressions (tests that got worse)"
echo "================================================================"

# Tests that passed before but failed after
regressions=$(comm -23 \
    <(grep ":0$" "$TEMP_DIR/before.txt" | cut -d: -f1) \
    <(grep ":0$" "$TEMP_DIR/after.txt" | cut -d: -f1))

regression_count=0
if [[ -n "$regressions" ]]; then
    echo ""
    echo -e "${RED}Tests that PASSED before but FAILED/SKIPPED after:${NC}"
    echo "----------------------------------------------------------------"
    for test in $regressions; do
        before_stat=$(grep "^${test}:" "$TEMP_DIR/before.txt" | cut -d: -f2)
        after_stat=$(grep "^${test}:" "$TEMP_DIR/after.txt" | cut -d: -f2 || echo "MISSING")

        case "$after_stat" in
            0) status="PASS" ;;
            1) status="FAIL" ;;
            2) status="TCONF" ;;
            32) status="SKIP" ;;
            MISSING) status="NOT RUN" ;;
            *) status="UNKNOWN($after_stat)" ;;
        esac

        echo -e "  ${RED}✗${NC} $test: PASS -> $status"
        ((regression_count++))
    done
else
    echo -e "${GREEN}No regressions found!${NC}"
fi

echo ""

# Find improvements (tests that failed before but passed after)
echo "================================================================"
echo "Improvements (tests that got better)"
echo "================================================================"

improvements=$(comm -13 \
    <(grep ":0$" "$TEMP_DIR/before.txt" | cut -d: -f1) \
    <(grep ":0$" "$TEMP_DIR/after.txt" | cut -d: -f1))

improvement_count=0
if [[ -n "$improvements" ]]; then
    echo ""
    echo -e "${GREEN}Tests that FAILED/SKIPPED before but PASSED after:${NC}"
    echo "----------------------------------------------------------------"
    for test in $improvements; do
        before_stat=$(grep "^${test}:" "$TEMP_DIR/before.txt" | cut -d: -f2 || echo "MISSING")

        case "$before_stat" in
            0) status="PASS" ;;
            1) status="FAIL" ;;
            2) status="TCONF" ;;
            32) status="SKIP" ;;
            MISSING) status="NOT RUN" ;;
            *) status="UNKNOWN($before_stat)" ;;
        esac

        echo -e "  ${GREEN}✓${NC} $test: $status -> PASS"
        ((improvement_count++))
    done
else
    echo "No improvements found."
fi

echo ""

# Find new failures (tests that failed after but didn't run before)
new_fails=$(comm -13 \
    <(cut -d: -f1 "$TEMP_DIR/before.txt") \
    <(grep -v ":0$" "$TEMP_DIR/after.txt" | cut -d: -f1))

new_fail_count=0
if [[ -n "$new_fails" ]]; then
    echo "================================================================"
    echo "New Test Failures (didn't run before)"
    echo "================================================================"
    for test in $new_fails; do
        after_stat=$(grep "^${test}:" "$TEMP_DIR/after.txt" | cut -d: -f2)
        case "$after_stat" in
            1) status="FAIL" ;;
            2) status="TCONF" ;;
            32) status="SKIP" ;;
            *) status="UNKNOWN($after_stat)" ;;
        esac
        echo -e "  ${YELLOW}!${NC} $test: NEW -> $status"
        ((new_fail_count++))
    done
    echo ""
fi

# Cleanup
rm -rf "$TEMP_DIR"

# Final verdict
echo "================================================================"
echo "Final Verdict"
echo "================================================================"

exit_code=0

if [[ $regression_count -gt 0 ]]; then
    echo -e "${RED}REGRESSION DETECTED:${NC} $regression_count test(s) got worse"
    exit_code=1
else
    echo -e "${GREEN}NO REGRESSIONS:${NC} No tests got worse"
fi

if [[ $improvement_count -gt 0 ]]; then
    echo -e "${GREEN}IMPROVEMENTS:${NC} $improvement_count test(s) got better"
fi

if [[ $new_fail_count -gt 0 ]]; then
    echo -e "${YELLOW}NEW TESTS:${NC} $new_fail_count new test(s) with issues"
fi

# Check if failure count increased
failed_delta=$((after_failed - before_failed))
if [[ $failed_delta -gt 0 ]]; then
    echo -e "${RED}WARNING:${NC} Total failures increased by $failed_delta"
    exit_code=1
elif [[ $failed_delta -lt 0 ]]; then
    echo -e "${GREEN}GOOD:${NC} Total failures decreased by ${failed_delta#-}"
fi

echo ""
echo "Exit code: $exit_code (0=no regressions, 1=regressions detected)"
echo "================================================================"

exit $exit_code
