# Report di collaudo browser — Preventivi Carpenteria

Data: 17 luglio 2026  
Ambiente: Django 5.2.16, server locale `127.0.0.1:9000`, browser integrato/Playwright  
Profilo: utente commerciale con scarsa esperienza informatica  
Codice applicativo modificato: no

## Sintesi

Sono stati completati i flussi di creazione, inserimento di due articoli, inserimento di più materiali, modifica, lavorazioni temporali, costo esterno, riepilogo, PDF, completamento, ricerca, riapertura, duplicazione e archiviazione. Sono stati provati anche campi vuoti, valori negativi, zero, valori molto grandi, testi lunghi, doppio clic, tasto Indietro, aggiornamento durante il salvataggio, seconda scheda e viewport mobile.

Problemi rilevati: 6 alti, 7 medi e 3 bassi. Nessun errore JavaScript è apparso in console. Il server ha però registrato richieste `422` non rappresentate nell'interfaccia e un `404` del favicon.

## Problemi rilevati

### 1. Quantità zero: risposta HTTP 422 senza alcun errore visibile

- Gravità: **alta**
- Percorso: Dashboard → Nuovo preventivo → salvare i dati generali → Articoli → inserire un codice → Quantità `0` → **Aggiungi articolo**.
- Comportamento attuale: il server risponde `422 Unprocessable Content`, i campi restano compilati e non compare nessun messaggio. La pagina sembra non aver recepito il clic. Il campo HTML espone inoltre `min="0"`, mentre il backend richiede almeno `1`.
- Comportamento atteso: indicare immediatamente “La quantità deve essere almeno 1”, mantenendo i dati inseriti.
- Proposta: impostare `min=1` nel form e configurare HTMX per scambiare anche le risposte 422, oppure restituire una risposta compatibile con lo swap contenente gli errori inline.
- Evidenza: log server `POST /preventivi/4/articoli/aggiungi/` → 422; riproduzione ripetuta senza messaggi nel DOM.

### 2. Un preventivo archiviato resta modificabile

- Gravità: **alta**
- Percorso: Cerca preventivo → Stato **Archiviato** → aprire `PREV-2026-0004` → modificare il prezzo da 4.200,50 a 4.300,00 → **Salva riepilogo**.
- Comportamento attuale: la modifica viene salvata e il preventivo resta “Archiviato”. Tutti i campi e i pulsanti di modifica rimangono attivi.
- Comportamento atteso: uno storico archiviato dovrebbe essere in sola lettura, oppure richiedere una riapertura esplicita e tracciata.
- Proposta: bloccare lato server tutte le view di mutazione quando lo stato è archiviato; disabilitare/nascondere i controlli e offrire un'azione “Riapri come bozza” con conferma e audit.
- Evidenza: database finale `PREV-2026-0004`, stato `archived`, prezzo `4300.00`.

### 3. Rimozioni immediate senza conferma

- Gravità: **alta**
- Percorso: Articoli → materiale già inserito → **Rimuovi**; lo stesso vale per **Rimuovi articolo**, operazioni e costi diretti.
- Comportamento attuale: il materiale viene cancellato immediatamente; nessuna finestra di conferma e nessuna possibilità di annullamento. I form di rimozione non hanno `data-confirm`.
- Comportamento atteso: conferma esplicita con oggetto dell'azione e, se possibile, breve possibilità di annullamento.
- Proposta: aggiungere conferme specifiche (“Rimuovere Acciaio… dall'articolo…?”), prevenire doppi invii e valutare cancellazione recuperabile.
- Screenshot: `03-articoli-materiali.png`.

### 4. Errore vuoto quando gli operatori sono zero

- Gravità: **alta**
- Percorso: Lavorazioni → attivare una fase → aprire **Aggiungi i tempi di lavorazione** → scegliere la risorsa → Operatori `0` → **Aggiungi operazione**.
- Comportamento attuale: compare soltanto “Operazione non aggiunta:” senza spiegazione; il pannello si richiude e i dati vengono azzerati.
- Comportamento atteso: errore inline “Gli operatori devono essere almeno 1”, dati conservati e pannello ancora aperto.
- Proposta: allineare `min=1`, rendere gli errori di form completi nel messaggio/DOM e riaprire automaticamente il `<details>` che contiene l'errore.

### 5. È possibile completare un preventivo con costi orari produttivi non configurati

- Gravità: **alta**
- Percorso: Lavorazioni → Taglio Lamiera/Saldatura → aggiungere tempi → Riepilogo → **Segna come completato**.
- Comportamento attuale: le operazioni hanno costo `EUR 0,00` perché gli snapshot orari sono `0.0000`; l'interfaccia mostra un avviso non bloccante e consente comunque il completamento.
- Comportamento atteso: evitare il completamento di un'offerta potenzialmente sottocosto, oppure richiedere un override esplicito e motivato.
- Proposta: rendere bloccante il costo orario zero per fasi attive, o introdurre una conferma amministrativa tracciata. Configurare i costi reali prima dell'uso produttivo.
- Evidenza: `PREV-2026-0003` completato; snapshot Laser 9kW e Saldatura Manuale entrambi `0.0000`.

### 6. Pagina Lavorazioni eccessivamente lunga e dispersiva

- Gravità: **alta**
- Percorso: preventivo con due articoli → Lavorazioni.
- Comportamento attuale: 22 schede (11 per articolo), altezza circa 6.868 px desktop e 13.050 px mobile. Le fasi non necessarie occupano comunque spazio e l'utente può perdere il punto in cui stava lavorando.
- Comportamento atteso: percorso breve e riconoscibile, con articolo corrente, fasi attive e stato di avanzamento sempre visibili.
- Proposta: accordion chiusi per le fasi non attive, navigazione per articolo, filtro “solo attive/da compilare”, riepilogo sticky non coprente e ritorno alla scheda appena salvata.
- Screenshot: `07-mobile-lavorazioni.png`.

### 7. Costo esterno pari a zero accettato come dato valido

- Gravità: **media**
- Percorso: Lavorazioni → Acquisti Esterni → attivare → Aggiungi acquisto esterno → Importo `0` → **Aggiungi costo**.
- Comportamento attuale: viene creata una riga da `EUR 0,00` e il preventivo resta completabile.
- Comportamento atteso: un costo obbligatorio dovrebbe essere maggiore di zero, oppure marcato esplicitamente “da definire” e impedire il completamento.
- Proposta: validatore `> 0` o stato separato “importo da definire”; aggiungere test economico dedicato.

### 8. Nella ricerca mobile il pulsante Apri è fuori schermo

- Gravità: **media**
- Percorso: viewport 390 px → Cerca preventivo → risultati.
- Comportamento attuale: la tabella è orizzontalmente scorrevole; a 390 px si vedono numero, cliente, data e parte dello stato, mentre **Apri** si trova oltre 600 px a destra senza indicazione evidente di scorrimento.
- Comportamento atteso: ogni risultato dovrebbe poter essere aperto senza scorrimento orizzontale non evidente.
- Proposta: trasformare le righe in card su mobile o rendere numero/intera riga cliccabile; aggiungere affordance di scorrimento se si mantiene la tabella.
- Screenshot: `08-mobile-ricerca.png`.

### 9. Barra azioni mobile sovrapposta al contenuto

- Gravità: **media**
- Percorso: viewport 390 px → Articoli o Lavorazioni → scorrere la pagina.
- Comportamento attuale: la barra sticky alta circa 140 px copre tabelle e contenuti sottostanti.
- Comportamento atteso: le azioni devono restare disponibili senza nascondere campi e righe.
- Proposta: riservare spazio inferiore equivalente, ridurre l'altezza, usare una sola azione primaria compatta o rendere la barra non sovrapposta.
- Screenshot: `06-mobile-articoli.png`.

### 10. Intervallo date inverso accettato senza spiegazione

- Gravità: **media**
- Percorso: Cerca preventivo → Dal `31/12/2026` → Al `01/01/2026` → Cerca.
- Comportamento attuale: la pagina mostra “Risultati (0)” e “Nessun preventivo…” senza indicare che l'intervallo è impossibile.
- Comportamento atteso: errore “La data iniziale non può essere successiva alla data finale”.
- Proposta: validazione incrociata lato server nel form di ricerca e messaggio inline vicino alle date.

### 11. Aggiornamento durante il salvataggio: modifica persa ma messaggio di successo

- Gravità: **media**
- Percorso: aprire lo stesso preventivo in una seconda scheda → cambiare il prezzo da 4.200,50 a 4.400,00 → premere Salva e aggiornare immediatamente.
- Comportamento attuale: dopo la corsa tra POST e GET compare “Riepilogo economico e fattibilità salvati”, ma il database conserva 4.200,50.
- Comportamento atteso: indicare chiaramente se il salvataggio è concluso; non mostrare successo per dati non persistiti.
- Proposta: disabilitare il pulsante durante il POST, mostrare stato “Salvataggio…”, aggiungere protezione `beforeunload` solo durante richieste attive e verifica della versione salvata.

### 12. Stato Completato/Archiviato con azioni incoerenti

- Gravità: **media**
- Percorso: completare o archiviare un preventivo → riaprire il riepilogo.
- Comportamento attuale: restano abilitati “Segna come completato”, “Salva riepilogo” e “Archivia preventivo”; il testo continua a dire che il preventivo “può essere segnato come completato”.
- Comportamento atteso: azioni coerenti con lo stato corrente e nessuna operazione ridondante.
- Proposta: macchina a stati esplicita lato server e UI; sostituire le azioni con “Già completato”, “Riapri” o “Ripristina”, secondo le regole aziendali.

### 13. Controlli dinamici dei materiali non hanno nomi accessibili

- Gravità: **media**
- Percorso: Articoli → scheda articolo → Materiali.
- Comportamento attuale: nel DOM accessibile il select del materiale e il peso risultano rispettivamente “combobox” e “spinbutton” senza nome, anche se il testo visivo è presente.
- Comportamento atteso: ogni controllo deve essere associato alla propria etichetta.
- Proposta: usare `label for` e `id` univoci per articolo/formset, verificando anche i pulsanti ripetuti con un nome contestuale.

### 14. Passaggi futuri prima del primo salvataggio sembrano link attivi

- Gravità: **bassa**
- Percorso: Dashboard → Nuovo preventivo → clic su “2. Articoli”, “3. Lavorazioni” o “4. Riepilogo” prima di salvare.
- Comportamento attuale: elementi `<a href="#">` focusabili, con sola classe CSS `disabled`; il clic non produce feedback e manca `aria-disabled`.
- Comportamento atteso: controlli realmente disabilitati con spiegazione “Salva prima i dati generali”.
- Proposta: usare testo/button disabilitato non focusabile, `aria-disabled="true"` e messaggio contestuale.

### 15. Richiesta favicon fallita

- Gravità: **bassa**
- Percorso: aprire qualsiasi pagina in una nuova scheda.
- Comportamento attuale: `GET /favicon.ico` → 404.
- Comportamento atteso: nessuna richiesta fallita ordinaria.
- Proposta: aggiungere favicon locale e relativo `<link rel="icon">`.

### 16. Testi italiani senza accenti

- Gravità: **bassa**
- Percorso: varie pagine e messaggi (“Quantita”, “Fattibilita”, “verra”, “puo”, “piu”).
- Comportamento attuale: interfaccia comprensibile ma poco curata e meno naturale.
- Comportamento atteso: italiano corretto e coerente.
- Proposta: correggere le stringhe visibili e mantenere invariati i codici/slug tecnici.

## Esiti positivi

- Creazione, salvataggio, modifica, ricerca e riapertura hanno persistito correttamente i dati validi.
- Il doppio clic su accesso e primo salvataggio ha prodotto una sola richiesta POST e non ha creato duplicati.
- Duplicazione profonda riuscita: `PREV-2026-0004` è nata in bozza con articoli, materiali, fasi, tempi, costi e snapshot copiati.
- Archiviazione riuscita e preventivo ancora ricercabile con filtro Archiviato.
- Snapshot verificati nel database: costo materiale `1.2750`, nomi risorsa, costo orario, operatori e tempi sono stati copiati.
- PDF: `GET /preventivi/4/pdf/` ha risposto 200 con 8.739 byte. Il browser integrato non ha emesso l'evento download, ma il backend ha generato correttamente il file.
- Console JavaScript: nessun errore o warning catturato.
- Ricaricamento pagina ricerca: circa 146 ms; nuovo preventivo 350 ms; riepilogo 371 ms; lavorazioni circa 1.015 ms in viewport mobile.
- La validazione nativa gestisce correttamente campi obbligatori, valori negativi e peso minimo.

## Priorità consigliata

1. Correggere il 422 silenzioso della quantità zero e tutti gli errori HTMX non scambiati.
2. Rendere gli archiviati non modificabili e definire chiaramente la mutabilità dei completati.
3. Impedire il completamento con costi produttivi a zero, salvo override tracciato.
4. Aggiungere conferma/annullamento alle rimozioni.
5. Mostrare errori completi, inline e persistenti nei pannelli lavorazione.
6. Ridisegnare la pagina Lavorazioni per articolo/fasi attive.
7. Decidere la regola economica per costi diretti pari a zero e aggiungere test.
8. Correggere ricerca e barra azioni su mobile.
9. Validare l'intervallo date e proteggere il salvataggio durante refresh/navigazione.
10. Completare accessibilità, coerenza degli stati, favicon e microcopy italiana.

## Dati di collaudo lasciati nel database

- Utente: `collaudo_commerciale`.
- Cliente: `CLIENTE COLLAUDO SRL`.
- Materiali: `Acciaio S355JR - collaudo`, `Inox AISI 304 - collaudo`.
- `PREV-2026-0003`: completato, prezzo 4.200,50.
- `PREV-2026-0004`: copia archiviata, prezzo modificato a 4.300,00 durante il test di mutabilità.

