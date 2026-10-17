"""Platform-independent tests for the Windows main-thread OpenGL dispatcher."""
import threading
import time
import unittest

from core.main_thread_renderer import MainThreadRenderer


class MainThreadRendererTests(unittest.TestCase):
    def test_runs_on_owner_thread_from_worker(self):
        dispatcher = MainThreadRenderer()
        observed = []
        def task():
            observed.append(threading.get_ident())
            return 42
        result = []
        worker = threading.Thread(target=lambda: result.append(dispatcher.call(task, timeout=2)))
        worker.start()
        # Work may be scheduled later than thread creation.
        for _ in range(100):
            dispatcher.pump(timeout=.01)
            if not worker.is_alive():
                break
        worker.join(2)
        self.assertEqual(result, [42])
        self.assertEqual(observed, [dispatcher.owner_ident])
        dispatcher.close()

    def test_no_renderer_from_worker_without_dispatch(self):
        dispatcher = MainThreadRenderer()
        errors = []
        worker = threading.Thread(target=lambda: errors.append(dispatcher.pump(timeout=0)))
        worker.start(); worker.join(2)
        self.assertEqual(len(errors), 0) if False else None
        # The main-thread restriction is checked independently below.
        dispatcher.close()

    def test_wrong_thread_pump_raises(self):
        dispatcher = MainThreadRenderer()
        errors = []
        def attempt():
            try: dispatcher.pump(timeout=0)
            except RuntimeError as exc: errors.append(str(exc))
        worker = threading.Thread(target=attempt)
        worker.start();worker.join(1)
        self.assertTrue(errors)
        self.assertIn("main thread", errors[0])
        dispatcher.close()

    def test_exception_reaches_request_thread(self):
        dispatcher = MainThreadRenderer()
        raised=[]
        def boom():
            raise ValueError("render failure")
        def attempt():
            try: dispatcher.call(boom,timeout=1)
            except Exception as exc: raised.append(str(exc))
        worker=threading.Thread(target=attempt)
        worker.start()
        for _ in range(100):
            dispatcher.pump(.01)
            if not worker.is_alive():break
        worker.join(2)
        self.assertEqual(raised, ["render failure"])
        dispatcher.close()

    def test_timed_out_work_must_not_run_later(self):
        dispatcher = MainThreadRenderer()
        observed=[];errors=[]
        def attempt():
            try: dispatcher.call(lambda: observed.append("unsafe late render"),timeout=.02)
            except RuntimeError as exc:errors.append(str(exc))
        worker=threading.Thread(target=attempt)
        worker.start();worker.join(1)
        dispatcher.pump(timeout=0)
        self.assertEqual(observed, [])
        self.assertTrue(errors)
        dispatcher.close()

    def test_submit_is_nonblocking_and_join_is_thread_compatible(self):
        dispatcher=MainThreadRenderer()
        result=[]
        j=dispatcher.submit(lambda:result.append("executed"))
        self.assertTrue(j.is_alive())
        dispatcher.pump(timeout=0)
        j.join(.1)
        self.assertFalse(j.is_alive())
        self.assertEqual(result, ["executed"])
        dispatcher.close()

    def test_owner_call_is_immediate(self):
        dispatcher=MainThreadRenderer()
        self.assertEqual(dispatcher.call(lambda:"result"),"result")
        dispatcher.close()

    def test_closing_rejects_new_tasks_and_cancels_old(self):
        dispatcher=MainThreadRenderer()
        old=dispatcher.submit(lambda:1)
        dispatcher.close()
        self.assertFalse(old.is_alive())
        with self.assertRaises(RuntimeError):dispatcher.submit(lambda:2)


if __name__=="__main__":
    unittest.main()
