# Import necessary libraries
import re
import os
import difflib


from quack_norris.core.tools.tool import register_tool
from quack_norris.core.tools.ask_user_consent import ask_user_consent


SUPPORTED_TXT_FILES = ['.txt', '.md', '.py', '.json', '.yaml', '.yml', '.csv', '.ini', '.cfg', '.toml', '.js', '.ts', '.html', '.css']


class Filesystem():
    def __init__(self, workspaces: dict[str, str]):
        """Sets up filesystem tools for the given workspaces."""
        # Make paths absolute and create a copy of workspaces
        self.workspaces = {
            name: os.path.abspath(path)
            for name, path in workspaces.items()
        }
        # Always add cwd (if not already in config)
        cwd = os.path.abspath(os.getcwd())
        if cwd not in self.workspaces.values():
            self.workspaces[os.path.basename(cwd)] = cwd

    # Helper function to safely join paths, accepting relative and absolute paths
    def _safe_join(self, workspace, sub_path):
        # If absolute, use as is, but check it's inside cwd
        if workspace not in self.workspaces:
            raise ValueError(f"Workspace '{workspace}' not found.")
        cwd = self.workspaces[workspace]
        if os.path.isabs(sub_path):
            abs_path = os.path.abspath(sub_path)
        else:
            abs_path = os.path.abspath(os.path.join(cwd, sub_path))
        # Prevent directory traversal outside cwd
        if os.path.commonpath([cwd, abs_path]) != cwd:
            raise ValueError(f"Attempted directory traversal outside the working directory: {sub_path}")
        return abs_path


    # Register tool functions directly
    @register_tool(name="filesystem.list_workspaces")
    def list_workspaces(self) -> list:
        """Returns a list of workspace names, you always need to do this first.
        All other filesystem functions require you to select a workspace.
        If the user does not explicitly state a workspace, check with this function which workspace matches best to the users intent."""
        return list(self.workspaces.keys())


    @register_tool(name="filesystem.read_file")
    def read_file(self, workspace: str, file_path: str, start: int = 0, end: int = -1) -> str:
        """Reads the contents of a file (with a character limit)."""
        try:
            safe_path = self._safe_join(workspace, file_path)
            end = end if end > 0 else -1
            with open(safe_path, 'r', encoding="utf-8") as f:
                content = f.read(end if end > 0 else None)
            return content[max(0, start):min(end, len(content))]
        except Exception as e:
            return f"Error reading file: {str(e)}"


    @register_tool(name="filesystem.list_files")
    def list_files(self, workspace: str, subfolder: str = '.') -> list:
        """Lists files and folders in the specified subfolder of the workspace."""
        try:
            safe_path = self._safe_join(workspace, subfolder)
            files = os.listdir(safe_path)
            # hide files and folders starting with "."
            files = [f for f in files if not f.startswith(".")]
            return files
        except Exception as e:
            return [f"Error listing files: {str(e)}"]


    @register_tool(name="filesystem.list_tree")
    def list_tree(self, workspace: str, root: str = '.') -> str:
        """Lists all files and folders like a tree command for the workspace."""
        safe_root = self._safe_join(workspace, root)
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


    @register_tool(name="filesystem.write_file")
    def write_file(self, workspace: str, file_path: str, content: str) -> str:
        """Writes content to a file in the workspace."""
        try:
            safe_path = self._safe_join(workspace, file_path)
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


    @register_tool(name="filesystem.delete_file")
    def delete_file(self, workspace: str, file_path: str) -> str:
        """Deletes a file in the workspace."""
        try:
            safe_path = self._safe_join(workspace, file_path)
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


    @register_tool(name="filesystem.open_file_for_user")
    def open_file_for_user(self, workspace: str, file_path: str) -> str:
        """Opens a file on the OS for the user."""
        try:
            safe_path = self._safe_join(workspace, file_path)
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


    # @register_tool(name="filesystem.retrieve")
    # def retrieve(self, workspace: str, query: str) -> list:
    #     """Retrieves data based on the query in the workspace."""
    #     # Note: A full implementation would require integrating a model or search mechanism.
    #     # This is a placeholder.
    #     return [f"Retrieval results for '{query}' in workspace '{workspace}' - functionality to be implemented."]


    @register_tool(name="filesystem.search_text_in_files")
    def search_text_in_files(self, workspace: str, pattern: str, folder=".", top_k: int = -1) -> list:
        """Searches for a regex pattern in all text files in the workspace and returns up to top_k matches.
        Use top_k -1 to indicate that you want to find all matches."""
        matches = []
        try:
            regex = None
            try:
                regex = re.compile(pattern, re.MULTILINE)
            except re.error as err:
                return [f"Invalid regex pattern: {err}"]
            root_dir = self._safe_join(workspace, folder)
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
                                end_pos = match.end()
                                # Count newlines before start_pos and ened_pos
                                start_line = text.count('\n', 0, start_pos)
                                end_line = text.count('\n', 0, end_pos)
                                # Get the matched string (may be multiline)
                                matched_str = "\n".join(text.split("\n")[start_line:(end_line+1)])
                                llm_file_path = file_path.replace(self.workspaces[workspace], ".")
                                matches.append(f"{llm_file_path} (Line {start_line+1}-{end_line+1}):\n{matched_str}")
                                if top_k > 0 and len(matches) >= top_k:
                                    return matches
                    except Exception:
                        continue
            return matches
        except Exception as e:
            return [f"Error during grep: {str(e)}"]
