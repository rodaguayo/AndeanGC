"""Parse the raw exports into tidy frames (notebook 01).

One workbook per gauge, in the layout the ANA portal produces: a metadata block
in the first rows, then a year x day table with one column per month. The field
labels vary between exports (accented or not, Spanish or English), so
`extract_metadata` matches on substrings rather than fixed cell positions.

`process_excel_files` is the entry point; it skips workbooks that fail to parse
rather than aborting the batch.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm


def extract_metadata(file_path: Path) -> dict[str, str | int | None]:
    """Extract one gauge's metadata from an ANA Excel file.

    Returns the fields the pipeline needs (name, operator, lat/lon, altitude),
    with `None` for anything the workbook does not carry. Takes a `Path`: the
    file name is reported back in the result.
    """
    # Read the first few rows to get metadata
    df_meta = pd.read_excel(file_path, header=None, nrows=15)
    
    metadata = {}
    
    # Extract metadata from the structured format
    for _, row in df_meta.iterrows():
        if pd.notna(row.iloc[0]):
            key = str(row.iloc[0]).strip()
            
            # Check for value in column 1 or 2
            value = None
            if len(row) > 1 and pd.notna(row.iloc[1]):
                value = str(row.iloc[1]).strip()
            elif len(row) > 2 and pd.notna(row.iloc[2]):
                value = str(row.iloc[2]).strip()
            
            if value:
                metadata[key] = value
    
    # Try to extract specific fields with common variations
    station_name = None
    operator = None
    latitude = None
    longitude = None
    altitude = None
    
    # Look for station name
    for key, value in metadata.items():
        if 'estación' in key.lower() or 'estacion' in key.lower() or 'station' in key.lower():
            station_name = value
        elif 'operador' in key.lower() or 'operator' in key.lower():
            operator = value
        elif 'latitud' in key.lower() or 'latitude' in key.lower() or 'geográficas' in key.lower():
            # Parse coordinates from string like "Latitud: -7.726 / Longitud: -77.665 / Altitud(msnm): 1200"
            coord_parts = value.split('/')
            for part in coord_parts:
                part = part.strip()
                if 'latitud' in part.lower():
                    latitude = part.split(':')[1].strip()
                elif 'longitud' in part.lower():
                    longitude = part.split(':')[1].strip()
                elif 'altitud' in part.lower():
                    altitude = part.split(':')[1].strip()
    
    return {
        'file_path': file_path.name,
        'gauge_name': station_name,
        'operator': operator,
        'gauge_lat': latitude,
        'gauge_lon': longitude,
        'altitude': altitude,
    }
    
def extract_timeseries_data(file_path: Path, metadata: dict) -> pd.Series:
    """Unpivot the year x day x month table into a daily series.

    Named after the gauge in `metadata`, reindexed onto a gap-free daily range
    so missing days are NaN rather than absent. Impossible dates produced by
    the rectangular layout (31 February and friends) are dropped.
    """
    
    # Read the data starting from row 13 (header) with first 31 rows of data
    df = pd.read_excel(file_path, header=13)
    
    # Get year, day, and month columns
    year_col = df.columns[0]  # Año
    day_col = df.columns[1]   # Día
    month_cols = df.columns[2:14]  # Ene through Dic
    
    # Convert to long format
    dates = []
    values = []
    
    for _, row in df.iterrows():
        year = row[year_col]
        day = row[day_col]
        
        # Skip rows with missing year or day
        if pd.isna(year) or pd.isna(day):
            continue
            
        for month_idx, month_col in enumerate(month_cols):
            value = row[month_col]
            
            # Create date (month_idx + 1 because enumerate starts at 0)
            try:
                date = pd.to_datetime(f"{int(year)}-{month_idx + 1:02d}-{int(day):02d}")
                dates.append(date)
                # Use np.nan for missing values instead of skipping
                values.append(value if pd.notna(value) else np.nan)
            except (ValueError, TypeError):
                # Skip invalid dates
                continue
    
    # Create pandas Series with station name
    station_name = metadata.get('gauge_name', 'Unknown')
    series = pd.Series(values, index=dates, name=station_name)
    
    # Fill missing dates with np.nan
    if len(series) > 0:
        full_date_range = pd.date_range(start=series.index.min(), end=series.index.max(), freq='D')
        series = series.reindex(full_date_range, fill_value=np.nan)
    
    return series

def process_excel_files(file_paths: Sequence[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Process multiple Excel files and return metadata and timeseries DataFrames

    Parameters:
    file_paths (list): List of Excel file paths

    Returns:
    tuple: (metadata_df, timeseries_df)
        - metadata_df: one row per station, with a `days_with_data` count
        - timeseries_df: date index, one column per station

    A workbook that raises is reported and skipped, so a single malformed
    export does not lose the rest of the batch.
    """
    
    all_metadata = []
    all_timeseries = []
    
    for file_path in tqdm(file_paths, desc="Processing Excel files"):
        try:
            # Extract metadata
            metadata = extract_metadata(file_path)
            
            # Extract timeseries
            series = extract_timeseries_data(file_path, metadata)
            
            # Add number of days with data to metadata
            metadata['days_with_data'] = series.notna().sum()
            
            all_metadata.append(metadata)
            all_timeseries.append(series)
            
        except Exception as e:  # noqa: BLE001 - one malformed export must not lose the batch
            print(f"Error processing {file_path}: {e}")
            continue
    
    # Create metadata DataFrame
    metadata_df = pd.DataFrame(all_metadata)
    
    # Create timeseries DataFrame by concatenating all series
    if all_timeseries:
        timeseries_df = pd.concat(all_timeseries, axis=1)
        # Sort by date index
        timeseries_df = timeseries_df.sort_index()
    else:
        timeseries_df = pd.DataFrame()
    
    return metadata_df, timeseries_df

def assign_gauge_ids(
    names: Sequence[str],
    registry_path: Path,
    prefix: str,
    zfill: int,
) -> list[str]:
    """Map SENAMHI station names to their permanent gauge ids.

    The ANDREA export carries no station code — every file downloads as
    `DatosSerie(N).xlsx`, where `N` is the browser's collision counter — so the
    ids used to come from the filename and moved whenever the archive was
    re-downloaded (`Condorcerro` was `P00000008` in v10 and `P00000009` in v11).
    `gauge_id` is the join key of the published dataset, so it must not depend on
    how the files arrived.

    The registry is therefore the authority: a two-column CSV
    (`gauge_name,gauge_id`) at the repo root, where it is under version control —
    `data/` is not, so a registry stored beside the raw exports would be absent
    from a fresh clone and every id would be reassigned. A name already in it
    keeps its id forever. A name that is not gets the lowest unused number, and
    the registry is rewritten so the new assignment is a reviewable diff. New
    names are sorted before they are numbered, so the result does not depend on
    the order the workbooks were read.

    Renaming a station upstream reads as a new station here — that is deliberate.
    It surfaces as an added registry row rather than silently rewriting an id that
    a published version already used.
    """
    registry = (
        pd.read_csv(registry_path, dtype=str)
        if registry_path.exists()
        else pd.DataFrame(columns=["gauge_name", "gauge_id"])
    )
    known = dict(zip(registry["gauge_name"], registry["gauge_id"], strict=True))

    new = sorted(set(names) - set(known))
    if new:
        used = {int(i.removeprefix(prefix)) for i in known.values()}
        candidate = 1
        for name in new:
            while candidate in used:
                candidate += 1
            known[name] = f"{prefix}{candidate:0{zfill}d}"
            used.add(candidate)
        (
            pd.DataFrame(sorted(known.items()), columns=["gauge_name", "gauge_id"])
            .to_csv(registry_path, index=False)
        )
        print(f"gauge_id registry: added {len(new)} station(s): {', '.join(new)}")

    return [known[name] for name in names]
