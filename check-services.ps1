# check-services.ps1 - ContextIQ Service Health Check
Write-Host "`n=== ContextIQ Service Status ===" -ForegroundColor Cyan
Write-Host "`nDocker Containers:" -ForegroundColor Yellow
docker compose ps

Write-Host "`n`nService Health Checks:" -ForegroundColor Yellow

$services = @(
    @{Name="API Gateway"; URL="http://localhost:8000/healthz"; Port=8000}
    @{Name="Agent Worker"; URL="http://localhost:8001/healthz"; Port=8001}
    @{Name="Admin Portal"; URL="http://localhost:3000"; Port=3000}
    @{Name="Keycloak"; URL="http://localhost:8080/auth"; Port=8080}
    @{Name="Jaeger UI"; URL="http://localhost:16686"; Port=16686}
    @{Name="MinIO Console"; URL="http://localhost:9001"; Port=9001}
    @{Name="Qdrant"; URL="http://localhost:6333/dashboard"; Port=6333}
    @{Name="Neo4j Browser"; URL="http://localhost:7474"; Port=7474}
)

foreach ($service in $services) {
    try {
        $response = Invoke-WebRequest -Uri $service.URL -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        Write-Host "✓ $($service.Name) - RUNNING (port $($service.Port))" -ForegroundColor Green
    } catch {
        Write-Host "✗ $($service.Name) - NOT READY (port $($service.Port))" -ForegroundColor Red
    }
}

Write-Host "`n=== Quick Access URLs ===" -ForegroundColor Cyan
Write-Host "API Documentation:  http://localhost:8000/docs" -ForegroundColor White
Write-Host "Admin Portal:       http://localhost:3000" -ForegroundColor White
Write-Host "Keycloak Admin:     http://localhost:8080/auth (admin/admin)" -ForegroundColor White
Write-Host "Jaeger Tracing:     http://localhost:16686" -ForegroundColor White
Write-Host "MinIO Console:      http://localhost:9001 (contextiq/contextiq_dev)" -ForegroundColor White
Write-Host "Neo4j Browser:      http://localhost:7474 (neo4j/contextiq_dev)" -ForegroundColor White
Write-Host "`n"
