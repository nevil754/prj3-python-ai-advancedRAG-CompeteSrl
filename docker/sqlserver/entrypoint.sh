
#!/bin/bash   
   #QUELLO HERE QUA SOPRA NON E UN COMMENTO! E UN'ISTRUZIONE! dice che tutto questo code deve essere eseguito con Bash!!

#questo entrypoint è runnato nel command di sqlserver dentro docker-compose.yml, QUESTO FILE serve per assicurarsi (grazie a loop) che sql server sia pronto, e poi solo dopo runno (sempre in questo file) il file init.sql 

set -e    #dice a BAsh 'se QUALSIASI comando fallisce -> termina immediatamente lo script'. SEMPRE DA FARE!!

echo "Attendo SQL Server..."  #log console
until /opt/mssql-tools18/bin/sqlcmd \   #loop bash, ripete finche il COMMAND non ha successo, in questo caso il comando /opt/mssql-tools18/bin/sqlcmd (client CLI SQL Server) che verifica se SQL Server è vivo
    -S localhost \   #-S = server, poi vuole sapere a quale server deve connttersi, quindi gli dici connnettiti a localhost
    -U SA \    #-U = user, poi vuole sapere a quale utente SQL deve connettersi, dice connettiti come utente SA(System Administrator)
    -P "$SA_PASSWORD" \   #-P = password (presa da file .env), poi vuole sapere la psw, gli dai la psw 
    -Q "SELECT 1" > /dev/null 2>&1; do    #-Q = query, esegue query di test "SELECT 1", se risponde è vivo, se fallisce è unhealthy, > /dev/null butta via stdout, 2>&1 redirect stderr verso stdout., così non vediamo errori di connessione in console finché non è pronto
    sleep 2   #se sqlserver non è pronto, aspetta 2 secondi e riprova, finché non risponde correttamente al comando sqlcmd
done

echo "SQL Server pronto. Eseguo init.sql..."
/opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U SA \
    -P "$SA_PASSWORD" \
    -i /docker-entrypoint-initdb.d/init.sql \    #-i = input file, RUNNA SCRIPT INIT.SQL presente in /docker-entrypoint-initdb.d/init.sql (montato da docker-compose)
    -b    #esce con errore se il batch fallisce

echo "init.sql completato."   #log console


