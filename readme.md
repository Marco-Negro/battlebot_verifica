Strategia completa utilizzata:
EVOLUZIONE:
v1  → ping base, timing fisso                    (rotto)
v2  → nextPingAt dal server                      (stabile)
v3  → sleep(1.0) post-auth                       (fix timing)
v4  → thread paralleli                           (raffica)
v5  → Session TCP + pool 20                      (latenza -30ms)
v6  → sleep 0.05s, margini al limite             (finestra 4.70s)
v7  → kill lock + vendetta tracker               (priorità fuoco)
v8  → decoy dinamico + shield + camouflage       (sopravvivenza)
v9  → first blood + burst finale                 (fasi di round)
v10 → DNS pre-resolve + prefetch players         (latenza -100ms)
v11 → dual-bot con offset 2.5s                   (doppio vettore)
FINAL → tri-bot, ally escrow, 50 thread,         (formazione)
        ally_names blacklist, ShooterState
        separato da AllyState