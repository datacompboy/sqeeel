"""
Stress engine.
"""
from ..template_instantiator.instantiator import TemplateInstantiator


class StressEngine:
    """
    Creates templates generator, loops over chosen templates, and for each
    runs a stress loop for some chosen sizes.
    """
    def __init__(self, db_module, query_generator, max_query_size=32*1024*1024, verbose=False):
        self.db_module = db_module
        self.query_generator = query_generator
        self.max_query_size = max_query_size
        self.all_stats = {}
        self.verbose = verbose

    def _get_effect(self, result):
        """
        Determines the effect of a query execution result.
        """
        if result is None:
            return "too-big", ""
        if result.exit_code == 0:
            return "success", ""
        # This is a simplification. A real implementation would have more
        # sophisticated error classification.
        if "timeout" in result.stderr.lower():
            return "timeout", ""
        if result.exit_code < 0:
            return "crash", ""
        return "error", result.stderr[:100]

    def _run_query_for_size(self, instantiator, size):
        """
        Instantiates and runs a query for a given size.
        """
        if size in self.all_stats:
            return self.all_stats[size]
        
        query = instantiator.instantiate(size)
        query_size = len(query)

        if self.verbose:
            print(f"  Running query for size {size} (query size: {query_size} bytes)...")

        if query_size > self.max_query_size:
            if self.verbose:
                print("  Query is too large, skipping execution.")
            self.all_stats[size] = None
            return None

        result = self.db_module.run_query(query)
        self.all_stats[size] = result
        
        if self.verbose:
            effect = self._get_effect(result)
            print(f"  Finished in {result.duration:.4f}s. Effect: {effect}")

        return result

    def _stress_template(self, template):
        """
        Runs the stress loop for a single template.
        """
        instantiator = TemplateInstantiator(template)
        intervals = []

        # 1. Initial discovery phase
        size = 1
        while True:
            result = self._run_query_for_size(instantiator, size)
            effect = self._get_effect(result)
            if len(intervals) > 0 and intervals[-1]["effect"] == effect:
                intervals[-1]["end"] = size
            else:
                intervals.append({"begin": size, "end": size, "effect": effect})
            if result is None:
                break
            size *= 10

        # 2. Close the gaps
        while True:
            merged = False
            new_intervals = []
            if not intervals:
                break
            new_intervals.append(intervals[0])
            for i in range(len(intervals) - 1):
                end1 = new_intervals[-1]["end"]
                effect1 = new_intervals[-1]["effect"]
                begin2, end2, effect2 = intervals[i+1]["begin"], intervals[i+1]["end"], intervals[i+1]["effect"]

                if end1 + 1 < begin2:
                    middle = (end1 + begin2) // 2
                    result = self._run_query_for_size(instantiator, middle)
                    effect = self._get_effect(result)
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


            intervals = new_intervals
            if not merged:
                break
        return intervals


    def run(self):
        """
        Run the stress test.
        """
        print("Starting stress test...")
        templates = self.query_generator.generate_templates()
        results = {}
        for template in templates:
            print(f"Processing template: {template}")
            results[str(template)] = self._stress_template(template)
        print("Stress test finished.")
        return results, self.all_stats