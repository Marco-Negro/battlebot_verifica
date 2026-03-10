import requests
import time
import threading
import socket
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════
# PRE-RESOLVE DNS — elimina lookup ad ogni richiesta
# ═══════════════════════════════════════════════════════════════════
def resolve_host(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        print(f"[DNS] {hostname} → {ip}")
        return ip
    except Exception as e:
        print(f"[DNS] Fallback hostname: {e}")
        return hostname


# ═══════════════════════════════════════════════════════════════════
# CLASSE: comunicazione con il server
# CHEAT TECNICO 1: DNS pre-resolved + Keep-Alive esplicito
# CHEAT TECNICO 2: headers ottimizzati per zero overhead
# ═══════════════════════════════════════════════════════════════════
class BattleAPI:
    def __init__(self, base_url, hostname):
        self.base_url = base_url
        self.hostname = hostname
        self.session  = requests.Session()

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=0
        )
        self.session.mount("https://", adapter)

        # ── Keep-Alive esplicito + header ottimizzati ─────────────
        self.session.headers.update({
            "Connection":   "keep-alive",
            "Keep-Alive":   "timeout=30, max=1000",
            "Accept":       "application/json",
            # Dice al server di non comprimere → meno CPU, meno latenza
            "Accept-Encoding": "identity",
        })

    def auth(self, name):
        return self.session.get(f"{self.base_url}/auth",
            params={"name": name}, timeout=5).json()

    def ping(self, code, visible=True):
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
# CLASSE: stato del bot
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

        # ── CHEAT META: cache players ─────────────────────────────
        # Salva l'ultima lista players valida.
        # Se /players fallisce o il round non è attivo,
        # usa la cache per non perdere il ciclo.
        self.players_cache     = []
        self.cache_iteration   = 0  # quando è stata aggiornata

        # ── CHEAT META: preemptive players ───────────────────────
        # Thread che chiama /players in anticipo durante il sleep
        self.prefetch_result   = None
        self.prefetch_lock     = threading.Lock()

    def reset(self, new_code):
        self.code              = new_code
        self.iteration         = 0
        self.round_start       = time.time()
        self.kill_target_lock  = None
        self.ghost_cycles_left = 0
        self.players_cache     = []
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
            print(f"[GHOST] 🚨 Score {self.my_score} → 2 cicli difensivi")
            return True
        return False

    def update_kill_lock(self, players):
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
                if p["name"] != self.name and p.get("visible")]
            for nome in sospettati:
                self.hit_by[nome] = self.hit_by.get(nome, 0) + abs(delta)
            print(f"[VENDETTA] 😤 -{abs(delta)} → {sospettati}")

    def pick_targets(self, players):
        targets = [p for p in players
            if p["name"] != self.name and p.get("visible")]
        if not targets:
            return []
        ordered   = []
        remaining = list(targets)
        if self.kill_target_lock:
            lock = next((t for t in remaining
                if t["name"] == self.kill_target_lock), None)
            if lock:
                ordered.append(lock)
                remaining = [t for t in remaining
                    if t["name"] != self.kill_target_lock]
                print(f"[KILL LOCK] 🎯 {lock['name']} (score={lock.get('score',0)})")
        vendetta = sorted(
            [t for t in remaining if t["name"] in self.hit_by],
            key=lambda x: self.hit_by.get(x["name"], 0), reverse=True
        )
        altri = sorted(
            [t for t in remaining if t["name"] not in self.hit_by],
            key=lambda x: x.get("score", 0), reverse=True
        )
        if vendetta:
            print(f"[VENDETTA] 🎯 {[t['name'] for t in vendetta]}")
        return ordered + vendetta + altri


# ═══════════════════════════════════════════════════════════════════
# CHEAT META: PREFETCH PLAYERS
# Chiama /players durante il sleep del ciclo precedente.
# Quando arriva il momento di sparare, i target sono già pronti.
# Guadagno: ~100-200ms in meno di latenza percepita per ciclo.
# ═══════════════════════════════════════════════════════════════════
def prefetch_players(api, state):
    """Eseguito in thread durante il sleep — popola prefetch_result."""
    try:
        res = api.players(state.code)
        with state.prefetch_lock:
            state.prefetch_result = res
    except Exception as e:
        with state.prefetch_lock:
            state.prefetch_result = None


def get_players(api, state):
    """
    Usa il risultato prefetchato se disponibile e fresco.
    Altrimenti fa la chiamata normale.
    """
    with state.prefetch_lock:
        cached = state.prefetch_result
        state.prefetch_result = None  # consuma il cache

    if cached and cached.get("ok"):
        print("[PREFETCH] ⚡ Players da cache prefetch")
        return cached.get("players", [])

    # Fallback: chiamata diretta
    try:
        res = api.players(state.code)
        if res.get("ok"):
            return res.get("players", [])
    except Exception as e:
        print(f"[!] Errore players: {e}")
    return []


# ═══════════════════════════════════════════════════════════════════
# RAFFICA PARALLELA
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
    print(f"[RAFFICA] ✅ {fired}/{len(targets)} | score={state.my_score}")


# ═══════════════════════════════════════════════════════════════════
# CHEAT IBRIDO: DUE ISTANZE IN PARALLELO
# Bot A (Ghost_V4)  → kill lock sul leader
# Bot B (Ghost_V4b) → kill lock sul secondo + vendetta
# Girano in thread separati, condividono zero stato.
# Il server li vede come due giocatori distinti.
# ═══════════════════════════════════════════════════════════════════
def login(api, state):
    for attempt in range(1, 4):
        try:
            print(f"\n[*] Auth {attempt}/3 come '{state.name}'...")
            res = api.auth(state.name)
            if res.get("ok"):
                state.reset(res["code"])
                print(f"[V] {state.name} Auth OK. Code: {state.code}")
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
    return False


def do_ping(api, state, visible=True):
    try:
        res = api.ping(state.code, visible=visible)
        print(f"[{state.name}] PING #{state.iteration} | score={state.my_score} | t={int(state.round_elapsed())}s")
        return res
    except Exception as e:
        print(f"[!] Errore ping: {e}")
        return None


def do_blitz(api, state, next_ping_at):
    players = get_players(api, state)
    if not players:
        print("[~] Nessun player o round non attivo.")
        return
    state.update_score_and_vendetta(players)
    state.update_kill_lock(players)
    targets = state.pick_targets(players)
    if not targets:
        print("[~] Nessun target visibile.")
        return
    execute_raffica(api, state, targets, next_ping_at)


def bot_loop(api, state):
    """Loop principale di un singolo bot."""
    if not login(api, state):
        print(f"[!!] {state.name} — auth fallita.")
        return

    while True:
        state.iteration += 1
        go_ghost    = state.should_go_ghost()
        visible_now = not go_ghost

        ping_res = do_ping(api, state, visible=visible_now)
        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "nessuna risposta"
            print(f"[!] {state.name} ping fallito: {motivo}")
            time.sleep(2.0)
            if not login(api, state): time.sleep(5.0)
            continue

        next_ping_at = ping_res.get("nextPingAt")
        stato = "👻 GHOST" if go_ghost else "🎯 ATTACK"
        print(f"[{state.name}] {stato} | lock={state.kill_target_lock}")

        if visible_now:
            time.sleep(0.05)
            do_blitz(api, state, next_ping_at)
        else:
            print(f"[{state.name}] Ghost — nessuna azione.")

        # ── PREFETCH durante il sleep ─────────────────────────────
        # Lancia /players in background mentre aspetti il prossimo ping.
        # Al ciclo successivo i target sono già pronti.
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.05
            if wait > 0.5:
                # Lancia prefetch a metà del sleep
                prefetch_delay = wait * 0.6
                def _prefetch():
                    time.sleep(prefetch_delay)
                    prefetch_players(api, state)
                threading.Thread(target=_prefetch, daemon=True).start()
                print(f"[~] Sleep {wait:.2f}s | prefetch in {prefetch_delay:.2f}s")
                time.sleep(wait)
            elif wait > 0:
                time.sleep(wait)
            else:
                print("[!] In ritardo.")
        else:
            time.sleep(4.95)


# ═══════════════════════════════════════════════════════════════════
# MAIN — lancia due bot in thread separati
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    BASE_URL = "https://sososisi.isonlab.net/api"
    HOSTNAME = "sososisi.isonlab.net"

    # DNS pre-resolve una volta sola
    resolve_host(HOSTNAME)

    # ── Bot A: kill lock aggressivo sul leader ────────────────────
    api_a   = BattleAPI(BASE_URL, HOSTNAME)
    state_a = BotState("Ghost_V4")

    # ── Bot B: stesso codice, nome diverso ────────────────────────
    # Il server lo vede come giocatore separato.
    # Attacca gli stessi target da un secondo vettore.
    api_b   = BattleAPI(BASE_URL, HOSTNAME)
    state_b = BotState("Ghost_V4b")

    thread_a = threading.Thread(target=bot_loop, args=(api_a, state_a), daemon=False)
    thread_b = threading.Thread(target=bot_loop, args=(api_b, state_b), daemon=False)

    print("[ DUAL BOT ] Lancio Ghost_V4 + Ghost_V4b...")
    thread_a.start()

    # ── Offset di 2.5s tra i due bot ─────────────────────────────
    # Evita che i due bot mandino ping nello stesso istante
    # e che le loro raffiche si sovrappongano sul server.
    # Con offset 2.5s uno spara mentre l'altro dorme → copertura continua.
    time.sleep(2.5)
    thread_b.start()

    thread_a.join()
    thread_b.join()