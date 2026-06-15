-- HealthCheck MySQL Schema
-- Create database first:
--   mysql -u root -p -e "CREATE DATABASE healthcheck CHARACTER SET utf8mb4;"

CREATE TABLE IF NOT EXISTS hc_services (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    url           VARCHAR(1024) NOT NULL,
    method        VARCHAR(10) DEFAULT 'GET',
    timeout       INT DEFAULT 10,
    expect_status INT DEFAULT 200,
    expect_body   TEXT,
    headers       JSON,
    active        TINYINT(1) DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hc_results (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    service_id  INT NOT NULL,
    ok          TINYINT(1) NOT NULL,
    status      INT DEFAULT 0,
    elapsed_ms  FLOAT DEFAULT 0,
    error       TEXT,
    body_match  TINYINT(1),
    checked_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES hc_services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hc_daily_logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_date    DATE NOT NULL UNIQUE,
    total       INT NOT NULL,
    healthy     INT NOT NULL,
    failed      INT NOT NULL,
    summary     JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sample services (ajusta a tus URLs reales)
INSERT INTO hc_services (name, url, method, timeout, expect_status, expect_body) VALUES
  ('Web App Prod',     'https://tudominio.com',         'GET',  10, 200, '</html>'),
  ('API Health',       'https://api.tudominio.com/health', 'GET', 10, 200, '"status":"ok"'),
  ('API Login',        'https://api.tudominio.com/auth/ping', 'POST', 5, 200, NULL),
  ('API Users',        'https://api.tudominio.com/v1/users', 'GET', 10, 200, '"id"');
