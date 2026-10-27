# Eisen MVP technical brief

Status: implementation brief. First local MVP implemented with a Python server, SQLite persistence, and live browser updates. Estimates and recovery policies remain illustrative.

## Purpose

Help hotel agents prevent poor guest experiences by prioritizing housekeeping and maintenance work, recommending how to use available workers, and recommending service recovery when appropriate. Reduce input, repeated information, and steps. Preserve agent responsibility for dispatch and recovery offers.

## Scope

- One demo hotel; housekeeping and maintenance.
- Two direct portals: agent.html and worker.html, sharing persistent state. No login page, PIN, or shared sign-in session. Worker identity is selected by a URL parameter, with a demo worker selector. Both portals work in the same browser.
- Seeded guests, previous stays, property incidents, workers, and recovery outcomes, supplemented by new records created through the demo.
- Configurable initial scoring and decay parameters; later analysis can replace them without changing workflows.
- No live hotel-system integration required for the first version.

## Agent interface

Primary view: a running list of open jobs ordered by importance to the hotel. Ranking must consider severe combined guest experiences as well as preventable harm from further delay.

Each compact row shows location, issue, estimated rating loss, trend, and assignment/status. Keep calculations and detailed guest history behind a details or Why action. Present recommendations when reviewing/dispatching a job; avoid repeating a full explanation on every row.

Intake starts with location and issue description. Retrieve known guest/stay context from the room; suggest department and allow correction. Request extra information only when relevant or missing.

For dispatch, recommend a worker and queue position. Consider department eligibility, availability, current location, existing jobs, expected finish time, issue decay, and checkout timing. Offer an alternative with a short tradeoff. The agent approves either option. Do not assign or reassign without approval.

Example: add a nearby job to Mike's queue after his current repair, versus sending another available worker from a different floor.

Keep queued, on-the-way, and in-progress jobs visible. Remove closed jobs from the active list; preserve accessible history.

## Worker interface

Each worker has their own mobile-friendly page showing only their current job and approved queue. Agent-approved assignments and queue changes appear dynamically without refresh; worker progress updates appear live on the agent page. New assignments produce an in-page alert. Closed-page/lock-screen push notifications are outside the initial MVP scope. Routine queue changes should update visibly without repeatedly alerting the worker for unchanged jobs.

Focus on Current job and Up next. Show location, actionable description, and relevant notes. The MVP assumes workers can access the location and have what they need; omit blocker states, blocker reporting, and blocker alerts. Show only information needed to complete work.

Before heading to a job, the worker must see what kind of work is needed and exactly where to go: department/job type, a short specific issue description, room or named area, and floor. Show known preparation or access details only when relevant (for example, a reported AC symptom or a guest's access restriction). Keep unknown information unknown; do not invent diagnoses, required parts, or equipment. Additional context can expand from the card rather than crowding the primary view.

Compact card: “AC repair · Room 1208, floor 12” / “AC running but not cooling” / relevant note / “Head there”. Once travelling, show “Start”; once work has started, show “Done”. Implementation default: Head there protects that job from further queue changes.

The queue contains agent-approved assignments. The agent can dynamically adjust upcoming work, but should preserve the worker's immediate commitments. Current work is not interrupted to dispatch an urgent new job. Recommend another available worker, a later queue position, or recovery instead.

Worker loop: check the latest approved queue → Head there → Start → Done → return to the latest queue and repeat. No second dispatch approval is needed for already-approved queued jobs. Completion must reveal the current queue, including any agent-approved changes, rather than an old snapshot. If empty, show “No jobs queued”; a new approved assignment appears live with an alert. Do not automatically start work or mark the worker as travelling after completion. Head there is the implementation default for the protected commitment boundary. Queue adjustments must preserve this commitment and be validated against concurrent worker actions.

When the worker marks a job done, close it immediately; do not require an agent confirmation step. If the guest reports the issue is still unresolved, reopen the issue and retain the previous work history. Guest feedback can be recorded by the agent; a guest-facing app is outside the initial two-interface scope.

## Experience estimates

Each issue has a configurable time-dependent rating-loss curve. Different issue types may decline at different speeds and reach different severity levels.

Combine baseline issue behavior, similar incidents at the same property, guest-specific history across stays, and the current stay's issues and interventions. Sparse guest history should rely more heavily on property/category evidence; confidence weighting remains to be specified.

Retain separately:

- Estimated loss so far.
- Expected additional loss from further delay.
- Expected outcomes under each proposed worker/queue alternative.
- Combined stay-level expected final rating and severe-experience risk.

Show estimated rating loss on job rows and a direction/speed indicator. Show a predicted final rating range in stay details, rather than a precise decimal on the main list. Rating points refer to an affected guest's stay rating, not a direct change to the hotel's aggregate rating.

Combine issues with a bounded model; do not simply sum losses indefinitely. Exact curve shapes, aggregation, uncertainty, thresholds, and ranking function remain to be specified. Already severe experiences must not disappear from priority merely because their predicted marginal decline is small.

## Recovery recommendations

Trigger a recommendation when timely resolution is unlikely OR the experience is already severely affected. A fix and a recovery offer can proceed in parallel.

Recommend a relevant option and an alternative, explain briefly, and require agent approval. Candidate examples include coffee, breakfast, and loyalty points; the actual menu, eligibility rules, and limits still need agreement. Do not represent illustrative offers as Hilton policy or guaranteed entitlements.

Combine the guest's issues when assessing recovery need. Consider past offers and outcomes across stays. Display previous offers for the current stay and whether accepted. Eisen may suggest another offer as conditions worsen; prior compensation does not suppress all future recommendations. Avoid repeated identical suggestions without a material change.

Record approval, offering, acceptance/decline, and fulfillment separately. Compensation does not automatically resolve the maintenance issue or erase estimated loss.

## Historical outcomes and later analysis

Retain issue conditions, incident timing, predictions before intervention, model/parameter version, worker and queue alternatives, agent decisions, actual work events, recovery offers, and outcomes.

Where available, associate actual final star rating and review sentiment with the stay. Missing outcomes remain missing; do not manufacture them. Compare predicted and observed outcomes, accounting for repairs and other changes. Observational differences alone do not establish a causal compensation effect.

## Shared data and behavior

Core records: property, location, guest, stay, issue, worker, assignment/queue entry, issue event, prediction snapshot, recovery recommendation/offer, and stay outcome.

Use shared persistent storage and updates across agent and worker sessions. Validate portal actions and valid transitions; prevent conflicting assignments and preserve an event history. Provide visible saving/connection errors. Real work progress comes from worker actions; simulation controls must be explicit and separate from operational behavior.

Issue lifecycle: New → Queued → On the way → In progress → Closed, with cancellation, reassignment of uncommitted work, and reopening supported where appropriate. No blocker flow in the MVP. Worker completion closes the issue in one action and returns the worker to their latest queue. A guest report of non-resolution reopens it without deleting earlier events. No interruption of current work for a new dispatch.

## Open workflow decisions

1. Validate the Head there commitment boundary in use.
2. Replace the illustrative recovery catalog, approval limits, and eligibility with property-approved policy before a real pilot.
3. Calibrate curve families, ranking horizon, severity thresholds, uncertainty, and fallback behavior for sparse data. The initial implementation uses configurable exponential curves and a 30-minute delay horizon.

## MVP acceptance scenario

An agent creates an issue on a laptop and sees a recommendation with an alternative. The agent approves a worker/queue placement. The worker receives it on another device with an alert, heads there, starts, and marks it done. The issue closes and the worker checks their latest queue to repeat the cycle. The agent sees synchronized updates and can reopen the issue on guest feedback. If a timely fix is unlikely or the stay is severely affected, Eisen suggests a recovery offer showing previous offers; the agent approves it and records the response. Refreshing either device preserves all work and history.

## Next specification steps

Review the first local implementation with the agent and worker interfaces side by side. Refine the operational flow and visual density before expanding scope. Internet hosting, individual employee identity, real integrations, and calibrated predictions are later work; the existing public site remains unpublished.

## Demo portal access

This MVP is intentionally unauthenticated. The agent portal and each worker portal provide explicit per-request context, not a browser-wide role cookie. Portal context is not a security boundary. Separate worker views remain operationally scoped, and state-transition rules remain enforced.

## Agent review dashboard

The default page is an operational Issue review dashboard, with open issues, awaiting assignments, recovery decisions, and active-worker counts. Issue rows are numbered in review order. Agent review order is distinct from worker dispatch order: urgent uncommitted issues first, then recovery decisions, severe unassigned stays, other unassigned issues, queued work, and committed work to monitor. Estimated guest impact orders issues within each group. This changes attention order, never worker commitments. Marketing headings and demo controls are removed. The sidebar footer credits Global Solutions for Cornell Hospitality Hackathon 2026.
