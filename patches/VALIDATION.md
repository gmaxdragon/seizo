# Simulated-camera production integration

This release is delivered by the existing START_SEIZO.bat desktop manifest.
It does not require a separate folder or real-camera connection.

Run tests with MuJoCo 3.3.7 and NumPy. Linux headless rendering may use MUJOCO_GL=egl.
- python -m unittest discover -s tests -p 'test_*.py' -v
- python tests/camera_http_smoke.py
- python tests/browser_camera_v8.py

Production app.default_runner always selects CameraWorld and CameraAgent. Both training
and frozen evaluation consume the same two simulated RGB streams. Exact state is used
only for simulation, reward/evaluation and the fixed rejection guard. No saved state
policy is imported as a vision policy. Keys and checkpoints are never source assets.

Image-input training integration and frozen tests are not proof of learned manipulation.
The model receives fixed average-pooled camera images and has no pretrained visual
encoder. All physical geometry, masses, camera ranges and collision safety are provisional.
The visual camera feeds use simplified physics geometry rather than the detailed human
viewer. Real Pi input and physical actuator output are absent.
