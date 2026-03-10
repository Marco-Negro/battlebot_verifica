import requests
import time
import threading
import socket
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════
# GHOST_2 — ALLEATO / ESCA
# Ascolta sulla porta 9002
# Comportamento:
#   - Sempre INVISIBILE di default
#   - Quando riceve segnale FIRE da Shooter_v1 →
#     diventa visibile per UN solo ping → torna invisibile
#   - NON spara MAI a nessuno
#   - NON spara MAI a Shooter_v1
# ═══════════════════════════════════════════════════════════════════
SYNC_PORT = 9002
BASE_URL  = "https://sososisi.isonlab.net/api"
BOT_NAME  = "Ghost_2"


# ═══════════════════════════════════════════════════════════════════
# SYNC SERVER — ascolta segnali da Ghost_lastV
# ═══════════════════════════════════════════════════════════════════
class SyncListener:
    def __init__(self, port):
        self.port       = port
        self.fire_event = threading.Event()
        self._start()

    def _start(self):
        def _server():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.port))
            srv.listen(1)
            print(f"[SYNC] 👂 Ghost_2 in ascolto su porta {self.port}...")
            conn, _ = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[SYNC] ✅ Shooter_v1 connesso!")
            buf = ""
            while True:
                try:
                    data = conn.recv(64).decode()
                    if not data:
                        break
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if line.strip() == "FIRE":
                            print("[SYNC] 📡 Segnale FIRE ricevuto → visibile prossimo ping")
                            self.fire_event.set()
                except Exception as e:
                    print(f"[SYNC] Errore: {e}")
                    break
        threading.Thread(target=_server, daemon=True).start()

    def should_be_visible(self):
        if self.fire_event.is_set():
            self.fire_event.clear()
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════
class BattleAPI:
    def __init__(self):
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5, pool_maxsize=5, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Connection": "keep-alive",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })

    def auth(self, name):
        return self.session.get(f"{BASE_URL}/auth", params={"name": name}, timeout=5).json()

    def ping(self, code, visible=False):
        v = "visible" if visible else "invisible"
        return self.session.get(f"{BASE_URL}/ping",
            params={"code": code, "visible": v}, timeout=5).json()


# ═══════════════════════════════════════════════════════════════════
# STATO
# ═══════════════════════════════════════════════════════════════════
class AllyState:
    def __init__(self, name):
        self.name        = name
        self.code        = None
        self.iteration   = 0
        self.round_start = time.time()

    def reset(self, new_code):
        self.code        = new_code
        self.iteration   = 0
        self.round_start = time.time()

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return (next_ping - datetime.now(timezone.utc)).total_seconds()
        except:
            return 5.0

    def round_elapsed(self):
        return time.time() - self.round_start


# ═══════════════════════════════════════════════════════════════════
# LOGIN
# ═══════════════════════════════════════════════════════════════════
def login(api, state):
    for attempt in range(1, 4):
        try:
            print(f"\n[*] Auth {attempt}/3 — '{state.name}'...")
            res = api.auth(state.name)
            if res.get("ok"):
                state.reset(res["code"])
                print(f"[V] {state.name} OK. Code: {state.code}")
                next_ping_at = res.get("nextPingAt")
                ping_every   = res.get("pingEverySeconds", 5)
                wait = state.seconds_until(next_ping_at) - 0.05 if next_ping_at else ping_every - 0.05
                if wait > 0: time.sleep(wait)
                return True
            else:
                print(f"[!] Rifiutata: {res}")
        except Exception as e:
            print(f"[!] Errore: {e}")
        time.sleep(2.0)
    return False


# ═══════════════════════════════════════════════════════════════════
# LOOP ALLEATO
# ═══════════════════════════════════════════════════════════════════
def ally_loop(api, state, sync):
    if not login(api, state):
        print("[!!] Auth fallita.")
        return

    while True:
        state.iteration += 1

        visible_now = sync.should_be_visible()
        stato = "👁️  VISIBILE (SYNC)" if visible_now else "👻 INVISIBILE"

        try:
            ping_res = api.ping(state.code, visible=visible_now)
            print(f"[{state.name}] PING #{state.iteration} | {stato} | t={int(state.round_elapsed())}s")
        except Exception as e:
            print(f"[!] Ping error: {e}")
            ping_res = None

        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "no risposta"
            print(f"[!] Ping fallito: {motivo}")
            time.sleep(2.0)
            if not login(api, state): time.sleep(5.0)
            continue

        next_ping_at = ping_res.get("nextPingAt")

        # ── NESSUNA AZIONE — solo ping, mai spara ─────────────────
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.05
            if wait > 0:
                time.sleep(wait)
        else:
            time.sleep(4.95)


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("═" * 50)
    print(f"  GHOST_2 — ALLEATO ESCA")
    print(f"  Porta sync: {SYNC_PORT}")
    print(f"  Comportamento: invisibile sempre,")
    print(f"  visibile solo su segnale FIRE da Shooter_v1")
    print("═" * 50)

    sync  = SyncListener(SYNC_PORT)
    api   = BattleAPI()
    state = AllyState(BOT_NAME)
    ally_loop(api, state, sync)
