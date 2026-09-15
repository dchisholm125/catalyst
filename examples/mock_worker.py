"""Exercise the worker contract once. No model, shell execution, or provider billing.

Run with CATALYST_AGENT_TOKEN set in your local environment. Output is explicitly
labeled as simulation. A real adapter must validate provider authorization first.
"""
import argparse
import os
import sys
import time
from urllib.parse import urlparse
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument('--demo-seconds', type=int, default=0, choices=range(0, 31), metavar='0..30',
                        help='Optional visible simulation duration; no inference is performed')
    parser.add_argument("--role", choices=["summarizer", "challenger", "researcher", "bridge-builder", "catalyst-drafter", "claim-extractor"], help="Only claim this role; otherwise accept any role")
    args = parser.parse_args()
    url = urlparse(args.server)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")):
        parser.error("Use HTTPS except for a loopback development server")
    token = os.getenv("CATALYST_AGENT_TOKEN")
    if not token:
        parser.error("Set a scoped CATALYST_AGENT_TOKEN; never use a provider credential here")
    job = None
    try:
        with httpx.Client(base_url=args.server, headers={"Authorization": f"Bearer {token}"}, timeout=20) as client:
            contract = client.get("/api/agent-contract")
            contract.raise_for_status()
            def heartbeat(state='connected'):
                response = client.post('/api/agents/me/heartbeat', json={'runtime': 'simulation', 'state': state})
                response.raise_for_status()

            heartbeat()
            response = client.post("/api/tasks/claim", json={"roles": [args.role]} if args.role else {})
            response.raise_for_status()
            job = response.json()
            if job["status"] != "leased":
                print(f"No work started: {job['status']} — {job['reason']}")
                heartbeat('stopped')
                return
            print("Assigned role:", job["role"], "— prior jobs provided:", len(job["agent_history"]))
            sequence = 0
            def progress(stage, excerpt=''):
                nonlocal sequence
                sequence += 1
                response = client.post(f"/api/tasks/{job['task_id']}/progress", json={
                    'lease_token': job['lease_token'], 'stage': stage, 'sequence': sequence, 'excerpt': excerpt})
                response.raise_for_status()

            progress('preparing')
            # Explicitly requested demonstration time, not an inference estimate.
            if args.demo_seconds:
                time.sleep(min(2, args.demo_seconds))
            progress('generating', 'SIMULATION ONLY: checking the assigned question and response format. No model is thinking or researching.')
            for _ in range(max(0, args.demo_seconds - 2)):
                time.sleep(1)
                progress('generating', 'SIMULATION ONLY: preparing a demonstration response. No evidence has been gathered.')
            progress('submitting', 'SIMULATION ONLY: submitting a labeled test artifact for human review.')
            result = client.post(f"/api/tasks/{job['task_id']}/complete", json={
                "lease_token": job["lease_token"], "contribution": {
                    "kind": "observation",
                    "body": "SIMULATION ONLY: the worker received this investigation and returned a text artifact. No research was performed. Question: " + job["question"],
                    "provenance": "Catalyst mock worker; no model inference, evidence verification, or external actions."}})
            result.raise_for_status()
            print("Simulation contribution accepted:", result.json()["contribution_id"])
            heartbeat('stopped')
    except (httpx.HTTPError, KeyError, ValueError) as error:
        # Report a bounded status, never raw exception details or provider secrets.
        try:
            with httpx.Client(base_url=args.server, headers={'Authorization': f'Bearer {token}'}, timeout=5) as reporter:
                if job and job.get('status') == 'leased':
                    reporter.post(f"/api/tasks/{job['task_id']}/progress", json={
                        'lease_token': job['lease_token'], 'sequence': 10000, 'stage': 'failed',
                        'excerpt': 'Simulation worker stopped before confirming completion. Check the local terminal.'})
                reporter.post('/api/agents/me/heartbeat', json={'runtime': 'simulation', 'state': 'error'})
        except httpx.HTTPError:
            pass  # Lost contact must remain unknown if even status delivery fails.
        # Do not print request headers or secrets.
        print(f"Worker stopped without retry: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
