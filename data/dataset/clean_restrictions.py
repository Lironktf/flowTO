"""
Step 1 — Clean v3.csv into a well-formed CSV that cuDF can read.

v3.csv has two problems cuDF's CSV reader can't handle:
  1. A title row ("Current road restrictions") above the real header.
  2. ~22 rows with unescaped quotes/commas inside embedded JSON columns
     (Signing / Notification / PermitType), which break field alignment.

The stdlib csv reader parses the well-formed rows correctly, so we use it to
pull only the columns we need and drop the malformed rows. StartTime/EndTime
are left as raw epoch-millisecond integers — converted in the cuDF stage.
"""
import csv

KEEP = [
    "ID", "Road", "Name", "District", "RoadClass", "Planned",
    "Latitude", "Longitude", "StartTime", "EndTime",
    "MaxImpact", "CurrImpact", "Type", "SubType",
    "DirectionsAffected", "WorkEventType", "Signing",
]

def main():
    rows = list(csv.reader(open("v3.csv")))
    hdr = rows[1]                                  # row 0 is the title banner
    ix = {h: i for i, h in enumerate(hdr)}
    kept = dropped = 0
    with open("restrictions_clean.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(KEEP)
        for r in rows[2:]:
            if len(r) < 41:                        # malformed → skip
                dropped += 1
                continue
            try:
                int(r[ix["StartTime"]]); int(r[ix["EndTime"]])
                float(r[ix["Latitude"]]); float(r[ix["Longitude"]])
            except ValueError:
                dropped += 1
                continue
            w.writerow([r[ix[k]] for k in KEEP])
            kept += 1
    print(f"restrictions_clean.csv written: {kept} kept, {dropped} dropped")

if __name__ == "__main__":
    main()
