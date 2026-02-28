import requests
from dataclasses import dataclass
from pathlib import Path
import json
from datetime import datetime
import pandas as pd

geo_coding_url = ("https://geocoding-api.open-meteo.com/v1/search?"
                  "name={location}&count=10&language=en&format=json")

weather_url = ("https://api.open-meteo.com/v1/forecast?"
    "latitude={latitude}&longitude={longitude}&"
    "current=temperature_2m,weather_code,relative_humidity_2m&"
    "forecast_days={days}"
)

air_quality_url = (
    "https://air-quality-api.open-meteo.com/v1/air-quality?"
    "latitude={latitude}&longitude={longitude}&"
    "hourly=pm10,pm2_5,uv_index&"
    "forecast_days={days}"
)

location_details = {
    "petaling": {
        "admin1": "Kuala Lumpur"
    },
    "segamat": {
        "admin1": "Johor"
    }
}

@dataclass
class CurrentWeather:
    temperature: float
    relative_humidity: float
    description: str

class WeatherAPIRequestor:
    @staticmethod
    def make_api_call(url: str) -> dict:
        response = requests.get(url)
        response.raise_for_status()

        return response.json()
    
class HourlyDataAnalyzer:
    def __init__(self, data: dict):
        """
        Args:
            data: the dictionary response from API call"""
        self._data = data

    def display_daily_analysis(self):
        df = pd.DataFrame(self._data)
        # format the date to facilitate groupby operation
        df['time'] = pd.to_datetime(df['time'])
        df['date'] = df['time'].dt.date

        # daily averages
        metrics = ['pm10', 'pm2_5', 'uv_index']
        daily_avg = df.groupby('date')[metrics].mean().round(2)
        daily_avg.index.name = 'Date'
        daily_avg.columns = ['PM10 (µg/m³)', 'PM2.5 (µg/m³)', 'UV Index']
        daily_max = df.groupby('date')[metrics].max().round(2)
        daily_max.index.name = 'Date'
        daily_max.columns = ['PM10 (µg/m³)', 'PM2.5 (µg/m³)', 'UV Index']
        
        print("=" * 50)
        print("       Daily Average Air Quality Metrics")
        print("=" * 50)
        print(daily_avg.to_string())
        print("=" * 50)
        print("=" * 50)
        print("       Daily Max Air Quality Metrics")
        print("=" * 50)
        print(daily_max.to_string())
    
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
    hour = now.hour
    return 6 <= hour < 18

def get_day_or_night() -> str:
    """
    Return 'day' or 'night' based on current local time.
    """
    return "day" if is_daytime() else "night"

def get_coordinate(
    url: str,      # geo-coding url
    location_str: str,
    # state: str   # admin1 
):
    if location_str not in location_details:
        raise KeyError(f"Location {location_str} not available")
    
    data = WeatherAPIRequestor.make_api_call(url.format(location=location_str))
    state = location_details.get(location_str, {}).get("admin1")
    if not state:
        print("error in reading the state from the location dictionary")
        return
    
    location = next((r for r in data["results"] if r.get("admin1") == state), None)
    if location:
        print(f"Timezone: {location.get("timezone")}")
        print(f"location name: {location.get("name")}")
        return (location["latitude"], location["longitude"])
    return None

def get_current_weather(
    weather_url: str,
    latitude: float,
    longitude: float,
    days: int = 3,
    weather_code_filepath: str | Path = "./weather_code.json"
) -> CurrentWeather | None:
    formatted_url = weather_url.format(latitude=latitude, longitude=longitude, days=days)
    response = WeatherAPIRequestor.make_api_call(formatted_url)

    current_data = response.get("current")
    if current_data:
        weather_code_ref = load_json_file(weather_code_filepath)

        weather_code = str(current_data.get("weather_code"))
        print(f"weather code: {weather_code}")

        desc = weather_code
        if weather_code_ref and weather_code in weather_code_ref:
            desc = weather_code_ref[weather_code].get(get_day_or_night(), {}).get("description")

        current_weather = CurrentWeather(
            temperature=current_data.get("temperature_2m"),
            relative_humidity=current_data.get("relative_humidity_2m"),
            description=desc
        )
        return current_weather
    return None

def get_air_quality_metrics(
    air_quality_url: str,
    latitude: str,
    longitude: str,
    days: int = 3
):
    formatted_url = air_quality_url.format(latitude=latitude, longitude=longitude, days=days)
    response = WeatherAPIRequestor.make_api_call(formatted_url)

    hourly_forecast = response.get("hourly")
    return hourly_forecast if hourly_forecast else None  # dict with "time iso8601 utc", "pm10", "pm2_5", "uv_index"

if __name__ == "__main__":
    # location_resp = WeatherAPIRequestor.make_api_call(geo_coding_url)
    # print(type(location_resp))
    coordinate = get_coordinate(
        url=geo_coding_url,
        location_str="petaling"
    )

    if coordinate:
        current_weather = get_current_weather(
            weather_url=weather_url,
            latitude=coordinate[0],
            longitude=coordinate[1]
        )
        if current_weather:
            print(f"Temperature: {current_weather.temperature}")
            print(f"relative humidity: {current_weather.relative_humidity}")
            print(f"weather code: {current_weather.description}")

        air_quality_json = get_air_quality_metrics(
            air_quality_url=air_quality_url,
            latitude=coordinate[0],
            longitude=coordinate[1]
        )

        # print(air_quality_json)

        if air_quality_json:
            analyzer = HourlyDataAnalyzer(data=air_quality_json)
            analyzer.display_daily_analysis()
