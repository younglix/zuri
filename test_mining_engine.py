#!/usr/bin/env python3
"""
Test to verify the mining engine scheduler is properly initialized
"""

import sys
import time
import os

# Import the app module (this should trigger scheduler initialization)
print("[TEST] Importing app module...")
from app import app, scheduler, run_mining_engine

print(f"[TEST] Scheduler object exists: {scheduler is not None}")
print(f"[TEST] Scheduler running: {scheduler.running}")

# List all jobs
jobs = scheduler.get_jobs()
print(f"[TEST] Total scheduled jobs: {len(jobs)}")

for job in jobs:
    print(f"  - Job ID: {job.id}")
    print(f"    Function: {job.func.__name__}")
    print(f"    Trigger: {job.trigger}")
    print(f"    Next run: {job.next_run_time}")

if any(job.id == 'mining_engine' for job in jobs):
    print("\n✅ SUCCESS: Mining engine scheduler is properly initialized!")
    print("   The scheduler will run every 60 seconds when the app starts.")
else:
    print("\n❌ FAILED: Mining engine job not found in scheduler!")
    sys.exit(1)
