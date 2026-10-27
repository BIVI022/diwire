# Start one daily performance run

You are a NEW visible BB thread for one daily DIWire job. The appended JSON is the job context. Read .bb/automation/prompts/POLICY.md in this worktree first. Read the complete current dispatcher job state. Check no other writer owns this job.

Run the saved BB workflow .bb/workflows/daily-perf.js with args {job: JOB_CONTEXT}. Use the workflows skill. Do not create schedules or continue the old Codex chat. Publish the exact returned workflow preview directive once. Let the background workflow finish; use bb workflows status and bounded history for inspection. A provider or workflow failure is a blocker, not success. Resume an interrupted workflow only in the same worktree and with its persisted run ID.

The workflow finds candidates before it implements them. It validates behavior, Linux measurements, independent reviews and local gates before opening a PR. It returns PR/head/evidence when ready. Record waiting_review using tools/bb_perf_dispatch.py and the appended record_command. Record the actual root BB_THREAD_ID, BB_ENVIRONMENT_ID and workspace. Set the measurement run URL and evidence path. Do not merge during this first stage. The dispatcher starts a new follow-up thread after the review wait or a relevant state change.

If no candidate qualifies, record inconclusive/rejected with the evidence and next action. If infrastructure fails, record blocked with the exact failure and a bounded recovery action. Report a short outcome in this thread. Only this root thread writes the job state.
