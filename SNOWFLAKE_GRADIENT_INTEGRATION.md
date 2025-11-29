# Snowflake & Gradient Integration Guide

## Overview
This document describes the complete integration of CognitoForge with Snowflake (data warehouse) and DigitalOcean Gradient (AI compute platform).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                          │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ Dashboard   │  │  Demo Page   │  │  Welcome Dashboard       │ │
│  │  Component  │  │   (Reports)  │  │                          │ │
│  └─────┬───────┘  └──────┬───────┘  └──────────────────────────┘ │
│        │                 │                                         │
│        └─────────────────┴─────────────────┐                      │
│                                             │                      │
│                   ┌─────────────────────────▼──────────────────┐  │
│                   │     API Service (lib/api.ts)               │  │
│                   │  - getAllSimulations()                     │  │
│                   │  - getAnalyticsSummary()                   │  │
│                   │  - getGradientStatus()                     │  │
│                   │  - simulateAttack()                        │  │
│                   └─────────────────────────┬──────────────────┘  │
└─────────────────────────────────────────────┼───────────────────────┘
                                              │
                    HTTP/REST (NEXT_PUBLIC_BACKEND_URL)
                                              │
┌─────────────────────────────────────────────▼───────────────────────┐
│                      Backend (FastAPI)                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │         Operations Router (routers/operations.py)            │ │
│  │                                                              │ │
│  │  POST /upload_repo                                          │ │
│  │  POST /simulate_attack  ◄──┐                               │ │
│  │  GET  /reports/{repo_id}/latest                            │ │
│  │  GET  /api/simulations/list                                │ │
│  │  GET  /analytics/summary   ◄──┐                            │ │
│  │  GET  /api/gradient/status ◄──┼──┐                         │ │
│  └───────────────────┬────────────┼──┼──────────────────────────┘ │
│                      │            │  │                            │
│           ┌──────────▼────────┐   │  │                            │
│           │  Gradient Service │───┘  │                            │
│           │  (simulated)      │      │                            │
│           └───────────────────┘      │                            │
│                                      │                            │
│           ┌──────────────────────────▼──────────────────────┐    │
│           │   Snowflake Integration Service                │    │
│           │   (integrations/snowflake_service.py)          │    │
│           │                                                 │    │
│           │  - store_simulation_run()                      │    │
│           │  - store_affected_files()                      │    │
│           │  - store_ai_insight()                          │    │
│           │  - fetch_severity_summary()                    │    │
│           │  - fetch_latest_simulation_report()            │    │
│           └─────────────────────┬───────────────────────────┘    │
└─────────────────────────────────┼────────────────────────────────┘
                                  │
                       Snowflake Connector
                                  │
                  ┌───────────────▼────────────────┐
                  │     Snowflake Warehouse       │
                  │                                │
                  │  Tables:                       │
                  │  - simulation_runs             │
                  │  - affected_files              │
                  │  - ai_insights                 │
                  └────────────────────────────────┘
```

## 1. Snowflake Integration

### Backend Components

#### Tables Schema
```sql
-- Simulation metadata
CREATE TABLE IF NOT EXISTS simulation_runs (
    repo_id VARCHAR,
    run_id VARCHAR,
    overall_severity VARCHAR,
    timestamp TIMESTAMP
);

-- Affected files per simulation
CREATE TABLE IF NOT EXISTS affected_files (
    repo_id VARCHAR,
    run_id VARCHAR,
    file_path VARCHAR,
    severity VARCHAR
);

-- AI-generated insights
CREATE TABLE IF NOT EXISTS ai_insights (
    repo_id VARCHAR,
    run_id VARCHAR,
    insight TEXT
);
```

#### Backend Functions (`backend/app/integrations/snowflake_service.py`)

```python
# Store simulation metadata
store_simulation_run(repo_id, run_id, summary) -> bool

# Store affected files
store_affected_files(repo_id, run_id, file_list) -> bool

# Store AI insights
store_ai_insight(repo_id, run_id, insight) -> bool

# Fetch severity analytics
fetch_severity_summary() -> Dict[str, int]

# Fetch simulation reports
fetch_latest_simulation_report(repo_id) -> Dict[str, Any]
fetch_simulation_report(repo_id, run_id) -> Dict[str, Any]
```

#### API Endpoint
```
GET /analytics/summary

Response:
{
  "critical": 5,
  "high": 12,
  "medium": 8,
  "low": 3
}
```

### Frontend Components

#### API Service (`frontend/src/lib/api.ts`)
```typescript
export async function getAnalyticsSummary(): Promise<ApiResponse<SnowflakeSeveritySummary>>

interface SnowflakeSeveritySummary {
  critical: number;
  high: number;
  medium: number;
  low: number;
}
```

#### Dashboard Display (`frontend/src/components/Dashboard.tsx`)
- **Snowflake Analytics Card**: Displays severity counts from warehouse
- **Real-time sync indicator**: Shows data freshness
- **Fallback handling**: Graceful degradation when Snowflake unavailable

### Configuration

Environment variables (backend `.env`):
```bash
COGNITOFORGE_SNOWFLAKE_ACCOUNT=your_account.region
COGNITOFORGE_SNOWFLAKE_USER=your_username
COGNITOFORGE_SNOWFLAKE_PASSWORD=your_password
COGNITOFORGE_SNOWFLAKE_WAREHOUSE=COGNITOFORGE_WH
COGNITOFORGE_SNOWFLAKE_DATABASE=COGNITOFORGE_DB
COGNITOFORGE_SNOWFLAKE_SCHEMA=PUBLIC
```

### Data Flow

1. **Write Path** (during `/simulate_attack`):
   ```
   User triggers analysis
   → Backend generates attack plan
   → store_simulation_run() persists metadata
   → store_affected_files() persists file list
   → store_ai_insight() persists Gemini analysis
   ```

2. **Read Path** (dashboard refresh):
   ```
   Dashboard loads
   → GET /analytics/summary
   → fetch_severity_summary() queries Snowflake
   → Returns aggregated counts
   → UI renders Snowflake Analytics card
   ```

## 2. Gradient Integration

### Backend Components

#### Gradient Service (`backend/app/services/gradient_service.py`)

```python
# Initialize cluster (mock mode)
init_gradient() -> bool

# Run AI task
run_gradient_task(task_name: str, payload: Dict[str, Any]) -> Dict[str, Any]

# Get cluster status
get_gradient_status() -> Dict[str, Any]
```

**Task Response Format:**
```json
{
  "status": "success",
  "task": "ai_insight",
  "output": "Gemini-generated insight text...",
  "metadata": {
    "runtime_env": "DigitalOcean Gradient (Simulated)",
    "instance_type": "g1-small (mock)",
    "execution_time": 1.234
  }
}
```

#### API Endpoints

```
GET /api/gradient/status

Response:
{
  "success": true,
  "status": {
    "connected": true,
    "mock_mode": true,
    "message": "Connected to DigitalOcean Gradient (Simulated Mode)"
  }
}
```

### Frontend Components

#### API Service (`frontend/src/lib/api.ts`)
```typescript
export async function getGradientStatus(): Promise<ApiResponse<{
  success: boolean;
  status: GradientStatus;
}>>

interface GradientStatus {
  connected: boolean;
  mock_mode: boolean;
  message: string;
}

interface GradientTaskMetadata {
  runtime_env: string;
  instance_type: string;
  execution_time: number;
}
```

#### Dashboard Display (`frontend/src/components/Dashboard.tsx`)
- **Gradient Cluster Card**: Connection status with pulse indicator
- **Mode Badge**: Production vs Simulated
- **Mock Mode Warning**: Development indicator

#### Demo Page Display (`frontend/src/app/demo/page.tsx`)
- **Gradient Execution Environment Card**: Task metadata after analysis
- **Runtime Environment**: Shows compute instance details
- **Execution Time**: Displays actual task duration
- **Instance Type**: Shows Gradient instance specification

### Data Flow

1. **During Simulation** (`/simulate_attack`):
   ```
   Attack plan generated
   → Gradient payload prepared
   → run_gradient_task("ai_insight", payload)
   → Task executes (calls Gemini internally)
   → Returns status + metadata
   → Response includes "gradient" field
   ```

2. **Status Check** (dashboard):
   ```
   Dashboard loads
   → GET /api/gradient/status
   → get_gradient_status() returns cluster info
   → UI renders Gradient Cluster card
   ```

## 3. Environment Variables

### Frontend (`frontend/.env.local`)
```bash
# Backend API URL
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000

# Auth0 (existing)
AUTH0_SECRET=...
AUTH0_BASE_URL=...
AUTH0_ISSUER_BASE_URL=...
AUTH0_CLIENT_ID=...
AUTH0_CLIENT_SECRET=...
```

### Backend (`backend/.env`)
```bash
# Gemini AI
COGNITOFORGE_GEMINI_API_KEY=your_gemini_key
COGNITOFORGE_USE_GEMINI=true

# Snowflake
COGNITOFORGE_SNOWFLAKE_ACCOUNT=account.region
COGNITOFORGE_SNOWFLAKE_USER=username
COGNITOFORGE_SNOWFLAKE_PASSWORD=password
COGNITOFORGE_SNOWFLAKE_WAREHOUSE=warehouse_name
COGNITOFORGE_SNOWFLAKE_DATABASE=database_name
COGNITOFORGE_SNOWFLAKE_SCHEMA=schema_name

# Gradient (optional, defaults to mock)
USE_GRADIENT_MOCK=true

# GitHub (optional)
COGNITOFORGE_GITHUB_TOKEN=ghp_...
```

## 4. UI Features

### Dashboard Components

#### Snowflake Analytics Section
- ✅ Real-time severity counts (Critical, High, Medium, Low)
- ✅ Sync status indicator
- ✅ Fallback state when unavailable
- ✅ Color-coded severity displays

#### Gradient Cluster Section
- ✅ Connection status with pulse animation
- ✅ Production/Simulated mode badge
- ✅ Status message display
- ✅ Mock mode warning banner

#### Recent Simulations
- ✅ Last 5 simulations with metadata
- ✅ AI-powered vs deterministic badges
- ✅ Severity indicators
- ✅ Time ago formatter
- ✅ AI insight preview

### Demo Page Enhancements

#### Gradient Metadata Card (new)
- Task status indicator
- Runtime environment details
- Execution time display
- Instance type specification
- Mock mode indicator

## 5. Error Handling

### Snowflake
- **Connection Failure**: Falls back to local severity calculation
- **Query Errors**: Logs error, returns empty/zero counts
- **Missing Credentials**: Silently skips, displays "unavailable" UI

### Gradient
- **Task Failure**: Returns error status in response
- **Service Down**: Returns "unavailable" status
- **Mock Mode**: Transparent indicator in UI

## 6. Testing

### Backend Tests
```bash
# Test Snowflake connection
curl http://127.0.0.1:8000/analytics/summary

# Test Gradient status
curl http://127.0.0.1:8000/api/gradient/status

# Test full simulation with both integrations
curl -X POST http://127.0.0.1:8000/simulate_attack \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"test-repo", "force":true}'
```

### Frontend Tests
1. Navigate to `/dashboard`
2. Verify Snowflake Analytics card displays counts
3. Verify Gradient Cluster card shows status
4. Run a simulation from `/demo`
5. Verify Gradient metadata appears in report
6. Click "Refresh" on dashboard
7. Verify data updates

## 7. Performance Considerations

### Snowflake
- **Connection Pooling**: Single reusable connection per app instance
- **Query Optimization**: Indexed columns (repo_id, run_id, timestamp)
- **Batch Inserts**: `executemany()` for affected_files
- **Caching**: 10-minute TTL on dashboard data

### Gradient
- **Async Execution**: `run_in_threadpool()` prevents blocking
- **Timeout Handling**: Configurable task timeouts
- **Graceful Degradation**: Continues if Gradient unavailable
- **Mock Mode**: Zero latency for development

## 8. Security

### Credentials Management
- All secrets in environment variables
- `.gitignore` excludes `.env` files
- `.env.example` files for documentation only
- Snowflake password never logged

### API Security
- CORS configured for frontend origin
- No sensitive data in API responses
- Error messages sanitized
- Optional Auth0 JWT validation ready

## 9. Monitoring & Logging

### Backend Logs
```python
logger.info("Snowflake data synced", extra={"repo_id": repo_id})
logger.info("Gradient task completed", extra={"execution_time": 1.234})
logger.error("Snowflake connection failed", extra={"error": str(exc)})
```

### Frontend Logs
```typescript
console.log('Dashboard data refreshed:', stats);
console.error('Failed to fetch Gradient status:', error);
```

## 10. Future Enhancements

### Planned Features
- [ ] Snowflake query result caching
- [ ] Gradient real-time task streaming
- [ ] Historical trend charts from Snowflake
- [ ] Gradient task queue management
- [ ] Snowflake materialized views for analytics
- [ ] Gradient cost tracking per task

### Production Readiness
- [ ] Snowflake connection pool tuning
- [ ] Gradient production API integration
- [ ] Rate limiting on API endpoints
- [ ] Comprehensive error recovery
- [ ] Performance metrics collection
- [ ] Audit logging to Snowflake

## Support

For issues or questions:
- Backend: Check `backend/app/integrations/snowflake_service.py`
- Frontend: Check `frontend/src/lib/api.ts` and Dashboard component
- Configuration: Review `.env.example` files
- Logs: Check console output for detailed error messages
