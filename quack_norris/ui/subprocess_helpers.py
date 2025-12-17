import atexit
import subprocess as sp
import os

LOCAL_UI_CMD = 'npm run dev'
LOCAL_API_CMD = 'uv run quack-norris --serve'

def _kill_process(p):
    if os.name == 'nt':
        # p.kill is not adequate
        sp.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
    elif os.name == 'posix':
        p.kill()
    else:
        pass


def startup_servers_in_background(dev: bool = False) -> None:
    """Starts the local quack-norris api and ui servers in background processes."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if dev:
        cmd = LOCAL_UI_CMD
        if os.name == "nt":
            cmd = cmd.split()
        p_ui = sp.Popen(LOCAL_UI_CMD.split(), stdout=sp.DEVNULL, cwd=os.path.join(root_dir, 'quack_ui'), shell=True)
        atexit.register(_kill_process, p_ui)

    # Add cwd as workspace to quack-norris server
    cmd = LOCAL_API_CMD.split() + ['--workdir', f'{os.getcwd()}']
    if os.name != "nt":
        cmd = " ".join(cmd)
    p_api = sp.Popen(cmd, stdout=sp.DEVNULL, cwd=root_dir, shell=True)
    atexit.register(_kill_process, p_api)
