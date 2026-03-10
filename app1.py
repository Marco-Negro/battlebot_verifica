print("HELLO WORLD")

'''creazione di bot
creazione della classe:strutturala con metodi- attributi
inserire su Git 
-----> su git metti anche un file read me con i comandi utilizzati per poter creare la repo e pushare in Git
(tutti i comandi)
autenticazione tramite chiamate api get e post per autenticazine 
(parli col server che autentica e restituisce una key)
fai un ping tramite chiamata get ( ping ogni 5 sec)'''

'''Come funziona il gioco
1. Autenticazione
Invia il tuo nome al server. Riceverai un codice personale.

2. Ping ogni 5 secondi
Devi mandare un ping ogni 5 secondi. Se mandi un ping in piu, in meno, troppo presto o troppo tardi, il codice si distrugge.

3. Visibilita
Puoi diventare visibile o invisibile solo quando mandi il ping.

4. Round attivo
Quando il docente da il via, puoi vedere i bot autenticati e sparare solo ai bot visibili.

Regole importanti
Le API sono tutte in GET.

Se il codice viene distrutto devi rifare autenticazione.

Puoi sparare solo se anche tu sei visibile.

Non puoi colpire te stesso.

La classifica usa i punti: colpi a segno - colpi ricevuti.

Base URL
https://sososisi.isonlab.net
API da usare
Autenticazione
GET /api/auth?name=Mario
{
  "ok": true,
  "name": "Mario",
  "code": "AB12CD34",
  "pingEverySeconds": 5
}
Ping
GET /api/ping?code=AB12CD34
GET /api/ping?code=AB12CD34&visible=visible
GET /api/ping?code=AB12CD34&visible=invisible
{
  "ok": true,
  "name": "Mario",
  "visible": true,
  "nextPingAt": "2026-03-09T22:00:05.000Z"
}
Lista bot autenticati
GET /api/players?code=AB12CD34
Funziona solo quando il round e attivo.

Sparare
GET /api/fire?code=AB12CD34&target=Luisa
Puoi sparare solo se tu e il target siete visibili.'''