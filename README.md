# eisen.

**Hotel service prioritization and guest recovery, with people in control.**

Eisen helps hotel teams decide which guest issues need attention, who can handle them, and when a recovery offer is more useful than a repair. It is designed as a decision-support layer for existing hotel operations, with a planned HotSOS integration and familiar 1–5 priorities. The current MVP runs locally with separate agent and worker portals.

Built by **Global Solutions for Cornell Hospitality Hackathon 2026**. The sample property is **Waldorf Astoria Ithaca**; its guests, workers and histories are fictional. This project is not an official Hilton or Amadeus product.

## Agent workspace

- Review issues in priority order and sort the table by priority, status, location or time elapsed.
- Open a full-screen task view: situation on the left, suggested actions on the right.
- Compare a recommended worker with an alternative, then approve the assignment.
- See the guest's combined issues, history, checkout timing and estimated Stay Score impact.
- Review recovery options when a timely fix offers limited benefit or the stay has ended. Previous offers remain visible; the agent approves each action.
- Monitor workers and their upcoming queues without interrupting committed work.

## Worker portal

Workers see where to go, what needs fixing and the next approved job. The cycle is **Head there → Start job → Done**. Upcoming jobs reorder as priorities change; travel and work already started remain protected. Completion closes the issue, and the agent can reopen it if the guest reports it is unresolved. Both portals update automatically while open.

## Run locally

The application needs **Python 3.10+**, with no additional packages or build step:

```sh
python3 demo/server.py --reload
```

- Agent: http://127.0.0.1:8765/agent.html
- Worker: http://127.0.0.1:8765/worker.html
- Specific worker: http://127.0.0.1:8765/worker.html?worker=sara — also `mike`, `ana`, `leo`.

The root URL opens the agent portal. There is no login in this demo. Both portals can run side by side; a worker selector supports demonstrations. Live data refreshes every 2.5 seconds while visible, and `--reload` restarts Python and refreshes the browser after source changes.

The default scenario includes 13 maintenance and housekeeping reports. SQLite saves changes to `demo/eisen.sqlite3`; restarting preserves the scenario. Use `--db /path/to/new.sqlite3` for a separate scenario.

## Model and integration

`demo/model.py` holds configurable service durations, time-dependent impact curves, useful repair windows, priority bands and recovery options. Work completed after checkout does not improve that guest's experience; routine dispatch gives way to guest follow-up while the maintenance obligation remains open. Safety issues remain actionable.

Guest sensitivities and history are seeded demonstration inputs. The application does not fit its weights from private research data. Individual stay estimates use an illustrative 0–100 display. These demonstration estimates are not validated property-level survey metrics or revenue forecasts.

The HotSOS connection is a planned integration, not a live connector in this MVP. Production onboarding would require connecting tickets, worker availability and guest/stay context, mapping statuses and priorities, and validating recommendations against hotel policy. Human approval remains part of dispatch and guest recovery.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
```

Tests cover the worker cycle, protected commitments, queue ordering, stale decisions, recovery lifecycle, persistence and outcome capture. The runtime uses Python, SQLite and browser JavaScript.

## Demo scope

This is an unauthenticated local demonstration using fictional operational records. Portal roles are checked on requests, but individual employee authentication is not implemented. Alerts appear in an open worker page; background or lock-screen push is not included. GitHub Pages cannot run the Python/SQLite backend. Production hosting requires authentication, HTTPS and durable storage.

Supplied survey data, financial workbooks, event materials, Tableau analysis, and research scripts and outputs are excluded from this source tree. The demo uses fictional operational records and illustrative parameters; no measured revenue uplift is claimed. Keep real guest records, local databases, and private research out of commits.

This portfolio repository contains application code, tests, documentation, and fictional sample records only. Private research materials and their Git history are kept separately.
