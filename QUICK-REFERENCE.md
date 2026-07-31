# ContextIQ - Quick Reference Card

## 🚀 Start/Stop Commands

```powershell
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Restart a specific service
docker compose restart api

# View logs
docker compose logs -f [service-name]

# Rebuild and restart
docker compose up -d --build --force-recreate
```

## 🌐 Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| **API Gateway** | http://localhost:8000 | - |
| **API Docs** | http://localhost:8000/docs | - |
| **Admin Portal** | http://localhost:3000 | (from Keycloak) |
| **Agent Worker** | http://localhost:8001 | - |
| **Keycloak** | http://localhost:8080/auth | admin / admin |
| **Jaeger UI** | http://localhost:16686 | - |
| **MinIO Console** | http://localhost:9001 | contextiq / contextiq_dev |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | - |
| **Neo4j Browser** | http://localhost:7474 | neo4j / contextiq_dev |

## 🧪 Testing Commands

```powershell
# Check all services
.\check-services.ps1

# Run all tests
.\run-tests.ps1 -Suite all -Verbose

# Run specific test suite
.\run-tests.ps1 -Suite unit
.\run-tests.ps1 -Suite integration
.\run-tests.ps1 -Suite api
.\run-tests.ps1 -Suite frontend

# Run with coverage
.\run-tests.ps1 -Suite all -Coverage

# Manual pytest
docker compose exec api pytest tests/unit/ -v
docker compose exec api pytest tests/integration/ -v
```

## 🔍 Health Checks

```powershell
# API health
curl http://localhost:8000/healthz

# Agent worker health
curl http://localhost:8001/healthz

# Check all containers
docker compose ps

# View container logs
docker compose logs api
docker compose logs agent-worker
docker compose logs indexing
```

## 🗄️ Database Access

```powershell
# PostgreSQL
docker compose exec postgres psql -U contextiq -d contextiq

# Redis
docker compose exec redis redis-cli --tls --insecure -a contextiq_dev

# Check migrations
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

## 🐛 Common Issues

### Port already in use
```powershell
# Find process using port
netstat -ano | findstr :8000

# Kill process or change port in docker-compose.yml
```

### Service won't start
```powershell
# Check logs
docker compose logs SERVICE_NAME

# Rebuild
docker compose up -d --build SERVICE_NAME
```

### Database migration failed
```powershell
# Run migration manually
docker compose exec api alembic upgrade head

# Reset database (CAUTION: Deletes all data)
docker compose down -v
docker compose up -d
```

### Out of disk space
```powershell
# Clean up unused Docker resources
docker system prune -af
docker volume prune
```

## 📝 Environment Configuration

```powershell
# Edit environment variables
notepad .env

# Required for AI features:
# - OPENAI_API_KEY (already set)
# - GEMINI_API_KEY (already set)
# - LANGFUSE_* (already set)

# After changes, restart services
docker compose restart api agent-worker indexing
```

## 🎯 Quick Test Scenarios

### 1. API Test
```powershell
curl http://localhost:8000/healthz
curl http://localhost:8000/docs
```

### 2. Frontend Test
```powershell
Start-Process http://localhost:3000
```

### 3. Model Installation Test
```powershell
# Ensure Ollama is running on host
curl http://localhost:11434/api/tags

# Then use Admin Portal to install a model
```

### 4. Knowledge Source Test
1. Open Admin Portal
2. Navigate to Knowledge Sources
3. Add a test source
4. Trigger sync
5. Check Jaeger for traces

## 📚 Documentation

- **Full Guide**: `LOCAL-SETUP-TESTING-GUIDE.md`
- **API Docs**: http://localhost:8000/docs
- **Architecture**: `docs/BRD.md`
- **MCP Setup**: `docs/config/README.md`

## 💡 Pro Tips

1. **Memory**: Ensure Docker Desktop has ≥8GB RAM
2. **First Run**: Initial setup takes 10-15 min (image pulls)
3. **Logs**: Use `docker compose logs -f` for real-time monitoring
4. **Reset**: `docker compose down -v` for complete reset
5. **Performance**: Stop unused services to save resources
