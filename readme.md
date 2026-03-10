STRATEGIA:
Strategie attive nel tuo codice
Difesa

Decoy 1/3 — visibile solo 1 ciclo su 3, ricevi colpi il 33% del tempo
Score shield — se score < 0, 2 cicli invisibili forzati per recuperare
Invisibile di default — self.visible = False come stato base

Attacco

Blitz parallelo — thread simultanei, tutti i colpi partono nello stesso millisecondo
Vendetta tracker — chi ti colpisce va primo nella lista fire
Target dinamico — se score ≥ 0 attacchi i forti, se < 0 attacchi i deboli

Timing

nextPingAt del server — timing basato sul server, non su clock locale
Session HTTP persistente — connessione TCP riusata, -30ms per richiesta
Latency optimization — sleep(0.3) invece di 0.8 → +0.5s di finestra di sparo
Burst finale — ultimi 60s sempre visibile e a raffica


Idee militari avanzateScegli cosa implementare. Nel frattempo ecco tutte le idee militari disponibili — alcune non ho messo come opzione perché richiedono discussione prima:
Livello tattico

Camouflage adattivo — se sei l'unico visibile nella lista players, sei il bersaglio di tutti. Sparisci subito
Kill priority lock — smetti di ricalcolare i target ogni ciclo, locka il leader finché non muore
Decoy dinamico — fire_every_n si aggiusta automaticamente in base ai colpi ricevuti
First blood — primi 30s = sempre visibile, tutti sparano a caso, tu già miri

Livello strategico

Score freezing — quando sei in testa di N punti, passa a modalità puramente difensiva: 1 ciclo su 4, nessun rischio
Timing jitter — aggiungi ±20ms random al sleep per non essere predicibile (alcuni bot potrebbero sincronizzarsi con il tuo pattern)
Dead reckoning — se un target era visibile al ciclo N e invisibile al ciclo N+1, probabilmente sta usando la stessa strategia 1/3. Prevedi quando tornerà visibile e spara appena riappare

Livello psicologico (contro bot umani)

Name spoofing — impossibile qui, il nome è fisso
Threat assessment — classifica i nemici per pericolosità reale (colpi ricevuti / cicli visibili) non solo per score grezzo