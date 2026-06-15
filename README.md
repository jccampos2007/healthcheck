# HealthCheck

Monitor de salud para aplicaciones web y APIs REST. Chequea disponibilidad, tiempo de respuesta y contenido de hasta decenas de servicios en paralelo. Guarda histórico en MySQL y envía reportes diarios a Telegram.

## Requisitos

- Python 3.8+
- MySQL 5.7+ / MariaDB 10.3+

```bash
pip install httpx rich pymysql
```

## Setup rápido

```bash
# 1. Clonar
git clone https://github.com/jccampos2007/healthcheck.git
cd healthcheck

# 2. Configurar conexión MySQL
cp .env.healthcheck.example .env.healthcheck
# Editar .env.healthcheck con tus credenciales

# 3. Crear base de datos y tablas
python3 setup_db.py --seed

# 4. Probar
python3 healthcheck.py --db
```

## Configuración

Editar `.env.healthcheck`:

```env
HC_DB_HOST=localhost
HC_DB_PORT=3306
HC_DB_USER=admin
HC_DB_PASSWORD=tu_password
HC_DB_NAME=app_monitor
HC_TELEGRAM_BOT_TOKEN=    # opcional, para reportes diarios
HC_TELEGRAM_CHAT_ID=      # opcional
```

## Uso

```bash
# Leer servicios desde MySQL y chequear
python3 healthcheck.py --db

# Ejecución completa (chequear + guardar + Telegram)
python3 healthcheck.py --daily

# Chequear una URL rápida
python3 healthcheck.py --url https://miapp.com --expect-body "</html>"

# Desde archivo JSON
python3 healthcheck.py servicios.json
```

### Servicios desde JSON

```json
{
  "services": [
    {
      "name": "Mi App",
      "url": "https://miapp.com",
      "method": "GET",
      "timeout": 10,
      "expect_status": 200,
      "expect_body": "</html>"
    }
  ]
}
```

## Base de datos

| Tabla | Descripción |
|---|---|
| `hc_services` | Definición de servicios a monitorear |
| `hc_results` | Histórico de cada chequeo individual |
| `hc_daily_logs` | Resumen diario (1 fila por día) |

### Agregar servicios

```sql
INSERT INTO hc_services (name, url, method, expect_status, expect_body)
VALUES ('API Facturas', 'https://api.tudominio.com/v1/facturas', 'GET', 200, '"ok"');
```

### Consultar resultados

```sql
SELECT s.name, r.ok, r.status, r.elapsed_ms, r.checked_at
FROM hc_results r
JOIN hc_services s ON r.service_id = s.id
ORDER BY r.checked_at DESC
LIMIT 20;
```

## Telegram

Configurar en `.env.healthcheck`:

```env
HC_TELEGRAM_BOT_TOKEN=123456789:ABCdef123...
HC_TELEGRAM_CHAT_ID=-123456789
```

El reporte diario muestra:

```
✅ Health Check Daily Report
📅 2026-06-15

✓ Healthy: 12/12

All services are operational 🟢

⚡ Avg response: 234ms
```

## Automatizar con cron

```cron
0 8 * * * cd /home/tu_usuario/healthcheck && python3 healthcheck.py --daily >> /var/log/healthcheck.log 2>&1
```

## Mantenimiento

```bash
python3 setup_db.py          # crear tablas
python3 setup_db.py --seed   # insertar servicios de ejemplo
python3 setup_db.py --drop   # eliminar tablas
```
