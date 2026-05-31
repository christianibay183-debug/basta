-- Run this in your Neon/PostgreSQL database to set up user credentials with RBAC

CREATE TABLE IF NOT EXISTS user_credentials (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          VARCHAR(16) NOT NULL DEFAULT 'viewer'
                  CHECK (role IN ('admin', 'operator', 'viewer')),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Example: insert an admin user
-- Replace 'your_bcrypt_hash' with the output of generate_password_hash('yourpassword')
-- INSERT INTO user_credentials (username, password_hash, role)
-- VALUES ('admin', 'your_bcrypt_hash', 'admin');

-- Role permissions reference:
-- admin    -> dashboard, footage, logs, cameras (full access)
-- operator -> dashboard, footage, cameras
-- viewer   -> dashboard only
