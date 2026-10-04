import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PhoneControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.phone = (ROOT / "scripts/seizo_phone_control.py").read_text()
        cls.camera = (ROOT / "scripts/seizo_camera_site.py").read_text()
        cls.rr = (ROOT / "scripts/seizo_record_replay_v21.py").read_text()
        cls.setup = (ROOT / "scripts/seizo_one_touch_setup.sh").read_text()
        cls.session = (ROOT / "scripts/seizo_session_start.sh").read_text()

    def test_manual_first_surface(self):
        self.assertIn("Guided control. One step at a time.", self.phone)
        self.assertIn("ARM MANUAL", self.phone)
        self.assertIn("STOP / DISARM", self.phone)
        self.assertNotIn("Auto Align X", self.phone)
        self.assertNotIn("Start New Recording", self.phone)
        self.assertNotIn("Replay latest skill", self.phone)
        self.assertNotIn('self.path == "/auto/run"', self.phone)

    def test_five_row_quick_test(self):
        for name in ["Base rotation", "Reach", "Height", "Gripper", "Wrist"]:
            self.assertIn(name, self.phone)
        self.assertIn("TEST 1 OF 5", self.phone)
        self.assertIn("firstUnfinished", self.phone)
        self.assertIn("finishTest", self.phone)
        self.assertIn("COMPONENT_KEYS", self.phone)
        self.assertIn("manual_test_latest.json", self.phone)
        self.assertIn("report_component", self.phone)

    def test_manual_controls_exist(self):
        for key in ["move('w')", "move('s')", "move('a')", "move('d')",
                    "move('q')", "move('e')", "move('n')", "move('m')",
                    "move('o')", "move('p')"]:
            self.assertIn(key, self.phone)

    def test_manual_motion_is_bounded_by_core_profile(self):
        self.assertIn("rr.STEPPER_STEP_MM[axis]", self.phone)
        self.assertIn("feed = self._feed_for_axes([axis])", self.phone)
        self.assertIn('STEPPER_STEP_MM = {"X": 3.00, "Y": 3.00, "Z": 1.50}', self.rr)
        self.assertIn('STEPPER_FEED_MM_MIN = {"X": 90.0, "Y": 90.0, "Z": 60.0}', self.rr)

    def test_arm_uses_fast_bounded_preflight_without_motion(self):
        self.assertIn("def fast_manual_preflight", self.phone)
        self.assertIn("time.sleep(2.2)", self.phone)
        self.assertIn('build = rr.query(ser, "$I", 1.0)', self.phone)
        self.assertIn('startup + "\\n" + build', self.phone)
        self.assertNotIn('ser.write(b"\\x18")', self.phone)
        self.assertIn('rr.startup_blocks(starts)', self.phone)
        self.assertIn('250.000 steps/mm', self.phone)
        self.assertIn('abs(float(value) - 250.0) > 0.01', self.phone)
        self.assertIn('line_expect_ok(ser, "G21 G90"', self.phone)
        self.assertIn("wait_idle(ser, timeout=1.5)", self.phone)
        self.assertNotIn("pre = rr.preflight(ser)", self.phone)

    def test_software_stop_is_immediate_path(self):
        self.assertIn("def stop_now", self.phone)
        stop = self.phone[self.phone.index("def stop_now"):self.phone.index("def flip_axis")]
        self.assertLess(stop.index('ser.write(b"!")'), stop.index("with self.lock:"))

    def test_workspace_is_safety_setup_not_automatic_executor(self):
        self.assertIn("WorkspaceGuard", self.phone)
        self.assertIn("self.workspace.predict", self.phone)
        self.assertIn("self.workspace.commit", self.phone)
        self.assertIn('self.path == "/auto/home"', self.phone)
        self.assertIn('self.path == "/auto/limit"', self.phone)
        self.assertIn('self.path == "/auto/dry-run"', self.phone)
        self.assertNotIn('self.path == "/auto/run"', self.phone)
        self.assertNotIn("vision_move_x", self.phone)
        self.assertNotIn("require_camera_verification", self.phone)
        self.assertNotIn("camera_monitor", self.phone)

    def test_record_replay_lazy_imports_camera(self):
        top = self.rr.split("def main():", 1)[0]
        self.assertNotIn("from seizo_core.camera_monitor import DualCameraMonitor", top)
        self.assertIn("from seizo_core.camera_monitor import DualCameraMonitor", self.rr)

    def test_nano_is_the_only_phone_servo_backend(self):
        self.assertIn('rr.make_servo_controller("nano")', self.phone)
        self.assertIn("command accepted by Nano", self.phone)

    def test_cameras_are_view_only_and_one_tap_away(self):
        self.assertIn("view-only Seizo dual-camera service", self.camera)
        self.assertIn('"automation_enabled": False', self.camera)
        self.assertIn('id="screen-cameras"', self.phone)
        self.assertIn("showScreen('cameras')", self.phone)
        self.assertNotIn("controlled_incremental_move", self.camera)
        self.assertNotIn("vision_tracking", self.camera)

    def test_one_touch_setup_delegates_to_canonical_session_start(self):
        self.assertIn("seizo_session_start.sh", self.setup)
        self.assertNotIn("provision_nano_servo.py", self.setup)
        self.assertNotIn("install_phone_control.sh", self.setup)

    def test_one_tap_nano_probe_is_readonly_and_requires_disarmed(self):
        self.assertIn("def nano_probe_now",self.phone)
        self.assertIn('self.path == "/nano-probe"',self.phone)
        self.assertIn("VERIFY NANO · NO MOTION",self.phone)
        self.assertIn("STOP / DISARM before the read-only Nano check.",self.phone)
        self.assertIn("seizo_nano_readonly_probe.py",self.phone)
        self.assertIn("No servo output command was sent.",self.phone)

    def test_nano_usb_presence_is_not_called_verified_firmware(self):
        self.assertIn('"nano_verified"',self.phone)
        self.assertIn('"nano_probe"',self.phone)
        self.assertIn("Nano VERIFIED",self.phone)
        self.assertIn("Nano USB ONLY",self.phone)

    def test_status_exposes_hardware_without_motion(self):
        self.assertIn('"uno_port"', self.phone)
        self.assertIn('"nano_ports"', self.phone)
        self.assertIn('"camera_overhead"', self.phone)
        self.assertIn('"automation_enabled": False', self.phone)

    def test_fast_preflight_queries_full_grbl_settings(self):
        dollar = chr(36)
        self.assertIn('rr.query(ser, "' + dollar + dollar + '", 1.7)', self.phone)
        self.assertNotIn('rr.query(ser, "' + dollar + '", 1.7)', self.phone)

    def test_advanced_motion_backend_remains_but_is_hidden_from_guided_ui(self):
        self.assertIn("def vector_move", self.phone)
        self.assertIn("controlled_incremental_vector_move", self.phone)
        self.assertIn('coordinated manual move accepted', self.phone.lower())
        self.assertNotIn("3-axis move together", self.phone)
        self.assertNotIn("MOVE TOGETHER", self.phone)
        self.assertNotIn("FAST · 1.5× FEED", self.phone)

    def test_fast_mode_keeps_manual_scope_and_is_not_in_guided_ui(self):
        self.assertIn("def set_speed_mode", self.phone)
        self.assertIn("self.fast_mode", self.phone)
        self.assertIn("135.0", self.phone)
        self.assertIn("110.0", self.phone)
        self.assertNotIn("FAST · 1.5× FEED", self.phone)
        self.assertNotIn("automatic trajectory", self.phone.lower())

    def test_guided_ui_never_shows_more_than_four_context_buttons(self):
        screens=["start","test","summary","controls","xy","height","hand","directions","cameras","automatic",
                 "auto-home","auto-limits","auto-return","auto-preview","teach"]
        for name in screens:
            m=re.search(r'<section id="screen-'+name+r'".*?</section>',self.phone,re.S)
            self.assertIsNotNone(m,name)
            self.assertLessEqual(m.group(0).count("<button"),4,name)
        self.assertIn('class="sticky-stop"',self.phone)

    def test_manual_to_automatic_transition_is_explicit_and_gated(self):
        self.assertIn("AUTOMATIC SETUP",self.phone)
        self.assertIn("Session HOME",self.phone)
        self.assertIn("Safe travel limits",self.phone)
        self.assertIn("PLANNER DRY RUN",self.phone)
        self.assertIn("SET CURRENT POSE AS HOME",self.phone)
        self.assertIn("SAVE SAFE MIN",self.phone)
        self.assertIn("SAVE SAFE MAX",self.phone)
        self.assertIn("zero physical commands",self.phone.lower())
        self.assertNotIn('self.path == "/auto/run"',self.phone)

    def test_automatic_setup_uses_one_dynamic_next_action(self):
        self.assertIn('id="auto-primary"',self.phone)
        self.assertIn("onclick=\"autoNext()\">NEXT",self.phone)
        self.assertIn("ARM_MANUAL:'ARM MANUAL'",self.phone)
        self.assertIn("TEST_HARDWARE:'TEST HARDWARE'",self.phone)
        self.assertIn("CHECK_CAMERAS:'CHECK CAMERAS'",self.phone)
        self.assertIn("SET_HOME:'SET HOME'",self.phone)
        self.assertIn("CALIBRATE_LIMITS:'CALIBRATE LIMITS'",self.phone)
        self.assertIn("PLANNER_READY:'PLANNER DRY RUN'",self.phone)
        self.assertIn("testBack='automatic'",self.phone)
        self.assertIn("openCameras('automatic')",self.phone)

    def test_automatic_wizard_recovers_failed_hardware_rows(self):
        self.assertIn("function hasFailedHardware",self.phone)
        self.assertIn("if(hasFailedHardware(latest))await act('/retest-next-fail')",self.phone)
        self.assertIn("currentTest=firstUnfinished(latest)",self.phone)

    def test_limit_wizard_resumes_without_resetting_partial_calibration(self):
        self.assertIn("function firstIncompleteLimitAxis",self.phone)
        self.assertIn("if(w.calibrating)",self.phone)
        self.assertIn("limitAxis=firstIncompleteLimitAxis(latest)",self.phone)
        block=self.phone[self.phone.index("async function startLimits"):self.phone.index("async function limitMove")]
        self.assertLess(block.index("if(w.calibrating)"),block.index("await act('/auto/cal-start',{reset:'1'})"))

    def test_stop_disarm_invalidates_session_home(self):
        close=self.phone[self.phone.index("def _close_locked"):self.phone.index("def arm(self)")]
        self.assertIn("self.workspace.clear_reference()",close)
        self.assertIn("self.workspace.clear_limits()",close)
        self.assertIn("self.auto_preview = None",close)

    def test_manual_home_limits_do_not_survive_new_reference_or_restart(self):
        init=self.phone[self.phone.index("self.workspace = WorkspaceGuard"):self.phone.index("self.boot_id = current_boot_id()")]
        self.assertIn("self.workspace.clear_limits()",init)
        home=self.phone[self.phone.index("def set_home_reference"):self.phone.index("def clear_home_reference")]
        self.assertIn("self.workspace.clear_limits()",home)
        clear=self.phone[self.phone.index("def clear_home_reference"):self.phone.index("def start_limit_calibration")]
        self.assertIn("self.workspace.clear_limits()",clear)
        self.assertIn("HOME and its travel limits are both forgotten",self.phone)

    def test_hardware_pass_state_is_bound_to_current_pi_boot(self):
        self.assertIn('Path("/proc/sys/kernel/random/boot_id")',self.phone)
        self.assertIn('"boot_id": boot_id or current_boot_id()',self.phone)
        self.assertIn('"profile": MANUAL_TEST_PROFILE',self.phone)
        self.assertIn('loaded_test.get("boot_id") != self.boot_id',self.phone)
        self.assertIn('loaded_test.get("profile") != MANUAL_TEST_PROFILE',self.phone)
        self.assertIn('new_test_state(self.boot_id)',self.phone)

    def test_retest_next_fail_only_unlocks_one_component(self):
        self.assertIn("def retest_next_failed",self.phone)
        self.assertIn('self.path == "/retest-next-fail"',self.phone)
        self.assertIn("Other failed components stay quarantined",self.phone)
        self.assertIn("RETEST NEXT FAIL",self.phone)
        self.assertNotIn("onclick=\"retest()\">RETEST HARDWARE",self.phone)

    def test_failed_components_are_quarantined_before_motion(self):
        self.assertIn("def _require_component_available",self.phone)
        self.assertIn("is quarantined after a physical FAIL",self.phone)
        self.assertIn("self._require_component_available(self._component_for_axis(axis))",self.phone)
        self.assertIn("self._require_component_available(servo_name)",self.phone)
        self.assertIn("marked FAIL and QUARANTINED",self.phone)

    def test_phone_teaching_is_gated_and_record_only(self):
        self.assertIn("TEACH SKILL",self.phone)
        self.assertIn("def start_teaching",self.phone)
        self.assertIn("def save_teaching",self.phone)
        self.assertIn("def cancel_teaching",self.phone)
        self.assertIn('self.path == "/teach/start"',self.phone)
        self.assertIn('self.path == "/teach/save"',self.phone)
        self.assertIn('self.path == "/teach/cancel"',self.phone)
        self.assertNotIn('self.path == "/teach/replay"',self.phone)
        start=self.phone[self.phone.index("def start_teaching"):self.phone.index("def cancel_teaching")]
        self.assertIn("ready_for_planning",start)
        self.assertIn("Finish safety setup before teaching",start)
        self.assertIn("ARM MANUAL before teaching",start)

    def test_taught_actions_are_bounded_skill_actions(self):
        self.assertIn("def _teach_capacity_check",self.phone)
        self.assertIn("Teaching buffer is full at 200 actions",self.phone)
        self.assertIn("validate_skill(candidate)",self.phone)
        self.assertIn('"type": "relative_move"',self.phone)
        self.assertIn('"type": "servo_set"',self.phone)
        self.assertIn("save_skill(LATEST_TAUGHT_SKILL, valid)",self.phone)
        self.assertIn("save_skill(rr.SKILL, valid)",self.phone)
        self.assertIn('"source_mode": "phone-teach"',self.phone)

    def test_stop_discards_unsaved_teaching_session(self):
        close=self.phone[self.phone.index("def _close_locked"):self.phone.index("def arm(self)")]
        self.assertIn("self.teach = new_teach_state()",close)
        self.assertIn("Teaching records only the bounded manual commands",self.phone)
        self.assertIn("It does not enable automatic motion or replay",self.phone)

    def test_vector_api_is_blocked_during_teaching(self):
        vector=self.phone[self.phone.index("def vector_move"):self.phone.index("def nano_probe_now")]
        self.assertIn("if self.teach.get(\"active\")",vector)
        self.assertIn("Coordinated vector moves are disabled while teaching",vector)

    def test_planner_dry_run_is_preview_only(self):
        block=self.phone[self.phone.index("def planner_dry_run"):self.phone.index("def reset_test")]
        self.assertIn("preview_skill",block)
        self.assertNotIn("controlled_incremental_move",block)
        self.assertNotIn("controlled_incremental_vector_move",block)
        self.assertIn("zero physical commands executed",block.lower())

    def test_local_motion_api_requires_same_origin_control_header(self):
        self.assertIn("def origin_ok(self)",self.phone)
        self.assertIn('self.headers.get("X-Seizo-Control") != "guided-v1"',self.phone)
        self.assertIn("'X-Seizo-Control':'guided-v1'",self.phone)
        self.assertIn("Cross-origin control request blocked.",self.phone)
        self.assertIn("Missing Seizo control header.",self.phone)
        self.assertIn("application/x-www-form-urlencoded",self.phone)

    def test_local_web_has_basic_browser_security_headers(self):
        self.assertIn("X-Content-Type-Options",self.phone)
        self.assertIn("Referrer-Policy",self.phone)
        self.assertIn("X-Frame-Options",self.phone)
        self.assertIn("Content-Security-Policy",self.phone)
        self.assertIn("frame-ancestors 'none'",self.phone)

    def test_browser_page_has_fail_visible_health_marker(self):
        self.assertIn('PAGE_MARKER = "SEIZO_MANUAL_WEB_OK"', self.phone)
        self.assertIn('if self.path == "/healthz"', self.phone)
        self.assertIn('data-seizo-page="SEIZO_MANUAL_WEB_OK"', self.phone)
        self.assertIn("WEB ONLINE", self.phone)

    def test_session_start_verifies_exact_page_and_lan_endpoint(self):
        self.assertIn("SEIZO_MANUAL_WEB_OK", self.session)
        self.assertIn("http://127.0.0.1:8790/healthz", self.session)
        self.assertIn('"http://$IP:8790/healthz"', self.session)
        self.assertIn("port 8790 answered but did not serve the expected Seizo page", self.session)


if __name__ == "__main__":
    unittest.main()
