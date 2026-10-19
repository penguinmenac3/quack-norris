#!/usr/bin/env python3
"""Build distributions with PyPI-friendly links in the package README."""

import re
import subprocess
import sys
from pathlib import Path


def transform_readme(content):
    """Replace relative links and images with absolute GitHub URLs for PyPI."""
    github_base = "https://github.com/penguinmenac3/quack-norris/blob/main"
    github_raw_base = "https://github.com/penguinmenac3/quack-norris/raw/main"

    # Replace relative image paths with absolute GitHub URLs (use raw for images)
    image_pattern = r'!\[([^\]]+)\]\(([^)]+\.(png|jpg|jpeg|gif|svg))\)'

    def replace_image(match):
        alt_text = match.group(1)
        relative_path = match.group(2)
        absolute_url = f"{github_raw_base}/{relative_path}"
        return f'![{alt_text}]({absolute_url})'

    content = re.sub(image_pattern, replace_image, content)

    # Replace relative markdown links with absolute GitHub URLs
    link_pattern = r'\[([^\]]+)\]\((?!http|#)([^)]+)\)'

    def replace_link(match):
        link_text = match.group(1)
        relative_path = match.group(2)
        absolute_url = f"{github_base}/{relative_path}"
        return f'[{link_text}]({absolute_url})'

    return re.sub(link_pattern, replace_link, content)


def build_with_pypi_readme():
    """Build with transformed README.md, restoring the working copy afterward."""
    # Since this script is in .github/workflows/, we need to go to the repo root.
    repo_root = Path(__file__).parent.parent.parent
    readme_path = repo_root / "README.md"

    if not readme_path.exists():
        print(f"README.md not found at {readme_path}")
        return False

    original_readme = readme_path.read_bytes()
    transformed_readme = transform_readme(original_readme.decode("utf-8"))
    try:
        readme_path.write_text(transformed_readme, encoding="utf-8")
        print("Temporarily transformed README.md with absolute GitHub URLs")

        # Run the actual build command using python -m build.
        result = subprocess.run([sys.executable, "-m", "build"] + sys.argv[1:])
        return result.returncode == 0
    finally:
        readme_path.write_bytes(original_readme)
        print("Restored README.md")


if __name__ == "__main__":
    if not build_with_pypi_readme():
        sys.exit(1)
