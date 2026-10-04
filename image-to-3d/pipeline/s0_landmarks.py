"""Step 0: MediaPipe face landmarks + head pose + canonical metric face mesh (needs face_landmarker.task, libEGL)."""
import struct, numpy as np, mediapipe as mp, zipfile
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
img = mp.Image.create_from_file("photo.jpg")
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path="face_landmarker.task"), output_facial_transformation_matrixes=True,
    num_faces=1, min_face_detection_confidence=0.2, min_face_presence_confidence=0.2))
res = det.detect(img)
np.save("mp_landmarks_px.npy", np.array([[p.x, p.y, p.z] for p in res.face_landmarks[0]]) * img.width)
np.save("mp_matrix.npy", np.array(res.facial_transformation_matrixes[0]))
# canonical face mesh from the .task bundle (protobuf: field 1 mesh, 3 = vertex floats x,y,z,u,v, 4 = indices)
buf = zipfile.ZipFile("face_landmarker.task").read("geometry_pipeline_metadata_landmarks.binarypb")
def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7f) << s; s += 7
        if c < 0x80: return r, i
def fields(b):
    i = 0
    while i < len(b):
        k, i = varint(b, i); f, wt = k >> 3, k & 7
        if wt == 0: v, i = varint(b, i)
        elif wt == 5: v = struct.unpack("<f", b[i:i + 4])[0]; i += 4
        elif wt == 1: v = b[i:i + 8]; i += 8
        else: n, i = varint(b, i); v = b[i:i + n]; i += n
        yield f, wt, v
mesh = [v for f, wt, v in fields(buf) if f == 1][0]; vb, ib = [], []
for f, wt, v in fields(mesh):
    if f == 3: vb.extend([v] if wt == 5 else struct.unpack("<%df" % (len(v) // 4), v))
    if f == 4:
        if wt == 0: ib.append(v)
        else:
            j = 0
            while j < len(v): x, j = varint(v, j); ib.append(x)
np.save("canon_xyz.npy", np.array(vb).reshape(-1, 5)[:, :3]); np.save("canon_tris.npy", np.array(ib).reshape(-1, 3))
print("landmarks + pose + canonical mesh saved")
