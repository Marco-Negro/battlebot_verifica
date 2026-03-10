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

    def auth(self, name):
        return self.session.get(f"{self.base_url}/auth", params={"name": name}, timeout=5).json()

    def ping(self, code, visible=False):
        return self.session.get(f"{self.base_url}/ping",
            params={"code": code, "visible": "visible" if visible else "invisible"}, timeout=5).json()

    def players(self, code):
        return self.session.get(f"{self.base_url}/players", params={"code": code}, timeout=5).json()

    def fire(self, code, target_name):
        return self.session.get(f"{self.base_url}/fire",
            params={"code": code, "target": target_name}, timeout=3).json()


# ═══════════════════════════════════════════════════════════════════
# CLASSE: stato del bot
# ═══════════════════════════════════════════════════════════════════
class BotState:
    def __init__(self, name):
        self.name               = name
        self.code               = None
        self.iteration          = 0
        self.visible            = False
        self.my_score           = 0
        self.prev_score         = 0
        self.hit_by             = {}        # vendetta tracker
        self.shield_cycles      = 0         # score shield
        self.round_start        = time.time()
        self.burst_seconds      = 60

        # ── Decoy dinamico ────────────────────────────────────────
        # fire_every_n si aggiusta in base ai colpi ricevuti
        self.fire_every_n       = 3         # default: 1 ciclo su 3
        self.cycles_no_hit      = 0         # cicli consecutivi senza colpi ricevuti

        # ── Kill priority lock ────────────────────────────────────
        # Nome del leader lockato come target fisso
        self.kill_target_lock   = None
        self.kill_lock_score    = 0         # score del lockato quando è stato scelto

        # ── Camouflage adattivo ───────────────────────────────────
        # Flag: siamo diventati invisibili d'emergenza questo ciclo?
        self.camouflage_active  = False

        # ── First blood ───────────────────────────────────────────
        self.first_blood_window = 30        # secondi di fase aggressiva iniziale

    def reset(self, new_code):
        self.code               = new_code
        self.iteration          = 0
        self.round_start        = time.time()
        self.shield_cycles      = 0
        self.cycles_no_hit      = 0
        self.fire_every_n       = 3
        self.kill_target_lock   = None
        self.camouflage_active  = False

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return (next_ping - datetime.now(timezone.utc)).total_seconds()
        except:
            return 5.0

    def round_elapsed(self):
        return time.time() - self.round_start

    def is_burst_mode(self, round_duration=300):
        return self.round_elapsed() >= (round_duration - self.burst_seconds)

    def is_first_blood(self):
        """Primi N secondi: sempre visibile e aggressivo."""
        return self.round_elapsed() < self.first_blood_window

    def update_decoy(self, delta):
        """
        Decoy dinamico: aggiusta fire_every_n in base ai colpi ricevuti.
        Senza colpi da 3 cicli → più aggressivo (1/2).
        Colpi ricevuti         → più difensivo (1/3 o 1/4).
        """
        if delta < 0:
            # Stiamo ricevendo colpi → aumenta copertura
            self.cycles_no_hit = 0
            self.fire_every_n  = min(4, self.fire_every_n + 1)
            print(f"[DECOY] 🛡️  Colpi ricevuti → fire_every_n={self.fire_every_n}")
        else:
            self.cycles_no_hit += 1
            if self.cycles_no_hit >= 3:
                # Nessun colpo da 3 cicli → possiamo essere più aggressivi
                self.fire_every_n  = max(2, self.fire_every_n - 1)
                self.cycles_no_hit = 0
                print(f"[DECOY] ⚡ Zona sicura → fire_every_n={self.fire_every_n}")

    def update_kill_lock(self, players):
        """
        Kill priority: locka il leader come target fisso.
        Sblocca solo se il leader cambia o diventa invisibile.
        """
        visibili = [p for p in players if p["name"] != self.name and p.get("visible")]
        if not visibili:
            self.kill_target_lock = None
            return

        leader = max(visibili, key=lambda x: x.get("score", 0))

        if self.kill_target_lock is None:
            # Primo lock
            self.kill_target_lock = leader["name"]
            self.kill_lock_score  = leader.get("score", 0)
            print(f"[KILL LOCK] 🔒 Target lockato: {self.kill_target_lock} (score={self.kill_lock_score})")
        else:
            # Controlla se il lock è ancora valido
            lock_still_visible = any(
                p["name"] == self.kill_target_lock and p.get("visible")
                for p in players
            )
            nuovo_leader_score = leader.get("score", 0)

            if not lock_still_visible or nuovo_leader_score > self.kill_lock_score + 2:
                # Il lockato è sparito o c'è qualcuno molto più forte
                self.kill_target_lock = leader["name"]
                self.kill_lock_score  = nuovo_leader_score
                print(f"[KILL LOCK] 🔄 Nuovo lock: {self.kill_target_lock} (score={self.kill_lock_score})")

    def should_fire(self):
        """
        Priorità decisionale:
        1. First blood  → sempre spara (primi 30s)
        2. Burst finale → sempre spara (ultimi 60s)
        3. Camouflage   → override invisibile se siamo soli esposti
        4. Score shield → invisibile forzato se score < 0
        5. Decoy din.   → fire_every_n adattivo
        """
        # 1. First blood
        if self.is_first_blood():
            print(f"[FIRST BLOOD] ⚔️  t={int(self.round_elapsed())}s — attacco immediato!")
            return True

        # 2. Burst finale
        if self.is_burst_mode():
            print("[BURST] 🔥 Ultimi 60s — sempre visibile!")
            return True

        # 3. Camouflage adattivo (gestito in do_blitz dopo aver visto i players)
        if self.camouflage_active:
            print("[CAMOUFLAGE] 👻 Solo esposto → invisibile d'emergenza")
            self.camouflage_active = False  # reset per il ciclo dopo
            return False

        # 4. Score shield
        if self.my_score < 0 and self.shield_cycles < 2:
            self.shield_cycles += 1
            print(f"[SHIELD] ⛔ Score {self.my_score} → ghost forzato ({self.shield_cycles}/2)")
            return False
        if self.my_score >= 0:
            self.shield_cycles = 0

        # 5. Decoy dinamico
        return self.iteration % self.fire_every_n == 1

    def update_score_and_vendetta(self, players):
        self.prev_score = self.my_score
        for p in players:
            if p["name"] == self.name:
                self.my_score = p.get("score", self.my_score)
                break
        delta = self.my_score - self.prev_score
        if delta < 0:
            sospettati = [
                p["name"] for p in players
                if p["name"] != self.name and p.get("visible")
            ]
            for nome in sospettati:
                self.hit_by[nome] = self.hit_by.get(nome, 0) + abs(delta)
            print(f"[VENDETTA] 😤 -{abs(delta)} punti. Sospettati: {sospettati}")

        # Aggiorna decoy dinamico ad ogni ciclo
        self.update_decoy(delta)

    def check_camouflage(self, players):
        """
        Camouflage adattivo: se siamo gli unici visibili,
        setta il flag per diventare invisibili al prossimo ciclo.
        """
        altri_visibili = [
            p for p in players
            if p["name"] != self.name and p.get("visible")
        ]
        if len(altri_visibili) == 0:
            # Siamo gli unici visibili: tutti ci stanno puntando
            self.camouflage_active = True
            print(f"[CAMOUFLAGE] ⚠️  Siamo gli unici visibili! Attivo camouflage...")

    def pick_targets(self, players):
        """
        Ordine di fuoco:
        1. Kill lock (leader) — sempre primo se visibile
        2. Vendetta — chi ci ha colpito di più
        3. Score >= 0 → i più forti | Score < 0 → i più deboli
        """
        targets = [
            p for p in players
            if p["name"] != self.name and p.get("visible")
        ]
        if not targets:
            return []

        ordered = []

        # 1. Kill lock per primo
        if self.kill_target_lock:
            lock = next((t for t in targets if t["name"] == self.kill_target_lock), None)
            if lock:
                ordered.append(lock)
                targets = [t for t in targets if t["name"] != self.kill_target_lock]
                print(f"[KILL LOCK] 🎯 Primo fuoco su: {lock['name']}")

        # 2. Vendetta
        vendetta = sorted(
            [t for t in targets if t["name"] in self.hit_by],
            key=lambda x: self.hit_by.get(x["name"], 0), reverse=True
        )
        altri = [t for t in targets if t["name"] not in self.hit_by]

        if self.my_score >= 0:
            altri.sort(key=lambda x: x.get("score", 0), reverse=True)
        else:
            altri.sort(key=lambda x: x.get("score", 0), reverse=False)

        if vendetta:
            print(f"[VENDETTA] 🎯 Poi: {[t['name'] for t in vendetta]}")

        return ordered + vendetta + altri


# ═══════════════════════════════════════════════════════════════════
# RAFFICA PARALLELA
# ═══════════════════════════════════════════════════════════════════
def fire_worker(api, code, target_name, results, index):
    try:
        res = api.fire(code, target_name)
        results[index] = res
        esito = "✅" if res.get("ok") else "❌"
        print(f"[THREAD-{index}] {esito} -> {target_name} | {res}")
    except Exception as e:
        results[index] = {"ok": False, "error": str(e)}
        print(f"[THREAD-{index}] ❌ Errore -> {target_name}: {e}")


def execute_raffica(api, state, targets, next_ping_at):
    results = [None] * len(targets)
    threads = []

    print(f"[RAFFICA] 🚀 {len(targets)} thread simultanei...")

    for i, target in enumerate(targets):
        t = threading.Thread(
            target=fire_worker,
            args=(api, state.code, target["name"], results, i),
            daemon=True
        )
        threads.append(t)

    for t in threads:
        t.start()

    timeout = max(0.5, state.seconds_until(next_ping_at) - 0.6)
    for t in threads:
        t.join(timeout=timeout)

    fired   = sum(1 for r in results if r and r.get("ok"))
    missed  = sum(1 for r in results if r and not r.get("ok"))
    pending = sum(1 for r in results if r is None)
    print(f"[RAFFICA] colpiti={fired} | falliti={missed} | timeout={pending}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
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
                wait = state.seconds_until(next_ping_at) - 0.15 if next_ping_at else ping_every - 0.15
                print(f"[~] Attendo {wait:.2f}s prima del primo ping...")
                if wait > 0:
                    time.sleep(wait)
                return True
            else:
                print(f"[!] Auth rifiutata: {res}")
        except Exception as e:
            print(f"[!] Errore auth: {e}")
        time.sleep(2.0)
    print("[!!] Auth fallita dopo 3 tentativi.")
    return False


def do_ping(api, state):
    try:
        res = api.ping(state.code, visible=state.visible)
        print(f"[DEBUG PING] raw: {res}")
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

    # Aggiorna score, vendetta, decoy
    state.update_score_and_vendetta(players)

    # Aggiorna kill lock
    state.update_kill_lock(players)

    # Controlla camouflage adattivo (per il PROSSIMO ciclo)
    state.check_camouflage(players)

    targets = state.pick_targets(players)
    if not targets:
        print("[~] Nessun target visibile.")
        return

    execute_raffica(api, state, targets, next_ping_at)


def run(api, state):
    if not login(api, state):
        print("[!!] Impossibile autenticarsi. Uscita.")
        return

    while True:
        state.iteration += 1
        fire_this_cycle = state.should_fire()
        state.visible   = fire_this_cycle

        # ── 1. PING ───────────────────────────────────────────────
        ping_res = do_ping(api, state)

        if ping_res is None or not ping_res.get("ok"):
            motivo = ping_res.get("error", "?") if ping_res else "nessuna risposta"
            print(f"[!] Ping fallito #{state.iteration}. Motivo: {motivo}")
            time.sleep(2.0)
            if not login(api, state):
                print("[!!] Re-auth fallita. Riprovo tra 5s.")
                time.sleep(5.0)
            continue

        next_ping_at = ping_res.get("nextPingAt")
        elapsed = int(state.round_elapsed())

        if state.is_first_blood():
            stato = "⚔️  FIRST BLOOD"
        elif state.is_burst_mode():
            stato = "🔥 BURST"
        elif fire_this_cycle:
            stato = "🎯 BLITZ"
        else:
            stato = "👻 GHOST"

        print(f"[OK] Ping #{state.iteration} | {stato} | score={state.my_score} | t={elapsed}s | decoy=1/{state.fire_every_n}")

        # ── 2. BLITZ ─────────────────────────────────────────────
        if fire_this_cycle:
            time.sleep(0.3)
            do_blitz(api, state, next_ping_at)
        else:
            print("[~] Ciclo ghost — nessuna azione.")

        # ── 3. SLEEP PRECISO ─────────────────────────────────────
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.15
            if wait > 0:
                print(f"[~] Sleep {wait:.2f}s\n")
                time.sleep(wait)
            else:
                print("[!] In ritardo, pingo subito.")
        else:
            time.sleep(4.85)


if __name__ == "__main__":
    api   = BattleAPI("https://sososisi.isonlab.net/api")
    state = BotState("Ghost_XxX")
    run(api, state)
