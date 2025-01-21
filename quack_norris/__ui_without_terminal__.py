import os


def ui():
    if os.name == 'nt':  # Windows
        os.system("start /b pythonw -m quack_norris ui")
    else:  # Linux/Unix/Mac
        os.system("python -m quack_norris ui &")
