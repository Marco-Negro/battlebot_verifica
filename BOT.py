import requests
import time
import threading
import socket
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════
# GHOST_2 — ALLEATO ATTIVO
# - Ascolta segnale FIRE da Shooter_v1 su porta 9002
# - Invisibile di default
# - Visibile solo quando riceve FIRE → fa ping visibile → torna invisibile
# - Spara a tutti i nemici visibili TRANNE Shooter_v1
# - /players lanciato IN PARALLELO al ping per risparmiare ~100ms
# ═══════════════════════════════════════════════════════════════════
SYNC_PORT   = 9002
BASE_URL    = "https://sososisi.isonlab.net/api"
BOT_NAME    = "Ghost_2"
NO_FIRE     = {"Shooter_v1"}   # MAI sparare al principale
MAX_THREADS = 50


# ═══════════════════════════════════════════════════════════════════
# SYNC LISTENER
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
            print(f"[SYNC] 👂 Ghost_2 in ascolto porta {self.port}...")
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
                            print("[SYNC] 📡 FIRE → visibile prossimo ping")
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
            pool_connections=MAX_THREADS + 5,
            pool_maxsize=MAX_THREADS + 5,
            max_retries=0
        )
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "Connection":      "keep-alive",
            "Keep-Alive":      "timeout=30, max=1000",
            "Accept":          "application/json",
            "Accept-Encoding": "identity",
        })

    def auth(self, name):
        return self.session.get(f"{BASE_URL}/auth", params={"name": name}, timeout=5).json()

    def ping(self, code, visible=False):
        v = "visible" if visible else "invisible"
        return self.session.get(f"{BASE_URL}/ping",
            params={"code": code, "visible": v}, timeout=5).json()

    def players(self, code):
        return self.session.get(f"{BASE_URL}/players", params={"code": code}, timeout=5).json()

    def fire(self, code, target_name):
        return self.session.get(f"{BASE_URL}/fire",
            params={"code": code, "target": target_name}, timeout=1).json()


# ═══════════════════════════════════════════════════════════════════
# STATO
# ═══════════════════════════════════════════════════════════════════
class AllyState:
    def __init__(self, name):
        self.name              = name
        self.code              = None
        self.iteration         = 0
        self.my_score          = 0
        self.prev_score        = 0
        self.hit_by            = {}
        self.round_start       = time.time()
        self.kill_target_lock  = None
        self.kill_lock_score   = 0

    def reset(self, new_code):
        self.code              = new_code
        self.iteration         = 0
        self.round_start       = time.time()
        self.kill_target_lock  = None

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return (next_ping - datetime.now(timezone.utc)).total_seconds()
        except:
            return 5.0

    def round_elapsed(self):
        return time.time() - self.round_start

    def update_kill_lock(self, players):
        visibili = [p for p in players
            if p["name"] != self.name
            and p["name"] not in NO_FIRE
            and p.get("visible")]
        if not visibili:
            self.kill_target_lock = None
            return
        leader = max(visibili, key=lambda x: x.get("score", 0))
        if self.kill_target_lock is None:
            self.kill_target_lock = leader["name"]
            self.kill_lock_score  = leader.get("score", 0)
            print(f"[{BOT_NAME}] KILL LOCK 🔒 {self.kill_target_lock}")
        else:
            lock_visible = any(p["name"] == self.kill_target_lock and p.get("visible") for p in players)
            if not lock_visible or leader.get("score", 0) > self.kill_lock_score + 10:
                self.kill_target_lock = leader["name"]
                self.kill_lock_score  = leader.get("score", 0)
                print(f"[{BOT_NAME}] KILL LOCK 🔄 → {self.kill_target_lock}")

    def update_score_and_vendetta(self, players):
        self.prev_score = self.my_score
        for p in players:
            if p["name"] == self.name:
                self.my_score = p.get("score", self.my_score)
                break
        delta = self.my_score - self.prev_score
        if delta < 0:
            sospettati = [p["name"] for p in players
                if p["name"] != self.name
                and p["name"] not in NO_FIRE
                and p.get("visible")]
            for nome in sospettati:
                self.hit_by[nome] = self.hit_by.get(nome, 0) + abs(delta)

    def pick_targets(self, players):
        targets = [p for p in players
            if p["name"] != self.name
            and p["name"] not in NO_FIRE   # MAI sparare a Shooter_v1
            and p.get("visible")]
        if not targets:
            return []
        ordered   = []
        remaining = list(targets)
        if self.kill_target_lock:
            lock = next((t for t in remaining if t["name"] == self.kill_target_lock), None)
            if lock:
                ordered.append(lock)
                remaining = [t for t in remaining if t["name"] != self.kill_target_lock]
        vendetta = sorted([t for t in remaining if t["name"] in self.hit_by],
            key=lambda x: self.hit_by.get(x["name"], 0), reverse=True)
        altri    = sorted([t for t in remaining if t["name"] not in self.hit_by],
            key=lambda x: x.get("score", 0), reverse=True)
        return ordered + vendetta + altri


# ═══════════════════════════════════════════════════════════════════
# RAFFICA
# ═══════════════════════════════════════════════════════════════════
def fire_worker(api, code, target_name, results, index):
    try:
        res = api.fire(code, target_name)
        results[index] = res
        print(f"[{BOT_NAME}] T-{index} {'✅' if res.get('ok') else '❌'} {target_name}")
    except Exception as e:
        results[index] = {"ok": False, "error": str(e)}


def execute_raffica(api, state, targets, next_ping_at):
    targets = targets[:MAX_THREADS]
    results = [None] * len(targets)
    threads = [threading.Thread(
        target=fire_worker,
        args=(api, state.code, t["name"], results, i),
        daemon=True) for i, t in enumerate(targets)]
    print(f"[{BOT_NAME}] RAFFICA 🚀 {len(threads)} thread...")
    for t in threads: t.start()
    timeout = max(0.2, state.seconds_until(next_ping_at) - 0.2)
    for t in threads: t.join(timeout=timeout)
    fired = sum(1 for r in results if r and r.get("ok"))
    print(f"[{BOT_NAME}] ✅ {fired}/{len(targets)} | score={state.my_score}")


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
                print(f"[V] {state.name} OK.")
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
#
# OTTIMIZZAZIONE: /players parte IN PARALLELO al ping
# Quando visibile=True (ciclo FIRE):
#   ping     [~100ms] ──┐
#   /players [~100ms] ──┘ partono insieme → risparmio ~100ms
# ═══════════════════════════════════════════════════════════════════
def ally_loop(api, state, sync):
    if not login(api, state):
        print("[!!] Auth fallita.")
        return

    while True:
        state.iteration += 1
        visible_now = sync.should_be_visible()

        players_result = [None]
        players_ready  = threading.Event()

        def fetch_players_parallel():
            try:
                res = api.players(state.code)
                players_result[0] = res
            except:
                pass
            finally:
                players_ready.set()

        # Lancia /players in parallelo solo quando visibile (spara)
        if visible_now:
            threading.Thread(target=fetch_players_parallel, daemon=True).start()

        # Ping bloccante
        try:
            ping_res = api.ping(state.code, visible=visible_now)
            stato = "👁️  VISIBILE+FIRE" if visible_now else "👻 invisibile"
            print(f"[{BOT_NAME}] PING #{state.iteration} | {stato} | t={int(state.round_elapsed())}s")
        except Exception as e:
            print(f"[!] Ping error: {e}")
            ping_res = None
            players_ready.set()

        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "no risposta"
            print(f"[!] Ping fallito: {motivo}")
            time.sleep(2.0)
            if not login(api, state): time.sleep(5.0)
            continue

        next_ping_at = ping_res.get("nextPingAt")

        # Spara solo quando visibile (ciclo FIRE)
        if visible_now:
            players_ready.wait(timeout=0.3)
            pd = players_result[0]
            players = pd.get("players", []) if (pd and pd.get("ok")) else []

            if not players:
                try:
                    r = api.players(state.code)
                    players = r.get("players", []) if r.get("ok") else []
                except:
                    players = []

            if players:
                state.update_score_and_vendetta(players)
                state.update_kill_lock(players)
                targets = state.pick_targets(players)
                if targets:
                    print(f"[{BOT_NAME}] 🎯 {[t['name'] for t in targets]}")
                    execute_raffica(api, state, targets, next_ping_at)
                else:
                    print(f"[{BOT_NAME}] Nessun target nemico.")

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
    print(f"  GHOST_2 — ALLEATO ATTIVO")
    print(f"  Porta sync: {SYNC_PORT}")
    print(f"  Non spara mai a: {NO_FIRE}")
    print("═" * 50)
    sync  = SyncListener(SYNC_PORT)
    api   = BattleAPI()
    state = AllyState(BOT_NAME)
    ally_loop(api, state, sync)
