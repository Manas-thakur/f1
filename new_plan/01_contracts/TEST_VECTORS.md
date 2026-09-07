# Contract acceptance vectors

- 350000 W displays as 350 kW; 1500000 J displays as 1.50 MJ; 90 m/s displays as 324 km/h.
- Missing energy is null/quality=missing, never a displayed 0% battery.
- An event at source time 12.0 arriving after a published cutoff 12.2 remains archived but cannot alter that decision record.
- A snapshot ending sequence 100 followed by delta 102 causes resynchronisation.
- Two identical selections with the same idempotency key create one operator event.
- A recommendation selected after expiry is rejected even if the browser still shows it.
- WorldState serialisation must never appear in normal session snapshot responses.
- RuleContext with unknown eligibility yields no active-Overtake plan.
- A driver-action request for replay/live_team returns 403.
- Same snapshot, build and seed reproduces the simulation within the declared platform tolerance.

The coordinator must implement these as executable tests before downstream integration. The JSON fixtures are illustrative inputs; they are not evidence of a tested simulator or a real car.
