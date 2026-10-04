"""Deterministic virtual Seizo.

This is a software simulator for logic, fault handling, sensor fusion, task flow,
and regression testing. It is NOT a physics engine and it never touches hardware.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import random
from typing import Optional

from seizo_core.sensor_fusion import UltrasonicFilter, IRDebouncer, ActiveViewModel


@dataclass
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other):
        return Vec3(self.x+other.x,self.y+other.y,self.z+other.z)

    def __sub__(self, other):
        return Vec3(self.x-other.x,self.y-other.y,self.z-other.z)

    def scale(self, k):
        return Vec3(self.x*k,self.y*k,self.z*k)

    def norm(self):
        return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)

    def tuple(self):
        return (self.x,self.y,self.z)


@dataclass
class VirtualObject:
    name: str
    pos: Vec3
    held: bool=False
    dropped: bool=False


@dataclass
class Faults:
    axis_skip: Optional[str]=None
    axis_skip_fraction: float=0.0
    camera_occluded: bool=False
    camera_stale: bool=False
    camera_stream_restart: bool=False
    camera_outlier_mm: Optional[float]=None
    camera_bias_mm: Optional[float]=None
    ultrasonic_spike_cm: Optional[float]=None
    ultrasonic_persistent_cm: Optional[float]=None
    ir_bounce: bool=False
    grip_failure: bool=False
    forced_drop: bool=False
    camera_pan_without_relocalize: bool=False


@dataclass
class VirtualArm:
    base_deg: float=0.0
    reach_mm: float=180.0
    z_mm: float=90.0
    gripper_closed: bool=False
    held_object: Optional[str]=None

    BASE_LIMIT=(-100.0,100.0)
    REACH_LIMIT=(60.0,360.0)
    Z_LIMIT=(15.0,260.0)

    def tool(self):
        r=math.radians(self.base_deg)
        return Vec3(self.reach_mm*math.cos(r),self.reach_mm*math.sin(r),self.z_mm)

    def state_tuple(self):
        return (self.base_deg,self.reach_mm,self.z_mm)


@dataclass
class SimEvent:
    kind: str
    detail: dict=field(default_factory=dict)


class VirtualSeizo:
    """A closed virtual loop with explicit expected-vs-observed checks."""
    def __init__(self, seed=1, noise_mm=1.2):
        self.rng=random.Random(seed)
        self.arm=VirtualArm()
        self.noise_mm=float(noise_mm)
        self.objects={}
        self.events=[]
        self.clock=0.0
        self.reference_locked=True
        self.camera_stream_id=1
        self.camera_seq=0
        self.ultra=UltrasonicFilter(caution_cm=25,block_cm=12,release_cm=16,window=5,confirm=3)
        self.ir=IRDebouncer(confirm=3)
        self.view=ActiveViewModel()
        self.abort_reason=None
        self.motion_commands=0
        self.blind_retries=0
        self.last_observation=None
        self.safe_box=(Vec3(-380,-380,15),Vec3(380,380,260))
        self.obstacles=[]

    def log(self, kind, **detail):
        self.events.append(SimEvent(kind,detail))

    def add_object(self,name,pos):
        self.objects[name]=VirtualObject(name,pos)

    def inside_workspace(self, pose):
        lo,hi=self.safe_box
        return lo.x<=pose.x<=hi.x and lo.y<=pose.y<=hi.y and lo.z<=pose.z<=hi.z

    def _advance(self, dt=.05):
        self.clock += dt

    def _ultrasonic_raw(self, faults):
        if faults.ultrasonic_persistent_cm is not None:
            return faults.ultrasonic_persistent_cm
        if faults.ultrasonic_spike_cm is not None:
            value=faults.ultrasonic_spike_cm
            faults.ultrasonic_spike_cm=None
            return value
        # Generic clear reading until the real mounted orientation is measured.
        return 80.0 + self.rng.gauss(0,.6)

    def update_sensors(self, faults):
        self._advance()
        us=self.ultra.add(self._ultrasonic_raw(faults),self.clock)
        physical_closed=self.arm.gripper_closed
        raw_ir=physical_closed
        if faults.ir_bounce:
            raw_ir=self.rng.choice([True,False])
        ir=self.ir.add(raw_ir)
        return us,ir

    def observe_tool(self, faults):
        self._advance()
        if faults.camera_stream_restart:
            self.camera_stream_id += 1
            self.camera_seq=0
            self.reference_locked=False
            faults.camera_stream_restart=False
            self.log("camera_stream_restart")
        if faults.camera_pan_without_relocalize:
            self.view.command(35,"forward")
            self.reference_locked=False
            faults.camera_pan_without_relocalize=False
            self.log("camera_pan",relocalized=False)
        if faults.camera_occluded:
            self.last_observation=None
            self.log("vision_unknown",reason="occluded")
            return None
        if faults.camera_stale:
            self.last_observation=None
            self.log("vision_unknown",reason="stale")
            return None
        if not self.reference_locked or not self.view.snapshot()["world_measurement_usable"]:
            self.last_observation=None
            self.log("vision_unknown",reason="reference_unlocked")
            return None
        self.camera_seq += 1
        actual=self.arm.tool()
        measured=Vec3(actual.x+self.rng.gauss(0,self.noise_mm),
                      actual.y+self.rng.gauss(0,self.noise_mm),
                      actual.z+self.rng.gauss(0,self.noise_mm))
        if faults.camera_bias_mm is not None:
            measured.x += float(faults.camera_bias_mm)
        if faults.camera_outlier_mm is not None:
            measured.x += float(faults.camera_outlier_mm)
            faults.camera_outlier_mm=None
        self.last_observation=measured
        self.log("vision",stream=self.camera_stream_id,seq=self.camera_seq,xyz=measured.tuple())
        return measured

    def observe_tool_confirmed(self, faults, samples=5):
        """Require a burst of fresh observations and use coordinate medians.

        A single visual outlier must not decide motion success/failure. Persistent
        disagreement, occlusion, stale data, stream restart, or lost reference
        still returns unknown/failure.
        """
        count=max(3,int(samples))
        observed=[]
        for _ in range(count):
            value=self.observe_tool(faults)
            if value is None:
                return None
            observed.append(value)
        xs=sorted(v.x for v in observed)
        ys=sorted(v.y for v in observed)
        zs=sorted(v.z for v in observed)
        mid=len(observed)//2
        result=Vec3(xs[mid],ys[mid],zs[mid])
        self.log("vision_confirmed",samples=len(observed),xyz=result.tuple())
        return result

    def relocalize_camera(self):
        self.reference_locked=True
        self.view.confirm_relocalized()
        self.log("camera_relocalized")

    def _check_joint_limits(self,b,r,z):
        return (VirtualArm.BASE_LIMIT[0] <= b <= VirtualArm.BASE_LIMIT[1] and
                VirtualArm.REACH_LIMIT[0] <= r <= VirtualArm.REACH_LIMIT[1] and
                VirtualArm.Z_LIMIT[0] <= z <= VirtualArm.Z_LIMIT[1])

    def command_move(self, db=0.0, dr=0.0, dz=0.0, faults=None, verify=True):
        faults=faults or Faults()
        before_obs=self.observe_tool_confirmed(faults) if verify else None
        if verify and before_obs is None:
            return self.abort("vision_unknown_before_move")
        us,_=self.update_sensors(faults)
        if us["state"] in ("BLOCK","UNKNOWN"):
            return self.abort("ultrasonic_"+us["state"].lower())
        nb=self.arm.base_deg+db
        nr=self.arm.reach_mm+dr
        nz=self.arm.z_mm+dz
        if not self._check_joint_limits(nb,nr,nz):
            return self.abort("joint_limit")
        predicted=VirtualArm(nb,nr,nz,self.arm.gripper_closed,self.arm.held_object).tool()
        if not self.inside_workspace(predicted):
            return self.abort("visual_workspace")
        self.motion_commands += 1
        adb,adr,adz=db,dr,dz
        if faults.axis_skip == "base": adb*=faults.axis_skip_fraction
        if faults.axis_skip == "reach": adr*=faults.axis_skip_fraction
        if faults.axis_skip == "z": adz*=faults.axis_skip_fraction
        self.arm.base_deg += adb
        self.arm.reach_mm += adr
        self.arm.z_mm += adz
        self._advance(.15)
        if self.arm.held_object:
            self.objects[self.arm.held_object].pos=self.arm.tool()
        after=self.observe_tool_confirmed(faults) if verify else None
        if verify:
            if after is None:
                return self.abort("vision_unknown_after_move")
            error=(after-predicted).norm()
            self.log("move_verify",expected=predicted.tuple(),observed=after.tuple(),error_mm=error)
            if error > 6.0:
                return self.abort("motion_mismatch")
        return True

    def move_tool_toward(self,target, faults=None, max_segments=12):
        faults=faults or Faults()
        for _ in range(max_segments):
            cur=self.arm.tool()
            delta=target-cur
            if delta.norm() <= 7.0:
                return True
            # Convert target world position to polar joint target.
            desired_base=math.degrees(math.atan2(target.y,target.x))
            desired_reach=math.hypot(target.x,target.y)
            desired_z=target.z
            db=max(-12,min(12,desired_base-self.arm.base_deg))
            dr=max(-30,min(30,desired_reach-self.arm.reach_mm))
            dz=max(-20,min(20,desired_z-self.arm.z_mm))
            if not self.command_move(db,dr,dz,faults=faults,verify=True):
                return False
        return (self.arm.tool()-target).norm()<=7.0

    def close_gripper(self, object_name=None, faults=None):
        faults=faults or Faults()
        self.arm.gripper_closed=True
        self.log("gripper_command",state="closed")
        for _ in range(3):
            _,ir=self.update_sensors(faults)
        if ir["stable_triggered"] is not True:
            return self.abort("ir_did_not_confirm_closed")
        if object_name is not None:
            obj=self.objects[object_name]
            near=(obj.pos-self.arm.tool()).norm() <= 12.0
            if faults.grip_failure or not near:
                return self.abort("grasp_not_verified")
            obj.held=True
            self.arm.held_object=object_name
            self.log("grasp_verified",object=object_name)
        return True

    def open_gripper(self):
        self.arm.gripper_closed=False
        if self.arm.held_object:
            name=self.arm.held_object
            obj=self.objects[name]
            obj.held=False
            obj.pos=self.arm.tool()
            self.arm.held_object=None
            self.log("released",object=name)
        return True

    def verify_grasp(self, name, faults=None):
        faults=faults or Faults()
        if faults.forced_drop and self.arm.held_object==name:
            self.objects[name].held=False
            self.objects[name].dropped=True
            self.arm.held_object=None
        ok=(self.arm.held_object==name and self.objects[name].held and
            (self.objects[name].pos-self.arm.tool()).norm() <= 3.0)
        self.log("grasp_check",object=name,ok=ok)
        return ok

    def pick_and_place(self,name,destination,faults=None):
        faults=faults or Faults()
        obj=self.objects[name]
        pre=Vec3(obj.pos.x,obj.pos.y,obj.pos.z+35)
        if not self.move_tool_toward(pre,faults): return False
        if not self.move_tool_toward(obj.pos,faults): return False
        if not self.close_gripper(name,faults): return False
        if not self.verify_grasp(name,faults): return self.abort("post_grip_verification_failed")
        lift=Vec3(self.arm.tool().x,self.arm.tool().y,self.arm.tool().z+35)
        if not self.move_tool_toward(lift,faults): return False
        if not self.verify_grasp(name,faults): return self.abort("object_lost_after_lift")
        above=Vec3(destination.x,destination.y,destination.z+35)
        if not self.move_tool_toward(above,faults): return False
        if not self.move_tool_toward(destination,faults): return False
        self.open_gripper()
        err=(self.objects[name].pos-destination).norm()
        self.log("place_verify",object=name,error_mm=err)
        return err <= 8.0

    def abort(self,reason):
        if self.abort_reason is None:
            self.abort_reason=reason
        self.log("abort",reason=reason)
        return False

    def safe_failure(self):
        return self.abort_reason is not None and self.blind_retries==0


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str
    commands: int=0


def _fresh_robot(seed=1):
    s=VirtualSeizo(seed)
    s.add_object("cube",Vec3(210,45,45))
    return s


def deterministic_scenarios():
    out=[]

    s=_fresh_robot(10)
    ok=s.pick_and_place("cube",Vec3(180,-90,45),Faults())
    out.append(ScenarioResult("nominal pick/place",ok and s.abort_reason is None,"completed" if ok else str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(11)
    f=Faults(axis_skip="reach",axis_skip_fraction=.0)
    ok=s.pick_and_place("cube",Vec3(180,-90,45),f)
    out.append(ScenarioResult("reach skip is detected",not ok and s.abort_reason=="motion_mismatch" and s.safe_failure(),str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(12)
    f=Faults(camera_occluded=True)
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("occluded camera prevents movement",not ok and s.motion_commands==0 and s.abort_reason=="vision_unknown_before_move",str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(13)
    f=Faults(camera_stale=True)
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("stale camera prevents movement",not ok and s.motion_commands==0 and s.abort_reason=="vision_unknown_before_move",str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(14)
    f=Faults(ultrasonic_spike_cm=4)
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("single ultrasonic spike is filtered",ok and s.abort_reason is None,"completed" if ok else str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(141)
    f=Faults(camera_outlier_mm=50)
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("single camera outlier is rejected by consensus",ok and s.abort_reason is None,"completed" if ok else str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(142)
    f=Faults(camera_bias_mm=20)
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("persistent camera bias blocks motion verification",not ok and s.abort_reason=="motion_mismatch",str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(15)
    f=Faults(ultrasonic_persistent_cm=8)
    # Seed close evidence until filter confirms block, then attempt a move.
    for _ in range(5): s.update_sensors(f)
    before=s.motion_commands
    ok=s.command_move(dr=10,faults=f)
    out.append(ScenarioResult("persistent close ultrasonic blocks",not ok and s.motion_commands==before and s.abort_reason=="ultrasonic_block",str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(16)
    s.view.command(35,"forward");s.reference_locked=False
    ok=s.command_move(dr=10)
    cond=(not ok and s.motion_commands==0 and s.abort_reason=="vision_unknown_before_move")
    s2=_fresh_robot(17);s2.view.command(35,"forward");s2.reference_locked=False;s2.relocalize_camera()
    ok2=s2.command_move(dr=10)
    out.append(ScenarioResult("pan requires relocalization",cond and ok2,"blocked before relocalize; moved after" if cond and ok2 else "failed",s.motion_commands+s2.motion_commands))

    s=_fresh_robot(18)
    ok=s.command_move(dr=500)
    out.append(ScenarioResult("joint limit blocks impossible reach",not ok and s.abort_reason=="joint_limit","blocked",s.motion_commands))

    s=_fresh_robot(19)
    f=Faults(grip_failure=True)
    ok=s.pick_and_place("cube",Vec3(180,-90,45),f)
    out.append(ScenarioResult("failed grasp prevents relocation",not ok and s.abort_reason=="grasp_not_verified" and s.safe_failure(),str(s.abort_reason),s.motion_commands))

    s=_fresh_robot(20)
    # Pick successfully, then force loss before post-lift verification.
    f=Faults()
    obj=s.objects["cube"]
    pre=Vec3(obj.pos.x,obj.pos.y,obj.pos.z+35)
    ok=s.move_tool_toward(pre,f) and s.move_tool_toward(obj.pos,f) and s.close_gripper("cube",f)
    if ok:
        f.forced_drop=True
        ok2=s.verify_grasp("cube",f)
        if not ok2: s.abort("post_grip_verification_failed")
    out.append(ScenarioResult("object loss is detected",ok and s.abort_reason=="post_grip_verification_failed" and s.safe_failure(),str(s.abort_reason),s.motion_commands))

    return out


def randomized_stress(episodes=1000, seed=20260930):
    rng=random.Random(seed)
    passed=0
    safe_aborts=0
    failures=[]
    for i in range(int(episodes)):
        s=_fresh_robot(rng.randrange(1,10_000_000))
        dest=Vec3(rng.uniform(120,260),rng.uniform(-140,140),45)
        faults=Faults()
        kind=rng.choice(["none","none","none","skip","occlusion","stale","ultra","grip"])
        expected_success = kind=="none"
        if kind=="skip":
            faults.axis_skip=rng.choice(["base","reach","z"]);faults.axis_skip_fraction=rng.choice([0,.25,.5])
        elif kind=="occlusion":
            faults.camera_occluded=True
        elif kind=="stale":
            faults.camera_stale=True
        elif kind=="ultra":
            faults.ultrasonic_persistent_cm=8
            for _ in range(5): s.update_sensors(faults)
        elif kind=="grip":
            faults.grip_failure=True
        ok=s.pick_and_place("cube",dest,faults)
        invariant = s.blind_retries==0
        if expected_success:
            good=ok and s.abort_reason is None and invariant
        else:
            good=(not ok) and s.safe_failure() and invariant
            if good: safe_aborts += 1
        if good:
            passed += 1
        elif len(failures)<10:
            failures.append({"episode":i,"kind":kind,"ok":ok,"abort":s.abort_reason,"commands":s.motion_commands})
    return {"episodes":episodes,"passed":passed,"safe_aborts":safe_aborts,"failures":failures}
