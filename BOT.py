# BATTLEBOT
# AVEVO UN PROBLEMA CON LA VELOCITà DI SPARO E HO APPORTATO 3 FIX PER LA MODALITà DI SPARO OFFLINE-INVISIBILE

import requests
import time
from concurrent.futures import ThreadPoolExecutor

class PredatorSniperUltra:
    def __init__(self, name):
        self.base_url = "https://sososisi.isonlab.net/api"
        self.name = name
        self.code = None
        # POWER UP 1: Gatling Gun (30 thread per colpi simultanei istantanei)
        self.executor = ThreadPoolExecutor(max_workers=30) 
        self.safety_margin = 5.1  # POWER UP 2: Il "muro" di sicurezza contro i ban (5.1s)

    def login(self):
        """Autenticazione con gestione errori"""
        try:
            res = requests.get(f"{self.base_url}/auth", params={"name": self.name}, timeout=5).json()
            if res.get("ok"):
                self.code = res["code"]
                print(f"[*] LOGIN SUCCESS: Key [{self.code}] ottenuta per {self.name}")
                return True
        except Exception as e:
            print(f"[!] Errore Auth: {e}")
        return False

    def send_fire(self, target):
        """Invia il colpo al server"""
        try:
            # Timeout breve per non bloccare i thread
            requests.get(f"{self.base_url}/fire", params={"code": self.code, "target": target}, timeout=2)
        except:
            pass

    def run(self):
        if not self.login():
            return

        print("[*] Bot avviato. Caccia ai leader in corso...")

        while True:
            start_cycle = time.time()  # Punto di riferimento per il timer di precisione

            try:
                # 1. PING (Forziamo 'visible' per poter sparare)
                ping_params = {"code": self.code, "visible": "visible"}
                res_ping = requests.get(f"{self.base_url}/ping", params=ping_params, timeout=3).json()
                
                if not res_ping.get("ok"):
                    print("[!] Sessione scaduta o eliminata. Tentativo di rientro...")
                    if self.login(): continue
                    else: 
                        time.sleep(2)
                        continue

                # 2. POWER UP 3: Scansione e Priorità (Caccia ai Pesci Grossi)
                res_players = requests.get(f"{self.base_url}/players", params={"code": self.code}, timeout=3).json()
                
                if res_players.get("ok"):
                    players = res_players.get("players", [])
                    
                    # Filtra: visibili e non io
                    targets = [p for p in players if p['name'] != self.name and p.get('visible')]
                    
                    # Ordina per punteggio (score) decrescente per colpire prima i leader
                    targets.sort(key=lambda x: x.get('score', 0), reverse=True)
                    
                    if targets:
                        print(f"[VOLLEY] Bersagli: {len(targets)} | Primo Target: {targets[0]['name']} ({targets[0].get('score')} pt)")
                        for t in targets:
                            # Spara a tutti simultaneamente usando i thread
                            self.executor.submit(self.send_fire, t['name'])
                    else:
                        print("[IDLE] Nessun bersaglio visibile.")

            except Exception as e:
                print(f"[ERRORE] Ciclo interrotto: {e}")

            # --- CALCOLO PRECISIONE (FIX 5.1s) ---
            # Misuriamo quanto tempo ha impiegato il codice (ping + scansione + invio thread)
            elapsed = time.time() - start_cycle
            
            # Calcoliamo l'attesa per arrivare esattamente a 5.1 secondi
            # Usiamo 5.1 per essere sicuri che il server non ci veda come "troppo veloci"
            wait_time = self.safety_margin - elapsed
            
            if wait_time > 0:
                # Se siamo stati veloci (es. 0.5s), aspettiamo 4.6s
                time.sleep(wait_time)
            else:
                # Se abbiamo laggato e ci abbiamo messo più di 5.1s, non aspettiamo
                print(f"[WARN] Lag di rete rilevato: ciclo durato {elapsed:.2f}s")

if __name__ == "__main__":
    # INSERISCI IL TUO NOME QUI
    MY_NICKNAME = "xxx" 
    bot = PredatorSniperUltra(MY_NICKNAME)
    bot.run()

