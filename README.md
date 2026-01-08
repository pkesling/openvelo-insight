# OpenVelo Insight

OpenVelo Insight is a FastAPI service that combines deterministic bike-ride suitability scoring with an LLM narration layer. It fetches current and forecast conditions (Open-Meteo by default), computes ride recommendations, and serves a simple web UI plus a JSON API.

## Features
- Deterministic ride suitability scoring and best-window recommendations
- LLM narration via Ollama (default model: `phi4-mini`)
- Open-Meteo weather + air quality by default; optional Postgres-backed source (compatible as a demo with the postgres data warehouse found in https://github.com/pkesling/event-driven-open-weather-insight)
- Session and API-key support via Redis (optional)
- Static single-page UI served from `/`

## Architecture
```text
[Static Web UI]
      |
      v
[FastAPI App] -----> (Redis Sessions + API Keys)
      |
      v
[Ride Scoring + Narration]
      |
      +--> [Forecast Source] --> [Open-Meteo API]
      |
      +--> (Postgres Forecast DB)
      |
      +--> [Ollama LLM Runtime]
```

## Deployment / Infrastructure
```text
                +----------------------+
                |  Browser / Client    |
                +----------+-----------+
                           |
                           v
                +----------------------+
                |   FastAPI App        |
                | (openvelo-insight)   |
                +----+-----------+-----+
                     |           |
                     v           v
        +----------------+   +------------------+
        | Ollama Runtime |   | Redis (optional) |
        |    (ollama)    |   | sessions + keys  |
        +----------------+   +------------------+
                     |
                     v
        +-------------------------+
        | Forecast Source         |
        | Open-Meteo (default)    |
        | or Postgres (optional)  |
        +-------------------------+
```

## Prerequisites
- Python 3.12+
- Ollama running locally or reachable over the network
- Optional: Docker + Docker Compose, Redis

## Quick Start (local)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .

# Start the API + UI
python run_server.py
```
Open `http://localhost:8000`.

If you want to skip the Ollama preflight check during development:
```bash
AGENT_SKIP_OLLAMA_CHECK=true python run_server.py
```

## Quick Start (Docker)
```bash
docker compose up --build
```
This brings up:
- `openvelo-insight` (FastAPI app)
- `ollama` (LLM runtime)
- `redis` (sessions + API keys)

The compose file expects a `.env` file. It can be empty, or you can set overrides there.

To connect to a Postgres-backed forecast source on an external Docker network:
```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

## Configuration
Most settings are read from environment variables with the `AGENT_` prefix.

Common options:
- `AGENT_OLLAMA_BASE_URL`: Ollama base URL (default `http://localhost:11434`)
- `AGENT_OLLAMA_MODEL`: Model name to use (default `phi4-mini`)
- `AGENT_AUTO_PULL_OLLAMA_MODELS`: Auto-pull missing models (`true`/`false`)
- `AGENT_SKIP_OLLAMA_CHECK`: Skip the Ollama preflight (`true`/`false`)
- `AGENT_FORECAST_SOURCE`: `open_meteo` (default) or `postgres`
- `AGENT_FORECAST_DATABASE_URL`: DB URL for forecast data (default `sqlite:///./test.db`)
- `AGENT_SESSION_REDIS_URL`: Redis URL for session storage
- `AGENT_API_KEY`: Static API key for `X-API-Key`
- `AGENT_API_KEY_REDIS_URL`: Redis URL for API key validation
- `AGENT_API_KEY_REDIS_SET`: Redis set name for API keys (default `api_keys`)

User preference defaults:
- `USER_LATITUDE_DEFAULT`, `USER_LONGITUDE_DEFAULT`
- `USER_TIMEZONE_DEFAULT`

### LLM model selection
The app uses Ollama for narration. The active model is `AGENT_OLLAMA_MODEL`, which defaults to `llama3.2:3b` if not set.

To change it for local runs:
```bash
export AGENT_OLLAMA_MODEL=llama3.2:3b
python run_server.py
```

To change it for Docker Compose, set `AGENT_OLLAMA_MODEL` in your `.env` file:
```bash
AGENT_OLLAMA_MODEL=llama3.2:3b
```

Additional models can be found at https://ollama.com.

## API Overview
- `POST /v1/session/start`: Fetch conditions and create a session
- `POST /v1/session/{session_id}/initial`: Build the initial assessment + narration
- `POST /v1/session/{session_id}/chat`: Continue the conversation
- `POST /v1/session/{session_id}/refresh`: Refresh conditions + assessment
- `GET /v1/session/{session_id}/preferences`: Get user preferences
- `POST /v1/session/{session_id}/preferences`: Update user preferences

Example:
```bash
curl -X POST http://localhost:8000/v1/session/start
```
If `AGENT_API_KEY` or Redis-based API keys are enabled, include:
```bash
curl -H "X-API-Key: <your-key>" -X POST http://localhost:8000/v1/session/start
```

Using Redis for API keys:
- Set `AGENT_API_KEY_REDIS_URL` (and optionally `AGENT_API_KEY_REDIS_SET`).
- Add keys to the Redis set:
```bash
redis-cli -u "$AGENT_API_KEY_REDIS_URL" SADD api_keys "your-api-key"
```
- If you want Redis to be authoritative, unset `AGENT_API_KEY` to avoid static fallback.

## Running Tests
```bash
pytest
```

## Project Structure
- `app/`: FastAPI app, agent logic, data sources
- `static/`: Front-end UI
- `tests/`: Test suite
- `run_server.py`: App entrypoint

## License
See LICENSE file
