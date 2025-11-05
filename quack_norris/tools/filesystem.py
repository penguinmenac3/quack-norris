import os
import inspect
from typing import get_type_hints

from quack_norris.logging import logger
from quack_norris.core.llm import Tool, ToolParameter


def generate_schema(func):
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    properties: dict[str, ToolParameter] = {}
    required = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        typ = hints.get(name, str)
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array"}
        properties[name] = ToolParameter(type=type_map.get(typ, "string"), description="")
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required
    }


class FileSystemTools:
    def __init__(
        self,
        root_folder: str,
        is_list_allowed: bool = True,
        is_read_allowed: bool = True,
        is_write_allowed: bool = False,
        is_delete_allowed: bool = False,
    ) -> None:
        self._root_folder = os.path.abspath(root_folder)
        self._is_list_allowed = is_list_allowed
        self._is_read_allowed = is_read_allowed
        self._is_write_allowed = is_write_allowed
        self._is_delete_allowed = is_delete_allowed

    def _normalize_path(self, path, allow_no_exist: bool = False):
        if path.startswith("/"):
            path = path[1:]
        if path == "":
            path = "."

        target_folder = os.path.normpath(os.path.abspath(os.path.join(self._root_folder, path)))
        if not target_folder.startswith(self._root_folder):
            return path, f"Access to path '{path}' is not allowed."
        if not allow_no_exist and not os.path.exists(target_folder):
            return path, f"Path '{path}' does not exist."
        return path, ""

    def list_files(self, subfolder: str = ".") -> list[str]:
        """List files and folders in the specified subfolder."""
        if not self._is_list_allowed:
            return ["Listing files is not allowed."]
        
        target_folder, error = self._normalize_path(subfolder)
        if error != "":
            return [error]
        files = os.listdir(target_folder)

        # hide files and folders starting with "."
        files = [f for f in files if not f.startswith(".")]
        
        return files
    
    def list_tree(self, root: str = ".") -> str:
        """
        List all the files of a folder and its subfolders similar to the tree command.
        
        This tool is especially helpfull to get an overview over the folder structure.
        Especially when the user does not know where a file is or it is unclear, this tool can help locating files.
        Sometimes reading with a path does not work well, then calling tree can help you find the file without the users help.
        """
        if not self._is_list_allowed:
            return "Listing files is not allowed."

        target_folder, error = self._normalize_path(root)
        if error != "":
            return error

        tree_lines = []

        def _tree(dir_path, prefix=""):
            entries = sorted(os.listdir(dir_path))
            entries = [e for e in entries if not e.startswith(".")]
            entries_count = len(entries)
            for idx, entry in enumerate(entries):
                entry_path = os.path.join(dir_path, entry)
                connector = "└── " if idx == entries_count - 1 else "├── "
                tree_lines.append(f"{prefix}{connector}{entry}")
                if os.path.isdir(entry_path):
                    extension = "    " if idx == entries_count - 1 else "│   "
                    _tree(entry_path, prefix + extension)

        tree_lines.append(os.path.basename(target_folder) or target_folder)
        _tree(target_folder)
        return "\n".join(tree_lines)

    def read_file(self, file_path: str, max_characters: int = -1) -> str:
        """
        Read the content of the specified text file (text only, NO image or binary support).

        max_characters specifies how many characters of the file should be read.
        The default is -1 and means read the entire file.
        Unless you really only need the head of a file, you should use -1.
        """
        if not self._is_read_allowed:
            return "Reading files is not allowed."

        target_file, error = self._normalize_path(file_path)
        if error != "":
            return error

        with open(target_file, "r", encoding="utf-8") as f:
            text = f.read()
        if max_characters <= 0:
            return text
        return text[:min(max_characters, len(text))]

    def write_file(self, file_path: str, text: str) -> str:
        """Write text to the specified text file (text only, NO image or binary support)."""
        if not self._is_write_allowed:
            return "Writing files is not allowed."

        target_file, error = self._normalize_path(file_path, allow_no_exist=True)
        if error != "":
            return error

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(text)
        return f"File '{file_path}' written successfully."

    def delete_file(self, file_path: str) -> str:
        """Delete the specified file."""
        if not self._is_delete_allowed:
            return "Deleting files is not allowed."

        target_file, error = self._normalize_path(file_path)
        if error != "":
            return error

        os.remove(target_file)
        return f"File '{file_path}' deleted successfully."

    def list_tools(self, prefix: str = "") -> list[Tool]:
        tools = []
        if self._is_list_allowed:
            tools.append(self.list_files)
            tools.append(self.list_tree)
        if self._is_read_allowed:
            tools.append(self.read_file)
        if self._is_write_allowed:
            tools.append(self.write_file)
        if self._is_delete_allowed:
            tools.append(self.delete_file)
        return [
            Tool(
                name=prefix + tool.__name__,
                description=tool.__doc__ or "missing description",
                parameters=generate_schema(tool)["properties"],
                tool_callable=tool,
            )
            for tool in tools
        ]
