# Distributed Task Platform Architecture

## 1. What This Project Is

This is a backend system for creating, storing, scheduling, and processing jobs asynchronously.

It is built around a simple but realistic distributed workflow:

- a FastAPI API accepts authenticated job requests
- jobs are stored in the database
- a worker claims jobs and processes them in the background
- a scheduler releases delayed jobs when they become due
- Prometheus metrics and health checks expose operational status

The project is designed to teach and demonstrate backend engineering fundamentals such as:

- authentication
- database modeling
- queue-driven processing
- retry and dead-letter handling
- job state transitions
- observability
- backend testing

## 2. High-Level Flow

```text
Client
  -> FastAPI API
      -> Database stores job
      -> Queue publishes job message
          -> Worker claims job
              -> Worker processes payload
                  -> Job marked completed / retrying / dead_letter
                      -> Metrics and attempt history updated
```

For delayed jobs:

```text
Client creates scheduled job
  -> Job stored with future run_at
      -> Scheduler checks due jobs
          -> Moves job into queued state
              -> Worker processes it
```

## 3. Main Components

### API layer

The API lives in `app/main.py` and `app/routers/`.

Responsibilities:

- register and authenticate users
- accept job creation requests
- list and inspect jobs
- retry jobs
- expose health and metrics endpoints

Important files:

- `app/main.py`
- `app/routers/auth.py`
- `app/routers/jobs.py`
- `app/routers/health.py`

### Service layer

The business logic lives in `app/services.py`.

Responsibilities:

- create users
- authenticate users
- create jobs
- claim jobs
- update job state
- store job attempts
- compute dashboard stats
- retry jobs

### Database layer

The persistence layer lives in `app/models.py` and `app/database.py`.

Entities:

- `User`
- `Job`
- `JobAttempt`

The `Job` table stores the lifecycle state of each job.
The `JobAttempt` table stores each processing attempt so failures are visible and explainable.

### Worker

The worker lives in `worker.py`.

Responsibilities:

- claim jobs
- execute the payload
- record success or failure
- retry or dead-letter failed jobs
- measure processing time

### Scheduler

The scheduler lives in `scheduler.py`.

Responsibilities:

- find jobs whose `run_at` time has arrived
- move them from `scheduled` to `queued`
- publish them for processing

### Queue and cache

Queue logic is in `app/broker.py`.

Cache logic is in `app/cache.py`.

Responsibilities:

- publish jobs to RabbitMQ when enabled
- fall back to database polling when RabbitMQ is disabled
- cache dashboard stats for a short period

### Observability

Observability lives in `app/observability.py`.

It exposes:

- job creation count
- job completion count
- job failure count
- job retry count
- worker activity
- queue depth
- processing duration histogram

## 4. Job Lifecycle

The lifecycle is the most important part of the system.

### Statuses

- `queued`
- `scheduled`
- `running`
- `retrying`
- `completed`
- `dead_letter`

### Flow

1. User creates a job.
2. The API stores the job in the database.
3. If the job is immediate, it is published to the queue.
4. A worker claims the job and marks it `running`.
5. The worker executes the payload.
6. If the work succeeds, the job becomes `completed`.
7. If it fails and retries remain, the job becomes `retrying`.
8. If retries are exhausted, the job becomes `dead_letter`.
9. Each attempt is saved in `job_attempts`.

## 5. Why This Design Is Good

This design demonstrates real backend skills because it separates concerns:

- API handles HTTP and auth
- services handle business rules
- models handle persistence
- worker handles background execution
- scheduler handles delayed delivery
- observability handles operational visibility

That separation makes the system easier to test, extend, and explain.

## 6. How To Use It

### Local flow

1. Install dependencies.
2. Start the API.
3. Start the worker.
4. Start the scheduler if you want delayed jobs.
5. Register a user and log in.
6. Create a job.
7. Inspect the job and its attempts.

### Useful endpoints

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/attempts`
- `POST /jobs/{job_id}/retry`
- `GET /jobs/dashboard/stats`
- `GET /health`
- `GET /ready`
- `GET /metrics`

## 7. Interview Explanation

If someone asks you what this project does, say:

"I built a distributed task platform where users authenticate, create jobs, and have those jobs processed asynchronously by workers. The system supports scheduling, retries, dead-letter handling, attempt history, health checks, and Prometheus metrics. I separated the API, service layer, worker, scheduler, and persistence logic so the system is easy to reason about and extend."

## 8. Resume Bullets

You can describe the project like this:

- Built a FastAPI-based distributed job platform with authenticated job creation, retries, scheduling, and background processing.
- Implemented worker-driven job execution with PostgreSQL persistence and optional RabbitMQ/Redis integration.
- Added job attempt tracking, dead-letter handling, health checks, and Prometheus metrics for better reliability and observability.
- Wrote backend tests for auth, job lifecycle behavior, retry rules, and failure scenarios.

## 9. Probable Interview Questions

### System design and architecture

**Q: What problem does this project solve?**  
A: It offloads work from the request-response path and processes jobs asynchronously so the API stays responsive.

**Q: Why did you separate the API, worker, and scheduler?**  
A: Each process has a different responsibility, which keeps the system easier to scale, debug, and maintain.

**Q: Why is there a scheduler if jobs already exist in the database?**  
A: The scheduler promotes delayed jobs at the right time, so the worker only handles jobs that are ready to run.

**Q: Why support both database polling and RabbitMQ?**  
A: Database polling makes local development easy, while RabbitMQ shows a more realistic queue-based deployment option.

**Q: What happens when a job fails?**  
A: The worker records the failed attempt, retries if attempts remain, and moves the job to dead letter when retries are exhausted.

**Q: What is dead-letter handling?**  
A: It is the final state for jobs that failed too many times and should not keep retrying.

**Q: How do you avoid duplicate job execution?**  
A: The worker claims jobs in a running state before processing, and the service layer validates claimable states before marking work as active.

**Q: How are job attempts stored?**  
A: Each attempt is inserted into a `job_attempts` table with attempt number, status, error message, worker ID, and timestamps.

**Q: Why store attempt history separately from the job row?**  
A: It keeps the current state lightweight while preserving a full audit trail of every execution attempt.

**Q: How does retry work?**  
A: Failed jobs can be re-queued immediately or after a delay, and the retry action clears stale result and error state.

**Q: Why track `run_at`?**  
A: It lets the platform support scheduled work instead of only immediate background jobs.

### API and auth

**Q: How does authentication work?**  
A: Users register and log in to receive JWT access and refresh tokens, and protected routes validate the access token.

**Q: Why use JWT here?**  
A: It is lightweight, stateless for API requests, and good for demonstrating practical auth in a backend project.

**Q: What endpoints are protected?**  
A: Job creation, listing, inspection, retry, and attempt history are all tied to the current authenticated user.

**Q: How do you prevent users from seeing each other's jobs?**  
A: The job lookup functions filter by `owner_id`, so each user only accesses their own records.

**Q: How would you improve auth in a production version?**  
A: I would add refresh-token storage, logout/revocation, stricter session tracking, and better role-based access control.

### Data and persistence

**Q: Why use SQLAlchemy and not raw SQL?**  
A: It keeps the code easier to maintain, safer to evolve, and more expressive for backend logic.

**Q: Why use SQLite locally and PostgreSQL in deployment?**  
A: SQLite makes local setup easy, while PostgreSQL is a better production-grade relational database.

**Q: Why do the timestamps use naive UTC values?**  
A: The project normalizes times to UTC-naive for storage simplicity, which is common in many backend codebases.

**Q: What are the main job statuses?**  
A: `queued`, `scheduled`, `running`, `retrying`, `completed`, and `dead_letter`.

**Q: What is the purpose of the `attempts` counter on the job row?**  
A: It gives a quick summary of how many times the job has been processed.

### Worker behavior

**Q: What does the worker actually do?**  
A: It claims jobs, interprets the payload, runs the action, and records the final state.

**Q: What payload actions are supported?**  
A: `sum`, `uppercase`, `sleep`, `fail`, and a default echo-style action.

**Q: How does the worker measure performance?**  
A: It records processing duration with a Prometheus histogram.

**Q: Why log worker ID?**  
A: It makes it easier to trace which worker processed which job.

**Q: How would you make the worker more production-ready?**  
A: I would add structured logging, heartbeats, graceful shutdown handling, and stronger duplicate-claim protection.

### Observability and operations

**Q: What metrics does the project expose?**  
A: Job created, completed, failed, retried, active workers, queue length, and processing duration.

**Q: Why are health and readiness endpoints important?**  
A: They let deployment platforms and operators know whether the app is alive and ready to serve traffic.

**Q: Why cache dashboard stats?**  
A: It reduces repeated database queries for data that does not need to update every request.

**Q: What would you monitor in production?**  
A: Queue depth, retry rate, failure rate, dead-letter count, worker count, and job latency.

### Testing

**Q: What do your tests cover?**  
A: Auth flow, job lifecycle behavior, retry rules, attempt history, and failure handling.

**Q: What would you add next in testing?**  
A: HTTP integration tests, worker/scheduler tests, metrics tests, and more edge-case coverage.

### Tradeoffs and limitations

**Q: What is the biggest limitation of the current design?**  
A: It is still a learning project, so it lacks production features like fully structured logging, distributed tracing, and deep queue hardening.

**Q: If you had more time, what would you build next?**  
A: I would add idempotency keys, structured logs, better retry backoff, richer dashboards, and more end-to-end tests.

**Q: Why is this a good resume project for a 1-year backend engineer?**  
A: Because it shows practical backend skills beyond CRUD, including auth, async processing, persistence, observability, and testing.
