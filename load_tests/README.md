# Locust Load Testing Guide

This directory contains automated load and performance testing suites for the Distributed Task Platform using **Locust**.

---

## 1. What the Load Test Measures

The simulation models real-world tenant behaviors:
- **Authentication**: Concurrent user registration and JWT token negotiation.
- **Job Submission**: Burst and sustained task creation across priorities (1–10) with idempotency keys and trace IDs.
- **Polling & Auditing**: High-frequency job status queries and attempt inspection.
- **Dashboard Load**: Cache hit/miss rates on `/jobs/dashboard/stats` backed by Redis.
- **System Metrics**: p50, p95, and p99 latencies, HTTP error rates, and queue drain throughput.

---

## 2. Running the Load Test

### Prerequisites
Make sure the platform is running (locally or via Docker Compose):
```bash
docker compose up -d
```

### Option A: Interactive Web UI Mode
Start Locust and navigate to `http://localhost:8089`:
```bash
locust -f load_tests/locustfile.py --host http://localhost:8000
```
- Set **Number of Users**: `100`
- Set **Spawn Rate**: `10`
- Start Swarming and watch real-time charts.

### Option B: Automated Headless CLI Mode (CI / Benchmarking)
Run a 60-second benchmark and output results directly to terminal:
```bash
locust -f load_tests/locustfile.py --headless -u 50 -r 10 --run-time 1m --host http://localhost:8000
```

---

## 3. Recommended Performance Baselines

| Metric | Target | Failure Threshold |
| :--- | :--- | :--- |
| **API p95 Response Time** | < 25ms | > 100ms |
| **Error Rate** | 0.0% | > 0.5% |
| **Throughput (1 Worker)** | ~80–120 jobs/sec | < 40 jobs/sec |
| **Queue Backlog Recovery** | Drains monotonically | Growing queue without plateau |
