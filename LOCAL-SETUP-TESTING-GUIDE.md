# ContextIQ Local Setup & Testing Guide

## 🚀 Quick Start

### 1. Start All Services
```powershell
# Ensure .env file exists (already done)
docker compose up -d --build
```

### 2. Check Service Status
```powershell
.\check-services.ps1
```

### 3. View Logs
```powershell
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f agent-worker
docker compose logs -f indexing
```

---

## 🧪 Testing the Application

### **1. API Health Check**
```powershell
# Quick health check
curl http://localhost:8000/healthz

# Detailed API docs
Start-Process "http://localhost:8000/docs"
```

### **2. Admin Portal**
1. Open: http://localhost:3000
2. Login with admin credentials
3. Navigate through:
   - Dashboard
   - Knowledge Sources
   - Models
   - Policies

### **3. Test Model Installation**
```powershell
# Test Ollama model installation
# Prerequisites: Ollama running on your host machine

# Check if Ollama is running
curl http://localhost:11434/api/tags

# Then use Admin Portal (http://localhost:3000):
# 1. Go to Models → Install Model
# 2. Select "Ollama" provider
# 3. Choose "llama3.2" from popular models
# 4. Click "Install Model"
```

### **4. Run Python Backend Tests**
```powershell
# Install test dependencies (if not in Docker)
pip install pytest pytest-asyncio

# Run all tests
docker compose exec api pytest tests/ -v

# Run specific test suites
docker compose exec api pytest tests/unit/ -v
docker compose exec api pytest tests/integration/ -v
docker compose exec api pytest tests/api/ -v

# Run with coverage
docker compose exec api pytest tests/ --cov=src --cov-report=html
```

### **5. Run Frontend Tests**
```powershell
# Navigate to frontend directory
cd frontend/admin-portal

# Install dependencies (if not done)
npm install

# Run tests
npm test

# Run tests in watch mode
npm run test:watch

# Run with coverage
npm run test:coverage

# Return to root
cd ../..
```

---

## 🔍 Manual Testing Scenarios

### **Scenario 1: Knowledge Source Sync**
1. Open Admin Portal: http://localhost:3000
2. Navigate to "Knowledge Sources"
3. Add a new source (e.g., GitHub repository)
4. Configure credentials in Vault
5. Trigger sync
6. Monitor sync job status

**API Test:**
```powershell
# List knowledge sources
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/v1/knowledge-sources

# Trigger sync
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/knowledge-sources/{source_id}/sync
```

### **Scenario 2: Semantic Search**
1. Ensure knowledge sources are synced
2. Test search via API:
```powershell
$body = @{
    query = "authentication implementation"
    limit = 10
    source_ids = @("source-id-here")
} | ConvertTo-Json

curl -X POST -H "Content-Type: application/json" -H "Authorization: Bearer YOUR_TOKEN" `
  -d $body http://localhost:8000/api/v1/search/semantic
```

### **Scenario 3: Agent Workflow**
1. Open API docs: http://localhost:8000/docs
2. Navigate to Agent endpoints
3. Test clarification flow:
```powershell
# Create agent session
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/agents/sessions

# Send message to agent
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Help me debug authentication error"}' \
  http://localhost:8000/api/v1/agents/sessions/{session_id}/messages
```

### **Scenario 4: Policy Evaluation**
```powershell
# Test OPA policy
curl -X POST -H "Content-Type: application/json" \
  -d @tests/governance/sample_request.json \
  http://localhost:8181/v1/data/contextiq/governance/evaluate
```

---

## 📊 Monitoring & Observability

### **1. Jaeger Tracing**
- URL: http://localhost:16686
- View distributed traces
- Analyze request latency
- Debug service interactions

### **2. Application Logs**
```powershell
# Real-time logs
docker compose logs -f api agent-worker indexing

# Search logs
docker compose logs api | Select-String "ERROR"
```

### **3. Database Inspection**
```powershell
# Connect to PostgreSQL
docker compose exec postgres psql -U contextiq -d contextiq

# Sample queries
# \dt - List tables
# SELECT * FROM knowledge_sources;
# SELECT * FROM sync_jobs ORDER BY started_at DESC LIMIT 10;
```

### **4. Redis Inspection**
```powershell
# Connect to Redis
docker compose exec redis redis-cli --tls --insecure -a contextiq_dev

# Sample commands
# KEYS *
# GET some_key
# INFO stats
```

### **5. Qdrant Vector DB**
- Dashboard: http://localhost:6333/dashboard
- View collections
- Inspect embeddings
- Monitor vector operations

---

## 🐛 Troubleshooting

### **Services Won't Start**
```powershell
# Check container status
docker compose ps

# View logs for failed service
docker compose logs SERVICE_NAME

# Restart specific service
docker compose restart SERVICE_NAME

# Rebuild and restart
docker compose up -d --build --force-recreate SERVICE_NAME
```

### **Database Migration Issues**
```powershell
# Check migration status
docker compose exec api alembic current

# Run migrations manually
docker compose exec api alembic upgrade head

# Rollback migration
docker compose exec api alembic downgrade -1
```

### **Network Issues**
```powershell
# Recreate network
docker compose down
docker network prune
docker compose up -d
```

### **Port Conflicts**
```powershell
# Check what's using a port
netstat -ano | findstr :8000

# Change port in docker-compose.yml or .env
```

---

## 🧹 Cleanup

### **Stop All Services**
```powershell
docker compose down
```

### **Remove Volumes (Reset Everything)**
```powershell
docker compose down -v
```

### **Full Cleanup**
```powershell
docker compose down -v --rmi all
docker system prune -af
```

---

## 📝 Key Credentials

### **Keycloak**
- URL: http://localhost:8080/auth
- Admin: `admin` / `admin`
- Realm: `contextiq`

### **MinIO**
- Console: http://localhost:9001
- User: `contextiq` / `contextiq_dev`

### **Neo4j**
- Browser: http://localhost:7474
- User: `neo4j` / `contextiq_dev`

### **PostgreSQL**
- Host: localhost:5433
- User: `contextiq` / `contextiq_dev`
- Database: `contextiq`

### **Redis**
- Host: localhost:6380
- Password: `contextiq_dev`

### **Vault** (Dev Mode)
- URL: http://localhost:8200
- Token: `contextiq-dev-root-token`

---

## 🎯 Next Steps

1. **Explore API**: http://localhost:8000/docs
2. **Configure Models**: Add your LLM provider API keys in `.env`
3. **Add Knowledge Sources**: Use Admin Portal
4. **Test MCP Integration**: Configure your AI assistant (see `docs/config/`)
5. **Run Tests**: Execute test suites to verify functionality
6. **Monitor**: Check Jaeger for traces and logs for debugging

---

## 📚 Additional Documentation

- [BRD (Business Requirements)](docs/BRD.md)
- [Connector SDK](docs/connector-sdk.md)
- [Model Installation](docs/MODEL-INSTALLATION-TESTING.md)
- [MCP Configuration](docs/config/README.md)
- [Langfuse Integration](docs/LANGFUSE_INTEGRATION.md)
- [Policy Management](docs/policies/README.md)

---

## 💡 Tips

1. **First time setup**: Allow 10-15 minutes for image pulls
2. **API Keys**: Update OpenAI/Anthropic keys in `.env` for full functionality
3. **Ollama**: Install Ollama on host machine for local model testing
4. **Memory**: Ensure Docker has at least 8GB RAM allocated
5. **Logs**: Use `docker compose logs -f` to watch real-time activity
