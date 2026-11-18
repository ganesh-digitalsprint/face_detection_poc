# Face Mask model and evidence encoder notes

The Face Mask pipeline uses the existing CPU person, face and pose detectors. It does not use YOLO, Torch, face recognition, stored embeddings or identity labels. This change does not replace model weights.

Evidence clips are encoded by a separately launched FFmpeg executable. A build that includes `libx264` is generally distributed under the GPL; check the license terms of the actual FFmpeg build used in your deployment. The application invokes the executable as a separate process and does not link its libraries. When H.264 is unavailable, the evidence recorder uses a browser-playable WebM encoder if present and reports the selected codec through `/api/health`.
