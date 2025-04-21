import os
import sys
import signal
import subprocess
import time
import unittest

from quack_norris.common.llm_provider import OpenAI
from quack_norris.common._types import ChatMessage, ChatCompletionRequest

os.chdir(os.path.dirname(__file__))

# Store the process ID of the test server
test_server_process = None


def start_test_server():
    global test_server_process
    # skip on windows (killing is bugged)
    if os.name == 'nt':
        return
    # Start "quak-norris-server"
    test_server_process = subprocess.Popen(['quack-norris-server'], shell=True)
    print(f"Test server started with PID: {test_server_process.pid}")
    time.sleep(1)


def stop_test_server():
    global test_server_process
    if os.name == "nt":
        return
    if test_server_process and test_server_process.poll() is None:
        try:
            # Send a SIGTERM signal to the process
            os.kill(test_server_process.pid, signal.SIGTERM)
            # Wait for the process to terminate
            test_server_process.wait()
            print(f"Test server with PID {test_server_process.pid} stopped.")
        except Exception as e:
            print(f"Failed to stop test server: {e}")
    else:
        print("Test server is not running or already terminated.")


def _manual_test_run():
    flag_file = os.path.join(os.path.dirname(__file__), "_enable_manual")
    if os.path.exists(flag_file):
        return True
    print(f"Skipping Test in {__file__}. If you want to run it, create '{flag_file}'.")
    return False


class TestAPIServer(unittest.TestCase):
    def setUp(self):
        if not _manual_test_run():
            return
        start_test_server()
        self.client = OpenAI(base_url="http://localhost:11337", api_key="test_key")

    def tearDown(self):
        if not _manual_test_run():
            return
        stop_test_server()

    def test_chat(self):
        if not _manual_test_run():
            return
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Who won the world series in 2020?"),
            ChatMessage(role="assistant", content="The LA Dodgers won in 2020."),
            ChatMessage(role="user", content="Where was it played?"),
        ]
        response = self.client.chat(
            ChatCompletionRequest(model="qwen2.5-coder:1.5b", messages=messages)
        )
        print(response)

    def test_chat_stream(self):
        if not _manual_test_run():
            return
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Who won the world series in 2020?"),
            ChatMessage(role="assistant", content="The LA Dodgers won in 2020."),
            ChatMessage(role="user", content="Where was it played?"),
        ]
        response = self.client.chat(
            ChatCompletionRequest(model="qwen2.5-coder:1.5b", messages=messages, stream=True)
        )
        for chunk in response:
            print(chunk, end="")
            sys.stdout.flush()
        print()

    def test_chat_invalid_model(self):
        if not _manual_test_run():
            return
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Who won the world series in 2020?"),
            ChatMessage(role="assistant", content="The LA Dodgers won in 2020."),
            ChatMessage(role="user", content="Where was it played?"),
        ]
        fail = False
        try:
            response = self.client.chat(
                ChatCompletionRequest(model="non-existent", messages=messages)
            )
        except RuntimeError as e:
            fail = True
            response = str(e)
        assert fail, response
        print(response)
