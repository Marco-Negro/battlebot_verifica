# BATTLEBOT
# AVEVO UN PROBLEMA CON LA VELOCITà DI SPARO E HO APPORTATO 3 FIX PER LA MODALITà DI SPARO OFFLINE-INVISIBILE

# STO RISCONTRANDO PROBLEMA DI AUTENTICAZIONE [!] Sessione persa. Re-autenticazione...
'''[*] SESSIONE ATTIVA: xxx_66 | Key: 01PMBJIQ
[!] Sessione persa. Re-autenticazione...
[*] SESSIONE ATTIVA: xxx_66 | Key: U75AN3T4
[!] Sessione persa. Re-autenticazione...
[*] SESSIONE ATTIVA: xxx_66 | Key: M3HU194J
[!] Sessione persa. Re-autenticazione...
[*] SESSIONE ATTIVA: xxx_66 | Key: CPHV21CC
[!] Sessione persa. Re-autenticazione...
'''
import requests
import time
from concurrent.futures import ThreadPoolExecutor

class BattleBotFinal:
    def __init__(self, base_name):
        self.base_url = "https://sososisi.isonlab.net/api"
        # Cambiamo nome a ogni avvio per resettare sessioni bloccate
        self.name = f"{base_name}_{int(time.time() % 100)}"
        self.code = None
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.safety_interval = 5.2 # Intervallo di sicurezza per non essere bannati

    def login(self):
        try:
            res = requests.get(f"{self.base_url}/auth", params={"name": self.name}, timeout=5).json()
            if res.get("ok"):
                self.code = res["code"]
                print(f"[*] SESSIONE ATTIVA: {self.name} | Key: {self.code}")
                return True
        except: return False

    def fire_task(self, target):
        """Invia un singolo colpo"""
        try:
            requests.get(f"{self.base_url}/fire", params={"code": self.code, "target": target}, timeout=1)
        except: pass

    def run(self):
        if not self.login(): return

        while True:
            start_time = time.time()

            try:
                # 1. IL PING (Deve essere pulito e veloce)
                ping_res = requests.get(f"{self.base_url}/ping", 
                                      params={"code": self.code, "visible": "visible"}, timeout=2).json()
                
                if not ping_res.get("ok"):
                    print("[!] Sessione persa. Re-autenticazione...")
                    if self.login(): continue
                    else: break

                # 2. SCANSIONE BERSAGLI
                p_res = requests.get(f"{self.base_url}/players", params={"code": self.code}, timeout=2).json()
                
                if p_res.get("ok"):
                    # Filtra nemici visibili e ordinali per punteggio
                    targets = [p for p in p_res.get("players", []) if p['name'] != self.name and p.get('visible')]
                    targets.sort(key=lambda x: x.get('score', 0), reverse=True)

                    # 3. IL TRICK: SPARO DILAZIONATO
                    # Spariamo ai primi 10, ma uno ogni 0.2 secondi
                    # Questo mantiene la connessione fluida e non rompe l'audio del prof
                    for i, target in enumerate(targets[:10]):
                        self.executor.submit(self.fire_task, target['name'])
                        time.sleep(0.2) # Distribuisce i colpi nel tempo
                        print(f"[FIRE] Lanciato colpo {i+1}/10 a {target['name']}")

            except Exception as e:
                print(f"[!] Errore: {e}")

            # 4. SINCRONIZZAZIONE FINALE
            # Calcoliamo quanto tempo dormire per arrivare a 5.2s totali
            elapsed = time.time() - start_time
            to_sleep = max(0.1, self.safety_interval - elapsed)
            time.sleep(to_sleep)

if __name__ == "__main__":
    # Inserisci il tuo nome qui (il codice aggiungerà un numero finale)
    bot = BattleBotFinal("xxx") 
    bot.run()