import argparse
import sys

from sqeeel.database_modules.docker_db import DockerExecutor
from sqeeel.stress_engine.engine import StressEngine


# Stub for the query generator
class QueryGenerator:
    def generate_templates(self):
        return [('SELECT ', '1,', '1', '', '')]


def main():
    """
    Main function for the sqeeel stress-testing application.
    """
    parser = argparse.ArgumentParser(description="A database stress-testing tool.")
    parser.add_argument(
        "--db-image",
        type=str,
        default="postgres:latest",
        help="The Docker image to use for the database.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    args = parser.parse_args()

    print(f"Using database image: {args.db_image}")

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

        query_generator = QueryGenerator()
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


if __name__ == "__main__":
    sys.exit(main())