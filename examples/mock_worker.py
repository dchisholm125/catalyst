"""Exercise the worker contract once. No model, shell execution, or provider billing.

Run with CATALYST_AGENT_TOKEN set in your local environment. Output is explicitly
labeled as simulation. A real adapter must validate provider authorization first.
"""
import argparse
import os
import sys
from urllib.parse import urlparse
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    url = urlparse(args.server)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")):
        parser.error("Use HTTPS except for a loopback development server")
    token = os.getenv("CATALYST_AGENT_TOKEN")
    if not token:
        parser.error("Set a scoped CATALYST_AGENT_TOKEN; never use a provider credential here")
    try:
        with httpx.Client(base_url=args.server, headers={"Authorization": f"Bearer {token}"}, timeout=20) as client:
            response = client.post("/api/tasks/claim")
            response.raise_for_status()
            job = response.json()
            if job["status"] != "leased":
                print(f"No work started: {job['status']} — {job['reason']}")
                return
            result = client.post(f"/api/tasks/{job['task_id']}/complete", json={
                "lease_token": job["lease_token"], "contribution": {
                    "kind": "observation",
                    "body": "SIMULATION ONLY: the worker received this investigation and returned a text artifact. No research was performed. Question: " + job["question"],
                    "provenance": "Catalyst mock worker; no model inference, evidence verification, or external actions."}})
            result.raise_for_status()
            print("Simulation contribution accepted:", result.json()["contribution_id"])
    except (httpx.HTTPError, KeyError, ValueError) as error:
        # Do not print request headers or secrets.
        print(f"Worker stopped without retry: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
