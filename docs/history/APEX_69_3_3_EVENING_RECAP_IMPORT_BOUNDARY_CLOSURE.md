# APEX 69.3.3 — Evening Recap Import Boundary Closure

Adds `engine.evening_recap_service` as a lightweight route boundary so Flask routes no longer import the heavy recap implementation directly. Recap semantics and archive behavior are unchanged.
