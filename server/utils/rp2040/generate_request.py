from base64 import b64encode

def generate_req(settings: dict) -> str:
    headers = ""
    path = settings["mountpoint"]
    hostname = settings["server"]
    port = settings["port"]
    user = settings["ntripuser"]
    password = settings["ntrippassword"]

    cred = b64encode(f"{user}:{password}".encode()).decode()
    headers += f"Authorization: Basic {cred}\r\n"
    httpver = "1.1"

    headers += "Ntrip-Version: Ntrip/2.0\r\n"

    return (
        f"GET /{path} HTTP/{httpver}\r\n"
        f"Host: {hostname}:{port}\r\n"
        f"User-Agent: NTRIP pygnssutils/1.1.9\r\n"
        f"{headers}"
        "Accept: */*\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

def main():
    settings = {
        "mountpoint" : "AVRIL",
        "server" : "rtk2go.com",
        "port" : 2101,
        "ntripuser" : "h285zhou@uwaterloo.ca",
        "ntrippassword" : "none",
    }
    request = generate_req(settings)
    print(request)

if __name__ == "__main__":
    main()