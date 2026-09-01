#!/bin/bash

set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/base-test.sh"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/power/BAT0" "$tmp_dir/power/BAT1"
printf 'Battery\n' >"$tmp_dir/power/BAT0/type"
printf 'Battery\n' >"$tmp_dir/power/BAT1/type"

if OMARCHY_POWER_SUPPLY_PATH="$tmp_dir/power" "$ROOT/bin/omarchy-battery-charge-limit" >/dev/null 2>&1; then
  fail "charge-limit command rejects unsupported hardware"
fi
pass "charge-limit command rejects unsupported hardware"

printf '80\n' >"$tmp_dir/power/BAT0/charge_control_end_threshold"
actual=$(OMARCHY_POWER_SUPPLY_PATH="$tmp_dir/power" "$ROOT/bin/omarchy-battery-charge-limit")
[[ $actual == "80" ]] || fail "charge-limit command reads the current limit" "actual: $actual"
pass "charge-limit command reads the current limit"

for invalid in 49 101 nope 80.5; do
  if OMARCHY_POWER_SUPPLY_PATH="$tmp_dir/power" "$ROOT/bin/omarchy-battery-charge-limit" "$invalid" >/dev/null 2>&1; then
    fail "charge-limit command rejects invalid value: $invalid"
  fi
done
pass "charge-limit command validates the requested percentage before elevation"

# Source the fixed-target writer so a sysfs-shaped fixture can exercise the
# privileged half without invoking sudo or polkit from the test suite.
source "$ROOT/bin/omarchy-battery-charge-limit"
POWER_SUPPLY_PATH="$tmp_dir/power"

printf '85\n' >"$tmp_dir/power/BAT0/charge_control_start_threshold"
printf '90\n' >"$tmp_dir/power/BAT1/charge_control_end_threshold"
printf '75\n' >"$tmp_dir/power/BAT1/charge_control_start_threshold"

actual=$(write_limit 80)
[[ $actual == "80" ]] || fail "charge-limit writer returns the accepted threshold" "actual: $actual"
[[ $(<"$tmp_dir/power/BAT0/charge_control_end_threshold") == "80" ]] || fail "charge-limit writer updates BAT0"
[[ $(<"$tmp_dir/power/BAT1/charge_control_end_threshold") == "80" ]] || fail "charge-limit writer updates BAT1"
[[ $(<"$tmp_dir/power/BAT0/charge_control_start_threshold") == "75" ]] || fail "charge-limit writer keeps the start threshold below the new limit"
[[ $(<"$tmp_dir/power/BAT1/charge_control_start_threshold") == "75" ]] || fail "charge-limit writer preserves an already valid start threshold"
pass "charge-limit writer safely updates every supported battery"
