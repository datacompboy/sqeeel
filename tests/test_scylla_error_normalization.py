import unittest
import argparse
from sqeeel.database_modules.scylladb import ScyllaDBModule

class TestScyllaErrorNormalization(unittest.TestCase):
    def setUp(self):
        self.module = ScyllaDBModule()

    def test_normalize_scylla_error(self):
        raw_stderr = (
            "Some unrelated line\n"
            "'cassandra.cluster.NoHostAvailable: (\\'Unable to complete the operation against any hosts\\', {<Host: 172.20.0.2:9042 datacenter1>: <Error from server: code=0000 [Server error] message=\"request processing failed, error [std::runtime_error (Value too large, 8031329 > 65535)]\">})'"
        )
        expected = (
            "'cassandra.cluster.NoHostAvailable: (\\'Unable to complete the operation against any hosts\\', {<Host: XXX>: <Error from server: code=0000 [Server error] message=\"request processing failed, error [std::runtime_error (Value too large)]\">})'"
        )
        
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_scylla_frame_size_error(self):
        raw_stderr = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"request size too large (frame size 33554443; estimate 67116886; allowed 48444211)\"'"
        )
        expected = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"request size too large (frame size XXX; estimate XXX; allowed XXX)\"'"
        )
        
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_scylla_token_arguments_error(self):
        raw_stderr = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"Invalid number of arguments in call to function system.token: 1 required but 47266 provided\"'"
        )
        expected = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"Invalid number of arguments in call to function system.token: XXX required but XXX provided\"'"
        )
        
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_scylla_tuple_elements_error(self):
        raw_stderr = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"Expected 1 elements in value tuple, but got 8: (0, 0, 0, 0, 0, 0, 0, 0)\"'"
        )
        expected = (
            "'cassandra.InvalidRequest: Error from server: code=2200 [Invalid query] message=\"Expected 1 elements in value tuple, but got X: (...)\"'"
        )
        
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_scylla_syntax_error(self):
        raw_stderr = (
            "'cassandra.protocol.SyntaxException: <Error from server: code=2000 [Syntax error in CQL query] message=\"line 1:531 : Missing \\'>\\'\">'"
        )
        expected = (
            "'cassandra.protocol.SyntaxException: <Error from server: code=2000 [Syntax error in CQL query] message=\"line X:X : Missing \\'>\\'\">'"
        )
        
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

if __name__ == '__main__':
    unittest.main()
