# GLOSSARY.md — Sushi Shop

> Canonical definitions for terms used across this project.
> Updated at commit time when a new concept or term is introduced.
> If a term appears in code, docs, or conversation — it is defined here.

---

## D

**DLQ (Dead Letter Queue)**
A holding queue for Celery tasks that have failed after all retry attempts. Instead of silently dropping a failed kitchen task, the worker routes it to the DLQ. The DLQ handler sets the order status to `FAILED` in Postgres and logs the failure reason. This makes failures inspectable and recoverable rather than invisible. Introduced in Commit 10.

---
