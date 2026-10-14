# Seizo Desktop Contact Simulation (October 2026)

This is the local computer-only simulator. **No robot control endpoints.**

### Collision corrections
The previous learner had an incomplete collision system: a falling object could
pass through a visible forearm cross-rib, and object-to-object impulses could be
applied even when the bodies were far apart. This version fixes those defects:

- Sixteen moving/fixed capsule proxies cover arm rails, ribs, rear mount, wrist
  housing, palm, and both gripper jaws.
- Contacts resolve penetration and entering velocity relative to moving links.
- Adaptive internal substeps reduce skipped collisions during fast falling.
- Object-object impulses occur only with actual overlap.
- Visual finger aperture matches the physical-proxy aperture.

This is **not** a calibrated real rigid-body physics engine: the arm STL was one
combined assembly and does not encode pivots, mass, inertia, or motor torque.
Object contact shapes are conservative proxies, not exact triangle-mesh surfaces.
Successful virtual training is not safe real-world autonomy.

Old `seizo-five-control-contact-ppo-v2` policies are auto-archived in
`data/legacy_collision_v2_*` so the faulty physics does not contaminate new PPO
results. Do not erase those archives unless you choose to.

### Updating
Use the separate **Seizo Desktop Auto-Updater** `START_SEIZO.bat` to start the
app. It checks the owner-controlled `gmaxdragon/seizo` branch `seizo-desktop` and
installs verified code updates in `%LOCALAPPDATA%\Seizo\Studio` without making
new folders. It never overwrites saved `data/` or `%LOCALAPPDATA%\Seizo\credentials`.

### Safety
This app uses random simulated worlds, not the Pi's cameras or physical axes.
Do not use simulator output as real motor commands. A homebuilt arm without
verified homing/physical limits should remain under manual supervision.