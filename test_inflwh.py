#!/usr/bin/env python3

import io
import textwrap
import unittest

import inflwh


def parse_env_file(fileobj):
    retdict = {}
    for line in fileobj.readlines():
        if len(line) > 0:
            key, value = line.split('=', 1)
            retdict[key.strip()] = value.strip()
    return retdict


class TestEnvFileParser(unittest.TestCase):
    
    def test_pef_trailing_newline(self):
        teststr = textwrap.dedent("""ASDF=QWER
            FOX=SLY
            """)
        self.assertEqual(
            {'ASDF': 'QWER', 'FOX': 'SLY'},
            inflwh.parse_env_file(io.StringIO(teststr)))
    
    def test_pef_3_trailing_newlines(self):
        teststr = textwrap.dedent("""ASDF=QWER
            FOX=SLY


            """)
        self.assertEqual(
            {'ASDF': 'QWER', 'FOX': 'SLY'},
            inflwh.parse_env_file(io.StringIO(teststr)))

    def test_pef_leading_newlines(self):
        teststr = textwrap.dedent("""
        
            ASDF=QWER
            FOX=SLY
            """)
        self.assertEqual(
            {'ASDF': 'QWER', 'FOX': 'SLY'},
            inflwh.parse_env_file(io.StringIO(teststr)))


if __name__ == '__main__':
    unittest.main()
