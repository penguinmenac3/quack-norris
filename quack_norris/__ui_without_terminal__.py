import os
import sys


def ui():
    args = ' '.join(sys.argv[1:])
    if os.name == 'nt':  # Windows
        os.system(f"start /b python -m quack_norris ui {args}")
    else:  # Linux/Unix/Mac
        os.system(f"python -m quack_norris ui {args} &")
