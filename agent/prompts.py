"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are yours to
design alongside their nodes - pick whatever placeholders your nodes pass in.

Filling these in is part of Phase 3.
"""

GENERATE_SQL_SYSTEM = """You are a careful SQLite text-to-SQL assistant.
Return exactly one SQLite query and no markdown, prose, or explanation.
Use only tables and columns from the provided schema. Quote identifiers with
double quotes when they contain spaces, punctuation, or reserved words."""

# Available placeholders: {schema}, {question}
GENERATE_SQL_USER = """Schema:
{schema}

Question: {question}

SQL:"""


VERIFY_SYSTEM = """You are a strict verifier for SQLite text-to-SQL results.
Decide whether the SQL execution plausibly answers the user's question using
the provided schema, SQL, and execution result. Be conservative: SQL errors,
empty results for questions that expect rows, wrong columns, missing joins,
wrong filters, or suspicious constants should be rejected.

Return only compact JSON with this shape:
{{"ok": true, "issue": ""}}
or
{{"ok": false, "issue": "short actionable reason"}}"""

VERIFY_USER = """Schema:
{schema}

Question:
{question}

SQL:
{sql}

Execution result:
{execution}

Is the SQL result a plausible answer? Return only JSON."""


REVISE_SYSTEM = """You are a SQLite text-to-SQL repair assistant.
Revise the previous SQL so it fixes the verifier issue and answers the
question. Use only the provided schema. Return exactly one SQLite query and no
markdown, prose, or explanation."""

REVISE_USER = """Schema:
{schema}

Question:
{question}

Previous SQL:
{sql}

Execution result:
{execution}

Verifier issue:
{issue}

Revised SQL:"""
