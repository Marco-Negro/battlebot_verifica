import requests
import time
from datetime import datetime, timezone

class GhostShield:
    def __init__(self, base_name):
        self.base_url = "https://sososisi.isonlab.net/api"
        self.name = f"{base_name}_Shield"
        self.code = None
        self.iteration = 0
        self.visible = True

    def seconds_until(self, iso_timestamp):
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (next_ping - now).total_seconds()
        except:
            return 5.0

    def login(self):
        for attempt in range(1, 4):
            try:
                print(f"\n[*] Auth tentativo {attempt}/3 come '{self.name}'...")
                res = requests.get(
                    f"{self.base_url}/auth",
                    params={"name": self.name},
                    timeout=5
                ).json()

                print(f"[DEBUG AUTH] raw: {res}")  # vediamo tutto quello che manda

                if res.get("ok"):
                    self.code = res["code"]
                    self.iteration = 0
                    print(f"[V] Auth OK. Code: {self.code}")

                    # ── FIX CRITICO: leggi nextPingAt dall'auth response ───
                    # Il server ti dice già QUANDO mandare il primo ping.
                    # Se non c'è nextPingAt nell'auth, aspetta pingEverySeconds.
                    next_ping_at = res.get("nextPingAt")
                    ping_every   = res.get("pingEverySeconds", 5)

                    if next_ping_at:
                        wait = self.seconds_until(next_ping_at) - 0.15
                        print(f"[~] Attendo {wait:.2f}s (da nextPingAt auth) prima del primo ping...")
                    else:
                        wait = ping_every - 0.15
                        print(f"[~] Attendo {wait:.2f}s (da pingEverySeconds) prima del primo ping...")

                    if wait > 0:
                        time.sleep(wait)

                    return True
                else:
                    print(f"[!] Auth rifiutata: {res}")

            except Exception as e:
                print(f"[!] Errore di rete durante auth: {e}")

            time.sleep(2.0)

        print("[!!] Auth fallita dopo 3 tentativi.")
        return False

    def ping(self, visible=True):
        visibility_param = "visible" if visible else "invisible"
        try:
            res = requests.get(
                f"{self.base_url}/ping",
                params={"code": self.code, "visible": visibility_param},
                timeout=5
            ).json()
            print(f"[DEBUG PING] raw: {res}")
            return res
        except Exception as e:
            print(f"[!] Errore ping: {e}")
            return None

    def get_players(self):
        try:
            res = requests.get(
                f"{self.base_url}/players",
                params={"code": self.code},
                timeout=5
            ).json()
            if res.get("ok"):
                return res.get("players", [])
            return []
        except Exception as e:
            print(f"[!] Errore players: {e}")
        return []

    def fire(self, target_name):
        try:
            res = requests.get(
                f"{self.base_url}/fire",
                params={"code": self.code, "target": target_name},
                timeout=5
            ).json()
            print(f"[FIRE] -> {target_name} | risposta: {res}")
            return res
        except Exception as e:
            print(f"[!] Errore fire: {e}")
        return None

    def pick_target(self, players):
        """
        Strategia sopravvivenza:
        - Prendi il target con punteggio più BASSO (bersaglio facile)
        - Se vuoi il più forte cambia reverse=False → True
        """
        targets = [
            p for p in players
            if p["name"] != self.name and p.get("visible")
        ]
        if not targets:
            return None
        targets.sort(key=lambda x: x.get("score", 0), reverse=False)
        return targets[0]

    def run(self):
        if not self.login():
            print("[!!] Impossibile autenticarsi. Uscita.")
            return

        while True:
            self.iteration += 1

            # ── 1. PING ────────────────────────────────────────────────────
            ping_res = self.ping(visible=self.visible)

            if ping_res is None or not ping_res.get("ok"):
                motivo = ping_res.get("error", "?") if ping_res else "nessuna risposta"
                print(f"[!] Ping fallito #{self.iteration}. Motivo: {motivo}")
                time.sleep(2.0)
                if not self.login():
                    print("[!!] Re-auth fallita. Riprovo tra 5s.")
                    time.sleep(5.0)
                continue

            next_ping_at = ping_res.get("nextPingAt")
            print(f"[OK] Ping #{self.iteration} | visible={ping_res.get('visible')}")

            # ── 2. AZIONE: players + un solo sparo ────────────────────────
            # Aspetta metà della finestra disponibile prima di agire:
            # questo ti mette lontano sia dal ping appena fatto
            # che dal prossimo → zero rischio blink
            time.sleep(1.5)

            players = self.get_players()
            target = self.pick_target(players)

            if target:
                print(f"[*] Target: {target['name']} (score={target.get('score',0)})")
                self.fire(target["name"])
            else:
                print("[~] Nessun target visibile o round non attivo.")

            # ── 3. SLEEP PRECISO FINO AL PROSSIMO PING ────────────────────
            if next_ping_at:
                wait = self.seconds_until(next_ping_at) - 0.15
                if wait > 0:
                    print(f"[~] Sleep {wait:.2f}s")
                    time.sleep(wait)
                else:
                    print("[!] In ritardo, pingo subito.")
            else:
                time.sleep(4.85)

if __name__ == "__main__":
    bot = GhostShield("Ghost_V4")
    bot.run()