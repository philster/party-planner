# Evals

Three scenarios covering the skill's core flows: adding a new event, catching
a duplicate, and planning a day. Each file names a query and the behavior
that counts as a pass.

There's no automated runner for these yet — run the query against a fresh
session with the skill loaded, then check the transcript against
`expected_behavior` line by line. Add a scenario here whenever a real session
reveals a gap `SKILL.md` doesn't cover; that's a better source of new cases
than guessing ahead of time.
