import json
import re
import os
import datetime
from langchain_core.tools import tool

from dotenv import load_dotenv

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import googlemaps
import requests
load_dotenv()

CALENDAR_ID=os.getenv("CALENDAR_ID")

def get_calendar_service():
    SCOPES=['https://www.googleapis.com/auth/calendar']
    SERVICE_ACCOUNT_info=json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
    credentials=Credentials.from_service_account_info(
        info=SERVICE_ACCOUNT_info, scopes=SCOPES)

    service = build('calendar', 'v3', credentials=credentials)
    return service

@tool("list_calendar_events", description="List events from the calendar. You can specify a date (YYYY-MM-DD) to get events for that day, or leave it blank to get upcoming events.")
def list_calendar_events(date: str = None, count: int = 10):
    try:
        google_calendar_service=get_calendar_service()

        if date:
            # Specific Date
            target_date=datetime.datetime.strptime(date, "%Y-%m-%d")
            # Start of day (00:00:00)
            time_min=target_date.isoformat() + 'Z'
            # End of day (23:59:59)
            time_max=(target_date + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)).isoformat() + 'Z'
            header=f"--- EVENTS FOR {date} ---"
        else:
            # Upcoming
            time_min=datetime.datetime.utcnow().isoformat() + 'Z'
            time_max=None
            header="--- UPCOMING EVENTS ---"

        # Call the API to fetch events
        events_result=google_calendar_service.events().list(
            calendarId=CALENDAR_ID, 
            timeMin=time_min,
            timeMax=time_max,
            maxResults=count, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events=events_result.get('items', [])
        
        if not events:
            return f"No events found for {date if date else 'upcoming'}."
            
        # Format the output for LLM
        result_strings=[header]
        for event in events:
            start=event['start'].get('dateTime', event['start'].get('date'))
            end=event['end'].get('dateTime', event['end'].get('date'))
            summary=event.get('summary', 'No Title')
            location=event.get('location', 'No Location')
            result_strings.append(f"• {start}: {summary}, Location: {location}, End: {end}")
            
        return "\n".join(result_strings)
        
    except Exception as e:
        return f"Error fetching events: {e}"

@tool("create_calendar_event", description="Create a new event on the calendar with a title, start time (ISO format), and duration in hours.")
def create_calendar_event(summary: str, start_time: str, location: str, duration_hours: float = 1.0):
    try:
        google_calendar_service=get_calendar_service()
        
        # Convert to datetime object
        start_dt=datetime.datetime.fromisoformat(start_time)
        end_dt=start_dt+datetime.timedelta(hours=duration_hours)
        
        # Construct the event
        event={
            'summary': summary,
            'location': location,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'UTC+8',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'UTC+8',
            },
        }
        # Insert the event though API
        created_event=google_calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return f"Success! Event created: {created_event.get('htmlLink')}"
    except Exception as e:
        return f"Error creating event: {e}"
    
def get_map_service():
    try:
        service=googlemaps.Client(key=os.environ.get("GOOGLE_MAPS_API_KEY"))
    except Exception as e:
        service=None
        print(f"Warning: Google Maps API Key not found. Navigation tool will fail. {e}")
    return service

@tool("find_route_directions", description="Find directions between two locations using Google Maps. Specify origin, destination, travel mode (driving, walking, bicycling, transit), and departure time (now or ISO timestamp).")
def find_route_directions(origin: str, destination: str, travel_mode: str = "transit", departure_time: str = "now"):
    google_map_service=get_map_service()
    if not google_map_service:
        return "Error: Google Maps API Key is missing."

    try:
        # Handle time for departure
        dep_time=datetime.datetime.now()
        if departure_time!="now":
            try:
                dep_time=datetime.datetime.fromisoformat(departure_time)
            except ValueError:
                return f"Error: Invalid date format '{departure_time}'. Use YYYY-MM-DDTHH:MM:SS."

        # Call Directions API to get route
        directions_result=google_map_service.directions(
            origin,
            destination,
            mode=travel_mode,
            departure_time=dep_time
        )

        # filename="direction_api_output_test.json"
    
        # with open(filename, 'w', encoding='utf-8') as f:
        #     json.dump(
        #         directions_result, 
        #         f, 
        #         indent=4,           
        #         ensure_ascii=False,    
        #         default=str           
        #     )
            
        # print(f"Successfully saved route to {filename}")

        if not directions_result:
            return f"No route found from '{origin}' to '{destination}'."

        # Parse the Result for First route only
        route=directions_result[0]

        # The Step from A to B
        path=route['legs'][0]
        
        summary=route.get('summary', 'Route')
        distance=path['distance']['text']
        duration=path['duration']['text']
        start_address=path['start_address']
        end_address=path['end_address']

        # Extract major steps from the path
        steps_summary=[]
        for step in path['steps']:
            # Strip HTML tags from instructions (e.g., <b>Turn Left</b>)
            clean_instruction=re.sub('<[^<]+?>', '', step['html_instructions'])
            steps_summary.append(f"- {clean_instruction} ({step['distance']['text']})")

        # Combine into a readable report
        response = (
            f"**Route Found:** {summary}\n"
            f"**From:** {start_address}\n"
            f"**To:** {end_address}\n"
            f"**Distance:** {distance}\n"
            f"**Duration:** {duration}\n\n"
            f"**Directions:**\n" + "\n".join(steps_summary[:10])
        )
        # Limit to first 10 steps for saving the token
        if len(steps_summary)>10:
            response+=f"\n... (and {len(steps_summary) - 10} more steps)"

        return response

    except Exception as e:
        return f"Error finding directions: {e}"
    
# Call Google Weather API through HTTP
def call_weather_api(location_name: str, days: int):
    google_map_service=get_map_service()

    if not google_map_service:
        return "Error: Google Maps API Key is missing."
    
    # Convert the location name to get latitude & longitude
    geocode_result=google_map_service.geocode(location_name)
    location=geocode_result[0]['geometry']['location']
    lat=location['lat']
    lng=location['lng']
    formatted_address=geocode_result[0]['formatted_address']

    url = "https://weather.googleapis.com/v1/forecast/days:lookup"
    params = {
        "key": os.environ.get("GOOGLE_MAPS_API_KEY"),
        "location.latitude": lat,
        "location.longitude": lng,
        "days": days
    }
    
    # Call the Weather API
    response=requests.get(url, params=params)
    response.raise_for_status()
    return response.json(),formatted_address

@tool("get_daily_forecast", description="Get the daily weather forecast for a specific location using Google Weather API.")
def get_daily_forecast(location_name: str, days: int = 3):
    try:
        data,formatted_address=call_weather_api(location_name, days)

        # Parse the JSON response
        forecasts=data.get('forecastDays', [])
        
        report=[f"--- Weather Forecast for {formatted_address} ---"]
        
        # As there is no api call for focast particular date so we return n days forecast
        for day_data in forecasts:
            date_info=day_data.get('displayDate', {})
            date_str=f"{date_info.get('year')}-{date_info.get('month')}-{date_info.get('day')}"
            
            # Extract Weather Condition
            day_forecast=day_data.get('daytimeForecast', {})
            day_condition=day_forecast.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
            
            # Extract Temperature
            max_temp=day_data.get('maxTemperature', {}).get('degrees', 'N/A')
            min_temp=day_data.get('minTemperature', {}).get('degrees', 'N/A')
            
            # Extract Rain Chance which isPrecipitation Probability
            day_precip_data=day_forecast.get('precipitation', {})
            day_rain_chance=day_precip_data.get('probability', {}).get('percent', 0)
            
            night_forecast=day_data.get('nighttimeForecast', {})
            night_condition=night_forecast.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
            night_precip_data=night_forecast.get('precipitation', {})
            night_rain_chance=night_precip_data.get('probability', {}).get('percent', 0)

            report.append(
                f"• {date_str} |"
                f"Daytime: {day_condition} | "
                f"Nighttime: {night_condition} | "
                f"High: {max_temp}°C, Low: {min_temp}°C | "
                f"Rain Chance (Daytime): {day_rain_chance}% | "
                f"Rain Chance (Nighttime): {night_rain_chance}%"
            )

        return "\n".join(report)

    except Exception as e:
        return f"Error fetching forecast: {e}"

# Export the list of tools
tools_list=[list_calendar_events,create_calendar_event,get_daily_forecast,find_route_directions]

# if __name__ == "__main__":
    # print(list_calendar_events("2025-12-03",5))
    # print(create_calendar_event("LunchTime","2025-12-03T10:00:00",2))
    # print(find_route_directions("Hoi Lai Estate","The Hong Kong University of Science and Technology","transit","2025-12-03T08:00:00"))
    # print(get_daily_forecast("Hong Kong",2))