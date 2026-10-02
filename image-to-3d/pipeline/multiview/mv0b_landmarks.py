"""Stage 0b: MediaPipe FaceLandmarker on the panels (478 points in px, z in px; plus the head pose matrix).
Only the front view is used later; the side views are printed as a pose sanity check."""
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path="face_landmarker.task"), output_facial_transformation_matrixes=True,
    num_faces=1, min_face_detection_confidence=0.2, min_face_presence_confidence=0.2))
for name in ("front", "right", "left"):
    img = mp.Image.create_from_file("out/%s.png" % name)
    res = det.detect(img)
    if not res.face_landmarks:
        print(name, ": no face"); continue
    pts = np.array([[p.x * img.width, p.y * img.height, p.z * img.width] for p in res.face_landmarks[0]])
    M = np.array(res.facial_transformation_matrixes[0]); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
    yaw = np.degrees(np.arctan2(R[0, 2], R[2, 2])); roll = np.degrees(np.arctan2(R[1, 0], R[1, 1])); pitch = np.degrees(np.arcsin(-R[1, 2]))
    print("%s: yaw %.1f pitch %.1f roll %.1f" % (name, yaw, pitch, roll))
    np.save("out/mp_%s.npy" % name, pts); np.save("out/mpM_%s.npy" % name, M)
