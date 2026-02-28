"""
Weather MCP server
======
Expose 3 tools via FastMCP:
* get_coordinate  - resolve a location key to lat/lon
* get_current_weather  - fetch current weather conditions
* get_air_quality - fetch hourly PM10, PM2.5 and uv index

Run (stdio transport, default)

Run (SSE transport for remote clients)"""

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Annotated

import requests
from fastmcp import FastMCP

# --- URL --------------------------
geo_coding_url = ("https://geocoding-api.open-meteo.com/v1/search?"
                  "name={location}&count=10&language=en&format=json")

weather_url = ("https://api.open-meteo.com/v1/forecast?"
    "latitude={latitude}&longitude={longitude}&"
    "current=temperature_2m,weather_code,relative_humidity_2m&"
)

air_quality_url = (
    "https://air-quality-api.open-meteo.com/v1/air-quality?"
    "latitude={latitude}&longitude={longitude}&"
    "hourly=pm10,pm2_5,uv_index&"
    "forecast_days={days}"
)

# ---- Location registry ----------------------
location_details: dict[str, dict] = {
    "petaling": {
        "admin1": "Kuala Lumpur"
    },
    "segamat": {
        "admin1": "Johor"
    },
    "kampar": {
        "admin1": "Perak"
    }
}

# --- Internal helpers ----
@dataclass
class _CoordinateResult:
    latitude: float
    longitude: float
    name: str
    timezone: str
    admin1: str

@dataclass
class CurrentWeather:
    temperature: float
    relative_humidity: float
    weather_code: int
    description: str

def _api_get(url: str) -> dict:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _is_daytime() -> bool:
    """
    Return True if current local time is between 06:00 (inclusive)
    and 18:00 (exclusive). Otherwise return False.
    """
    now = datetime.now().astimezone()
    return 6 <= now.hour < 18

def _load_weather_codes(filepath: str | Path) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return data if isinstance(data, dict) else {}

# ---- MCP server --------
mcp = FastMCP(
    name="WeatherServer",
    instructions=(
        "Provides weather and air quality data for registered Malaysian locations. "
        "Call get_coordinate first to obtain lat/lon, then pass those values to "
        "get_current_weather and/or get_air_quality."
    ),
)

@mcp.tool(
    description=(
        "Resolve a location key to geographic coordinates. "
        f"Available location keys: {', '.join(location_details)}. "
        "Returns latitude, longitude, place name, timezone, and state (admin1)."
    )
)
def get_coordinate(
    location: Annotated[str, "Location key, e.g. 'petaling', 'segamat', 'kampar'"],
) -> dict:
    """Resolve a location key to lat/lon and metadata."""
    location = location.strip().lower()
    if location not in location_details:
        raise ValueError(
            f"Unknown location '{location}'. "
            f"Available: {', '.join(location_details)}"
        )

    state = location_details[location]["admin1"]
    data = _api_get(geo_coding_url.format(location=location))
    results = data.get("results", [])

    match = next((r for r in results if r.get("admin1") == state), None)
    if not match:
        raise RuntimeError(
            f"Geocoding API returned no results for '{location}' in {state}."
        )
    
    return asdict(
        _CoordinateResult(
            latitude=match["latitude"],
            longitude=match["longitude"],
            name=match.get("name", location),
            timezone=match.get("timezone", ""),
            admin1=state
        )
    )

@mcp.tool(
    description=(
        "Fetch current weather conditions (temperature, humidity, description) "
        "for the given coordinates. Optionally specify a forecast window (days) "
        "and a path to a weather_code.json mapping file."
    )
)
def get_current_weather(
    latitude: Annotated[float, "Latitude obtained from get_coordinate"],
    longitude: Annotated[float, "Longitude obtained from get_coordinate"],
    weather_code_filepath: Annotated[
        str, "Path to a WMO weather-code JSON mapping file"
    ] = "./weather_code.json"
) -> dict:
    """Return current temperature, humidity and weather description"""
    url = weather_url.format(latitude=latitude, longitude=longitude)
    response = _api_get(url)

    current = response.get("current")
    if not current:
        raise RuntimeError("Weather API did not return 'current' data")
    
    code = current.get("weather_code")
    code_str = str(code)
    desc = code_str

    codes = _load_weather_codes(weather_code_filepath)
    if codes and code_str in codes:
        period = "day" if _is_daytime() else "night"
        desc = codes[code_str].get(period, {}).get("description", code_str)

    return asdict(
        CurrentWeather(
            temperature=current.get("temperature_2m"),
            relative_humidity=current.get("relative_humidity_2m"),
            weather_code=code,
            description=desc,
        )
    )

@mcp.tool(
    description=(
        "Fetch hourly air quality forecast (PM10, PM2.5, UV index) "
        "for the given coordinates over a number of days. "
        "Returns a dict with keys 'time', 'pm10', 'pm2_5', 'uv_index', "
        "each being a list of values aligned by index."
    )
)
def get_air_quality(
    latitude: Annotated[float, "Latitude obtained from get_coordinate"],
    longitude: Annotated[float, "Longitude obtained from get_coordinate"],
    days: Annotated[int, "Forecast windows in days (1, 3, 5 and 7)"] = 3,
) -> dict:
    """Returns hourly PM10, PM2.5 and UV index forecasts"""
    if not (1 <= days <= 7):
        raise ValueError("days must be between 1 and 7 for air quality forecast")
    
    url = air_quality_url.format(latitude=latitude, longitude=longitude, days=days)
    response = _api_get(url)

    hourly = response.get("hourly")
    if not hourly:
        raise RuntimeError("AIR quality api did not return 'hourly' data")
    
    return {
        "time": hourly.get("time", []),
        "pm10": hourly.get("pm10", []),
        "pm2_5": hourly.get("pm2_5", []),
        "uv_index": hourly.get("uv_index", [])
    }

# ----- Entry point ----
def _parse_args():
    """
    # stdio (for Claude Desktop / local MCP clients)
python weather_mcp.py

# SSE (for remote/HTTP clients)
python weather_mcp.py --transport http --port 8000"""
    parser = argparse.ArgumentParser(description="Weather MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4567,
        help="Port for http transport (default: 4567)"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = _parse_args()
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()
