"""TorontoSim data pipeline (P01).

Reproducible ingest: fetch raw Toronto open data + transit GTFS + weather,
normalize to (Geo)Parquet + a DuckDB catalog, and record raw-file lineage in a
manifest. One CLI: ``python -m torontosim.datapipeline {fetch,bake,verify}``.

All City of Toronto datasets are licensed under the Open Government Licence –
Toronto; Metrolinx GTFS under OGL – Ontario. See ``manifest.ATTRIBUTION``.
"""

from __future__ import annotations

__all__ = ["ckan", "restrictions", "gtfs", "weather", "bake", "manifest"]
