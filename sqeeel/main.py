import argparse
import sys

from sqeeel.database_modules.docker_db import DockerExecutor


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
    args = parser.parse_args()

    print(f"Using database image: {args.db_image}")

    # Example usage of the DockerExecutor
    executor = DockerExecutor(
        image_name=args.db_image,
        container_name="sqeeel-test-db",
        client_command=["psql", "-U", "postgres", "-d", "postgres"],
        env={"POSTGRES_PASSWORD": "mysecretpassword"},
    )

    try:
        print("Starting database container...")
        executor.start()
        print("Container started.")

        # Give the database some time to initialize
        import time
        time.sleep(5)

        print("Running a test query...")
        result = executor.run_query("SELECT 1;")
        print(f"Query finished with exit code: {result.exit_code}")
        print(f"Duration: {result.duration:.4f}s")
        if result.exit_code == 0:
            print(f"Output:\n{result.stdout}")
        else:
            print(f"Error:\n{result.stderr}")

    finally:
        print("Stopping database container...")
        executor.stop()
        print("Container stopped.")


if __name__ == "__main__":
    sys.exit(main())