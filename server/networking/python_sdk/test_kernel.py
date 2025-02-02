import os

from main import send_data, eventQueue

if __name__ == "__main__":
    # List all file descriptors in the current process
    print(os.environ)
    fds = os.listdir("/proc/self/fd")

    print("Open file descriptors:")
    for fd in fds:
        try:
            link = os.readlink(f"/proc/self/fd/{fd}")
            print(f"FD {fd}: {link}")
        except OSError:
            pass  # Ignore errors (e.g., invalid links

    while True:
        event = eventQueue.get()
        # echo incoming data
        if event.HasField("data"):
            if event.data.HasField("channel"):
                event.data.channel.dest_uuid = event.data.channel.src_uuid
                event.data.channel.ClearField("src_uuid")
            send_data(event.data)
