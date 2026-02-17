# Code Metrics v2.0 - Guia de Despliegue

## Requisitos

- Docker y Docker Compose
- API key de Anthropic (Claude) - [console.anthropic.com](https://console.anthropic.com)
- Repositorio en GitHub con acceso para configurar secrets y workflows

---

## 1. Despliegue del servicio con Docker

### 1.1 Clonar el repositorio

```bash
git clone https://github.com/practisistemas/code-metrics-test.git
cd code-metrics-test
```

### 1.2 Configurar variables de entorno

Crear archivo `.env` en la raiz del proyecto:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-tu-clave-aqui
CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

### 1.3 Levantar con Docker Compose

```bash
docker compose up -d --build
```

Esto levanta:
- **code-metrics** en puerto `8080` - API y dashboard
- **PostgreSQL 16** en puerto `5432` - base de datos

### 1.4 Verificar que esta corriendo

```bash
# Health check
curl http://localhost:8080/health

# Respuesta esperada:
# {"status":"ok","service":"code-metrics","version":"2.0.0"}
```

### 1.5 Acceder al dashboard

Abrir en el navegador: `http://localhost:8080`

### 1.6 Comandos utiles

```bash
# Ver logs
docker compose logs -f code-metrics

# Reiniciar
docker compose restart code-metrics

# Parar todo
docker compose down

# Parar y eliminar datos (reset completo)
docker compose down -v
```

---

## 2. Despliegue en un servidor (produccion)

### Opcion A: VPS (DigitalOcean, AWS EC2, etc.)

1. Instalar Docker en el servidor
2. Clonar el repo y crear `.env` con la API key
3. Ejecutar `docker compose up -d --build`
4. Configurar un reverse proxy (nginx/caddy) para HTTPS:

```nginx
# /etc/nginx/sites-available/code-metrics
server {
    listen 443 ssl;
    server_name metrics.tudominio.com;

    ssl_certificate /etc/letsencrypt/live/metrics.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/metrics.tudominio.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

### Opcion B: Railway / Render / Fly.io

Estos servicios soportan Docker directamente:

1. Conectar el repositorio
2. Configurar variable de entorno `ANTHROPIC_API_KEY`
3. Configurar variable `DATABASE_URL` (usar el PostgreSQL que provee el servicio)
4. Puerto: `8080`

---

## 3. Configurar GitHub Actions

El workflow `.github/workflows/code-analysis.yml` ya esta incluido en el repositorio. Solo necesitas configurar los secrets.

### 3.1 Configurar secrets en tu repositorio

Ve a tu repositorio en GitHub > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**

| Secret | Valor | Descripcion |
|--------|-------|-------------|
| `METRICS_SERVICE_URL` | `https://metrics.tudominio.com` | URL del servicio desplegado (sin `/` al final) |

O por CLI:

```bash
gh secret set METRICS_SERVICE_URL --body "https://metrics.tudominio.com"
```

> **Nota:** Si usas localhost para pruebas, el workflow de GitHub Actions no podra conectarse porque corre en servidores de GitHub. Necesitas una URL publica.

### 3.2 Copiar el workflow a otros repositorios

Para analizar otros repositorios, copia el archivo de workflow:

```bash
# En el otro repositorio
mkdir -p .github/workflows
cp /ruta/code-metrics-test/.github/workflows/code-analysis.yml .github/workflows/
```

Luego configura el secret `METRICS_SERVICE_URL` en ese repositorio.

### 3.3 Que hace el workflow

Cuando haces **push** a `main`, `develop`, o `feature/**`:

1. Prepara un payload con info del commit (archivos cambiados, autor, mensaje)
2. Envia el payload a tu servicio Code Metrics (`POST /api/analyze`)
3. El servicio clona el repo, analiza el codigo, ejecuta Claude AI review
4. El workflow recibe la respuesta con score, tendencia, y opinion
5. Postea un **comentario en el commit** con los resultados
6. Sube el reporte `.md` como artifact (disponible 30 dias)
7. Falla el build si el score es menor a 30 o si hay problemas de integridad

Cuando haces **pull request** a `main`:

- Hace lo mismo pero postea un **comentario en el PR**

### 3.4 Ejemplo de comentario en commit

```
## 🟢 Code Metrics Analysis

| Metric | Value |
|--------|-------|
| **Quality Score** | **85/100** |
| **Integrity** | pass |
| **Trend** | 📈 Improving (+3.2) |
| **Lines** | +45 / -12 |

### Claude AI Opinion
Este push mejora la estructura del codigo con buenas practicas...

### Suggestions
- Considerar agregar tests unitarios para las nuevas funciones
- Extraer la logica de validacion a un modulo separado

[View Full Report](https://metrics.tudominio.com/api/report/42)
```

### 3.5 Personalizar el workflow

Puedes modificar el workflow segun tus necesidades:

**Cambiar branches monitoreados:**
```yaml
on:
  push:
    branches: [main, develop, "release/**"]
```

**Cambiar el umbral de calidad minimo (actualmente 30):**
```yaml
- name: Fail on low quality
  if: ${{ steps.analyze.outputs.score < 50 }}  # Cambiar a 50
```

**Desactivar el fallo por integridad:**
```yaml
- name: Fail on integrity issues
  if: false  # Desactivado
```

---

## 4. Endpoints disponibles

### API principal

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| `POST` | `/api/analyze` | Analizar un push (llamado por GitHub Actions) |
| `GET` | `/api/results` | Listar resultados (`?repo=nombre&limit=50`) |
| `GET` | `/api/results/{id}` | Detalle de un analisis |
| `GET` | `/api/report/{id}` | Descargar reporte `.md` |
| `GET` | `/health` | Health check |
| `GET` | `/` | Dashboard con graficas |

### Estadisticas (todos soportan `?from_date=&to_date=`)

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| `GET` | `/api/developers` | Lista de developers unicos |
| `GET` | `/api/stats/developers` | Stats por developer |
| `GET` | `/api/stats/score-evolution` | Evolucion del score (para grafica de lineas) |
| `GET` | `/api/stats/push-activity` | Actividad de pushes por semana (para barras) |
| `GET` | `/api/stats/quality-distribution` | Distribucion de calidad A-F (para donut) |
| `GET` | `/api/stats/codebase-trend` | Tendencia del codebase (snapshots) |
| `GET` | `/api/stats/leaderboard` | Ranking de developers |

### Filtros comunes

```
?repo=owner/repo-name
?developer=username
?from_date=2025-01-01
?to_date=2025-12-31
?branch=main
```

---

## 5. Estructura del proyecto

```
code-metrics/
├── .github/workflows/
│   └── code-analysis.yml    # Workflow de GitHub Actions
├── app/
│   ├── main.py              # FastAPI app + endpoint /api/analyze
│   ├── database.py          # Modelos SQLAlchemy (6 tablas)
│   ├── analyzer.py          # Analisis estatico de codigo
│   ├── claude_review.py     # Integracion con Claude AI
│   ├── integrity.py         # Validacion de integridad (secrets, debug)
│   ├── deprecation_detector.py  # Deteccion de funciones deprecadas
│   ├── reporter.py          # Generador de reportes .md
│   ├── trend_engine.py      # Motor de tendencias
│   ├── routes_stats.py      # 7 endpoints de estadisticas
│   └── templates/
│       └── dashboard.html   # Dashboard con Chart.js
├── scripts/
│   └── entrypoint.sh        # Entrypoint de Docker
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env                     # Variables de entorno (no commitear)
```

---

## 6. Troubleshooting

### El workflow falla con "HTTP 000" o connection refused
- El servicio no esta corriendo o la URL es incorrecta
- Verificar que `METRICS_SERVICE_URL` apunta a una URL publica accesible

### El workflow falla con "HTTP 400 - Git clone failed"
- El repo es privado y el servicio no tiene acceso
- Solucion: hacer el repo publico, o configurar un token de acceso en el servicio

### Claude review dice "API key not configured"
- Verificar que `ANTHROPIC_API_KEY` esta configurado en el `.env`
- Reiniciar: `docker compose restart code-metrics`

### Las graficas no cargan datos
- Verificar que hay al menos 1 analisis ejecutado
- Revisar la consola del navegador (F12) para errores de fetch

### Error "table has no column named..."
- La base de datos es de una version anterior
- Reset: `docker compose down -v && docker compose up -d --build`
