import pandas as pd

def update_camels_cl_data(original_file, updated_parquet, output_file):
    """Update CAMELS_CL daily data by combining historical and recent data."""
    original_data = pd.read_csv(original_file, index_col='date', parse_dates=['date'])
    original_data = original_data.reindex(pd.date_range(start=original_data.index.min(), end='2025-12-31', freq='D'))

    # load and pivot updated data
    updated_data = pd.read_parquet(updated_parquet)[['CODIGO ESTACION', 'FECHA', 'Caudal_diario']]
    updated_data["CODIGO ESTACION"] = updated_data["CODIGO ESTACION"].astype(str)
    updated_data = updated_data.drop_duplicates(subset=['FECHA', 'CODIGO ESTACION'], keep='first')
    updated_data = updated_data.pivot(index='FECHA', columns='CODIGO ESTACION', values='Caudal_diario')

    updated_data.index = pd.to_datetime(updated_data.index, format='%d/%m/%Y')
    updated_data = updated_data.sort_index()
    updated_data.index.name = "date"
    updated_data.columns.name = None

    # keep only stations that are in both datasets
    updated_data = updated_data[original_data.columns.intersection(updated_data.columns)]

    # merging
    final_data = original_data.combine_first(updated_data)
    final_data = final_data.round(3)
    final_data.to_csv(output_file, index_label='date')
    return final_data

def update_pmet_data(original_file, updated_cl_file, updated_arg_file, output_file):
    """
    Update PMET data by merging original data with updated Chile and Argentina datasets.
    
    Parameters:
    - original_file: path to original PMET data (1950-2020)
    - updated_cl_file: path to updated Chile data (parquet)
    - updated_arg_file: path to updated Argentina data (csv)
    - output_file: path to save the merged output
    """
    # Load and reindex original data
    original_data = pd.read_csv(original_file, index_col=0)
    original_data.index = pd.to_datetime(original_data.index)
    original_data = original_data.reindex(pd.date_range(start=original_data.index.min(), end='2025-12-31', freq='D'))
    original_data.index.name = "date"

    # Load and pivot updated Chile data
    updated_data_cl = pd.read_parquet(updated_cl_file)[['CODIGO ESTACION', 'FECHA', 'Caudal_diario']]
    updated_data_cl["CODIGO ESTACION"] = ['X' + str(i).zfill(8) for i in updated_data_cl["CODIGO ESTACION"]]
    updated_data_cl = updated_data_cl.drop_duplicates(subset=['FECHA', 'CODIGO ESTACION'], keep='first')
    updated_data_cl = updated_data_cl.pivot(index='FECHA', columns='CODIGO ESTACION', values='Caudal_diario')
    updated_data_cl.index = pd.to_datetime(updated_data_cl.index, format='%d/%m/%Y')
    updated_data_cl = updated_data_cl.sort_index()
    updated_data_cl.index.name = "date"
    updated_data_cl.columns.name = None
    updated_data_cl = updated_data_cl[original_data.columns.intersection(updated_data_cl.columns)]

    # Load updated Argentina data
    updated_data_arg = pd.read_csv(updated_arg_file, index_col="date", parse_dates=['date'])
    updated_data_arg = updated_data_arg[original_data.columns.intersection(updated_data_arg.columns)]

    # Merge and save
    updated_data = pd.concat([updated_data_cl, updated_data_arg], axis=1)
    final_data = original_data.combine_first(updated_data).round(3)
    final_data.to_csv(output_file, index_label='date')
    
    return final_data
