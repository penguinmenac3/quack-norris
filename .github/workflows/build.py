#!/usr/bin/env python3
"""Custom build script that generates PyPI README before building."""

import re
import subprocess
import sys
from pathlib import Path


def generate_pypi_readme():
    """Generate README_PYPI.md with absolute GitHub URLs from README.md."""
    # Since this script is in .github/workflows/, we need to go to the repo root
    repo_root = Path(__file__).parent.parent.parent
    readme_path = repo_root / "README.md"
    pypi_readme_path = repo_root / "README_PYPI.md"
    
    if not readme_path.exists():
        print(f"README.md not found at {readme_path}")
        return False
    
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    github_base = "https://github.com/penguinmenac3/quack-norris/blob/main"
    github_raw_base = "https://github.com/penguinmenac3/quack-norris/raw/main"
    
    # Replace relative image paths with absolute GitHub URLs (use raw for images)
    image_pattern = r'!\[([^\]]+)\]\(([^)]+\.(png|jpg|jpeg|gif|svg))\)'
    
    def replace_image(match):
        alt_text = match.group(1)
        relative_path = match.group(2)
        absolute_url = f"{github_raw_base}/{relative_path}"
        return f'![{alt_text}]({absolute_url})'
    
    new_content = re.sub(image_pattern, replace_image, content)
    
    # Replace relative markdown links with absolute GitHub URLs
    link_pattern = r'\[([^\]]+)\]\((?!http|#)([^)]+)\)'
    
    def replace_link(match):
        link_text = match.group(1)
        relative_path = match.group(2)
        absolute_url = f"{github_base}/{relative_path}"
        return f'[{link_text}]({absolute_url})'
    
    new_content = re.sub(link_pattern, replace_link, new_content)
    
    with open(pypi_readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"Generated {pypi_readme_path} with absolute GitHub URLs")
    return True


if __name__ == "__main__":
    # Generate the PyPI README first
    if not generate_pypi_readme():
        sys.exit(1)
    
    # Run the actual build command using python -m build
    result = subprocess.run([sys.executable, "-m", "build"] + sys.argv[1:])
    sys.exit(result.returncode)
