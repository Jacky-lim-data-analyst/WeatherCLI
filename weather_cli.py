import argparse
import requests
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import sys

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

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
location_details = {
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

# --- Data class -------------------------
@dataclass
class CurrentWeather:
    temperature: float
    relative_humidity: float
    description: str

# --- Helpers ---------------
class WeatherAPIRequestor:
    @staticmethod
    def make_api_call(url: str) -> dict:
        response = requests.get(url)
        response.raise_for_status()

        return response.json()
    
def load_json_file(filepath: str | Path) -> dict:
    """
    Load a JSON file and return its contents as a Python dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        TypeError: If the top-level JSON object is not a dictionary.
    """
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise TypeError("JSON root element is not a dictionary")

    return data
    
def is_daytime() -> bool:
    """
    Return True if current local time is between 06:00 (inclusive)
    and 18:00 (exclusive). Otherwise return False.
    """
    now = datetime.now().astimezone()
    return 6 <= now.hour < 18

def get_day_or_night() -> str:
    """
    Return 'day' or 'night' based on current local time.
    """
    return "day" if is_daytime() else "night"

def get_coordinate(
    url: str,      # geo-coding url
    location_str: str,
):
    location_str = location_str.lower()
    if location_str not in location_details:
        raise KeyError(
            f"Location {location_str} not available"
            f"Available: {', '.join(location_details)}"
        )
    
    data = WeatherAPIRequestor.make_api_call(url.format(location=location_str))
    state = location_details.get(location_str, {}).get("admin1")
    if not state:
        print("error in reading the state from the location dictionary")
        return
    
    location = next((r for r in data["results"] if r.get("admin1") == state), None)
    if location:
        return (
            location.get("latitude"),
            location.get("longitude"),
            location.get("name", location_str),
            location.get("timezone", "")
        )
    return None

def get_current_weather(
    weather_url: str,
    latitude: float,
    longitude: float,
    weather_code_filepath: str | Path = "./weather_code.json"
) -> CurrentWeather | None:
    formatted_url = weather_url.format(latitude=latitude, longitude=longitude)
    response = WeatherAPIRequestor.make_api_call(formatted_url)

    current_data = response.get("current")
    if not current_data:
        return None
    
    desc = str(current_data.get("weather_code"))
    try:
        weather_code_ref = load_json_file(weather_code_filepath)

        desc = (
            weather_code_ref[desc]
            .get(get_day_or_night(), {})
            .get("description", desc)
        )

    except (TypeError, FileNotFoundError):
        pass  # fallback to raw code

    return CurrentWeather(
        temperature=current_data.get("temperature_2m"),
        relative_humidity=current_data.get("relative_humidity_2m"),
        description=desc
    )

def get_air_quality_metrics(
    air_quality_url: str,
    latitude: str,
    longitude: str,
    days: int = 3
) -> dict | None:
    formatted_url = air_quality_url.format(latitude=latitude, longitude=longitude, days=days)
    response = WeatherAPIRequestor.make_api_call(formatted_url)

    return response.get("hourly")  # dict with "time iso8601 utc", "pm10", "pm2_5", "uv_index"

# ---- Rich display helpers -------------------------
def _pm10_color(value: float) -> str:
    if value <= 20: return "green"
    if value <= 40: return "yellow"
    if value <= 55: return "dark_orange"
    if value <= 150: return "red"
    return "bright_red"

def _pm25_color(value: float) -> str:
    if value <= 10:   return "green"
    if value <= 20:   return "yellow"
    if value <= 25:   return "dark_orange"
    if value <= 50:   return "red"
    return "bright_red"

def _uv_color(v: float) -> str:
    if v < 3:   return "green"
    if v < 6:   return "yellow"
    if v < 8:   return "dark_orange"
    if v < 11:  return "red"
    return "bright_red"

def _uv_label(v: float) -> str:
    if v < 3:   return "Low"
    if v < 6:   return "Moderate"
    if v < 8:   return "High"
    if v < 11:  return "Very High"
    return "Extreme"

def display_current_weather(weather: CurrentWeather, location_name: str, timezone: str):
    icon = "☀️" if is_daytime() else "🌙"
    temp_color = (
        "cyan" if weather.temperature < 25
        else "yellow" if weather.temperature < 35
        else "red"
    )

    # rebuild as Text for proper markup
    t = Text()
    t.append(f"{icon}  ")
    t.append(weather.description, style="bold white")
    t.append("\n\n")
    t.append("🌡  Temperature   ")
    t.append(f"{weather.temperature} °C\n", style=f"bold {temp_color}")
    t.append("💧 Humidity       ")
    t.append(f"{weather.relative_humidity} %", style="bold cyan")

    title = f"[bold]{location_name}[/bold]  [dim]{timezone}[/dim]"
    console.print(Panel(t, title=title, border_style="bright_blue", padding=(1, 2)))

def display_air_quality(data: dict, stat: str = "avg"):
    """Display daily average or max air quality as a rich table."""
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"])
    df["date"] = df["time"].dt.date

    metrics = ["pm10", "pm2_5", "uv_index"]
    if stat == "max":
        daily = df.groupby("date")[metrics].max().round(2)
        title = "Daily [bold]Max[/bold] Air Quality"
    else:
        daily = df.groupby("date")[metrics].mean().round(2)
        title = "Daily [bold]Average[/bold] Air Quality"

    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=True
    )
    table.add_column("Date", style="dim", justify="center")
    table.add_column("PM10 (µg/m³)", justify="right")
    table.add_column("PM2.5 (µg/m³)", justify="right")
    table.add_column("UV Index", justify="right")

    for date, row in daily.iterrows():
        pm10_val = row["pm10"]
        pm25_val = row["pm2_5"]
        uv_val = row["uv_index"]
        table.add_row(
            str(date),
            Text(f"{pm10_val}", style=f"bold {_pm10_color(pm10_val)}"),
            Text(f"{pm25_val}", style=f"bold {_pm25_color(pm25_val)}"),
            Text(
                f"{uv_val}  [{_uv_label(uv_val)}]",
                style=f"bold {_uv_color(uv_val)}",
            ),
        )

    console.print(table)

def display_legend():
    legend = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    legend.add_column(justify="left")
    legend.add_column(justify="left")

    legend.add_row("[bold]Air Quality Thresholds[/bold]", "")
    legend.add_row(
        "[green]●[/green] Good",
        "[yellow]●[/yellow] Moderate",
    )
    legend.add_row(
        "[dark_orange]●[/dark_orange] Unhealthy (sensitive)",
        "[red]●[/red] Unhealthy",
    )
    legend.add_row("[bright_red]●[/bright_red] Very Unhealthy / Hazardous", "")
    console.print(legend)

# --- CLI ------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weather",
        description="Fetch current weather and air quality for a location"
    )
    parser.add_argument(
        "location",
        nargs="?",  # zero or one argument (positional argument)
        default="petaling",
        help=f"Location key. Available: {', '.join(location_details)}. (default: petaling)"
    )

    parser.add_argument(
        "--days",
        type=int,
        default=3,
        metavar="N",  # display name in help message instead of days
        help="Forecast window in day (default: 3)",
    )

    parser.add_argument(
        "--stat",
        choices=["avg", "max", "both"],
        default="both",
        help="Air quality statistics to display: avg, max or both (default: both)",
    )
    parser.add_argument(
        "--weather-only",
        action="store_true",
        help="Show only current weather, skip air quality"
    )
    parser.add_argument(
        "--air-only",
        action="store_true",
        help="Show only air quality metrics, skip current weather"
    )
    parser.add_argument(
        "--weather-codes",
        default="./weather_code.json",
        metavar="FILE",
        help="Path to weather_code.json (default: './weather_code.json')"
    )
    parser.add_argument(
        "--list-locations",
        action="store_true",
        help="List all available location keys and exit"
    )
    return parser

def main():
    """Example usage: 
    # Basic - defaults to "petaling", 3-day window
python weather_cli.py

# Pick a location
python weather_cli.py segamat

# Show 5-day forecast, only average air quality
python weather_cli.py petaling --days 5 --stat avg

# Current weather only (no air quality fetch)
python weather_cli.py --weather-only

# Air quality only
python weather_cli.py --air-only --stat max

# See all registered locations
python weather_cli.py --list-locations"""
    parser = build_parser()
    args = parser.parse_args()

    if args.list_locations:
        console.print("[bold cyan]Available locations:[/bold cyan]")
        for key, meta in location_details.items():
            console.print(f"  [green]{key}[/green] → {meta['admin1']}")
        return
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console
    ) as progress:
        task = progress.add_task("Fetching coordinates...", total=None)

        try:
            result = get_coordinate(geo_coding_url, args.location)
        except KeyError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            sys.exit(1)

        if not result:
            console.print(
                f"[bold red]Error:[/bold red] Could not find coordinates for '{args.location}'."
            )
            sys.exit(1)

        lat, lon, loc_name, timezone = result
        console.print()

        # ---- current weather ----
        if not args.air_only:
            progress.update(task, description="Fecthing current weather...")
            weather = get_current_weather(
                weather_url, lat, lon,
                weather_code_filepath=args.weather_codes
            )
            progress.stop()
            if weather:
                display_current_weather(weather, loc_name, timezone)
            else:
                console.print("[yellow]Warning:[/yellow] Could not retrieve current weather data.")

        else:
            progress.stop()

        # --- Air quality -----
        if not args.weather_only:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
                console=console
            ) as p2:
                p2.add_task("Fetching air quality...", total=None)
                aq_data = get_air_quality_metrics(air_quality_url, lat, lon, days=args.days)

            if aq_data:
                console.print()
                if args.stat in ("avg", "both"):
                    display_air_quality(aq_data, stat="avg")
                if args.stat in ("max", "both"):
                    console.print()
                    display_air_quality(aq_data, stat="max")
                console.print()
                display_legend()
            else:
                console.print("[yellow]Warning:[/yellow] Could not retrieve air quality data.")

if __name__ == "__main__":
    main()
