## Issue #4 — There is no benchmark suite or workload characterization for quantum network applications: every paper evaluates on QKD plus one bespoke toy

**Labels:** `research` `benchmarks` `infrastructure` `good-first-project`

### Problem

Every scheduler, router, and API in this literature is evaluated on an idiosyncratic workload — typically QKD traffic plus one hand-rolled protocol — making results incomparable and letting weak abstractions hide. There is no SPEC/TPC/YCSB equivalent: no standard application set, no characterization of *demand signatures* (burstiness, fidelity-vs-rate sensitivity, tolerance to staleness of pre-generated pairs, classical-communication coupling), and no shared trace format that simulators consume. This absence is itself blocking Issues #1–#3 and #5, all of which need credible workloads.

### What exists in the literature

- **Application protocols, individually:** QKD (BB84/E91 variants), verified blind quantum computation (demonstrated on the Delft stack, Nature 2025 companion work), CHSH/DIQKD, distributed-gate and teleportation-based DQC circuits, anonymous transmission, clock synchronization, leader election. The Quantum Protocol Zoo wiki catalogs many informally.
- **Simulators, mutually incompatible:** NetSquid, SeQUeNCe, QuISP, SimQN each have their own configuration and application models; the 2026 Wiley review of quantum-network software (Adv. Quantum Technol.) documents the fragmentation explicitly and notes the absence of common workloads.
- **Partial precedents:** SquidASM ships a handful of example programs (the closest thing to a de facto suite, but Delft-stack-specific); the quantum-*computing* world has QASMBench/SupermarQ, proving the model works and that the first credible suite gets adopted; the datacenter-DQC paper (IEEE 2026) extracts Entanglement Demand Schedules from compiled programs — a technique a benchmark suite should generalize.
- **Nothing exists** for cross-simulator workload specs, demand-signature taxonomy, or standardized reporting metrics (delivered fidelity-throughput, contract-violation rate, staleness tolerance curves).

### What could / should be done

1. Select 6–8 applications spanning the classes: key distribution (steady, rate-hungry, fidelity-thresholded), BQC (bursty, latency-coupled, high-fidelity), distributed gates (deadline-critical, staleness-intolerant), sensing/clock sync (correlation-quality-sensitive), anonymous broadcast (multipartite). Implement each against a thin portable API shim with backends for ≥2 simulators (SeQUeNCe + NetSquid or QuISP).
2. Define the demand-signature taxonomy and *measure* it: for each application, publish burstiness profiles, fidelity/rate indifference curves, and staleness-tolerance curves (utility vs age of pre-generated pair — directly feeding Issue #5).
3. Define standard metrics + reporting format; publish machine-readable workload traces so scheduler papers can run without reimplementing applications.
4. Demonstrate discriminative power: run 2–3 published scheduling/routing policies over the suite and show their ranking *inverts* across workload classes — the proof that single-workload evaluation has been producing unreliable conclusions.

**Deliverables**
- [ ] Open-source suite (portable shim + 2 simulator backends)
- [ ] Demand-signature characterization paper
- [ ] Trace + metric spec (versioned, machine-readable)
- [ ] Cross-policy evaluation showing ranking inversions
- [ ] Docs sufficient for third-party adoption (the actual success metric)
