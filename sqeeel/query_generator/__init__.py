"""
This package will contain the query templates generator.
"""
from .generator import QueryGenerator, parse_template_string, generate_cmd

__all__ = ["QueryGenerator", "parse_template_string", "generate_cmd"]
