"""
Stress engine.
"""
import logging
from ..template_instantiator.instantiator import TemplateInstantiator


class StressEngine:
    """
    Creates templates generator, loops over chosen templates, and for each
    runs a stress loop for some chosen sizes.
    """
    def __init__(self, db_module, templates, max_query_size=32*1024*1024, verbose=False):
        self.db_module = db_module
        self.templates = templates
        self.max_query_size = max_query_size
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
        
        error_msg = getattr(result, "error_message", None)
        if not error_msg:
            error_msg = result.stderr[:100]
        return "error", error_msg

    def _run_query_for_size(self, instantiator, size, stats):
        """
        Instantiates and runs a query for a given size.
        """
        if size in stats:
            return stats[size]
        
        query = instantiator.instantiate(size)
        query_size = len(query)

        logging.info(f"  Running query for size {size} (query size: {query_size} bytes)...")

        if query_size > self.max_query_size:
            logging.info("  Query is too large, skipping execution.")
            stats[size] = None
            return None

        result = self.db_module.run_query(query)
        stats[size] = result
        
        effect = self._get_effect(result)
        logging.info(f"  Finished in {result.duration:.4f}s. Effect: {effect}")
        logging.debug(f"    Full run stats: {result}")

        return result

    def _stress_template(self, template):
        """
        Runs the stress loop for a single template.
        """
        instantiator = TemplateInstantiator(template)
        intervals = []
        stats = {}

        # 1. Initial discovery phase
        size = 1
        while True:
            result = self._run_query_for_size(instantiator, size, stats)
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
                    result = self._run_query_for_size(instantiator, middle, stats)
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
        return intervals, stats


    def run(self):
        """
        Run the stress test.
        """
        logging.warning("Starting stress test...")
        results = {}
        for template in self.templates:
            logging.warning(f"Processing template: {template}")
            results[str(template)] = self._stress_template(template)
        logging.warning("Stress test finished.")
        return results