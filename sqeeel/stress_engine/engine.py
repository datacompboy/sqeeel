"""
Stress engine.
"""
import logging
import signal
import subprocess
from ..template_instantiator.instantiator import TemplateInstantiator
from ..database_modules.base import ExecutionStatus
from ..stress_engine.intervals import add_interval
from ..query_generator import parse_template_string

class ExploreSession:
    def __init__(self, template=None):
        self.template = template
        self.stats = {}
        self.intervals = []

class DelayedKeyboardInterrupt:
    def __init__(self):
        self.signal_received = None
        self.original_popen = None

    def __enter__(self):
        self.signal_received = None
        self.old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self.handler)
        
        # Isolate subprocesses from SIGINT
        self.original_popen = subprocess.Popen
        def new_popen(*args, **kwargs):
            if 'start_new_session' not in kwargs:
                kwargs['start_new_session'] = True
            if self.original_popen:
                return self.original_popen(*args, **kwargs)
            raise RuntimeError("original_popen is None")
        subprocess.Popen = new_popen
        
        return self

    def handler(self, sig, frame):
        if self.signal_received:
            # Second interrupt: Restore old handler and call it immediately
            signal.signal(signal.SIGINT, self.old_handler)
            print("\nForce quitting...")
            if callable(self.old_handler):
                self.old_handler(sig, frame)
            else:
                 raise KeyboardInterrupt
        else:
            self.signal_received = (sig, frame)
            print("\nInterrupt received. Finishing recovery... (Press Ctrl+C again to force quit)")

    def __exit__(self, type, value, traceback):
        subprocess.Popen = self.original_popen
        signal.signal(signal.SIGINT, self.old_handler)
        if self.signal_received and not type:
             if callable(self.old_handler):
                 self.old_handler(*self.signal_received)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import NestedCompleter
    completer = NestedCompleter.from_nested_dict({
        '(': None,
        'debug': None,
        'exit': None,
        'extra-clean': None,
        'extra': None,
        'gap': None,
        'help': None,
        'init': None,
        'q': None,
        'query': None,
        'quiet': None,
        'quit': None,
        'set': {
            'max-size': None,
            'timeout': None,
        },
        'verbose': None,
    })
    prompt = PromptSession(completer=completer).prompt
except ImportError:
    prompt = input

def parse_size(value):
    mult = 1
    value = value.lower()
    if value.endswith('g'):
        mult = 1024**3
        value = value[:-1]
    elif value.endswith('m'):
        mult = 1024**2
        value = value[:-1]
    elif value.endswith('k'):
        mult = 1024
        value = value[:-1]
    return int(float(value) * mult)


def parse_time(value):
    mult = 1
    value = value.lower()
    if value.endswith('m'):
        mult = 60
        value = value[:-1]
    elif value.endswith('s'):
        mult = 1
        value = value[:-1]
    return float(value) * mult


class StressEngine:
    """
    Creates templates generator, loops over chosen templates, and for each
    runs a stress loop for some chosen sizes.
    """
    def __init__(self, db_module, templates, max_query_size=32*1024*1024, verbose=False, quick=False, extra_queries=None):
        self.db_module = db_module
        self.templates = templates
        self.max_query_size = max_query_size
        self.verbose = verbose
        self.quick = quick
        self.extra_queries = extra_queries if extra_queries is not None else []

    def _get_effect(self, result):
        """
        Determines the effect of a query execution result.
        """
        if result is None:
            return "too-big", ""
        
        if result.status == ExecutionStatus.TIMEOUT:
            return "timeout", ""
        if result.status == ExecutionStatus.HANG:
            return "hang", ""
        if result.status == ExecutionStatus.CLIENT_HANG:
            return "client-hang", ""
        if result.status == ExecutionStatus.CRASH:
            return "crash", ""

        if result.exit_code == 0:
            return "success", ""
        # This is a simplification. A real implementation would have more
        # sophisticated error classification.
        if result.exit_code is not None and result.exit_code < 0:
            return "crash", ""
        
        error_msg = getattr(result, "error_message", None)
        if not error_msg:
            error_msg = result.stderr[:100]
        return "error", error_msg

    def _run_extra_queries(self):
        if self.extra_queries:
            logging.info(f"Running {len(self.extra_queries)} extra queries...")
            for q in self.extra_queries:
                self.db_module.run_query(q)

    def _fill_gaps_step(self, instantiator, stats, intervals, bounds=None):
        """
        Performs one pass of gap filling.
        Returns (merged, quick_crashed)
        """
        merged = False
        new_intervals = []
        if not intervals:
            return False, False
        
        new_intervals.append(intervals[0])
        quick_crashed = False
        
        for i in range(len(intervals) - 1):
            end1 = new_intervals[-1]["end"]
            effect1 = new_intervals[-1]["effect"]
            begin2, end2, effect2 = intervals[i+1]["begin"], intervals[i+1]["end"], intervals[i+1]["effect"]
            
            if end1 + 1 < begin2:
                in_bounds = True
                if bounds:
                    # Gap is (end1, begin2) exclusive
                    # Check if gap is within bounds (inclusive)
                    # We want to fill gaps that are strictly inside the requested range
                    if end1 < bounds[0] or begin2 > bounds[1]:
                        in_bounds = False

                if in_bounds:
                    middle = (end1 + begin2) // 2
                    if self.quick:
                        is_hang1 = (effect1[0] == "hang")
                        is_hang2 = (effect2[0] == "hang")
                        if is_hang1 != is_hang2:
                            diff = begin2 - end1
                            step = max(1, diff // 3)
                            if is_hang2:
                                middle = end1 + step
                            else:
                                middle = begin2 - step

                    result = self._run_query_for_size(instantiator, middle, stats)
                    effect = self._get_effect(result)

                    if self.quick and effect[0] == "crash":
                        logging.warning("Crash observed during gap closing. Terminating.")
                        quick_crashed = True
                        new_intervals.append({"begin": middle, "end": middle, "effect": effect})
                        new_intervals.extend(intervals[i+1:])
                        intervals[:] = new_intervals
                        return False, True

                    if effect == effect1:
                        new_intervals[-1]["end"] = middle
                    elif effect == effect2:
                        intervals[i+1]["begin"] = middle
                    else:
                        new_intervals.append({"begin": middle, "end": middle, "effect": effect})
                    merged = True

            if new_intervals[-1]["end"] == intervals[i+1]["begin"] -1 and new_intervals[-1]["effect"] == intervals[i+1]["effect"]:
                new_intervals[-1]["end"] = intervals[i+1]["end"]
            else:
                new_intervals.append(intervals[i+1])

        intervals[:] = new_intervals
        return merged, quick_crashed

    def _recover_database(self):
        """
        Recovers the database by restarting it.
        """
        logging.warning("Attempting database recovery...")
        with DelayedKeyboardInterrupt():
            try:
                self.db_module.recover()
                self._run_extra_queries()
                logging.warning("Database recovered successfully.")
            except Exception:
                logging.exception("Failed to recover database.")
                raise RuntimeError("Database recovery failed.")

    def _run_query_for_size(self, instantiator, size, stats):
        """
        Instantiates and runs a query for a given size.
        """
        # We always run the query, even if it's in stats, to update the result
        
        query = instantiator.instantiate(size)
        query_size = len(query)

        logging.info(f"  Running query for size {size} (query size: {query_size} bytes)...")

        if query_size > self.max_query_size:
            logging.info("  Query is too large, skipping execution.")
            stats[size] = None
            return None

        result = self.db_module.run_query(query)
        
        if result.status in [ExecutionStatus.INTERRUPTED, ExecutionStatus.INTERRUPTED_HANG]:
            if result.status == ExecutionStatus.INTERRUPTED_HANG:
                self._recover_database()
            raise KeyboardInterrupt

        stats[size] = result
        
        if result.status in [ExecutionStatus.HANG, ExecutionStatus.CRASH]:
            self._recover_database()

        effect = self._get_effect(result)
        logging.info(f"  Finished in {result.duration:.4f}s. Effect: {effect}")
        logging.debug(f"    Full run stats: {result}")

        return result

    def _discover_intervals(self, instantiator, stats, intervals):
        """
        Runs the initial discovery phase (powers of 10).
        Returns True if quick crash detected (and should stop).
        """
        size = 1
        quick_crashed = False
        while True:
            result = self._run_query_for_size(instantiator, size, stats)
            effect = self._get_effect(result)
            add_interval(intervals, size, effect)

            if self.quick and effect[0] == "crash":
                logging.warning("Crash observed in quick scan. Terminating discovery.")
                quick_crashed = True
                break
            
            if result is None: # Too big
                break
            
            size *= 10
        return quick_crashed

    def _stress_template(self, template):
        """
        Runs the stress loop for a single template.
        """
        instantiator = TemplateInstantiator(template)
        intervals = []
        stats = {}

        # 1. Initial discovery phase
        quick_crashed = self._discover_intervals(instantiator, stats, intervals)

        # 2. Close the gaps
        while not quick_crashed:
            merged, quick_crashed = self._fill_gaps_step(instantiator, stats, intervals)
            if not merged:
                break
        logging.warning(f"Stress results for template {template}:")
        for interval in intervals:
            logging.warning(f"  {interval['begin']} - {interval['end']}: {interval['effect']}")
        return intervals, stats


    def run(self):
        """
        Run the stress test.
        """
        logging.warning("Starting stress test...")
        self._run_extra_queries()
        results = {}
        for template in self.templates:
            logging.warning(f"Processing template: {template}")
            results[str(template)] = self._stress_template(template)
        logging.warning("Stress test finished.")
        return results
    
    def _try_parse_template(self, line) -> tuple[tuple|None, str]:
        start_paren = line.find('(')
        end_paren = line.rfind(')')
        
        if start_paren != -1 and end_paren != -1 and end_paren > start_paren:
            tpl_str = line[start_paren:end_paren+1]
            try:
                new_template = parse_template_string(tpl_str)
                # Extract command part (before template)
                cmd_part = line[:start_paren].strip()
                return (new_template, cmd_part)
            except ValueError as e:
                # Not a valid template, ignore
                logging.error(f"Invalid template: {e}")
        return (None, line)

    def _handle_explore_command(self, line, session) -> bool:
        tokens = line.split()
        if not tokens:
            return False
        
        cmd = tokens[0]

        # Part 1: handle commands that does not depend on the template,
        # so they can't be combined with the new template

        if cmd == "exit" or cmd == "quit":
            return True

        elif cmd == "help":
            print("Available commands:")
            print("  ('TEMPLATE_STR')       Set current template (e.g. ('SELECT ', '1', ...))")
            print("  init                   Run initial scan (10x increments)")
            print("  set max-size <value>   Set maximum query size (e.g. 1g, 100m)")
            print("  set timeout <value>    Set query timeout (e.g. 5m, 30s)")
            print("  quiet/verbose/debug    Set output verbosity")
            print("  q / query <sql>        Run raw SQL query")
            print("  extra <sql>            Run SQL and add to recovery list")
            print("  extra                  List extra queries")
            print("  extra-clean            Clear extra queries list")
            print("  gap <index>            Explore gap after interval <index>")
            print("  <start>..<end>         Explore range (e.g. 100..200)")
            print("  <integer>              Run query of specific size")
            print("  exit/quit              Exit explore mode")
            return False

        elif cmd == "q" or cmd == "query":
            query = line[len(cmd):].strip()
            if not query:
                print("Usage: q <sql>")
                return False
            logging.info(f"Running raw query: {query}")
            result = self.db_module.run_query(query)
            effect = self._get_effect(result)
            logging.info(f"Finished in {result.duration:.4f}s. Effect: {effect}")
            if result.status in [ExecutionStatus.HANG, ExecutionStatus.CRASH]:
                    self._recover_database()
            return False

        elif cmd == "extra":
            query = line[len(cmd):].strip()
            if not query:
                # List extra queries
                print("Extra queries:")
                for i, q in enumerate(self.extra_queries):
                    print(f"  {i+1}: {q}")
                return False
            
            logging.info(f"Adding and running extra query: {query}")
            self.extra_queries.append(query)
            result = self.db_module.run_query(query)
            effect = self._get_effect(result)
            logging.info(f"Finished in {result.duration:.4f}s. Effect: {effect}")
            if result.status in [ExecutionStatus.HANG, ExecutionStatus.CRASH]:
                    self._recover_database()
            return False

        elif cmd == "extra-clean":
            self.extra_queries = []
            print("Extra queries list cleared.")
            return False

        elif cmd == "set":
            if len(tokens) < 3:
                print("Usage: set <param> <value>")
                return False
            param = tokens[1]
            value = tokens[2]

            if param == "max-size":
                try:
                    self.max_query_size = parse_size(value)
                    print(f"max-query-size set to {self.max_query_size}")
                except ValueError:
                    print("Invalid size format. Use 1g, 100m, etc.")
            elif param == "timeout":
                try:
                    t = parse_time(value)
                    # In main.py: executor = db_module.create_executor(args)
                    # engine = StressEngine(executor, ...)
                    # So self.db_module in Engine IS the executor.
                    target = self.db_module
                    if hasattr(self.db_module, 'executor'):
                            target = self.db_module.executor

                    if hasattr(target, 'timeout'):
                        setattr(target, 'timeout', t)
                        print(f"timeout set to {t}s")
                    else:
                        print("Executor does not support dynamic timeout update.")
                except ValueError:
                        print("Invalid time format. Use 5m, 30s, etc.")
            else:
                print(f"Unknown parameter: {param}")
            return False

        elif cmd in ["quiet", "verbose", "debug"]:
            # Adjust root logger or console handler
            level = logging.WARNING
            if cmd == "verbose": level = logging.INFO
            if cmd == "debug": level = logging.DEBUG
            
            root = logging.getLogger()
            if level < root.getEffectiveLevel():
                root.setLevel(level)
            # Find console handler
            for h in root.handlers:
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                    h.setLevel(level)
            print(f"Output level set to {cmd.upper()}")
            return False

        else:
            # Part 2: handle commands that can be combined with new template setting
            new_template, cmd_part = self._try_parse_template(line)
            if new_template:
                session.template = new_template
                session.stats = {}
                session.intervals = []
                logging.warning(f"Template set to: {session.template}")
            
            if not cmd_part and new_template:
                return False

            tokens = cmd_part.split()
            if not tokens:
                return False
            
            cmd = tokens[0]

            if cmd == "init":
                if not session.template:
                    print("No template set.")
                    return False
                
                instantiator = TemplateInstantiator(session.template)
                self._discover_intervals(instantiator, session.stats, session.intervals)
                return False

            elif cmd == "gap":
                if len(tokens) < 2:
                    print("Usage: gap <index>")
                    return False
                try:
                    idx = int(tokens[1])
                    if idx < 0 or idx >= len(session.intervals) - 1:
                        print("Invalid gap index (must be between intervals)")
                        return False
                    
                    min_b = session.intervals[idx]['end']
                    max_b = session.intervals[idx+1]['begin']
                    
                    print(f"Exploring gap {idx} ({min_b} .. {max_b})...")
                    instantiator = TemplateInstantiator(session.template)
                    while True:
                        merged, _ = self._fill_gaps_step(instantiator, session.stats, session.intervals, bounds=(min_b, max_b))
                        if not merged:
                            break
                except ValueError:
                    print("Invalid index.")
                return False

            elif ".." in cmd:
                # Range exploration
                try:
                    parts = cmd.split("..")
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    
                    if not session.template:
                        print("No template set.")
                        return False

                    instantiator = TemplateInstantiator(session.template)
                    
                    # Ensure boundaries are run
                    if start not in session.stats:
                            res = self._run_query_for_size(instantiator, start, session.stats)
                            effect = self._get_effect(res)
                            add_interval(session.intervals, start, effect)
                    
                    if end not in session.stats:
                            res = self._run_query_for_size(instantiator, end, session.stats)
                            effect = self._get_effect(res)
                            add_interval(session.intervals, end, effect)
                    
                    print(f"Exploring range {start} .. {end}...")
                    while True:
                        merged, _ = self._fill_gaps_step(instantiator, session.stats, session.intervals, bounds=(start, end))
                        if not merged:
                            break

                except ValueError:
                    print("Invalid range format (e.g. 100..200)")
                return False

            elif cmd.isdigit():
                if not session.template:
                    print("No template set.")
                    return False
                size = int(cmd)
                instantiator = TemplateInstantiator(session.template)
                res = self._run_query_for_size(instantiator, size, session.stats)
                if res:
                    effect = self._get_effect(res)
                    print(f"Result: {effect}")
                    add_interval(session.intervals, size, effect)
                else:
                    print("Query too large.")
            
            else:
                print(f"Unknown command: {cmd}")        
            return False
        
        # No explicit return to let linter complain if any of the branches missing return

    def explore(self, initial_template_str=None):
        """
        Runs the explore interactive mode.
        """
        current_template = None
        if initial_template_str:
            try:
                current_template = parse_template_string(initial_template_str)
            except ValueError as e:
                logging.error(f"Invalid initial template: {e}")

        session = ExploreSession(current_template)

        print("Entering explore mode. Type 'help' for commands.")
        self._run_extra_queries()

        while True:
            # Show state
            print(f"\nCurrent Template: {session.template}")
            if session.intervals:
                print("Known Intervals:")
                session.intervals.sort(key=lambda x: x['begin'])
                for i, interval in enumerate(session.intervals):
                    print(f"(  )  {interval['begin']} - {interval['end']}: {interval['effect']}")
                    if i < len(session.intervals) - 1 and interval['end'] + 1 < session.intervals[i+1]['begin']:
                        print(f"({i:2})  {interval['end']} - {session.intervals[i+1]['begin']}: [gap]")
            
            try:
                line = prompt("> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                continue
            
            if not line:
                continue
            
            try:
                stop = self._handle_explore_command(line, session)
                if stop:
                    break
            except KeyboardInterrupt:
                print("\nInterrupted.")
                continue
            except Exception as e:
                logging.error(f"Error executing command: {e}")
                continue