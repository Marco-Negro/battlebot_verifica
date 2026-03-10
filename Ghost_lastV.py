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
ALLY_NAMES  = {"BOT", "CheatBot"}
MAX_THREADS = 50


def resolve_host(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        print(f"[DNS] {hostname} → {ip}")
    except Exception as e:
        print(f"[DNS] Fallback: {e}")


def build_sync_connections():
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
            pool_connections=MAX_THREADS + 10,
            pool_maxsize=MAX_THREADS + 10,
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

    def reset(self, new_code):
        self.code              = new_code
        self.iteration         = 0
        self.round_start       = time.time()
        self.kill_target_lock  = None
        self.ghost_cycles_left = 0

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
            print(f"[ALLY HIT] 🤝 {[t['name'] for t in alleati_visibili]}")

        return ordered + vendetta + altri + alleati_visibili


# ═══════════════════════════════════════════════════════════════════
# RAFFICA — 50 thread
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
    attempt = 0
    while True:
        attempt += 1
        try:
            print(f"\n[*] Auth #{attempt} — '{state.name}'...")
            res = api.auth(state.name)
            if res.get("ok"):
                state.reset(res["code"])
                print(f"[V] OK. Code: {state.code}")
                next_ping_at = res.get("nextPingAt")
                ping_every   = res.get("pingEverySeconds", 5)
                wait = state.seconds_until(next_ping_at) - 0.10 if next_ping_at else ping_every - 0.10
                if wait > 0: time.sleep(wait)
                return True
            else:
                print(f"[!] Rifiutata: {res}")
        except Exception as e:
            print(f"[!] Errore: {e}")
        time.sleep(2.0)


# ═══════════════════════════════════════════════════════════════════
# LOOP PRINCIPALE
#
# OTTIMIZZAZIONE: /players parte IN PARALLELO al ping
# ──────────────────────────────────────────────────────────────────
# PRIMA (sequenziale):
#   ping [~100ms] → /players [~100ms] → fire
#   tempo perso: ~200ms
#
# ORA (parallelo):
#   ping     [~100ms] ──┐
#   /players [~100ms] ──┘ partono insieme
#   → risparmio ~100ms per ciclo
# ═══════════════════════════════════════════════════════════════════
def bot_loop(api, state, sync_conns):
    login(api, state)

    while True:
        state.iteration += 1
        go_ghost    = state.should_go_ghost()
        visible_now = not go_ghost

        # Contenitore condiviso per il risultato di /players parallelo
        players_result = [None]
        players_ready  = threading.Event()

        def fetch_players_parallel():
            try:
                res = api.players(state.code)
                players_result[0] = res
            except Exception as e:
                print(f"[!] /players parallelo: {e}")
            finally:
                players_ready.set()

        # ── LANCIA /players e ping CONTEMPORANEAMENTE ─────────────
        if visible_now:
            threading.Thread(target=fetch_players_parallel, daemon=True).start()

        # Ping bloccante — obbligatorio prima di sparare
        try:
            ping_res = api.ping(state.code, visible=visible_now)
            print(f"[Shooter_v1] PING #{state.iteration} | score={state.my_score} | t={int(state.round_elapsed())}s")
        except Exception as e:
            print(f"[!] Ping error: {e}")
            ping_res = None
            players_ready.set()

        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "no risposta"
            print(f"[!] Ping fallito: {motivo}")
            time.sleep(2.0)
            login(api, state)
            continue

        next_ping_at = ping_res.get("nextPingAt")

        if visible_now:
            # Attendi /players (solitamente già pronto, ping e players ~stesso tempo)
            players_ready.wait(timeout=0.3)
            pd = players_result[0]
            players = pd.get("players", []) if (pd and pd.get("ok")) else []

            # Fallback se parallelo ha fallito
            if not players:
                try:
                    r = api.players(state.code)
                    players = r.get("players", []) if r.get("ok") else []
                except:
                    players = []

            if players:
                state.update_score_and_vendetta(players)
                state.update_kill_lock(players)

                # Segnale FIRE agli alleati → diventano visibili
                print("[SYNC] 📡 FIRE → Ghost_1, Ghost_2")
                fire_signal(sync_conns)
                time.sleep(0.3)  # tempo per ping visibile degli alleati

                # Ri-fetch players per vedere alleati appena diventati visibili
                try:
                    r2 = api.players(state.code)
                    if r2.get("ok"):
                        players = r2.get("players", players)
                except:
                    pass

                targets = state.pick_targets(players)
                if targets:
                    execute_raffica(api, state, targets, next_ping_at)
                else:
                    print("[~] Nessun target.")
            else:
                print("[~] Round non attivo.")
        else:
            print("[Shooter_v1] 👻 Ghost.")

        # ── SLEEP + PREFETCH ──────────────────────────────────────
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.10
            if wait > 0.5:
                pd2 = wait * 0.7
                def _pre(d=pd2):
                    time.sleep(d)
                    try:
                        res = api.players(state.code)
                        players_result[0] = res
                    except:
                        pass
                threading.Thread(target=_pre, daemon=True).start()
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
