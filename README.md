# Weather CLI

A simple command-line interface (CLI) for fetching weather information. This Python project provides an easy way to query current weather data using a local JSON configuration or online API.

## Project Structure

```
cli.py
weather.py
weather_code.json
pyproject.toml
README.md
```

- `cli.py`: Entry point for the command-line interface.
- `weather.py`: Core logic for retrieving and processing weather data.
- `weather_code.json`: Configuration or sample data file used by the application.
- `pyproject.toml`: Project metadata and dependencies.

## Installation

1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd weather_cli
   ```
2. Create and activate a virtual environment:
   ```bash
   uv venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

Run the CLI script to query weather:

```bash
python cli.py [options]
```

## Development

- Modify `weather.py` for business logic changes.
- Update `cli.py` for command-line parsing or new flags.


