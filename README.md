# SQeeeL

![SQeeeL](docs/sqeeel.png)

SQeeeL is a project for stress-test database engines against looong SQL queries.

The project creation prompts sequence can be found in `docs/`. Generated using mix of Gemini 2.5 & 3.

Note: despite code being written by the AI, the idea / README / blog / paper / etc are 100% human :)

## Usage

```bash
python3 -m sqeeel.main --help
```

to see the available commands and options.

For the experiments and manual ideas: use `stress-test` subcommand with `--template='...'` argument.

For widespread search:

1. Use `generate-templates` to convert database grammar into templates set
2. Use `stress-test` to run stress against the templates set.

## The Idea

The project was inspired by the ideas from my time at Google Dremel / BigQuery, where I saw first-hand as an oncall engineer
how some queries that looks normal lead that server-side crashes. Debugging and fixing these issues lead me to creation of
5-tuple based regression tests to try out wide range of query scale to find and test the boundary between success and error;
or beteween different errors. You can find the testing code at [ZetaSQL](https://github.com/google/zetasql/) in
[depth_limit_detector_test_cases](https://github.com/google/zetasql/blob/2d8f7b7db9e4ede0557664d256f49804069356e5/zetasql/compliance/depth_limit_detector_test_cases.cc#L330)

Reliability hardening of database at Huawei lead to several similar findings. As part of fixing them, similar regression tests
were also added in, f.e., [openGemini](https://github.com/openGemini/openGemini/blob/6ebe73c187b5d6c7b62dc45c8cb507d055712990/lib/util/lifted/influx/influxql/sqldepth_test.go#L40)

Manual testing confirmed that many other projects shared the same weakness against complex queries: MySQL (and MariaDB),
PostgreSQL, SingleStore, Firebolt, CockroachDB, ScyllaDB, TiDB and others.

To some degree, that looks like a task for the fuzz testing, but full input fuzzing are prone to combinatorial explosion,
and direct attempt to construct large query that will produce useful findings are almost impossible due to the problem.

Hence the idea is to construct scalable patterns, and explore each of the patterns in-depth, not just stopping at the first
error. That approach shrinks exploration domain dramatically to manageable number of patterns; and exploration + gap filling
approach reduces exploration demand per each pattern down. As a result, it is possible to stress multiple layers of processing
inside of the database engine for their quality of problem-prevention and limits settings.

Since processing is a multi-stage process, often without clear layering and the boundary checking are not always done at the
best possible positions, the unbounded approach proven that getting the error for the query does not mean that query can't
harm the server.

The effects caused by these queries are vary:

- Query timeout: when query experience quadratic or cubic behaviour, simple increase of query length lead to enormous execution
  time. Without any other effects, that's mostly harmless and just problem to the user. Although, if database is shared, it may
  still be ground to cause Denial of Service to the other users.
- Query "client-hang": when query gets into a busy loop, closing the connection from client side doesn't lead to query termination.
  If these queries still can be trivially cancelled on the server, this is a way to cause problem to the server management team,
  but nothing more serious.
- Query "server-hang": sometimes the busy loop lack any aliveness checks, which leads to the long-running, CPU-eating (and sometimes
  RAM-eating) queries, with the only way to cancel them is to restart the server. That's typically lengthy and disruptive process
  interrupting other queries and breaking application for an extended time.
- Server OOM: sometimes even good memory tracking code failing in these cases due to hitting a handling path without checks,
  or due slow cancellation time, which allows construct sequence of queries that eat disproportionate amount of RAM and lead to
  server being killed by OOM killer. Typically that is even slower than server restart, since it requires recovery from a failure
  point, plus it triggered by the queries and could be caused many times in a row even before the oncall team reacts.
- Server crash: typically due to stack overflow and access memory beyond the stack.
- Cluster crash: large messages cause large cross-server communication packets, which leads to multiple different
  outcomes, from trivial message limit mismatch configurations that lead to query failures, to breaking the system due to
  permanent change on one of the components that breaks communication with the rest of the system.
- Performance / efficiency: processing worse than O(len^2) in time or memory is a very bad sign.

(I haven't seen yet cases where query lead to any unexpected data leak, nor lead to server-side code execution, which is good.)

The same stress technique is usable to stress various other query inputs, by generating e.g. nested JSON structures, nested proto,
etc as long as you have way to express the pattern construction iteratively with scalable factor.

This project goal is to provide an example on how these stress technique and patterns construction could be used to test multiple
database engines and prove them all faulty :)

## Stressing process

The SQeeeL is designed to construct queries increasing their size until given query size (32mb default) is reached.
The queries constructed is run against a database and query effect is observed: success / error / timeout / hang / crash.

The queries are run at different sizes until we can fully cover the search space, leading to the result like this:

```
Stress results for template ('SELECT * FROM ', '', 'x x$ ', 'NATURAL LEFT JOIN x x$ ', ''):
  1 - 60: ('success', '')
  61 - 13634: ('error', 'Too many tables\n')
  13635 - 52010: ('crash', '')
  52011 - 62057: ('timeout', '')
  62058 - 66542: ('client-hang', '')
  66543 - 603153: ('hang', '')
  603154 - 611329: ('error', "Got a packet bigger than '...' bytes\n")
  611330 - 1195362: ('error', 'Server has gone away\n')
  1195363 - 10000000: ('too-big', '')
Stress test finished.
```

## Templates structure

Templates are 5-tuples, where even parts are repeated equal number of times.

For example: `('SELECT ', '1,', '1', '', '')` can produce:

- SELECT 1
- SELECT 1,1
- SELECT 1,1,1,1,1,1,1,1,1,1,1,1

And `('SELECT ', '(', '1', ')', '')` produces `SELECT 1` and `SELECT ((((1))))`.

Templates support sequential numbering with `$`, so the template
`('SELECT * FROM ', 'x x$,', 'x', '', '')` will produce `SELECT * FROM x x0, x x1, x x2, x`.

(Note: It makes sense to support templates with more than only two repeatable parts, f.e. by scaling all odd elements.
That would allow to construct more complex patterns; additionally, it is good to support for more than single sequence ($).
The task is left as an exercise for the reader.)

## Template construction

Manual template construction is kind of trivial: for any repetitive pattern you can construct two queries, and
differentiate them into fixed prefix/suffix/middle part and repetitive left and right parts.

Obviously, more interesting approach is to have automatic construction of useful/promising patterns.

For the Database engine, the repeated part comes from:

- Lexical structure (strings, numbers, comments, whitespaces etc)
- Grammatical structure (sequence of the tokens that valid according to the grammar)
- Syntactical structure (e.g. "SELECT 1" is valid, but "SELECT x" is not valid without FROM clause)
- Referenced metadata (INSERT INTO .. require number of fields depending on the table; different fields in tables etc).

As the first step, SQeeeL generates templates based on the grammar file, which produces patterns with correct grammatical
structure. The pre-creation of the table and hooks to generate reference to the pre-created table is used to maximize
number of queries that also has correct syntax and references correct metadata.

(Note: Generation of various stress forms for the lexical structure requires separate research, f.e. by collecting supported
operators and functions, identifying the arguments that most likely contain user-supplied input, and stressing these
inputs in a most meaningful way.)

To construct all grammatically-correct queries, we construct connection graph, that replicates relationship between
rules and their descendants. All simple loops (i.e. loops without self-references inside) is found in this graph and each
loop is a source for the repeatable pattern. See [docs/stepA.3.gemini3.txt] with detailed explanation on the algo.

## Findings

Example findings:

### MariaDB

Automatic finds:

- Template: `('with x as (select 1) select 1 from x x', ',x x$', '', '', '')` \
  Query: `with x as (select 1) select 1 from x x, x x0, x x1, x x2, x x3, ...` \
  Effect: hung \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  The longer the list of joins, the long query runs, and one can't interrupt the query, meaning 100% cpu is consumed
  by each thread even after client disconnects. You can't cancel query server-side even with `KILL QUERY`. \
  Fix: [https://jira.mariadb.org/browse/MDEV-37938]
- Template: `('SELECT * FROM ', '', 'x x$ ', 'JOIN x x$ ON x ', '')` \
  Query: `SELECT * FROM x x0 JOIN x x1 on x JOIN x x2 on x JOIN x x3 on x ...` \
  Effect: crash (SIGSEGV) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  For the interval between ~14k and 50k JOINs, the server crashes with SIGSEGV trying to access memory outside of the
  stack due to stack overflow. \
  Fix: [https://jira.mariadb.org/browse/MDEV-38168]

Manually constructed templates:

- Template: `('select ', 'hex(', '\'\\\\\'', ')', '')` \
  Query: `select hex(hex(hex(hex(...'\\'))))` \
  Effect: crash (out of memory) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Each hex() call doubles amount of memory needed for the string, which leads to unbounded memory consumption. \
  Fix: [https://jira.mariadb.org/browse/MDEV-37947]

### PostgreSQL

Automatic finds:

- Template: `('with x as (select 1) select 1 from x x', ',x x$', '', '', '')` \
  Query: `with x as (select 1) select 1 from x x, x x0, x x1, x x2, x x3, ...` \
  Effect: hung \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  The longer the list of joins, the long query runs, and one can't interrupt the query, meaning 100% cpu is consumed
  by each thread even after client disconnects. You can't cancel query server-side even with
  `SELECT pg_cancel_backend(..)`, nor with SIGTERM, and SIGKILL leads to abort of all other queries as well. \
  Report: ...
- Template: `('SELECT FROM x ', ',x x$ ', '', '', '')` \
  Query: `SELECT FROM x, x x0, x x1, x x2, x x3, ...` \
  Effect: crash (out of memory) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  While the query with join of multiple references to subquery "just" consumes unbounded CPU, when the join refers an
  existing table, server consumes unbounded O(n^2) memory, leading to server consuming all the memory available,
  crashing the whole database server process with all other currently running queries. \
  Report: ...

### CockroachDB

Just a few cases with same effect but different crash sources:

- Template: `('SELECT', '(', '1', ')', '')` \
  Query: `SELECT((((1))))` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Crash is at :  `github.com/cockroachdb/cockroach/pkg/sql/sem/tree.(*ParenExpr).Format`
  Report: RS-6152, https://github.com/cockroachdb/cockroach/issues/159599
- Template: `('SELECT LIMIT 0 BETWEEN ', '0 ^ ', '0 ', '', 'AND 0 OFFSET 0')` \
  Query: `SELECT LIMIT 0 BETWEEN 0 ^ 0 ^ 0 ^ ... 0 ^ 0 AND 0 OFFSET 0` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Crash is at : `github.com/cockroachdb/cockroach/pkg/sql/sem/tree.(*BinaryExpr).TypeCheck` \
  Report: ...
- Template: `('SELECT LIMIT ', 'CASE ', '0 ', 'WHEN 0 THEN 0 END ', 'OFFSET 0')` \
  Query: `SELECT LIMIT CASE CASE ... CASE 0 WHEN 0 THEN 0 END ... WHEN 0 THEN 0 END OFFSET 0` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Crash is at : `github.com/cockroachdb/cockroach/pkg/sql/opt/optbuilder.(*Builder).buildScalar` \
  Report: ...
- Template: `('SELECT LIMIT ', 'IFERROR ( ', '0 ', ', 0 ) [ : ] ', 'OFFSET 0')` \
  Query: `SELECT LIMIT IFERROR ( IFERROR ( IFERROR ( 0, 0 ) [ : ] , 0 ) [ : ] , 0 ) [ : ] OFFSET 0` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Crash is at : `github.com/cockroachdb/cockroach/pkg/sql/sem/tree.(*IfErrExpr).Walk` \
  Report: ...

There are queries that "hung" as well; and there are also interesting hangs:

- Template: `("WITH x AS (SELECT TRUE x) ", "SELECT x = ALL(", "TRUE,TRUE", ")", " FROM x")` \
  Query: `WITH x AS (SELECT TRUE x) SELECT x = ALL(SELECT X = ALL(...(TRUE,TRUE))) FROM x` \
  Effect: hang \
  Reason: CWE-405 "CWE-405: Asymmetric Resource Consumption (Amplification)" \
  The query execution time grows with quadratic/cubic time: 500 reps => 4.6s, 1000 => 35.5s, 2000 => 287.3s \
  Report: ...
- Template: `('WITH x AS (SHOW STATEMENTS) SELECT FROM x', ' x$,x', ' LIMIT 1')` \
  Query: `WITH x AS (SHOW STATEMENTS) SELECT FROM x x0,x x1,x x2,...,x LIMIT 1` \
  Effect: hang + oom \
  Reason: CWE-405 "CWE-405: Asymmetric Resource Consumption (Amplification)" \
  The query consumes lot of time in "preparing" state when it can't be cancelled, and at the same time
  consumes lot of memory during both preparing and execute phases, despite returning zero columns and
  limited to only single row. \
  Report: ...

### ScyllaDB

- Template: `('SELECT ', 'f(', 'x', ')', ' FROM x')` \
  Query: `SELECT f(f(f(f(...(x)))))) from x` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  The crashing boundary exceptionally low, just 1515 repetitions. \
  Report: ...
- Template: `('SELECT * FROM x WHERE x = 0 ', 'AND x = 0 ', '', '', '')` \
  Query: `SELECT * FROM x WHERE x = 0 AND x = 0 AND x = 0 ...` \
  Effect: hang \
  Reason: CWE-405 "CWE-405: Asymmetric Resource Consumption (Amplification)" \
  The node that got the query for the execution start consuming 100%+ CPU and does not respond nor allow
  to run new queries. Multiple attempts to run query will get stuck multiple nodes. The time required to
  complete the query and un-stuck grows quadratically (or even cubic). \
  Report: ...

### TiDB

Generated templates lack "FROM" for the case "SELECT * " when next word is next FROM. For simplicity,
I added "FROM x" manually to these cases.

Manual tests:

- Template: `("SELECT ", "+2")` \
  Query: `SELECT +2+2+2+2+2+2...` \
  Effect: crash (stack overflow) \
  Reason: CWE-400 "Uncontrolled Resource Consumption" \
  Simple nested expression that leads to golang stack overflow. \
  Reported over email.
- Template: `("SELECT ", "hex(", "2", ")")` \
  Query: `SELECT hex(hex(hex(...(2))))` \
  Effect: OOM \
  Reason: CWE-405 "Asymmetric Resource Consumption (Amplification)" \
  40 repetitions is enough to consume up to 1Tb of RAM. The query can't be cancelled, so the server is
  doomed once query is sent. \
  Reported over email.
- Template: `("SELECT user.user FROM mysql.user WHERE ", "user='roott' OR ", "user='root'")` \
  Query: `SELECT user.user FROM mysql.user WHERE user='roott' OR user='roott' OR ...` \
  Effect: hang \
  Reason: CWE-400 "Uncontrolled Resource Consumption" + CWE-405 Asymmetric Resource Consumption (Amplification)" \
  The query can't be cancelled, killing client doesn't cancel the query, query eating 200% cpu for each
  query instance, time until finish grows quadratically from the number of filters. The problem can
  be triggered by passing long list of filters to the application. The longer string matching before
  negative check for each OR, the longer query hang. \
  Reported over email.

Automated search also found multiple variations of hung / crash / oom queries.

### SingleStore

- Template: `('SELECT * FROM ', '', 'x x$ ', 'JOIN x x$ ON x ', '')` \
  Query: `SELECT * FROM x x0 JOIN x x1 ON x JOIN x x2 ON x ...` \
  Effect: crash \
  Reason: ? \
  Actually interesting case, as it switch between different effects: \

  ```
  1 - 3068: ('error', "ERROR 1052 (23000) at line 1: Column '...' in on clause is ambiguous\n")
  3069 - 5245: ('error', 'ERROR 1119 (HY000) at line 1: Thread stack overrun:  Used: X of a 1048576 stack.  Specify a bigger stack in the memsql.cnf file by setting the thread-stack engine variable.\n')
  5246 - 5500: ('crash', '')
  5501 - 12465: ('error', 'ERROR 1119 (HY000) at line 1: Thread stack overrun:  Used: X of a 1048576 stack.  Specify a bigger stack in the memsql.cnf file by setting the thread-stack engine variable.\n')
  12466 - 820767: ('crash', '')
  ```

  which suggests improperly placed checks, so the deep process sometimes hit the limit, sometimes triggers SIGSEGV.

### MySQL

Tracking #:    S2329421
Description:   MySQL Server DoS query

Tracking #:    S2329413/CVE-2026-21968:
Description:   MySQL server: CPU-eating DoS query

Tracking #:    S2389842
Description:   CRASH INSIDE OF THE QUERY PARSER/PLANNER/RESOLVER

NOTE: Fill in

### Firebolt

- Template: `("CREATE TABLE x(x int DESCRIPTION '","x","')")`
  Query: `CREATE TABLE x(x int DESCRIPTION 'xxxxxxxxxxxxxx...')`
  Effect: query successful, but no more queries possible against the server \
  Reason: bug in internal retry mechanism \
  Report: https://github.com/firebolt-db/firebolt-core/issues/59 \

  Interesting failure mode, when correct query causes problems for the followup queries.
  While failure pattern is clear, haven't had time to generalize handling this kind of patterns,
  thus this one was confirmed and validated manually. Worth deeper exploration.

