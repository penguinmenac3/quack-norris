import unittest
import subprocess
import signal
import os
import time

from quack_norris.server.llm_provider import OpenAIProvider, Message

# Store the process ID of the test server
test_server_process = None

def start_test_server():
    global test_server_process
    # Start "quack-norris-server"
    test_server_process = subprocess.Popen(['quack-norris-server'], shell=True)
    print(f"Test server started with PID: {test_server_process.pid}")
    time.sleep(1)

def stop_test_server():
    global test_server_process
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


class TestAPIServer(unittest.TestCase):
    def setUp(self):
        start_test_server()
        self.client = OpenAIProvider(base_url="http://localhost:11337", api_key="test_key")

    def tearDown(self):
        stop_test_server()

    def test_chat(self):
        messages = [
            Message("system", "You are a helpful assistant."),
            Message("user", "Who won the world series in 2020?"),
            Message("assistant", "The LA Dodgers won in 2020."),
            Message("user", "Where was it played?"),
        ]
        response = self.client.chat(model="qwen2.5-coder:1.5b", messages=messages)
        print(response)
