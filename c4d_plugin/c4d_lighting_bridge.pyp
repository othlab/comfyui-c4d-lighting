"""
c4d_lighting_bridge.pyp
ComfyUI -> C4D automatic lighting bridge.

Watches a lights.json file and automatically builds a Redshift
dome light (HDRI) + area lights + a basic set in the active scene
whenever the file is updated.

Installation:
1. Edit WATCH_FILE below to point to your ComfyUI output folder
2. Copy this file into your C4D plugins folder
   (C4D menu: Edit > Preferences > click "Open Preferences Folder"
    at the bottom left -> open the "plugins" folder inside)
3. Restart C4D. You should see "[Lighting Bridge] Watching:" in the console.
"""
import c4d
import os
import json
import math
from c4d import plugins

# ========== SETTINGS ==========
# The plugin watches a fixed rendezvous folder that the ComfyUI node
# writes to automatically -- no configuration needed:
#   <your user folder>/Documents/C4D_Lighting_Bridge/lights.json
# To use a different location, set CUSTOM_WATCH_FILE below.
CUSTOM_WATCH_FILE = ""     # e.g. r"D:\my\custom\path\lights.json"
AUTO_CLEAR = True          # delete the previous result group before rebuilding
BUILD_SET = True           # create the hero object (sphere)
CREATE_AREA_LIGHTS = False  # False = dome (HDRI) only; light data stays in lights.json
# ==============================

WATCH_FILE = CUSTOM_WATCH_FILE or os.path.join(
    os.path.expanduser("~"), "Documents",
    "C4D_Lighting_Bridge", "lights.json")

PLUGIN_ID = 1064977  # temporary ID for personal use
                     # (get an official ID from Plugin Cafe before public release)
GROUP_NAME = "Lighting_From_Reference"

RS_LIGHT_ID = 1036751
BASE_INTENSITY = 100.0

# Subject-aware scaling: light size/distance are RATIOS of the subject size.
# The bridge looks for an object named SUBJECT_NAME in the scene and measures
# it; if not found, it creates a preview sphere of SUBJECT_FALLBACK_SIZE.
# (A light larger than the subject = soft shadows; smaller = hard shadows.)
SUBJECT_NAME = "Hero_Object"
SUBJECT_FALLBACK_SIZE = 100.0   # cm, used when no subject exists yet

ROLE_SETTINGS = {
    # role: (intensity multiplier, size_factor, distance_factor)
    "key":  (1.0, 1.5, 2.0),
    "rim":  (1.2, 0.6, 2.5),
    "back": (1.2, 0.6, 2.5),
    "fill": (0.8, 2.0, 3.0),
    "sub":  (1.0, 1.0, 2.5),
}


def measure_subject(doc):
    """Return (size_cm, existed). Measures the bounding size of the
    subject object if present; otherwise returns the fallback size."""
    obj = doc.SearchObject(SUBJECT_NAME)
    if obj is not None:
        r = obj.GetRad()  # bounding-box half sizes
        size = 2.0 * max(r.x, r.y, r.z)
        if size > 1e-3:
            return size, True
    return SUBJECT_FALLBACK_SIZE, False


def rs_set(obj, sym, value, file_path=False):
    """Safely set a Redshift parameter: skip with a warning if the
    symbol does not exist in this RS version."""
    if not hasattr(c4d, sym):
        print(f"[Lighting Bridge] Warning: c4d.{sym} not found (skipped)")
        return False
    try:
        if file_path:
            obj[getattr(c4d, sym), c4d.REDSHIFT_FILE_PATH] = value
        else:
            obj[getattr(c4d, sym)] = value
        return True
    except Exception as e:
        print(f"[Lighting Bridge] Warning: failed to set {sym}: {e}")
        return False


def look_at_target(pos, target=None):
    """Matrix at pos with +Z pointing at the target (default: origin)."""
    if target is None:
        target = c4d.Vector(0)
    z = (target - pos).GetNormalized()
    up = c4d.Vector(0, 1, 0)
    if abs(z.Dot(up)) > 0.99:
        up = c4d.Vector(0, 0, 1)
    x = up.Cross(z).GetNormalized()
    y = z.Cross(x)
    return c4d.Matrix(pos, x, y, z)


def create_dome(doc, hdri_path):
    dome = c4d.BaseObject(RS_LIGHT_ID)
    dome.SetName("RS_Dome_HDRI")
    rs_set(dome, "REDSHIFT_LIGHT_TYPE", c4d.REDSHIFT_LIGHT_TYPE_DOME)
    rs_set(dome, "REDSHIFT_LIGHT_DOME_TEX0", hdri_path, file_path=True)
    doc.InsertObject(dome)
    return dome


def create_area_light(doc, light_data, subject_size):
    role = light_data.get("role", "sub")
    base_role = role.rstrip("0123456789")
    mult, size_f, dist_f = ROLE_SETTINGS.get(base_role, (1.0, 1.0, 2.5))
    size = subject_size * size_f
    distance = subject_size * dist_f
    d = light_data["direction"]
    pos = c4d.Vector(d[0], d[1], d[2]) * distance
    col = light_data.get("color", [1, 1, 1])
    inten = light_data.get("intensity", 1.0)

    lt = c4d.BaseObject(RS_LIGHT_ID)
    lt.SetName(f"RS_{role.capitalize()}")
    rs_set(lt, "REDSHIFT_LIGHT_TYPE", c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA)
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_AREA_GEOMETRY",
           c4d.REDSHIFT_LIGHT_AREA_GEOMETRY_RECTANGLE)
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_COLOR",
           c4d.Vector(col[0], col[1], col[2]))
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_INTENSITY", BASE_INTENSITY * mult)
    # Relative intensity as exposure in stops: key = 1.0 -> 0 EV
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_EXPOSURE",
           math.log2(max(inten, 1e-3)))
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_AREA_SIZEX", size)
    rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_AREA_SIZEY", size)

    # Gobo (shadow pattern) mask: connect to opacity texture slot if present
    gobo = light_data.get("gobo")
    if gobo:
        rs_set(lt, "REDSHIFT_LIGHT_PHYSICAL_AREA_OPACITY_TEXTURE",
               gobo, file_path=True)

    center = c4d.Vector(0, subject_size * 0.5, 0)
    pos = pos + center
    lt.SetMg(look_at_target(pos, center))
    doc.InsertObject(lt)
    return lt


def build_set(doc, parent):
    """Hero object (sphere) at the center."""
    sphere = c4d.BaseObject(c4d.Osphere)
    sphere.SetName("Hero_Object")
    sphere[c4d.PRIM_SPHERE_RAD] = 50.0
    sphere.SetRelPos(c4d.Vector(0, 104.1716, 0))
    doc.InsertObject(sphere)
    sphere.InsertUnder(parent)


def apply_lighting(data):
    doc = c4d.documents.GetActiveDocument()
    if doc is None:
        return
    doc.StartUndo()

    if AUTO_CLEAR:
        old = doc.SearchObject(GROUP_NAME)
        if old:
            doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, old)
            old.Remove()

    subject_size, subject_exists = measure_subject(doc)

    null = c4d.BaseObject(c4d.Onull)
    null.SetName(GROUP_NAME)
    doc.InsertObject(null)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, null)

    if data.get("hdri"):
        dome = create_dome(doc, data["hdri"])
        dome.InsertUnder(null)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, dome)

    for L in data.get("lights", []):
        lt = create_area_light(doc, L, subject_size)
        lt.InsertUnder(null)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, lt)

    if BUILD_SET and not subject_exists:
        build_set(doc, null)
    print(f"[Lighting Bridge] Subject size: {subject_size:.0f} cm"
          f" ({'measured from ' + SUBJECT_NAME if subject_exists else 'fallback sphere'})")

    doc.EndUndo()
    c4d.EventAdd()
    print(f"[Lighting Bridge] Scene updated: "
          f"{len(data.get('lights', []))} lights created")


class LightingBridge(plugins.MessageData):
    def __init__(self):
        self.last_mtime = 0.0
        # Ignore a file that already exists at startup;
        # only react to updates after C4D starts.
        if os.path.exists(WATCH_FILE):
            self.last_mtime = os.path.getmtime(WATCH_FILE)

    def GetTimer(self):
        return 1000  # check every second

    def CoreMessage(self, id, bc):
        if id == c4d.MSG_TIMER:
            self.check()
        return True

    def check(self):
        try:
            if not os.path.exists(WATCH_FILE):
                return
            m = os.path.getmtime(WATCH_FILE)
            if m <= self.last_mtime:
                return
            self.last_mtime = m
            with open(WATCH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print("[Lighting Bridge] New lights.json detected -> building scene")
            apply_lighting(data)
        except Exception as e:
            print(f"[Lighting Bridge] Error: {e}")


if __name__ == "__main__":
    ok = plugins.RegisterMessagePlugin(
        id=PLUGIN_ID, str="ComfyUI Lighting Bridge",
        info=0, dat=LightingBridge())
    if ok:
        print(f"[Lighting Bridge] Watching: {WATCH_FILE}")
