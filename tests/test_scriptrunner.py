# -*- coding: utf-8 -*-
"""Pruebas del ejecutor de build.sh / run.sh (sin pantalla)."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'plugins', 'text'))

import scriptrunner  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-run-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def script(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as handle:
            handle.write(body)
        return path

    def run_script(self, path, timeout=10, stop_after=None):
        out, done = [], {}
        finished = threading.Event()

        def on_done(code, error):
            done['code'], done['error'] = code, error
            finished.set()

        proc = scriptrunner.ScriptProcess(
            path, out.append, on_done, command=scriptrunner.plain_command)
        proc.start()
        if stop_after is not None:
            time.sleep(stop_after)
            proc.stop()
        self.assertTrue(finished.wait(timeout), 'el script no terminó')
        return u''.join(out), done['code'], done['error'], proc


class FindTests(Base):
    def test_only_existing_scripts_are_found(self):
        main = os.path.join(self.tmp, 'prog.pas')
        open(main, 'w').close()
        self.assertEqual(scriptrunner.find_scripts(main), {})
        run = self.script('run.sh', b'echo\n')
        self.assertEqual(scriptrunner.find_scripts(main), {'run': run})
        build = self.script('build.sh', b'echo\n')
        self.assertEqual(scriptrunner.find_scripts(main),
                         {'run': run, 'build': build})

    def test_a_folder_named_run_sh_does_not_count(self):
        os.mkdir(os.path.join(self.tmp, 'run.sh'))
        self.assertEqual(scriptrunner.find_scripts(
            os.path.join(self.tmp, 'x.pas')), {})

    def test_scripts_in_another_folder_do_not_count(self):
        os.mkdir(os.path.join(self.tmp, 'sub'))
        self.script('run.sh', b'echo\n')
        self.assertEqual(scriptrunner.find_scripts(
            os.path.join(self.tmp, 'sub', 'x.pas')), {})


class RunTests(Base):
    def test_output_exit_code_and_cwd(self):
        path = self.script('run.sh', b'pwd\necho hola\necho error >&2\nexit 3\n')
        text, code, error, _p = self.run_script(path)
        self.assertEqual(code, 3)
        self.assertTrue(error is None)
        self.assertIn(os.path.realpath(self.tmp), text.replace('\n', ' '))
        self.assertIn(u'hola', text)
        self.assertIn(u'error', text)             # stderr va en el mismo flujo

    def test_output_arrives_in_order(self):
        path = self.script('run.sh', b'for i in 1 2 3 4 5; do echo l$i; done\n')
        text, code, _e, _p = self.run_script(path)
        self.assertEqual(text.split(), ['l1', 'l2', 'l3', 'l4', 'l5'])
        self.assertEqual(code, 0)

    def test_utf8_is_decoded_even_across_chunks(self):
        body = (u'for i in $(seq 1 3000); do printf "ñandú canción "; done\n'
                ).encode('utf-8')
        text, _c, _e, _p = self.run_script(self.script('run.sh', body))
        self.assertEqual(text.count(u'ñandú canción'), 3000)
        self.assertNotIn(u'�', text)

    def test_invalid_bytes_do_not_break_it(self):
        path = self.script('run.sh', b"printf 'a\\377b\\n'\n")
        text, code, _e, _p = self.run_script(path)
        self.assertEqual(code, 0)
        self.assertIn(u'a', text)

    def test_a_flood_of_output_does_not_hang(self):
        path = self.script('run.sh', b'yes linea | head -n 100000\n')
        text, code, _e, _p = self.run_script(path, timeout=60)
        self.assertEqual(code, 0)
        self.assertEqual(text.count(u'linea'), 100000)

    def test_stdin_is_closed(self):
        path = self.script('run.sh', b'read x\necho "leido=[$x]"\n')
        text, code, _e, _p = self.run_script(path)
        self.assertIn(u'leido=[]', text)          # no se queda esperando

    def test_missing_script_reports_an_error(self):
        out, done = [], {}
        proc = scriptrunner.ScriptProcess(
            os.path.join(self.tmp, 'no-existe', 'run.sh'), out.append,
            lambda c, e: done.update(code=c, error=e),
            command=scriptrunner.plain_command)
        proc.start()
        self.assertTrue(done['code'] is None)
        self.assertTrue(done['error'])

    def test_a_failing_shell_is_a_nonzero_code(self):
        path = self.script('run.sh', b'nonexistent_command_xyz\n')
        _t, code, _e, _p = self.run_script(path)
        self.assertEqual(code, 127)


class StopTests(Base):
    def test_stop_kills_the_script_and_its_children(self):
        marker = os.path.join(self.tmp, 'hijo.pid')
        body = ('sleep 60 &\necho $! > "%s"\nwait\n' % marker).encode('utf-8')
        path = self.script('run.sh', body)
        _t, code, _e, proc = self.run_script(path, stop_after=1.0)
        self.assertTrue(proc.was_stopped)
        self.assertNotEqual(code, 0)
        child = int(open(marker).read().strip())
        time.sleep(0.3)
        self.assertFalse(os.path.exists('/proc/%d' % child),
                         'el proceso hijo sigue vivo')

    def test_stubborn_script_is_killed_with_kill(self):
        scriptrunner._KILL_AFTER, saved = 0.5, scriptrunner._KILL_AFTER
        self.addCleanup(setattr, scriptrunner, '_KILL_AFTER', saved)
        path = self.script('run.sh', b"trap '' TERM\nwhile true; do sleep 1; done\n")
        _t, code, _e, _p = self.run_script(path, stop_after=0.5, timeout=15)
        self.assertEqual(code, -9)

    def test_stop_after_finish_is_harmless(self):
        path = self.script('run.sh', b'echo ok\n')
        _t, code, _e, proc = self.run_script(path)
        proc.stop()
        self.assertEqual(code, 0)
        self.assertFalse(proc.running)


class ExitTests(Base):
    """Al cerrar la actividad no debe quedar ningún script (ni sus hijos)."""

    def _pid_gone(self, pid, wait=5.0):
        end = time.time() + wait
        while time.time() < end:
            if not os.path.exists('/proc/%d' % pid):
                return True
            time.sleep(0.1)
        return False

    def _spawn_and_exit(self, body, exit_code='0'):
        """Un intérprete arranca el script y sale; devuelve el pid que escribió."""
        import subprocess
        marker = os.path.join(self.tmp, 'pid')
        script = self.script('run.sh', body % {'marker': marker})
        code = ('import sys, time\n'
                'sys.path.insert(0, %r)\n'
                'import scriptrunner\n'
                'p = scriptrunner.ScriptProcess(%r, lambda t: None, '
                'lambda c, e: None, command=scriptrunner.plain_command)\n'
                'p.start()\n'
                'time.sleep(1.0)\n'
                'sys.exit(%s)\n' % (os.path.join(ROOT, 'plugins', 'text'),
                                    script, exit_code))
        # el intérprete sale a propósito con ``exit_code`` (también distinto de 0)
        self.assertEqual(subprocess.call([sys.executable, '-c', code]),
                         int(exit_code))
        return int(open(marker).read().strip())

    def test_children_die_when_the_interpreter_exits(self):
        pid = self._spawn_and_exit(
            b'sleep 62 &\necho $! > "%(marker)s"\nwait\n'.replace(
                b'%(marker)s', b'%(marker)s'))
        self.assertTrue(self._pid_gone(pid), 'el hijo sigue vivo tras salir')

    def test_it_also_works_when_the_interpreter_exits_with_an_error(self):
        pid = self._spawn_and_exit(
            b'echo $$ > "%(marker)s"\nsleep 63\n', exit_code='3')
        self.assertTrue(self._pid_gone(pid))

    def test_a_script_ignoring_term_is_killed_at_exit(self):
        pid = self._spawn_and_exit(
            b"trap '' TERM\necho $$ > \"%(marker)s\"\nwhile true; do sleep 1; done\n")
        self.assertTrue(self._pid_gone(pid, wait=8.0))

    def test_stop_all_stops_everything_running(self):
        path = self.script('run.sh', b'sleep 64\n')
        proc = scriptrunner.ScriptProcess(path, lambda t: None,
                                          lambda c, e: None,
                                          command=scriptrunner.plain_command)
        proc.start()
        time.sleep(0.3)
        self.assertTrue(proc.running)
        scriptrunner.stop_all(wait=2.0)
        time.sleep(0.5)
        self.assertFalse(proc.running)

    def test_stop_all_with_nothing_running_is_harmless(self):
        scriptrunner.stop_all(wait=0.1)


class TrimTests(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(scriptrunner.trim_output(u'abc\n', 100), u'abc\n')

    def test_long_text_is_cut_at_a_line_boundary(self):
        text = u''.join(u'linea %04d\n' % i for i in range(1000))
        cut = scriptrunner.trim_output(text, 500)
        self.assertTrue(len(cut) <= 500)
        self.assertTrue(cut.startswith(u'linea '))
        self.assertTrue(cut.endswith(u'linea 0999\n'))

    def test_one_huge_line(self):
        self.assertEqual(len(scriptrunner.trim_output(u'x' * 1000, 100)), 100)


if __name__ == '__main__':
    unittest.main()
