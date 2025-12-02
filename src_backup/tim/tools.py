import json
import math
import os
import re
import requests
from dotenv import load_dotenv
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from schema import BrowseAction, SearchAction, SearchEntry, Step

load_dotenv()

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_SCRAPE_URL = "https://scrape.serper.dev"
SERPER_ENTRIIES_IN_PAGE = 10


@tool
def submit_answer(content: str, runtime: ToolRuntime):
    """Provide the final answer. Please make sure the answer is as concise as possible, and wrap it in <answer>...</answer> tag,

    Args:
        content: The content to submit as the final answer, e.g. "The singer is <answer>John Doe</answer>"
    """

    match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)
    if not match:
        return 'The answer is not wrapped in <answer>...</answer> tag. Please wrap it in <answer>...</answer> tag, such as "The answer is <answer>...</answer>", then resubmit the answer. If you failed to find the answer after lots of efforts, you can submit the content "<answer>failure</answer>" to admit that you failed to find the answer.'

    answer_text = match.group(1).strip()

    if answer_text.lower() == "failure":
        pass
    elif len(answer_text.split()) > 15:
        return f'The answer inside <answer>...</answer> tags is too long ({len(answer_text.split())} words). It should be a short phrase, entity, date, or name (ideally < 10 words). Please extract only the key information and resubmit. Example: Instead of "<answer>The capital of France is Paris, which is a large city.</answer>", use "The capital is <answer>Paris</answer>".'

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content="The final answer is successfully submitted: " + content,
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "answer": content,
        }
    )

def search_api_call(query: str, max_results: int):
    pages = math.ceil(max_results / SERPER_ENTRIIES_IN_PAGE)
    all_entries = list[SearchEntry]()
    for page in range(1, pages + 1):
        payload = json.dumps({"q": query, "page": page})
        headers = {"X-API-KEY": os.getenv("SERPER_API_KEY"),"Content-Type": "application/json"}
        response = requests.request("POST", SERPER_SEARCH_URL, headers=headers, data=payload)
        limit = (SERPER_ENTRIIES_IN_PAGE if page <= pages else max_results % SERPER_ENTRIIES_IN_PAGE)
        entries = [{"title": entry["title"], "link": entry["link"], "snippet": entry.get("snippet", "(No snippet available)")} for entry in response.json()["organic"][:limit]]
        all_entries.extend(entries)
    return all_entries


@tool
def search(query: str, max_results: int, runtime: ToolRuntime):
    """Search the web for the given query.

    Args:
        query: The query to search the web for.
        max_results: The maximum number of results to return, must be less than or equal to 30.
    """

    if max_results > 30:
        return f"The maximum number of results is 30, but got {max_results}. Please reduce the number of results."

    entries = search_api_call(query, max_results)
    formatted_entries = []
    for entry in entries:
        formatted_entries.append("<Entry>\n"+ f"<Title>{entry["title"]}</Title>\n"+ f"<Link>{entry["link"]}</Link>\n"+ f"<Snippet>{entry["snippet"]}</Snippet>\n"+ "</Entry>\n")
    formatted_entries = f"<Entries>\n{''.join(formatted_entries)}</Entries>\n"

    return Command(
        update={
            "messages": [ToolMessage(content=formatted_entries, tool_call_id=runtime.tool_call_id)],
            "steps": [Step(step_number=runtime.state["current_step"],actions=[SearchAction(action="search", query=query, num_docs_requested=max_results, retrieved_documents=entries)])]
        }
    )


def browse_api_call(url: str):
    payload = json.dumps({"url": url, "includeMarkdown": True})
    headers = {"X-API-KEY": os.getenv("SERPER_API_KEY"),"Content-Type": "application/json"}
    response = requests.request("POST", SERPER_SCRAPE_URL, headers=headers, data=payload)
    try:
        return response.json()["markdown"]
    except Exception:
        return f"Failed to read the content of the URL {url}. Please verify the URL and try again."


@tool
def browse(url: str, runtime: ToolRuntime):
    """Browse the web for the given URL.

    Args:
        url: The URL to browse the web for.
    """
    browsed_content = browse_api_call(url)
    return Command(
        update={"messages": [ToolMessage(content=browsed_content, tool_call_id=runtime.tool_call_id)],
                "steps": [Step(step_number=runtime.state["current_step"],actions=[BrowseAction(action="browse", url=url, browsed_content=browsed_content)])]}
    )


if __name__ == "__main__":
    print(search_api_call("\"He Ain't Heavy He's My Brother\" song information history", 10))
