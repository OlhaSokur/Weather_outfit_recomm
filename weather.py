import datetime as dt
import json
import requests
import re
from flask import Flask, jsonify, request, render_template
from openai import OpenAI
from collections import OrderedDict

API_WEATHER_TOKEN = "######"
WEATHER_API_KEY = "######"
OPENROUTER_API_KEY = "#######"

app = Flask(__name__)


class InvalidUsage(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv["message"] = self.message
        return rv


def get_weather(location, date=None):
    base_url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
    if date:
        url = f"{base_url}/{location}/{date}"
    else:
        url = f"{base_url}/{location}"

    params = {
        "unitGroup": "metric",
        "key": WEATHER_API_KEY,
        "contentType": "json"
    }

    response = requests.get(url, params=params)
    if response.status_code != requests.codes.ok:
        raise InvalidUsage(response.text, status_code=response.status_code)

    weather_data = response.json()

    if not date:
        return weather_data.get("currentConditions", {}), False, weather_data

    try:
        given_date = dt.datetime.strptime(date, "%Y-%m-%d").date()

        if given_date < dt.date.today():
            raise InvalidUsage(f"Cannot show weather for past dates: {date}", status_code=400)
    except ValueError:
        raise InvalidUsage(f"Invalid date format: {date}. Use YYYY-MM-DD format.", status_code=400)

    for day in weather_data.get("days", []):
        if day.get("datetime") == date:
            return day, True, weather_data

    raise InvalidUsage(f"No forecast available for the givenn date: {date}", status_code=404)


def get_weather_info(weather_data, full_weather_data, forecast):
    temp = weather_data.get("temp", 0)
    condition = weather_data.get("conditions", "unknown")
    precip = weather_data.get("precip", 0)
    humidity = weather_data.get("humidity", 0)
    wind_speed = weather_data.get("windspeed", 0)

    location = full_weather_data.get("resolvedAddress", "unknown location")
    date_str = weather_data.get("datetime", "forecast date") if forecast else "current weather"

    return (f"{'Forecasted' if forecast else 'Current'} weather for {date_str} in {location}: "
            f"Temperature: {temp}°C, Conditions: {condition}, "
            f"Precipitation: {precip}mm, Humidity: {humidity}%, Wind speed: {wind_speed} km/h.")


def get_outfit_recommendations(weather_data, forecast=False, full_weather_data=None):
    weather_info = get_weather_info(weather_data, full_weather_data, forecast)

    prompt = f"Based on this weather information: {weather_info}\n"
    prompt += "Please provide outfit recommendations for this weather. Include suggestions for:"
    prompt += "\n1. Top clothing (shirt, sweater, etc.)"
    prompt += "\n2. Bottom clothing (pants, skirt, etc.)"
    prompt += "\n3. Outerwear (jacket, coat, etc. if needed)"
    prompt += "\n4. Footwear"
    prompt += "\n5. Accessories (umbrella, hat, scarf, etc. if needed)"
    prompt += "\nFormat as a JSON object with these categories as keys and recommendations as values."
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    completion = client.chat.completions.create(
        model="deepseek/deepseek-chat:free",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    recommendation_text = completion.choices[0].message.content

    json_match = re.search(r'```json\n(.*?)\n```', recommendation_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    return {"text": recommendation_text}


def get_activity_recommendations(weather_data, forecast=False, full_weather_data=None):
    weather_info = get_weather_info(weather_data, full_weather_data, forecast)

    prompt = (f"Based on this weather information: {weather_info}\n"
              "Please recommend activities or places to visit (like parks, museums, outdoor events) based on the weather conditions. "
              "Make suggestions for:\n"
              "1. Places like parks or exhibitions for this specific weather conditions.\n"
              "Format as a JSON object with these categories as keys and recommendations as values.")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    completion = client.chat.completions.create(
        model="deepseek/deepseek-chat:free",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    recommendation_text = completion.choices[0].message.content

    json_match = re.search(r'```json\n(.*?)\n```', recommendation_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    return {"text": recommendation_text}


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


@app.route("/")
def home_page():
    return "<p><h2>KMA L2 Weather API.</h2></p>"


@app.route("/weather/api/v1/current", methods=["POST"])
def current_weather_endpoint():
    request_time = dt.datetime.utcnow()
    json_data = request.get_json()

    if json_data.get("token") is None:
        raise InvalidUsage("token is required", status_code=400)

    if json_data["token"] != API_WEATHER_TOKEN:
        raise InvalidUsage("wrong API token", status_code=403)

    if json_data.get("location") is None:
        raise InvalidUsage("location is required", status_code=400)

    location = json_data["location"]
    date = json_data.get("date")
    include_outfit = json_data.get("include_outfit", False)
    include_activities = json_data.get("include_activities", False)

    try:
        weather_data, forecast, full_weather_data = get_weather(location, date)

        formatted_weather = {
            "temp_c": weather_data.get("temp"),
            "wind_kph": weather_data.get("windspeed"),
            "pressure_mb": weather_data.get("pressure"),
            "humidity": weather_data.get("humidity"),
            "conditions": weather_data.get("conditions", "Unknown"),
            "precipitation_mm": weather_data.get("precip", 0),
            "cloud_cover": weather_data.get("cloudcover"),
            "visibility_km": weather_data.get("visibility")
        }

        outfit_recommendations = get_outfit_recommendations(
            weather_data, forecast=forecast, full_weather_data=full_weather_data
        ) if include_outfit else None

        activity_recommendations = get_activity_recommendations(
            weather_data, forecast=forecast, full_weather_data=full_weather_data
        ) if include_activities else None

    except Exception as e:
        raise InvalidUsage(f"Failed to get weather data: {str(e)}", status_code=500)

    result_data = {
        "requester_name": json_data.get("requester_name", "Unknown"),
        "timestamp": request_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "location": location,
        "date": date if date else request_time.strftime("%Y-%m-%d"),
        "weather": formatted_weather
    }

    if include_activities:
        result_data["activity_recommendations"] = activity_recommendations

    if include_outfit:
        result_data["outfit_recommendations"] = outfit_recommendations


    return jsonify(result_data)
