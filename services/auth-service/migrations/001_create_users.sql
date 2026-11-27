CREATE TABLE users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT        NOT NULL,
    password_hash TEXT        NOT NULL,
    role          TEXT        NOT NULL DEFAULT 'user',
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT users_email_key       UNIQUE (email),
    CONSTRAINT users_email_lowercase CHECK  (email = lower(email)),
    CONSTRAINT users_role_valid      CHECK  (role IN ('user', 'admin'))
);
