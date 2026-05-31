"""Network-free tests for the Open-Meteo weather parsing + labeling."""

from __future__ import annotations

import math

from torontosim.feedback.weather import _parse_openmeteo, weather_label


def test_parse_openmeteo_schema():
    data = {
        "hourly": {
            "time": ["2024-05-29T11:00", "2024-05-29T12:00"],
            "temperature_2m": [12.0, 13.6],
            "precipitation": [0.0, 1.4],
            "snowfall": [0.0, 0.0],
            "wind_speed_10m": [9.0, 11.2],
            "visibility": [24000.0, None],
        }
    }
    df = _parse_openmeteo(data)
    assert list(df.columns) == ["dt", "temp_c", "precip_mm", "snow", "wind_kmh", "visibility_km"]
    assert str(df["dt"].dt.tz) == "UTC"
    assert df["visibility_km"].iloc[0] == 24.0
    assert math.isnan(df["visibility_km"].iloc[1])  # None -> NaN
    assert df["temp_c"].iloc[1] == 13.6


def test_weather_label():
    assert weather_label(snow=2.0, precip_mm=0.0) == "snow"
    assert weather_label(snow=0.0, precip_mm=1.4) == "rain"
    assert weather_label(snow=0.0, precip_mm=0.0) == "clear"
    assert weather_label(snow=float("nan"), precip_mm=float("nan")) == "clear"
