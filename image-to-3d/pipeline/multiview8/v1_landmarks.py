"""MediaPipe FaceLandmarker on every panel (also on 2x upscaled + mirrored copies for robustness)."""
import numpy as np, cv2, json
import mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path="face_landmarker.task"), output_facial_transformation_matrixes=True,
    num_faces=1, min_face_detection_confidence=0.15, min_face_presence_confidence=0.15))
names = ["v000", "v045", "v090", "v135", "v180", "v225", "v270", "v315"]
res_all = {}
for nm in names:
    img = cv2.imread("out/%s.png" % nm)
    best = None
    for scale in (2.0, 3.0):
        big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        mi = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(big, cv2.COLOR_BGR2RGB))
        r = det.detect(mi)
        if not r.face_landmarks: continue
        pts = np.array([[p.x * big.shape[1], p.y * big.shape[0], p.z * big.shape[1]] for p in r.face_landmarks[0]]) / scale
        M = np.array(r.facial_transformation_matrixes[0]); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
        yaw = np.degrees(np.arctan2(R[0, 2], R[2, 2])); pitch = np.degrees(np.arcsin(-R[1, 2])); roll = np.degrees(np.arctan2(R[1, 0], R[1, 1]))
        best = (pts, M, yaw, pitch, roll, scale); break
    if best is None:
        print("%s: no face" % nm); continue
    pts, M, yaw, pitch, roll, scale = best
    np.save("out/mp_%s.npy" % nm, pts); np.save("out/mpM_%s.npy" % nm, M)
    res_all[nm] = dict(yaw=float(yaw), pitch=float(pitch), roll=float(roll), scale=scale)
    print("%s: yaw %6.1f pitch %5.1f roll %5.1f  nose tip (%.0f,%.0f)  (upscale %.0fx)" % (nm, yaw, pitch, roll, pts[4, 0], pts[4, 1], scale))
json.dump(res_all, open("out/mp_pose.json", "w"), indent=1)
