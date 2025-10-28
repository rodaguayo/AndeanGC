import pandas as pd
import numpy as np
from tqdm import tqdm

def extract_metadata(file_path):
    """Extract metadata from ANA Excel file"""
    # Read the first few rows to get metadata
    df_meta = pd.read_excel(file_path, header=None, nrows=15)
    
    metadata = {}
    
    # Extract metadata from the structured format
    for idx, row in df_meta.iterrows():
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
    
def extract_timeseries_data(file_path, metadata):
    """Extract time series data from ANA Excel file and return as pandas Series"""
    
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

def process_excel_files(file_paths):
    """
    Process multiple Excel files and return metadata and timeseries DataFrames
    
    Parameters:
    file_paths (list): List of Excel file paths
    
    Returns:
    tuple: (metadata_df, timeseries_df)
        - metadata_df: DataFrame with metadata for all stations
        - timeseries_df: DataFrame with date index and station columns
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
            
        except Exception as e:
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