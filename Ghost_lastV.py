import requests
import time
import threading
import socket
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════
# SYNC MASTER — Ghost_lastV manda segnale FIRE agli alleati
# Porta 9001 → Ghost_1 (cheatBot.py)
# Porta 9002 → Ghost_2 (BOT.py)
# ═══════════════════════════════════════════════════════════════════
SYNC_PORTS  = [9001, 9002]
BASE_URL    = "https://sososisi.isonlab.net/api"
ALLY_NAMES  = {"Ghost_1", "Ghost_2"}
MAX_THREADS = 50


def resolve_host(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        print(f"[DNS] {hostname} → {ip}")
    except Exception as e:
        print(f"[DNS] Fallback: {e}")


def build_sync_connections():
    """Connette ai socket degli alleati. Blocca finché non sono pronti."""
    conns = {}
    for port in SYNC_PORTS:
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(("127.0.0.1", port))
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conns[port] = s
                print(f"[SYNC] ✅ Alleato su porta {port} connesso")
                break
            except Exception:
                print(f"[SYNC] ⏳ Attendo alleato porta {port}...")
                time.sleep(1.0)
    return conns


def fire_signal(conns):
    """Manda segnale FIRE a tutti gli alleati contemporaneamente."""
    for port, s in conns.items():
        try:
            s.sendall(b"FIRE\n")
        except Exception as e:
            print(f"[SYNC] ⚠️  Porta {port}: {e}")


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
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=30, max=1000",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })

    def auth(self, name):
        return self.session.get(f"{BASE_URL}/auth", params={"name": name}, timeout=5).json()

    def ping(self, code, visible=True):
        return self.session.get(f"{BASE_URL}/ping",
            params={"code": code, "visible": "visible" if visible else "invisible"},
            timeout=5).json()

    def players(self, code):
        return self.session.get(f"{BASE_URL}/players", params={"code": code}, timeout=5).json()

    def fire(self, code, target_name):
        return self.session.get(f"{BASE_URL}/fire",
            params={"code": code, "target": target_name}, timeout=1).json()


# ═══════════════════════════════════════════════════════════════════
# STATO
# ═══════════════════════════════════════════════════════════════════
class BotState:
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
        self.ghost_cycles_left = 0
        self.prefetch_result   = None
        self.prefetch_lock     = threading.Lock()

    def reset(self, new_code):
        self.code              = new_code
        self.iteration         = 0
        self.round_start       = time.time()
        self.kill_target_lock  = None
        self.ghost_cycles_left = 0
        self.prefetch_result   = None

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return (next_ping - datetime.now(timezone.utc)).total_seconds()
        except:
            return 5.0

    def round_elapsed(self):
        return time.time() - self.round_start

    def should_go_ghost(self):
        if self.ghost_cycles_left > 0:
            self.ghost_cycles_left -= 1
            return True
        if self.my_score < -50:
            self.ghost_cycles_left = 2
            print(f"[GHOST] 🚨 Score {self.my_score} → 2 cicli ghost")
            return True
        return False

    def update_kill_lock(self, players):
        visibili = [p for p in players
            if p["name"] != self.name
            and p["name"] not in ALLY_NAMES
            and p.get("visible")]
        if not visibili:
            self.kill_target_lock = None
            return
        leader = max(visibili, key=lambda x: x.get("score", 0))
        if self.kill_target_lock is None:
            self.kill_target_lock = leader["name"]
            self.kill_lock_score  = leader.get("score", 0)
            print(f"[KILL LOCK] 🔒 {self.kill_target_lock} (score={self.kill_lock_score})")
        else:
            lock_visible = any(p["name"] == self.kill_target_lock and p.get("visible") for p in players)
            if not lock_visible or leader.get("score", 0) > self.kill_lock_score + 10:
                self.kill_target_lock = leader["name"]
                self.kill_lock_score  = leader.get("score", 0)
                print(f"[KILL LOCK] 🔄 → {self.kill_target_lock}")

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
                and p["name"] not in ALLY_NAMES
                and p.get("visible")]
            for nome in sospettati:
                self.hit_by[nome] = self.hit_by.get(nome, 0) + abs(delta)
            print(f"[VENDETTA] 😤 -{abs(delta)} → {sospettati}")

    def pick_targets(self, players):
        """
        Nemici reali: kill lock → vendetta → score.
        Alleati visibili: colpiti in fondo (punti garantiti).
        """
        nemici = [p for p in players
            if p["name"] != self.name
            and p["name"] not in ALLY_NAMES
            and p.get("visible")]

        alleati_visibili = [p for p in players
            if p["name"] in ALLY_NAMES and p.get("visible")]

        ordered   = []
        remaining = list(nemici)

        if self.kill_target_lock:
            lock = next((t for t in remaining if t["name"] == self.kill_target_lock), None)
            if lock:
                ordered.append(lock)
                remaining = [t for t in remaining if t["name"] != self.kill_target_lock]
                print(f"[KILL LOCK] 🎯 {lock['name']} (score={lock.get('score',0)})")

        vendetta = sorted([t for t in remaining if t["name"] in self.hit_by],
            key=lambda x: self.hit_by.get(x["name"], 0), reverse=True)
        altri    = sorted([t for t in remaining if t["name"] not in self.hit_by],
            key=lambda x: x.get("score", 0), reverse=True)

        if vendetta:
            print(f"[VENDETTA] 🎯 {[t['name'] for t in vendetta]}")
        if alleati_visibili:
            print(f"[ALLY HIT] 🤝 {[t['name'] for t in alleati_visibili]} — punti garantiti")

        return ordered + vendetta + altri + alleati_visibili


# ═══════════════════════════════════════════════════════════════════
# PREFETCH
# ═══════════════════════════════════════════════════════════════════
def prefetch_players(api, state):
    try:
        res = api.players(state.code)
        with state.prefetch_lock:
            state.prefetch_result = res
    except:
        pass


def get_players(api, state):
    with state.prefetch_lock:
        cached = state.prefetch_result
        state.prefetch_result = None
    if cached and cached.get("ok"):
        print("[PREFETCH] ⚡ Da cache")
        return cached.get("players", [])
    try:
        res = api.players(state.code)
        if res.get("ok"):
            return res.get("players", [])
    except Exception as e:
        print(f"[!] Errore players: {e}")
    return []


# ═══════════════════════════════════════════════════════════════════
# RAFFICA
# ═══════════════════════════════════════════════════════════════════
def fire_worker(api, code, target_name, results, index):
    try:
        res = api.fire(code, target_name)
        results[index] = res
        print(f"[T-{index}] {'✅' if res.get('ok') else '❌'} {target_name}")
    except Exception as e:
        results[index] = {"ok": False, "error": str(e)}


def execute_raffica(api, state, targets, next_ping_at):
    targets = targets[:MAX_THREADS]
    results = [None] * len(targets)
    threads = [threading.Thread(
        target=fire_worker,
        args=(api, state.code, t["name"], results, i),
        daemon=True) for i, t in enumerate(targets)]
    print(f"[RAFFICA] 🚀 {len(threads)} thread...")
    for t in threads: t.start()
    timeout = max(0.2, state.seconds_until(next_ping_at) - 0.2)
    for t in threads: t.join(timeout=timeout)
    fired = sum(1 for r in results if r and r.get("ok"))
    print(f"[RAFFICA] ✅ {fired}/{len(targets)} | score={state.my_score}")


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
                print(f"[V] OK. Code: {state.code}")
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
# LOOP PRINCIPALE
# ═══════════════════════════════════════════════════════════════════
def bot_loop(api, state, sync_conns):
    if not login(api, state):
        print("[!!] Auth fallita.")
        return

    while True:
        state.iteration += 1
        go_ghost    = state.should_go_ghost()
        visible_now = not go_ghost

        try:
            ping_res = api.ping(state.code, visible=visible_now)
            print(f"[Shooter_v1] PING #{state.iteration} | score={state.my_score} | t={int(state.round_elapsed())}s")
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

        if visible_now:
            time.sleep(0.05)

            # ── SEGNALE SYNC ─────────────────────────────────────
            # Manda FIRE agli alleati → si rendono visibili nel loro ping
            print("[SYNC] 📡 FIRE signal → Ghost_1, Ghost_2")
            fire_signal(sync_conns)
            time.sleep(0.3)  # aspetta che gli alleati facciano ping visibile

            players = get_players(api, state)
            if players:
                state.update_score_and_vendetta(players)
                state.update_kill_lock(players)
                targets = state.pick_targets(players)
                if targets:
                    execute_raffica(api, state, targets, next_ping_at)
                else:
                    print("[~] Nessun target.")
            else:
                print("[~] Round non attivo.")
        else:
            print("[Shooter_v1] 👻 Ghost.")

        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.05
            if wait > 0.5:
                pd = wait * 0.6
                threading.Thread(target=lambda d=pd: (time.sleep(d), prefetch_players(api, state)), daemon=True).start()
                time.sleep(wait)
            elif wait > 0:
                time.sleep(wait)
        else:
            time.sleep(4.95)


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    resolve_host("sososisi.isonlab.net")
    print("═" * 55)
    print("  SHOOTER_V1 — MASTER")
    print("  Avvia prima cheatBot.py e BOT.py,")
    print("  poi lancia questo file.")
    print("═" * 55)
    sync_conns = build_sync_connections()
    print("[SYNC] Tutti connessi — partenza!")
    api   = BattleAPI()
    state = BotState("Shooter_v1")
    bot_loop(api, state, sync_conns)
