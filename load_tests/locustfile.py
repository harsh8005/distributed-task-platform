import random
import uuid
from locust import HttpUser, between, task


class TaskPlatformUser(HttpUser):
    wait_time = between(0.1, 1.0)
    token = None
    user_id = None
    created_job_ids = []

    def on_start(self):
        """Register and log in each virtual user upon starting."""
        unique_suffix = str(uuid.uuid4())[:8]
        self.email = f"loadtest_{unique_suffix}@example.com"
        self.password = "LoadTestPassword123!"

        # Register
        reg_resp = self.client.post(
            "/auth/register",
            json={
                "email": self.email,
                "password": self.password,
                "full_name": f"Load Tester {unique_suffix}",
            },
            name="Auth: Register",
        )

        # Login
        login_resp = self.client.post(
            "/auth/login",
            json={"email": self.email, "password": self.password},
            name="Auth: Login",
        )
        if login_resp.status_code == 200:
            data = login_resp.json()
            self.token = data["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}

    @task(5)
    def submit_compute_job(self):
        """Submit a compute job with random priority and idempotency key."""
        if not self.token:
            return

        priority = random.randint(1, 10)
        idempotency_key = f"load-{uuid.uuid4()}"
        correlation_id = f"trace-{uuid.uuid4()}"

        payload = {
            "job_type": "math",
            "priority": priority,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "payload": {
                "action": "sum",
                "numbers": [random.randint(1, 1000) for _ in range(5)],
            },
        }

        resp = self.client.post("/jobs", json=payload, headers=self.headers, name="Jobs: Create")
        if resp.status_code == 201:
            job_id = resp.json().get("id")
            if job_id:
                self.created_job_ids.append(job_id)
                if len(self.created_job_ids) > 50:
                    self.created_job_ids.pop(0)

    @task(3)
    def query_recent_job(self):
        """Check the status of a previously submitted job."""
        if not self.token or not self.created_job_ids:
            return

        job_id = random.choice(self.created_job_ids)
        self.client.get(f"/jobs/{job_id}", headers=self.headers, name="Jobs: Get Status")

    @task(2)
    def inspect_attempts(self):
        """Audit the attempt history of a recent job."""
        if not self.token or not self.created_job_ids:
            return

        job_id = random.choice(self.created_job_ids)
        self.client.get(f"/jobs/{job_id}/attempts", headers=self.headers, name="Jobs: Get Attempts")

    @task(2)
    def fetch_dashboard(self):
        """Fetch system-wide cached dashboard metrics."""
        if not self.token:
            return
        self.client.get("/jobs/dashboard/stats", headers=self.headers, name="Jobs: Dashboard Stats")

    @task(1)
    def health_check(self):
        """Verify API operational readiness."""
        self.client.get("/health", name="System: Health")
        self.client.get("/ready", name="System: Ready")
