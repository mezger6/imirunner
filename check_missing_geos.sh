#!/bin/bash
# adjust region and dates
MET_DIR="/home/ubuntu/ExtData/GEOS_0.25x0.3125_ME/GEOS_FP"
missing=0

date="20241201"
end="20260102"

while [[ "$date" < "$end" ]]; do
    yyyy=${date:0:4}
    mm=${date:4:2}
    for type in A1 A3cld A3dyn A3mstC A3mstE I3; do
        f="${MET_DIR}/${yyyy}/${mm}/GEOSFP.${date}.${type}.025x03125.ME.nc"
        if [[ ! -f "$f" ]]; then
            echo "MISSING: $f"
            ((missing++))
        fi
    done
    date=$(date -d "${yyyy}-${mm}-${date:6:2} + 1 day" +%Y%m%d)
done

# Also check BC for Jan 1 2026
bc="/home/ubuntu/ExtData/BoundaryConditions/v2025-06-blended/GEOSChem.BoundaryConditions.20260101_0000z.nc4"
[[ ! -f "$bc" ]] && echo "MISSING: $bc" && ((missing++))

if [[ $missing -eq 0 ]]; then
    echo "All files present (20241201–20260101)"
else
    echo "$missing file(s) missing"
fi