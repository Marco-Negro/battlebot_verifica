import requests
import time
import threading
import socket
from datetime import datetime, timezone
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════════
# ADAPTIVE BOT — sistema di apprendimento a 3 livelli
#
# LIVELLO 1 — Visibilità adattiva (regole if/else dinamiche)
#   Finestra mobile 5 cicli di score_delta.
#   Perdi spesso → abbassa aggressione → più ghost.
#   Guadagni → alza aggressione → più attacco.
#
# LIVELLO 2 — Target scoring reward-based
#   Ogni nemico ha uno score interno:
#   +1 se lo colpisci con successo (proporzionale al suo score)
#   +danno*0.5 se ti ha colpito (priorità vendetta)
#   Il bot spara prima a chi ha score interno più alto.
#
# LIVELLO 3 — RL semplice su visibilità
#   Ogni ciclo visibile registra reward +1 (guadagno) o -1 (perdita).
#   Se reward medio ultimi 10 cicli < -0.3 → ghost forzato.
#   Più negativo → più cicli ghost.
# ═══════════════════════════════════════════════════════════════════

BASE_URL    = "https://sososisi.isonlab.net/api"
HOSTNAME    = "sososisi.isonlab.net"
BOT_NAME    = "ADAPTIVE - BOT "                      # <---- LO RINOMINO QUI
MAX_THREADS = 50


# ═══════════════════════════════════════════════════════════════════
# DNS
# ═══════════════════════════════════════════════════════════════════
def resolve_host(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        print(f"[DNS] {hostname} → {ip}")
    except Exception as e:
        print(f"[DNS] Fallback: {e}")


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
        return self.session.get(f"{BASE_URL}/auth",
            params={"name": name}, timeout=5).json()

    def ping(self, code, visible=True):
        v = "visible" if visible else "invisible"
        return self.session.get(f"{BASE_URL}/ping",
            params={"code": code, "visible": v}, timeout=5).json()

    def players(self, code):
        return self.session.get(f"{BASE_URL}/players",
            params={"code": code}, timeout=5).json()

    def fire(self, code, target_name):
        return self.session.get(f"{BASE_URL}/fire",
            params={"code": code, "target": target_name}, timeout=1).json()


# ═══════════════════════════════════════════════════════════════════
# LIVELLO 2 — PLAYER SCORER (reward-based)
# ═══════════════════════════════════════════════════════════════════
class PlayerScorer:
    def __init__(self):
        self.scores    = defaultdict(float)
        self.hits_on   = defaultdict(int)
        self.hits_from = defaultdict(int)

    def reward_hit(self, name, game_score):
        """Colpito con successo → premio proporzionale allo score del target."""
        bonus = 1.0 + max(0, game_score / 100)
        self.scores[name] += bonus
        self.hits_on[name] += 1

    def penalize_received(self, name, damage):
        """Ricevuto danno → priorità aumenta (vogliamo rispondere)."""
        self.scores[name] += damage * 0.5
        self.hits_from[name] += 1

    def get_priority(self, player):
        """Score finale = appreso + bonus score in game."""
        name       = player["name"]
        game_score = player.get("score", 0)
        learned    = self.scores[name]
        bonus      = max(0, game_score / 50)
        return learned + bonus

    def summary(self):
        if not self.scores:
            return "nessun dato"
        top = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        return " | ".join(f"{n}:{v:.1f}" for n, v in top[:3])


# ═══════════════════════════════════════════════════════════════════
# LIVELLO 3 — RL VISIBILITY
# ═══════════════════════════════════════════════════════════════════
class VisibilityRL:
    def __init__(self):
        self.history      = []
        self.window       = 10
        self.force_ghost  = 0

    def record(self, was_visible, score_delta):
        if was_visible:
            reward = 1 if score_delta >= 0 else -1
            self.history.append(reward)
            if len(self.history) > self.window:
                self.history.pop(0)

    def should_go_ghost(self, current_score):
        # Ghost streak in corso
        if self.force_ghost > 0:
            self.force_ghost -= 1
            print(f"[L3] 👻 Ghost forzato, ancora {self.force_ghost} cicli")
            return True

        # Emergenza assoluta
        if current_score < -50:
            self.force_ghost = 3
            print(f"[L3] 🚨 Emergenza score {current_score} → 3 cicli ghost")
            return True

        # RL: reward medio recente
        if len(self.history) >= 5:
            avg = sum(self.history) / len(self.history)
            if avg < -0.3:
                self.force_ghost = 2 if avg < -0.6 else 1
                print(f"[L3] 📉 Reward avg={avg:.2f} → {self.force_ghost} cicli ghost")
                return True

        return False

    def summary(self):
        if not self.history:
            return "nessun dato"
        avg   = sum(self.history) / len(self.history)
        trend = "📈" if avg > 0 else "📉"
        return f"avg={avg:.2f} {trend} | ultimi={self.history[-5:]}"


# ═══════════════════════════════════════════════════════════════════
# STATO
# ═══════════════════════════════════════════════════════════════════
class BotState:
    def __init__(self, name):
        self.name             = name
        self.code             = None
        self.iteration        = 0
        self.my_score         = 0
        self.prev_score       = 0
        self.round_start      = time.time()
        self.kill_target_lock = None
        self.kill_lock_score  = 0

        # I 3 sistemi
        self.scorer     = PlayerScorer()   # L2
        self.rl         = VisibilityRL()   # L3

        # L1: finestra mobile aggressione
        self.delta_window = []
        self.aggression   = 1.0            # 1.0=full attack, scende se perdi

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

    # ── L1: aggiorna aggressione ──────────────────────────────────
    def update_aggression(self, score_delta):
        self.delta_window.append(score_delta)
        if len(self.delta_window) > 5:
            self.delta_window.pop(0)
        avg = sum(self.delta_window) / len(self.delta_window)
        if avg < -2:
            self.aggression = max(0.2, self.aggression - 0.15)
        elif avg > 0:
            self.aggression = min(1.0, self.aggression + 0.10)
        print(f"[L1] aggr={self.aggression:.2f} | delta_avg={avg:.2f}")

    def update_score(self, players):
        self.prev_score = self.my_score
        for p in players:
            if p["name"] == self.name:
                self.my_score = p.get("score", self.my_score)
                break
        return self.my_score - self.prev_score

    # ── Kill lock ─────────────────────────────────────────────────
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
                for p in players)
            if not lock_visible or leader.get("score", 0) > self.kill_lock_score + 10:
                self.kill_target_lock = leader["name"]
                self.kill_lock_score  = leader.get("score", 0)
                print(f"[KILL LOCK] 🔄 → {self.kill_target_lock}")

    # ── Pick targets con scorer L2 ────────────────────────────────
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
                print(f"[KILL LOCK] 🎯 {lock['name']}")

        # Ordina per score appreso L2
        remaining.sort(key=lambda p: self.scorer.get_priority(p), reverse=True)
        print(f"[L2] Order: {[t['name'] for t in ordered + remaining]}")
        return ordered + remaining

    # ── Decisione visibilità: L3 prima, poi L1 ───────────────────
    def decide_visibility(self):
        # L3 ha priorità
        if self.rl.should_go_ghost(self.my_score):
            return False

        # L1: se aggressione < 0.5, vai ghost 1 ciclo su 3
        if self.aggression < 0.5 and self.iteration % 3 == 0:
            print(f"[L1] 👻 Aggressione bassa ({self.aggression:.2f}) → ghost")
            return False

        return True


# ═══════════════════════════════════════════════════════════════════
# RAFFICA con feedback a scorer L2
# ═══════════════════════════════════════════════════════════════════
def fire_worker(api, code, target_name, target_score, results, index, scorer):
    try:
        res = api.fire(code, target_name)
        results[index] = res
        if res.get("ok"):
            scorer.reward_hit(target_name, target_score)
            print(f"[T-{index}] ✅ {target_name}")
        else:
            print(f"[T-{index}] ❌ {target_name}")
    except Exception as e:
        results[index] = {"ok": False, "error": str(e)}


def execute_raffica(api, state, targets, next_ping_at):
    targets = targets[:MAX_THREADS]
    results = [None] * len(targets)
    threads = [
        threading.Thread(
            target=fire_worker,
            args=(api, state.code,
                  t["name"], t.get("score", 0),
                  results, i, state.scorer),
            daemon=True)
        for i, t in enumerate(targets)
    ]
    print(f"[RAFFICA] 🚀 {len(threads)} thread...")
    for t in threads: t.start()
    timeout = max(0.2, state.seconds_until(next_ping_at) - 0.2)
    for t in threads: t.join(timeout=timeout)
    fired = sum(1 for r in results if r and r.get("ok"))
    print(f"[RAFFICA] ✅ {fired}/{len(targets)} | score={state.my_score}")
    print(f"[L2] Scorer: {state.scorer.summary()}")


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
                return
            else:
                print(f"[!] Rifiutata: {res}")
        except Exception as e:
            print(f"[!] Errore: {e}")
        time.sleep(2.0)


# ═══════════════════════════════════════════════════════════════════
# LOOP PRINCIPALE
# ═══════════════════════════════════════════════════════════════════
def bot_loop(api, state):
    login(api, state)

    while True:
        state.iteration += 1

        # ── DECISIONE VISIBILITÀ (L1 + L3) ───────────────────────
        visible_now = state.decide_visibility()

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

        # ── PING + /players in parallelo ─────────────────────────
        if visible_now:
            threading.Thread(target=fetch_players_parallel, daemon=True).start()

        try:
            ping_res = api.ping(state.code, visible=visible_now)
            stato    = "👻 GHOST" if not visible_now else "🎯 ATTACK"
            print(f"\n[{state.name}] #{state.iteration} | {stato} | score={state.my_score} | aggr={state.aggression:.2f} | t={int(state.round_elapsed())}s")
            print(f"[L3] {state.rl.summary()}")
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
            players_ready.wait(timeout=0.3)
            pd      = players_result[0]
            players = pd.get("players", []) if (pd and pd.get("ok")) else []

            if not players:
                try:
                    r = api.players(state.code)
                    players = r.get("players", []) if r.get("ok") else []
                except:
                    players = []

            if players:
                score_delta = state.update_score(players)

                # Aggiorna tutti e 3 i sistemi
                state.update_aggression(score_delta)          # L1

                if score_delta < 0:                           # L2
                    for p in players:
                        if p["name"] != state.name and p.get("visible"):
                            state.scorer.penalize_received(p["name"], abs(score_delta))

                state.rl.record(was_visible=True,             # L3
                                score_delta=score_delta)

                state.update_kill_lock(players)
                targets = state.pick_targets(players)
                if targets:
                    execute_raffica(api, state, targets, next_ping_at)
                else:
                    print("[~] Nessun target visibile.")
            else:
                print("[~] Round non attivo.")
        else:
            state.rl.record(was_visible=False, score_delta=0)

        # ── SLEEP + PREFETCH ──────────────────────────────────────
        if next_ping_at:
            wait = state.seconds_until(next_ping_at) - 0.10
            if wait > 0.5:
                def _pre(d=wait * 0.6):
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
                print("[!] In ritardo.")
        else:
            time.sleep(4.90)


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    resolve_host(HOSTNAME)
    print("═" * 55)
    print(f"  {BOT_NAME} — ADAPTIVE BOT")
    print(f"  L1: visibilità adattiva  (aggression window 5)")
    print(f"  L2: target scoring       (reward-based)")
    print(f"  L3: RL visibilità        (reward history 10)")
    print("═" * 55)
    api   = BattleAPI()
    state = BotState(BOT_NAME)
    bot_loop(api, state)
