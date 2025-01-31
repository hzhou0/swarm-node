import time

from python_sdk import receive_event, send_data

while True:
    event = receive_event()
    if event.HasField("data"):
        send_data(event.data)
    time.sleep(0.01)
