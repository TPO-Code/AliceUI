import datetime

import requests


def get_weather_forecast(city: str) -> str:
    """
    Provides the current weather and a 3-day forecast for a given city.
    First, it geocodes the city to get its latitude and longitude, then fetches the weather data.
    """
    print(f"--- [Alice/Weather-Forecast] --- Getting weather for '{city}'")
    try:
        # Step 1: Geocode the city to get latitude and longitude
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {'name': city, 'count': 1, 'language': 'en', 'format': 'json'}
        geo_res = requests.get(geo_url, params=geo_params, timeout=5)
        geo_res.raise_for_status()
        geo_data = geo_res.json()

        if not geo_data.get('results'):
            return f"Error: Could not find location information for the city '{city}'."

        loc = geo_data['results'][0]
        lat, lon = loc['latitude'], loc['longitude']
        name = loc['name']
        admin1 = loc.get('admin1', '')
        country = loc.get('country', '')
        full_location = f"{name}, {admin1}, {country}".strip(', ')
        print(f"--- [Alice/Weather-Forecast] --- Found coordinates for {full_location}: Lat={lat}, Lon={lon}")

        # Step 2: Get weather data using the coordinates
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,apparent_temperature,weather_code',
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min',
            'forecast_days': 3,
            'timezone': 'auto'
        }
        weather_res = requests.get(weather_url, params=weather_params, timeout=10)
        weather_res.raise_for_status()
        weather_data = weather_res.json()

        # Step 3: Format the output
        current = weather_data['current']
        daily = weather_data['daily']

        report = f"Weather Report for {full_location}:\n"
        report += f"- Current: {current['temperature_2m']}°C (Feels like {current['apparent_temperature']}°C)\n"

        for i in range(len(daily['time'])):
            date = datetime.datetime.fromisoformat(daily['time'][i]).strftime('%A, %b %d')
            max_temp = daily['temperature_2m_max'][i]
            min_temp = daily['temperature_2m_min'][i]
            report += f"- {date}: High of {max_temp}°C, Low of {min_temp}°C\n"

        return report.strip()

    except requests.exceptions.RequestException as e:
        return f"Error: Failed to contact the weather service. Reason: {e}"
    except Exception as e:
        return f"Error: An unexpected error occurred while fetching weather. Reason: {e}"


def get_mapping():
    return {
        "weather.get_forecast": get_weather_forecast,  # Provides a weather forecast for a specified city.
    }