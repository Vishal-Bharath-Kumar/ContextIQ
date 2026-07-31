# run-tests.ps1 - ContextIQ Test Runner
param(
    [string]$Suite = "all",
    [switch]$Coverage,
    [switch]$Verbose
)

Write-Host "`n=== ContextIQ Test Runner ===" -ForegroundColor Cyan
Write-Host "Test Suite: $Suite`n" -ForegroundColor Yellow

function Test-ServiceRunning {
    param([int]$Port)
    try {
        $null = Test-NetConnection -ComputerName localhost -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
        return $?
    } catch {
        return $false
    }
}

# Check if API is running
if (-not (Test-ServiceRunning -Port 8000)) {
    Write-Host "⚠️  API service is not running. Starting services..." -ForegroundColor Yellow
    docker compose up -d api
    Write-Host "Waiting for API to be ready..."
    Start-Sleep -Seconds 10
}

$pytestArgs = @("tests/")
if ($Verbose) { $pytestArgs += "-v" }
if ($Coverage) { $pytestArgs += @("--cov=src", "--cov-report=html", "--cov-report=term") }

switch ($Suite) {
    "unit" {
        Write-Host "Running Unit Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/unit/"
        docker compose exec api pytest @pytestArgs
    }
    "integration" {
        Write-Host "Running Integration Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/integration/"
        docker compose exec api pytest @pytestArgs
    }
    "api" {
        Write-Host "Running API Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/api/"
        docker compose exec api pytest @pytestArgs
    }
    "agents" {
        Write-Host "Running Agent Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/agents/"
        docker compose exec api pytest @pytestArgs
    }
    "auth" {
        Write-Host "Running Auth Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/auth/"
        docker compose exec api pytest @pytestArgs
    }
    "connectors" {
        Write-Host "Running Connector Tests..." -ForegroundColor Green
        $pytestArgs[0] = "tests/connectors/"
        docker compose exec api pytest @pytestArgs
    }
    "frontend" {
        Write-Host "Running Frontend Tests..." -ForegroundColor Green
        Set-Location frontend/admin-portal
        if ($Coverage) {
            npm run test:coverage
        } else {
            npm test
        }
        Set-Location ../..
    }
    "all" {
        Write-Host "Running All Backend Tests..." -ForegroundColor Green
        docker compose exec api pytest @pytestArgs
        
        Write-Host "`nRunning Frontend Tests..." -ForegroundColor Green
        Set-Location frontend/admin-portal
        npm test
        Set-Location ../..
    }
    default {
        Write-Host "Invalid test suite. Available options:" -ForegroundColor Red
        Write-Host "  unit, integration, api, agents, auth, connectors, frontend, all"
        exit 1
    }
}

if ($Coverage) {
    Write-Host "`n📊 Coverage report generated at htmlcov/index.html" -ForegroundColor Cyan
    # Start-Process "htmlcov/index.html"
}

Write-Host "`n✅ Tests completed!" -ForegroundColor Green
