import json
import os
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_core.tools import tool

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# Define the Response Schema
class AgentOutput(BaseModel):
    answer: str = Field(description="The direct answer to the user's question.")

search=GoogleSerperAPIWrapper()

@tool("google_search", description="Search Google for current information.")
def google_search(query: str):
    try:
        results=search.results(query)
        
        organic_results = results.get("organic", [])[:3] # Limit to top 3
        
        parsed_results = []
        for item in organic_results:
            parsed_results.append({
                "title": item.get("title", "No Title"),
                "snippet": item.get("snippet", "No Snippet"),
                "link": item.get("link", "")
            })
        
        # Return a JSON string so the LLM can read the specific details
        return json.dumps(parsed_results)
    except Exception as e:
        return f"Error connecting to search API: {e}"


# Export the list of tools
tools_list=[google_search]