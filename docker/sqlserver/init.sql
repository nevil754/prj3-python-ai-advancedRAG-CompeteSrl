-- strategia: schema-per-tenant dentro un unico database RAGChat

USE master;  --db di sistema, da cui creiamo il nostro db RAGChat
GO  --separatore batch code

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'RAGChat')
BEGIN
    CREATE DATABASE RAGChat
    COLLATE Latin1_General_100_CI_AS_SC_UTF8;   --encoding del db, CI=case insensitive AS=accent sensitive (distingue "è" da "e")  SC=supplementary characters (emoji e caratteri rari) UTF8=supporto completo unicode
END
GO

USE RAGChat;
GO

--creo schema 'shared' x metadati piattaforma (non dati tenant dove OGNI 'AZIENDA' AVRA IL SUO SCHEMA TUTTO PER LUI, lo schema personale viene creato al SignUp dell'azienda grazie a stored procedure shared.sp_provision_tenant)

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'shared')  --in sqlserver(microsoft) non puoi fare CREATE SCHEMA IF NOT EXISTS direttamente, devi sempre fare check manuale su sys.schemas
    EXEC('CREATE SCHEMA shared');
GO

-- registro di tutti i tenant attivi
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.tenants (
    id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),  --NEWSEQUENTIALID() è UUID/GUID univoco MA sequenziale
    slug            NVARCHAR(100)       NOT NULL,   -- "acme-corp" diventa -> schema tenant_acme_corp
    display_name    NVARCHAR(255)       NOT NULL,
    plan            NVARCHAR(50)        NOT NULL DEFAULT 'starter',  -- starter | pro | enterprise
    is_active       BIT                 NOT NULL DEFAULT 1,   -- 1=attivo, 0=disabilitato (es. per scadenza abbonamento)
    max_docs        INT                 NOT NULL DEFAULT 500,
    max_users       INT                 NOT NULL DEFAULT 10,
    max_tokens_day  BIGINT              NOT NULL DEFAULT 100000,   --🔥RATE LIMIT TOKEN X DAY!!
    settings        NVARCHAR(MAX)       NULL,       -- JSON: feature flags, custom prompts, ecc.
    created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),  --return data e ora corrente del server SQL in formato UTC
    updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_tenants PRIMARY KEY (id),
    CONSTRAINT UQ_tenants_slug UNIQUE (slug),
    CONSTRAINT CK_tenants_plan CHECK (plan IN ('starter','pro','enterprise'))
);
GO

--🔥audit log globale (x GDPR, compliance legale)
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'audit_log'
)
CREATE TABLE shared.audit_log (  --FONDAMENTALE in contesti enterprise, con questa puoi ricostruire info chi ha fatto cosa, quando, dove, con che dati ect quest tab puo contenere recrods che ricostruiscono query rag - llm call - document ingestion - security
    id          BIGINT IDENTITY(1,1)    NOT NULL,
    tenant_id   UNIQUEIDENTIFIER        NOT NULL,
    user_id     UNIQUEIDENTIFIER        NULL,
    action      NVARCHAR(100)           NOT NULL,  --e.g. 'doc.upload' | 'chat.query' | 'user.login'
    resource    NVARCHAR(500)           NULL,
    ip_address  NVARCHAR(45)            NULL,
    user_agent  NVARCHAR(500)           NULL,
    metadata    NVARCHAR(MAX)           NULL,       -- JSON
    created_at  DATETIME2(3)               NOT NULL DEFAULT SYSUTCDATETIME(),  --return data e ora corrente del server SQL in formato UTC
    CONSTRAINT PK_audit_log PRIMARY KEY (id),
    CONSTRAINT FK_audit_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

CREATE INDEX IX_audit_tenant_date ON shared.audit_log (tenant_id, created_at DESC);  --index per iterare velocemente i records quando utente fa una search
GO

-- utilizzo token per billing e rate limiting
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'usage_stats'
)
CREATE TABLE shared.usage_stats (
    id              BIGINT IDENTITY(1,1) NOT NULL,
    tenant_id       UNIQUEIDENTIFIER     NOT NULL,
    stat_date       DATE                 NOT NULL,
    tokens_in       BIGINT               NOT NULL DEFAULT 0,
    tokens_out      BIGINT               NOT NULL DEFAULT 0,
    queries_count   INT                  NOT NULL DEFAULT 0,
    docs_ingested   INT                  NOT NULL DEFAULT 0,
    CONSTRAINT PK_usage PRIMARY KEY (id),
    CONSTRAINT UQ_usage_tenant_date UNIQUE (tenant_id, stat_date),
    CONSTRAINT FK_usage_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

-- API keys (per integrazione esterna di un tenant)
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'api_keys'
)
CREATE TABLE shared.api_keys (
    id          UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),   --UUID/GUID univoco MA sequenziale
    tenant_id   UNIQUEIDENTIFIER    NOT NULL,
    key_hash    NVARCHAR(64)        NOT NULL,     -- SHA-256 della key, ⚠️ MAI IN CHIARO (puoi hasharla nel backend)
    [name]        NVARCHAR(255)       NOT NULL,
    scopes      NVARCHAR(500)       NOT NULL DEFAULT 'read,write',
    is_active   BIT                 NOT NULL DEFAULT 1,
    last_used   DATETIME2(3)           NULL,
    expires_at  DATETIME2(3)           NULL,
    created_at  DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),   --return data e ora corrente del server SQL in formato UTC
    CONSTRAINT PK_api_keys PRIMARY KEY (id),
    CONSTRAINT UQ_api_keys_hash UNIQUE (key_hash),
    CONSTRAINT FK_api_keys_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO


--###################################

--stored procedure: provisioning dinamico di un tenant, 🔥🔥GRAZIE A QUESTO OGNI 'AZIENDA' AVRA UN'INTERO SCHEMA SOLO PER LUI!!
--chiamata da Python (tenant_db.provision_tenant) al signup
CREATE OR ALTER PROCEDURE shared.sp_provision_tenant  --🔥🔥CREA AUTOMATICAMENTE UNO SCHEMA SQL COMPLETO PER OGNI CLIENTE see screenshot multi-tenant-architecture.svg QUINDI OGNI 'AZIENDA' GLI VIENE CREATO UN SUO INTERO SCHEMA SOLO PER LUI!!
    @slug           NVARCHAR(100),  --e.g.'acme-corp'
    @display_name   NVARCHAR(255),  --e.g. 'Acme Corporation'
    @plan           NVARCHAR(50) = 'starter'  --starter | pro | enterprise
    --params passati dal backend al momento del signup di un nuovo tenant, con queste info creo schema dedicato e registro tenant in tabella shared.tenants (taba shared solo per i metadata)
AS  --inizio del corpo della stored procedure
BEGIN  --inizio del corpo
    SET NOCOUNT ON;  --evita messaggi di "X rows affected" che possono confondere client che chiamano la sp (es. Python pyodbc)

    DECLARE @schema_name NVARCHAR(200) = 'tenant_' + REPLACE(@slug, '-', '_');  --converte e.g. "acme-corp" -> "tenant_acme_corp", perche i '-' non sono validi in sqlserver nei nomi di schema/tabelle! quindi li converto
    DECLARE @sql NVARCHAR(MAX);  --here creerai query sql dinamiche 

    --1.crea schema
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = @schema_name)
    BEGIN
        SET @sql = 'CREATE SCHEMA [' + @schema_name + ']';
        EXEC sp_executesql @sql;    --esegue sql dentro quella var locale 
    END

    --2.inserisci record in shared.tenants
    IF NOT EXISTS (SELECT 1 FROM shared.tenants WHERE slug = @slug)
    BEGIN
        INSERT INTO shared.tenants (slug, display_name, plan)    --insert in tab condivisa 
        VALUES (@slug, @display_name, @plan);
    END

    --####### Crea tabelle tenant (DDL dinamico)

    --crea sql dinamico dentro var locale, con questo sql creerai tutte le tab del tenant (e.g.users/collections/document/ ect)
    --crea tab users
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''users''
    )
    CREATE TABLE [' + @schema_name + '].users (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        email           NVARCHAR(255)       NOT NULL,
        full_name       NVARCHAR(255)       NULL,
        role            NVARCHAR(50)        NOT NULL DEFAULT ''user'',
        password_hash   NVARCHAR(255)       NULL,
        is_active       BIT                 NOT NULL DEFAULT 1,
        last_login      DATETIME2(3)           NULL,
        settings        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_users] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_users_email] UNIQUE (email),
        CONSTRAINT [CK_' + @schema_name + '_users_role] CHECK (role IN (''admin'',''user'',''viewer''))
    )';
    EXEC sp_executesql @sql;  --esegue sql dentro quella var locale 

    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea tab collections (cartelle logiche di documenti)
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''collections''
    )
    CREATE TABLE [' + @schema_name + '].collections (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        name            NVARCHAR(255)       NOT NULL,
        description     NVARCHAR(1000)      NULL,
        qdrant_name     NVARCHAR(300)       NOT NULL,  -- nome collection su Qdrant
        is_active       BIT                 NOT NULL DEFAULT 1,
        metadata        NVARCHAR(MAX)       NULL,
        created_by      UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),  
        CONSTRAINT [PK_' + @schema_name + '_collections] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_qdrant_name] UNIQUE (qdrant_name)
    )';
    EXEC sp_executesql @sql;  --esegue sql dentro quella var locale 

    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea tab documents
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''documents''
    )
    CREATE TABLE [' + @schema_name + '].documents (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        collection_id   UNIQUEIDENTIFIER    NULL,
        filename        NVARCHAR(500)       NOT NULL,
        original_name   NVARCHAR(500)       NOT NULL,
        file_hash       NVARCHAR(64)        NOT NULL,   -- SHA-256, deduplicazione
        file_size       BIGINT              NOT NULL DEFAULT 0,
        mime_type       NVARCHAR(100)       NULL,
        storage_path    NVARCHAR(1000)      NULL,       -- path su object storage
        status          NVARCHAR(50)        NOT NULL DEFAULT ''pending'',
        chunk_count     INT                 NULL,
        page_count      INT                 NULL,
        language        NVARCHAR(10)        NULL DEFAULT ''it'',
        metadata        NVARCHAR(MAX)       NULL,
        uploaded_by     UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_documents] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_doc_status] CHECK (
            status IN (''pending'',''processing'',''ready'',''error'',''deleted'')
        )
    )';
    EXEC sp_executesql @sql;  --esegue sql dentro quella var locale 


    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea index su file_hash per deduplicazione veloce
    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_doc_hash'')
        CREATE INDEX [IX_' + @schema_name + '_doc_hash]
        ON [' + @schema_name + '].documents (file_hash)';
    EXEC sp_executesql @sql;  --esegue sql dentro quella var locale 


    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea tab ingestion_jobs
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''ingestion_jobs''
    )
    CREATE TABLE [' + @schema_name + '].ingestion_jobs (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        document_id     UNIQUEIDENTIFIER    NOT NULL,
        celery_task_id  NVARCHAR(255)       NULL,
        status          NVARCHAR(50)        NOT NULL DEFAULT ''queued'',
        progress_pct    TINYINT             NOT NULL DEFAULT 0,
        error_msg       NVARCHAR(MAX)       NULL,
        retry_count     TINYINT             NOT NULL DEFAULT 0,
        started_at      DATETIME2           NULL,
        finished_at     DATETIME2(3)           NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_jobs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_job_status] CHECK (
            status IN (''queued'',''running'',''done'',''failed'',''cancelled'')
        )
    )';
    EXEC sp_executesql @sql;

    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea tab conversations
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''conversations''
    )
    CREATE TABLE [' + @schema_name + '].conversations (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        user_id         UNIQUEIDENTIFIER    NOT NULL,
        collection_id   UNIQUEIDENTIFIER    NULL,       -- NULL = cross-collection
        title           NVARCHAR(500)       NULL,
        mode            NVARCHAR(50)        NOT NULL DEFAULT ''rag'',  -- rag | agent | sql
        is_archived     BIT                 NOT NULL DEFAULT 0,
        metadata        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_convs] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    --usi sempre stessa var locale @sql, ma il suo value all'interno lo cambi
    --crea tab messages
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''messages''
    )
    CREATE TABLE [' + @schema_name + '].messages (
        id                  BIGINT IDENTITY(1,1)    NOT NULL,
        conversation_id     UNIQUEIDENTIFIER        NOT NULL,
        role                NVARCHAR(20)            NOT NULL,   -- user | assistant | system
        content             NVARCHAR(MAX)           NOT NULL,
        sources             NVARCHAR(MAX)           NULL,   -- JSON: [{chunk_id, score, snippet}]
        tokens_in           INT                     NULL,
        tokens_out          INT                     NULL,
        latency_ms          INT                     NULL,
        model_used          NVARCHAR(100)           NULL,
        hallucination_score FLOAT                   NULL,   -- da ragas
        created_at          DATETIME2(3)               NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_msgs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_msg_role] CHECK (role IN (''user'',''assistant'',''system''))
    )';
    EXEC sp_executesql @sql;


    --crea index
    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_msgs_conv'')
        CREATE INDEX [IX_' + @schema_name + '_msgs_conv]
        ON [' + @schema_name + '].messages (conversation_id, created_at)';
    EXEC sp_executesql @sql;


    --crea tab feedback (thumbs up/down, rating per RAGAS evaluation loop)
    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''message_feedback''
    )
    CREATE TABLE [' + @schema_name + '].message_feedback (
        id          BIGINT IDENTITY(1,1) NOT NULL,
        message_id  BIGINT               NOT NULL,
        user_id     UNIQUEIDENTIFIER     NOT NULL,
        rating      TINYINT              NOT NULL,   -- 1=thumbs_up, 0=thumbs_down
        comment     NVARCHAR(1000)       NULL,
        created_at  DATETIME2(3)            NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_feedback] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    PRINT 'Tenant provisioned: ' + @schema_name;  --mex log su console
END
GO


EXEC shared.sp_provision_tenant    --runna creando 1 tenant (1 schema intermente per 1 'AZIENDA') fake, per testare tutto ok
    @slug         = 'demo-corp',
    @display_name = 'Demo Corporation',
    @plan         = 'pro';
GO

PRINT 'init.sql completato.';    --mex log su console
GO

