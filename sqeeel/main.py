import argparse
import sys
import json

from sqeeel.database_modules.docker_db import DockerExecutor
from sqeeel.stress_engine.engine import StressEngine
from sqeeel.query_generator import QueryGenerator
from sqeeel.database_modules.postgresql import PostgresModule


def get_db_module(db_type: str):
    if db_type == 'postgres':
        return PostgresModule()
    # Fallback or raise error for unknown db_type
    raise ValueError(f"Unknown database type: {db_type}")


def generate_templates(args):
    """
    Generates query templates from a grammar file and saves them to a JSON file.
    """
    print(f"Generating templates from {args.grammar_file}...")
    
    if args.db_type:
        db_module = get_db_module(args.db_type)
        generator = db_module.create_query_generator(args.grammar_file, args.max_cycle_length)
    else:
        generator = QueryGenerator(args.grammar_file, max_cycle_length=args.max_cycle_length)

    templates = generator.generate_templates(args.start_token)
    
    with open(args.output_file, 'w') as f:
        json.dump([t._asdict() for t in templates], f, indent=2)
        
    print(f"Saved {len(templates)} templates to {args.output_file}")


def run_stress_test(args):
    """
    Runs the stress test against a database.
    """
    print(f"Using database image: {args.db_image}")

    if args.db_type:
         db_module = get_db_module(args.db_type)
         executor = db_module.create_executor(args)
    else:
        # Example usage of the DockerExecutor
        executor = DockerExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db",
            client_command=["psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
            env={"POSTGRES_PASSWORD": "mysecretpassword"},
        )

    try:
        print("Starting database container...")
        executor.start()
        print("Container started.")

        # Give the database some time to initialize
        import time
        time.sleep(5)

        # For now, we'll use a stub query generator
        class StubQueryGenerator:
            def generate_templates(self):
                return [('SELECT ', '1,', '1', '', '')]

        query_generator = StubQueryGenerator()
        stress_engine = StressEngine(executor, query_generator, verbose=args.verbose)
        
        intervals, stats = stress_engine.run()

        print("\n--- Stress Test Results ---")
        for template, template_intervals in intervals.items():
            print(f"\nTemplate: {template}")
            for interval in template_intervals:
                print(f"  {interval['begin']} - {interval['end']}: {interval['effect']}")

    finally:
        print("\nStopping database container...")
        executor.stop()
        print("Container stopped.")


def main():
    """
    Main function for the sqeeel stress-testing application.
    """
    parser = argparse.ArgumentParser(description="A database stress-testing tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sub-parser for the stress-test command
    stress_parser = subparsers.add_parser("stress-test", help="Run the stress test.")
    stress_parser.add_argument(
        "--db-image",
        type=str,
        default="postgres:latest",
        help="The Docker image to use for the database.",
    )
    stress_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    stress_parser.add_argument(
        "--db-type",
        type=str,
        default="postgres",
        help="Database type module to use (e.g. postgres)",
    )
    stress_parser.set_defaults(func=run_stress_test)

    # Sub-parser for the generate-templates command
    gen_parser = subparsers.add_parser("generate-templates", help="Generate query templates from a grammar.")
    gen_parser.add_argument("grammar_file", type=str, help="Path to the grammar file.")
    gen_parser.add_argument("start_token", type=str, help="The start token for template generation.")
    gen_parser.add_argument("output_file", type=str, help="Path to the output JSON file.")
    gen_parser.add_argument(
        "--db-type",
        type=str,
        help="Database type module to use (e.g. postgres) for grammar customization",
    )
    gen_parser.add_argument(
        "--max-cycle-length",
        type=int,
        default=10,
        help="The maximum length of cycles to consider.",
    )
    gen_parser.set_defaults(func=generate_templates)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())