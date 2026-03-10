# BATTLEBOT
# AVEVO UN PROBLEMA CON LA VELOCITà DI SPARO E HO APPORTATO 3 FIX PER LA MODALITà DI SPARO OFFLINE-INVISIBILE

import requests
import time
from datetime import datetime, timezone

class GhostShield:
    def __init__(self, base_name):
        self.base_url = "https://sososisi.isonlab.net/api"
        self.name = f"{base_name}_Shield"
        self.code = None
        self.iteration = 0
        self.visible = True  # Traccia lo stato visibilità

    def login(self):
        """Autenticazione: chiedi codice al server."""
        try:
            print(f"\n[*] Autenticazione come '{self.name}'...")
            res = requests.get(
                f"{self.base_url}/auth",
                params={"name": self.name},
                timeout=5
            ).json()

            if res.get("ok"):
                self.code = res["code"]
                print(f"[V] Auth OK. Code: {self.code}")
                return True
            else:
                print(f"[!] Auth fallita: {res}")
        except Exception as e:
            print(f"[!] Errore auth: {e}")
        return False

    def ping(self, visible=True):
        """
        Manda il ping. 
        REGOLA: solo durante il ping puoi cambiare visibilità.
        """
        visibility_param = "visible" if visible else "invisible"
        try:
            res = requests.get(
                f"{self.base_url}/ping",
                params={"code": self.code, "visible": visibility_param},
                timeout=5
            ).json()
            return res
        except Exception as e:
            print(f"[!] Errore ping: {e}")
            return None

    def get_players(self):
        """Lista bot. Funziona solo a round attivo."""
        try:
            res = requests.get(
                f"{self.base_url}/players",
                params={"code": self.code},
                timeout=5
            ).json()
            if res.get("ok"):
                return res.get("players", [])
        except Exception as e:
            print(f"[!] Errore players: {e}")
        return []

    def fire(self, target_name):
        """
        Spara a un target.
        REGOLA: devi essere visibile TU e deve essere visibile il TARGET.
        """
        try:
            res = requests.get(
                f"{self.base_url}/fire",
                params={"code": self.code, "target": target_name},
                timeout=5
            ).json()
            print(f"[FIRE] -> {target_name}: {res}")
            return res
        except Exception as e:
            print(f"[!] Errore fire: {e}")
        return None

    def seconds_until(self, iso_timestamp):
        """
        Calcola i secondi mancanti a nextPingAt.
        Usa il timestamp del server per evitare derive di clock.
        """
        try:
            next_ping = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = (next_ping - now).total_seconds()
            return delta
        except Exception as e:
            print(f"[!] Errore parsing timestamp: {e}")
            return 5.0  # Fallback sicuro

    def run(self):
        """Loop principale."""
        if not self.login():
            print("[!] Impossibile autenticarsi. Uscita.")
            return

        while True:
            self.iteration += 1

            # ── BLOCCO 1: PING ──────────────────────────────────────────────
            # Il ping è OBBLIGATORIO ogni 5s esatti (usa nextPingAt del server).
            # Qui decidi anche se essere visibile o invisibile.
            # STRATEGIA BASE: sempre visibile (necessario per poter sparare).
            ping_res = self.ping(visible=self.visible)

            if ping_res is None or not ping_res.get("ok"):
                print(f"[!] Ping fallito al ciclo {self.iteration}. Rieseguo auth...")
                if not self.login():
                    print("[!] Auth fallita. Attendo 5s e riprovo.")
                    time.sleep(5)
                continue

            print(f"[OK] Ping {self.iteration} | visible={ping_res.get('visible')}")

            # Leggi nextPingAt dal server — è la fonte di verità per il timing
            next_ping_at = ping_res.get("nextPingAt")

            # ── BLOCCO 2: AZIONI (players + fire) ───────────────────────────
            # Le azioni vanno fatte TRA un ping e il successivo.
            # Non aspettare troppo: devi avere tempo di dormire prima del ping.
            if self.visible:  # FIX: puoi sparare solo se SEI visibile
                players = self.get_players()

                if players:
                    # Filtra: escluditi, prendi solo i visibili
                    targets = [
                        p for p in players
                        if p["name"] != self.name and p.get("visible")
                    ]
                    # Ordina per punteggio decrescente (colpisci il più forte)
                    targets.sort(key=lambda x: x.get("score", 0), reverse=True)

                    if targets:
                        self.fire(targets[0]["name"])
                else:
                    print("[~] Nessun giocatore visibile o round non attivo.")

            # ── BLOCCO 3: SLEEP PRECISO ──────────────────────────────────────
            # Dormi fino a nextPingAt (con piccolo margine di sicurezza).
            # FIX: non usare 5.1 fisso — usa il timestamp del server.
            if next_ping_at:
                wait = self.seconds_until(next_ping_at) - 0.1  # 100ms di anticipo
                if wait > 0:
                    print(f"[~] Attendo {wait:.2f}s fino al prossimo ping...")
                    time.sleep(wait)
                else:
                    # Siamo già in ritardo: pinga subito senza sleep
                    print("[!] In ritardo sul ping, eseguo subito.")
            else:
                # Fallback se nextPingAt non arriva
                time.sleep(4.9)

if __name__ == "__main__":
    bot = GhostShield("Ghost_V3")
    bot.run()