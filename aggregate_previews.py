#!/usr/bin/env python3
"""
Aggregate monthly IMI preview results into a summary table and tiled PNGs.

Usage:
    python aggregate_previews.py <run_prefix_pattern> [--data-dir DIR]

Examples:
    python aggregate_previews.py "05-Egypt-2025-01" "16-Egypt-2025-12"
    python aggregate_previews.py "17-Egypt-2025-01-Clustering400" "28-Egypt-2025-12-Clustering400"

The script expects runs named sequentially with a 2-digit prefix.
It takes the first and last run name, finds all runs in between.
"""

import os
import sys
import re
import glob
import yaml
from PIL import Image

# Load configuration
with open('settings.yml', 'r') as f:
    config = yaml.safe_load(f)

DATA_DIR = config['paths']['local_data']


def parse_diagnostics(path):
    """Extract key metrics from preview_diagnostics.txt"""
    metrics = {}
    with open(path) as f:
        text = f.read()

    m = re.search(r"=\s*\$([\d.]+)\s+for spot instance", text)
    if m:
        metrics["spot_cost"] = float(m.group(1))

    m = re.search(r"=\s*\$([\d.]+)\s+for on-demand instance", text)
    if m:
        metrics["ondemand_cost"] = float(m.group(1))

    m = re.search(r"Total prior emissions in region of interest\s*=\s*([\d.]+)\s*Tg/y", text)
    if m:
        metrics["prior_emissions_tgy"] = float(m.group(1))

    m = re.search(r"Found\s+([\d.]+)\s+observations", text)
    if m:
        metrics["observations"] = float(m.group(1))

    m = re.search(r"expectedDOFS:\s*([\d.]+)", text)
    if m:
        metrics["expected_dofs"] = float(m.group(1))

    return metrics


def tile_images(image_paths, labels, output_path, cols=4):
    """Tile images into a grid with labels."""
    images = []
    for p in image_paths:
        if os.path.exists(p):
            images.append(Image.open(p))
        else:
            images.append(None)

    # Use first available image for dimensions
    ref = next((img for img in images if img is not None), None)
    if ref is None:
        return

    w, h = ref.size
    rows = (len(images) + cols - 1) // cols

    # Space for labels
    label_h = 30
    tile_h = h + label_h

    canvas = Image.new("RGB", (cols * w, rows * tile_h), (255, 255, 255))

    # We need ImageDraw for labels
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except (OSError, IOError):
        font = ImageFont.load_default()

    for i, (img, label) in enumerate(zip(images, labels)):
        col = i % cols
        row = i // cols
        x = col * w
        y = row * tile_h

        # Draw label
        draw.text((x + 10, y + 5), label, fill=(0, 0, 0), font=font)

        # Paste image
        if img is not None:
            # Resize if dimensions don't match
            if img.size != (w, h):
                img = img.resize((w, h), Image.LANCZOS)
            canvas.paste(img, (x, y + label_h))

    canvas.save(output_path)


def main():
    if len(sys.argv) < 3:
        print("Usage: aggregate_previews.py <first_run> <last_run> [--data-dir DIR]")
        sys.exit(1)

    first_run = sys.argv[1]
    last_run = sys.argv[2]

    data_dir = DATA_DIR
    for i, arg in enumerate(sys.argv):
        if arg == "--data-dir" and i + 1 < len(sys.argv):
            data_dir = sys.argv[i + 1]

    # Extract numeric prefixes
    first_num = int(re.match(r"(\d+)", first_run).group(1))
    last_num = int(re.match(r"(\d+)", last_run).group(1))

    # Find all matching runs
    runs = []
    for entry in sorted(os.listdir(data_dir)):
        m = re.match(r"(\d+)", entry)
        if m and first_num <= int(m.group(1)) <= last_num:
            runs.append(entry)
    runs.sort(key=lambda x: int(re.match(r"(\d+)", x).group(1)))

    if not runs:
        print(f"No runs found between {first_run} and {last_run}")
        sys.exit(1)

    print(f"Found {len(runs)} runs: {runs[0]} ... {runs[-1]}")

    # Create output directory
    out_dir = os.path.join(data_dir, f"Aggregate from runs {first_run} to {last_run}")
    os.makedirs(out_dir, exist_ok=True)

    # Collect diagnostics
    table_rows = []
    for run in runs:
        diag_path = os.path.join(data_dir, run, "preview", "preview_diagnostics.txt")
        if os.path.exists(diag_path):
            metrics = parse_diagnostics(diag_path)
            table_rows.append((run, metrics))
        else:
            print(f"  WARNING: no diagnostics for {run}")
            table_rows.append((run, {}))

    # Build table data
    headers = ["Run", "Prior Emissions (Tg/y)", "Expected DOFS", "Observations",
               "Spot Cost ($)", "On-Demand Cost ($)"]
    keys = ["prior_emissions_tgy", "expected_dofs", "observations", "spot_cost", "ondemand_cost"]
    formats = [".4f", ".2f", ".0f", ".2f", ".2f"]

    rows = []
    totals = {k: 0 for k in keys}
    for run, m in table_rows:
        row = [run]
        for key, fmt in zip(keys, formats):
            if key in m:
                row.append(f"{m[key]:{fmt}}")
                totals[key] += m[key]
            else:
                row.append("")
        rows.append(row)

    total_row = ["TOTAL"] + [f"{totals[k]:{fmt}}" for k, fmt in zip(keys, formats)]
    n = len([r for _, r in table_rows if r])
    avg_row = ["AVERAGE"] + [f"{totals[k]/n:{fmt}}" if n else "" for k, fmt in zip(keys, formats)]

    # Write CSV
    table_path = os.path.join(out_dir, "summary.csv")
    with open(table_path, "w") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(row) + "\n")
        f.write(",".join(total_row) + "\n")
        f.write(",".join(avg_row) + "\n")
    print(f"Summary CSV written to {table_path}")

    # Write formatted markdown table
    md_path = os.path.join(out_dir, "summary.md")
    all_rows = rows + [total_row, avg_row]
    col_widths = [max(len(headers[i]), *(len(r[i]) for r in all_rows)) for i in range(len(headers))]

    with open(md_path, "w") as f:
        f.write(f"# Preview Summary: {first_run} to {last_run}\n\n")

        # Header
        f.write("| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |\n")
        f.write("|" + "|".join("-" * (w + 2) for w in col_widths) + "|\n")

        # Data rows
        for row in rows:
            f.write("| " + " | ".join(row[i].rjust(col_widths[i]) if i > 0 else row[i].ljust(col_widths[i])
                    for i in range(len(row))) + " |\n")

        # Separator before totals
        f.write("|" + "|".join("-" * (w + 2) for w in col_widths) + "|\n")

        # Total and average
        for row in [total_row, avg_row]:
            f.write("| " + " | ".join(("**" + row[i] + "**").rjust(col_widths[i] + 4) if i > 0
                    else ("**" + row[i] + "**").ljust(col_widths[i] + 4)
                    for i in range(len(row))) + " |\n")

    print(f"Summary MD  written to {md_path}")

    # Find all PNG names from the first run with a preview dir
    png_names = set()
    for run in runs:
        preview_dir = os.path.join(data_dir, run, "preview")
        if os.path.isdir(preview_dir):
            for f in os.listdir(preview_dir):
                if f.endswith(".png"):
                    png_names.add(f)

    # Tile each PNG type
    for png_name in sorted(png_names):
        image_paths = []
        labels = []
        for run in runs:
            image_paths.append(os.path.join(data_dir, run, "preview", png_name))
            # Extract month label from run name
            m = re.search(r"2025-(\d{2})", run)
            month_label = m.group(1) if m else run
            month_names = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
                          "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
                          "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}
            labels.append(month_names.get(month_label, month_label))

        out_path = os.path.join(out_dir, f"tiled_{png_name}")
        tile_images(image_paths, labels, out_path, cols=4)
        print(f"  Tiled {png_name} -> {out_path}")

    print(f"\nDone! Output in: {out_dir}")


if __name__ == "__main__":
    main()
