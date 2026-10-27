# Sample guest decision audit

Historical audit of the original eight-report, six-guest scenario, evaluated at one frozen instant before automatic stack reordering and the five additional reports were introduced. Amounts below are expressed on the current 100-point Stay Score scale (20 times the original latent units). All weights, settling times, Stay Score effects, and thresholds are illustrative. Comparisons evaluate each stay independently; they are not a global multi-job dispatch schedule. Existing saved demo state continues to age and may differ.

| Guest / room | Checkout in | Repair completion | Useful time after repair / settling | Estimated Stay Score decrease preventable by repairs | First agent action |
|---|---:|---|---|---:|---|
| Alex Morgan / 1208 | 42 min | Heating / AC: 39 min; Room cleaning: 38 min | Heating / AC: 0 min; Room cleaning: 4 min | 0.2 pts | Contact guest; propose 2,000 loyalty points; keep repair open |
| Taylor Reed / 1204 | 240 min | Heating / AC: 13 min | Heating / AC: 217 min | 10.2 pts | Complete / dispatch the repair; monitor |
| Jordan Lee / 0812 | 360 min | Room cleaning: 13 min | Room cleaning: 347 min | 12.6 pts | Complete / dispatch the repair; monitor |
| Casey Rivera / 0816 | 150 min | Towels / linen: 24 min | Towels / linen: 126 min | 5.6 pts | Complete / dispatch the repair; monitor |
| Sam Patel / 1502 | 110 min | Bathroom / water: 35 min | Bathroom / water: 75 min | 3.2 pts | Complete / dispatch the repair; monitor |
| Drew Wilson / 1510 | 300 min | Lights / equipment: 19 min; Towels / linen: 11 min | Lights / equipment: 281 min; Towels / linen: 289 min | 16.4 pts | Complete / dispatch the repair; monitor |

## Calculation

Issue loss = category cap × (1 − exp(− unresolved minutes × guest sensitivity × property factor / category time constant)). Unresolved exposure stops at checkout or completion. AC benefit begins after an illustrative 10-minute cooling period.

Useful time = max(0, checkout − estimated completion − settling time). Recovery is recommended if a meaningful service window is unavailable or the combined stay is severely affected. Initial minimum windows: AC 30 minutes, cleaning/water/lights 20, towels/linen 10. These are configurable assumptions, not learned weights.

Combined issue loss = 4 × (1 − exp(− sum of issue losses / 4)). The latent satisfaction estimate is the guest baseline minus this bounded loss, plus only the illustrative credit for fulfilled gestures. Stay Score and repair benefit use 20 times these latent units. Repair benefit is the difference between expected Stay Score at checkout with the proposed repairs versus no additional repairs. It does not claim to restore harm already suffered.

For Alex, the earlier recommended 39-minute AC fix leaves only three minutes before checkout, and no useful cooling time after settling. Even a 20-minute completion leaves only ten useful minutes under the same assumptions. Guest contact and appropriate recovery must come first; the room still requires repair.

Compensation can accompany a repair. Exact compensation uplift is unvalidated and must not be treated as guaranteed review recovery.
