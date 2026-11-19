#!/usr/bin/env bash
# Build every product and QC level of a release into a build directory, from a clean, committed tree.
# Profilers and fixed series run side by side; per-run durations go to <out>/timings.log.
# Every product gets ooi to advanced (R39); deploymentcorrected only the shallow profilers, the only
# products with deployment corrections so far (R24).
#
#   scripts/build_release.sh [data/build]
#   release-cresst vYYYY.MM.N --from data/build
set -euo pipefail
OUT=${1:-data/build}
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "commit first: products are stamped with git_commit"; exit 1; }
mkdir -p "$OUT"

run() {
    local t=$SECONDS
    "$@"
    echo "$(date +%H:%M) $((SECONDS - t))s $*" >> "$OUT/timings.log"
}

profilers() {
    for level in ooi qartod hitl advanced deploymentcorrected; do
        for s in "oregon_offshore 0 200" "axial_base 0 200" "slope_base 0 200"; do
            read -r site lo hi <<< "$s"
            run regrid-profiler "$site" --grid "$lo" "$hi" 1 --format both --qaqc-filter "$level" --output-dir "$OUT"
        done
    done
    for level in ooi qartod hitl advanced; do
        for s in "oregon_offshore_deep 175 590" "slope_base_deep 150 2900" "axial_base_deep 150 2600"; do
            read -r site lo hi <<< "$s"
            run regrid-profiler "$site" --grid "$lo" "$hi" 1 --format both --qaqc-filter "$level" --output-dir "$OUT"
        done
    done
    for f in "$OUT"/*_profiles_*.zarr; do
        [[ $f == *_binned_* ]] || run bin-dataset "$f" --bin 24 --format both
    done
}

fixed() {
    for level in ooi qartod hitl advanced; do
        for site in slope_base oregon_offshore axial_base \
                    oregon_offshore_seafloor oregon_shelf_seafloor slope_base_seafloor axial_base_seafloor; do
            run fixed-instruments "$site" --format both --qaqc-filter "$level" --output-dir "$OUT"
        done
    done
}

profilers > "$OUT/profilers.log" 2>&1 & p=$!
fixed > "$OUT/fixed.log" 2>&1 & f=$!
wait $p
wait $f
echo "built: $(ls -d "$OUT"/*.zarr | wc -l) zarr products in $OUT"
