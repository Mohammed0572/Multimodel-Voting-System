# Pinned face models

Run `python server/face-recognition/face_models.py` from the repository root.
The demo launcher and `make install-python` also run this installer.

YuNet and SFace come from OpenCV Zoo revision
`48b10fa505aeb51fbd127fc60a5c660040e823b7`. Filenames and SHA-256 digests are
checked in `face_models.py`; binaries are ignored by Git. Their accompanying
licenses are included here. Models are verified before the API becomes ready,
never downloaded as part of voter authentication.

SFace templates are versioned and cannot be created from old dlib vectors.
Existing voters need one new enrollment and administrator approval to use it.
Legacy vectors retain their existing recognizer until then. The demonstration
does not establish deployment-specific false-accept/false-reject rates.
