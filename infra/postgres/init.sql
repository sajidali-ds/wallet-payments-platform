CREATE DATABASE auth_db;
CREATE DATABASE wallet_db;
CREATE DATABASE notification_db;
-- Separate databases for integration tests, so tests can truncate freely.
-- (The wallet-service tests also create theirs on demand if it is missing.)
CREATE DATABASE auth_test_db;
CREATE DATABASE wallet_test_db;
CREATE DATABASE notification_test_db;
