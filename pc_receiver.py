import socket
import json
import mysql.connector
import time
import threading
from datetime import datetime
from pathlib import Path

# -----------------------------
# Server Configuration
# -----------------------------
HOST = "0.0.0.0"
PORT = 5000

LOG_FILE = Path(__file__).with_name("machine_events.jsonl")
PRESENCE_FILE = Path(__file__).with_name("machine_presence.json")

# Heartbeat from ESP is every ~15s — wait longer than that before timeout noise
RECV_TIMEOUT = 20
# Drop client if no real JSON for this long (missed heartbeats)
IDLE_DISCONNECT_SEC = 45

# -----------------------------
# MySQL
# -----------------------------
db_lock = threading.Lock()
log_lock = threading.Lock()
presence_lock = threading.Lock()
clients_lock = threading.Lock()
active_clients = set()  # {(ip, port), ...}


def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="jeevaMuthu14#",
        database="iot_db",
        autocommit=False,
    )


db = get_db()
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS iot_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    machine_no VARCHAR(50),
    state VARCHAR(50),
    shot INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()
print("Connected to MySQL")


def ensure_db():
    global db, cursor
    try:
        db.ping(reconnect=True, attempts=3, delay=1)
    except Exception:
        print("MySQL reconnecting...")
        db = get_db()
        cursor = db.cursor()


def insert_row(machine_no, state, shot):
    with db_lock:
        ensure_db()
        sql = """
        INSERT INTO iot_data
        (machine_no, state, shot)
        VALUES (%s,%s,%s)
        """
        cursor.execute(sql, (machine_no, state, shot))
        db.commit()


def append_log(machine_no, state, shot):
    row = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "machine_no": machine_no,
        "state": state,
        "shot": shot,
    }
    with log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def update_presence(machine_no, state, shot, ip=""):
    """Live presence for Streamlit (updated on every message including heartbeat)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with presence_lock:
        data = {}
        if PRESENCE_FILE.exists():
            try:
                data = json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[str(machine_no)] = {
            "last_seen": now,
            "state": state,
            "shot": shot,
            "ip": ip,
            "online": state != "disconnected",
        }
        PRESENCE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def enable_keepalive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            # enable, 20s idle, 5s interval
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 20000, 5000))
        else:
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except Exception as e:
        print("Keepalive setup note:", e)


def active_count():
    with clients_lock:
        return len(active_clients)


def register_client(addr):
    with clients_lock:
        active_clients.add(addr)
        n = len(active_clients)
        ips = sorted({a[0] for a in active_clients})
    return n, ips


def unregister_client(addr):
    with clients_lock:
        active_clients.discard(addr)
        n = len(active_clients)
        ips = sorted({a[0] for a in active_clients})
    return n, ips


def handle_client(client, addr):
    client.settimeout(RECV_TIMEOUT)
    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    enable_keepalive(client)

    n, ips = register_client(addr)
    print("-----------------------------------")
    print(f"Client Connected : {addr}")
    print(f"Active boards    : {n} → {ips}")
    print("-----------------------------------")

    buffer = ""
    last_data_time = time.time()
    last_machine_no = None
    last_shot = 0

    try:
        while True:
            try:
                data = client.recv(1024)

                if not data:
                    print(f"Client closed socket (recv empty) {addr}")
                    break

                last_data_time = time.time()
                buffer += data.decode("utf-8", errors="ignore")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    print(f"[{addr[0]}] {line}")

                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        print("Skip non-JSON line")
                        continue

                    machine_no = obj.get("machine_no")
                    state = obj.get("state")
                    shot = obj.get("shot")

                    if machine_no is None or state is None or shot is None:
                        print("Skip incomplete JSON")
                        continue

                    last_machine_no = machine_no
                    if state != "reconnection":
                        last_shot = shot

                    update_presence(machine_no, state, last_shot, ip=addr[0])

                    # Heartbeat — keep link only, no DB/log
                    if state == "heartbeat":
                        print(f"Heartbeat OK · {machine_no} · from {addr[0]} · active={active_count()}")
                        try:
                            client.sendall(b"OK\n")
                        except Exception:
                            print(f"ACK failed after heartbeat — {addr}")
                            return
                        continue

                    insert_row(machine_no, state, shot)
                    append_log(machine_no, state, shot)

                    if state == "reconnection":
                        print(f"Reconnect logged · {machine_no} count={shot}")
                    else:
                        print(f"Inserted · {machine_no} · {state}")

                    try:
                        client.sendall(b"OK\n")
                    except Exception as ack_err:
                        print(f"ACK failed — {addr}: {ack_err}")
                        return

            except socket.timeout:
                idle = time.time() - last_data_time
                # No PING — ESP heartbeat keeps the link alive.
                # Only drop if heartbeats stop for too long.
                if idle >= IDLE_DISCONNECT_SEC:
                    print(f"No data from {addr[0]} for {idle:.0f}s — disconnecting idle client")
                    break
                continue

            except ConnectionResetError:
                print(f"Connection reset by ESP {addr}")
                break

            except OSError as e:
                print(f"Socket Error {addr}: {e}")
                break

            except Exception as e:
                print(f"Unexpected Error {addr}: {e}")
                break
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

        # Tell dashboard this machine went offline
        if last_machine_no:
            try:
                insert_row(last_machine_no, "disconnected", last_shot)
                append_log(last_machine_no, "disconnected", last_shot)
                update_presence(last_machine_no, "disconnected", last_shot, ip=addr[0])
                print(f"Logged disconnected · {last_machine_no}")
            except Exception as e:
                print(f"Failed to log disconnect: {e}")

        n, ips = unregister_client(addr)
        print(f"Client Disconnected : {addr}")
        print(f"Active boards left  : {n} → {ips}\n")


# -----------------------------
# TCP Server — one thread per ESP (all boards at once)
# -----------------------------
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
enable_keepalive(server)
server.bind((HOST, PORT))
server.listen(10)

print(f"Listening on {HOST}:{PORT}")
print("Multi-board mode: each ESP gets its own thread")
print("Waiting for ESP32 boards...\n")

while True:
    client, addr = server.accept()
    t = threading.Thread(target=handle_client, args=(client, addr), daemon=True)
    t.start()
