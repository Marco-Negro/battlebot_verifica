# BATTLEBOT

import requests
import time
from concurrent.futures import ThreadPoolExecutor

class SniperBotPredator:
    def __init__(self, name):
        self.base_url = "https://sososisi.isonlab.net/api"
        self.name = name
        self.code = None
        # Usiamo 30 workers per essere sicuri di coprire ogni possibile player istantaneamente
        self.executor = ThreadPoolExecutor(max_workers=30) 

    def login(self):
        try:
            res = requests.get(f"{self.base_url}/auth", params={"name": self.name}).json()
            if res.get("ok"):
                self.code = res["code"]
                print(f"[*] CACCIA INIZIATA! Key: {self.code}")
                return True
        except: return False

    def send_fire(self, target):
        """Singolo proiettile ultra-rapido"""
        try:
            requests.get(f"{self.base_url}/fire", params={"code": self.code, "target": target})
        except: pass

    def run(self):
        if not self.login(): return

        while True:
            start_cycle = time.time()

            try:
                # 1. PING (Sempre visibile per massimizzare i turni di fuoco)
                ping_res = requests.get(f"{self.base_url}/ping", 
                                      params={"code": self.code, "visible": "visible"}).json()
                
                if not ping_res.get("ok"):
                    print("[!] Codice scaduto/distrutto. Re-auth...")
                    if not self.login(): break
                    continue

                # 2. SCANSIONE E PRIORITIZZAZIONE (Il "NOS" strategico)
                p_res = requests.get(f"{self.base_url}/players", params={"code": self.code}).json()
                
                if p_res.get("ok"):
                    all_players = p_res.get("players", [])
                    
                    # Filtriamo i visibili e ORDINA per punteggio (dal più alto al più basso)
                    # Assumiamo che l'API restituisca il campo 'score' o 'points'
                    targets_data = [p for p in all_players if p['name'] != self.name and p.get('visible')]
                    
                    # Ordiniamo: i "pesci grossi" per primi
                    targets_data.sort(key=lambda x: x.get('score', 0), reverse=True)
                    
                    targets_names = [p['name'] for p in targets_data]

                    if targets_names:
                        print(f"[TARGETS] {len(targets_names)} nemici rilevati. Leader attuale: {targets_names[0]}")
                        
                        # 3. FUOCO A SALVE (Tutti insieme, ma con ordine di priorità nei thread)
                        for t in targets_names:
                            self.executor.submit(self.send_fire, t)
                    else:
                        print("[IDLE] Nessun bersaglio visibile. In attesa...")

            except Exception as e:
                print(f"Errore: {e}")

            # 4. PRECISIONE CHRONOS (Sincronizzazione perfetta 5s)
            elapsed = time.time() - start_cycle
            wait_time = max(0.05, 5.0 - elapsed)
            time.sleep(wait_time)

if __name__ == "__main__":
    # Inserisci il tuo nome qui
    bot = SniperBotPredator("SNIPERBOT")
    bot.run()