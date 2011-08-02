#!/usr/bin/env python
#
#   Copyright (c) 2011 Canonical Ltd.
#
#   This file is part of: SST (selenium-simple-test)
#   https://launchpad.net/selenium-simple-test
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

import ast
import os
import sys

from unittest import TestSuite, TextTestRunner, TestCase

from sst import config
from .actions import start, stop, reset_base_url, set_wait_timeout
from .context import populate_context

__unittest = True

__all__ = ['runtests']



def runtests(
        test_names, test_dir='tests', report_format='console',
        browser_type='Firefox', javascript_disabled=False,
        shared_directory=None, failfast=False
    ):
    if test_dir == 'selftests':
        # XXXX horrible hardcoding
        # selftests should be a command instead
        package_dir = os.path.dirname(__file__)
        test_dir = os.path.join(package_dir, 'selftests')

    test_dir = _get_full_path(test_dir)
    if not os.path.isdir(test_dir):
        msg = 'Specified directory %r does not exist' % (test_dir,)
        print msg
        sys.exit(1)

    shared_directory = find_shared_directory(test_dir, shared_directory)
    config.shared_directory = shared_directory
    sys.path.append(shared_directory)

    found_tests = set()
    test_names = set(test_names)

    suites = (
        get_suite(
            test_names, root, browser_type, javascript_disabled,
            found_tests, failfast
        )
        for root, _, _ in os.walk(test_dir)
        if os.path.abspath(root) != shared_directory and
        not os.path.split(root)[1].startswith('_')
    )

    alltests = TestSuite(suites)

    if not alltests.countTestCases():
        print "Error: Didn't find any tests"
        sys.exit(1)

    if report_format == 'console':
        runner = TextTestRunner(verbosity=2)
        runner.run(alltests)

    if report_format == 'html':
        import HTMLTestRunner
        fp = file('results.html', 'wb')
        runner = HTMLTestRunner.HTMLTestRunner(
            stream=fp, title='SST Test Report', verbosity=2
        )
        runner.run(alltests)

    if report_format == 'xml':
        try:
            import junitxml
        except ImportError:
            print 'Please install junitxml to use XML output'
            sys.exit(1)
        fp = file('results.xml', 'wb')
        result = junitxml.JUnitXmlResult(fp)
        result.startTestRun()
        alltests.run(result)
        result.stopTestRun()

    missing = test_names - found_tests
    for name in missing:
        msg = "Warning: test %r not found" % name
        print >> sys.stderr, msg


def _get_full_path(path):
    return os.path.normpath(
        os.path.abspath(
            os.path.join(os.getcwd(), path)
        )
    )


def find_shared_directory(test_dir, shared_directory):
    """This function is responsible for finding the shared directory.
    It implements the following rule:

    If a shared directory is explicitly specified then that is used.

    The test directory is checked first. If there is a shared directory
    there, then that is used.

    If the current directory is not "above" the test directory then the
    function bails.

    Otherwise it checks every directory from the test directory up to the
    current directory. If it finds one with a "shared" directory then it
    uses that as the shared directory and returns.

    The intention is that if you have 'tests/shared' and 'tests/foo' you
    run `sst-run -d tests/foo` and 'tests/shared' will still be used as
    the shared directory.
    """
    if shared_directory is not None:
        return _get_full_path(shared_directory)

    cwd = os.getcwd()
    default_shared = os.path.join(test_dir, 'shared')
    shared_directory = default_shared
    if not os.path.isdir(default_shared):
        relpath = os.path.relpath(test_dir, cwd)
        if not relpath.startswith('..') and not os.path.isabs(relpath):
            while relpath and relpath != os.curdir:
                this_shared = os.path.join(cwd, relpath, 'shared')
                if os.path.isdir(this_shared):
                    shared_directory = this_shared
                    break
                relpath = os.path.split(relpath)[0]

    return _get_full_path(shared_directory)


def get_suite(
        test_names, test_dir, browser_type, javascript_disabled, found, failfast
    ):
    suite = TestSuite()
    dir_list = os.listdir(test_dir)

    for entry in dir_list:
        if not entry.endswith('.py'):
            continue
        if test_names and entry[:-3] not in test_names:
            continue
        elif not test_names:
            if entry.startswith('_'):
                # ignore entries that start with an underscore unless explcitly specified
                continue
        found.add(entry[:-3])

        csv_path = os.path.join(test_dir, entry.replace('.py', '.csv'))
        if os.path.isfile(csv_path):
            # reading the csv file now
            for row in get_data(csv_path):
                # row is a dictionary of variables
                suite.addTest(
                    get_case(test_dir, entry, browser_type,
                             javascript_disabled, row, failfast=failfast)
                )
        else:
            suite.addTest(
                get_case(test_dir, entry, browser_type,
                         javascript_disabled, failfast=failfast)
            )

    return suite


def get_case(
        test_dir, entry, browser_type, javascript_disabled, context=None,
        failfast=False
    ):
    context_provided = context is not None
    context = context or {}
    path = os.path.join(test_dir, entry)
    def setUp(self):
        sys.path.append(test_dir)
        with open(path) as h:
            source = h.read() + '\n'
            self.code = compile(source, path, 'exec')

        js_disabled = javascript_disabled or 'JAVASCRIPT_DISABLED' in self.code.co_names
        populate_context(context, path, browser_type, js_disabled)
        reset_base_url()
        set_wait_timeout(5, 0.1)
        start(browser_type, js_disabled)
    def tearDown(self):
        sys.path.remove(test_dir)
        stop()
    def test(self):
        if context_provided:
            print 'Loading data row %s' % context['_row_num']
        exec self.code in context
    def run(self, result=None):
        # Had to move some bits from original implementation of TestCase.run to
        # keep the way it works
        if result is None:
            result = self.defaultTestResult()
            startTestRun = getattr(result, 'startTestRun', None)
            if startTestRun is not None:
                startTestRun()
        TestCase.run(self, result)
        if not result.wasSuccessful() and failfast:
            result.shouldStop = True

    name = entry[:-3]
    test_name = 'test_%s' % name
    FunctionalTest = type(
        'Test%s' % name.title(), (TestCase,),
        {'setUp': setUp, 'tearDown': tearDown,
         test_name: test, 'run': run}
    )
    return FunctionalTest(test_name)


def get_data(csv_path):
    """
    Return a list of data dicts for parameterized testing.

      the first row (headers) match data_map key names
      rows beneath that are filled with data values
    """
    rows = []
    print 'Reading data from %s...' % csv_path,
    row_num = 0
    with open(csv_path) as f:
        headers = f.readline().rstrip().split('^')
        headers = [header.replace('"', '') for header in headers]
        headers = [header.replace("'", '') for header in headers]
        for line in f:
            row = {}
            row_num += 1
            row['_row_num'] = row_num
            fields = line.rstrip().split('^')
            for header, field in zip(headers, fields):
                try:
                    value = ast.literal_eval(field)
                except ValueError:
                    value = field
                    if value.lower() == 'false':
                        value = False
                    if value.lower() == 'true':
                        value = True
                row[header] = value
            rows.append(row)
    print 'found %s rows' % len(rows)
    return rows