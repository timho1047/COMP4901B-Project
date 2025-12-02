import re
from typing import Literal


def rgb_to_hex(color_dict, default_val=0.0):
    """Converts Google's 0-1 RGB dict to hex string."""
    if not color_dict:
        r, g, b = default_val, default_val, default_val
    else:
        r = color_dict.get("red", default_val)
        g = color_dict.get("green", default_val)
        b = color_dict.get("blue", default_val)

    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def hex_to_rgb_dict(hex_color):
    """Converts #RRGGBB to Google API RGB dict (0-1 floats)."""
    if not hex_color or not hex_color.startswith("#"):
        return None
    hex_color = hex_color.lstrip("#")
    return {
        "red": int(hex_color[0:2], 16) / 255.0,
        "green": int(hex_color[2:4], 16) / 255.0,
        "blue": int(hex_color[4:6], 16) / 255.0,
    }


def get_grid_coords(range_name):
    """Parses 'Sheet1!A1' into (sheet_title, row_idx, col_idx)."""
    match = re.match(r"(?:'([^']+)'|([^!]+))!([A-Za-z]+)([0-9]+)", range_name)
    if not match:
        raise ValueError(f"Invalid range format: {range_name}")

    sheet_title = match.group(1) or match.group(2)
    col_str = match.group(3).upper()
    row_str = match.group(4)

    row_idx = int(row_str) - 1

    col_idx = 0
    for char in col_str:
        col_idx = col_idx * 26 + (ord(char) - ord("A") + 1)
    col_idx -= 1

    return sheet_title, row_idx, col_idx


def format_todo_xml(
    todo_list: list[tuple[str, Literal["pending", "in_progress", "done"]]],
) -> str:
    todo_xml = "<TodoList>\n"
    for todo in todo_list:
        todo_xml += f"<Todo>\n<Description>{todo[0]}</Description>\n<Status>{todo[1]}</Status>\n</Todo>\n"
    todo_xml += "</TodoList>"

    return todo_xml

