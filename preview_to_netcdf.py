#!/usr/bin/env python3
"""
preview_to_netcdf.py
--------------------
Post-processing script that re-uses IMI preview functions to produce two
NetCDF files from a completed IMI preview run, without modifying any IMI code.

Outputs (written to the preview/ subdirectory of the run):
  preview_model_fields.nc       -- prior emissions, state vector labels, and
                                   estimated averaging kernel sensitivities,
                                   all on the cropped inversion-domain grid
  preview_observation_fields.nc -- TROPOMI XCH4, SWIR albedo, and observation
                                   counts binned to 0.1 x 0.1 degree grid

Usage:
  python preview_to_netcdf.py --config /path/to/config.yml \
                               --imi-path /path/to/integrated_methane_inversion

The run output directory is derived from OutputPath + RunName in the config,
matching exactly how IMI constructs it internally.
"""

import argparse
import datetime
import os
import sys

import numpy as np
import xarray as xr
import yaml


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config",   required=True,
                   help="Path to the IMI config.yml used for the run")
    p.add_argument("--imi-path", required=True,
                   help="Root of the integrated_methane_inversion repo "
                        "(directory that contains run_imi.sh)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    config = yaml.load(open(config_path), Loader=yaml.FullLoader)
    # Expand any shell variables (IMI does the same at runtime)
    for k, v in config.items():
        if isinstance(v, str):
            config[k] = os.path.expandvars(v)
    return config


def derive_run_dirs(config: dict) -> dict:
    """Return the canonical IMI directory paths for a given config."""
    run_name   = config["RunName"]
    output_dir = config["OutputPath"]
    run_dirs   = os.path.join(output_dir, run_name)
    return {
        "run_dirs":       run_dirs,
        "preview_dir":    os.path.join(run_dirs, "preview"),
        "tropomi_cache":  os.path.join(run_dirs, "satellite_data"),
        "state_vector":   os.path.join(run_dirs, "StateVector.nc"),
    }


def clip_to_sv_grid(da_global: xr.DataArray,
                    sv: xr.Dataset) -> xr.DataArray:
    """
    Clip a global DataArray to the lat/lon extent of the state vector grid.

    The HEMCO standalone runs on the global domain, so `prior` comes back
    with global coordinates, while StateVector.nc is cropped to the inversion
    domain + buffer.  We select the matching grid cells by nearest-neighbour
    so that both variables share identical coordinate arrays and can safely
    be combined in one xr.Dataset.
    """
    return da_global.sel(
        lat=sv["StateVector"].lat,
        lon=sv["StateVector"].lon,
        method="nearest",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # ------------------------------------------------------------------
    # 1. Bootstrap: add IMI to sys.path so we can import its modules
    # ------------------------------------------------------------------
    imi_path = os.path.abspath(args.imi_path)
    if imi_path not in sys.path:
        sys.path.insert(0, imi_path)

    # Now we can import from the IMI source tree
    from src.inversion_scripts.imi_preview import (
        estimate_averaging_kernel,
        map_sensitivities_to_sv,
    )

    # ------------------------------------------------------------------
    # 2. Load config and derive paths
    # ------------------------------------------------------------------
    config_path = os.path.abspath(args.config)
    config      = load_config(config_path)
    paths       = derive_run_dirs(config)

    preview_dir   = paths["preview_dir"]
    tropomi_cache = paths["tropomi_cache"]
    sv_path       = paths["state_vector"]

    for label, path in [("preview_dir",   preview_dir),
                         ("tropomi_cache", tropomi_cache),
                         ("StateVector",   sv_path)]:
        if not os.path.exists(path):
            sys.exit(f"ERROR: {label} not found: {path}\n"
                     f"  Has the IMI preview completed successfully?")

    print(f"Run:          {config['RunName']}")
    print(f"Preview dir:  {preview_dir}")
    print(f"State vector: {sv_path}")
    print(f"TROPOMI data: {tropomi_cache}")
    print()

    # ------------------------------------------------------------------
    # 3. Re-run the preview computation (no plotting, just data)
    #    estimate_averaging_kernel with preview=True returns:
    #      a            -- 1-D array of per-element averaging kernel sensitivities
    #      df           -- DataFrame of individual TROPOMI observations (lat, lon,
    #                      xch4, swir_albedo) already filtered and in the domain
    #      num_days     -- length of inversion period in days
    #      prior        -- xr.DataArray of mean prior emissions (global grid, Tg/y)
    #      outstrings   -- diagnostic text (already written to preview_diagnostics.txt)
    # ------------------------------------------------------------------
    print("Re-running preview computation (no plots)...")
    a, df, num_days, prior, _ = estimate_averaging_kernel(
        config,
        sv_path,
        preview_dir,
        tropomi_cache,
        preview=True,
        kf_index=None,
    )

    # ------------------------------------------------------------------
    # 4. Load state vector and derive ROI mask
    # ------------------------------------------------------------------
    state_vector        = xr.load_dataset(sv_path)
    state_vector_labels = state_vector["StateVector"]
    last_ROI_element    = int(
        np.nanmax(state_vector_labels.values) - config["nBufferClusters"]
    )

    # ------------------------------------------------------------------
    # 5. Map per-element sensitivities back to the 2-D grid
    # ------------------------------------------------------------------
    sensitivities_da = map_sensitivities_to_sv(a, state_vector, last_ROI_element)

    # ------------------------------------------------------------------
    # 6. Convert prior to kg km-2 h-1 and clip to inversion domain
    #    prior is on the GLOBAL HEMCO grid; state_vector_labels is on the
    #    CROPPED inversion-domain grid.  We must clip before combining.
    # ------------------------------------------------------------------
    prior_kgkm2h        = prior * (1000 ** 2) * 3600          # Tg/y → kg km-2 h-1
    prior_kgkm2h_domain = clip_to_sv_grid(prior_kgkm2h, state_vector)

    # ------------------------------------------------------------------
    # 7. Build model-grid NetCDF
    # ------------------------------------------------------------------
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    model_ds = xr.Dataset(
        data_vars={
            "prior_emissions_kgkm2h": prior_kgkm2h_domain,
            "state_vector":           state_vector_labels,
            "estimated_sensitivity":  sensitivities_da["Sensitivities"],
        }
    )
    model_ds["prior_emissions_kgkm2h"].attrs = {
        "long_name": "Prior methane emissions (mean over inversion period)",
        "units":     "kg km-2 h-1",
        "source":    "HEMCO standalone, clipped to inversion domain",
    }
    model_ds["state_vector"].attrs = {
        "long_name": "State vector element ID (ROI elements 1..N, buffer N+1..N+nBuf)",
        "units":     "1",
    }
    model_ds["estimated_sensitivity"].attrs = {
        "long_name": "Estimated averaging kernel sensitivity (from IMI preview)",
        "units":     "1",
        "note":      "Values > last_ROI_element masked to NaN",
    }
    model_ds.attrs = {
        "title":          "IMI preview fields on inversion-domain model grid",
        "run_name":       config["RunName"],
        "start_date":     str(config["StartDate"]),
        "end_date":       str(config["EndDate"]),
        "num_days":       float(num_days),
        "last_ROI_element": last_ROI_element,
        "n_buffer_clusters": config["nBufferClusters"],
        "created_utc":    now_utc,
        "imi_config":     config_path,
    }

    model_out = os.path.join(preview_dir, "preview_model_fields.nc")
    model_ds.to_netcdf(model_out)
    print(f"Written: {model_out}")

    # ------------------------------------------------------------------
    # 8. Build observation-grid NetCDF (0.1 x 0.1 degree bins)
    #    This replicates the binning done inside imi_preview.py for plots
    # ------------------------------------------------------------------
    import pandas as pd

    df_means = df.copy(deep=True)
    df_means["lat"] = np.round(df_means["lat"], 1)
    df_means["lon"] = np.round(df_means["lon"], 1)
    df_means = df_means.groupby(["lat", "lon"]).mean()
    ds_obs   = df_means.to_xarray()

    df_counts           = df.copy(deep=True).drop(["xch4", "swir_albedo"], axis=1)
    df_counts["counts"] = 1
    df_counts["lat"]    = np.round(df_counts["lat"], 1)
    df_counts["lon"]    = np.round(df_counts["lon"], 1)
    df_counts           = df_counts.groupby(["lat", "lon"]).sum()
    ds_counts           = df_counts.to_xarray()

    obs_ds = xr.Dataset(
        data_vars={
            "xch4":               ds_obs["xch4"],
            "swir_albedo":        ds_obs["swir_albedo"],
            "observation_count":  ds_counts["counts"],
        }
    )
    obs_ds["xch4"].attrs = {
        "long_name": "Mean TROPOMI XCH4 in 0.1 degree bins",
        "units":     "ppb",
        "source":    "Blended TROPOMI+GOSAT" if config["BlendedTROPOMI"]
                     else "TROPOMI operational",
    }
    obs_ds["swir_albedo"].attrs = {
        "long_name": "Mean SWIR albedo in 0.1 degree bins",
        "units":     "1",
    }
    obs_ds["observation_count"].attrs = {
        "long_name": "Number of individual TROPOMI soundings in 0.1 degree bins",
        "units":     "count",
    }
    obs_ds.attrs = {
        "title":       "IMI preview TROPOMI observations binned to 0.1 degree grid",
        "run_name":    config["RunName"],
        "start_date":  str(config["StartDate"]),
        "end_date":    str(config["EndDate"]),
        "num_days":    float(num_days),
        "blended":     str(config["BlendedTROPOMI"]),
        "created_utc": now_utc,
        "imi_config":  config_path,
    }

    obs_out = os.path.join(preview_dir, "preview_observation_fields.nc")
    obs_ds.to_netcdf(obs_out)
    print(f"Written: {obs_out}")

    # ------------------------------------------------------------------
    # 9. Summary
    # ------------------------------------------------------------------
    expected_dofs = np.round(sum(a), 4)
    print()
    print(f"Expected DOFS:        {expected_dofs}")
    print(f"ROI elements:         {last_ROI_element}")
    print(f"Inversion period:     {num_days:.0f} days")
    print(f"Total observations:   {int(df.shape[0])}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
