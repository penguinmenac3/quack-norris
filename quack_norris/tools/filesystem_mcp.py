# Import necessary libraries
import re
import os
import difflib
import json
import requests
from loguru import logger
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse


from quack_norris.tools.ask_user_consent import ask_user_consent


SUPPORTED_TXT_FILES = ['.txt', '.md', '.py', '.json', '.yaml', '.yml', '.csv', '.ini', '.cfg', '.toml', '.js', '.ts', '.html', '.css']


def build_mcp_server(config_path: str | None = None):
    # By default use the standard quack norris config
    if config_path is None:
        config_path = os.path.join(os.path.expanduser("~"), ".config", "quack-norris", "config.json")

    # Initialize FastMCP instance
    mcp_server = FastMCP("Filesystem MCP Server")

    # A mapping from workspace name to path
    workspaces = {}
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
            for name, path in config.get("workspaces", {}).items():
                workspaces[name] = os.path.abspath(path)
    except Exception as e:
        print(f"Warning: Could not load workspaces from config.json: {e}")
    # Always add cwd (if not already in config)
    cwd = os.path.abspath(os.getcwd())
    if cwd not in workspaces.values():
        workspaces[os.path.basename(cwd)] = cwd

    # Helper function to safely join paths, accepting relative and absolute paths
    def _safe_join(workspace, sub_path):
        # If absolute, use as is, but check it's inside cwd
        cwd = workspaces[workspace]
        if os.path.isabs(sub_path):
            abs_path = os.path.abspath(sub_path)
        else:
            abs_path = os.path.abspath(os.path.join(cwd, sub_path))
        # Prevent directory traversal outside cwd
        if os.path.commonpath([cwd, abs_path]) != cwd:
            raise ValueError(f"Attempted directory traversal outside the working directory: {sub_path}")
        return abs_path


    # Register tool functions directly
    @mcp_server.tool
    def list_workspaces() -> list:
        """Returns a list of workspace names, you always need to do this first.
        All other functions require you to select a workspace."""
        return list(workspaces.keys())


    @mcp_server.tool
    def read_file(workspace: str, file_path: str, start: int = 0, end: int = -1) -> str:
        """Reads the contents of a file (with a character limit)."""
        try:
            safe_path = _safe_join(workspace, file_path)
            end = end if end > 0 else -1
            with open(safe_path, 'r', encoding="utf-8") as f:
                content = f.read(end if end > 0 else None)
            return content[max(0, start):min(end, len(content))]
        except Exception as e:
            return f"Error reading file: {str(e)}"


    @mcp_server.tool
    def list_files(workspace: str, subfolder: str = '.') -> list:
        """Lists files and folders in the specified subfolder of the workspace."""
        try:
            safe_path = _safe_join(workspace, subfolder)
            files = os.listdir(safe_path)
            # hide files and folders starting with "."
            files = [f for f in files if not f.startswith(".")]
            return files
        except Exception as e:
            return [f"Error listing files: {str(e)}"]


    @mcp_server.tool
    def list_tree(workspace: str, root: str = '.') -> str:
        """Lists all files and folders like a tree command for the workspace."""
        safe_root = _safe_join(workspace, root)
        tree_lines = [safe_root]
        
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

        _tree(safe_root)
        return "\n".join(tree_lines)


    @mcp_server.tool
    def write_file(workspace: str, file_path: str, content: str) -> str:
        """Writes content to a file in the workspace."""
        try:
            safe_path = _safe_join(workspace, file_path)
            if not safe_path.lower().endswith(tuple(SUPPORTED_TXT_FILES)):
                return f"ERROR: Unsupported filetype, only supporting: {SUPPORTED_TXT_FILES}"
            if os.path.exists(safe_path):
                with open(safe_path, 'r', encoding='utf-8') as file:
                    original_content = file.readlines()
                diff = difflib.unified_diff(original_content, content.splitlines(), lineterm='')
                diff_text = '\n'.join(list(diff))
                # Show popup for user consent (using tkinter)
                if not ask_user_consent("Allow making the following changes?", detail=diff_text):
                    return "Error: User declined to apply the changes. No changes made."
            else:
                if not ask_user_consent(f"Allow writing `{safe_path}`?", detail=content):
                    return "Error: User declined to write the file. No changes made."
            with open(safe_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return f"Successfully written to {safe_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


    @mcp_server.tool
    def delete_file(workspace: str, file_path: str) -> str:
        """Deletes a file in the workspace."""
        try:
            safe_path = _safe_join(workspace, file_path)
            if not os.path.isfile(safe_path):
                return f"Error: {safe_path} is not a file."
            ext = os.path.splitext(safe_path)[1].lower()
            detail = None
            if ext in SUPPORTED_TXT_FILES:
                try:
                    with open(safe_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    detail = content if len(content) < 5000 else content[:5000] + "\n... (truncated)"
                except Exception as e:
                    detail = f"Error reading file content: {str(e)}"
            question = f"Are you sure you want to delete the file '{file_path}'?"
            consent = ask_user_consent(question, detail)
            if not consent:
                return "Error: User declined to delete the file. No changes made."
            os.remove(safe_path)
            return f"Successfully deleted {safe_path}"
        except Exception as e:
            return f"Error deleting file: {str(e)}"


    @mcp_server.tool
    def open_file_for_user(workspace: str, file_path: str) -> str:
        """Opens a file on the OS for the user."""
        try:
            safe_path = _safe_join(workspace, file_path)
            if not os.path.isfile(safe_path):
                return f"Error: {safe_path} is not a file."
            consent = ask_user_consent(f"Do you want to open the file '{safe_path}'?")
            if not consent:
                return "Error: User declined to open the file. No action taken."
            # Open file using OS-specific command
            if os.name == 'nt':  # Windows
                os.startfile(safe_path)
            elif os.name == 'posix':
                import subprocess
                opener = 'xdg-open' if os.uname().sysname != 'Darwin' else 'open'
                subprocess.Popen([opener, safe_path])
            else:
                return "Error: Unsupported operating system."
            return f"Opened file: {safe_path}"
        except Exception as e:
            return f"Error opening file: {str(e)}"


    # @mcp_server.tool
    # def retrieve_data(workspace: str, query: str) -> list:
    #     """Retrieves data based on the query in the workspace."""
    #     # Note: A full implementation would require integrating a model or search mechanism.
    #     # This is a placeholder.
    #     return [f"Retrieval results for '{query}' in workspace '{workspace}' - functionality to be implemented."]


    @mcp_server.tool
    def search_files(workspace: str, query: str, directory: str = '.') -> list:
        """Performs a traditional search for the query in files in the workspace."""
        matches = []
        try:
            safe_directory = _safe_join(workspace, directory)
            for dirpath, _, filenames in os.walk(safe_directory):
                for filename in filenames:
                    try:
                        safe_file_path = _safe_join(workspace, os.path.join(dirpath, filename))
                        with open(safe_file_path, 'r') as file:
                            for line_number, line in enumerate(file):
                                if query in line:
                                    matched_line = f"{filename} (Line {line_number + 1}): {line.strip()}"
                                    matches.append(matched_line)
                                    if len(matches) >= 10:
                                        return matches
                    except Exception:
                        continue
            return matches
        except Exception as e:
            return [f"Error searching files: {str(e)}"]


    @mcp_server.tool
    def grep_text(workspace: str, pattern: str, top_k: int = -1) -> list:
        """Searches for a regex pattern in all text files in the workspace and returns up to top_k matches.
        Use top_k -1 to indicate that you want to find all matches."""
        matches = []
        try:
            regex = None
            try:
                regex = re.compile(pattern, re.MULTILINE)
            except re.error as err:
                return [f"Invalid regex pattern: {err}"]
            root_dir = workspaces[workspace]
            for dirpath, _, filenames in os.walk(root_dir):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    # Only check text files by extension or try reading as text
                    if not filename.lower().endswith(tuple(SUPPORTED_TXT_FILES)):
                        continue
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            text = f.read()
                            for match in regex.finditer(text):
                                # Find the line number where the match starts
                                start_pos = match.start()
                                # Count newlines before start_pos
                                line_number = text.count('\n', 0, start_pos) + 1
                                # Get the matched string (may be multiline)
                                matched_str = match.group().replace('\n', ' ')
                                matches.append(f"{file_path} (Line {line_number}): {matched_str}")
                                if top_k > 0 and len(matches) >= top_k:
                                    return matches
                    except Exception:
                        continue
            return matches
        except Exception as e:
            return [f"Error during grep: {str(e)}"]


    @mcp_server.custom_route("/add_folder", methods=["POST"])
    async def add_folder(request: Request):
        data = await request.json()
        new_dir = data.get("path")
        if not new_dir:
            return JSONResponse({"error": "Missing path"}, status_code=400)
        abs_new_dir = os.path.abspath(new_dir)
        if new_dir != abs_new_dir:
            return JSONResponse({"error": "Provided path must be an absolute path"}, status_code=400)
        if not os.path.isdir(abs_new_dir):
            return JSONResponse({"error": "Directory does not exist"}, status_code=400)
        if abs_new_dir in workspaces.values():
            return JSONResponse({"error": "Path already in workspaces"}, status_code=400)
        workspaces[os.path.basename(abs_new_dir)] = abs_new_dir
        logger.info(f"Added new workspace: {abs_new_dir}")
        return JSONResponse({"status": "success", "path": new_dir})

    return mcp_server


def main(host: str = "127.0.0.1", port: int = 13370) -> None:
    server_url = f"http://{host}:{port}"
    cwd = os.path.abspath(os.getcwd())
    # Check if server is running
    try:
        response = requests.post(f"{server_url}/add_folder", json={"path": cwd}, timeout=2)
        if response.status_code == 200:
            print(f"Server already running. Add working directory: {cwd}.")
            return
        if response.status_code == 400:
            print(response.text)
            return
    except Exception:
        pass
    # If not running, start a new server
    print(f"No server detected. Starting new MCP HTTP server on {host}:{port}...")
    mcp_server = build_mcp_server()
    mcp_server.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
