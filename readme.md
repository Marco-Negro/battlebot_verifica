Strategia completa — evoluzione versione per versione ( ALCUNE NON SONO DOCUMENTATE IN GIT, A CAUSA DELLA VELOCITà DI EVO )

v1 — Ping base, timing fisso (rotto)
Primo tentativo. Sleep fisso di 5s hardcodato. Il server ha timing dinamico → i ping arrivavano fuori finestra → codice distrutto continuamente.
v2 — nextPingAt dal server (stabile)
Svolta fondamentale. Il bot legge nextPingAt dalla risposta del server e usa quello come riferimento invece del clock locale. Ping stabili, zero codici distrutti.
v3 — Sleep post-auth (fix timing)
Dopo l'auth il bot partiva troppo presto. Aggiunto sleep(1.0) per aspettare la finestra corretta prima del primo ping.
v4 — Thread paralleli (raffica)
Introdotta la raffica: un thread per target, tutti partono insieme con t.start() separato da t.join(). Il bot smette di sparare in sequenza e colpisce tutti i nemici nello stesso millisecondo.
v5 — Session TCP + pool 20 (latenza -30ms)
requests.Session() persistente con HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0). Le connessioni TCP vengono riusate invece di essere riaperte ogni volta. Guadagno misurato: ~30ms per richiesta.
v6 — Margini al limite assoluto (finestra 4.70s)
Sleep post-ping abbassato a 0.05s, margine ping a 0.05s. La finestra di sparo effettiva passa a 4.70s per ciclo. Più ci si avvicina al limite senza sforarlo, più colpi si riesce a sparare.
v7 — Kill lock + vendetta tracker (priorità fuoco)
Kill lock: il bot locka il leader assoluto e non lo molla finché non sparisce o viene superato di +10 punti. Vendetta tracker: hit_by dict che accumula il danno ricevuto per fonte — chi spara di più finisce secondo nella lista fire.
v8 — Decoy dinamico + shield + camouflage (sopravvivenza)
Fase difensiva sperimentale: fire_every_n adattivo (più colpi ricevi → più cicli ghost), score shield (invisibile se score < 0), camouflage (invisibile se sei l'unico visibile). Tutti e tre rimossi nella versione successiva — troppo difensivi, perdita netta di punti.
v9 — First blood + burst finale (fasi di round)
Logica a fasi: primi 30s sempre visibile e aggressivo (first blood), ultimi 60s sempre visibile (burst finale). Anch'essa rimossa nella versione full-attack — il bot è sempre in modalità attacco quindi le fasi erano ridondanti.
v10 — DNS pre-resolve + prefetch players (latenza -100ms)
socket.gethostbyname() una volta sola all'avvio elimina il DNS lookup ad ogni richiesta. Prefetch: durante il sleep del ciclo corrente, un thread lancia già /players in background. Al ciclo successivo i target sono pronti senza attendere la risposta — risparmio ~100-200ms.
v11 — Dual-bot con offset 2.5s (doppio vettore)
Due istanze Ghost_V4 e Ghost_V4b in thread separati, stessa logica, offset di partenza 2.5s. Il server li vede come due giocatori distinti. Doppio vettore di fuoco sul leader ogni ciclo.

FINAL — Tri-bot sincronizzato via socket (formazione)
Architettura a tre bot con ruoli distinti:

Shooter_v1 (Ghost_lastV) → master shooter, sempre visibile, 50 thread simultanei, spara a tutti inclusi gli alleati nel momento di sync
Ghost_1 (cheatBot) → esca, invisibile di default, visibile solo su segnale FIRE
Ghost_2 (BOT) → esca, invisibile di default, visibile solo su segnale FIRE

Sincronizzazione via TCP socket locale (porta 9001/9002): Shooter_v1 manda segnale FIRE 0.3s prima della raffica → gli alleati ricevono il segnale → diventano visibili per un solo ping → Shooter_v1 li trova in /players e li colpisce → punti garantiti ogni ciclo anche senza nemici visibili. Gli alleati non sparano mai a nessuno.
Ottimizzazioni di rete finali: Keep-Alive + Accept-Encoding: identity + pool 55 connessioni + timeout=1s sui fire.