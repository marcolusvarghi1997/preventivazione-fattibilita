# Istruzioni vincolanti per agenti

- Mantenere Django server-rendered; non introdurre una SPA senza richiesta esplicita.
- Non duplicare la logica dei calcoli: usare i servizi e i modelli economici esistenti.
- Usare sempre `Decimal`, mai `float`, per importi e formule.
- Conservare gli snapshot di costi, risorse e operatori nei preventivi storici.
- Aggiungere test per ogni nuova regola economica.
- Mantenere l'interfaccia interamente italiana, semplice e accessibile.
- Non mostrare costi industriali, costi orari, operatori o margini nei PDF cliente.
- Prima di concludere eseguire test, `manage.py check` e `makemigrations --check --dry-run`.
- Aggiornare il README quando cambiano setup o deployment.
