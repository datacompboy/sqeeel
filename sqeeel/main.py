import argparse
import sys
import json
import logging
import random
import time
from typing import List, Tuple

from sqeeel.stress_engine.engine import StressEngine
from sqeeel.stress_engine.intervals import add_interval
from sqeeel.query_generator import QueryGenerator, parse_template_string, generate_cmd
from sqeeel.database_modules import get_db_module, get_all_db_modules
from sqeeel.template_instantiator.instantiator import TemplateInstantiator


def setup_logging(args):
    """
    Configures logging based on arguments.
    """
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s - %(message)s')

    if args.verbose:
         console_handler.setLevel(logging.INFO)
    else:
         console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(console_formatter)
    handlers.append(console_handler)

    # File handler
    if not args.nolog:
        file_handler = logging.FileHandler(args.log)
        file_formatter = logging.Formatter('%(asctime)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG) # Log everything interesting
        handlers.append(file_handler)

    # Stats file handler
    if not args.nostats:
        stats_handler = logging.FileHandler(args.stats)
        stats_formatter = logging.Formatter('%(asctime)s - %(message)s')
        stats_handler.setFormatter(stats_formatter)
        stats_handler.setLevel(logging.WARNING)
        handlers.append(stats_handler)

    # Determine root logger level based on handlers
    root_level = logging.INFO
    if not args.nolog:
        root_level = logging.DEBUG

    logging.basicConfig(
        level=root_level,
        handlers=handlers
    )


def get_templates(args, db_module) -> List:
    """
    Retrieves templates based on source configuration.
    """
    templates = []
    
    if args.template:
        try:
            tpl = parse_template_string(args.template)
            templates.append(tpl)
        except ValueError as e:
            logging.error(f"{e}")
            sys.exit(1)
    elif args.grammar_file:
        generator = db_module.create_query_generator(args.grammar_file, args.max_cycle_length)
        templates = generator.generate_templates(args.start_token)
    else:
        # Default to json file (either explicit --templates-file or default "templates.json")
        t_file = args.templates_file if args.templates_file else "templates.json"
        try:
            with open(t_file, 'r') as f:
                raw_templates = json.load(f)
                # Convert dicts back to tuples/values
                for t in raw_templates:
                    templates.append((t['prefix'], t['left'], t['middle'], t['right'], t['suffix']))
        except FileNotFoundError:
             logging.error(f"Templates file not found: {t_file}")
             sys.exit(1)
    
    return templates


def filter_templates(templates, args):
    """
    Filters templates based on range and random options.
    """
    total = len(templates)
    if total == 0:
        return []

    selected = templates

    if args.templates_range:
        try:
            if ".." in args.templates_range:
                start, end = map(int, args.templates_range.split(".."))
                # 1-based index to 0-based slice
                selected = templates[start-1:end]
            else:
                idx = int(args.templates_range)
                selected = [templates[idx-1]]
        except (ValueError, IndexError):
             logging.error(f"Invalid range: {args.templates_range}")
             sys.exit(1)

    if args.random:
        count = int(args.random)
        if count < len(selected):
            selected = random.sample(selected, count)
            
    return selected


def generate_templates(args):
    """
    Generates query templates from a grammar file and saves them to a JSON file.
    """
    print(f"Generating templates from {args.grammar_file}...")
    
    if args.db_type:
        db_module = get_db_module(args.db_type)
        generator = db_module.create_query_generator(args.grammar_file, args.max_cycle_length)
    else:
        # Fallback if no db-type specific generator available (or generic), usable only to learn how it works
        generator = QueryGenerator(args.grammar_file, max_cycle_length=args.max_cycle_length)

    templates = generator.generate_templates(args.start_token)
    
    with open(args.output_file, 'w') as f:
        json.dump([t._asdict() for t in templates], f, indent=2)
        
    print(f"Saved {len(templates)} templates to {args.output_file}")


def run_generate_cmd(args):
    """
    Generates a bash one-liner for a query template.
    """
    try:
        tpl = parse_template_string(args.template)
        cmd = generate_cmd(tpl)
        print(cmd)
    except ValueError as e:
        logging.error(f"{e}")
        sys.exit(1)


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


def run_explore_mode(args):
    """
    Runs the explore interactive mode.
    """
    # Explore mode defaults
    args.nostats = True
    setup_logging(args)

    db_module = get_db_module(args.db_type)
    executor = db_module.create_executor(args)

    try:
        logging.info("Starting database container...")
        executor.start()
        executor.wait_for_ready()
        logging.warning("Database container started.")

        # Use StressEngine as helper
        engine = StressEngine(executor, [], max_query_size=args.max_query_size, verbose=args.verbose)

        current_template = None
        if args.template:
             try:
                current_template = parse_template_string(args.template)
             except ValueError as e:
                logging.error(f"Invalid initial template: {e}")

        stats = {}
        intervals = []

        print("Entering explore mode. Type 'help' for commands.")

        while True:
            # Show state
            print(f"\nCurrent Template: {current_template}")
            if intervals:
                print("Known Intervals:")
                for i in sorted(intervals, key=lambda x: x['begin']):
                     print(f"  {i['begin']} - {i['end']}: {i['effect']}")
            
            try:
                line = input("> ").strip()
            except EOFError:
                break
            
            if not line:
                continue
            
            # 1. Check for template setting (Bracket-enclosed)
            new_template = None
            cmd_part = line
            
            start_paren = line.find('(')
            end_paren = line.rfind(')')
            
            if start_paren != -1 and end_paren != -1 and end_paren > start_paren:
                tpl_str = line[start_paren:end_paren+1]
                try:
                    new_template = parse_template_string(tpl_str)
                    # Extract command part (before template)
                    cmd_part = line[:start_paren].strip()
                except ValueError as e:
                    # Not a valid template, ignore
                    logging.error(f"Invalid template: {e}")
            
            if new_template:
                current_template = new_template
                stats = {}
                intervals = []
                # engine.templates = [current_template]
                print(f"Template set to: {current_template}")
            
            if not cmd_part and new_template:
                continue

            tokens = cmd_part.split()
            if not tokens:
                continue
            
            cmd = tokens[0]

            if cmd == "exit" or cmd == "quit":
                break

            elif cmd == "init":
                if not current_template:
                    print("No template set.")
                    continue
                
                instantiator = TemplateInstantiator(current_template)
                size = 1
                while True:
                     res = engine._run_query_for_size(instantiator, size, stats)
                     if res is None: # Too big
                         break
                     
                     effect = engine._get_effect(res)
                     add_interval(intervals, size, effect)
                     
                     size *= 10

            elif cmd == "set":
                if len(tokens) < 3:
                    print("Usage: set <param> <value>")
                    continue
                param = tokens[1]
                value = tokens[2]

                if param == "max-size":
                    try:
                        engine.max_query_size = parse_size(value)
                        print(f"max-query-size set to {engine.max_query_size}")
                    except ValueError:
                        print("Invalid size format. Use 1g, 100m, etc.")
                elif param == "timeout":
                    try:
                        t = parse_time(value)
                        if hasattr(executor, 'timeout'):
                            setattr(executor, 'timeout', t)
                            print(f"timeout set to {t}s")
                        else:
                            print("Executor does not support dynamic timeout update.")
                    except ValueError:
                         print("Invalid time format. Use 5m, 30s, etc.")
                else:
                    print(f"Unknown parameter: {param}")

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

            elif cmd.isdigit():
                if not current_template:
                    print("No template set.")
                    continue
                size = int(cmd)
                instantiator = TemplateInstantiator(current_template)
                res = engine._run_query_for_size(instantiator, size, stats)
                if res:
                    effect = engine._get_effect(res)
                    print(f"Result: {effect}")
                    add_interval(intervals, size, effect)
                else:
                    print("Query too large.")
            
            else:
                print(f"Unknown command: {cmd}")

    except Exception:
        logging.exception("An error occurred during explore mode.")
    finally:
        logging.info("Stopping database container...")
        executor.stop()
        logging.warning("Container stopped.")


def run_stress_test(args):
    """
    Runs the stress test against a database.
    """
    setup_logging(args)
    
    db_module = get_db_module(args.db_type)
    executor = db_module.create_executor(args)

    try:
        logging.info("Starting database container...")
        executor.start()
        executor.wait_for_ready()
        logging.warning("Database container started.")

        templates = get_templates(args, db_module)
        templates = filter_templates(templates, args)
        
        logging.info(f"Running stress test with {len(templates)} templates.")

        stress_engine = StressEngine(executor, templates, max_query_size=args.max_query_size, verbose=args.verbose, quick=args.quick)
        
        results = stress_engine.run()

        logging.warning("--- Stress Test Results ---")
        for template, (template_intervals, template_stats) in results.items():
            logging.warning(f"Template: {template}")
            for interval in template_intervals:
                logging.warning(f"  {interval['begin']} - {interval['end']}: {interval['effect']}")

    except Exception as e:
        logging.exception("An error occurred during stress testing.")
        raise
    finally:
        logging.info("Stopping database container...")
        executor.stop()
        logging.warning("Container stopped.")


def main():
    """
    Main function for the sqeeel stress-testing application.
    """
    # Pre-scan for db-type to know which module to load args from
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--db-type", type=str)
    pre_args, _ = pre_parser.parse_known_args()

    parser = argparse.ArgumentParser(description="A database stress-testing tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sub-parser for the stress-test command
    stress_parser = subparsers.add_parser("stress-test", help="Run the stress test.")
    
    # Core arguments
    stress_parser.add_argument(
        "--db-type",
        type=str,
        required=True,
        choices=get_all_db_modules().keys(),
        help="Database type module to use",
    )
    
    stress_parser.add_argument(
        "--query-timeout",
        type=float,
        default=10.0,
        help="Query execution timeout in seconds (default: 10s).",
    )
    stress_parser.add_argument(
        "--max-query-size",
        type=int,
        default=32 * 1024 * 1024,
        help="Maximum query size in bytes (default: 32MB).",
    )

    # Template selection
    template_group = stress_parser.add_mutually_exclusive_group()
    template_group.add_argument(
        "--templates-file",
        help="Path to JSON templates file."
    )
    template_group.add_argument(
        "--grammar-file",
        help="Path to grammar file for dynamic generation."
    )
    template_group.add_argument(
        "--template",
        help="Single template tuple string (e.g. \"('SELECT ', '1,', '1', '', '')\")."
    )

    stress_parser.add_argument(
        "--start-token",
        default="stmt",
        help="Start token for dynamic generation."
    )
    stress_parser.add_argument(
        "--max-cycle-length",
        type=int,
        default=10,
        help="The maximum length of cycles to consider (dynamic generation).",
    )

    # Filtering
    stress_parser.add_argument(
        "--templates-range",
        help="Range of templates to use (e.g., '1', '1..10')."
    )
    stress_parser.add_argument(
        "--random",
        type=int,
        help="Select N random templates from the source."
    )

    # Logging / Output
    stress_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    stress_parser.add_argument(
        "--log",
        default="run.log",
        help="Log file path."
    )
    stress_parser.add_argument(
        "--nolog",
        action="store_true",
        help="Disable file logging."
    )
    stress_parser.add_argument(
        "--stats",
        default="stats.log",
        help="Stats log file path."
    )
    stress_parser.add_argument(
        "--nostats",
        action="store_true",
        help="Disable stats file logging."
    )
    stress_parser.add_argument(
        "--quick",
        action="store_true",
        help="Enable quick scan mode."
    )

    # Dynamic module args
    if pre_args.db_type:
        try:
            db_module = get_db_module(pre_args.db_type)
            db_module.configure_args(stress_parser)
        except ValueError:
            # Will be caught by main parser check
            pass

    stress_parser.set_defaults(func=run_stress_test)


    # Sub-parser for the explore command
    explore_parser = subparsers.add_parser("explore", help="Run interactive explore mode.")
    explore_parser.add_argument(
        "--db-type",
        type=str,
        required=True,
        choices=get_all_db_modules().keys(),
        help="Database type module to use",
    )
    explore_parser.add_argument(
        "--query-timeout",
        type=float,
        default=10.0,
        help="Query execution timeout in seconds (default: 10s).",
    )
    explore_parser.add_argument(
        "--max-query-size",
        type=int,
        default=32 * 1024 * 1024,
        help="Maximum query size in bytes (default: 32MB).",
    )
    explore_parser.add_argument(
        "--template",
        help="Initial template tuple string."
    )
    explore_parser.add_argument(
        "--log",
        default="explore.log",
        help="Log file path."
    )
    explore_parser.add_argument(
        "--nolog",
        action="store_true",
        help="Disable file logging."
    )
    explore_parser.add_argument(
        "--stats",
        help="Stats log file path (optional, default stats disabled in explore).",
    )
    explore_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )

    if pre_args.db_type:
        try:
            db_module = get_db_module(pre_args.db_type)
            db_module.configure_args(explore_parser)
        except ValueError:
            pass
            
    explore_parser.set_defaults(func=run_explore_mode)


    # Sub-parser for the generate-templates command
    gen_parser = subparsers.add_parser("generate-templates", help="Generate query templates from a grammar.")
    gen_parser.add_argument("grammar_file", type=str, help="Path to the grammar file.")
    gen_parser.add_argument("start_token", type=str, help="The start token for template generation.")
    gen_parser.add_argument("output_file", type=str, help="Path to the output JSON file.")
    gen_parser.add_argument(
        "--db-type",
        type=str,
        choices=get_all_db_modules().keys(),
        help="Database type module to use (e.g. postgres) for grammar customization",
    )
    gen_parser.add_argument(
        "--max-cycle-length",
        type=int,
        default=10,
        help="The maximum length of cycles to consider.",
    )
    gen_parser.set_defaults(func=generate_templates)

    # Sub-parser for the generate-cmd command
    cmd_parser = subparsers.add_parser("generate-cmd", help="Generate bash one-liner for a query template.")
    cmd_parser.add_argument("template", type=str, help="Single template tuple string (e.g. \"('SELECT ', '1,', '1', '', '')\")")
    cmd_parser.set_defaults(func=run_generate_cmd)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
