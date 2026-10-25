# Agents Service Definition — s6-supervised

This package converts Gmail Monitor, Mr. Moneyball, and Spy Film from
orphaned `nohup` background processes into proper s6-supervised services.

## Why this is needed

- The container's PID 1 is `s6-svscan`, which supervises services in `/run/service/`.
- Currently the agents are orphaned `nohup` processes (PPID=1).
- `nohup` only ignores SIGHUP, not SIGTERM. The coordinated `docker stop` sent
  SIGTERM at 2026-10-24 05:00:10 UTC, which killed all three agents.
- Compose uses `restart: unless-stopped` for the **container**, not the agents.
- Because the agents are not s6-supervised, they will not restart on container restart.

## What this package provides

- `agents-service/run` — s6 longrun run script that starts all three agents
  and keeps the service alive so s6-svscan tracks it.
- `agents-service/type` — service type file containing `longrun`.

## How to deploy

The service definition must be placed in the s6-rc build context so the
Docker image includes it when the bundle is compiled.

### Step 1: Add the service definition files

Copy these files into the s6-rc source directory (relative to your Dockerfile
build context):

    docker/s6-rc.d/agents-service/run
    docker/s6-rc.d/agents-service/type

### Step 2: Rebuild the Docker image

Rebuild the image using your normal Docker build command. The Dockerfile
copies `docker/s6-rc.d/` to `/etc/s6-overlay/s6-rc.d/` at build time.

### Step 3: Restart the container

Restart the container (e.g. `docker compose restart` or `docker services
restart <service>`). The s6-svscan daemon starts the agents as supervised
services.

### Step 4: Verify

Check that the agents are supervised by s6-svscan:

```bash
# Should list the agents service
s6-svstat /run/service/agents-service

# Verify processes are running
ps -eo pid,ppid,user,etime,args | grep -E "gmail-monitor|mr_moneyball|spy_film"
```

## Schedule verification

The agent schedules are verified against the configuration files:

| Agent | Schedule | Verified against |
|-------|----------|------------------|
| Gmail Monitor | Continuous polling, 600s interval, sleep window 23:00–06:00 PDT | `gmail-monitor.py` (sleep window logic) |
| Mr. Moneyball | Weekly Monday 7:00 AM PDT | `mr_moneyball_cron.sh` (Monday 7:00 target) |
| Spy Film | Weekly Thursday 7:00 AM PDT | `spy_film_cron.sh` (Thursday 7:00 target) |

Note: The user's original message mentioned "Spy Film Tuesday 5PM", but the
config files (spy_film_cron.sh) clearly state "weekly Thursday 7:00 AM PDT".
The config files are authoritative.

## Files included

- `agents-service/run` — s6 longrun run script
- `agents-service/type` — service type file

## Notes

- The run script sources `/opt/data/.env` if present for API credentials.
- Logs go to `/opt/data/cron/output/` matching the original setup.
- The service keeps `wait`ing so s6-svscan tracks it as a longrun.
