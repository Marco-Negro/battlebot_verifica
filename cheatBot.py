import requests
import time
import threading
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════
# CLASSE: comunicazione con il server
# ═══════════════════════════════════════════════════════════════════
class BattleAPI:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session  = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=0
        )
        self.session.mount("https://", adapter)

    def auth(self, name):
        return self.session.get(f"{self.base_url}/auth",
            params={"name": name}, timeout=5).json()

    def ping(self, code, visible=True):  # ── SEMPRE VISIBILE
        return self.session.get(f"{self.base_url}/ping",
            params={"code": code, "visible": "visible"},
            timeout=5).json()

    def players(self, code):
        return self.session.get(f"{self.base_url}/players",
            params={"code": code}, timeout=5).json()

    def fire(self, code, target_name):
        return self.session.get(f"{self.base_url}/fire",
            params={"code": code, "target": target_name},
            timeout=1).json()


# ═══════════════════════════════════════════════════════════════════
# CLASSE: stato del bot — PURO ATTACCO, ZERO DIFESA
# ═══════════════════════════════════════════════════════════════════
class BotState:
    def __init__(self, name):
        self.name             = name
        self.code             = None
        self.iteration        = 0
        self.my_score         = 0
        self.prev_score       = 0
        self.hit_by           = {}         # vendetta tracker
        self.kill_target_lock = None
        self.kill_lock_score  = 0
        self.round_start      = time.time()

    def reset(self, new_code):
        self.code             = new_code
        self.iteration        = 0
        self.round_start      = time.time()
        self.kill_target_lock = None

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return (next_ping - datetime.now(timezone.utc)).total_seconds()
        except:
            return 5.0

    def round_elapsed(self):
        return time.time() - self.round_start

    def update_kill_lock(self, players):
        """Locka il leader e non lo molla finché non sparisce."""
        visibili = [p for p in players
            if p["name"] != self.name and p.get("visible")]
        if not visibili:
            self.kill_target_lock = None
            return
        leader = max(visibili, key=lambda x: x.get("score", 0))
        if self.kill_target_lock is None:
            self.kill_target_lock = leader["name"]
            self.kill_lock_score  = leader.get("score", 0)
            print(f"[KILL LOCK] 🔒 {self.kill_target_lock} (score={self.kill_lock_score})")
        else:
            lock_visible = any(
                p["name"] == self.kill_target_lock and p.get("visible")
                for p in players
            )
            nuovo_score = leader.get("score", 0)
            if not lock_visible or nuovo_score > self.kill_lock_score + 3:
                self.kill_target_lock = leader["name"]
                self.kill_lock_score  = nuovo_score
                print(f"[KILL LOCK] 🔄 {self.kill_target_lock} (score={self.kill_lock_score})")

    def update_score_and_vendetta(self, players):
        self.prev_score = self.my_score
        for p in players:
            if p["name"] == self.name:
                self.my_score = p.get("score", self.my_score)
                break
        delta = self.my_score - self.prev_score
        if delta < 0:
            sospettati = [p["name"] for p in players
                if p["name"] != self.name and p.get("visible")]
            for nome in sospettati:
                self.hit_by[nome] = self.hit_by.get(nome, 0) + abs(delta)
            print(f"[VENDETTA] 😤 -{abs(delta)} → {sospettati}")

    def pick_targets(self, players):
        """
        Ordine di fuoco:
        1. Kill lock (leader assoluto)
        2. Vendetta (chi ci ha fatto più danno)
        3. Tutti gli altri visibili per score decrescente
        """
        targets = [p for p in players
            if p["name"] != self.name and p.get("visible")]
        if not targets:
            return []

        ordered = []

        # 1. Kill lock sempre primo
        if self.kill_target_lock:
            lock = next((t for t in targets
                if t["name"] == self.kill_target_lock), None)
            if lock:
                ordered.append(lock)
                targets = [t for t in targets
                    if t["name"] != self.kill_target_lock]
                print(f"[KILL LOCK] 🎯 {lock['name']} (score={lock.get('score',0)})")

        # 2. Vendetta
        vendetta = sorted(
            [t for t in targets if t["name"] in self.hit_by],
            key=lambda x: self.hit_by.get(x["name"], 0), reverse=True
        )
        # 3. Altri per score
        altri = sorted(
            [t for t in targets if t["name"] not in self.hit_by],
            key=lambda x: x.get("score", 0), reverse=True
        )

        if vendetta:
            print(f"[VENDETTA] 🎯 {[t['name'] for t in vendetta]}")

        return ordered + vendetta + altri


# ═══════════════════════════════════════════════════════════════════
# RAFFICA PARALLELA — tutti i thread partono insieme
# ═══════════════════════════════════════════════════════════════════
def fire_worker(api, code, target_name, results, index):
    try:
        res = api.fire(code, target_name)
        results[index] = res
        print(f"[T-{index}] {'✅' if res.get('ok') else '❌'} {target_name}")
    except Exception as e:
        results[index] = {"ok": False, "error": str(e)}


def execute_raffica(api, state, targets, next_ping_at):
    results = [None] * len(targets)
    threads = [
        threading.Thread(
            target=fire_worker,
            args=(api, state.code, t["name"], results, i),
            daemon=True
        )
        for i, t in enumerate(targets)
    ]
    print(f"[RAFFICA] 🚀 {len(threads)} thread...")
    for t in threads: t.start()

    timeout = max(0.2, state.seconds_until(next_ping_at) - 0.2)
    for t in threads: t.join(timeout=timeout)

    fired = sum(1 for r in results if r and r.get("ok"))
    print(f"[RAFFICA] ✅ {fired}/{len(targets)}")


# ═══════════════════════════════════════════════════════════════════
# MAIN — loop pulito, zero logica difensiva
# ═══════════════════════════════════════════════════════════════════
def login(api, state):
    for attempt in range(1, 4):
        try:
            print(f"\n[*] Auth {attempt}/3 come '{state.name}'...")
            res = api.auth(state.name)
            print(f"[DEBUG AUTH] raw: {res}")
            if res.get("ok"):
                state.reset(res["code"])
                print(f"[V] Auth OK. Code: {state.code}")
                next_ping_at = res.get("nextPingAt")
                ping_every   = res.get("pingEverySeconds", 5)
                wait = state.seconds_until(next_ping_at) - 0.05 if next_ping_at else ping_every - 0.05
                if wait > 0: time.sleep(wait)
                return True
            else:
                print(f"[!] Auth rifiutata: {res}")
        except Exception as e:
            print(f"[!] Errore auth: {e}")
        time.sleep(2.0)
    print("[!!] Auth fallita.")
    return False


def do_ping(api, state):
    try:
        res = api.ping(state.code)
        print(f"[PING] score={state.my_score} | t={int(state.round_elapsed())}s | {res}")
        return res
    except Exception as e:
        print(f"[!] Errore ping: {e}")
        return None


def do_blitz(api, state, next_ping_at):
    try:
        res = api.players(state.code)
    except Exception as e:
        print(f"[!] Errore players: {e}")
        return
    if not res.get("ok"):
        print("[~] Round non attivo.")
        return
    players = res.get("players", [])
    state.update_score_and_vendetta(players)
    state.update_kill_lock(players)
    targets = state.pick_targets(players)
    if not targets:
        print("[~] Nessun target visibile.")
        return
    execute_raffica(api, state, targets, next_ping_at)


def run(api, state):
    if not login(api, state):
        print("[!!] Impossibile autenticarsi.")
        return

    while True:
        state.iteration += 1

        # ── PING — sempre visibile, nessuna eccezione ─────────────
        ping_res = do_ping(api, state)
        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "nessuna risposta"
            print(f"[!] Ping fallito #{state.iteration}: {motivo}")
            time.sleep(2.0)
            if not login(api, state): time.sleep(5.0)
            continue

        next_ping_at = ping_res.get("nextPingAt")
        print(f"[OK] #{state.iteration} | 🎯 FULL ATTACK | score={state.my_score}")

        # ── BLITZ — ogni ciclo, nessuna eccezione ─────────────────
        time.sleep(0.05)
        do_blitz(api, state, next_ping_at)

        # ── SLEEP PRECISO ─────────────────────────────────────────
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.05
            if wait > 0:
                print(f"[~] Sleep {wait:.2f}s\n")
                time.sleep(wait)
            else:
                print("[!] In ritardo.")
        else:
            time.sleep(4.95)


if __name__ == "__main__":
    api   = BattleAPI("https://sososisi.isonlab.net/api")
    state = BotState("Ghost_v7")
    run(api, state)