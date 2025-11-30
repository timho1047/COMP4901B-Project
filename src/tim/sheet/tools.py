import json
import math
import os
import re
from pathlib import Path
from typing import Literal

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from schema import (
    BrowseAction,
    Cell,
    CreateSheetAction,
    DeleteSheetAction,
    ListSheetsAction,
    ReadSheetAction,
    SearchAction,
    SearchEntry,
    Step,
    UpdateCellAction,
    WriteTodoAction,
)
from utils import format_todo_xml, get_grid_coords, hex_to_rgb_dict, rgb_to_hex

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
GOOGLE_CREDENTIAL_FILE = (PROJECT_ROOT / os.getenv("GOOGLE_CREDENTIAL_FILE")).as_posix()

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_SCRAPE_URL = "https://scrape.serper.dev"
SERPER_ENTRIIES_IN_PAGE = 10


creds = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDENTIAL_FILE,
    scopes=[
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
)

drive_service = build("drive", "v3", credentials=creds)
sheets_service = build("sheets", "v4", credentials=creds)


def read_sheet_impl(spreadsheet_id, range_name="Sheet1!A1:Z100"):
    try:
        sheet = sheets_service.spreadsheets()

        # 1. Get Values (Formatted)
        result_values = (
            sheet.values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
        values_data = result_values.get("values", [])

        # 2. Get Formulas
        result_formulas = (
            sheet.values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueRenderOption="FORMULA",
            )
            .execute()
        )
        formulas_data = result_formulas.get("values", [])

        # 3. Get Formatting & Merges
        result_format = sheet.get(
            spreadsheetId=spreadsheet_id, ranges=[range_name], includeGridData=True
        ).execute()

        if not values_data:
            return "No data found in the sheet."

        sheet_data = result_format["sheets"][0]
        row_data = sheet_data["data"][0].get("rowData", [])
        merges = sheet_data.get("merges", [])

        # Process Merges
        merge_map = {}
        for merge in merges:
            start_row = merge["startRowIndex"]
            end_row = merge["endRowIndex"]
            start_col = merge["startColumnIndex"]
            end_col = merge["endColumnIndex"]

            rows_spanned = end_row - start_row
            cols_spanned = end_col - start_col

            merge_map[(start_row, start_col)] = f"merged:{rows_spanned}x{cols_spanned}"

            for r in range(start_row, end_row):
                for c in range(start_col, end_col):
                    if r == start_row and c == start_col:
                        continue
                    merge_map[(r, c)] = "covered_by_merge"

        # Determine max columns
        max_cols = max(len(row) for row in values_data)

        # Generate column headers (A, B, C...)
        col_headers = []
        for i in range(max_cols):
            header = ""
            temp = i
            while temp >= 0:
                header = chr(ord("A") + (temp % 26)) + header
                temp = (temp // 26) - 1
            col_headers.append(header)

        # Start building Markdown table
        md_lines = []
        header_row = "| Index | " + " | ".join(col_headers) + " |"
        md_lines.append(header_row)
        sep_row = "| :--- | " + " | ".join([":---:" for _ in range(max_cols)]) + " |"
        md_lines.append(sep_row)

        # Merge Data
        for r_idx, val_row in enumerate(values_data):
            merged_row = []
            formula_row = formulas_data[r_idx] if r_idx < len(formulas_data) else []
            fmt_row_values = (
                row_data[r_idx].get("values", []) if r_idx < len(row_data) else []
            )

            for c_idx in range(max_cols):
                val = val_row[c_idx] if c_idx < len(val_row) else ""
                formula = formula_row[c_idx] if c_idx < len(formula_row) else ""

                format_tags = []

                # Check Merge Status
                merge_status = merge_map.get((r_idx, c_idx))
                if merge_status:
                    if merge_status == "covered_by_merge":
                        merged_row.append("{covered}")
                        continue
                    else:
                        format_tags.append(merge_status)

                # Extract Format info
                if c_idx < len(fmt_row_values):
                    cell_format = fmt_row_values[c_idx].get("userEnteredFormat", {})
                    text_format = cell_format.get("textFormat", {})
                    bg_color_dict = cell_format.get("backgroundColor", {})
                    borders = cell_format.get("borders", {})

                    # Borders
                    if borders.get("top"):
                        format_tags.append("border-top")
                    if borders.get("bottom"):
                        format_tags.append("border-bottom")
                    if borders.get("left"):
                        format_tags.append("border-left")
                    if borders.get("right"):
                        format_tags.append("border-right")

                    # Horizontal Alignment
                    h_align = cell_format.get("horizontalAlignment")
                    if h_align:
                        format_tags.append(f"align:{h_align}")

                    if text_format.get("bold"):
                        format_tags.append("bold")
                    if text_format.get("italic"):
                        format_tags.append("italic")
                    if text_format.get("strikethrough"):
                        format_tags.append("strikethrough")

                    # Background Color
                    is_bg_empty = not bg_color_dict
                    if not is_bg_empty:
                        bg_r = bg_color_dict.get("red", 0.0)
                        bg_g = bg_color_dict.get("green", 0.0)
                        bg_b = bg_color_dict.get("blue", 0.0)
                        if (
                            abs(bg_r - 1.0) > 0.01
                            or abs(bg_g - 1.0) > 0.01
                            or abs(bg_b - 1.0) > 0.01
                        ):
                            hex_bg = rgb_to_hex(bg_color_dict, default_val=0.0)
                            format_tags.append(f"bg:{hex_bg}")

                    # Text Color
                    fg_color_dict = text_format.get("foregroundColor", {})
                    is_fg_empty = not fg_color_dict
                    if not is_fg_empty:
                        fg_r = fg_color_dict.get("red", 0.0)
                        fg_g = fg_color_dict.get("green", 0.0)
                        fg_b = fg_color_dict.get("blue", 0.0)
                        if fg_r > 0.01 or fg_g > 0.01 or fg_b > 0.01:
                            hex_fg = rgb_to_hex(fg_color_dict, default_val=0.0)
                            format_tags.append(f"text:{hex_fg}")

                cell_content = str(val)

                if str(formula).startswith("="):
                    cell_content += f" [{formula}]"

                if format_tags:
                    cell_content += f" {{{','.join(format_tags)}}}"

                safe_content = cell_content.replace("|", "\\|").replace("\n", " ")
                merged_row.append(safe_content)

            row_str = f"| {r_idx + 1} | " + " | ".join(merged_row) + " |"
            md_lines.append(row_str)

        return "\n".join(md_lines)

    except Exception as e:
        return f"Error reading sheet: {str(e)}"


@tool
def read_sheet(runtime: ToolRuntime, sheet: str):
    """
    Reads a Google Sheet and returns a markdown representation.

    Args:
        sheet: The sheet to read, e.g., "Sheet1".

    Returns:
        A string containing a Markdown table representing the sheet content.

    ### Output Format Explanation
    The output is a standard Markdown table with row indices (1, 2, 3...) and column headers (A, B, C...).
    Each cell contains the **Display Value** followed by optional metadata tags in `[]` or `{}`.

    #### 1. Values & Formulas
    - **Standard Value:** Just the text/number (e.g., `Total`, `150`).
    - **Formulas:** If a cell contains a formula, it is shown in square brackets after the value.
      - Example: `500 [=SUM(A1:A5)]`
      - Meaning: The cell displays "500", but the underlying formula is `=SUM(A1:A5)`.

    #### 2. Formatting Tags `{...}`
    Visual styling is enclosed in curly braces `{}`. Multiple tags are comma-separated.

    - **Text Style:** `bold`, `italic`, `strikethrough`.
      - Example: `Important {bold,italic}`

    - **Alignment:** `align:LEFT`, `align:CENTER`, `align:RIGHT`.
      - Example: `Title {align:CENTER}`

    - **Colors:**
      - `bg:#RRGGBB`: Background color (only shown if NOT white).
      - `text:#RRGGBB`: Text color (only shown if NOT black).
      - Example: `Warning {text:#ff0000,bg:#ffff00}` (Red text on Yellow background).

    - **Borders:** `border-top`, `border-bottom`, `border-left`, `border-right`.
      - Example: `Total {border-top}` (Indicates a line above the cell).

    #### 3. Merged Cells
    - **Top-Left Cell:** The content of a merged group is always in the top-left cell, tagged with `merged:RowsxCols`.
      - Example: `Quarterly Report {merged:1x4}`
      - Meaning: This cell spans 1 row and 4 columns (it covers the 3 cells to its right).

    - **Covered Cells:** Cells hidden by a merge are marked with `{covered}`.
      - Example: `| Title {merged:1x2} | {covered} |`
      - Meaning: The second cell is part of the "Title" cell.
    """

    spreadsheet_id = runtime.config["configurable"]["spreadsheet_id"]
    sheet_content = read_sheet_impl(spreadsheet_id, f"{sheet}!A1:Z100")
    
    if "#DIV/0!" in sheet_content:
        sheet_content += "\n\n<system_reminder>There is a division by zero error (#DIV/0!) in the sheet. Please check the formulas and fix them if it is not intended.</system_reminder>"
    
    return Command(
        update={
            "messages": [
                ToolMessage(content=sheet_content, tool_call_id=runtime.tool_call_id)
            ],
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[
                        ReadSheetAction(
                            action="read_sheet",
                            sheet=sheet,
                            sheet_content=sheet_content,
                        )
                    ],
                    reasoning=[],
                )
            ],
        }
    )


def update_cell_impl(spreadsheet_id, cell_updates):
    """
    Updates multiple cells' content and formatting. Replaces existing data.

    Args:
        spreadsheet_id: The ID of the spreadsheet.
        cell_updates: List of dictionaries, each containing:
            - cell_name: The single cell address (e.g., "Sheet1!A1").
            - content: Value to set. Starts with '=' for formulas. None to clear content.
            - formatting: List of format tags. None to clear formatting.
    """
    try:
        if not cell_updates:
            return "No cells to update."

        # Pre-fetch sheets metadata to cache sheet IDs
        sheet_meta = (
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
        sheet_id_map = {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in sheet_meta["sheets"]
        }

        requests = []

        for update in cell_updates:
            cell_name = update.get("name")
            content = update.get("content")
            formatting = update.get("formatting")

            try:
                sheet_title, row_idx, col_idx = get_grid_coords(cell_name)
            except ValueError as e:
                return f"Error parsing cell '{cell_name}': {str(e)}"

            sheet_id = sheet_id_map.get(sheet_title)
            if sheet_id is None:
                return f"Sheet '{sheet_title}' not found."

            fields = []
            cell_data = {}
            
            try:
                content = float(content)
            except ValueError:
                pass

            # --- Content ---
            if content is not None:
                fields.append("userEnteredValue")
                if isinstance(content, str) and content.startswith("="):
                    cell_data["userEnteredValue"] = {"formulaValue": content}
                elif isinstance(content, str):
                    cell_data["userEnteredValue"] = {"stringValue": content}
                elif isinstance(content, (int, float)):
                    cell_data["userEnteredValue"] = {"numberValue": content}
                elif isinstance(content, bool):
                    cell_data["userEnteredValue"] = {"boolValue": content}
            else:
                fields.append("userEnteredValue")

            # --- Formatting ---
            if formatting is not None:
                fields.append("userEnteredFormat")
                fmt_obj = {}
                text_fmt = {}
                borders = {}

                for tag in formatting:
                    tag = tag.strip()

                    # Validation & Processing
                    if tag == "bold":
                        text_fmt["bold"] = True
                    elif tag == "italic":
                        text_fmt["italic"] = True
                    elif tag == "strikethrough":
                        text_fmt["strikethrough"] = True
                    elif tag.startswith("bg:"):
                        color = hex_to_rgb_dict(tag.split(":")[1])
                        if color:
                            fmt_obj["backgroundColor"] = color
                    elif tag.startswith("text:"):
                        color = hex_to_rgb_dict(tag.split(":")[1])
                        if color:
                            text_fmt["foregroundColor"] = color
                    elif tag.startswith("align:"):
                        align_val = tag.split(":")[1].upper()
                        if align_val in ["LEFT", "CENTER", "RIGHT", "JUSTIFY"]:
                            fmt_obj["horizontalAlignment"] = align_val
                        else:
                            return f"Invalid alignment: {align_val}. Must be LEFT, CENTER, or RIGHT."
                    elif tag.startswith("border-"):
                        side = tag.split("-")[1]
                        if side not in ["top", "bottom", "left", "right"]:
                            return f"Invalid border side: {side}. Must be top, bottom, left, or right."

                        border_style = {
                            "style": "SOLID",
                            "width": 1,
                            "color": {"red": 0, "green": 0, "blue": 0},
                        }
                        borders[side] = border_style
                    elif tag.startswith("merged:"):
                        try:
                            rows, cols = map(int, tag.split(":")[1].split("x"))
                            if rows < 1 or cols < 1:
                                return "Merge rows/cols must be positive integers."
                            requests.append(
                                {
                                    "mergeCells": {
                                        "range": {
                                            "sheetId": sheet_id,
                                            "startRowIndex": row_idx,
                                            "endRowIndex": row_idx + rows,
                                            "startColumnIndex": col_idx,
                                            "endColumnIndex": col_idx + cols,
                                        },
                                        "mergeType": "MERGE_ALL",
                                    }
                                }
                            )
                        except ValueError:
                            return f"Invalid merge format: {tag}. Use 'merged:RxC' (e.g., 'merged:2x3')."
                    else:
                        return f"Unknown format tag: {tag}"

                if text_fmt:
                    fmt_obj["textFormat"] = text_fmt
                if borders:
                    fmt_obj["borders"] = borders

                cell_data["userEnteredFormat"] = fmt_obj
            else:
                # Clear formatting
                fields.append("userEnteredFormat")

            # Add UpdateCells Request
            requests.append(
                {
                    "updateCells": {
                        "rows": [{"values": [cell_data]}],
                        "fields": ",".join(fields),
                        "start": {
                            "sheetId": sheet_id,
                            "rowIndex": row_idx,
                            "columnIndex": col_idx,
                        },
                    }
                }
            )

        # Execute Batch
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

        updated_cells = [u.get("name") for u in cell_updates]
        return f"Successfully updated cells: {', '.join(updated_cells)}"

    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error updating cells: {str(e)}"


@tool
def update_cell(
    runtime: ToolRuntime,
    cell_data: list[Cell],
):
    """
    Updates multiple cells' content and formatting. Replaces existing data.

    Args:
        cell_data: A list of cell update objects, where each object has:
            - name: The single cell address (e.g., "Sheet1!A1").
            - content: Value to set. Starts with '=' for formulas. None to clear content.
            - formatting: List of format tags. None to clear formatting. Supported tags:
                - Text Styles: "bold", "italic", "strikethrough"
                - Alignment: "align:LEFT", "align:CENTER", "align:RIGHT"
                - Colors: "bg:#RRGGBB", "text:#RRGGBB" (e.g. "bg:#FF0000")
                - Borders: "border-top", "border-bottom", "border-left", "border-right"
                - Merges: "merged:RxC" (e.g. "merged:2x3" spans 2 rows, 3 cols)

    Notes: If you want to breakdown the merged cells, you need to update the origin cell of merge to remove the merge tag.
    """
    spreadsheet_id = runtime.config["configurable"]["spreadsheet_id"]
    res = update_cell_impl(spreadsheet_id, cell_data)

    return Command(
        update={
            "messages": [ToolMessage(content=res, tool_call_id=runtime.tool_call_id)],
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[
                        UpdateCellAction(action="update_cell", cell_data=cell_data)
                    ],
                    reasoning=[],
                )
            ],
        }
    )


@tool
def list_sheets(runtime: ToolRuntime):
    """Lists all available sheets."""
    spreadsheet_id = runtime.config["configurable"]["spreadsheet_id"]
    try:
        sheet_meta = (
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
        sheets = []
        for s in sheet_meta.get("sheets", []):
            props = s["properties"]
            sheets.append(f"{props['title']}")
    except Exception as e:
        return f"Error listing sheets: {str(e)}"

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content="\n".join(sheets),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[
                        ListSheetsAction(
                            action="list_sheets",
                            sheets=sheets,
                        )
                    ],
                    reasoning=[],
                )
            ],
        }
    )


@tool
def delete_sheet(runtime: ToolRuntime, sheet_title: str):
    """
    Deletes a sheet with the given title.

    Args:
        sheet_title: The title of the sheet to delete.
    """
    spreadsheet_id = runtime.config["configurable"]["spreadsheet_id"]
    try:
        sheet_meta = (
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )
        sheet_id = None
        for s in sheet_meta["sheets"]:
            if s["properties"]["title"] == sheet_title:
                sheet_id = s["properties"]["sheetId"]
                break
        if sheet_id is None:
            return f"Sheet '{sheet_title}' not found."

        requests = [{"deleteSheet": {"sheetId": sheet_id}}]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Successfully deleted sheet '{sheet_title}'",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "steps": [
                    Step(
                        step_number=runtime.state["current_step"],
                        actions=[
                            DeleteSheetAction(
                                action="delete_sheet", sheet_title=sheet_title
                            )
                        ],
                        reasoning=[],
                    )
                ],
            }
        )
    except Exception as e:
        return f"Error deleting sheet: {str(e)}"


@tool
def create_sheet(runtime: ToolRuntime, sheet_title: str):
    """
    Creates a new sheet with the given title.

    Args:
        sheet_title: The title of the new sheet.
    """
    spreadsheet_id = runtime.config["configurable"]["spreadsheet_id"]
    try:
        requests = [{"addSheet": {"properties": {"title": sheet_title}}}]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Successfully created sheet '{sheet_title}'",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "steps": [
                    Step(
                        step_number=runtime.state["current_step"],
                        actions=[
                            CreateSheetAction(
                                action="create_sheet", sheet_title=sheet_title
                            )
                        ],
                        reasoning=[],
                    )
                ],
            }
        )
    except Exception as e:
        return f"Error creating sheet: {str(e)}"


@tool
def write_todo(
    runtime: ToolRuntime,
    todo_list: list[tuple[str, Literal["pending", "in_progress", "done"]]],
):
    """
    Overwrite the todo list if there is any existing todo list, otherwise create a new todo list.
    You MUST use this tool to plan your actions and execute them sequentially (one by one).

    Rules for updating the todo list:
    1. Only one item can be "in_progress" at a time.
    2. Before starting a task, you MUST update its status to "in_progress".
    3. After completing a task, you MUST update its status to "done".
    4. Never skip steps. Finish the current "in_progress" task before starting the next one.
    5. If you need to add new tasks based on findings, append them to the list as "pending".

    Args:
        todo_list: A list of tuples, each containing a description and a status.
            - Description: The detailed description of the todo item.
            - Status: The status of the todo item. Must be one of "pending", "in_progress", "done".
    """

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"Todo list is updated:\n{format_todo_xml(todo_list)}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
            "todo_list": todo_list,
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[WriteTodoAction(action="write_todo", todo_list=todo_list)],
                    reasoning=[],
                )
            ],
        }
    )


def search_api_call(query: str, max_results: int):
    pages = math.ceil(max_results / SERPER_ENTRIIES_IN_PAGE)
    all_entries = list[SearchEntry]()
    for page in range(1, pages + 1):
        payload = json.dumps({"q": query, "page": page})
        headers = {
            "X-API-KEY": os.getenv("SERPER_API_KEY"),
            "Content-Type": "application/json",
        }
        response = requests.request(
            "POST", SERPER_SEARCH_URL, headers=headers, data=payload
        )
        limit = (
            SERPER_ENTRIIES_IN_PAGE
            if page <= pages
            else max_results % SERPER_ENTRIIES_IN_PAGE
        )
        entries = [
            {
                "title": entry["title"],
                "link": entry["link"],
                "snippet": entry.get("snippet", "(No snippet available)"),
            }
            for entry in response.json()["organic"][:limit]
        ]
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
        formatted_entries.append(
            "<Entry>\n"
            + f"<Title>{entry["title"]}</Title>\n"
            + f"<Link>{entry["link"]}</Link>\n"
            + f"<Snippet>{entry["snippet"]}</Snippet>\n"
            + "</Entry>\n"
        )
    formatted_entries = f"<Entries>\n{''.join(formatted_entries)}</Entries>\n"

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=formatted_entries, tool_call_id=runtime.tool_call_id
                )
            ],
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[
                        SearchAction(
                            action="search",
                            query=query,
                            num_docs_requested=max_results,
                            retrieved_documents=entries,
                        )
                    ],
                    reasoning=[],
                )
            ],
        }
    )


def browse_api_call(url: str):
    payload = json.dumps({"url": url, "includeMarkdown": True})
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY"),
        "Content-Type": "application/json",
    }

    response = requests.request(
        "POST", SERPER_SCRAPE_URL, headers=headers, data=payload
    )

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
        update={
            "messages": [
                ToolMessage(content=browsed_content, tool_call_id=runtime.tool_call_id)
            ],
            "steps": [
                Step(
                    step_number=runtime.state["current_step"],
                    actions=[
                        BrowseAction(
                            action="browse", url=url, browsed_content=browsed_content
                        )
                    ],
                    reasoning=[],
                )
            ],
        }
    )


if __name__ == "__main__":
    update_cell_impl(
        "1j1K9CKm-LWmfibmB9qWL3DVliCufFy9OFdZhcF6WkFQ",
        [
            {
                "name": "Sheet2!A1",
                "content": "100",
                "formatting": ["bold"],
            }
        ],
    )
