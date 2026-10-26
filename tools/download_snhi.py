"""Download the SNHI daily-flow records, one workbook per station, as the website exports them.

The "Datos Históricos" tab of http://snih.hidricosargentina.gob.ar is filled by a JSON
endpoint (`MuestraDatos.aspx/LeerDatosHistoricos`); the only gate is the cookie the
terms-of-use checkbox sets. This asks that endpoint for each station's mean daily flow
and writes it in the layout of the site's Excel export — a title row carrying the
station number, then `Fecha y Hora` / `Caudal Medio Diario [m3/seg]` — so nb01 reads
the result with `read_snhi_files`, unchanged.

    python tools/download_snhi.py                 # every station already in raw/
    python tools/download_snhi.py 1205 2213       # just these

Two things differ from a hand export, both in the export's favour to fix here:
values are written at full precision rather than rounded to two decimals, and a
station is requested over its whole record rather than the date range typed in the
form. Flagged values keep the export's spelling (`4.41 Dudoso`), which the parser
reads as missing, as it always has.

A workbook is replaced only once its download has succeeded, so a failed request
leaves the previous file in place.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

BASE = "http://snih.hidricosargentina.gob.ar"
RAW = Path(__file__).resolve().parents[1] / "data/resources/SNHI_ARG/raw"
NETWORK = 1                 # Red Hidrológica Nacional: site code = 10000 * network + station
DAILY_MEAN_FLOW = 101       # `CMDiario` in the site's parameter table
NO_DATA = -998.999          # `NoDataMin` in the site's own scripts
FLAGS = {"D": "Dudoso", ">": ">", "<": "<", "&": "VNC", "@": "ND", ")": "LDND", "%": "SD", "(": "NC"}
TIMEZONE = "America/Argentina/Buenos_Aires"


def fetch(station: int, until: str, timeout: int = 300) -> list[dict]:
    """The raw measurements of one station's mean daily flow, oldest first."""
    body = {"fechaDesde": "1900-01-01", "fechaHasta": until, "estacion": NETWORK * 10000 + station,
            "codigo": DAILY_MEAN_FLOW, "validados": True}
    request = urllib.request.Request(
        f"{BASE}/MuestraDatos.aspx/LeerDatosHistoricos", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", "Cookie": "ingreso=S"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        answer = json.load(response)["d"]
    if answer.get("RespuestaOK") != "True":
        raise RuntimeError(answer.get("MsgErr") or "request refused")
    return answer.get("Mediciones") or []


def to_table(measurements: list[dict]) -> pd.DataFrame:
    """Measurements as the export lays them out: local timestamp, and value or flagged text."""
    table = pd.DataFrame(measurements)
    millis = table["FechaHora"].str.extract(r"(-?\d+)", expand=False).astype("int64")
    stamps = pd.to_datetime(millis, unit="ms", utc=True).dt.tz_convert(TIMEZONE)

    flag = table["Calificador"].str.strip()
    value = table["Medicion"].astype(float)
    text = value.where(value >= NO_DATA).map(lambda v: "" if pd.isna(v) else v).astype(object)
    flagged = flag != ""
    text[flagged] = [f"{v:.2f} {FLAGS.get(f, f)}" for v, f in zip(value[flagged], flag[flagged], strict=True)]

    return pd.DataFrame({"Fecha y Hora": stamps.dt.strftime("%d/%m/%Y %H:%M"),
                         "Caudal Medio Diario [m3/seg]": text})


def write_workbook(path: Path, station: int, table: pd.DataFrame) -> None:
    """Write the export layout: title row with the station number, then the table."""
    partial = path.with_name(path.stem + ".part.xlsx")
    with pd.ExcelWriter(partial) as writer:
        pd.DataFrame([[f"Datos Historicos - Estacion {station}", None]]).to_excel(
            writer, index=False, header=False, startrow=0)
        table.to_excel(writer, index=False, startrow=1)
    partial.replace(path)


def stations_in(folder: Path) -> list[int]:
    return sorted(int(m.group(1)) for f in folder.glob("*.xlsx")
                  if (m := re.fullmatch(r"Historicos-Estacion (\d+)\.xlsx", f.name)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stations", nargs="*", type=int, help="SNHI station numbers (default: those in --out)")
    parser.add_argument("--out", type=Path, default=RAW, help=f"workbook folder (default: {RAW})")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args()

    stations = args.stations or stations_in(args.out)
    if not stations:
        parser.error(f"no stations given and none found in {args.out}")
    args.out.mkdir(parents=True, exist_ok=True)
    until = date.today().isoformat()

    failed = []
    for i, station in enumerate(stations, 1):
        try:
            measurements = fetch(station, until)
            if not measurements:
                raise RuntimeError("no data returned")
            table = to_table(measurements)
            write_workbook(args.out / f"Historicos-Estacion {station}.xlsx", station, table)
            print(f"[{i}/{len(stations)}] {station}: {len(table)} days, "
                  f"{table['Fecha y Hora'].iloc[0][:10]} – {table['Fecha y Hora'].iloc[-1][:10]}", flush=True)
        except Exception as error:  # one station failing must not stop the batch
            failed.append(station)
            print(f"[{i}/{len(stations)}] {station}: FAILED ({error}); previous file kept", flush=True)
        time.sleep(args.pause)

    if failed:
        print(f"{len(failed)} station(s) failed: {' '.join(map(str, failed))}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
